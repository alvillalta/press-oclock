import logging 
from datetime import datetime
from typing import List, TypeAlias
from uuid import UUID

from pydantic import EmailStr
from sqlmodel import Session, and_, col, or_, select

from app.models import AugmentedMailChunksGroup, Chunk, Mail, QuestionEmbedding

logger = logging.getLogger(__name__)


def retrieve_chunks(
    session: Session, 
    embedded_question: QuestionEmbedding, 
    user_id: UUID, 
    chunks_limit: int
) -> List[Chunk]:
    """
    Compara un embedding de referencia con los embeddings de los chunks en la base de datos
    y devuelve los chunks más similares.
    """
    query = (
        select(Chunk)
        .join(Mail, col(Chunk.mail_id) == col(Mail.id))
        .where(col(Mail.user_id) == user_id)
        .order_by(col(Chunk.embedding).op("<=>")(embedded_question))
        .limit(chunks_limit)
    )
    results = session.exec(query).all()

    if not results:
        return []
    
    return list(results)


ChunkIndexWindows: TypeAlias = List[
    tuple[
        UUID,  # MailId
        int,  # StartChunkIndex
        int,  # EndChunkIndex
    ]
]


def merge_windows(
    chunk_index_windows: ChunkIndexWindows,
) -> ChunkIndexWindows:
    """
    Fusiona ventanas solapadas para cada mail_id.
    """
    if not chunk_index_windows:
        return []

    # Ordena por mail_id y start de la tupla para poder fusionar en una pasada
    chunk_index_windows.sort(key=lambda window_key: (window_key[0], window_key[1]))

    merged_windows = []
    # Guarda el primer elemento de la lista para no compararlo consigo mismo a continuación
    current_mail_id, current_start, current_end = chunk_index_windows[0]

    # Itera sobre el resto de elementos de la lista para fusionar ventanas
    for mail_id, start, end in chunk_index_windows[1:]:
        # Si es el mismo mail y solapa, amplía el final
        if mail_id == current_mail_id and start <= current_end + 1:
            current_end = max(current_end, end)
        # Si no solapa, guarda la ventana acumulada y la sitúa la nueva de referencia para la siguiente iteración
        else:
            merged_windows.append((current_mail_id, current_start, current_end))
            current_mail_id, current_start, current_end = mail_id, start, end

    # Guarda la última ventana acumulada después de salir del bucle
    merged_windows.append((current_mail_id, current_start, current_end))
    return merged_windows


AugmentedList: TypeAlias = List[
    tuple[
        Chunk,
        str | None,  # MailSubject
        str,  # MailSender
        datetime,  # MailDate
    ]
]


ChunkWindowRetrieval: TypeAlias = dict[
    #  CLAVE: (MailId, ChunkIndex) -> VALOR: Chunk
    tuple[
        UUID,  # MailId
        int,  # ChunkIndex
    ],
    Chunk,
]


MailMetadata: TypeAlias = dict[
    #  CLAVE: MailId -> VALOR: (MailSubject, MailSender, MailDate)
    UUID, 
    tuple[
        str | None,  # MailSubject
        str,  # MailSender
        datetime,  # MailDate
    ],
]

def group_chunks(
    augmented_list: AugmentedList,
    chunk_index_windows: ChunkIndexWindows,
) -> List[AugmentedMailChunksGroup]:
    """
    Agrupa los chunks de cada grupo en un diccionario con metadatos del mail.
    """
    by_mail_and_index: ChunkWindowRetrieval = {}  # Almacena claves tuplas de (mail_id, chunk_index) para los valores de los objetos chunks
    mail_metadata: MailMetadata = {}  # Almacena claves de mail_id para los valores de los metadatos de los mails

    for chunk, subject, sender, date in augmented_list:
        by_mail_and_index[(chunk.mail_id, chunk.chunk_index)] = chunk
        if chunk.mail_id not in mail_metadata:
            mail_metadata[chunk.mail_id] = (subject, sender, date)

    grouped_chunks: List[AugmentedMailChunksGroup] = []
    for mail_id, start, end in chunk_index_windows:
        chunks_group: List[Chunk] = []
        for chunk_index in range(start, end + 1):
            chunk = by_mail_and_index.get((mail_id, chunk_index))
            if chunk is not None:
                chunks_group.append(chunk)

        if not chunks_group:
            continue

        subject, sender, date = mail_metadata[mail_id]
        grouped_chunks.append(
            {
                "mail_id": mail_id,
                "subject": subject,
                "sender": sender,
                "date": date,
                "chunk_list": chunks_group,
            }
        )

    return grouped_chunks


