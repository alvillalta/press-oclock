import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import Question, User
from app.rag.embedding import EmbeddingResponseError
from tests.utils.user import create_random_user


def create_question(db: Session, user_id: uuid.UUID) -> Question:
    question = Question(
        question="What is in my inbox?",
        answer="There are several messages.",
        user_id=user_id,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def get_normal_user(db: Session) -> User:
    user = crud.get_user_by_email(session=db, email=settings.EMAIL_TEST_USER)
    assert user is not None
    return user


def test_delete_own_question_removes_it_from_storage_and_reads(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    question = create_question(db, get_normal_user(db).id)
    question_id = question.id

    response = client.delete(
        f"{settings.API_STR}/questions/{question_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Question deleted successfully"}
    db.expire_all()
    assert db.get(Question, question_id) is None

    read_response = client.get(
        f"{settings.API_STR}/questions/{question_id}",
        headers=normal_user_token_headers,
    )
    assert read_response.status_code == 404

    list_response = client.get(
        f"{settings.API_STR}/questions/",
        headers=normal_user_token_headers,
    )
    assert list_response.status_code == 200
    assert all(item["id"] != str(question_id) for item in list_response.json())


def test_delete_question_not_found(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.delete(
        f"{settings.API_STR}/questions/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Question not found"}


def test_delete_another_users_question_is_forbidden(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    owner = create_random_user(db)
    question = create_question(db, owner.id)

    response = client.delete(
        f"{settings.API_STR}/questions/{question.id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Not enough permissions"}
    db.expire_all()
    assert db.get(Question, question.id) is not None


def test_superuser_can_delete_question(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    owner = create_random_user(db)
    question = create_question(db, owner.id)
    question_id = question.id

    response = client.delete(
        f"{settings.API_STR}/questions/{question_id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Question deleted successfully"}
    db.expire_all()
    assert db.get(Question, question_id) is None


def test_create_question_embedding_mismatch_returns_502(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingRagService:
        def __init__(self, session: object) -> None:
            self.session = session

        async def answer_question(
            self, *, question_in: str, user_id: uuid.UUID
        ) -> None:
            raise EmbeddingResponseError(
                "Expected an embedding with 1536 dimensions, got 3."
            )

    monkeypatch.setattr("app.api.routes.questions.RagService", FailingRagService)

    response = client.post(
        f"{settings.API_STR}/questions/",
        headers=normal_user_token_headers,
        params={"question_in": "What is in my inbox?"},
    )

    # Respuesta de embeddings incompatible: 502 (no 500)
    assert response.status_code == 502
