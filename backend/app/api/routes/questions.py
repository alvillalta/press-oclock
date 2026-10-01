import uuid

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.core.logging import get_logger
from app.models import Message, Question, QuestionBase, QuestionPublic
from app.services.rag_service import RagService

router = APIRouter(prefix="/questions", tags=["questions"])

logger = get_logger(__name__)

@router.get("/", response_model=list[QuestionPublic])
def read_questions(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 50
) -> list[QuestionPublic]:
    """
    Retrieve questions.
    """
    if current_user.is_superuser:
        statement = (
            select(Question).order_by(col(Question.created_at).desc()).offset(skip).limit(limit)
        )
        questions = session.exec(statement).all()
    else:
        statement = (
            select(Question)
            .where(Question.user_id == current_user.id)
            .order_by(col(Question.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        questions = session.exec(statement).all()

    return [QuestionPublic.model_validate(question) for question in questions]


@router.get("/{id}", response_model=QuestionPublic)
def read_question(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> QuestionPublic:
    """
    Get question by ID.
    """
    question = session.get(Question, id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if (question.user_id != current_user.id) and (not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return QuestionPublic.model_validate(question)


@router.post("/", response_model=QuestionPublic)
async def create_question(
    *, session: SessionDep, current_user: CurrentUser, question_in: QuestionBase
) -> QuestionPublic:
    """
    Answer a question using the RAG system.
    """
    logger.info("Routing question")
    rag_service = RagService(session=session)
    try:
        question = await rag_service.answer_question(
            question_in=question_in, user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return QuestionPublic.model_validate(question)


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
    crud.delete_question(session=session, question=question)
    session.commit()
    return Message(message="Question deleted successfully")
