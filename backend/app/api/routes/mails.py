import json
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlmodel import col, select

from app import crud
from app.api.deps import CurrentUser, MakeApiKeyDep, SessionDep
from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.attachment_storage import AttachmentStorage
from app.models import (
    Attachment,
    AttachmentPublic,
    AttachmentSignedUrl,
    Mail,
    MailPublic,
    MailResponse,
    MailStage,
    MailStageCreate,
    MailStagePublic,
    Message,
)
from app.services.mail_service import MailService
from app.services.storage_cleanup_service import StorageCleanupService

logger = get_logger(__name__)

router = APIRouter(prefix="/mails", tags=["mails"])


def _read_attachment_metadata(
    session: SessionDep, mail_id: uuid.UUID
) -> list[AttachmentPublic]:
    attachments = session.exec(
        select(Attachment)
        .where(Attachment.mail_id == mail_id)
        .order_by(col(Attachment.created_at))
    ).all()
    return [
        AttachmentPublic.model_validate(attachment) for attachment in attachments
    ]


async def _read_upload(upload: UploadFile) -> tuple[bytes, int, bool]:
    max_bytes = settings.MAIL_ATTACHMENT_MAX_BYTES
    size_bytes = 0
    content = bytearray()
    too_large = False
    while chunk := await upload.read(64 * 1024):
        size_bytes += len(chunk)
        if size_bytes <= max_bytes:
            content.extend(chunk)
        else:
            too_large = True
            content.clear()
    return bytes(content), size_bytes, too_large

