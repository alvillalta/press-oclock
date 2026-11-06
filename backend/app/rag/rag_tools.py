from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

from app.core.logging import get_logger
from app.rag.augmentation import AugmentationService
from app.rag.embedding import EmbeddingResponseError, EmbeddingService
from app.rag.generation import format_augmented_context
from app.rag.metadata import get_metadata
from app.rag.retrieval import RetrievalService
from app.schemas.langchain_dtos import RagAgentContext, RagAgentState

logger = get_logger(__name__)

MAX_SEARCHES = 1
SEARCH_ERROR_EMBEDDING = "embedding_response"
SEARCH_ERROR_EMBEDDING_PROVIDER = "embedding_provider"
SEARCH_ERROR_FAILED = "search_failed"


@tool
async def search_user_sources(
    query: str,
    runtime: ToolRuntime[RagAgentContext, RagAgentState],
) -> Command[Any]:
    """Busca información concreta en las fuentes del usuario.

    Úsala para hechos específicos, privados o temporales que puedan estar entre sus fuentes.
    No la uses para preguntas generales que puedas responder directamente.
    """
    search_count = runtime.state.get("search_count", 0)

    if search_count >= MAX_SEARCHES:
        return Command(
            update={
                # Aquí no vienen unos "search_error_code" ni "search_error_message" propios para no sobreescribir el error real que se haya recogido en la búsqueda anterior
                "messages": [
                    ToolMessage(
                        content=(
                            """No se pueden realizar más búsquedas.
                            Usa la evidencia obtenida en la búsqueda anterior o indica que no encontraste información suficiente.
                            """
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    logger.info("Searching user sources from the agent tool")

    session = runtime.context.session
    user_id = runtime.context.user_id
    next_search_count = search_count + 1

    try:
        embedded_query = await EmbeddingService().generate_question_embedding(query)
    except EmbeddingResponseError as exc:
        logger.exception("Search tool embedding failed")
        return Command(
            update={
                "search_count": next_search_count,
                "search_error_code": SEARCH_ERROR_EMBEDDING,
                # El texto literal queda en el state; el agente solo recibe el ToolMessage genérico
                "search_error_message": str(exc),
                "messages": [
                    ToolMessage(
                        content="The search service encountered an internal error.",
                        tool_call_id=runtime.tool_call_id,
                        status="error",
                    )
                ],
            }
        )
    except RuntimeError as exc:
        logger.exception("Search tool embedding provider failed")
        return Command(
            update={
                "search_count": next_search_count,
                "search_error_code": SEARCH_ERROR_EMBEDDING_PROVIDER,
                "search_error_message": str(exc),
                "messages": [
                    ToolMessage(
                        content="The search service encountered an internal error.",
                        tool_call_id=runtime.tool_call_id,
                        status="error",
                    )
                ],
            }
        )

    try:
        similar_chunks = RetrievalService().retrieve_chunks(
            session=session,
            embedded_question=embedded_query,
            user_id=user_id,
        )

        if not similar_chunks:
            return Command(
                update={
                    "search_count": next_search_count,
                    "search_error_code": None,
                    "search_error_message": None,
                    "messages": [
                        ToolMessage(
                            content=(
                                """No se encontró información relacionada en las fuentes del usuario."""
                            ),
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )

        augmented_chunk_groups = AugmentationService().augment_chunks(
            session=session,
            similar_chunks=similar_chunks,
            user_id=user_id,
        )
        augmented_chunk_groups = get_metadata(
            session=session,
            augmented_chunk_groups=augmented_chunk_groups,
        )
    except Exception as exc:
        logger.exception("Search tool failed")
        return Command(
            update={
                "search_count": next_search_count,
                "search_error_code": SEARCH_ERROR_FAILED,
                # El texto literal queda en el state; el agente solo recibe el ToolMessage genérico
                "search_error_message": str(exc),
                "messages": [
                    ToolMessage(
                        content="The search service encountered an internal error.",
                        tool_call_id=runtime.tool_call_id,
                        status="error",
                    )
                ],
            }
        )

    # format_augmented_context() se saca fuera del try porque sería muy raro un error en ese paso
    return Command(
        update={
            "similar_chunks": similar_chunks,
            "augmented_chunk_groups": augmented_chunk_groups,
            "search_count": next_search_count,
            "search_error_code": None,
            "search_error_message": None,
            "messages": [
                ToolMessage(
                    content=format_augmented_context(augmented_chunk_groups),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )
