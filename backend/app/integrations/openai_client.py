from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

from app.core.config import settings


MAX_RETRIES = 2  # Dos reintentos del proveedor OpenAI equivalen a 3 intentos totales
TIMEOUT_SECONDS = 60.0
TEMPERATURE = 0.5


# Cachea los adaptadores y sus clientes HTTP para evitar reconstruirlos en cada petición a la API
@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY),  # Lo ideal sería llevar SecretStr a config.py y aplicarlo para el resto de valores que deberían ser secretos si se hacen logs, etc.
        model=settings.GENERATION_MODEL,
        temperature=TEMPERATURE,
        max_retries=MAX_RETRIES,
        timeout=TIMEOUT_SECONDS,
    )


@lru_cache(maxsize=1)
def get_embeddings_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        api_key=SecretStr(settings.OPENAI_API_KEY),
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
        max_retries=MAX_RETRIES,
        timeout=TIMEOUT_SECONDS,
    )
