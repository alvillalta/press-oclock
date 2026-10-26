import asyncio
from collections.abc import AsyncIterable
from pathlib import PurePath
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app import crud
from app.core.config import settings
from app.core.logging import get_logger
from app.extraction.attachment_processing import AttachmentProcessingService
from app.extraction.mail_processing import MailProcessingService
from app.extraction.mime_types import get_attachment_mime_type
from app.integrations.attachment_storage import AttachmentStorage
from app.models import (
    Attachment,
    AttachmentStage,
    AttachmentStagePublic,
    AttachmentUpload,
    FinalizedMailResult,
    Mail,
    MailCreate,
    MailStage,
    MailStageCreate,
    MailStagePublic,
)

logger = get_logger(__name__)

# Levanta el error si fallan las suposiciones internas del flujo de la aplicación sobre algo que esperaba que no está
# Se tiene que declarar aparte porque no hay un error tipificado para ello
class MailIngestionError(Exception):
    """Error de consistencia interna durante la ingesta de un correo."""


# Construyen el mapa de identificación de las instancias stage únicamente
def public_mail_stage(stage: MailStage) -> MailStagePublic:
    return MailStagePublic(
        ingestion_id=stage.id,
        external_id=stage.external_id,
        status=stage.status,
        mail_id=stage.mail_id,
        result_summary=stage.result_summary,
    )


def public_attachment_stage(stage: AttachmentStage) -> AttachmentStagePublic:
    return AttachmentStagePublic(
        external_id=stage.external_id,
        status=stage.status,
        reason=stage.reason,
        attempt_count=stage.attempt_count,
        size_bytes=stage.size_bytes,
    )


