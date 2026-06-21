import uuid
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Depends
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import Message, Question, QuestionBase
from app.services.rag_service import RagService
from app.core.logging import get_logger

router = APIRouter(prefix="/questions", tags=["questions"])

logger = get_logger(__name__)

@router.get("/", response_model=list[Question])
def read_questions(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve questions.
    """
    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Question)
        count = session.exec(count_statement).one()
        statement = (
            select(Question).order_by(col(Question.created_at).desc()).offset(skip).limit(limit)
        )
        questions = session.exec(statement).all()
    else:
        count_statement = (
            select(func.count())
            .select_from(Question)
            .where(Question.user_id == current_user.id)
        )
        count = session.exec(count_statement).one()
        statement = (
            select(Question)
            .where(Question.user_id == current_user.id)
            .order_by(col(Question.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        questions = session.exec(statement).all()

    return questions


@router.get("/{id}", response_model=Question)
def read_question(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Question:
    """
    Get question by ID.
    """
    question = session.get(Question, id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if (question.user_id != current_user.id) and (not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return question


@router.post("/", response_model=Question)
async def create_question(
    *, session: SessionDep, current_user: CurrentUser, question_in: QuestionBase
) -> Question:
    """
    Answer a question using the RAG model of the application.
    """

    logger.info("Routing question")
    question_service = RagService(session=session)

    return await question_service.answer_question(
        question_in=question_in, user_id=current_user.id
    )


@router.delete("/{id}")
def delete_question(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Delete a question.
    """
    question = session.get(Question, id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if (question.user_id != current_user.id) and (not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    session.delete(question)
    session.commit()
    return Message(message="Question deleted successfully")
