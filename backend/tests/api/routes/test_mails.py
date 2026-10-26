import asyncio
import json
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app import crud
from app.api.routes import mails as mails_route
from app.core.config import settings
from app.extraction.attachment_processing import AttachmentProcessingService
from app.extraction.chunk_indexing import ChunkIndexingService
from app.extraction.extraction import (
    ExtractionDecodingError,
    extract_file_text,
)
from app.models import (
    Attachment,
    AttachmentStage,
    AttachmentUpload,
    Chunk,
    ChunkBase,
    ChunkCreate,
    Mail,
    MailStage,
    MailStageCreate,
    Source,
    StorageCleanup,
)
from app.rag.embedding import EmbeddingResponseError
from app.services.mail_ingestion_service import MailIngestionService
from app.services.storage_cleanup_service import StorageCleanupService
from tests.utils.documents import build_pdf
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
    async def generate_chunk_embeddings(
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
    def __init__(
        self,
        fail_uploads: int = 0,
        poison_paths: set[str] | None = None,
        fail_batch: bool = False,
        on_upload: Callable[[str], None] | None = None,
        fail_downloads: int = 0,
        download_content: bytes = b"plain text",
    ) -> None:
        self.fail_uploads = fail_uploads
        # Paths que siempre fallan al borrarse (simulan un registro veneno)
        self.poison_paths = set(poison_paths or ())
        # Fuerza el fallo del borrado por lote (len > 1)
        self.fail_batch = fail_batch
        # Hook opcional para simular efectos externos durante la subida (p. ej. borrar el stage)
        self.on_upload = on_upload
        self.fail_downloads = fail_downloads
        self.download_content = download_content
        self.expires_in = 120
        self.upload_calls: list[tuple[str, bytes, str]] = []
        self.uploaded_content: dict[str, bytes] = {}
        self.download_calls: list[str] = []
        self.removed_paths: list[str] = []

    async def upload(self, path: str, content: bytes, mime_type: str) -> None:
        self.upload_calls.append((path, content, mime_type))
        self.uploaded_content[path] = content
        if self.on_upload is not None:
            self.on_upload(path)
        if len(self.upload_calls) <= self.fail_uploads:
            raise RuntimeError("temporary storage error")

    async def remove(self, paths: list[str]) -> None:
        # Simula el fallo del lote completo o de un path veneno concreto
        if (self.fail_batch and len(paths) > 1) or any(
            path in self.poison_paths for path in paths
        ):
            raise RuntimeError("storage removal failed")
        self.removed_paths.extend(paths)

    async def download(self, path: str) -> bytes:
        self.download_calls.append(path)
        if len(self.download_calls) <= self.fail_downloads:
            raise RuntimeError("temporary storage error")
        return self.uploaded_content.get(path, self.download_content)

    async def create_signed_url(
        self, path: str, download_filename: str | None = None
    ) -> str:
        return f"https://storage.example/{path}?expires={self.expires_in}&download={download_filename}"


@pytest.mark.anyio
async def test_text_mime_types_share_the_same_extractor() -> None:
    markdown = b"# Heading\n\nBody"
    for mime_type in ("text/plain", "text/markdown", "text/x-markdown"):
        assert await extract_file_text(mime_type, markdown) == "# Heading\n\nBody"


@pytest.mark.anyio
async def test_extract_file_text_strips_utf8_bom() -> None:
    assert await extract_file_text("text/plain", b"\xef\xbb\xbfcontent") == "content"


@pytest.mark.anyio
async def test_extract_file_text_rejects_invalid_utf8() -> None:
    with pytest.raises(ExtractionDecodingError):
        await extract_file_text("text/plain", b"\xff")


@pytest.mark.anyio
async def test_extract_file_text_rejects_unimplemented_mime_type() -> None:
    with pytest.raises(ValueError, match="No text extraction flow implemented"):
        await extract_file_text("application/zip", b"x")


def test_attachment_upload_accepts_route_fields() -> None:
    upload = AttachmentUpload(
        external_id="gmail-attachment-1",
        filename="brief.pdf",
        mime_type="application/pdf",
        content=b"%PDF sample",
        oversize=False,
        measured_size=11,
    )

    assert upload.external_id == "gmail-attachment-1"
    assert upload.filename == "brief.pdf"
    assert upload.mime_type == "application/pdf"
    assert upload.content == b"%PDF sample"
    assert upload.oversize is False
    assert upload.measured_size == 11


def _ingest_form(
    mail: Mapping[str, object],
    attachment_external_ids: list[str] | None = None,
) -> dict[str, str]:
    return {
        "mail": json.dumps(mail),
        "attachment_external_ids": json.dumps(attachment_external_ids or []),
    }


def test_ingest_persists_mail_before_indexing_body(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService",
        FakeEmbeddingService,
    )

    observed: dict[str, Any] = {}
    original_index_source_text = ChunkIndexingService.index_source_text

    async def index_after_persist(
        self: ChunkIndexingService, *, source_id: uuid.UUID, text: str
    ) -> None:
        db.expire_all()
        persisted_mail = db.exec(
            select(Mail).where(Mail.source_id == source_id)
        ).first()
        observed["mail_persisted"] = persisted_mail is not None
        observed["body"] = persisted_mail.body if persisted_mail is not None else None
        await original_index_source_text(self, source_id=source_id, text=text)

    monkeypatch.setattr(
        ChunkIndexingService, "index_source_text", index_after_persist
    )

    mail_payload = {
        "external_id": "msg-body-order-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail body indexing order",
        "body": "Index this body after persisting the mail.",
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload),
    )

    assert response.status_code == 200
    assert observed == {
        "mail_persisted": True,
        "body": mail_payload["body"],
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
        "app.extraction.chunk_indexing.EmbeddingService",
        FakeEmbeddingService,
    )
    mail_payload = {
        "external_id": "msg-body-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail with a body",
        "body": "The mail body is indexed.",
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
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
        async def generate_chunk_embeddings(
            self, chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise AssertionError("Empty mail bodies should not be embedded")

    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService",
        EmbeddingServiceMustNotRun,
    )
    mail_payload = {
        "external_id": "msg-nobody-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail without a body",
        "body": body,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
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


def test_attachment_processing_skips_mail_without_attachments(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mail = create_random_mail(db)
    db.commit()

    async def process_attachment_must_not_run(
        _self: AttachmentProcessingService,
        *,
        attachment_id: uuid.UUID,  # noqa: ARG001
    ) -> None:
        raise AssertionError("A mail without attachments should not process files")

    monkeypatch.setattr(
        AttachmentProcessingService,
        "process_attachment",
        process_attachment_must_not_run,
    )

    asyncio.run(
        AttachmentProcessingService(session=db).process_mail_attachments(
            mail_id=mail.id
        )
    )


def test_pdf_is_extracted_and_indexed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_ingestion_service.AttachmentStorage", lambda: storage)
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )

    mail_payload = {
        "external_id": "msg-attach-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mail with attachment",
        "body": "The body is indexed.",
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-attachment-1"]),
        files=[("files", ("brief.pdf", build_pdf(), "application/pdf"))],
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
    assert attachment.extraction is not None
    assert "Hello PDF" in attachment.extraction
    assert attachment.extraction_status == "completed"
    assert len(storage.download_calls) == 1
    attachment_source = db.get(Source, attachment.source_id)
    assert attachment_source is not None
    assert attachment_source.origin == "attachment"
    assert attachment_source.user_id == webhook_user.id
    attachment_chunks = db.exec(
        select(Chunk).where(Chunk.source_id == attachment.source_id)
    ).all()
    assert len(attachment_chunks) == 1
    assert attachment_chunks[0].content == attachment.extraction
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
    assert attachment_metadata["extraction_status"] == "completed"


def test_ingest_extracts_and_indexes_txt_and_markdown(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )

    mail_payload = {
        "external_id": "msg-text-attach",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Text attachments",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["attachment-txt", "attachment-md"]),
        files=[
            ("files", ("notes.txt", b"\xef\xbb\xbfplain text", "text/plain")),
            ("files", ("notes.md", b"# Heading", "text/markdown")),
        ],
    )

    assert response.status_code == 200
    mail_id = uuid.UUID(response.json()["mail_id"])
    db.expire_all()
    attachments = db.exec(
        select(Attachment).where(Attachment.mail_id == mail_id)
    ).all()
    attachments_by_name = {attachment.filename: attachment for attachment in attachments}
    assert attachments_by_name["notes.txt"].extraction == "plain text"
    assert attachments_by_name["notes.txt"].extraction_status == "completed"
    assert attachments_by_name["notes.md"].extraction == "# Heading"
    assert attachments_by_name["notes.md"].extraction_status == "completed"
    assert len(storage.download_calls) == 2

    for attachment in attachments:
        chunks = db.exec(
            select(Chunk).where(Chunk.source_id == attachment.source_id)
        ).all()
        assert len(chunks) == 1
        assert chunks[0].content == attachment.extraction


def test_empty_text_extraction_is_stored_without_embeddings(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )

    class EmbeddingServiceMustNotRun:
        async def generate_chunk_embeddings(
            self, chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise AssertionError("Empty attachment text should not be embedded")

    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", EmbeddingServiceMustNotRun
    )
    mail_payload = {
        "external_id": "msg-empty-text",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Empty text attachment",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["attachment-empty"]),
        files=[("files", ("empty.txt", b"  \n", "text/plain"))],
    )

    assert response.status_code == 200
    mail_id = uuid.UUID(response.json()["mail_id"])
    db.expire_all()
    attachment = db.exec(
        select(Attachment).where(Attachment.mail_id == mail_id)
    ).one()
    assert attachment.extraction == ""
    assert attachment.extraction_status == "empty"
    assert db.exec(
        select(Chunk).where(Chunk.source_id == attachment.source_id)
    ).all() == []


def test_attachment_download_retries_transient_failures(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage(fail_downloads=2)
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )

    async def no_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr("app.extraction.attachment_processing.asyncio.sleep", no_sleep)
    mail_payload = {
        "external_id": "msg-dl-retry",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Download retry",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["attachment-download-retry"]),
        files=[("files", ("retry.txt", b"retried content", "text/plain"))],
    )

    assert response.status_code == 200
    assert len(storage.download_calls) == 3
    mail_id = uuid.UUID(response.json()["mail_id"])
    db.expire_all()
    attachment = db.exec(
        select(Attachment).where(Attachment.mail_id == mail_id)
    ).one()
    assert attachment.extraction == "retried content"
    assert attachment.extraction_status == "completed"


def test_attachment_download_failure_after_retries_marks_extraction_failed(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage(fail_downloads=3)
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )

    async def no_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr("app.extraction.attachment_processing.asyncio.sleep", no_sleep)
    mail_payload = {
        "external_id": "msg-dl-fail",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Download failure",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["attachment-download-fail"]),
        files=[("files", ("failed.txt", b"never downloaded", "text/plain"))],
    )

    assert response.status_code == 200
    assert len(storage.download_calls) == 3
    mail_id = uuid.UUID(response.json()["mail_id"])
    db.expire_all()
    attachment = db.exec(
        select(Attachment).where(Attachment.mail_id == mail_id)
    ).one()
    assert attachment.extraction is None
    assert attachment.extraction_status == "failed"


def test_invalid_text_fails_without_retry_and_does_not_block_other_attachments(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )

    mail_payload = {
        "external_id": "msg-invalid-text",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Invalid text attachment",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["attachment-invalid", "attachment-valid"]),
        files=[
            ("files", ("invalid.txt", b"\xff", "text/plain")),
            ("files", ("valid.txt", b"valid content", "text/plain")),
        ],
    )

    assert response.status_code == 200
    assert len(storage.download_calls) == 2
    mail_id = uuid.UUID(response.json()["mail_id"])
    db.expire_all()
    attachments = db.exec(
        select(Attachment).where(Attachment.mail_id == mail_id)
    ).all()
    attachments_by_name = {attachment.filename: attachment for attachment in attachments}
    assert attachments_by_name["invalid.txt"].extraction is None
    assert attachments_by_name["invalid.txt"].extraction_status == "failed"
    assert attachments_by_name["valid.txt"].extraction == "valid content"
    assert attachments_by_name["valid.txt"].extraction_status == "completed"
    assert db.exec(
        select(Chunk).where(
            Chunk.source_id == attachments_by_name["invalid.txt"].source_id
        )
    ).all() == []
    assert len(
        db.exec(
            select(Chunk).where(
                Chunk.source_id == attachments_by_name["valid.txt"].source_id
            )
        ).all()
    ) == 1


def test_attachment_indexing_failure_preserves_extracted_text(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )

    class FailingEmbeddingService:
        async def generate_chunk_embeddings(
            self, _chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FailingEmbeddingService
    )
    mail_payload = {
        "external_id": "msg-index-fail",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Attachment indexing failure",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["attachment-index-fail"]),
        files=[("files", ("kept.txt", b"keep this text", "text/plain"))],
    )

    assert response.status_code == 200
    mail_id = uuid.UUID(response.json()["mail_id"])
    db.expire_all()
    attachment = db.exec(
        select(Attachment).where(Attachment.mail_id == mail_id)
    ).one()
    assert attachment.extraction == "keep this text"
    assert attachment.extraction_status == "completed"
    assert db.exec(
        select(Chunk).where(Chunk.source_id == attachment.source_id)
    ).all() == []


def test_repeated_ingest_does_not_duplicate_records(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_ingestion_service.AttachmentStorage", lambda: storage)
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )

    process_calls = {"count": 0}
    original_process_mail_attachments = (
        AttachmentProcessingService.process_mail_attachments
    )

    async def counting_process_mail_attachments(
        self: AttachmentProcessingService, *, mail_id: uuid.UUID
    ) -> None:
        process_calls["count"] += 1
        await original_process_mail_attachments(self, mail_id=mail_id)

    monkeypatch.setattr(
        AttachmentProcessingService,
        "process_mail_attachments",
        counting_process_mail_attachments,
    )

    # Cuenta las lecturas de archivo para comprobar que un correo duplicado no consume adjuntos
    read_upload_calls = {"count": 0}
    original_read_upload = mails_route._read_upload

    async def counting_read_upload(upload: UploadFile) -> tuple[bytes, int, bool]:
        read_upload_calls["count"] += 1
        return await original_read_upload(upload)

    monkeypatch.setattr(mails_route, "_read_upload", counting_read_upload)

    mail_payload = {
        "external_id": "msg-repeat-1",
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
        f"{settings.API_STR}/mails/ingest-mail", **request_kwargs
    )
    assert read_upload_calls["count"] == 1

    second_response = client.post(
        f"{settings.API_STR}/mails/ingest-mail", **request_kwargs
    )
    # El segundo request no debe leer los adjuntos: la ingesta ya está completada
    assert read_upload_calls["count"] == 1

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "completed"
    assert second_response.json()["mail_id"] == first_response.json()["mail_id"]
    assert len(storage.upload_calls) == 1
    db.expire_all()
    mail_id = uuid.UUID(first_response.json()["mail_id"])
    assert len(db.exec(select(Mail).where(Mail.external_id == mail_payload["external_id"])).all()) == 1
    assert len(db.exec(select(Attachment).where(Attachment.mail_id == mail_id)).all()) == 1
    assert process_calls["count"] == 1


def test_finalize_ingestion_rejects_pending_attachments(db: Session) -> None:
    user = create_random_user(db)
    assert user.id is not None
    stage = MailStage(
        user_id=user.id,
        external_id="msg-pending-1",
        sender="sender@example.com",
        received_at=datetime.now(timezone.utc),
        subject="Pending attachment",
        body="Body",
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    stage_id = stage.id

    attachment_stage = AttachmentStage(
        mail_stage_id=stage_id,
        external_id="attachment-pending-1",
        filename="notes.txt",
        mime_type="text/plain",
        status="pending",
    )
    db.add(attachment_stage)
    db.commit()
    attachment_stage_id = attachment_stage.id

    service = MailIngestionService(session=db)
    with pytest.raises(ValueError, match="still being uploaded"):
        asyncio.run(service.finalize_ingestion(stage_id, user.id))

    db.expire_all()
    persisted_stage = db.get(MailStage, stage_id)
    assert persisted_stage is not None
    assert persisted_stage.status == "receiving"
    assert db.exec(
        select(Mail).where(Mail.external_id == "msg-pending-1")
    ).all() == []
    assert db.get(AttachmentStage, attachment_stage_id) is not None


def test_finalize_ingestion_is_idempotent_and_does_not_embed(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_random_user(db)
    assert user.id is not None
    stage = MailStage(
        user_id=user.id,
        external_id="msg-finalize-1",
        sender="sender@example.com",
        received_at=datetime.now(timezone.utc),
        subject="Finalized",
        body="Body persisted without embeddings",
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    stage_id = stage.id

    class EmbeddingServiceMustNotRun:
        async def generate_chunk_embeddings(
            self, chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise AssertionError("finalize_ingestion should not generate embeddings")

    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService",
        EmbeddingServiceMustNotRun,
    )

    service = MailIngestionService(session=db)
    first = asyncio.run(service.finalize_ingestion(stage_id, user.id))
    second = asyncio.run(service.finalize_ingestion(stage_id, user.id))

    assert first.finalized_in_this_call is True
    assert second.finalized_in_this_call is False
    assert second.mail_id == first.mail_id
    db.expire_all()
    mails = db.exec(
        select(Mail).where(Mail.external_id == "msg-finalize-1")
    ).all()
    assert len(mails) == 1
    assert mails[0].body == "Body persisted without embeddings"


def test_ingest_rejects_mismatched_attachment_ids(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    mail_payload = {
        "external_id": "msg-mismatch-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Mismatched ids",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(
            mail_payload, ["gmail-attachment-1", "gmail-attachment-2"]
        ),
        files=[("files", ("brief.pdf", b"%PDF sample", "application/pdf"))],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "attachment_external_ids must have the same length as files"


@pytest.mark.parametrize(
    ("external_id", "expected_status"),
    [("a" * 16, 200), ("a" * 17, 422)],
)
def test_ingest_enforces_mail_external_id_limit(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    external_id: str,
    expected_status: int,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    mail_payload = {
        "external_id": external_id,
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "External id limit",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload),
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("attachment_external_id", "expected_status"),
    [("c" * 1024, 200), ("c" * 1025, 422)],
)
def test_ingest_enforces_attachment_external_id_limit(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    attachment_external_id: str,
    expected_status: int,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )
    mail_payload = {
        "external_id": "b" * 16,
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Attachment external id limit",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, [attachment_external_id]),
        files=[("files", ("notes.txt", b"notes", "text/plain"))],
    )

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["result_summary"]["stored_count"] == 1
        assert len(storage.upload_calls) == 1
    else:
        assert response.json()["detail"] == (
            "attachment_external_ids must be a JSON array of strings "
            "between 1 and 1024 characters"
        )


def test_unsupported_attachment_is_omitted_without_upload(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_ingestion_service.AttachmentStorage", lambda: storage)

    mail_payload = {
        "external_id": "msg-unsup-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Unsupported attachment",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-archive-1"]),
        files=[("files", ("archive.zip", b"archive", "application/zip"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["result_summary"]["stored_count"] == 0
    assert payload["result_summary"]["omitted_count"] == 1
    assert payload["result_summary"]["omitted"] == [
        {"external_id": "gmail-archive-1", "reason": "Unsupported file type"}
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
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage(fail_uploads=3)
    monkeypatch.setattr("app.services.mail_ingestion_service.AttachmentStorage", lambda: storage)
    monkeypatch.setattr(
        "app.services.storage_cleanup_service.AttachmentStorage", lambda: storage
    )

    async def no_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr("app.services.mail_ingestion_service.asyncio.sleep", no_sleep)
    mail_payload = {
        "external_id": "msg-storage-fail",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Storage retry",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
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


def test_stage_disappearing_after_successful_upload_is_a_500_and_cleans_storage(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    db.exec(delete(StorageCleanup))
    db.commit()

    def delete_stage_after_upload(path: str) -> None:
        stage_id = uuid.UUID(path.rsplit("/", 1)[-1])
        db.exec(delete(AttachmentStage).where(AttachmentStage.id == stage_id))
        db.commit()

    # La subida termina bien, pero el hook borra el stage durante la subida
    storage = FakeAttachmentStorage(on_upload=delete_stage_after_upload)
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )

    async def no_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr("app.services.mail_ingestion_service.asyncio.sleep", no_sleep)
    mail_payload = {
        "external_id": "msg-vanishes-1",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Stage vanishes",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-attachment-stage-gone"]),
        files=[("files", ("notes.txt", b"notes", "text/plain"))],
    )

    # Inconsistencia interna: 500 y sin reintentar el error como si fuera un fallo de Storage
    assert response.status_code == 500
    assert len(storage.upload_calls) == 1
    db.expire_all()
    assert len(db.exec(select(StorageCleanup)).all()) == 1
    db.exec(delete(StorageCleanup))
    db.commit()


def test_stage_disappearing_after_exhausted_uploads_is_a_500_and_cleans_storage(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    db.exec(delete(StorageCleanup))
    db.commit()

    def delete_stage_after_upload(path: str) -> None:
        stage_id = uuid.UUID(path.rsplit("/", 1)[-1])
        db.exec(delete(AttachmentStage).where(AttachmentStage.id == stage_id))
        db.commit()

    storage = FakeAttachmentStorage(fail_uploads=3, on_upload=delete_stage_after_upload)
    monkeypatch.setattr(
        "app.services.mail_ingestion_service.AttachmentStorage", lambda: storage
    )

    async def no_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr("app.services.mail_ingestion_service.asyncio.sleep", no_sleep)
    mail_payload = {
        "external_id": "msg-vanish-exh",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Stage vanishes on exhaustion",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-attachment-stage-gone-on-fail"]),
        files=[("files", ("notes.txt", b"notes", "text/plain"))],
    )

    assert response.status_code == 500
    assert len(storage.upload_calls) == 3
    db.expire_all()
    assert len(db.exec(select(StorageCleanup)).all()) == 1
    db.exec(delete(StorageCleanup))
    db.commit()


def test_persistence_error_after_upload_is_not_retried_as_storage_failure(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    service = MailIngestionService(session=db, storage=storage)  # type: ignore[arg-type]
    mail_in = MailStageCreate(
        external_id="msg-persist-err",
        sender="sender@example.com",
        received_at=datetime.now(timezone.utc),
        subject="Persist error",
        body=None,
    )
    stage = service.start_ingestion(mail_in=mail_in, user_id=webhook_user.id)
    assert stage.ingestion_id is not None

    original_commit = Session.commit
    commit_calls = {"count": 0}

    def failing_commit(self: Session) -> None:
        commit_calls["count"] += 1
        # El primer commit persiste el stage; el segundo guarda el estado "stored"
        if commit_calls["count"] == 2:
            raise RuntimeError("database unavailable")
        original_commit(self)

    monkeypatch.setattr(Session, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(
            service.stage_attachment(
                ingestion_id=stage.ingestion_id,
                user_id=webhook_user.id,
                external_id="gmail-attachment-persist-error",
                filename="notes.txt",
                mime_type="text/plain",
                content=b"notes",
                measured_size=5,
            )
        )

    # Un fallo de persistencia no se interpreta como fallo de Storage: no hay reintentos
    assert len(storage.upload_calls) == 1
    db.rollback()


def test_storage_cleanup_isolates_poison_record(db: Session) -> None:
    db.exec(delete(StorageCleanup))
    db.commit()
    good_path = "mails/cleanup/good"
    poison_path = "mails/cleanup/poison"
    db.add(StorageCleanup(storage_path=good_path))
    db.add(StorageCleanup(storage_path=poison_path))
    db.commit()
    storage = FakeAttachmentStorage(poison_paths={poison_path})

    cleaned_count = asyncio.run(
        StorageCleanupService(
            session=db, storage=storage  # type: ignore[arg-type]
        ).process_pending()
    )

    # El lote falla por el veneno, pero el buen registro se limpia igualmente en el fallback
    assert cleaned_count == 1
    assert storage.removed_paths == [good_path]
    db.expire_all()
    remaining = db.exec(select(StorageCleanup)).all()
    assert [record.storage_path for record in remaining] == [poison_path]
    assert remaining[0].attempt_count == 1
    assert remaining[0].last_error is not None
    db.exec(delete(StorageCleanup))
    db.commit()


def test_storage_cleanup_dead_letters_record_and_advances_queue(db: Session) -> None:
    db.exec(delete(StorageCleanup))
    db.commit()
    poison_path = "mails/cleanup/poison"
    db.add(StorageCleanup(storage_path=poison_path))
    db.commit()
    storage = FakeAttachmentStorage(poison_paths={poison_path})
    service = StorageCleanupService(
        session=db, storage=storage, max_attempts=3  # type: ignore[arg-type]
    )

    for _ in range(3):
        asyncio.run(service.process_pending())

    db.expire_all()
    poison_record = db.exec(
        select(StorageCleanup).where(StorageCleanup.storage_path == poison_path)
    ).first()
    assert poison_record is not None
    assert poison_record.attempt_count == 3
    assert poison_record.last_error is not None

    # Al llegar al cap, el registro deja de seleccionarse y la cola avanza
    other_path = "mails/cleanup/other"
    db.add(StorageCleanup(storage_path=other_path))
    db.commit()

    cleaned_count = asyncio.run(service.process_pending())
    assert cleaned_count == 1
    assert other_path in storage.removed_paths
    db.expire_all()
    remaining = db.exec(select(StorageCleanup)).all()
    assert [record.storage_path for record in remaining] == [poison_path]
    db.exec(delete(StorageCleanup))
    db.commit()


def test_storage_cleanup_retries_per_record_when_batch_fails(db: Session) -> None:
    db.exec(delete(StorageCleanup))
    db.commit()
    paths = ["mails/cleanup/a", "mails/cleanup/b"]
    for path in paths:
        db.add(StorageCleanup(storage_path=path))
    db.commit()
    storage = FakeAttachmentStorage(fail_batch=True)

    cleaned_count = asyncio.run(
        StorageCleanupService(
            session=db, storage=storage  # type: ignore[arg-type]
        ).process_pending()
    )

    # Si el lote falla pero cada registro por separado funciona, no se marca ningún intento
    assert cleaned_count == len(paths)
    assert sorted(storage.removed_paths) == sorted(paths)
    db.expire_all()
    assert db.exec(select(StorageCleanup)).all() == []
    db.exec(delete(StorageCleanup))
    db.commit()


def test_storage_cleanup_continues_after_failed_batch(db: Session) -> None:
    db.exec(delete(StorageCleanup))
    db.commit()
    poison_path = "mails/cleanup/poison"
    good_paths = ["mails/cleanup/good-0", "mails/cleanup/good-1", "mails/cleanup/good-2"]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # El veneno es el más antiguo; los buenos van después (created_at explícito para ordenar)
    db.add(StorageCleanup(storage_path=poison_path, created_at=base_time))
    for offset, path in enumerate(good_paths, start=1):
        db.add(StorageCleanup(storage_path=path, created_at=base_time + timedelta(seconds=offset)))
    db.commit()
    storage = FakeAttachmentStorage(poison_paths={poison_path})
    service = StorageCleanupService(
        session=db, storage=storage, limit=2  # type: ignore[arg-type]
    )

    cleaned_count = asyncio.run(service.process_pending())

    # El fallo del primer lote no corta la corrida: los buenos de lotes posteriores se limpian igual
    assert cleaned_count == len(good_paths)
    assert sorted(storage.removed_paths) == sorted(good_paths)
    db.expire_all()
    remaining = db.exec(select(StorageCleanup)).all()
    assert [record.storage_path for record in remaining] == [poison_path]
    # El veneno cuenta un único intento por corrida (no tres dentro de la misma)
    assert remaining[0].attempt_count == 1
    db.exec(delete(StorageCleanup))
    db.commit()


def test_embedding_failure_persists_mail_without_chunks(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_ingestion_service.AttachmentStorage", lambda: storage)

    class FailingEmbeddingService:
        async def generate_chunk_embeddings(
            self, chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FailingEmbeddingService
    )
    mail_payload = {
        "external_id": "msg-embed-fail",
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

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail", **request_kwargs
    )

    # El fallo de indexación no impide que la ingesta termine correctamente
    assert response.status_code == 200
    db.expire_all()
    stage = db.exec(
        select(MailStage).where(MailStage.external_id == mail_payload["external_id"])
    ).one()
    assert stage.status == "completed"
    assert stage.mail_id is not None
    assert db.exec(
        select(AttachmentStage).where(AttachmentStage.mail_stage_id == stage.id)
    ).all() == []
    mail = db.exec(
        select(Mail).where(Mail.external_id == mail_payload["external_id"])
    ).one()
    assert mail.body == mail_payload["body"]
    assert db.exec(select(Chunk).where(Chunk.source_id == mail.source_id)).all() == []
    attachment = db.exec(
        select(Attachment).where(Attachment.mail_id == mail.id)
    ).one()
    assert attachment.extraction == "notes"
    assert db.exec(
        select(Chunk).where(Chunk.source_id == attachment.source_id)
    ).all() == []

    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )
    retry_response = client.post(
        f"{settings.API_STR}/mails/ingest-mail", **request_kwargs
    )

    assert retry_response.status_code == 200
    retry_payload = retry_response.json()
    assert retry_payload["status"] == "completed"
    assert retry_payload["result_summary"]["already_processed"] is True
    assert retry_payload["mail_id"] == str(mail.id)
    # El correo ya estaba persistido, así que no se repite la subida ni la indexación
    assert len(storage.upload_calls) == 1
    db.expire_all()
    assert db.exec(select(Chunk).where(Chunk.source_id == mail.source_id)).all() == []
    assert db.exec(
        select(Chunk).where(Chunk.source_id == attachment.source_id)
    ).all() == []


def test_embedding_dimension_mismatch_persists_mail_without_chunks(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_ingestion_service.AttachmentStorage", lambda: storage)

    class MismatchedEmbeddingService:
        async def generate_chunk_embeddings(
            self, chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise EmbeddingResponseError(
                "Expected an embedding with 1536 dimensions, got 3."
            )

    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", MismatchedEmbeddingService
    )
    mail_payload = {
        "external_id": "msg-embed-mism",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Embedding mismatch",
        "body": "This body cannot be embedded yet.",
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
        headers={"X-API-Key": settings.MAKE_API_KEY},
        data=_ingest_form(mail_payload, ["gmail-attachment-embedding-mismatch"]),
        files=[("files", ("notes.txt", b"notes", "text/plain"))],
    )

    # El fallo de indexación no impide que la ingesta termine correctamente
    assert response.status_code == 200
    db.expire_all()
    stage = db.exec(
        select(MailStage).where(MailStage.external_id == mail_payload["external_id"])
    ).one()
    assert stage.status == "completed"
    assert stage.mail_id is not None
    mail = db.exec(
        select(Mail).where(Mail.external_id == mail_payload["external_id"])
    ).one()
    assert db.exec(select(Chunk).where(Chunk.source_id == mail.source_id)).all() == []
    attachment = db.exec(
        select(Attachment).where(Attachment.mail_id == mail.id)
    ).one()
    assert attachment.extraction == "notes"
    assert db.exec(
        select(Chunk).where(Chunk.source_id == attachment.source_id)
    ).all() == []


def test_ingest_enforces_combined_attachment_limit(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_user = create_random_user(db)
    assert webhook_user.id is not None
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_USER_ID", webhook_user.id)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_URL", "https://storage.example")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_KEY", "test-key")
    monkeypatch.setattr(settings, "MAIL_ATTACHMENT_MAX_BYTES", 5)
    storage = FakeAttachmentStorage()
    monkeypatch.setattr("app.services.mail_ingestion_service.AttachmentStorage", lambda: storage)
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )

    mail_payload = {
        "external_id": "msg-total-limit",
        "sender": "sender@example.com",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Combined size limit",
        "body": None,
    }

    response = client.post(
        f"{settings.API_STR}/mails/ingest-mail",
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
        external_id=f"exp-{uuid.uuid4().hex[:12]}",
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
    service = StorageCleanupService(session=db, storage=storage)  # type: ignore[arg-type]

    expired_count = await service.cleanup_expired_ingestions()
    cleanup_count = await service.process_pending()

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