def augment_chunks(
    session: Session,
    similar_chunks: List[Chunk],
    user_id: UUID,
    chunks_range: int
) -> List[AugmentedMailChunksGroup]:
    """
    Devuelve grupos de chunks contiguos por cada chunk similar (anchor),
    manteniendo el orden por chunk_index dentro de cada grupo.
    """
    if not similar_chunks:
        return []

    chunk_index_windows: ChunkIndexWindows = []
    for chunk in similar_chunks:
        start = max(1, chunk.chunk_index - chunks_range)  # Devuelve el índice del chunk más bajo, pero no menor a 1
        end = chunk.chunk_index + chunks_range  # La consulta a la db se encargará de limitar el rango al máximo chunk_index disponible
        chunk_index_windows.append((chunk.mail_id, start, end))  # Añade una tupla de elementos inalterables de posición por cada chunk 

    chunk_index_windows = merge_windows(chunk_index_windows)

    conditions = [
        and_(
            col(Chunk.mail_id) == mail_id,
            col(Chunk.chunk_index) >= start,
            col(Chunk.chunk_index) <= end,
        )
        for mail_id, start, end in chunk_index_windows
    ]

    query = (
        select(Chunk, Mail.subject, Mail.sender, Mail.date)
        .join(Mail, col(Chunk.mail_id) == col(Mail.id))
        .where(col(Mail.user_id) == user_id)
        .where(or_(*conditions))  # or_ permite evaluar las condiciones de todas las ventanas de chunk_index y * desempaqueta la lista de condiciones
        .order_by(col(Chunk.mail_id), col(Chunk.chunk_index))
    )
    results = session.exec(query).all()

    augmented_list: AugmentedList = list(results)
    return group_chunks(augmented_list, chunk_index_windows)


def merge_chunks(
    augmented_chunks: List[AugmentedMailChunksGroup],
) -> str:
    """
    Devuelve un string con los chunks y metadatos del mail de cada grupo, separado por un delimitador.
    """
    items = []
    
    for grouped_mail_chunks in augmented_chunks:
        joined_chunks = "\n".join(chunk.chunk_text for chunk in grouped_mail_chunks["chunk_list"])

        mail_block = (
            f"\nCORREO\n"
            f"ID: {grouped_mail_chunks['mail_id']}\n"
            f"Subject: {grouped_mail_chunks['subject'] or '(sin asunto)'}\n"
            f"Sender: {grouped_mail_chunks['sender']}\n"
            f"Date: {grouped_mail_chunks['date'].isoformat()}\n"
            f"Body: {joined_chunks}"
        )
        items.append(mail_block)
    
    return "\n---\n".join(items)


class RetrievalAugmentationService:
    """Servicio para comparar embeddings y recuperar chunks similares para generar el contexto."""
    
    def __init__(self, chunks_limit: int = 3, chunks_range: int = 1):
        self.chunks_limit = chunks_limit
        self.chunks_range = chunks_range
    
    def search_similar_chunks(self, session: Session, embedded_question: QuestionEmbedding, user_id: UUID) -> List[Chunk]:
        """Recupera chunks de la base de datos chunks similares al embedding de referencia a partir de una lista de chunks."""
        return retrieve_chunks(session, embedded_question, user_id, self.chunks_limit)

    def expand_information(self, session: Session, similar_chunks: List[Chunk], user_id: UUID) -> List[AugmentedMailChunksGroup]:
        """Aumenta la información de los chunks recuperados y los metadatos del mail asociado"""
        return augment_chunks(session, similar_chunks, user_id, self.chunks_range)
    
    def build_context(self, augmented_chunks: List[AugmentedMailChunksGroup]) -> str:
        """Construye el contexto para un LM a partir de los chunks aumentados y metadatos del mail asociado."""
        return merge_chunks(augmented_chunks)

    