from datetime import datetime
from typing import TypeAlias
from uuid import UUID

from sqlmodel import Session, and_, col, or_, select

from app.core.logging import get_logger
from app.models import (
    AugmentedSourceChunksGroup,
    Chunk,
    Mail,
    QuestionEmbedding,
    Source,
)

logger = get_logger(__name__)


def retrieve_chunks(
    session: Session,
    embedded_question: QuestionEmbedding,
    user_id: UUID,
    chunks_limit: int,
) -> list[Chunk]:
    """
    Return the closest mail chunks belonging to the requested query.
    """
    logger.info("Retrieving similar chunks from the data base")
    
    query = (
        select(Chunk)
        .join(Source, col(Chunk.source_id) == col(Source.id))
        .join(Mail, col(Mail.source_id) == col(Source.id))
        .where(col(Mail.user_id) == user_id)
        .where(col(Source.origin) == "mail")
        .order_by(col(Chunk.embedding).op("<=>")(embedded_question))
        .limit(chunks_limit)
    )
    return list(session.exec(query).all())


ChunkPositionWindows: TypeAlias = list[
    tuple[
        UUID,  # SourceId
        int,  # StartChunkPosition
        int  # EndChunkPosition
    ]
]

def merge_windows(
    chunk_position_windows: ChunkPositionWindows,
) -> ChunkPositionWindows:
    """
    Merge overlapping chunk-position windows belonging to the same source.
    """
    logger.info("Excluding overlaping chunk position windows")

    if not chunk_position_windows:
        return []

    # Ordena la lista por source_id (puede haber un chunk con una misma posición pero en otra fuente) 
    # Y luego por el start position en la source, de esta manera se pueden fusionar ventanas en una pasada.
    ordered_windows = sorted(
        chunk_position_windows,
        key=lambda window: (window[0].int, window[1]),
    )

    # Guarda el primer elemento de la lista ordenada para no compararlo consigo mismo a continuación.
    current_source_id, current_start, current_end = ordered_windows[0]
    merged_windows: ChunkPositionWindows = []

    # Itera sobre el resto de elementos de la lista para fusionar ventanas.
    for source_id, start, end in ordered_windows[1:]:
        # Si es la misma source y solapa, amplía el final.
        if source_id == current_source_id and start <= current_end + 1:
            current_end = max(current_end, end)
            continue

        # Si no solapa, guarda la ventana acumulada y la sitúa como nueva referencia para la siguiente iteración.    
        merged_windows.append((current_source_id, current_start, current_end))
        current_source_id, current_start, current_end = source_id, start, end

    # Guarda la última ventana acumulada después de salir del bucle.
    merged_windows.append((current_source_id, current_start, current_end))
    return merged_windows


AugmentedList: TypeAlias = list[
    tuple[
        Chunk, 
        Source,
        Mail
    ]
]

ChunkWindowRetrieval: TypeAlias = dict[
    # CLAVE: (MailId, ChunkPosition) -> VALOR: Chunk
    tuple[
        UUID,  # MailId
        int  # ChunkPosition
    ], 
    Chunk
]

SourceMetadata: TypeAlias = dict[
    UUID, 
    tuple[
        str,
        UUID,
        str | None,
        str,
        datetime
    ]
]

