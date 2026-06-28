from typing import List

from app.core.logging import get_logger
from app.models import AugmentedMailChunksGroup, Chunk, Sources

logger = get_logger(__name__)

def get_sources(
    similar_chunks: List[Chunk], 
    augmented_chunks: List[AugmentedMailChunksGroup]
) -> List[Sources]:
    """
    Combina los chunks recuperados originalmente con los metadatos de su correo asociado.
    """
    # Indice de metadatos por mail_id usando augmented_chunks
    by_augmented_chunks = {}

    for information_group in augmented_chunks:
        mail_id = information_group["mail_id"]
        by_augmented_chunks[mail_id] = {
            "subject": information_group["subject"],
            "sender": information_group["sender"],
            "date": information_group["date"],
        }

    # chunk_text desde similar_chunks + metadata desde augmented_chunks
    sources: List[Sources] = []

    for chunk in similar_chunks:

        mail_metadata = by_augmented_chunks.get(chunk.mail_id)

        sources.append(
            Sources(
                mail_id=chunk.mail_id,
                chunk_text=chunk.chunk_text,
                subject=mail_metadata["subject"] if mail_metadata else None,
                sender=mail_metadata["sender"],
                date=mail_metadata["date"]
            )
        )

    return sources