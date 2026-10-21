from uuid import UUID

from sqlmodel import Session, col, delete

from app import crud
from app.core.logging import get_logger
from app.ingestion.indexing import TextIndexingService
from app.models import Attachment, Chunk

logger = get_logger(__name__)


class AttachmentProcessingService:
    """Procesa el texto de un adjunto y lo indexa bajo su propia source."""

    def __init__(
        self, session: Session, indexing: TextIndexingService | None = None
    ) -> None:
        self.session = session
        self.indexing = indexing or TextIndexingService()

    async def index_attachment_text(
        self, *, attachment_id: UUID, extraction: str
    ) -> Attachment:
        """Persist MarkItDown text and index it under the attachment's own source."""
        attachment = self.session.get(Attachment, attachment_id)
        if attachment is None:
            raise LookupError("Attachment not found")

        embedded_chunks = []
        if extraction.strip():
            logger.info("Embedding attachment extraction")
            embedded_chunks = await self.indexing.embed_text(extraction)

        try:
            # Borra porque si fallase el proceso de MarkItDown y hubiese que reprocesar elimina los chunks viejos
            self.session.exec(
                delete(Chunk).where(col(Chunk.source_id) == attachment.source_id)
            )
            attachment.extraction = extraction
            self.session.add(attachment)
            if embedded_chunks:
                crud.create_chunks(
                    session=self.session,
                    chunks_in=embedded_chunks,
                    source_id=attachment.source_id,
                )
            self.session.commit()
            self.session.refresh(attachment)
        except Exception:
            self.session.rollback()
            raise
        return attachment
