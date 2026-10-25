import asyncio
from uuid import UUID

from sqlmodel import Session, col, delete, select

from app import crud
from app.core.logging import get_logger
from app.extraction.extraction import ExtractionError, extract_file_text
from app.extraction.indexing import TextIndexingService
from app.integrations.attachment_storage import AttachmentStorage
from app.models import Attachment, Chunk

logger = get_logger(__name__)


class AttachmentProcessingService:
    def __init__(
        self,
        session: Session,
        indexing: TextIndexingService | None = None,
        storage: AttachmentStorage | None = None,
    ) -> None:
        self.session = session
        self.indexing = indexing or TextIndexingService()
        self.storage = storage or AttachmentStorage()
        self.attachment_download_retries: int = 3

    async def process_mail_attachments(self, *, mail_id: UUID) -> None:
        """Recupera la lista de attachments y los procesa de uno en uno."""
        attachment_ids = list(
            self.session.exec(
                select(Attachment.id).where(col(Attachment.mail_id) == mail_id)
            ).all()
        )
        for attachment_id in attachment_ids:
            try:
                await self.process_attachment(attachment_id=attachment_id)
            except Exception:
                self.session.rollback()
                logger.exception(
                    "Unexpected attachment processing error for %s", attachment_id
                )

    async def process_attachment(self, *, attachment_id: UUID) -> None:
        """Orquesta la descarga, extracción e indexación de un adjunto."""
        attachment = self.session.get(Attachment, attachment_id)
        if attachment is None:
            raise LookupError("Attachment not found")

        mime_type = attachment.mime_type
        storage_path = attachment.storage_path

        try:
            content = await self._download_with_retries(storage_path)
        except Exception:
            logger.exception(
                "Attachment download failed after retries for %s", attachment_id
            )
            self._mark_failed(attachment_id)
            return

        try:
            extraction = await extract_file_text(mime_type, content)
        # Recoge distintivamente entre errores de extracción y errores inesperados
        except ExtractionError as exc:
            logger.warning(
                "Attachment text extraction failed for %s: %s", attachment_id, exc
            )
            self._mark_failed(attachment_id)
            return
        except Exception:
            logger.exception("Unexpected extraction error for %s", attachment_id)
            self._mark_failed(attachment_id)
            return

        try:
            await self.index_attachment_text(
                attachment_id=attachment_id, extraction=extraction
            )
        except Exception:
            logger.exception(
                "Attachment indexing failed after successful extraction for %s",
                attachment_id,
            )

    async def _download_with_retries(self, storage_path: str) -> bytes:
        max_attempts = max(1, self.attachment_download_retries)
        for attempt in range(1, max_attempts + 1):
            try:
                return await self.storage.download(storage_path)
            except Exception as exc:
                logger.warning(
                    "Attachment download failed (attempt %s/%s): %s",
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt == max_attempts:
                    raise
                await asyncio.sleep(attempt)
        raise RuntimeError("Attachment download failed")

    def _mark_failed(self, attachment_id: UUID) -> None:
        attachment = self.session.get(Attachment, attachment_id)
        if attachment is None:
            return
        attachment.extraction = None
        attachment.extraction_status = "failed"
        self.session.add(attachment)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            logger.exception(
                "Could not persist failed extraction status for %s", attachment_id
            )

    async def index_attachment_text(
        self, *, attachment_id: UUID, extraction: str
    ) -> None:
        attachment = self.session.get(Attachment, attachment_id)
        if attachment is None:
            raise LookupError("Attachment not found")

        source_id = attachment.source_id
        has_text = bool(extraction.strip())
        attachment.extraction = extraction if has_text else ""
        attachment.extraction_status = "completed" if has_text else "empty"
        self.session.add(attachment)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        embedded_chunks = []
        if extraction.strip():
            logger.info("Embedding attachment extraction")
            embedded_chunks = await self.indexing.embed_text(extraction)

        try:
            self.session.exec(delete(Chunk).where(col(Chunk.source_id) == source_id))
            if embedded_chunks:
                crud.create_chunks(
                    session=self.session,
                    chunks_in=embedded_chunks,
                    source_id=source_id,
                )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
