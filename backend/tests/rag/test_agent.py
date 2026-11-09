from collections.abc import Generator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import ChunkCreate, Mail
from app.rag import rag_agent as agent_module
from app.rag import rag_tools as tools_module
from app.rag.embedding import EmbeddingResponseError, EmbeddingService
from app.rag.rag_agent import RagAgentService
from app.rag.retrieval import RetrievalService
from app.schemas.langchain_dtos import RagAgentContext, RagAgentResponse, RagAgentState
from app.services.rag_service import RagService
from tests.utils.mail import create_random_mail
from tests.utils.user import create_random_user


@pytest.fixture(autouse=True)
def clear_agent_cache() -> Generator[None]:
    agent_module.get_rag_agent.cache_clear()
    yield
    agent_module.get_rag_agent.cache_clear()


def make_runtime(
    session: Session,
    user_id: UUID,
    *,
    state: dict[str, Any] | None = None,
    tool_call_id: str = "test-tool-call",
) -> ToolRuntime[RagAgentContext, RagAgentState]:
    runtime_state: dict[str, Any] = {
        "messages": [],
        "similar_chunks": [],
        "augmented_chunk_groups": [],
        "search_count": 0,
        "search_error_code": None,
        "search_error_message": None,
    }
    if state is not None:
        runtime_state.update(state)

    return ToolRuntime(
        state=cast(RagAgentState, runtime_state),
        context=RagAgentContext(session=session, user_id=user_id),
        config={},
        stream_writer=lambda _: None,
        tool_call_id=tool_call_id,
        store=None,
    )