def group_chunks(
    augmented_list: AugmentedList,
    chunk_position_windows: ChunkPositionWindows,
) -> list[AugmentedSourceChunksGroup]:
    """
    Devuelve grupos de chunks contiguos por cada chunk similar manteniendo el orden por position dentro de cada grupo.
    """
    logger.info("Grouping contiguous similar chunks while maintaining their position")
    
    by_source_and_position: ChunkWindowRetrieval = {}
    source_metadata: SourceMetadata = {}

    for chunk, source, mail in augmented_list:
        source_id = chunk.source_id
        by_source_and_position[(source_id, chunk.position)] = chunk
        source_metadata.setdefault(
            source_id,
            (
                source.origin,
                mail.id,
                mail.subject,
                mail.sender,
                mail.received_at,
            ),
        )

    grouped_chunks: list[AugmentedSourceChunksGroup] = []
    for source_id, start, end in chunk_position_windows:
        chunks_group: list[Chunk] = []
        for position in range(start, end + 1):
            chunk_at_position = by_source_and_position.get((source_id, position))
            if chunk_at_position is not None:
                chunks_group.append(chunk_at_position)
        if not chunks_group:
            continue

        origin, mail_id, subject, sender, received_at = source_metadata[source_id]
        grouped_chunks.append(
            {
                "source_id": source_id,
                "origin": origin,
                "mail_id": mail_id,
                "subject": subject,
                "sender": sender,
                "received_at": received_at,
                "chunk_list": chunks_group,
            }
        )

    return grouped_chunks


def augment_chunks(
    session: Session,
    similar_chunks: list[Chunk],
    user_id: UUID,
    chunks_range: int,
) -> list[AugmentedSourceChunksGroup]:
    """
    Load neighboring chunks and mail metadata for each matching source.
    """
    logger.info("Grouping contiguous similar chunks while maintaining their position")

    if not similar_chunks:
        return []

    chunk_position_windows = merge_windows(
        [
            (
                chunk.source_id,
                max(1, chunk.position - chunks_range),
                chunk.position + chunks_range,
            )
            for chunk in similar_chunks
        ]
    )
    conditions = [
        and_(
            col(Chunk.source_id) == source_id,
            col(Chunk.position) >= start,
            col(Chunk.position) <= end,
        )
        for source_id, start, end in chunk_position_windows
    ]

    query = (
        select(Chunk, Source, Mail)
        .join(Source, col(Chunk.source_id) == col(Source.id))
        .join(Mail, col(Mail.source_id) == col(Source.id))
        .where(col(Mail.user_id) == user_id)
        .where(col(Source.origin) == "mail")
        .where(or_(*conditions))
        .order_by(col(Chunk.source_id), col(Chunk.position))
    )
    augmented_list: AugmentedList = list(session.exec(query).all())
    return group_chunks(augmented_list, chunk_position_windows)


def merge_chunks(augmented_chunks: list[AugmentedSourceChunksGroup]) -> str:
    """Build a language-model context from mail chunks and their metadata."""
    source_blocks = []
    for grouped_source_chunks in augmented_chunks:
        joined_chunks = "\n".join(
            chunk.content for chunk in grouped_source_chunks["chunk_list"]
        )
        source_blocks.append(
            "\nCORREO\n"
            f"Source ID: {grouped_source_chunks['source_id']}\n"
            f"Origin: {grouped_source_chunks['origin']}\n"
            f"ID: {grouped_source_chunks['mail_id']}\n"
            f"Subject: {grouped_source_chunks['subject'] or '(sin asunto)'}\n"
            f"Sender: {grouped_source_chunks['sender']}\n"
            f"Received at: {grouped_source_chunks['received_at'].isoformat()}\n"
            f"Body: {joined_chunks}"
        )

    return "\n---\n".join(source_blocks)


class RetrievalAugmentationService:
    """Retrieve similar chunks and augment them with adjacent mail content."""

    def __init__(self, chunks_limit: int = 3, chunks_range: int = 1):
        self.chunks_limit = chunks_limit
        self.chunks_range = chunks_range

    def search_similar_chunks(
        self,
        session: Session,
        embedded_question: QuestionEmbedding,
        user_id: UUID,
    ) -> list[Chunk]:
        return retrieve_chunks(
            session, embedded_question, user_id, self.chunks_limit
        )

    def expand_information(
        self,
        session: Session,
        similar_chunks: list[Chunk],
        user_id: UUID,
    ) -> list[AugmentedSourceChunksGroup]:
        return augment_chunks(session, similar_chunks, user_id, self.chunks_range)

    def build_context(
        self, augmented_chunks: list[AugmentedSourceChunksGroup]
    ) -> str:
        return merge_chunks(augmented_chunks)
