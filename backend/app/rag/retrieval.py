import logging 
from typing import List
from uuid import UUID

from sqlmodel import Session, col, select

from app.models import Chunk, Mail, QuestionEmbedding

logger = logging.getLogger(__name__)


def compare_chunks(
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


class RetrievalService:
    """Servicio para comparar embeddings y recuperar chunks similares para generar el contexto."""
    
    def __init__(self, chunks_limit: int = 3):
        self.chunks_limit = chunks_limit
    
    def search_similar_chunks(self, session: Session, embedded_question: QuestionEmbedding, user_id: UUID) -> List[Chunk]:
        """Busca chunks similares al embedding de referencia a partir de una lista de chunks."""
        return compare_chunks(session, embedded_question, user_id, self.chunks_limit)

    