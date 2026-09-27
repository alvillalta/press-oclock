from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import Chunk, ChunkCreate, Mail, Source
from app.rag.retrieval_augmentation import (
    augment_chunks,
    group_chunks,
    merge_windows,
    retrieve_chunks,
)
from app.rag.sources import get_sources, load_source_details
from tests.utils.mail import create_random_mail
from tests.utils.user import create_random_user


def make_chunk(source_id: UUID) -> Chunk:
    return Chunk(
        source_id=source_id,
        content="A relevant chunk.",
        position=1,
        embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
    )


def test_merge_windows_keeps_different_sources_separate() -> None:
    first_source_id = uuid4()
    second_source_id = uuid4()

    windows = merge_windows(
        [
            (second_source_id, 1, 2),
            (first_source_id, 3, 4),
            (first_source_id, 1, 2),
        ]
    )
    ordered_source_ids = sorted((first_source_id, second_source_id))

    assert windows == [
        (source_id, 1, 4 if source_id == first_source_id else 2)
        for source_id in ordered_source_ids
    ]


def test_citations_use_source_and_received_at_fields() -> None:
    source_id = uuid4()
    mail_id = uuid4()
    user_id = uuid4()
    received_at = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    chunk = make_chunk(source_id)
    source = Source(id=source_id, origin="mail", user_id=user_id)
    mail = Mail(
        id=mail_id,
        subject="Subject",
        sender="sender@example.com",
        received_at=received_at,
        user_id=user_id,
        source_id=source_id,
    )

    grouped_chunks = group_chunks(
        [(chunk, source)],
        [(source_id, 1, 1)],
    )
    class FakeResult:
        def all(self) -> list[Mail]:
            return [mail]

    class FakeSession:
        calls = 0

        def exec(self, _statement: object) -> FakeResult:
            self.calls += 1
            return FakeResult()

    session = FakeSession()
    enriched_groups = load_source_details(
        session=session, source_groups=grouped_chunks  # type: ignore[arg-type]
    )
    assert session.calls == 1

    citations = get_sources([chunk], enriched_groups)

    assert len(citations) == 1
    citation = citations[0].model_dump(mode="json")
    assert citation["source_id"] == str(source_id)
    assert citation["origin"] == "mail"
    assert citation["details"]["mail_id"] == str(mail_id)
    serialized_received_at = datetime.fromisoformat(
        citation["details"]["received_at"].replace("Z", "+00:00")
    )
    assert serialized_received_at == received_at
    assert citation["content"] == chunk.content


def test_retrieval_and_expansion_are_scoped_to_source_owner(db: Session) -> None:
    first_user = create_random_user(db)
    second_user = create_random_user(db)
    assert first_user.id is not None
    assert second_user.id is not None

    first_mail = create_random_mail(db, user_id=first_user.id, body=None)
    second_mail = create_random_mail(db, user_id=second_user.id, body=None)
    embedding = [1.0] + [0.0] * (settings.EMBEDDING_DIMENSIONS - 1)

    for mail in (first_mail, second_mail):
        crud.create_chunks(
            session=db,
            source_id=mail.source_id,
            chunks_in=[
                ChunkCreate(
                    content="User-scoped chunk.",
                    position=1,
                    embedding=embedding,
                )
            ],
        )

    first_user_chunks = retrieve_chunks(
        session=db,
        embedded_question=embedding,
        user_id=first_user.id,
        chunks_limit=10,
    )
    assert {chunk.source_id for chunk in first_user_chunks} == {first_mail.source_id}

    second_user_chunk = db.exec(
        select(Chunk).where(Chunk.source_id == second_mail.source_id)
    ).one()
    assert (
        augment_chunks(
            session=db,
            similar_chunks=[second_user_chunk],
            user_id=first_user.id,
            chunks_range=1,
        )
        == []
    )
