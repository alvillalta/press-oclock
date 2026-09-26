from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models import Chunk, Mail, Source
from app.rag.retrieval_augmentation import group_chunks, merge_windows
from app.rag.sources import get_sources


def make_chunk(source_id: UUID) -> Chunk:
    return Chunk(
        source_id=source_id,
        content="A relevant chunk.",
        position=1,
        embedding=[0.0] * 1536,
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
    received_at = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    chunk = make_chunk(source_id)
    source = Source(id=source_id, origin="mail")
    mail = Mail(
        id=mail_id,
        subject="Subject",
        sender="sender@example.com",
        received_at=received_at,
        user_id=uuid4(),
        source_id=source_id,
    )

    grouped_chunks = group_chunks(
        [(chunk, source, mail)],
        [(source_id, 1, 1)],
    )
    citations = get_sources([chunk], grouped_chunks)

    assert len(citations) == 1
    citation = citations[0].model_dump(mode="json")
    assert citation["source_id"] == str(source_id)
    assert citation["origin"] == "mail"
    assert citation["mail_id"] == str(mail_id)
    serialized_received_at = datetime.fromisoformat(
        citation["received_at"].replace("Z", "+00:00")
    )
    assert serialized_received_at == received_at
    assert citation["content"] == chunk.content
