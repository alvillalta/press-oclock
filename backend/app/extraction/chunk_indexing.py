from uuid import UUID

from sqlmodel import Session, col, delete

from app import crud
from app.core.logging import get_logger
from app.models import Chunk, ChunkCreate
from app.rag.chunking import ChunkingService
from app.rag.embedding import EmbeddingService

logger = get_logger(__name__)


class ChunkIndexingService:
    """Convierte texto en chunks con embeddings y reemplaza los de una source."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def index_source_text(self, *, source_id: UUID, text: str) -> None:
        embedded_chunks: list[ChunkCreate] = []
        if text.strip():
            logger.info("Embedding source text")
            chunking_service = ChunkingService()
            chunks = chunking_service.chunk_text(text)
            # Evita llamar a EmbeddingService si no hay chunks
            if chunks:
                embedding_service = EmbeddingService()
                embedded_chunks = await embedding_service.generate_chunk_embeddings(
                    chunks
                )

        try:
            self.session.exec(delete(Chunk).where(col(Chunk.source_id) == source_id))
            if embedded_chunks:
                crud.create_chunks(
                    session=self.session,
                    chunks_in=embedded_chunks,
                    source_id=source_id,
                )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
