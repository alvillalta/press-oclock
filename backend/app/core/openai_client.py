from functools import lru_cache
from openai import AsyncOpenAI
from app.core.config import settings

@lru_cache
def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)