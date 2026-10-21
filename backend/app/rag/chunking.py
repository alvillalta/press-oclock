from app.core.logging import get_logger
from app.models import ChunkBase

logger = get_logger(__name__)


class ChunkingService:
    """Servicio para procesar y dividir contenido de correos en chunks."""

    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str) -> list[ChunkBase]:
        """
        Descompone un texto en chunks con solapamiento.
        Descompone el body de un correo en chunks.
        """
        logger.info("Chunking text")

        chunks: list[ChunkBase] = []
        start = 0

        while start < len(text):
            # Toma chunk_size caracteres desde la posición actual
            end = start + self.chunk_size
            content = text[start:end]
            position = len(chunks) + 1
            chunk = ChunkBase(
                content=content,
                position=position,
            )
            chunks.append(chunk)

            # Mueve el inicio para el siguiente chunk, considerando el overlap
            start += self.chunk_size - self.overlap

        return chunks
