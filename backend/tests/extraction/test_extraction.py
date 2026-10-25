import base64
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import settings
from app.extraction import extraction
from app.extraction.extraction import (
    ImageExtractionError,
    MarkItDownExtractionError,
    extract_file_text,
)
from tests.utils.documents import build_docx, build_pdf, build_pptx, build_xlsx

DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mime_type", "content", "expected"),
    [
        ("application/pdf", build_pdf(), "Hello PDF"),
        (DOCX_MIME_TYPE, build_docx(), "Hello DOCX"),
        (PPTX_MIME_TYPE, build_pptx(), "Hello PPTX"),
        (XLSX_MIME_TYPE, build_xlsx(), "Hello XLSX"),
    ],
    ids=["pdf", "docx", "pptx", "xlsx"],
)
async def test_extract_file_text_converts_supported_documents(
    mime_type: str, content: bytes, expected: str
) -> None:
    assert expected in await extract_file_text(mime_type, content)


def _fake_vision_client(descriptions: list[str]) -> tuple[Any, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=descriptions.pop(0))
                )
            ]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return client, calls


@pytest.mark.anyio
async def test_extract_file_text_describes_image_with_vision_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls = _fake_vision_client(["  Una fotografía de una calle.  "])
    monkeypatch.setattr(extraction, "get_openai_client", lambda: client)
    content = b"\x89PNG\r\n\x1a\nfoto"

    assert (
        await extract_file_text("image/png", content)
        == "Una fotografía de una calle."
    )

    request = calls[0]
    assert request["model"] == settings.GENERATION_MODEL
    expected_url = (
        "data:image/png;base64," + base64.b64encode(content).decode("ascii")
    )
    assert request["messages"][1]["content"][0]["image_url"]["url"] == expected_url


@pytest.mark.anyio
async def test_extract_file_text_truncates_image_description_to_chunk_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _fake_vision_client(["x" * 900])
    monkeypatch.setattr(extraction, "get_openai_client", lambda: client)

    description = await extract_file_text("image/jpeg", b"foto")

    assert len(description) == extraction.IMAGE_DESCRIPTION_MAX_CHARS
    assert description == "x" * extraction.IMAGE_DESCRIPTION_MAX_CHARS


@pytest.mark.anyio
async def test_vision_extraction_wraps_provider_failure_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def create(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(extraction, "get_openai_client", lambda: client)

    with pytest.raises(
        ImageExtractionError, match="Image description extraction failed"
    ) as exc_info:
        await extract_file_text("image/png", b"foto")

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert calls == 1


@pytest.mark.anyio
async def test_markitdown_extraction_wraps_conversion_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingMarkItDown:
        def convert_stream(self, *_args: Any, **_kwargs: Any) -> None:
            raise ValueError("broken document")

    monkeypatch.setattr(extraction, "_get_markitdown", lambda: FailingMarkItDown())

    with pytest.raises(
        MarkItDownExtractionError, match="Document content extraction failed"
    ) as exc_info:
        await extract_file_text("application/pdf", b"not a real pdf")

    assert isinstance(exc_info.value.__cause__, ValueError)
