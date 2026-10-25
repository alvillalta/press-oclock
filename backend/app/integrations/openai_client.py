from functools import lru_cache

from openai import AsyncOpenAI

from app.core.config import settings


OPENAI_MAX_RETRIES = 2  # 2 reintentos del proveedor (OpenAI) equivalen a 3 intentos totales
OPENAI_TIMEOUT_SECONDS = 60.0


# Cachea el cliente OpenAI
@lru_cache
def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        max_retries=OPENAI_MAX_RETRIES,
        timeout=OPENAI_TIMEOUT_SECONDS,
    )
