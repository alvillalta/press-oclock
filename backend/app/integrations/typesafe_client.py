import asyncio
from functools import lru_cache
from typing import Any

from langchain_typesafe import ClassifierRequest, Noul, TypeSafeClassifier
from pydantic import SecretStr

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 3  # intento inicial + 2 reintentos
RETRY_WAIT_SECONDS = 1.0


# Cachea el clasificador y sus clientes HTTP para reutilizarlos durante la vida del proceso
@lru_cache(maxsize=1)
def get_typesafe_classifier() -> TypeSafeClassifier:
    return TypeSafeClassifier(
        api_key=SecretStr(settings.TYPESAFE_API_KEY),
        model="jev-1.14.0",
        timeout=15.0,
    )


class TypeSafeJevClient:
    """Adaptador del clasificador de TypeSafe para los lotes de elementos a procesar."""

    async def answer_nouls(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Noul],
    ) -> dict[str, float]:
        classifier = get_typesafe_classifier()
        request: ClassifierRequest = {
            "state": dict(state),
            "questions": dict(questions),
        }

        # TypeSafeClassifier no expone todavía en su SDK un parámetro equivalente a max_retries y se tienen que hacer manualmente
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await classifier.ainvoke(request)

                # Crea un diccionario de las probabilidades declaradas en questions sobre un state que el modelo evalúa como conjunto
                return {
                    question_id: response.nouls[question_id].noul
                    for question_id in questions
                }
            except Exception as exc:
                logger.warning(
                    "Jev attempt %s/%s failed: %s",
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                )
                if attempt == MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(RETRY_WAIT_SECONDS * attempt)
