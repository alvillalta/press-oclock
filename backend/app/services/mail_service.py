from datetime import datetime, timezone
from uuid import UUID

from app.rag.chunking import ChunkingService
from sqlmodel import Session

from app.core.logging import get_logger
from app.models import Chunk, ChunkCreate, Mail, MailCreate, MailData, Message
from app.crud import create_mail, create_chunks

logger = get_logger(__name__)

class MailService:
    def __init__(self, session: Session):
        self.session = session

    def process_mail(self, mail_data: MailData, user_id: UUID) -> Mail:
        """
        Procesa un mail ya obtenido de Gmail a través de Make
        """
        logger.info(f"Processing mail")

        chunking_service = ChunkingService()
        chunks = chunking_service.chunk_email_body(mail_data.body or "")

        mail = MailCreate(
                subject=mail_data.subject,
                sender=mail_data.sender,
                date=mail_data.date or datetime.now(timezone.utc),
            )
        db_mail = create_mail(session=self.session, mail_in=mail, user_id=user_id) 

        if chunks:
            create_chunks(session=self.session, chunks_in=chunks, mail_in=db_mail)

        return db_mail