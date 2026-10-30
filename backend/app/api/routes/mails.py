import json
import uuid
from collections.abc import AsyncIterator

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
    AttachmentUpload,
    Mail,
    MailPublic,
    MailResponse,
    MailStageCreate,
    MailStagePublic,
    Message,
)
from app.rag.embedding import EmbeddingResponseError
from app.services.mail_ingestion_service import (
    MailIngestionError,
    MailIngestionService,
)
from app.services.storage_cleanup_service import StorageCleanupService

logger = get_logger(__name__)

router = APIRouter(prefix="/mails", tags=["mails"])


def _read_attachment_metadata(
    session: SessionDep, mail_id: uuid.UUID
) -> list[AttachmentPublic]:
    """Obtiene metadatos reducidos para pintar en el front al devolver AttachmentPublic."""
    attachments = session.exec(
        select(Attachment)
        .where(Attachment.mail_id == mail_id)
        .order_by(col(Attachment.created_at))
    ).all()
    return [
        AttachmentPublic.model_validate(attachment) for attachment in attachments
    ]


async def _read_upload(upload: UploadFile) -> tuple[bytes, int, bool]:
    """Lee un archivo de subida por partes para no cargar en memoria un archivo arbitrariamente grande."""
    max_bytes = settings.MAIL_ATTACHMENT_MAX_BYTES
    size_bytes = 0
    content = bytearray()  # Buffer (Acumulador de memoria temporal)
    too_large = False
    # := operador condicional para asignar la variable a la vez que evalúa la condición (funciona mientras el chunk sea True)
    while chunk := await upload.read(64 * 1024):  # Lee hasta 64 KB por iteración
        size_bytes += len(chunk)
        if size_bytes <= max_bytes:
            content.extend(chunk)  # Guarda el chunk en el buffer
        else:
            too_large = True
            content.clear()
    # El bucle sigue leyendo el archivo hasta el final para reportar el tamaño real del archivo
    return bytes(content), size_bytes, too_large


@router.get("/", response_model=list[MailPublic])
def read_mails(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 50
) -> list[MailPublic]:
    """
    Trae una lista de correos y un booleano para indicar si tienen adjuntos
    """
    has_attachments = select(Attachment.id).where(Attachment.mail_id == Mail.id).exists()
    if current_user.is_superuser:
        statement = (
            # Hace una consulta anidada a través de la variable has_attachments como segundo parámetro de la selección
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
        # Asigna a la clave has_attachments de cada correo MailPublic el booleano determinado
        # "has_files" es el parámetro iterador para el segundo elemento seleccionado en la consulta
        MailPublic.model_validate(mail, update={"has_attachments": bool(has_files)})
        for mail, has_files in mail_rows
    ]


@router.post(
    "/ingest-mail", response_model=MailStagePublic, operation_id="ingestMail"
)
async def ingest_mail(
    *,
    session: SessionDep,
    # Form(..., ...) sirve para indicar al endpoint que espera un campo de formulario, en este caso llamado mail, ... lo hace obligatorio
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
    # File es como Form pero indica que el valor que recibe puede ser binario
    # Se tiene que enviar en un formulario aparte porque multipart/form-data de HTTP no acepta más de un campo cuando se envía un archivo
    files: list[UploadFile] = File(default=[]),  
    _api_key: MakeApiKeyDep,
) -> MailStagePublic:
    """
    Ingesta síncrona de un correo y todos sus adjuntos en una única petición.

    Make envía el correo y sus archivos juntos. El backend sube los adjuntos y
    persiste el correo (y los adjuntos que se hayan guardado) antes de responder.
    """
    logger.info("Routing mail and attachments from external integrator")

    try:
        mail_in = MailStageCreate.model_validate_json(mail)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        raw_external_ids = json.loads(attachment_external_ids)  # Parsea el JSON que viene como string de HTTP y lo convierte en una lista de Python
    except json.JSONDecodeError:  # Recoge el error si no es un JSON válido
        raise HTTPException(
            status_code=422,
            detail="attachment_external_ids must be a JSON array of strings",
        )
    if not isinstance(raw_external_ids, list) or not all(  # devuelve True solo si la expresión es verdadera para todos los elementos
        isinstance(external_id, str) and 1 <= len(external_id) <= 1024
        for external_id in raw_external_ids
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "attachment_external_ids must be a JSON array of strings "
                "between 1 and 1024 characters"
            ),
        )
    if len(raw_external_ids) != len(files):
        raise HTTPException(
            status_code=422,
            detail="attachment_external_ids must have the same length as files",
        )

    webhook_user_id = settings.MAIL_WEBHOOK_USER_ID

    # Cargador asíncrono de cada adjunto para irlos procesando de uno en uno, yield envía a MailIngestionService y pone en pausa el bucle for hasta que vuelve a tener luz verde por parte del servicio de ingestión
    # A través de esta iteración asíncrona evita cargar en memoria los bytes de todos los archivos de una tacada
    async def iter_attachments() -> AsyncIterator[AttachmentUpload]:  # Indica que la lista de AttachmentUpload se consume de forma asíncrona
        for external_id, upload in zip(raw_external_ids, files, strict=True):  
            content, size_bytes, too_large = await _read_upload(upload)  # Extrae los datos del archivo adjunto en una tupla
            yield AttachmentUpload(  # yield es como un return pero simplemente pausa la ejecución de la función en vez de finalizarla
                external_id=external_id,
                filename=upload.filename or "attachment",
                mime_type=upload.content_type or "",
                content=content,
                oversize=too_large,
                measured_size=size_bytes,
            )

    mail_service = MailIngestionService(session=session)
    # Llama al orquestador e intenta devolver MailStagePublic después de persistir Mail y Attachments
    try:
        return await mail_service.ingest_mail(
            mail_in=mail_in,
            user_id=webhook_user_id,
            attachments=iter_attachments(),
        )
    except MailIngestionError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except EmbeddingResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/{id}", response_model=MailResponse)
def read_mail(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> MailResponse:
    """
    Recupera un correo por ID así como los metadatos esenciales de sus adjuntos.
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
            download_filename=attachment.filename if download else None,  # El cliente frontend pasa download como True cuando llama al endpoint
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        logger.exception("Could not create an attachment signed URL")
        raise HTTPException(status_code=502, detail="Could not access attachment storage")
    return AttachmentSignedUrl(url=url, expires_in=storage.expires_in)


@router.get(
    "/{mail_id}/attachments/{attachment_id}/text",
    response_class=PlainTextResponse,  # Clase de FastAPI específica para archivos de texto: Content-Type: text/plain; charset=utf-8
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
        content = await AttachmentStorage().download(attachment.storage_path)  # Descarga los binarios
        text_content = content.decode("utf-8-sig")  # Convierte los bytes en str usando el códec "utf-8-sig"
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
    Borra un correo.
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
