import uuid

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app import crud
from app.api.deps import CurrentUser, MakeApiKeyDep, SessionDep
from app.core.config import settings
from app.core.logging import get_logger
from app.models import Mail, MailCreate, MailPublic, MailResponse, Message
from app.services.mail_service import MailService

logger = get_logger(__name__)

router = APIRouter(prefix="/mails", tags=["mails"])

@router.get("/", response_model=list[MailPublic])
def read_mails(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 50
) -> list[MailPublic]:
    """
    Retrieve mails.
    """
    if current_user.is_superuser:
        statement = (
            select(Mail).order_by(col(Mail.created_at).desc()).offset(skip).limit(limit)
        )
        mails = session.exec(statement).all()
    else:
        statement = (
            select(Mail)
            .where(Mail.user_id == current_user.id)
            .order_by(col(Mail.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        mails = session.exec(statement).all()

    return [MailPublic.model_validate(mail) for mail in mails]


@router.get("/{id}", response_model=MailResponse)
def read_mail(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> MailResponse:
    """
    Get mail by ID.
    """
    mail = session.get(Mail, id)
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")
    if (mail.user_id != current_user.id) and (not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return MailResponse.model_validate(mail)


@router.post("/", response_model=MailPublic)
async def ingest_mail(
    *, session: SessionDep, mail_in: MailCreate, _api_key: MakeApiKeyDep
) -> Mail:
    """
    Ingesta de un correo y sus embeddings dentro del sistema.
    Este flujo no es multiusuario, se resuelve a partir de la configuración con Make
    (de ahí user_id=settings.MAIL_WEBHOOK_USER_ID)
    """
    logger.info("Routing mail from external integrator")

    mail_service = MailService(session=session)
    return await mail_service.process_mail(
        mail_in=mail_in, user_id=settings.MAIL_WEBHOOK_USER_ID
    )


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
    if (mail.user_id != current_user.id) and (not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    crud.delete_mail(session=session, mail_in=mail)
    session.commit()
    return Message(message="Mail deleted successfully")
