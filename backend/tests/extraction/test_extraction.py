import pytest

from app.extraction.extraction import extract_file_text
from tests.utils.documents import build_docx, build_pdf, build_pptx, build_xlsx

DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
def test_extract_file_text_converts_supported_documents(
    mime_type: str, content: bytes, expected: str
) -> None:
    assert expected in extract_file_text(mime_type, content)
