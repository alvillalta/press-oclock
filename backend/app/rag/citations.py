from app.core.logging import get_logger
from app.models import AugmentedChunksGroup, Chunk, SourceCitation

logger = get_logger(__name__)


def get_citations(
        similar_chunks: list[Chunk],
        augmented_chunks: list[AugmentedChunksGroup],
    ) -> list[SourceCitation]:
        """
        Crea citas utilizando los chunks originales recuperados y los metadatos asociados a la fuente.
        """
        logger.info("Creating source citations")

        # Crea un diccionario con CLAVE: source_id -> VALOR: instancia de grupo de chunks
        metadata_by_source_id = {
            group["source_id"]: group for group in augmented_chunks
        }
        citations: list[SourceCitation] = []

        for chunk in similar_chunks:
            # Por cada chunk original recupera la instancia de grupo de chunks
            source_chunks_group = metadata_by_source_id.get(chunk.source_id)
            if source_chunks_group is None:
                continue

            citations.append(
                SourceCitation(
                    source_id=chunk.source_id,
                    origin=source_chunks_group["origin"],
                    content=chunk.content,
                    details=source_chunks_group["details"],
                )
            )

        return citations


class CitationService:
    """Servicio para construir las citas de las fuentes de una respuesta."""

    def get_citations_metadata(
            self,
            similar_chunks: list[Chunk],
            augmented_chunks: list[AugmentedChunksGroup],
        ) -> list[SourceCitation]:
            return get_citations(similar_chunks, augmented_chunks)

