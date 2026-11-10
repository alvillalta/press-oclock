from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

from app.core.config import settings


# Cachea los adaptadores y sus clientes HTTP para evitar reconstruirlos en cada petición a la API
@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY),  # Lo ideal sería llevar SecretStr a config.py y aplicarlo para el resto de valores que deberían ser secretos si se hacen logs, etc.
        model="gpt-4o-mini",
        temperature=0.4,
        max_retries=2,  # 3 intentos totales
        timeout=60.0,
    )

@lru_cache(maxsize=1)
def get_agent_model() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=SecretStr(settings.OPENAI_API_KEY),
        model="gpt-4o-mini",
        temperature=0.1,
        max_retries=1,  # Reintento extra si el agente llama al modelo en uno de sus pasos
        timeout=45.0,
        model_kwargs={"parallel_tool_calls": False},  # Va de una en una para evitar concurrencia en el llamado de herramientas por parte del agente. Se tiene que pasar como argumento clave porque el proveedor OpenAI no lo reconoce directamente
    )

@lru_cache(maxsize=1)
def get_embeddings_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        api_key=SecretStr(settings.OPENAI_API_KEY),
        model="text-embedding-3-small",
        dimensions=settings.EMBEDDING_DIMENSIONS,
        max_retries=2,
        timeout=60.0,
    )