class MailIngestionService:
    def __init__(
        self, session: Session, storage: AttachmentStorage | None = None
    ):
        self.session = session
        self.storage = storage or AttachmentStorage()
        self.attachment_storage_retries: int = 3

    async def ingest_mail(
        self,
        *,
        mail_in: MailStageCreate,
        user_id: UUID,
        attachments: AsyncIterable[AttachmentUpload],
    ) -> MailStagePublic:
        """Orquesta la ingesta completa de un correo y todos sus adjuntos."""
        logger.info("Orchestrating mail and attachments ingestion")

        stage = self.start_ingestion(mail_in=mail_in, user_id=user_id)
        if stage.status == "completed":
            # Si se trata de un correo ya persistido no repite el registro
            return stage
        if stage.ingestion_id is None:
            raise MailIngestionError("Mail ingestion has no id")

        ingestion_id = stage.ingestion_id  # Es el id del objeto mail_stage

        # Solicita los adjuntos uno a uno al cargador asíncrono de mails.py hasta terminar de procesarlos todos
        async for attachment in attachments:
            await self.stage_attachment(
                ingestion_id=ingestion_id,
                user_id=user_id,
                external_id=attachment.external_id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                content=attachment.content,
                oversize=attachment.oversize,
                measured_size=attachment.measured_size,
            )

        finalized_mail_result = await self.finalize_ingestion(
            ingestion_id=ingestion_id,
            user_id=user_id,
        )
        # Evalúa finalized_in_this call para procesar únicamente la rama ligada que ha persistido los datos, evitando problemas de concurrencia y de repetición de mails que ya hubiesen sido completados
        if finalized_mail_result.finalized_in_this_call:
            try:
                await MailProcessingService(session=self.session).process_mail_body(
                    mail_id=finalized_mail_result.mail_id
                )
            # Levanta el error si el mail no existe tras finalizar la ingesta
            except LookupError as exc:
                raise MailIngestionError(
                    "Mail not found after finalizing ingestion"
                ) from exc
            except Exception:
                # Registra el error pero no vuelve a lanzarlo con raise porque no es bloqueante del éxito del endpoint, lo mismo con attachments
                logger.exception("Mail body indexing failed after mail finalization")

            try:
                await AttachmentProcessingService(
                    session=self.session,
                    storage=self.storage,
                ).process_mail_attachments(mail_id=finalized_mail_result.mail_id)
            except Exception:
                logger.exception("Attachment extraction indexing failed after mail finalization")

        # Devuelve MailStagePublic
        finalized_stage = self.session.get(MailStage, ingestion_id)
        if finalized_stage is None:
            raise MailIngestionError(
                "Mail ingestion stage disappeared after finalizing"
            )
        return public_mail_stage(finalized_stage)

    def start_ingestion(
        self, *, mail_in: MailStageCreate, user_id: UUID
    ) -> MailStagePublic:
        logger.info("Creating mail stage")

        existing_mail = self.session.exec(
            select(Mail).where(
                Mail.user_id == user_id,
                Mail.external_id == mail_in.external_id
            )
        ).first()
        if existing_mail is not None:
            return MailStagePublic(
                external_id=mail_in.external_id,
                status="completed",
                mail_id=existing_mail.id,
                result_summary={"already_processed": True},
            )

        existing_stage = self.session.exec(
            select(MailStage).where(
                MailStage.user_id == user_id,
                MailStage.external_id == mail_in.external_id,
            )
        ).first()
        if existing_stage is not None:
            return public_mail_stage(existing_stage)

        # Si no existe Mail ni MailStage en la db, construye la nueva instancia de MailStage
        stage = MailStage.model_validate(
            mail_in,
            update={"user_id": user_id, "status": "receiving"},
        )
        self.session.add(stage)
        try:
            self.session.commit()
        except IntegrityError:
            # .rollback() vuelve a comprobar existing_stage en la db por si hubiese efectos de concurrencia
            self.session.rollback()
            existing_stage = self.session.exec(
                select(MailStage).where(
                    MailStage.user_id == user_id,
                    MailStage.external_id == mail_in.external_id,
                )
            ).first()
            if existing_stage is not None:
                return public_mail_stage(existing_stage)
            raise  # Un raise sin argumento vuelve a lanzar la excepción que capturó el except
        self.session.refresh(stage)
        return public_mail_stage(stage)

    async def stage_attachment(
        self,
        *,
        ingestion_id: UUID,
        user_id: UUID,
        external_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        oversize: bool = False,
        measured_size: int
    ) -> AttachmentStagePublic:
        logger.info("Creating an attachment stage")
        # Trae la instancia de MailStage a la que asociar el adjunto
        mail_stage = self.session.exec(
            select(MailStage)
            .where(MailStage.id == ingestion_id, MailStage.user_id == user_id)
            # with_for_update() bloquea a las filas seleccionadas de recibir updates hasta que termina la transacción (commit/rollback)
            .with_for_update()
        ).first()
        if mail_stage is None:
            raise LookupError("Mail ingestion not found")
        if mail_stage.status != "receiving":
            raise ValueError("Mail ingestion is already finalized")

        # Comprueba que no exista el attachment_stage en la db
        existing_attachment_stage = self.session.exec(
            select(AttachmentStage).where(
                AttachmentStage.mail_stage_id == ingestion_id,
                AttachmentStage.external_id == external_id,
            )
        ).first()
        if existing_attachment_stage is not None and existing_attachment_stage.status != "pending":
            return public_attachment_stage(existing_attachment_stage)

        # Construcción de attachment_stage si no existe (podría tener status pendiente si no)
        attachment_stage = existing_attachment_stage
        if attachment_stage is None:
            # PurePath interpreta el string como ruta pura
            # .name toma solo el último componente de la ruta del archivo y trunca a no más de 255 caracteres
            safe_filename = PurePath(filename.replace("\\", "/")).name[:255]
            attachment_stage = AttachmentStage(
                mail_stage_id=ingestion_id,
                external_id=external_id,
                filename=safe_filename or "attachment",  # Se guarda así pero las comprobaciones del tipo de archivo se hacen con el filename que entra como argumento en la función
                mime_type=(mime_type or "application/octet-stream")[:255],
                size_bytes=measured_size,
                status="pending",
            )
            mail_stage.total_size_bytes += measured_size

        # Normalización del tipo de archivo, cada variable declarada recibe en orden cada elemento de la tupla (aunque venga de un reintento)
        normalized_mime_type, unsupported_reason = get_attachment_mime_type(
            filename, mime_type
        )

        # Comprobaciones de tamaño
        total_too_large = (
            mail_stage.total_size_bytes > settings.MAIL_ATTACHMENT_MAX_BYTES
            or oversize
        )
        # Omite attachment_stage si no cumple las condiciones anteriores
        if unsupported_reason is not None or total_too_large:
            attachment_stage.status = "omitted"
            attachment_stage.reason = (
                "Total size limit exceeded" if total_too_large else unsupported_reason
            )
            attachment_stage.attempt_count = 0
            mail_stage.total_size_bytes -= attachment_stage.size_bytes
            self.session.add(attachment_stage)
            self.session.add(mail_stage)
            self.session.commit()
            return public_attachment_stage(attachment_stage)

        # Genera una ruta para el adjunto que apunta a Supabase Storage
        # Comprobación para evitar errores silenciosos a la hora de asignar storage_path
        if not settings.SUPABASE_STORAGE_URL or not settings.SUPABASE_STORAGE_KEY:
            raise RuntimeError("Supabase Storage is not configured")

        if attachment_stage.storage_path is None:
            attachment_stage.storage_path = (
                f"mails/{ingestion_id}/attachments/{attachment_stage.id}"
            )

        # Aquí también entraría un attachment_state que vienese de un reintento con status "pending"
        attachment_stage.mime_type = normalized_mime_type
        self.session.add(attachment_stage)
        self.session.add(mail_stage)
        self.session.commit()
        # Después de .commit() o .rollback() se expira el objeto, la consulta se va a hacer sí o sí ya sea de forma perezosa recogiendo una variable de las que habíamos declarado o de forma explícita llamando a db
        self.session.refresh(attachment_stage)
        attachment_stage_id = attachment_stage.id
        storage_path = attachment_stage.storage_path
        stored_mime_type = attachment_stage.mime_type

        max_attempts = self.attachment_storage_retries
        upload_succeeded = False
        for attempt in range(1, max_attempts + 1):
            try:
                # Invoca la subida a Supabase Storage en un bloque de reintentos
                logger.info("Uploading the attachment file to database storage")
                await self.storage.upload(
                    storage_path,
                    content,
                    stored_mime_type,
                )
                upload_succeeded = True
                break
            except Exception as exc:
                logger.warning(
                    "Attachment upload failed (attempt %s/%s): %s",
                    attempt,
                    max_attempts,
                    exc,
                )
                self.session.rollback()
                if attempt < max_attempts:
                    await asyncio.sleep(attempt)

        # Continuación si se agotan todos los intentos de subida
        if not upload_succeeded:
            attachment_stage = self.session.get(AttachmentStage, attachment_stage_id)
            if attachment_stage is None:
                # La subida pudo dejar un objeto huérfano: se encola su limpieza antes de propagar la inconsistencia
                crud.create_storage_cleanup(
                    session=self.session, storage_path=storage_path
                )
                self.session.commit()
                raise MailIngestionError("Attachment stage disappeared during upload")
            attachment_stage.status = "omitted"
            attachment_stage.reason = "storage_upload_failed"
            attachment_stage.attempt_count = max_attempts
            self.session.add(attachment_stage)
            if attachment_stage.storage_path:
                # Se guarda en StorageCleanup para limpiarlo posteriormente en el caso de que hubiera quedado algún objeto huérfano en Supabase tras agotar los fallos en la subida
                logger.info("Indexing the attachment stage object for storage cleanup")
                crud.create_storage_cleanup(
                    session=self.session, storage_path=attachment_stage.storage_path
                )
            self.session.commit()
            return public_attachment_stage(attachment_stage)

        # La subida terminó bien: la persistencia queda fuera del bloque de reintentos
        # Se refresca la sesión para no leer una instancia cacheada si el stage desapareció durante la subida
        self.session.expire_all()
        attachment_stage = self.session.get(AttachmentStage, attachment_stage_id)
        if attachment_stage is None:
            # El stage podría borrarse de forma muy improbable, por ejemplo, si el servidor se estropease y el servicio de cleanup limpiase el stage al volver, si se borrase el mail padre, etc.
            # Pero la subida ya se completó, así que se encola el objeto para no dejarlo huérfano en Supabase
            crud.create_storage_cleanup(
                session=self.session, storage_path=storage_path
            )
            self.session.commit()
            raise MailIngestionError("Attachment stage disappeared during upload")
        attachment_stage.status = "stored"
        attachment_stage.reason = None
        attachment_stage.attempt_count = attempt
        self.session.add(attachment_stage)
        self.session.commit()
        return public_attachment_stage(attachment_stage)

    async def finalize_ingestion(
        self, ingestion_id: UUID, user_id: UUID
    ) -> FinalizedMailResult:
        logger.info("Setting up mail and attachments from staging")

        try:
            # with_for_update() bloquea la escritura del stage durante la validación y la persistencia para evitar finalizaciones concurrentes
            stage = self.session.exec(
                select(MailStage)
                .where(
                    MailStage.id == ingestion_id,
                    MailStage.user_id == user_id,
                )
                .with_for_update()
            ).first()
            if stage is None:
                raise LookupError("Mail ingestion not found")
            if stage.status == "completed" and stage.mail_id is not None:
                completed_mail = self.session.get(Mail, stage.mail_id)
                if completed_mail is not None:
                    self.session.rollback()  # Libera el bloqueo si ya se ha completado
                    # Correo ya persistido por lo que no se repite su procesamiento de texto
                    return FinalizedMailResult(
                        mail_id=completed_mail.id, finalized_in_this_call=False
                    )
            if stage.status != "receiving":
                raise ValueError("Mail ingestion cannot be finalized")

            external_id = stage.external_id
            mail_in = MailCreate(
                subject=stage.subject,
                sender=stage.sender,
                received_at=stage.received_at,
                body=stage.body,
                external_id=external_id,
            )
            staged_attachments = list(
                self.session.exec(
                    select(AttachmentStage).where(
                        col(AttachmentStage.mail_stage_id) == ingestion_id
                    )
                ).all()
            )
            # Lista si hay attachment pendientes para que si existen se detenga la ingesta
            pending_attachments = [
                attachment
                for attachment in staged_attachments
                if attachment.status == "pending"
            ]
            if pending_attachments:
                raise ValueError("Mail ingestion has attachments still being uploaded")

            # Lista solo con la condición de "stored", los "omitted" se quedan fuera
            stored_attachments = [
                attachment
                for attachment in staged_attachments
                if attachment.status == "stored" and attachment.storage_path
            ]
            db_mail = crud.create_mail(
                session=self.session,
                mail_in=mail_in,
                user_id=user_id,
            )
            for staged_attachment in stored_attachments:
                attachment_source = crud.create_source(
                    session=self.session, origin="attachment", user_id=user_id
                )
                db_attachment = Attachment(
                    mail_id=db_mail.id,
                    source_id=attachment_source.id,
                    filename=staged_attachment.filename,
                    mime_type=staged_attachment.mime_type,
                    storage_path=staged_attachment.storage_path,
                    extraction=None,
                )
                # Los objetos de las relaciones siempre se añaden después de la asignación principal
                db_attachment.source = attachment_source
                db_attachment.mail = db_mail
                self.session.add(db_attachment)

            omitted_attachments = [
                {
                    "external_id": attachment.external_id,
                    "reason": attachment.reason,
                }
                for attachment in staged_attachments
                if attachment.status == "omitted"
            ]
            stage.status = "completed"
            stage.mail_id = db_mail.id  # Establece la relación Foreign Key con el Mail recién creado
            # Mete los attachments omitidos en el resumen de mail_stage y borra todos los attachment_stage
            stage.result_summary = {
                "stored_count": len(stored_attachments),
                "omitted_count": len(omitted_attachments),
                "omitted": omitted_attachments,
            }
            self.session.add(stage)
            for staged_attachment in staged_attachments:
                self.session.delete(staged_attachment)
            self.session.commit()
            self.session.refresh(db_mail)
            logger.info("Mail ingestion OK")
            return FinalizedMailResult(
                mail_id=db_mail.id, finalized_in_this_call=True
            )
        except IntegrityError:
            # Salta si se está creando un correo duplicado para evitar concurrencia (UniqueConstraint de Mail al hacer flush())
            self.session.rollback()
            existing_mail = self.session.exec(
                select(Mail).where(
                    Mail.user_id == user_id, Mail.external_id == external_id
                )
            ).first()
            # Esta rama no es la que ha persistido por lo que no es la dueña de los efectos posteriores, de ahí finalized_in_this_call=False
            if existing_mail is not None:
                return FinalizedMailResult(
                    mail_id=existing_mail.id, finalized_in_this_call=False
                )
            raise
        except Exception:
            self.session.rollback()
            raise
