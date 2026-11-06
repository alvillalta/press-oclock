from datetime import datetime

from app.core.logging import get_logger
from app.models import AugmentedChunksGroup

logger = get_logger(__name__)


def format_augmented_context(augmented_chunk_groups: list[AugmentedChunksGroup]) -> str:
    """
    Formatea los grupos de chunks aumentados como texto legible para la generación de una respuesta por parte del agente.
    """
    logger.info("Formatting augmented chunk groups and their specific metadata")

    source_blocks: list[str] = []
    for grouped_source_chunks in augmented_chunk_groups:
        # Añade un número por cada iteración para enumerar la fuente en el prompt de abajo
        source_number = len(source_blocks) + 1

        # Une los textos de los chunks
        joined_chunks = "\n".join(
            chunk.content for chunk in grouped_source_chunks["chunk_list"]
        )

        # details se reinicia vacío cada vez que termina el bucle
        details = []
        # Bucle para recorrer las parejas CLAVE-VALOR de los distintos diccionarios details
        for details_key, details_value in grouped_source_chunks["details"].items():
            if details_value is None:
                rendered_value = "(sin datos)"
            elif isinstance(details_value, datetime):
                rendered_value = details_value.isoformat()
            else:
                rendered_value = str(details_value)
            # Escribe el metadato en texto común legible
            details.append(f"{details_key.replace('_', ' ').title()}: {rendered_value}")
        # Une los textos de los metadatos
        details_block = "\n".join(details)
        if details_block:
            details_block = f"{details_block}\n"

        source_blocks.append(
            f"\nFUENTE {source_number}\n"
            f"Origin: {grouped_source_chunks['origin']}\n"
            f"{details_block}"
            f"Content: {joined_chunks}"
        )

    return "\n---\n".join(source_blocks)
