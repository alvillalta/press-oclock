from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session

from app.core.logging import get_logger
from app.models import Mail, MailCreate
from app.crud import create_mail

logger = get_logger(__name__)

class MailService:
    def __init__(self, session: Session):
        self.session = session

    def process_mail(self, user_id: UUID, mail_data: dict) -> Mail:
        """
        Procesa un mail ya obtenido de cualquier fuente.
        """
        logger.info(f"Processing mail from {mail_data.get('from')}")

        mail_in = MailCreate(
            title=mail_data.get("subject"),
            source_email=mail_data.get("from"),  # sender
            content=mail_data.get("body"),
            received_at=mail_data.get("received_at")
            or datetime.now(timezone.utc),
        )

        return create_mail(session=self.session, mail_in=mail_in, user_id=user_id) 