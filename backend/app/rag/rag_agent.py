from functools import lru_cache
from typing import Any
from uuid import UUID

from langchain.agents import create_agent
from langchain.agents.middleware import Runtime, after_agent
from langchain_core.messages import AIMessage, HumanMessage
from sqlmodel import Session

from app.core.logging import get_logger
from app.integrations.openai_client import get_agent_model
from app.models import QuestionBase
from app.rag.citations import get_citations
from app.rag.embedding import EmbeddingResponseError
from app.rag.rag_tools import (
    SEARCH_ERROR_EMBEDDING,
    SEARCH_ERROR_EMBEDDING_PROVIDER,
    search_user_sources,
)
from app.schemas.langchain_dtos import RagAgentContext, RagAgentResponse, RagAgentState

logger = get_logger(__name__)

SYSTEM_PROMPT = """
Eres un asistente para periodistas que trabaja con las fuentes del usuario.

REGLAS:
- Usa la herramienta search_user_sources cuando la respuesta dependa de información
  concreta, privada o temporal que pueda estar en las fuentes del usuario.
- Responde directamente, sin buscar, ante preguntas generales o de conocimiento
  que no necesiten consultar esas fuentes.
- Si la pregunta está incompleta y falta información para entenderla no supongas
  datos ni respondas con información genérica.
- Cuando busques, basa la respuesta únicamente en la evidencia recuperada e indica
  que no encontraste información suficiente si la búsqueda devuelve resultados
  inútiles o contradictorios.
- No inventes ni completes con conocimiento general los hechos específicos.
- No menciones el funcionamiento interno de las herramientas ni del sistema RAG.
"""

NO_ANSWER_MESSAGE = "No pude generar una respuesta en este momento."


def _extract_answer(messages: object) -> str:
    # object es preferible para un dato desconocido que el código va a validar, porque el get("messages") podría traer None en vez de una lista por ejemplo
    # Any cuando renunciamos a esas comprobaciones
    if not isinstance(messages, list):
        return ""

    # Recorre la lista al revés porque el último mensaje suele ser la respuesta final del agente y devuelve la respuesta del primer AIMessage que encuentre
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            # El último AIMessage puede ser una llamada a herramienta en vez de la respuesta al usuario
            if message.tool_calls:
                return ""
            return message.text  # .text accede al contenido del AIMessage asegurándolo como string
    return ""


# Middleware de LangChain posterior al agente para revisar que el estado final recoja una respuesta válida
# Se ejecuta dentro del ainvoke antes de que exista result, que más adelante se
@after_agent(state_schema=RagAgentState, name="ensure_final_answer")
def ensure_final_answer(
    state: RagAgentState,
    _runtime: Runtime[RagAgentContext],  # El contexto se omite pero el middleware lo exige en su firma
) -> dict[str, Any] | None:
    if _extract_answer(state["messages"]):
        return None
    logger.warning("Agent completed without a valid final answer")
    return {"messages": [AIMessage(content=NO_ANSWER_MESSAGE)]}  # Esto actualiza el estado pero no hace falta añadir Command porque no se necesita dirigir el flujo a otro paso más


@lru_cache(maxsize=1)  # Al cachearlo se evita volver a crear al agente compilando LangChain en cada petición
def get_rag_agent() -> Any:  # Any para evitar errores con el tipo de retorno ya que mezcla genéricos de la librería de LangChain con lo declarado/esperado por nosotros
    return create_agent(
        model=get_agent_model(),
        tools=[search_user_sources],
        system_prompt=SYSTEM_PROMPT,
        middleware=[ensure_final_answer],
        context_schema=RagAgentContext,
        state_schema=RagAgentState,
    )


class RagAgentService:
    """Orquesta al agente que decide entre responder o buscar en los correos."""

    def __init__(self, max_agent_steps: int = 6) -> None:
        # Medida de seguridad de los pasos que el agente puede ejecutar para prevenir bucles infinitos
        self.max_agent_steps = max_agent_steps

    async def agent_answer(
        self,
        question: QuestionBase,
        *,  # Esta firma deja más clara la separación del dato principal de las dependencias de ejecución
        session: Session,
        user_id: UUID,
    ) -> RagAgentResponse:
        logger.info("Answering question through the agent")

        try:
            result: Any = await get_rag_agent().ainvoke(
                # Propoción del state inicial del agente
                {
                    "messages": [HumanMessage(content=question)],
                    "similar_chunks": [],
                    "augmented_chunk_groups": [],
                    "search_count": 0,
                    "search_error_code": None,
                    "search_error_message": None,
                },
                context=RagAgentContext(session=session, user_id=user_id),
                config={"recursion_limit": self.max_agent_steps},  # Se añade posteriormente al cacheo del agente por si quisiesemos cambiar el valor para esta instancia
            )
        # Los errores se terminan de transformar aquí, RagService() no los recoge porque ya no necesita hacerles nada más y estos suben implícitamente hasta la API para convertirse en errores HTTP
        except Exception as exc:
            logger.warning("Agent execution failed: %s", exc)
            raise RuntimeError("Agent execution failed") from exc

        if not isinstance(result, dict):  # Aunque el valor de salida del result sea Any, se valida que este venga como diccionario
            logger.warning("Agent returned an unexpected result: %s", type(result))
            raise RuntimeError("Agent execution failed")

        error_code = result.get("search_error_code")
        error_message = result.get("search_error_message")

        if error_code == SEARCH_ERROR_EMBEDDING:
            raise EmbeddingResponseError(error_message or "Embedding service failed")
        if error_code == SEARCH_ERROR_EMBEDDING_PROVIDER:
            raise RuntimeError(error_message or "Embedding provider failed")
        if error_code is not None:
            raise RuntimeError(error_message or "Search tool failed")

        messages = result.get("messages")
        answer = _extract_answer(messages)  # @after_agent ha validado, aquí se vuelve a usar _extract_answer() para reaprovechar lógica en la asignación porque el último mensaje de messages podría ser una llamada a herramienta

        citations = get_citations(
            result.get("similar_chunks") or [],
            result.get("augmented_chunk_groups") or [],
        )

        return RagAgentResponse(answer=answer, citations=citations)
