from uuid import UUID

from sqlmodel import Session, col, select

from app.core.logging import get_logger
from app.models import (
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
    Recupera los chunks más similares al embedding de la pregunta de las fuentes que pertenecen al usuario.
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


class RetrievalService:
    """Servicio para recuperar chunks mediante una búsqueda por similitud."""

    def __init__(self, chunks_limit: int = 3):
        self.chunks_limit = chunks_limit

    def search_similar_chunks(
        self,
        session: Session,
        embedded_question: QuestionEmbedding,
        user_id: UUID,
    ) -> list[Chunk]:
        return retrieve_chunks(session, embedded_question, user_id, self.chunks_limit)
