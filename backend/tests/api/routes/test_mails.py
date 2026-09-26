import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import Chunk, ChunkBase, ChunkCreate, Mail, Source
from tests.utils.mail import create_random_mail
from tests.utils.user import create_random_user


def test_read_mails(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    mail = create_random_mail(db)

    response = client.get(
        f"{settings.API_V1_STR}/mails/",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    mail_response = next(item for item in response.json() if item["id"] == str(mail.id))
    received_at = datetime.fromisoformat(
        mail_response["received_at"].replace("Z", "+00:00")
    )
    assert received_at == mail.received_at
    assert mail_response["source_id"] == str(mail.source_id)
    assert "body" not in mail_response


def test_read_mail_returns_original_body(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    mail = create_random_mail(db, body="The original body is retained.")

    response = client.get(
        f"{settings.API_V1_STR}/mails/{mail.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["body"] == "The original body is retained."
    received_at = datetime.fromisoformat(
        response.json()["received_at"].replace("Z", "+00:00")
    )
    assert received_at == mail.received_at
    assert response.json()["source_id"] == str(mail.source_id)


def test_read_mail_not_found(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/mails/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Mail not found"


def test_read_mail_not_enough_permissions(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    mail = create_random_mail(db)

    response = client.get(
        f"{settings.API_V1_STR}/mails/{mail.id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Not enough permissions"


def test_delete_mail_deletes_its_source_and_chunks(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    mail = create_random_mail(db)
    crud.create_chunks(
        session=db,
        source_id=mail.source_id,
        chunks_in=[
            ChunkCreate(
                content="A chunk to delete.",
                position=1,
                embedding=[0.0] * 1536,
            )
        ],
    )

    response = client.delete(
        f"{settings.API_V1_STR}/mails/{mail.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Mail deleted successfully"
    db.expire_all()
    assert db.get(Mail, mail.id) is None
    assert db.get(Source, mail.source_id) is None
    assert db.exec(select(Chunk).where(Chunk.source_id == mail.source_id)).all() == []


class FakeChunkingEmbeddingService:
    async def create_chunk_embeddings(
        self, chunks: list[ChunkBase]
    ) -> list[ChunkCreate]:
        return [
            ChunkCreate(
                content=chunk.content,
                position=chunk.position,
                embedding=[0.0] * 1536,
            )
            for chunk in chunks
        ]


def test_ingest_mail_creates_source_and_chunks(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(
        "app.services.mail_service.ChunkingEmbeddingService",
        FakeChunkingEmbeddingService,
    )
    data = {
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail with a body",
        "body": "The mail body is indexed.",
    }

    response = client.post(
        f"{settings.API_V1_STR}/mails/",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        json=data,
    )

    assert response.status_code == 200
    mail = db.get(Mail, uuid.UUID(response.json()["id"]))
    assert mail is not None
    assert mail.body == data["body"]
    source = db.get(Source, mail.source_id)
    assert source is not None
    assert source.origin == "mail"
    chunks = db.exec(select(Chunk).where(Chunk.source_id == source.id)).all()
    assert len(chunks) == 1
    assert chunks[0].content == data["body"]


@pytest.mark.parametrize("body", [None, ""])
def test_ingest_mail_without_body_does_not_create_chunks(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    body: str | None,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)

    class EmbeddingServiceMustNotRun:
        async def create_chunk_embeddings(
            self, chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise AssertionError("Empty mail bodies should not be embedded")

    monkeypatch.setattr(
        "app.services.mail_service.ChunkingEmbeddingService",
        EmbeddingServiceMustNotRun,
    )
    data = {
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail without a body",
        "body": body,
    }

    response = client.post(
        f"{settings.API_V1_STR}/mails/",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        json=data,
    )

    assert response.status_code == 200
    mail = db.get(Mail, uuid.UUID(response.json()["id"]))
    assert mail is not None
    assert mail.body == body
    source = db.get(Source, mail.source_id)
    assert source is not None
    assert db.exec(select(Chunk).where(Chunk.source_id == source.id)).all() == []
