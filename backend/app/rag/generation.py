from app.core.config import settings
from app.core.logging import get_logger
from app.core.openai_client import get_openai_client
from app.models import QuestionBase
from openai.types.chat import ChatCompletionMessageParam  # Formato de salida de la API de OpenAI

logger = get_logger(__name__)

client = get_openai_client()


def build_messages(question: str, context: str) -> list[ChatCompletionMessageParam]:
    """
    Construye el prompt final para el modelo de IA generativa.
    """
    logger.info("Creating the final prompt for the generative AI Model")
    
    system_prompt = """
        Eres un asistente especializado en responder preguntas a partir de información recuperada mediante un sistema RAG.

        Tu tarea es responder a la pregunta del usuario utilizando únicamente la información proporcionada en el contexto recuperado.

        REGLAS:

        - Utiliza exclusivamente la información presente en el contexto. No utilices conocimientos externos ni inventes información.
        - Si la información del contexto es insuficiente para responder con seguridad, indícalo explícitamente. No inventes nada.
        - Si el contexto contiene información contradictoria, indícalo y atribuye cada afirmación a su fuente cuando sea posible.
        - Responde de forma clara y concisa, adaptando el nivel de detalle a la pregunta.
        - No menciones el funcionamiento interno del sistema RAG.
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
    """
    Generación de la respuesta.
    """
    logger.info("Generating answer")

    messages = build_messages(question, context)
    response = await client.chat.completions.create(
        model=settings.GENERATION_MODEL,
        messages=messages,
    )
    return response.choices[0].message.content or ""


class GenerationService:
    """Servicio para generar la respuesta."""

    async def generate_answer(self, question_in: str, context: str) -> str:
        return await ask_question(question_in, context)

    
    