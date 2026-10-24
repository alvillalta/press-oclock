from collections.abc import Callable
from functools import lru_cache
from io import BytesIO
from typing import TypeAlias

from markitdown import MarkItDown, StreamInfo

Extractor: TypeAlias = Callable[[str, bytes], str]  # Función que recibe mime_type y bytes y devuelve str


class ExtractionDecodingError(Exception):
    """El contenido del adjunto no se puede decodificar como texto."""


def _extract_plain_text(mime_type: str, content: bytes) -> str:  #mime_type no se usa en esta función, pero es necesario para la lógica de _extract_with_markitdown
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionDecodingError(
            "Attachment is not valid UTF-8 text"
        ) from exc

    
@lru_cache  # Cachea la instancia con la que opera MarkItDown para no reconstruirla de cero en cada adjunto
def _get_markitdown() -> MarkItDown:
    return MarkItDown(enable_plugins=False)  # Evita extensiones de terceros

def _extract_with_markitdown(mime_type: str, content: bytes) -> str:
    extraction = _get_markitdown().convert_stream(
        BytesIO(content),  # Convierte los bytes del binario a un objeto similar con el que trabaja MarkItDown
        stream_info=StreamInfo(mimetype=mime_type),  # Selecciona el conversor interno que debe usar
    )
    return extraction.markdown  # Devuelve el contenido de Markdown como un str


# Diccionario de mapeo de funciones de extracción
EXTRACTORS: dict[str, Extractor] = {
    "text/plain": _extract_plain_text,
    "text/markdown": _extract_plain_text,
    "text/x-markdown": _extract_plain_text,
    "application/pdf": _extract_with_markitdown,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        _extract_with_markitdown
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        _extract_with_markitdown
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        _extract_with_markitdown
    ),
}


def extract_file_text(mime_type: str, content: bytes) -> str:
    extractor = EXTRACTORS.get(mime_type)
    if extractor is None:
        raise ValueError(f"No text extraction flow implemented for {mime_type}")
    return extractor(mime_type, content)
