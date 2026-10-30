from uuid import UUID

from sqlmodel import Session

from app.core.logging import get_logger
from app.extraction.chunk_indexing import ChunkIndexingService
from app.models import Mail

logger = get_logger(__name__)


class MailProcessingService:
    def __init__(
        self,
        session: Session,
        indexing: ChunkIndexingService | None = None,
    ) -> None:
        self.session = session
        self.indexing = indexing or ChunkIndexingService(session=session)

    async def process_mail_body(self, *, mail_id: UUID) -> None:
        """Indexa el body del mail persistido, si contiene texto."""
        mail = self.session.get(Mail, mail_id)
        if mail is None:
            raise LookupError("Mail not found")

        body = mail.body or ""  # body puede guardarse como None en db y strip() no acepta ese tipo
        if not body.strip():
            return

        await self.indexing.index_source_text(
            source_id=mail.source_id,
            text=body,
        )
