import asyncio
import base64
from collections.abc import Awaitable, Callable
from functools import lru_cache
from io import BytesIO
from typing import TypeAlias

from langchain_core.messages import HumanMessage, SystemMessage
from markitdown import MarkItDown, StreamInfo

from app.integrations.openai_client import get_chat_model

# Función que recibe mime_type y bytes y devuelve texto de forma asíncrona
Extractor: TypeAlias = Callable[[str, bytes], Awaitable[str]]


class ExtractionError(Exception):
    """Fallo esperado al extraer contenido de un adjunto."""


class ExtractionDecodingError(ExtractionError):
    """El texto no se puede decodificar."""


class ImageExtractionError(ExtractionError):
    """No se pudo describir la imagen."""


class MarkItDownExtractionError(ExtractionError):
    """No se pudo extraer el contenido del documento."""


# Realmente es una operación síncrona y no bloqueante, pero se define como async para que cuadre con la llamada de extract_file_text()
async def _extract_plain_text(_mime_type: str, content: bytes) -> str:  # El mime_type no se usa, pero lo exige la firma de Extractor
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionDecodingError(
            "Attachment is not valid UTF-8 text"
        ) from exc


@lru_cache  # Cachea la instancia con la que opera MarkItDown para no reconstruirla de cero en cada adjunto
def _get_markitdown() -> MarkItDown:
    return MarkItDown(enable_plugins=False)  # Evita extensiones de terceros


def _convert_with_markitdown(mime_type: str, content: bytes) -> str:
    try:
        extraction = _get_markitdown().convert_stream(
            BytesIO(content),  # Convierte los bytes del binario a un objeto similar con el que trabaja MarkItDown
            stream_info=StreamInfo(mimetype=mime_type),  # Selecciona el conversor interno que debe usar
        )
    except Exception as exc:
        raise MarkItDownExtractionError(
            "Document content extraction failed"
        ) from exc
    return extraction.markdown  # Devuelve el contenido de Markdown como un str

# La conversión de MarkItDown es síncrona pero puede tardar, así que se ejecuta en un hilo de procesamiento asíncrono
async def _extract_with_markitdown(mime_type: str, content: bytes) -> str:
    return await asyncio.to_thread(_convert_with_markitdown, mime_type, content)


IMAGE_DESCRIPTION_MAX_CHARS = 800
system_prompt = f"""
        Describe la imagen de forma objetiva, concisa y precisa incluyedo cuando sean visibles y relevantes:

        - Contenido principal: escena, actividad y elementos protagonistas.
        - Personas y objetos: número aproximado de personas, acciones observables, vestimenta relevante, objetos destacados y entorno.
        - Texto y entidades: transcribe el texto legible y describe logotipos, carteles, señalización y nombres de entidades visibles.
        - Contexto visual: distribución de los elementos, primer plano, fondo y relaciones espaciales relevantes.
        - Calidad técnica: orientación, encuadre, iluminación, nitidez, composición y posibles dificultades para adaptar la imagen a formatos de redes sociales.
        - Aspectos editoriales: presencia visible de menores, datos personales, información sensible, escenas delicadas o elementos que requieran revisión antes de publicar.

        REGLAS:
        - Prioriza la información útil y omite los detalles irrelevantes o que no puedan evaluarse.
        - No inventes información que no pueda verificarse a partir de la imagen.
        - Evita valoraciones subjetivas y distingue los hechos observables de las interpretaciones.

        Devuelve únicamente la descripción, sin encabezados ni comentarios adicionales,
        con un máximo de {IMAGE_DESCRIPTION_MAX_CHARS} caracteres.
    """

async def _extract_with_vision(mime_type: str, content: bytes) -> str:
    encoded_image = base64.b64encode(content).decode("ascii")  # Convierte los bytes de la imagen a Base64 (una representación textual de los mismos). Usa ascii, un subconjunto de utf-8, porque está más acotado al tipo de caracteres que devuelve base64
    messages = [
        SystemMessage(content=system_prompt),  # SystemMessage es un tipo concreto de mensaje para establecer el comportamiento del modelo en base al system_prompt
        HumanMessage(
            content=[{"type": "image", "base64": encoded_image, "mime_type": mime_type}],  # Content block estándar de LangChain (en este caso han de declararse más campos que en un texto para enviar el contenido de una imágen) portable entre distintos proveedores de LLM. ChatOpenAI lo convierte automáticamente a image_url, que es la que usa.
        ),
    ]

    try:
        response = await get_chat_model().ainvoke(messages)  # ainvoke sirve para invocar el modelo de forma asíncrona y realizar otras tareas mientras tanto
    except Exception as exc:
        raise ImageExtractionError("Image description extraction failed") from exc

    description = response.text or ""
    return description.strip()[:IMAGE_DESCRIPTION_MAX_CHARS]  # Refuerzo de recorte para que nunca se pase de los caracteres máximos que buscamos


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
    "image/jpeg": _extract_with_vision,
    "image/png": _extract_with_vision,
    "image/webp": _extract_with_vision,
}


async def extract_file_text(mime_type: str, content: bytes) -> str:
    extractor = EXTRACTORS.get(mime_type)
    if extractor is None:
        raise ValueError(f"No text extraction flow implemented for {mime_type}")
    return await extractor(mime_type, content)
