from datetime import datetime

from openai.types.chat import (
    ChatCompletionMessageParam,  # Formato de salida de la API de OpenAI
)

from app.core.config import settings
from app.core.logging import get_logger
from app.core.openai_client import get_openai_client
from app.models import AugmentedChunksGroup, QuestionBase

logger = get_logger(__name__)

client = get_openai_client()


def create_context(augmented_chunk_groups: list[AugmentedChunksGroup]) -> str:
    """
    Crea la parte variable del prompt para el modelo de IA generativa.
    """
    logger.info(
        "Creating the prompt context from chunk groups and their specific metadata"
    )

    source_blocks: list[str] = []
    for grouped_source_chunks in augmented_chunk_groups:
        # Añade un número por cada iteración para enumerar la fuente en el prompt de abajo
        source_number = len(source_blocks) + 1

        # Une los textos de los chunks
        joined_chunks = "\n".join(
            chunk.content for chunk in grouped_source_chunks["chunk_list"]
        )

        # details se reinicia vacío cada vez que termina el bucle
        details = []
        # Bucle para recorrer las parejas CLAVE-VALOR de los distintos diccionarios details
        for details_key, details_value in grouped_source_chunks["details"].items():
            if details_value is None:
                rendered_value = "(sin datos)"
            elif isinstance(details_value, datetime):
                rendered_value = details_value.isoformat()
            else:
                rendered_value = str(details_value)
            # Escribe el metadato en texto común legible
            details.append(f"{details_key.replace('_', ' ').title()}: {rendered_value}")
        # Une los textos de los metadatos
        details_block = "\n".join(details)
        if details_block:
            details_block = f"{details_block}\n"

        source_blocks.append(
            f"\nFUENTE {source_number}\n"
            f"Origin: {grouped_source_chunks['origin']}\n"
            f"{details_block}"
            f"Content: {joined_chunks}"
        )

    return "\n---\n".join(source_blocks)


def build_messages(question: str, prompt_context: str) -> list[ChatCompletionMessageParam]:
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

        {prompt_context}

        PREGUNTA:

        {question}
    """

    # Formato de entrada para la API de OpenAI
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def ask_question(question: QuestionBase, prompt_context: str) -> str:
    """
    Generación de la respuesta.
    """
    logger.info("Generating answer")

    messages = build_messages(question, prompt_context)
    response = await client.chat.completions.create(
        model=settings.GENERATION_MODEL,
        messages=messages,
    )
    return response.choices[0].message.content or ""


class GenerationService:
    """Servicio para construir el contexto del prompt y generar la respuesta."""

    def build_prompt_context(self, augmented_chunk_groups: list[AugmentedChunksGroup]) -> str:
        return create_context(augmented_chunk_groups)

    async def generate_answer(
        self, question_in: QuestionBase, augmented_chunk_groups: list[AugmentedChunksGroup]
    ) -> str:
        # Orquesta aquí otro método de la clase para pasar el contexto a texto plano
        prompt_context = self.build_prompt_context(augmented_chunk_groups)
        return await ask_question(question_in, prompt_context)
