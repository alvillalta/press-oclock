from uuid import UUID

from sqlmodel import Session

from app.core.logging import get_logger
from app.crud import create_question
from app.models import Question, QuestionBase, QuestionCreate
from app.rag.augmentation import AugmentationService
from app.rag.citations import CitationService
from app.rag.embedding import EmbeddingService
from app.rag.generation import GenerationService
from app.rag.metadata import MetadataService
from app.rag.retrieval import RetrievalService

logger = get_logger(__name__)


class RagService:
    def __init__(self, session: Session):
        self.session = session

    async def answer_question(
        self, question_in: QuestionBase, user_id: UUID
    ) -> Question:
        """
        Responde a una pregunta utilizando el modelo RAG de la aplicación.
        """
        logger.info("Answering and persisting question")

        embedding_service = EmbeddingService()
        embedded_question = await embedding_service.create_question_embedding(
            question_in
        )

        retrieval_service = RetrievalService()
        similar_chunks = retrieval_service.search_similar_chunks(
            session=self.session, embedded_question=embedded_question, user_id=user_id
        )
        if not similar_chunks:
            raise LookupError("No similar chunks found for current user")

        augmentation_service = AugmentationService()
        augmented_chunk_groups = augmentation_service.create_chunk_groups(
            session=self.session, similar_chunks=similar_chunks, user_id=user_id
        )

        metadata_service = MetadataService()
        augmented_chunk_groups = metadata_service.load_source_details(
            session=self.session, augmented_chunk_groups=augmented_chunk_groups
        )

        generation_service = GenerationService()
        answer = await generation_service.generate_answer(question_in, augmented_chunk_groups)

        citation_service = CitationService()
        citations = citation_service.get_citations_metadata(similar_chunks, augmented_chunk_groups)
        # Conversión de modelos SQL en JSON para poder persistirlos
        serialized_citations = [
            citation.model_dump(mode="json") for citation in citations
        ]

        question = QuestionCreate(
            question=question_in,
            answer=answer,
            citations=serialized_citations,
        )
        db_question = create_question(
            session=self.session, question_in=question, user_id=user_id
        )

        logger.info("RAG Service OK")

        return db_question
