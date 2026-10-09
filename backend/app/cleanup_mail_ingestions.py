import asyncio

from sqlmodel import Session

from app.core.db import engine
from app.core.logging import get_logger
from app.services.mail_service import MailService
from app.services.storage_cleanup_service import StorageCleanupService

logger = get_logger(__name__)


async def cleanup() -> None:
    with Session(engine) as session:
        expired_count = await MailService(session=session).cleanup_expired_ingestions()
        cleaned_count = await StorageCleanupService(session=session).process_pending()
        logger.info(
            "Mail ingestion cleanup finished: %s expired sessions, %s Storage objects",
            expired_count,
            cleaned_count,
        )


def main() -> None:
    asyncio.run(cleanup())


if __name__ == "__main__":
    main()
