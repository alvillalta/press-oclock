from uuid import UUID

from sqlmodel import Session

from app.core.logging import get_logger
from app.crud import create_question
from app.models import Question, QuestionBase, QuestionCreate
from app.rag.embeddings import EmbeddingService
from app.rag.generation import GenerationService
from app.rag.retrieval_augmentation import RetrievalAugmentationService
from app.rag.sources import get_sources, load_source_details

logger = get_logger(__name__)

class RagService:
    def __init__(self, session: Session):
        self.session = session

    async def answer_question(self, question_in: QuestionBase, user_id: UUID) -> Question:
        """
        Responde a una pregunta utilizando el modelo RAG de la aplicación.
        """
        logger.info("Answering and persisting question")

        embedding_service = EmbeddingService()
        embedded_question = await embedding_service.create_question_embedding(question_in)
        if not embedded_question:
            raise ValueError("No embedding generated for the question")
        
        retrieval_augmentation_service = RetrievalAugmentationService()
        similar_chunks = retrieval_augmentation_service.search_similar_chunks(session=self.session, embedded_question=embedded_question, user_id=user_id)
        if not similar_chunks:
            raise ValueError("No similar chunks found for current user")
        
        augmented_chunks = retrieval_augmentation_service.augment_chunk_groups(session=self.session, similar_chunks=similar_chunks, user_id=user_id)
        augmented_chunks = load_source_details(
            session=self.session,
            source_groups=augmented_chunks,
        )
        context = retrieval_augmentation_service.build_prompt_context(augmented_chunks)

        generation_service = GenerationService()
        answer = await generation_service.generate_answer(question_in, context)
        if not answer:
            raise ValueError("No answer generated for the question")

        sources = get_sources(similar_chunks, augmented_chunks)
        # Conversión de modelos SQL en JSON para poder persistirlos
        serialized_sources = [source.model_dump(mode="json") for source in sources]
        
        question = QuestionCreate(
            question=question_in,
            answer=answer,
            sources=serialized_sources,
        )
        db_question = create_question(session=self.session, question_in=question, user_id=user_id)

        logger.info("RAG Service OK")

        return db_question
