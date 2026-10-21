import asyncio

from sqlmodel import Session

from app.core.db import engine
from app.core.logging import get_logger
from app.services.storage_cleanup_service import StorageCleanupService

logger = get_logger(__name__)


# La activación del borrado automático no funciona actualmente (solo manualmente al ejecutar este archivo en el backend). Está indicado para que en un futuro se pueda programar de forma periódica en producción
async def cleanup() -> None:
    with Session(engine) as session:
        # Primero borra todos los mail_stage caducados (encola sus adjuntos) y luego limpia Supabase Storage
        service = StorageCleanupService(session=session)
        expired_count = await service.cleanup_expired_ingestions()
        cleaned_count = await service.process_pending()
        logger.info(
            "Mail ingestion cleanup finished: %s expired sessions, %s Storage objects",
            expired_count,
            cleaned_count,
        )


def main() -> None:
    asyncio.run(cleanup())


if __name__ == "__main__":
    main()
