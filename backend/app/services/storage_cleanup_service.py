from sqlmodel import Session

from app import crud
from app.core.logging import get_logger
from app.integrations.attachment_storage import AttachmentStorage

logger = get_logger(__name__)


class StorageCleanupService:
    def __init__(
        self, 
        session: Session, 
        storage: AttachmentStorage | None = None,
        limit: int = 100
    ) -> None:
        self.session = session
        self.storage = storage or AttachmentStorage()
        self.limit = limit

    async def process_pending(self) -> int:
        processed = 0
        while True:
            cleanup_records = crud.get_pending_storage_cleanup(
                session=self.session, limit=self.limit
            )
            if not cleanup_records:
                return processed

            try:
                await self.storage.remove(
                    [record.storage_path for record in cleanup_records]
                )
            except Exception as exc:
                for record in cleanup_records:
                    record.attempt_count += 1
                    record.last_error = str(exc)[:1000]
                    self.session.add(record)
                self.session.commit()
                logger.exception(
                    "Failed to remove %s objects from Supabase Storage",
                    len(cleanup_records),
                )
                return processed

            for record in cleanup_records:
                crud.delete_storage_cleanup(session=self.session, cleanup=record)
            self.session.commit()
            processed += len(cleanup_records)
