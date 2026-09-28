from datetime import datetime
from typing import TypeAlias
from uuid import UUID

from sqlmodel import Session, and_, col, or_, select

from app.core.logging import get_logger
from app.models import (
    AugmentedChunksGroup,
    Chunk,
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
    Recupera los chunks más similares de las fuentes que pertenecen al usuario.
    """
    logger.info("Retrieving similar chunks from the data base")
    
    query = (
        select(Chunk)
        .join(Source, col(Chunk.source_id) == col(Source.id))
        .where(col(Source.user_id) == user_id)
        .order_by(col(Chunk.embedding).op("<=>")(embedded_question))
        .limit(chunks_limit)
    )
    return list(session.exec(query).all())


# Lista de tuplas
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
    Fusiona las posiciones de chunks de una misma fuente que se solapan.
    """
    logger.info("Merging overlaping chunk position windows")

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


# Lista de tuplas de Chunks aumentados y su Source asociada
AugmentedList: TypeAlias = list[
    tuple[
        Chunk,
        Source,
    ]
]

# Diccionario de clave tupla y valor diccionario
ChunkWindowRetrieval: TypeAlias = dict[
    # CLAVE: (SourceId, ChunkPosition) -> VALOR: Instancia de Chunk
    tuple[
        UUID,  # SourceId
        int  # ChunkPosition
    ],
    Chunk
]

def group_chunks(
    augmented_list: AugmentedList,
    chunk_position_windows: ChunkPositionWindows,
) -> list[AugmentedChunksGroup]:
    """
    Devuelve grupos de instancias de chunks contiguos según la fuente.
    """
    logger.info("Grouping contiguous chunk instances")
    
    by_source_and_position: ChunkWindowRetrieval = {}
    sources_by_id: dict[UUID, Source] = {}
    # CLAVE: SourceId -> VALOR: Instancia de Source

    for chunk, source in augmented_list:
        source_id = chunk.source_id
        # Recupera el chunk a partir de la ventana que se le dé sin recorrer la lista O(1)
        by_source_and_position[(source_id, chunk.position)] = chunk
        # Mete source_id como clave del diccionario asignando su correspondiente instancia de Source
        sources_by_id[source_id] = source

    grouped_chunks: list[AugmentedChunksGroup] = []
    # Primer bucle para recorrer las tuplas de las ventanas
    for source_id, start, end in chunk_position_windows:
        chunks_group: list[Chunk] = []
        # Segundo bucle anidado para recorrer los chunks contiguos de UNA ventana
        for position in range(start, end + 1):
            chunk_at_position = by_source_and_position.get((source_id, position))
            if chunk_at_position is not None:
                chunks_group.append(chunk_at_position)
        if not chunks_group:
            continue

        # Recupera la instancia de Source DENTRO DEL PRIMER BUCLE para acceder a su "origin"
        grouped_source = sources_by_id.get(source_id)
        if grouped_source is None:
            continue

        # Añade el grupo a list[AugmentedSourceGroup] DENTRO DEL PRIMER BUCLE
        grouped_chunks.append(
            {
                "source_id": source_id,
                "origin": grouped_source.origin,
                "details": {},
                "chunk_list": chunks_group,
            }
        )

    return grouped_chunks


def augment_chunks(
    session: Session,
    similar_chunks: list[Chunk],
    user_id: UUID,
    chunks_range: int,
) -> list[AugmentedChunksGroup]:
    """
    Recupera las instancias aumentadas de los chunks similares que se le proporcionan.
    """
    logger.info("Querying the database for augmented instances of the similar chunks.")

    # Sin esta comprobación la consulta a la db traería todos los chunks del usuario por el or_ vacío
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
        select(Chunk, Source)
        .join(Source, col(Chunk.source_id) == col(Source.id))
        .where(col(Source.user_id) == user_id)
        .where(or_(*conditions))  # or_ permite evaluar las condiciones de todas las ventanas de chunk_index y * desempaqueta la lista de condiciones.
        .order_by(col(Chunk.source_id), col(Chunk.position))
    )
    augmented_list: AugmentedList = list(session.exec(query).all())
    return group_chunks(augmented_list, chunk_position_windows)


def create_context(augmented_chunks: list[AugmentedChunksGroup]) -> str:
    """
    Crea la parte variable del prompt para el modelo de IA generativa.
    """
    logger.info("Creating the prompt context from chunk groups and their specific metadata")

    source_blocks = []
    for grouped_source_chunks in augmented_chunks:
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


class RetrievalAugmentationService:
    """Servicio para recuperar chunks similares y los aumenta con el contenido de los contiguos de la misma fuente."""

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

    def augment_chunk_groups(
        self,
        session: Session,
        similar_chunks: list[Chunk],
        user_id: UUID,
    ) -> list[AugmentedChunksGroup]:
        return augment_chunks(session, similar_chunks, user_id, self.chunks_range)

    def build_prompt_context(
        self, augmented_chunks: list[AugmentedChunksGroup]
    ) -> str:
        return create_context(augmented_chunks)
