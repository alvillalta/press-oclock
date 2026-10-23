from app.models import ChunkCreate
from app.rag.chunking import ChunkingService
from app.rag.embedding import EmbeddingService


class TextIndexingService:
    """Convierte texto en chunks con embeddings para indexarlo en la base de datos."""

    async def embed_text(self, content: str) -> list[ChunkCreate]:
        chunking_service = ChunkingService()
        chunks = chunking_service.chunk_text(content)
        # Evita llamar a EmbeddingService si no hay chunks
        if not chunks:
            return []
        embedding_service = EmbeddingService()
        return await embedding_service.generate_chunk_embeddings(chunks)
