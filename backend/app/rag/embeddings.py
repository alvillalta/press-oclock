import logging 
import asyncio
from typing import List

from openai import AsyncOpenAI
from app.core.config import settings
from app.models import ChunkCreate, ChunkBase

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY
)

async def generate_embeddings(
    chunks: List[ChunkBase],  # cada chunk: {"chunk_index": ..., "chunk_text": ...}
    batch_size,
    max_retries,
    wait_seconds
) -> List[ChunkCreate]:
    """
    Crea embeddings para una lista de chunks.
    """
    results: List[ChunkCreate] = []

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        inputs = [chunk.chunk_text for chunk in batch]

        for attempt in range(1, max_retries + 1):
            try:
                response = await client.embeddings.create(
                    model=settings.EMBEDDING_MODEL,
                    input=inputs,
                )
                break
            except Exception as exc:
                logger.warning("Embedding batch failed (attempt %s/%s): %s", attempt, max_retries, exc)
                if attempt == max_retries:
                    raise
                await asyncio.sleep(wait_seconds * attempt)

        if len(batch) != len(response.data):
            raise ValueError("Mismatch between number of chunks and embeddings returned")
        
        for chunk, datum in zip(batch, response.data):
            results.append(
                ChunkCreate(
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.chunk_text,
                    embedding=datum.embedding,
                )
            )

    return results

class ChunkingEmbeddingService:
    """Servicio para generar embeddings y agregarlos a los chunks."""
    
    def __init__(self, batch_size: int = 100, max_retries: int = 3, wait_seconds: int = 2):
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.wait_seconds = wait_seconds
    
    async def create_chunk_embeddings(self, chunks: List[ChunkBase]) -> List[ChunkCreate]:
        """Crea embeddings para una lista de chunks."""
        return await generate_embeddings(chunks, self.batch_size, self.max_retries, self.wait_seconds)
    
    