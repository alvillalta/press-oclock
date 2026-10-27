from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

from app.core.config import settings

GENERATION_TEMPERATURE: float = 0.6
OPENAI_MAX_RETRIES = 2  # Dos reintentos del proveedor OpenAI equivalen a 3 intentos totales
OPENAI_TIMEOUT_SECONDS = 60.0


# Cachea los adaptadores y sus clientes HTTP, no las respuestas de la API
@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY),  
        model=settings.GENERATION_MODEL,
        temperature=GENERATION_TEMPERATURE,
        max_retries=OPENAI_MAX_RETRIES,
        timeout=OPENAI_TIMEOUT_SECONDS,
    )


@lru_cache(maxsize=1)
def get_embeddings_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        api_key=SecretStr(settings.OPENAI_API_KEY),
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
        max_retries=OPENAI_MAX_RETRIES,
        timeout=OPENAI_TIMEOUT_SECONDS,
    )
