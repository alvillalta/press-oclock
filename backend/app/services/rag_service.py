from uuid import UUID

from sqlmodel import Session

from app.rag.embeddings import ChunkingEmbeddingService
from app.rag.retrieval_augmentation import RetrievalAugmentationService
from app.rag.generation import GenerationService
from app.rag.sources import get_sources

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
        if not embedded_question:
            raise ValueError("No embedding generated for the question")
        
        retrieval_augmentation_service = RetrievalAugmentationService()
        similar_chunks = retrieval_augmentation_service.search_similar_chunks(session=self.session, embedded_question=embedded_question, user_id=user_id)
        if not similar_chunks:
            raise ValueError("No chunks found for current user")
        
        augmented_chunks = retrieval_augmentation_service.expand_information(session=self.session, similar_chunks=similar_chunks, user_id=user_id)
        context = retrieval_augmentation_service.build_context(augmented_chunks)

        generation_service = GenerationService()
        answer = await generation_service.generate_answer(question_in, context)
        if not answer:
            raise ValueError("No answer generated for the question")

        sources = get_sources(similar_chunks, augmented_chunks)
        serialized_sources = [source.model_dump(mode="json") for source in sources]
        
        question = QuestionCreate(
            question=question_in,
            answer=answer,
            sources=serialized_sources,
        )
        db_question = create_question(session=self.session, question_in=question, user_id=user_id)

        return db_question