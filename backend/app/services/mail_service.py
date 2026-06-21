from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session
from app.rag.chunking import ChunkingTextService
from app.rag.embeddings import ChunkingEmbeddingService

from app.core.logging import get_logger
from app.models import Mail, MailCreate, MailData
from app.crud import create_mail, create_chunks

logger = get_logger(__name__)

class MailService:
    def __init__(self, session: Session):
        self.session = session

    async def process_mail(self, mail_data: MailData, user_id: UUID) -> Mail:
        """
        Procesa un mail ya obtenido de Gmail a través de Make
        """
        logger.info(f"Processing mail")

        if isinstance(mail_data.body, str) and mail_data.body.strip():
            chunking_text_service = ChunkingTextService()
            chunks = chunking_text_service.chunk_email_body(mail_data.body)

        mail = MailCreate(
                subject=mail_data.subject,
                sender=mail_data.sender,
                date=mail_data.date or datetime.now(timezone.utc),
            )
        db_mail = create_mail(session=self.session, mail_in=mail, user_id=user_id) 

        if chunks:
            chunking_embedding_service = ChunkingEmbeddingService()
            embedded_chunks = await chunking_embedding_service.create_chunk_embeddings(chunks)

            create_chunks(session=self.session, chunks_in=embedded_chunks, mail_in=db_mail)

        return db_mail