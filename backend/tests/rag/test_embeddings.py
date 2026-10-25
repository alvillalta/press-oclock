from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.models import ChunkBase, ChunkCreate
from app.rag import embedding
from app.rag.embedding import EmbeddingResponseError, EmbeddingService


def fake_openai_client(embedding: list[float]) -> Any:
    async def create(**_kwargs: Any) -> Any:
        return SimpleNamespace(data=[SimpleNamespace(embedding=embedding)])

    return SimpleNamespace(embeddings=SimpleNamespace(create=create))


def test_chunk_embedding_requires_configured_dimension() -> None:
    ChunkCreate(
        content="valid embedding",
        position=1,
        embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
    )

    with pytest.raises(ValidationError):
        ChunkCreate(
            content="wrong embedding dimension",
            position=1,
            embedding=[0.0] * (settings.EMBEDDING_DIMENSIONS - 1),
        )


def test_embedding_response_validator_rejects_wrong_dimension() -> None:
    with pytest.raises(EmbeddingResponseError, match=f"{settings.EMBEDDING_DIMENSIONS} dimensions"):
        embedding._validate_embedding_dimensions([0.0] * (settings.EMBEDDING_DIMENSIONS + 1))


@pytest.mark.anyio
async def test_question_embedding_response_dimension_is_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding,
        "client",
        fake_openai_client([0.0] * (settings.EMBEDDING_DIMENSIONS - 1)),
    )

    with pytest.raises(EmbeddingResponseError, match=f"{settings.EMBEDDING_DIMENSIONS} dimensions"):
        await EmbeddingService().generate_question_embedding("Question")


@pytest.mark.anyio
async def test_chunk_embedding_response_dimension_is_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding,
        "client",
        fake_openai_client([0.0] * (settings.EMBEDDING_DIMENSIONS - 1)),
    )

    with pytest.raises(EmbeddingResponseError, match=f"{settings.EMBEDDING_DIMENSIONS} dimensions"):
        await EmbeddingService(
            batch_size=1,
            overlaped_characters=100,
        ).generate_chunk_embeddings(
            chunks=[ChunkBase(content="Chunk", position=1)],
        )


@pytest.mark.anyio
async def test_chunk_embedding_response_count_mismatch_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El cliente devuelve un único embedding aunque se le envíen dos chunks
    monkeypatch.setattr(
        embedding,
        "client",
        fake_openai_client([0.0] * settings.EMBEDDING_DIMENSIONS),
    )

    with pytest.raises(EmbeddingResponseError, match="Mismatch"):
        await EmbeddingService(
            batch_size=2,
            overlaped_characters=100,
        ).generate_chunk_embeddings(
            chunks=[
                ChunkBase(content="Chunk one", position=1),
                ChunkBase(content="Chunk two", position=2),
            ],
        )


@pytest.mark.anyio
async def test_question_embedding_wraps_provider_failure_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def create(**_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        embedding,
        "client",
        SimpleNamespace(embeddings=SimpleNamespace(create=create)),
    )

    with pytest.raises(
        RuntimeError, match="Question embedding failed"
    ) as exc_info:
        await EmbeddingService().generate_question_embedding("Question")

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert calls == 1
