import asyncio
import mimetypes
from datetime import datetime, timedelta, timezone
from typing import TypeAlias
from pathlib import PurePath
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, select

from app import crud
from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.attachment_storage import AttachmentStorage
from app.models import (
    Attachment,
    AttachmentStage,
    AttachmentStagePublic,
    Chunk,
    ChunkCreate,
    Mail,
    MailCreate,
    MailStage,
    MailStageCreate,
    MailStagePublic,
)
from app.rag.chunking import ChunkingService
from app.rag.embedding import EmbeddingService

logger = get_logger(__name__)

SUPPORTED_ATTACHMENT_TYPES: dict[str, tuple[str, ...]] = {
    # Soporta tuplas con extensión variable
    ".pdf": ("application/pdf",),
    ".txt": ("text/plain",),
    ".md": ("text/markdown", "text/x-markdown", "text/plain"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}
# Valores por defecto que pueden llegar o si llega vacío
GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}


class MailService:
    def __init__(
        self, session: Session, storage: AttachmentStorage | None = None
    ):
        self.session = session
        self.storage = storage or AttachmentStorage()


    MimeTypeValidation: TypeAlias = tuple[
        str | None,  # normalized_mime_type
        str | None  # unsupported_reason
    ]

    def _get_or_create_attachment_mime_type(
        self, filename: str, mime_type: str
    ) -> MimeTypeValidation:
        """
        Validación de tipo de un adjunto
        """
        # Infiere el tipo de archivo a partir de la extensión de la ruta del archivo
        # PurePath sirve para interpretar el string que se le pase como ruta de archivo
        # .suffix es una propiedad de lectura de PurePath para sacar .pdf, .docx, etc.
        extension = PurePath(filename).suffix.lower()
        accepted_mime_types = SUPPORTED_ATTACHMENT_TYPES.get(extension)
        if accepted_mime_types is None:
            return None, "Unsupported file type"
        
        # Normalización del tipo, si es genérico se fía de la extensión
        # Se hace split porque un Content-Type puede llevar parámetros después del tipo
        normalized_mime_type = mime_type.split(";", maxsplit=1)[0].strip().lower()
        if normalized_mime_type in GENERIC_MIME_TYPES:
            guessed_mime_type = mimetypes.guess_type(filename)[0]
            if guessed_mime_type in accepted_mime_types:
                normalized_mime_type = guessed_mime_type
            else:
                normalized_mime_type = accepted_mime_types[0]
        if normalized_mime_type not in accepted_mime_types:
            return None, "Unsupported file type"
        return normalized_mime_type, None

    # @staticmethod es como una función normal que vive dentro de la clase (no método porque no necesita acceder a datos de dicha clase)
    # Estos @staticmethod sirven para construir el mapa de identificación de las instancias stage únicamente  
    @staticmethod
    def _public_mail_stage(stage: MailStage) -> MailStagePublic:
        return MailStagePublic(
            ingestion_id=stage.id,
            external_id=stage.external_id,
            status=stage.status,
            mail_id=stage.mail_id,
            result_summary=stage.result_summary,
        )

    @staticmethod
    def _public_attachment_stage(stage: AttachmentStage) -> AttachmentStagePublic:
        return AttachmentStagePublic(
            external_id=stage.external_id,
            status=stage.status,
            reason=stage.reason,
            attempt_count=stage.attempt_count,
            size_bytes=stage.size_bytes,
        )

    def start_ingestion(
        self, *, mail_in: MailStageCreate, user_id: UUID
    ) -> MailStagePublic:
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
            return self._public_mail_stage(existing_stage)

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
                return self._public_mail_stage(existing_stage)
            raise
        self.session.refresh(stage)
        return self._public_mail_stage(stage)

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
        measured_size: int | None = None,
    ) -> AttachmentStagePublic:
        # Trae la instancia de MailStage correspondiente al adjunto
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
            return self._public_attachment_stage(existing_attachment_stage)

        size_bytes = measured_size if measured_size is not None else len(content)

        # Construcción de attachment_stage si no existe (podría tener status pendiente si no)
        attachment_stage = existing_attachment_stage
        if attachment_stage is None:
            # PurePath interpreta el string como ruta pura
            # .name toma solo el último componente de la ruta del archivo y trunca a no más de 255 caracteres
            safe_filename = PurePath(filename.replace("\\", "/")).name[:255] 
            attachment_stage = AttachmentStage(
                mail_stage_id=ingestion_id,
                external_id=external_id,
                filename=safe_filename or "attachment",
                mime_type=(mime_type or "application/octet-stream")[:255],
                size_bytes=size_bytes,
                status="pending",
            )
            mail_stage.total_size_bytes += size_bytes

        # Normalización del tipo de archivo, cada variable declarada recibe en orden cada elemento de la tupla (aunque venga de un reintento)
        normalized_mime_type, unsupported_reason = self._get_or_create_attachment_mime_type(
            attachment_stage.filename, mime_type
        )

        # Comprobaciones de tamaño
        total_too_large = (
            mail_stage.total_size_bytes > settings.MAIL_ATTACHMENT_MAX_BYTES
            or size_bytes > settings.MAIL_ATTACHMENT_MAX_BYTES
            or oversize
        )
        # Omitir attachment_stage si no cumple las condiciones anteriores
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
            return self._public_attachment_stage(attachment_stage)

        # Genera ruta del adjunto en Supabase Storage 
        # Comprobación para evitar errores silenciosos a la hora de asignar storage_path
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
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
        attachment_stage_id = attachment_stage.id
        storage_path = attachment_stage.storage_path or ""
        stored_mime_type = attachment_stage.mime_type

        # CUAL ES EL PAPEL DE LAST_ERROR????
        last_error: Exception | None = None
        max_attempts = settings.MAIL_ATTACHMENT_STORAGE_RETRIES
        for attempt in range(1, max_attempts + 1):
            try:
                # Invoca el método upload de la clase AttachmentStorage
                await self.storage.upload(
                    storage_path,
                    content,
                    stored_mime_type,
                )
                # Query directa a la db a través de la clave primaria
                # Después de .commit() o .rollback() se expira el objeto, la consulta se va a hacer sí o sí ya sea de forma implícita recogiendo una variable de las que habíamos declarado o de forma explícita llamando a db
                attachment_stage = self.session.get(
                    AttachmentStage, attachment_stage_id
                )
                if attachment_stage is None:
                    raise RuntimeError("Attachment stage disappeared during upload")
                attachment_stage.status = "stored"
                attachment_stage.reason = None
                attachment_stage.attempt_count = attempt
                self.session.add(attachment_stage)
                self.session.commit()
                return self._public_attachment_stage(attachment_stage)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Attachment upload failed (attempt %s/%s): %s",
                    attempt,
                    max_attempts,
                    exc,
                )
                # SI HACE ROLLBACK EL OBJETO DE LA DB SE CIERRA Y SE REINTENTA A PARTIR DE FORMA PEREZOSA
                self.session.rollback()  # Por si la excepción se produce después de las nuevas asignaciones del try
                if attempt < max_attempts:
                    await asyncio.sleep(attempt)

        # Continuación del bucle si agota todos los intentos de subida:
        attachment_stage = self.session.get(AttachmentStage, attachment_stage_id)
        if attachment_stage is None:
            raise RuntimeError("Attachment stage disappeared during upload") from last_error
        attachment_stage.status = "omitted"
        attachment_stage.reason = "storage_upload_failed"
        attachment_stage.attempt_count = max_attempts
        self.session.add(attachment_stage)
        if attachment_stage.storage_path:
            # Limpieza el caso de que hubiera quedado algún objeto huérfano en Supabase tras fallos en la subida
            crud.create_storage_cleanup(
                session=self.session, storage_path=attachment_stage.storage_path
            )
        self.session.commit()
        return self._public_attachment_stage(attachment_stage)

    # CAMBIAR SACAR FUERA DE LA CLASE CUANDO SE HAGA LA REORGANIZACIÓN
    async def _embed_text(self, content: str) -> list[ChunkCreate]:
            chunking_service = ChunkingService()
            chunks = chunking_service.chunk_content(content)
            # Evita llamar a EmbeddingService si no hay chunks
            if not chunks:
                return []
            embedding_service = EmbeddingService()
            return await embedding_service.create_chunk_embeddings(chunks)


    async def process_mail(self, mail_in: MailCreate, user_id: UUID) -> Mail:
        """
        Procesa un mail obtenido vía webhook.
        """
        logger.info("Persisting mail and attachments")

        embedded_chunks = []
        if isinstance(mail_in.body, str) and mail_in.body.strip():
            logger.info("Embedding mail body")
            embedded_chunks = await self._embed_text(mail_in.body)

        try:
            mail = crud.create_mail(
                session=self.session,
                mail_in=mail_in,
                user_id=user_id,
                commit=False,
            )
            if embedded_chunks:
                crud.create_chunks(
                    session=self.session,
                    chunks_in=embedded_chunks,
                    source_id=mail.source_id,
                    commit=False,
                )
            self.session.commit()
            self.session.refresh(mail)
        except Exception:
            self.session.rollback()
            raise

        logger.info("Mail Service OK")
        return mail

    async def index_attachment_text(
        self, *, attachment_id: UUID, extraction: str
    ) -> Attachment:
        """Persist MarkItDown text and index it under the attachment's own source."""
        attachment = self.session.get(Attachment, attachment_id)
        if attachment is None:
            raise LookupError("Attachment not found")

        embedded_chunks = []
        if extraction.strip():
            logger.info("Embedding attachment extraction")
            embedded_chunks = await self._embed_text(extraction)

        try:
            # Borra porque si fallase el proceso de MarkItDown y hubiese que reprocesar elimina los chunks viejos
            self.session.exec(
                delete(Chunk).where(col(Chunk.source_id) == attachment.source_id)
            )
            attachment.extraction = extraction
            self.session.add(attachment)
            if embedded_chunks:
                crud.create_chunks(
                    session=self.session,
                    chunks_in=embedded_chunks,
                    source_id=attachment.source_id,
                    commit=False,
                )
            self.session.commit()
            self.session.refresh(attachment)
        except Exception:
            self.session.rollback()
            raise
        return attachment

    async def finalize_ingestion(self, ingestion_id: UUID, user_id: UUID) -> Mail:
        # Primera consulta al stage para preparar datos y comprobar que no haya adjuntos todavía pendientes
        stage = self.session.exec(
            select(MailStage).where(
                # ingestion_id recibido como argumento realmente es el mail_stage_id generado al principio de todo
                MailStage.id == ingestion_id, MailStage.user_id == user_id
            )
        ).first()
        if stage is None:
            raise LookupError("Mail ingestion not found")
        if stage.status == "completed" and stage.mail_id is not None:
            completed_mail = self.session.get(Mail, stage.mail_id)
            if completed_mail is not None:
                return completed_mail
        if stage.status != "receiving":
            raise ValueError("Mail ingestion cannot be finalized")

        mail_in = MailCreate(
            subject=stage.subject,
            sender=stage.sender,
            received_at=stage.received_at,
            body=stage.body,
        )
        user_id = stage.user_id
        external_id = stage.external_id
        staged_attachments = list(
            self.session.exec(
                select(AttachmentStage).where(
                    col(AttachmentStage.mail_stage_id) == ingestion_id
                )
            ).all()
        )
        if any(attachment.status == "pending" for attachment in staged_attachments):
            raise ValueError("Mail ingestion has attachments still being uploaded")
        # .rollback() aquí cierra la transacción de lectura de datos que se ha abierto para consultar el Stage
        # TIENE SENTIDO ASEGURAR ESTA LLAMADA A DB ANTES DE LOS CHUNKS
        self.session.rollback()

        embedded_chunks = []
        if isinstance(mail_in.body, str) and mail_in.body.strip():
            embedded_chunks = await self._embed_text(mail_in.body)

        try:
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
                    self.session.rollback()
                    return completed_mail
            if stage.status != "receiving":
                raise ValueError("Mail ingestion cannot be finalized")

            staged_attachments = list(
                self.session.exec(
                    select(AttachmentStage).where(
                        col(AttachmentStage.mail_stage_id) == ingestion_id
                    )
                ).all()
            )
            # Lista los pendientes para validar error de que todavía no se puede hacer la ingesta
            pending_attachments = [
                attachment
                for attachment in staged_attachments
                if attachment.status == "pending"
            ]
            if pending_attachments:
                raise ValueError("Mail ingestion has attachments still being uploaded")

            # Lista solo con la condición de "stored", los "ommited" se quedan fuera
            stored_attachments = [
                attachment
                for attachment in staged_attachments
                if attachment.status == "stored" and attachment.storage_path
            ]
            db_mail = crud.create_mail(
                session=self.session,
                mail_in=mail_in,
                user_id=user_id,
                external_id=external_id,
                commit=False,
            )
            for staged_attachment in stored_attachments:
                # Comprobación reforzada para asegurar el tipo str de Attachment (en AttachmentStage era str | None)
                assert staged_attachment.storage_path is not None, "Attachment no persistible si falta la ruta de guardado"
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

            if embedded_chunks:
                crud.create_chunks(
                    session=self.session,
                    chunks_in=embedded_chunks,
                    source_id=db_mail.source_id,
                    commit=False,
                )

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
            return db_mail
        except IntegrityError:
            self.session.rollback()
            existing_mail = self.session.exec(
                select(Mail).where(
                    Mail.user_id == user_id, Mail.external_id == external_id
                )
            ).first()
            if existing_mail is not None:
                return existing_mail
            raise
        except Exception:
            self.session.rollback()
            raise

    # Limpieza automática 
    async def cleanup_expired_ingestions(self) -> int:
        now = datetime.now(timezone.utc)
        receiving_before = now - timedelta(hours=settings.MAIL_STAGE_TTL_HOURS)
        completed_before = now - timedelta(days=settings.MAIL_STAGE_RETENTION_DAYS)
        stages = crud.get_expired_mail_stages(
            session=self.session,
            receiving_before=receiving_before,
            completed_before=completed_before,
        )
        for stage in stages:
            crud.delete_mail_stage(session=self.session, stage=stage)
        self.session.commit()
        return len(stages)
