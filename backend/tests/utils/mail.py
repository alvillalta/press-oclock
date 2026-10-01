from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session

from app import crud
from app.models import Mail, MailCreate
from tests.utils.user import create_random_user
from tests.utils.utils import random_email, random_lower_string


def create_random_mail(
    db: Session,
    user_id: UUID | None = None,
    body: str | None = "A sample email body for tests.",
) -> Mail:
    if user_id is None:
        user = create_random_user(db)
        if user.id is None:
            raise ValueError("Created user has no id")
        user_id = user.id

    mail_in = MailCreate(
        subject=random_lower_string(),
        sender=random_email(),
        received_at=datetime.now(timezone.utc),
        body=body,
    )
    return crud.create_mail(session=db, mail_in=mail_in, user_id=user_id)
