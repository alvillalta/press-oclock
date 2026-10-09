import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import settings
from app.integrations import attachment_storage
from app.integrations.attachment_storage import AttachmentStorage


class FakeBucket:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def upload(self, **kwargs: Any) -> None:
        self.calls.append(("upload", (), kwargs))

    def remove(self, paths: list[str]) -> None:
        self.calls.append(("remove", (paths,), {}))

    def download(self, path: str) -> bytearray:
        self.calls.append(("download", (path,), {}))
        return bytearray(b"file contents")

    def create_signed_url(
        self,
        path: str,
        expires_in: int,
        options: dict[str, str] | None = None,
    ) -> dict[str, str]:
        self.calls.append(
            ("create_signed_url", (path, expires_in), {"options": options})
        )
        return {"signedURL": "https://storage.example/signed/file"}


class FakeStorageClient:
    def __init__(self, bucket: FakeBucket) -> None:
        self.bucket = bucket
        self.bucket_names: list[str] = []

    def storage_from(self, bucket_name: str) -> FakeBucket:
        self.bucket_names.append(bucket_name)
        return self.bucket


def test_injected_client_handles_storage_operations_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", None)
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_BUCKET", "test-bucket")
    monkeypatch.setattr(
        attachment_storage,
        "get_supabase_client",
        lambda: pytest.fail("Injected client should be used"),
    )

    bucket = FakeBucket()
    client = FakeStorageClient(bucket)
    client.storage = SimpleNamespace(from_=client.storage_from)
    storage = AttachmentStorage(client)  # type: ignore[arg-type]

    asyncio.run(storage.upload("folder/file.pdf", b"payload", "application/pdf"))
    asyncio.run(storage.remove(["folder/file.pdf"]))
    downloaded = asyncio.run(storage.download("folder/file.pdf"))
    signed_url = asyncio.run(
        storage.create_signed_url(
            "folder/file.pdf", download_filename="report final.pdf"
        )
    )

    assert downloaded == b"file contents"
    assert storage.expires_in == 120
    assert signed_url == (
        "https://storage.example/signed/file?download=report%20final.pdf"
    )
    assert client.bucket_names == ["test-bucket"] * 4
    assert bucket.calls == [
        (
            "upload",
            (),
            {
                "path": "folder/file.pdf",
                "file": b"payload",
                "file_options": {"content-type": "application/pdf", "upsert": "true"},
            },
        ),
        ("remove", (["folder/file.pdf"],), {}),
        ("download", ("folder/file.pdf",), {}),
        (
            "create_signed_url",
            ("folder/file.pdf", 120),
            {"options": {"download": "report final.pdf"}},
        ),
    ]


def test_storage_uses_central_client_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", None)
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None)
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_BUCKET", "test-bucket")

    bucket = FakeBucket()
    client = FakeStorageClient(bucket)
    client.storage = SimpleNamespace(from_=client.storage_from)
    provider_calls = 0

    def get_client() -> FakeStorageClient:
        nonlocal provider_calls
        provider_calls += 1
        return client

    monkeypatch.setattr(attachment_storage, "get_supabase_client", get_client)
    storage = AttachmentStorage()

    asyncio.run(storage.download("folder/file.pdf"))
    asyncio.run(storage.download("folder/file.pdf"))

    assert provider_calls == 1
    assert client.bucket_names == ["test-bucket"] * 2
