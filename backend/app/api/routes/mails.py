import uuid
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Depends
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import Mail, MailData, MailUpdate, Message
from app.services.mail_service import MailService
from app.core.logging import get_logger

router = APIRouter(prefix="/mails", tags=["mails"])

logger = get_logger(__name__)

@router.get("/", response_model=list[Mail])
def read_mails(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve mails.
    """
    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Mail)
        count = session.exec(count_statement).one()
        statement = (
            select(Mail).order_by(col(Mail.created_at).desc()).offset(skip).limit(limit)
        )
        mails = session.exec(statement).all()
    else:
        count_statement = (
            select(func.count())
            .select_from(Mail)
            .where(Mail.user_id == current_user.id)
        )
        count = session.exec(count_statement).one()
        statement = (
            select(Mail)
            .where(Mail.user_id == current_user.id)
            .order_by(col(Mail.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        mails = session.exec(statement).all()

    return mails


@router.get("/{id}", response_model=Mail)
def read_mail(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Get mail by ID.
    """
    mail = session.get(Mail, id)
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")
    if not current_user.is_superuser and (mail.user_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return mail


@router.post("/", response_model=Mail)
async def ingest_mail(
    *, session: SessionDep, mail_data: MailData
) -> Mail:
    """
    Ingest a new mail directly into the system.
    """
    if settings.MAIL_WEBHOOK_USER_ID is None:
        raise HTTPException(
            status_code=500,
            detail="MAIL_WEBHOOK_USER_ID must be configured for the webhook user",
        )

    logger.info(f"Receiving mail from {mail_data.sender}")
    mail_service = MailService(session=session)

    return await mail_service.process_mail(
        mail_data=mail_data, user_id=settings.MAIL_WEBHOOK_USER_ID
    )


@router.put("/{id}", response_model=Mail)
def update_mail(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    mail_in: MailUpdate,
) -> Any:
    """
    Update a mail.
    """
    mail = session.get(Mail, id)
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")
    if not current_user.is_superuser and (mail.user_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    update_dict = mail_in.model_dump(exclude_unset=True)
    mail.sqlmodel_update(update_dict)
    session.add(mail)
    session.commit()
    session.refresh(mail)
    return mail


@router.delete("/{id}")
def delete_mail(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Delete a mail.
    """
    mail = session.get(Mail, id)
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")
    if not current_user.is_superuser and (mail.user_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    session.delete(mail)
    session.commit()
    return Message(message="Mail deleted successfully")
