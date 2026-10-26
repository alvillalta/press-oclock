import pytest
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.extraction.chunk_indexing import ChunkIndexingService
from app.models import Chunk, ChunkBase, ChunkCreate, Source
from tests.utils.user import create_random_user


class FakeEmbeddingService:
    async def generate_chunk_embeddings(
        self, chunks: list[ChunkBase]
    ) -> list[ChunkCreate]:
        return [
            ChunkCreate(
                content=chunk.content,
                position=chunk.position,
                embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
            )
            for chunk in chunks
        ]


def _create_source_with_chunk(db: Session) -> tuple[Source, Chunk]:
    user = create_random_user(db)
    assert user.id is not None
    source = crud.create_source(session=db, origin="mail", user_id=user.id)
    db.commit()
    crud.create_chunks(
        session=db,
        chunks_in=[
            ChunkCreate(
                content="old chunk",
                position=1,
                embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
            )
        ],
        source_id=source.id,
    )
    db.commit()
    chunk = db.exec(select(Chunk).where(Chunk.source_id == source.id)).one()
    return source, chunk


@pytest.mark.anyio
async def test_index_source_text_replaces_existing_chunks(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _ = _create_source_with_chunk(db)
    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FakeEmbeddingService
    )

    await ChunkIndexingService(session=db).index_source_text(
        source_id=source.id,
        text="new chunk content",
    )

    db.expire_all()
    chunks = db.exec(select(Chunk).where(Chunk.source_id == source.id)).all()
    assert len(chunks) == 1
    assert chunks[0].content == "new chunk content"


@pytest.mark.anyio
async def test_embedding_failure_keeps_existing_chunks(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, existing_chunk = _create_source_with_chunk(db)

    class FailingEmbeddingService:
        async def generate_chunk_embeddings(
            self, chunks: list[ChunkBase]
        ) -> list[ChunkCreate]:
            raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr(
        "app.extraction.chunk_indexing.EmbeddingService", FailingEmbeddingService
    )

    with pytest.raises(RuntimeError):
        await ChunkIndexingService(session=db).index_source_text(
            source_id=source.id,
            text="new chunk content",
        )

    db.expire_all()
    chunks = db.exec(select(Chunk).where(Chunk.source_id == source.id)).all()
    assert len(chunks) == 1
    assert chunks[0].id == existing_chunk.id
    assert chunks[0].content == "old chunk"
