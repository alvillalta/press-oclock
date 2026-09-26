from uuid import UUID

from sqlmodel import Session

from app import crud
from app.core.logging import get_logger
from app.models import Mail, MailCreate, MailData
from app.rag.chunking import ChunkingService
from app.rag.embeddings import EmbeddingService

logger = get_logger(__name__)

class MailService:
    def __init__(self, session: Session):
        self.session = session

    async def process_mail(self, mail_data: MailData, user_id: UUID) -> Mail:
        """
        Procesa un mail ya obtenido de Gmail a través de Make
        """
        logger.info("Persisting mail")

        mail = MailCreate(
            subject=mail_data.subject,
            sender=mail_data.sender,
            received_at=mail_data.received_at,
            body=mail_data.body,
        )
        db_mail = crud.create_mail(
            session=self.session, mail_in=mail, user_id=user_id
        )

        if isinstance(mail_data.body, str) and mail_data.body.strip():
            logger.info("Persisting chunks")
            chunking_service = ChunkingService()
            chunks = chunking_service.chunk_content(mail_data.body)
        
            if chunks:
                embedding_service = EmbeddingService()
                embedded_chunks = await embedding_service.create_chunk_embeddings(chunks)

                if embedded_chunks:
                    crud.create_chunks(
                        session=self.session,
                        chunks_in=embedded_chunks,
                        source_id=db_mail.source_id,
                    )

        logger.info("Mail Service OK")

        return db_mail
