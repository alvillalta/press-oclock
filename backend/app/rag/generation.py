import logging

from app.core.config import settings
from app.core.openai_client import get_openai_client
from app.models import QuestionBase
from openai.types.chat import ChatCompletionMessageParam  # Formato de salida de la API de OpenAI

logger = logging.getLogger(__name__)

client = get_openai_client()


def build_messages(question: str, context: str) -> list[ChatCompletionMessageParam]:
    system_prompt = """
        Eres un asistente experto.

        Responde únicamente utilizando la información
        proporcionada en el contexto.

        Si la respuesta no aparece en el contexto,
        indica que no dispones de información suficiente.
    """

    user_prompt = f"""
        CONTEXTO:

        {context}

        PREGUNTA:

        {question}
    """

    # Formato de entrada para la API de OpenAI
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def ask_question(question: QuestionBase, context: str) -> str:
    messages = build_messages(question, context)
    response = await client.chat.completions.create(
        model=settings.GENERATION_MODEL,
        messages=messages,
    )
    return response.choices[0].message.content or ""


class GenerationService:
    """Servicio para generar respuestas utilizando el modelo RAG."""

    async def generate_answer(self, question_in: str, context: str) -> str:
        return await ask_question(question_in, context)

    
    