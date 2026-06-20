from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session
from app.rag.embeddings import ChunkingEmbeddingService

from app.core.logging import get_logger
from app.models import Question, QuestionBase, QuestionCreate 
from app.crud import create_question

logger = get_logger(__name__)

class RagService:
    def __init__(self, session: Session):
        self.session = session

    async def answer_question(self, question_in: QuestionBase, user_id: UUID) -> Question:
        """
        Responde a una pregunta utilizando el modelo RAG de la aplicación.
        """
        logger.info("Answering question")

        chunking_embedding_service = ChunkingEmbeddingService()
        embedded_question = await chunking_embedding_service.create_question_embedding(question_in)

        question_to_db = QuestionCreate(question=question_in) 
        db_question = create_question(session=self.session, question_in=question_to_db, user_id=user_id)

        """ question = QuestionCreate(
                question=question_in,
                answer= # AQUÍ VENDRÁ EL CAMPO ANSWER 
            )
        db_question = create_question(session=self.session, question_in=question, user_id=user_id)
        """

        return db_question