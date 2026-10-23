from collections.abc import Callable
from typing import TypeAlias


class ExtractionDecodingError(Exception):
    """El contenido del adjunto no se puede decodificar como texto."""


def _extract_plain_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionDecodingError(
            "Attachment is not valid UTF-8 text"
        ) from exc


Extractor: TypeAlias = Callable[[bytes], str]  # Función que recibe bytes y devuelve str

# Diccionario de mapeo de funciones de extracción
EXTRACTORS: dict[str, Extractor] = {
    "text/plain": _extract_plain_text,
    "text/markdown": _extract_plain_text,
    "text/x-markdown": _extract_plain_text,
}


def extract_file_text(mime_type: str, content: bytes) -> str:
    extractor = EXTRACTORS.get(mime_type)
    if extractor is None:
        raise ValueError(f"No text extraction flow implemented for {mime_type}")
    return extractor(content)