@router.get("/", response_model=list[MailPublic])
def read_mails(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 50
) -> list[MailPublic]:
    """
    Retrieve mails.
    """
    # Comprueba si en el correo existe algún adjunto para determinar el booleano que necesita el front
    has_attachments = select(Attachment.id).where(Attachment.mail_id == Mail.id).exists()
    if current_user.is_superuser:
        statement = (
            # Selecciona las instancias de Mails y si existen adjuntos correspondientes a cada una de ellas a través de la consulta anidada de has_attachments
            select(Mail, has_attachments.label("has_attachments"))
            .order_by(col(Mail.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        mail_rows = session.exec(statement).all()
    else:
        statement = (
            select(Mail, has_attachments.label("has_attachments"))
            .where(Mail.user_id == current_user.id)
            .order_by(col(Mail.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        mail_rows = session.exec(statement).all()

    return [
        # Asigna a la clave has_attachments de MailPublic el booleano determinado
        # "has_files" es el parámetro iterador para el segundo elemento seleccionado en la consulta
        MailPublic.model_validate(mail, update={"has_attachments": bool(has_files)})
        for mail, has_files in mail_rows
    ]


@router.post(
    "/ingest", response_model=MailStagePublic, operation_id="ingestMail"
)
async def ingest_mail(
    *,
    session: SessionDep,
    mail: str = Form(
        ...,
        description=(
            "JSON con los metadatos del correo, validado como MailStageCreate: "
            "external_id, sender, received_at, subject y body."
        ),
    ),
    attachment_external_ids: str = Form(
        default="[]",
        description=(
            "JSON con un identificador externo estable por adjunto, en el mismo "
            "orden que los archivos enviados en el campo 'files'."
        ),
    ),
    files: list[UploadFile] = File(default=[]),
    _api_key: MakeApiKeyDep,
) -> MailStagePublic:
    """
    Ingesta síncrona de un correo y todos sus adjuntos en una única petición.

    Make envía el correo y sus archivos juntos. El backend sube los adjuntos y
    persiste el correo (y los adjuntos que se hayan guardado) antes de responder.

    Ejemplo de petición multipart:
    - mail: {"external_id": "gmail-1", "sender": "a@b.com", "received_at": "...",
      "subject": "Asunto", "body": "Cuerpo"}
    - attachment_external_ids: ["gmail-attachment-1"]
    - files: brief.pdf
    """
    logger.info("Routing mail and attachments from external integrator")

    try:
        mail_in = MailStageCreate.model_validate_json(mail)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        raw_external_ids = json.loads(attachment_external_ids)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=422,
            detail="attachment_external_ids must be a JSON array of strings",
        )
    if not isinstance(raw_external_ids, list) or not all(
        isinstance(external_id, str) and external_id for external_id in raw_external_ids
    ):
        raise HTTPException(
            status_code=422,
            detail="attachment_external_ids must be a JSON array of non-empty strings",
        )
    if len(raw_external_ids) != len(files):
        raise HTTPException(
            status_code=422,
            detail="attachment_external_ids must have the same length as files",
        )

    mail_service = MailService(session=session)
    webhook_user_id = settings.MAIL_WEBHOOK_USER_ID

    stage = mail_service.start_ingestion(mail_in=mail_in, user_id=webhook_user_id)
    if stage.status == "completed":
        # Petición repetida de un correo ya persistido: no se duplican registros
        return stage
    if stage.ingestion_id is None:
        raise HTTPException(status_code=500, detail="Mail ingestion has no id")

    ingestion_id = stage.ingestion_id
    try:
        for external_id, upload in zip(raw_external_ids, files, strict=True):
            content, size_bytes, too_large = await _read_upload(upload)
            await mail_service.stage_attachment(
                ingestion_id=ingestion_id,
                user_id=webhook_user_id,
                external_id=external_id,
                # REPASAR SI SE REALIZA LA VALIDACIÓN SIN NOMBRE O DE STRING VACÍO MÁS ADELANTE
                filename=upload.filename or "attachment",
                mime_type=upload.content_type or "",
                content=content,
                oversize=too_large,
                measured_size=size_bytes,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        await mail_service.finalize_ingestion(
            ingestion_id=ingestion_id,
            user_id=webhook_user_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # DEVUELVE MAILSTAGE POR EL RESUMEN PERO TIENE SENTIDO COMO RESPUESTA DEL ENDPOINT?
    finalized_stage = session.get(MailStage, ingestion_id)
    if finalized_stage is None:
        raise HTTPException(
            status_code=500, detail="Mail ingestion stage disappeared after finalizing"
        )
    return MailService._public_mail_stage(finalized_stage)


@router.get("/{id}", response_model=MailResponse)
def read_mail(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> MailResponse:
    """
    Recupera un correo por ID así como sus adjuntos.
    """
    mail = session.get(Mail, id)
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")
    if (mail.user_id != current_user.id) and (not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    attachments = _read_attachment_metadata(session, mail.id)
    return MailResponse.model_validate(
        # model_validate parte de la instancia de mail recuperada y añade las clave-valor que faltan para ajustarse al modelo MailResponse
        mail,
        update={
            "has_attachments": bool(attachments),
            "attachments": attachments,
        },
    )


@router.get(
    "/{mail_id}/attachments/{attachment_id}/signed-url",
    response_model=AttachmentSignedUrl,
    operation_id="getMailAttachmentSignedUrl",
)
async def read_attachment_signed_url(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    mail_id: uuid.UUID,
    attachment_id: uuid.UUID,
    download: bool = False,
) -> AttachmentSignedUrl:
    mail = session.get(Mail, mail_id)
    if mail is None:
        raise HTTPException(status_code=404, detail="Mail not found")
    if mail.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    attachment = session.exec(
        select(Attachment).where(
            Attachment.id == attachment_id, Attachment.mail_id == mail_id
        )
    ).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    storage = AttachmentStorage()
    try:
        url = await storage.create_signed_url(
            attachment.storage_path,
            download_filename=attachment.filename if download else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        logger.exception("Could not create an attachment signed URL")
        raise HTTPException(status_code=502, detail="Could not access attachment storage")
    return AttachmentSignedUrl(url=url, expires_in=storage.expires_in)


@router.get(
    "/{mail_id}/attachments/{attachment_id}/text",
    response_class=PlainTextResponse,
    operation_id="readMailAttachmentText",
)
async def read_text_attachment(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    mail_id: uuid.UUID,
    attachment_id: uuid.UUID,
) -> PlainTextResponse:
    mail = session.get(Mail, mail_id)
    if mail is None:
        raise HTTPException(status_code=404, detail="Mail not found")
    if mail.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    attachment = session.exec(
        select(Attachment).where(
            Attachment.id == attachment_id, Attachment.mail_id == mail_id
        )
    ).first()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if not attachment.filename.lower().endswith(".txt"):
        raise HTTPException(status_code=415, detail="Only TXT attachments can be previewed")

    try:
        content = await AttachmentStorage().download(attachment.storage_path)
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="TXT attachment is not valid UTF-8")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        logger.exception("Could not read a TXT attachment from Storage")
        raise HTTPException(status_code=502, detail="Could not access attachment storage")
    return PlainTextResponse(text_content, media_type="text/plain; charset=utf-8")


@router.delete("/{id}")
async def delete_mail(
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
    await StorageCleanupService(session=session).process_pending()
    return Message(message="Mail deleted successfully")
