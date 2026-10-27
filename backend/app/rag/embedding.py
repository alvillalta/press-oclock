from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.openai_client import get_embeddings_model
from app.models import ChunkBase, ChunkCreate, QuestionBase, QuestionEmbedding

logger = get_logger(__name__)


# Levanta el error si las dimensiones del embedding no coinciden con las esperadas de manera que no bloquee cada operación que necesite embeddings
# Se tiene que declarar aparte porque no hay un error tipificado para ello
class EmbeddingResponseError(ValueError):
    """Respuesta de embeddings incompatible con la configuración esperada."""


def _validate_embedding_dimensions(embedding: list[float]) -> list[float]:
    if len(embedding) != settings.EMBEDDING_DIMENSIONS:
        raise EmbeddingResponseError(
            f"Expected an embedding with {settings.EMBEDDING_DIMENSIONS} dimensions, "
            f"got {len(embedding)}."
        )
    return embedding


class EmbeddingService:
    """Servicio para generar embeddings."""

    def __init__(self, batch_size: int = 50, overlaped_characters: int = 100):
        self.batch_size = batch_size
        self.overlaped_characters = overlaped_characters

    async def generate_chunk_embeddings(
        self,
        chunks: list[ChunkBase],  # Cada chunk: {"position": ..., "content": ...}
    ) -> list[ChunkCreate]:
        """
        Crea embeddings para una lista de chunks.
        """
        logger.info("Embedding a list of chunks through an AI model")

        results: list[ChunkCreate] = []

        for index in range(0, len(chunks), self.batch_size):
            batch = chunks[index : index + self.batch_size]
            inputs = [chunk.content for chunk in batch]

            try:
                embeddings = await get_embeddings_model().aembed_documents(inputs)
            except Exception as exc:
                logger.warning("Chunk embedding batch failed: %s", exc)
                raise RuntimeError("Chunks embedding failed") from exc

            if len(batch) != len(embeddings):
                # embeddings es la lista de vectores que devuelve el LLM por cada por cada chunk del lote
                raise EmbeddingResponseError("Mismatch between number of chunks and embeddings returned")

            for chunk, chunk_embedding in zip(batch, embeddings, strict=True):
                embedding = _validate_embedding_dimensions(chunk_embedding)

                # Quita el ovelap del texto de los chunks antes de guardar en la db
                if chunk.position == 1:
                    chunk_content_to_store = chunk.content
                else:
                    if len(chunk.content) <= self.overlaped_characters:
                        continue
                    chunk_content_to_store = chunk.content[self.overlaped_characters:]
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
        self, question: QuestionBase
    ) -> QuestionEmbedding:
        """
        Crea un embedding para una pregunta.
        """
        logger.info("Embedding a question through an AI model")

        try:
            embedding = await get_embeddings_model().aembed_query(question)
        except Exception as exc:
            logger.warning("Question embedding failed: %s", exc)
            raise RuntimeError("Question embedding failed") from exc

        embedded_question = _validate_embedding_dimensions(embedding)

        return embedded_question
