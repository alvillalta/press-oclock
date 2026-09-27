import asyncio
from typing import List

from app.core.config import settings
from app.core.logging import get_logger
from app.core.openai_client import get_openai_client
from app.models import ChunkBase, ChunkCreate, QuestionBase, QuestionEmbedding

logger = get_logger(__name__)

client = get_openai_client()


def validate_embedding_dimensions(embedding: list[float]) -> list[float]:
    if len(embedding) != settings.EMBEDDING_DIMENSIONS:
        raise ValueError("Expected an embedding with a different number of dimensions.")
    return embedding


async def generate_chunk_embeddings(
    chunks: List[ChunkBase],  # cada chunk: {"position": ..., "content": ...}
    batch_size,
    max_retries,
    wait_seconds,
    overlaped_characters
) -> List[ChunkCreate]:
    """
    Crea embeddings para una lista de chunks.
    """
    logger.info("Embedding a list of chunks through an AI model")

    results: List[ChunkCreate] = []

    for index in range(0, len(chunks), batch_size):
        batch = chunks[index : index + batch_size]
        inputs = [chunk.content for chunk in batch]

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
            #response.data es la lista de embeddings que devuelve OpenAI por cada chunk del batch
            raise ValueError("Mismatch between number of chunks and embeddings returned")
        
        for chunk, datum in zip(batch, response.data, strict=True):
            embedding = validate_embedding_dimensions(datum.embedding)

            # Quita el ovelap del texto de los chunks antes de guardar en la db
            if chunk.position == 1:
                chunk_content_to_store = chunk.content
            else:
                if len(chunk.content) <= overlaped_characters:
                    continue
                chunk_content_to_store = chunk.content[overlaped_characters:]
            if not chunk_content_to_store.strip():
                continue

            results.append(
                ChunkCreate(
                    position=chunk.position,
                    content=chunk_content_to_store,
                    embedding=embedding,
                )
            )

    return results


async def generate_question_embedding(
    question: QuestionBase,
    max_retries,
    wait_seconds
) -> QuestionEmbedding:
    """
    Crea un embedding para una pregunta.
    """
    logger.info("Embedding a question through an AI model")
    
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=question,
            )
            break
        except Exception as exc:
            logger.warning("Embedding batch failed (attempt %s/%s): %s", attempt, max_retries, exc)
            if attempt == max_retries:
                raise
            await asyncio.sleep(wait_seconds * attempt)
    
    embedded_question = validate_embedding_dimensions(response.data[0].embedding)

    return embedded_question


class EmbeddingService:
    """Servicio para generar embeddings."""
    
    def __init__(self, batch_size: int = 50, max_retries: int = 3, wait_seconds: int = 2, overlaped_characters: int = 100):
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.wait_seconds = wait_seconds
        self.overlaped_characters = overlaped_characters  
    
    async def create_chunk_embeddings(self, chunks: List[ChunkBase]) -> List[ChunkCreate]:
        """Crea embeddings para una lista de chunks."""
        return await generate_chunk_embeddings(chunks, self.batch_size, self.max_retries, self.wait_seconds, self.overlaped_characters)
    
    async def create_question_embedding(self, question: QuestionBase) -> QuestionEmbedding:
        """Crea un embedding para una pregunta."""
        return await generate_question_embedding(question, self.max_retries, self.wait_seconds)
