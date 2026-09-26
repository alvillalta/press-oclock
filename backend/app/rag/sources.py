from app.models import AugmentedSourceChunksGroup, Chunk, SourceCitation


def get_sources(
    similar_chunks: list[Chunk],
    augmented_chunks: list[AugmentedSourceChunksGroup],
) -> list[SourceCitation]:
    """Create citations for retrieved chunks using their source and mail metadata."""
    metadata_by_source_id = {
        group["source_id"]: group for group in augmented_chunks
    }
    sources: list[SourceCitation] = []

    for chunk in similar_chunks:
        source_metadata = metadata_by_source_id.get(chunk.source_id)
        if source_metadata is None:
            continue

        sources.append(
            SourceCitation(
                source_id=chunk.source_id,
                origin=source_metadata["origin"],
                mail_id=source_metadata["mail_id"],
                content=chunk.content,
                subject=source_metadata["subject"],
                sender=source_metadata["sender"],
                received_at=source_metadata["received_at"],
            )
        )

    return sources
