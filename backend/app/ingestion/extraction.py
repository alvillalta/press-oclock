import mimetypes
from pathlib import PurePath
from typing import TypeAlias

SUPPORTED_ATTACHMENT_TYPES: dict[str, tuple[str, ...]] = {
    # Soporta tuplas con extensión variable
    ".pdf": ("application/pdf",),
    ".txt": ("text/plain",),
    ".md": ("text/markdown", "text/x-markdown", "text/plain"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}
# Valores por defecto que pueden llegar o si llega vacío
GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}

MimeTypeValidation: TypeAlias = tuple[
    str | None,  # normalized_mime_type
    str | None  # unsupported_reason
]


def get_attachment_mime_type(filename: str, mime_type: str) -> MimeTypeValidation:
    """
    Validación de tipo de un adjunto
    """
    # Infiere el tipo de archivo a partir de la extensión de la ruta del archivo
    # PurePath sirve para interpretar el string que se le pase como ruta de archivo
    # .suffix es una propiedad de lectura de PurePath para sacar .pdf, .docx, etc.
    extension = PurePath(filename).suffix.lower()
    accepted_mime_types = SUPPORTED_ATTACHMENT_TYPES.get(extension)
    if accepted_mime_types is None:
        return None, "Unsupported file type"

    # Normalización del tipo, si es genérico se fía del primer tipo de archivo de la extensión
    # Se hace split porque un Content-Type puede llevar parámetros después del tipo
    normalized_mime_type = mime_type.split(";", maxsplit=1)[0].strip().lower()
    if normalized_mime_type in GENERIC_MIME_TYPES:
        guessed_mime_type = mimetypes.guess_type(filename)[0]
        if guessed_mime_type in accepted_mime_types:
            normalized_mime_type = guessed_mime_type
        else:
            normalized_mime_type = accepted_mime_types[0]
    if normalized_mime_type not in accepted_mime_types:
        return None, "Unsupported file type"
    return normalized_mime_type, None