async def run_tool(
    search_tool: Any,
    query: str,
    session: Session,
    user_id: UUID,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = make_runtime(session, user_id, state=state)
    command = await search_tool.coroutine(query, runtime=runtime)
    return cast(dict[str, Any], command.update)


def install_fake_agent(
    monkeypatch: pytest.MonkeyPatch,
    behavior: Any,
) -> dict[str, Any]:
    created: dict[str, Any] = {}

    def fake_create_agent(
        *,
        model: object,
        tools: list[Any],
        system_prompt: str,
        context_schema: object,
        state_schema: object,
    ) -> Any:
        class FakeAgent:
            async def ainvoke(
                self,
                agent_input: dict[str, Any],
                *,
                context: RagAgentContext,
                config: dict[str, Any],
            ) -> dict[str, Any]:
                return cast(
                    dict[str, Any], await behavior(tools, agent_input, context, config)
                )

        created["model"] = model
        created["tools"] = tools
        created["system_prompt"] = system_prompt
        created["context_schema"] = context_schema
        created["state_schema"] = state_schema
        return FakeAgent()

    monkeypatch.setattr(agent_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(
        agent_module,
        "get_agent_model",
        lambda: ChatOpenAI(
            api_key=SecretStr("test-key"),
            model="gpt-4o-mini",
        ),
    )
    return created


def fake_embedding() -> list[float]:
    return [1.0] + [0.0] * (settings.EMBEDDING_DIMENSIONS - 1)


def create_mail_with_chunk(db: Session, user_id: UUID, content: str) -> Mail:
    mail = create_random_mail(db, user_id=user_id, body=None)
    crud.create_chunks(
        session=db,
        source_id=mail.source_id,
        chunks_in=[
            ChunkCreate(
                content=content,
                position=1,
                embedding=fake_embedding(),
            )
        ],
    )
    return mail


def test_agent_is_created_with_langchain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_module,
        "get_agent_model",
        lambda: ChatOpenAI(
            api_key=SecretStr("test-key"),
            model="gpt-4o-mini",
        ),
    )

    agent = agent_module.get_rag_agent()

    assert agent is not None


def test_agent_model_is_configured_for_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    agent_module.get_agent_model.cache_clear()

    try:
        model = agent_module.get_agent_model()
    finally:
        agent_module.get_agent_model.cache_clear()

    assert model.temperature == 0.1
    assert model.max_retries == 1
    assert model.request_timeout == 45.0
    assert model.model_kwargs["parallel_tool_calls"] is False


@pytest.mark.anyio
async def test_agent_answers_directly_without_searching(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def behavior(
        _tools: list[Any],
        agent_input: dict[str, Any],
        _context: RagAgentContext,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        assert agent_input["messages"][0].content == "¿Cuánto es 2 + 2?"
        return {
            **agent_input,
            "messages": [*agent_input["messages"], AIMessage(content="4")],
        }

    created = install_fake_agent(monkeypatch, behavior)

    response = await RagAgentService().agent_answer(
        "¿Cuánto es 2 + 2?",
        session=db,
        user_id=uuid4(),
    )

    assert response.answer == "4"
    assert response.citations == []
    assert len(created["tools"]) == 1
    assert created["context_schema"] is RagAgentContext
    assert created["state_schema"] is RagAgentState


@pytest.mark.anyio
async def test_agent_search_builds_citations_from_user_evidence(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_user = create_random_user(db)
    second_user = create_random_user(db)
    assert first_user.id is not None
    assert second_user.id is not None

    first_mail = create_mail_with_chunk(
        db,
        first_user.id,
        "La rueda de prensa del primer usuario fue el martes.",
    )
    second_mail = create_mail_with_chunk(
        db,
        second_user.id,
        "Contenido privado del segundo usuario.",
    )

    async def fake_generate_question_embedding(
        _self: object, _question: str
    ) -> list[float]:
        return fake_embedding()

    monkeypatch.setattr(
        EmbeddingService,
        "generate_question_embedding",
        fake_generate_question_embedding,
    )

    max_agent_steps = 4

    async def behavior(
        tools: list[Any],
        agent_input: dict[str, Any],
        context: RagAgentContext,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        assert config["recursion_limit"] == max_agent_steps
        assert context.session is db
        assert context.user_id == first_user.id

        update = await run_tool(
            tools[0],
            agent_input["messages"][0].content,
            db,
            first_user.id,
            state=agent_input,
        )
        state = {**agent_input, **update}
        tool_message = update["messages"][-1]
        assert isinstance(tool_message, ToolMessage)

        return {
            **state,
            "messages": [
                *agent_input["messages"],
                *update["messages"],
                AIMessage(content=str(tool_message.content)),
            ],
        }

    install_fake_agent(monkeypatch, behavior)

    response = await RagAgentService(max_agent_steps=max_agent_steps).agent_answer(
        "¿Cuándo fue la rueda de prensa?",
        session=db,
        user_id=first_user.id,
    )

    assert "La rueda de prensa del primer usuario fue el martes." in response.answer
    assert len(response.citations) == 1
    assert response.citations[0].source_id == first_mail.source_id
    assert response.citations[0].details["mail_id"] == first_mail.id
    assert all(
        citation.source_id != second_mail.source_id for citation in response.citations
    )


@pytest.mark.anyio
async def test_agent_search_without_results_has_no_citations(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_random_user(db)
    assert user.id is not None

    async def fake_generate_question_embedding(
        _self: object, _question: str
    ) -> list[float]:
        return fake_embedding()

    monkeypatch.setattr(
        EmbeddingService,
        "generate_question_embedding",
        fake_generate_question_embedding,
    )

    async def behavior(
        tools: list[Any],
        agent_input: dict[str, Any],
        _context: RagAgentContext,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        update = await run_tool(
            tools[0],
            "nota de prensa",
            db,
            user.id,
            state=agent_input,
        )
        assert update["search_error_code"] is None
        assert update["search_error_message"] is None
        state = {**agent_input, **update}
        tool_message = update["messages"][-1]
        assert isinstance(tool_message, ToolMessage)

        return {
            **state,
            "messages": [
                *agent_input["messages"],
                *update["messages"],
                AIMessage(content=str(tool_message.content)),
            ],
        }

    install_fake_agent(monkeypatch, behavior)

    response = await RagAgentService().agent_answer(
        "¿Qué dijo el remitente sobre la nota de prensa?",
        session=db,
        user_id=user.id,
    )

    assert "No se encontró información" in response.answer
    assert response.citations == []


@pytest.mark.anyio
async def test_search_tool_embedding_error_is_propagated(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_random_user(db)
    assert user.id is not None

    async def failing_generate_question_embedding(
        _self: object, _question: str
    ) -> list[float]:
        raise EmbeddingResponseError("Embedding dimensions mismatch")

    monkeypatch.setattr(
        EmbeddingService,
        "generate_question_embedding",
        failing_generate_question_embedding,
    )

    async def behavior(
        tools: list[Any],
        agent_input: dict[str, Any],
        _context: RagAgentContext,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        update = await run_tool(
            tools[0],
            "nota de prensa",
            db,
            user.id,
            state=agent_input,
        )
        assert update["search_error_code"] == tools_module.SEARCH_ERROR_EMBEDDING
        assert update["search_error_message"] == "Embedding dimensions mismatch"
        state = {**agent_input, **update}
        return {
            **state,
            "messages": [*agent_input["messages"], *update["messages"]],
        }

    install_fake_agent(monkeypatch, behavior)

    with pytest.raises(EmbeddingResponseError, match="Embedding dimensions mismatch"):
        await RagAgentService().agent_answer(
            "¿Qué dijo el remitente sobre la nota de prensa?",
            session=db,
            user_id=user.id,
        )


@pytest.mark.anyio
async def test_search_tool_generic_error_is_propagated(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_random_user(db)
    assert user.id is not None

    async def fake_generate_question_embedding(
        _self: object, _question: str
    ) -> list[float]:
        return fake_embedding()

    def failing_retrieve_chunks(_self: object, **_kwargs: Any) -> list[Any]:
        raise RuntimeError("Database unavailable")

    monkeypatch.setattr(
        EmbeddingService,
        "generate_question_embedding",
        fake_generate_question_embedding,
    )
    monkeypatch.setattr(
        RetrievalService,
        "retrieve_chunks",
        failing_retrieve_chunks,
    )

    async def behavior(
        tools: list[Any],
        agent_input: dict[str, Any],
        _context: RagAgentContext,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        update = await run_tool(
            tools[0],
            "nota de prensa",
            db,
            user.id,
            state=agent_input,
        )
        assert update["search_error_code"] == tools_module.SEARCH_ERROR_FAILED
        assert update["search_error_message"] == "Database unavailable"
        state = {**agent_input, **update}
        return {
            **state,
            "messages": [*agent_input["messages"], *update["messages"]],
        }

    install_fake_agent(monkeypatch, behavior)

    with pytest.raises(RuntimeError, match="Database unavailable"):
        await RagAgentService().agent_answer(
            "¿Qué dijo el remitente sobre la nota de prensa?",
            session=db,
            user_id=user.id,
        )


@pytest.mark.anyio
async def test_search_tool_embedding_provider_error_is_propagated(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_random_user(db)
    assert user.id is not None

    async def failing_generate_question_embedding(
        _self: object, _question: str
    ) -> list[float]:
        raise RuntimeError("Question embedding failed")

    monkeypatch.setattr(
        EmbeddingService,
        "generate_question_embedding",
        failing_generate_question_embedding,
    )

    async def behavior(
        tools: list[Any],
        agent_input: dict[str, Any],
        _context: RagAgentContext,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        update = await run_tool(
            tools[0],
            "nota de prensa",
            db,
            user.id,
            state=agent_input,
        )
        assert (
            update["search_error_code"]
            == tools_module.SEARCH_ERROR_EMBEDDING_PROVIDER
        )
        assert update["search_error_message"] == "Question embedding failed"
        state = {**agent_input, **update}
        return {
            **state,
            "messages": [*agent_input["messages"], *update["messages"]],
        }

    install_fake_agent(monkeypatch, behavior)

    with pytest.raises(RuntimeError, match="Question embedding failed"):
        await RagAgentService().agent_answer(
            "¿Qué dijo el remitente sobre la nota de prensa?",
            session=db,
            user_id=user.id,
        )


@pytest.mark.anyio
async def test_agent_execution_error_is_wrapped(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def behavior(
        _tools: list[Any],
        _agent_input: dict[str, Any],
        _context: RagAgentContext,
        _config: dict[str, Any],
    ) -> dict[str, Any]:
        raise ValueError("boom")

    install_fake_agent(monkeypatch, behavior)

    with pytest.raises(RuntimeError, match="Agent execution failed") as exc_info:
        await RagAgentService().agent_answer(
            "Pregunta",
            session=db,
            user_id=uuid4(),
        )

    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.anyio
async def test_search_tool_stops_after_max_searches(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_random_user(db)
    assert user.id is not None

    async def fake_generate_question_embedding(
        _self: object, _question: str
    ) -> list[float]:
        return fake_embedding()

    monkeypatch.setattr(
        EmbeddingService,
        "generate_question_embedding",
        fake_generate_question_embedding,
    )

    update = await run_tool(
        tools_module.search_user_sources,
        "nota de prensa",
        db,
        user.id,
        state={"search_count": tools_module.MAX_SEARCHES},
    )

    tool_message = update["messages"][-1]
    assert isinstance(tool_message, ToolMessage)
    assert "No se pueden realizar más búsquedas" in str(tool_message.content)
    assert "search_count" not in update


@pytest.mark.anyio
async def test_rag_service_persists_direct_answer_without_citations(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = create_random_user(db)
    assert user.id is not None

    class FakeRagAgentService:
        async def agent_answer(
            self,
            _question: str,
            *,
            session: Session,
            user_id: UUID,
        ) -> RagAgentResponse:
            assert session is db
            assert user_id == user.id
            return RagAgentResponse(answer="Respuesta directa.", citations=[])

    monkeypatch.setattr(
        "app.services.rag_service.RagAgentService",
        FakeRagAgentService,
    )

    question = await RagService(session=db).rag_answer("Pregunta general", user.id)

    assert question.answer == "Respuesta directa."
    assert question.citations == []
