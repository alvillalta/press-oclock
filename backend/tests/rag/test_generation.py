from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.models import AugmentedChunksGroup, Chunk
from app.rag import generation
from app.rag.generation import GenerationService


def completion_response(content: str | None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def fake_openai_client(create: Any) -> tuple[Any, dict[str, int]]:
    calls = {"create": 0}

    async def create_wrapper(**kwargs: Any) -> Any:
        calls["create"] += 1
        return await create(**kwargs)

    completions = SimpleNamespace(create=create_wrapper)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat), calls


def make_chunk(source_id: UUID, position: int, content: str) -> Chunk:
    return Chunk(
        source_id=source_id,
        content=content,
        position=position,
        embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
    )


def test_build_prompt_context_includes_metadata_and_content() -> None:
    source_id = uuid4()
    mail_id = uuid4()
    received_at = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    group: AugmentedChunksGroup = {
        "source_id": source_id,
        "origin": "mail",
        "details": {
            "mail_id": mail_id,
            "subject": "Asunto",
            "received_at": received_at,
            "sender": None,
        },
        "chunk_list": [
            make_chunk(source_id, 1, "Primer chunk."),
            make_chunk(source_id, 2, "Segundo chunk."),
        ],
    }

    context = GenerationService().build_prompt_context([group])

    assert "FUENTE 1" in context
    assert "Origin: mail" in context
    assert f"Mail Id: {mail_id}" in context
    assert "Subject: Asunto" in context
    assert f"Received At: {received_at.isoformat()}" in context
    assert "Sender: (sin datos)" in context
    assert "Content: Primer chunk.\nSegundo chunk." in context


def test_build_prompt_context_separates_multiple_sources() -> None:
    first_source_id = uuid4()
    second_source_id = uuid4()
    groups: list[AugmentedChunksGroup] = [
        {
            "source_id": first_source_id,
            "origin": "mail",
            "details": {},
            "chunk_list": [make_chunk(first_source_id, 1, "Uno.")],
        },
        {
            "source_id": second_source_id,
            "origin": "mail",
            "details": {},
            "chunk_list": [make_chunk(second_source_id, 1, "Dos.")],
        },
    ]

    context = GenerationService().build_prompt_context(groups)

    assert "FUENTE 1" in context
    assert "FUENTE 2" in context
    assert "\n---\n" in context


@pytest.mark.anyio
async def test_generation_succeeds_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def create(**_kwargs: Any) -> Any:
        return completion_response("Respuesta")

    client, calls = fake_openai_client(create)
    monkeypatch.setattr(generation, "client", client)

    answer = await GenerationService().generate_answer("Pregunta", [])

    assert answer == "Respuesta"
    assert calls["create"] == 1


@pytest.mark.anyio
async def test_generation_wraps_provider_failure_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def create(**_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    client, calls = fake_openai_client(create)
    monkeypatch.setattr(generation, "client", client)

    with pytest.raises(
        RuntimeError, match="Answer generation failed"
    ) as exc_info:
        await GenerationService().generate_answer("Pregunta", [])

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert calls["create"] == 1


@pytest.mark.anyio
async def test_generation_empty_answer_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def create(**_kwargs: Any) -> Any:
        return completion_response(None)

    client, calls = fake_openai_client(create)
    monkeypatch.setattr(generation, "client", client)

    answer = await GenerationService().generate_answer("Pregunta", [])

    assert answer == ""
    assert calls["create"] == 1
