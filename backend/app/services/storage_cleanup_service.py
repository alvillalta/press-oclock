from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.attachment_storage import AttachmentStorage
from app.models import StorageCleanup

logger = get_logger(__name__)


class StorageCleanupService:
    def __init__(
        self, 
        session: Session, 
        storage: AttachmentStorage | None = None,
        limit: int = 100,
        max_attempts: int = 3,
    ) -> None:
        self.session = session
        self.storage = storage or AttachmentStorage()
        self.limit = limit
        self.max_attempts = max_attempts

    async def cleanup_expired_ingestions(self) -> int:
        """Borra los mail_stage caducados de todos los usuarios y encola sus adjuntos para limpieza."""
        now = datetime.now(timezone.utc)
        receiving_before = now - timedelta(hours=settings.MAIL_STAGE_RETENTION_HOURS)
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

    async def process_pending(self) -> int:
        """Intenta borrar todos los storage_paths pendientes en Supabase Storage por lotes para ahorrar consumo de la API."""
        processed = 0
        #  Estas dos propiedades sirven para hacer avanzar al siguiente lote, id es importante para desempatar porque los created_at pueden repetirse
        cursor_created_at = None
        cursor_id = None
        # El bucle es infinito para procesar por lotes (limit) hasta que lo corta un break (cuando ya no queda nada)
        while True:
            # El filtro attempt_count < max_attempts excluye los venenos
            cleanup_records = crud.get_pending_storage_cleanup(
                session=self.session,
                limit=self.limit,
                max_attempts=self.max_attempts,
                after_created_at=cursor_created_at,  
                after_id=cursor_id,
            )
            if not cleanup_records:
                break

            # Captura created_at y id del último elemento de cleanup_records como variables locales antes del commit() para poder enviarlos como referencia a la consulta a db cuando se vuelva a iniciar el bucle 
            cursor_created_at = cleanup_records[-1].created_at
            cursor_id = cleanup_records[-1].id

            try:
                await self.storage.remove(
                    [record.storage_path for record in cleanup_records]
                )
            except Exception as exc:
                logger.warning(
                    "Batch removal of %s objects from Supabase Storage failed: %s",
                    len(cleanup_records),
                    exc,
                )
                # Si el lote falla, se aísla el registro veneno a registro a registro para no castigar con attempt_count al resto del mismo lote
                processed += await self._register_batch_failure(cleanup_records)
                continue

            for record in cleanup_records:
                crud.delete_storage_cleanup_record(session=self.session, cleanup_record=record)
            self.session.commit()
            processed += len(cleanup_records)
        return processed

    async def _register_batch_failure(self, cleanup_records: list[StorageCleanup]) -> int:
        """Aísla el fallo de un lote reintentando cada registro por separado."""
        removed = 0
        for record in cleanup_records:
            try:
                await self.storage.remove([record.storage_path])  # Lista de un solo elemento
            except Exception as exc:
                record.attempt_count += 1
                record.last_error = str(exc)[:1000]
                self.session.add(record)
                if record.attempt_count >= self.max_attempts:
                    logger.warning(
                        "Storage cleanup record for %s reached max attempts (%s) and is left as dead-letter: %s",
                        record.storage_path,
                        self.max_attempts,
                        record.last_error,
                    )
            # Cuando else va junto a try/except se ejecuta solo si el try terminó sin ninguna excexpción (se separan los errores de borrado en la db de borrado en Supabase Storage)
            else:  
                crud.delete_storage_cleanup_record(session=self.session, cleanup_record=record)
                removed += 1
        self.session.commit()
        return removed
