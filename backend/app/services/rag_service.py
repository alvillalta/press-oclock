from uuid import UUID

from sqlmodel import Session

from app.core.logging import get_logger
from app.crud import create_question
from app.models import Question, QuestionBase, QuestionCreate
from app.rag.rag_agent import AgentService

logger = get_logger(__name__)


class RagService:
    def __init__(self, session: Session):
        self.session = session

    async def rag_answer(
        self, question_in: QuestionBase, user_id: UUID
    ) -> Question:
        """
        Responde a una pregunta utilizando el agente RAG de la aplicación.
        """
        logger.info("Answering and persisting question")

        agent_response = await AgentService().agent_answer(
            question_in,
            session=self.session,
            user_id=user_id,
        )

        # Conversión de objetos en JSON para poder persistirlos
        # Si no hay citas se serializa una lista vacía tal y como viene del agente y el frontend no mapea nada
        serialized_citations = [
            citation.model_dump(mode="json") for citation in agent_response.citations
        ]

        question = QuestionCreate(
            question=question_in,
            answer=agent_response.answer,
            citations=serialized_citations,
        )
        db_question = create_question(
            session=self.session, question_in=question, user_id=user_id
        )

        logger.info("RAG Service OK")

        return db_question
