from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session

from app.core.logging import get_logger
from app.models import Mail, MailCreate, MailData
from app.crud import create_mail

logger = get_logger(__name__)

class MailService:
    def __init__(self, session: Session):
        self.session = session

    def process_mail(self, mail_data: MailData, user_id: UUID) -> Mail:
        """
        Procesa un mail ya obtenido de Gmail a través de Make
        """
        logger.info(f"Processing mail")

        mail_in = MailCreate(
            subject=mail_data.subject,
            sender=mail_data.sender,
            body=mail_data.body,
            date=mail_data.date or datetime.now(timezone.utc),
        )

        return create_mail(session=self.session, mail_in=mail_in, user_id=user_id) 