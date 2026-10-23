from app.extraction.mime_types import get_attachment_mime_type


def test_get_attachment_mime_type_classifies_supported_and_unsupported_types() -> None:
    assert get_attachment_mime_type("brief.pdf", "application/pdf") == (
        "application/pdf",
        None,
    )
    assert get_attachment_mime_type("notes.md", "text/plain") == (
        "text/plain",
        None,
    )
    assert get_attachment_mime_type("photo.png", "image/png") == (
        None,
        "Unsupported file type",
    )
