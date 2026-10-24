import pytest

from app.extraction.mime_types import get_attachment_mime_type


@pytest.mark.parametrize(
    ("filename", "mime_type", "expected"),
    [
        ("brief.pdf", "application/pdf", ("application/pdf", None)),
        ("notes.md", "text/plain", ("text/plain", None)),
        (
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                None,
            ),
        ),
        (
            "report.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                None,
            ),
        ),
        ("photo.png", "image/png", (None, "Unsupported file type")),
    ],
)
def test_get_attachment_mime_type_classifies_supported_and_unsupported_types(
    filename: str, mime_type: str, expected: tuple[str | None, str | None]
) -> None:
    assert get_attachment_mime_type(filename, mime_type) == expected


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [
        (
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "report.xlsx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ],
)
def test_get_attachment_mime_type_rejects_mismatched_extension_and_mime_type(
    filename: str, mime_type: str
) -> None:
    assert get_attachment_mime_type(filename, mime_type) == (
        None,
        "Unsupported file type",
    )
