import asyncio
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Attachment,
    AttachmentStage,
    Chunk,
    ChunkBase,
    ChunkCreate,
    Mail,
    MailStage,
    Source,
    StorageCleanup,
)
from app.services.mail_service import MailService
from app.services.storage_cleanup_service import StorageCleanupService
from tests.utils.mail import create_random_mail
from tests.utils.user import create_random_user


def test_read_mails(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    mail = create_random_mail(db)

    response = client.get(
        f"{settings.API_STR}/mails/",
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
        f"{settings.API_STR}/mails/{mail.id}",
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
        f"{settings.API_STR}/mails/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Mail not found"


def test_read_mail_not_enough_permissions(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    mail = create_random_mail(db)

    response = client.get(
        f"{settings.API_STR}/mails/{mail.id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Not enough permissions"


def test_delete_mail_deletes_its_source_and_chunks(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    mail = create_random_mail(db)
    mail_id = mail.id
    source_id = mail.source_id
    crud.create_chunks(
        session=db,
        source_id=source_id,
        chunks_in=[
            ChunkCreate(
                content="A chunk to delete.",
                position=1,
                embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
            )
        ],
    )

    response = client.delete(
        f"{settings.API_STR}/mails/{mail_id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Mail deleted successfully"
    db.expire_all()
    assert db.get(Mail, mail_id) is None
    assert db.get(Source, source_id) is None
    assert db.exec(select(Chunk).where(Chunk.source_id == source_id)).all() == []


def test_delete_mail_cleans_attachment_sources_chunks_and_storage(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mail = create_random_mail(db)
    assert mail.user_id is not None
    attachment_source = crud.create_source(
        session=db, origin="attachment", user_id=mail.user_id
    )
    attachment = Attachment(
        mail_id=mail.id,
        source_id=attachment_source.id,
        filename="brief.pdf",
        mime_type="application/pdf",
        storage_path="mails/mail-id/attachments/file-id",
    )
    db.add(attachment)
    db.commit()
    mail_id = mail.id
    attachment_source_id = attachment_source.id
    crud.create_chunks(
        session=db,
        source_id=attachment_source_id,
        chunks_in=[
            ChunkCreate(
                content="An attachment chunk.",
                position=1,
                embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
            )
        ],
    )
    storage = FakeAttachmentStorage()
    monkeypatch.setattr(
        "app.services.storage_cleanup_service.AttachmentStorage", lambda: storage
    )

    response = client.delete(
        f"{settings.API_STR}/mails/{mail_id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    db.expire_all()
    assert db.get(Mail, mail_id) is None
    assert db.get(Source, attachment_source_id) is None
    assert db.exec(select(Attachment).where(Attachment.mail_id == mail_id)).all() == []
    assert db.exec(select(Chunk).where(Chunk.source_id == attachment_source_id)).all() == []
    assert storage.removed_paths == ["mails/mail-id/attachments/file-id"]


class FakeEmbeddingService:
    async def create_chunk_embeddings(
        self, chunks: list[ChunkBase]
    ) -> list[ChunkCreate]:
        return [
            ChunkCreate(
                content=chunk.content,
                position=chunk.position,
                embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
            )
            for chunk in chunks
        ]


class FakeAttachmentStorage:
    def __init__(self, fail_uploads: int = 0) -> None:
        self.fail_uploads = fail_uploads
        self.expires_in = 120
        self.upload_calls: list[tuple[str, bytes, str]] = []
        self.removed_paths: list[str] = []

    async def upload(self, path: str, content: bytes, mime_type: str) -> None:
        self.upload_calls.append((path, content, mime_type))
        if len(self.upload_calls) <= self.fail_uploads:
            raise RuntimeError("temporary storage error")

    async def remove(self, paths: list[str]) -> None:
        self.removed_paths.extend(paths)

    async def download(self, _path: str) -> bytes:
        return b"plain text"

    async def create_signed_url(
        self, path: str, download_filename: str | None = None
    ) -> str:
        return f"https://storage.example/{path}?expires={self.expires_in}&download={download_filename}"


def test_mail_service_classifies_supported_and_unsupported_attachment_types() -> None:
    service = MailService(session=None)  # type: ignore[arg-type]

    assert service._get_or_create_attachment_type("brief.pdf", "application/pdf") == (
        "application/pdf",
        None,
    )
    assert service._get_or_create_attachment_type("notes.md", "text/plain") == (
        "text/plain",
        None,
    )
    assert service._get_or_create_attachment_type("photo.png", "image/png") == (
        None,
        "unsupported_type",
    )


def _ingest_form(
    mail: Mapping[str, object],
    attachment_external_ids: list[str] | None = None,
) -> dict[str, str]:
    return {
        "mail": json.dumps(mail),
        "attachment_external_ids": json.dumps(attachment_external_ids or []),
    }


def test_ingest_mail_creates_source_and_chunks(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(
        "app.services.mail_service.EmbeddingService",
        FakeEmbeddingService,
    )
    mail_payload = {
        "external_id": "gmail-message-body-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail with a body",
        "body": "The mail body is indexed.",
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["result_summary"]["stored_count"] == 0
    mail = db.get(Mail, uuid.UUID(payload["mail_id"]))
    assert mail is not None
    assert mail.body == mail_payload["body"]
    source = db.get(Source, mail.source_id)
    assert source is not None
    assert source.origin == "mail"
    assert source.user_id == webhook_user.id
    chunks = db.exec(select(Chunk).where(Chunk.source_id == source.id)).all()
    assert len(chunks) == 1
    assert chunks[0].content == mail_payload["body"]


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
        "app.services.mail_service.EmbeddingService",
        EmbeddingServiceMustNotRun,
    )
    mail_payload = {
        "external_id": "gmail-message-without-body-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail without a body",
        "body": body,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    mail = db.get(Mail, uuid.UUID(payload["mail_id"]))
    assert mail is not None
    assert mail.body == body
    source = db.get(Source, mail.source_id)
    assert source is not None
    assert db.exec(select(Chunk).where(Chunk.source_id == source.id)).all() == []


def test_ingest_mail_persists_attachment_and_defers_extraction(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_service.AttachmentStorage", lambda: storage)
    monkeypatch.setattr(
        "app.services.mail_service.EmbeddingService", FakeEmbeddingService
    )

    def index_attachment_text_must_not_run(
        _self: MailService,
        *,
        attachment_id: uuid.UUID,  # noqa: ARG001
        extraction: str,  # noqa: ARG001
    ) -> None:
        raise AssertionError("Attachment extraction is out of scope for this version")

    monkeypatch.setattr(
        MailService, "index_attachment_text", index_attachment_text_must_not_run
    )

    mail_payload = {
        "external_id": "gmail-message-with-attachment-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail with attachment",
        "body": "The body is indexed.",
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-attachment-1"]),
        files=[("files", ("brief.pdf", b"%PDF sample", "application/pdf"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["result_summary"]["stored_count"] == 1
    assert payload["result_summary"]["omitted_count"] == 0
    assert len(storage.upload_calls) == 1
    mail_id = uuid.UUID(payload["mail_id"])
    ingestion_id = uuid.UUID(payload["ingestion_id"])
    db.expire_all()

    mail = db.get(Mail, mail_id)
    assert mail is not None
    assert mail.external_id == mail_payload["external_id"]
    assert mail.body == mail_payload["body"]
    body_chunks = db.exec(select(Chunk).where(Chunk.source_id == mail.source_id)).all()
    assert len(body_chunks) == 1
    assert body_chunks[0].content == mail_payload["body"]
    attachment = db.exec(select(Attachment).where(Attachment.mail_id == mail_id)).one()
    assert attachment.filename == "brief.pdf"
    assert attachment.storage_path.startswith("mails/")
    assert attachment.extraction is None
    assert attachment.extraction_status == "pending"
    attachment_source = db.get(Source, attachment.source_id)
    assert attachment_source is not None
    assert attachment_source.origin == "attachment"
    assert attachment_source.user_id == webhook_user.id
    assert db.exec(
        select(Chunk).where(Chunk.source_id == attachment.source_id)
    ).all() == []
    assert db.exec(
        select(AttachmentStage).where(
            AttachmentStage.mail_stage_id == ingestion_id
        )
    ).all() == []
    mail_stage = db.get(MailStage, ingestion_id)
    assert mail_stage is not None
    assert mail_stage.status == "completed"
    assert mail_stage.result_summary["stored_count"] == 1

    mails_response = client.get(
        f"{settings.API_STR}/mails/",
        headers=superuser_token_headers,
    )
    listed_mail = next(item for item in mails_response.json() if item["id"] == str(mail_id))
    assert listed_mail["has_attachments"] is True

    mail_detail = client.get(
        f"{settings.API_STR}/mails/{mail_id}",
        headers=superuser_token_headers,
    )
    attachment_metadata = mail_detail.json()["attachments"][0]
    assert attachment_metadata["extraction_status"] == "pending"


def test_repeated_ingest_does_not_duplicate_records(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_service.AttachmentStorage", lambda: storage)
    monkeypatch.setattr(
        "app.services.mail_service.EmbeddingService", FakeEmbeddingService
    )
    mail_payload = {
        "external_id": "gmail-message-repeated-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Repeated ingestion",
        "body": "The body is indexed.",
    }
    request_kwargs: dict[str, Any] = {
        "headers": {"X-API-Key": settings.MAKE_API_KEY},
        "data": _ingest_form(mail_payload, ["gmail-attachment-repeated-1"]),
        "files": [("files", ("brief.pdf", b"%PDF sample", "application/pdf"))],
    }

    first_response = client.post(
        f"{settings.API_STR}/mails/ingest", **request_kwargs
    )
    second_response = client.post(
        f"{settings.API_STR}/mails/ingest", **request_kwargs
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "completed"
    assert second_response.json()["mail_id"] == first_response.json()["mail_id"]
    assert len(storage.upload_calls) == 1
    db.expire_all()
    mail_id = uuid.UUID(first_response.json()["mail_id"])
    assert len(db.exec(select(Mail).where(Mail.external_id == mail_payload["external_id"])).all()) == 1
    assert len(db.exec(select(Attachment).where(Attachment.mail_id == mail_id)).all()) == 1


def test_ingest_rejects_mismatched_attachment_ids(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    mail_payload = {
        "external_id": "gmail-message-mismatched-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mismatched ids",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(
            mail_payload, ["gmail-attachment-1", "gmail-attachment-2"]
        ),
        files=[("files", ("brief.pdf", b"%PDF sample", "application/pdf"))],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "attachment_external_ids must have the same length as files"


def test_unsupported_attachment_is_omitted_without_upload(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_service.AttachmentStorage", lambda: storage)

    mail_payload = {
        "external_id": "gmail-message-unsupported-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Unsupported attachment",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-image-1"]),
        files=[("files", ("photo.png", b"image", "image/png"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["result_summary"]["stored_count"] == 0
    assert payload["result_summary"]["omitted_count"] == 1
    assert payload["result_summary"]["omitted"] == [
        {"external_id": "gmail-image-1", "reason": "Unsupported file type"}
    ]
    assert storage.upload_calls == []
    mail_id = uuid.UUID(payload["mail_id"])
    ingestion_id = uuid.UUID(payload["ingestion_id"])
    db.expire_all()
    mail = db.get(Mail, mail_id)
    assert mail is not None
    assert db.exec(select(Attachment).where(Attachment.mail_id == mail_id)).all() == []
    sources = db.exec(select(Source).where(Source.user_id == webhook_user.id)).all()
    assert [source.origin for source in sources].count("attachment") == 0
    mail_stage = db.get(MailStage, ingestion_id)
    assert mail_stage is not None
    assert mail_stage.result_summary["omitted_count"] == 1


def test_storage_upload_retries_three_times_then_omits_attachment(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setattr(settings, "MAIL_ATTACHMENT_STORAGE_RETRIES", 3)
    storage = FakeAttachmentStorage(fail_uploads=3)
    monkeypatch.setattr("app.services.mail_service.AttachmentStorage", lambda: storage)
    monkeypatch.setattr(
        "app.services.storage_cleanup_service.AttachmentStorage", lambda: storage
    )

    async def no_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr("app.services.mail_service.asyncio.sleep", no_sleep)
    mail_payload = {
        "external_id": "gmail-message-storage-failure",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Storage retry",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-attachment-fails"]),
        files=[("files", ("notes.txt", b"notes", "text/plain"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["result_summary"]["stored_count"] == 0
    assert payload["result_summary"]["omitted_count"] == 1
    assert payload["result_summary"]["omitted"] == [
        {"external_id": "gmail-attachment-fails", "reason": "storage_upload_failed"}
    ]
    assert len(storage.upload_calls) == 3
    assert storage.removed_paths == []
    mail_id = uuid.UUID(payload["mail_id"])
    db.expire_all()
    assert db.get(Mail, mail_id) is not None
    assert db.exec(select(Attachment).where(Attachment.mail_id == mail_id)).all() == []
    assert len(db.exec(select(StorageCleanup)).all()) == 1

    cleanup_count = asyncio.run(
        StorageCleanupService(
            session=db, storage=storage  # type: ignore[arg-type]
        ).process_pending()
    )
    assert cleanup_count == 1
    assert len(storage.removed_paths) == 1
    db.expire_all()
    assert db.exec(select(StorageCleanup)).all() == []


def test_embedding_failure_keeps_stages_for_retry(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_service.AttachmentStorage", lambda: storage)

    class FailingEmbeddingService:
        async def create_chunk_embeddings(
            self, chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr(
        "app.services.mail_service.EmbeddingService", FailingEmbeddingService
    )
    mail_payload = {
        "external_id": "gmail-message-embedding-failure",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Embedding failure",
        "body": "This body cannot be embedded yet.",
    }
    request_kwargs: dict[str, Any] = {
        "headers": {"X-API-Key": settings.MAKE_API_KEY},
        "data": _ingest_form(mail_payload, ["gmail-attachment-embedding"]),
        "files": [("files", ("notes.txt", b"notes", "text/plain"))],
    }

    with pytest.raises(RuntimeError):
        client.post(f"{settings.API_STR}/mails/ingest", **request_kwargs)

    db.expire_all()
    stage = db.exec(
        select(MailStage).where(MailStage.external_id == mail_payload["external_id"])
    ).one()
    assert stage.status == "receiving"
    staged_attachments = db.exec(
        select(AttachmentStage).where(AttachmentStage.mail_stage_id == stage.id)
    ).all()
    assert len(staged_attachments) == 1
    assert staged_attachments[0].status == "stored"
    assert (
        db.exec(
            select(Mail).where(Mail.external_id == mail_payload["external_id"])
        ).first()
        is None
    )

    monkeypatch.setattr(
        "app.services.mail_service.EmbeddingService", FakeEmbeddingService
    )
    retry_response = client.post(
        f"{settings.API_STR}/mails/ingest", **request_kwargs
    )

    assert retry_response.status_code == 200
    retry_payload = retry_response.json()
    assert retry_payload["status"] == "completed"
    assert retry_payload["result_summary"]["stored_count"] == 1
    assert len(storage.upload_calls) == 1
    db.expire_all()
    mail = db.get(Mail, uuid.UUID(retry_payload["mail_id"]))
    assert mail is not None
    assert mail.external_id == mail_payload["external_id"]
    assert len(db.exec(select(Attachment).where(Attachment.mail_id == mail.id)).all()) == 1


def test_ingest_enforces_combined_attachment_limit(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setattr(settings, "MAIL_ATTACHMENT_MAX_BYTES", 5)
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_service.AttachmentStorage", lambda: storage)

    mail_payload = {
        "external_id": "gmail-message-total-limit",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Combined size limit",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-small-file", "gmail-over-limit-file"]),
        files=[
            ("files", ("one.txt", b"1234", "text/plain")),
            ("files", ("two.txt", b"67", "text/plain")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["result_summary"]["stored_count"] == 1
    assert payload["result_summary"]["omitted_count"] == 1
    assert payload["result_summary"]["omitted"] == [
        {"external_id": "gmail-over-limit-file", "reason": "Total size limit exceeded"}
    ]
    assert len(storage.upload_calls) == 1
    db.expire_all()
    attachments = db.exec(
        select(Attachment).where(Attachment.mail_id == uuid.UUID(payload["mail_id"]))
    ).all()
    assert len(attachments) == 1
    assert attachments[0].filename == "one.txt"


def test_attachment_access_uses_authorized_signed_url_and_txt_content(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_random_user(db)
    assert user.id is not None
    mail = create_random_mail(db, user_id=user.id)
    attachment_source = crud.create_source(
        session=db, origin="attachment", user_id=user.id
    )
    attachment = Attachment(
        mail_id=mail.id,
        source_id=attachment_source.id,
        filename="notes.txt",
        mime_type="text/plain",
        storage_path="mail/notes.txt",
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.api.routes.mails.AttachmentStorage", lambda: storage)

    signed_url_response = client.get(
        f"{settings.API_STR}/mails/{mail.id}/attachments/{attachment.id}/signed-url",
        headers=superuser_token_headers,
    )
    assert signed_url_response.status_code == 200
    assert signed_url_response.json()["url"].startswith("https://storage.example/")

    text_response = client.get(
        f"{settings.API_STR}/mails/{mail.id}/attachments/{attachment.id}/text",
        headers=superuser_token_headers,
    )
    assert text_response.status_code == 200
    assert text_response.text == "plain text"

    denied_response = client.get(
        f"{settings.API_STR}/mails/{mail.id}/attachments/{attachment.id}/signed-url",
        headers=normal_user_token_headers,
    )
    assert denied_response.status_code == 403


@pytest.mark.anyio
async def test_expired_mail_stage_removes_staged_object(
    db: Session,
) -> None:
    user = create_random_user(db)
    assert user.id is not None
    storage_path = "mails/staging/expired-file"
    stage = MailStage(
        external_id=f"expired-{uuid.uuid4()}",
        user_id=user.id,
        sender="sender@example.com",
        received_at=datetime.now(timezone.utc),
        status="receiving",
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.add(stage)
    db.flush()
    db.add(
        AttachmentStage(
            mail_stage_id=stage.id,
            external_id="attachment-1",
            filename="old.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            status="stored",
            storage_path=storage_path,
        )
    )
    db.commit()
    storage = FakeAttachmentStorage()

    expired_count = await MailService(session=db).cleanup_expired_ingestions()
    cleanup_count = await StorageCleanupService(
        session=db, storage=storage  # type: ignore[arg-type]
    ).process_pending()

    assert expired_count == 1
    assert cleanup_count == 1
    assert storage.removed_paths == [storage_path]
    db.expire_all()
    assert db.get(MailStage, stage.id) is None
    assert (
        db.exec(
            select(AttachmentStage).where(
                AttachmentStage.mail_stage_id == stage.id
            )
        ).all()
        == []
    )
