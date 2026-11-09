import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any

from app.models import (
    AttachmentUpload,
    FinalizedMailResult,
    MailStageCreate,
    MailStagePublic,
)
from app.services.mail_ingestion_service import MailIngestionService
from app.services.mail_triage_service import MailTriageService, _bound_body
from app.triage.triage_policy import (
    MailTriageDecision,
    decide_triage,
)


def test_triage_policy_uses_default_thresholds() -> None:
    decision = decide_triage(
        {
            "body_sufficient": 0.9,
            "is_spam": 0.1,
            "is_toxic": 0.2,
            "is_hazard": 0.1,
        }
    )

    assert decision.status == "continue"


def test_bound_body_truncates_long_messages() -> None:
    body = "a" * 50_000

    bounded = _bound_body(body)

    assert len(bounded) < len(body)
    assert "[...]" in bounded


def test_triage_policy_continues_when_risks_are_low() -> None:
    decision = decide_triage(
        {
            "body_sufficient": 0.9,
            "is_spam": 0.1,
            "is_toxic": 0.2,
            "is_hazard": 0.05,
        },
        risk_threshold=0.7,
        review_threshold=0.3,
        min_body_sufficiency=0.3,
    )

    assert decision.status == "continue"


def test_triage_policy_blocks_above_the_risk_threshold() -> None:
    decision = decide_triage(
        {
            "body_sufficient": 0.95,
            "is_spam": 0.1,
            "is_toxic": 0.2,
            "is_hazard": 0.71,
        },
        risk_threshold=0.7,
        review_threshold=0.3,
        min_body_sufficiency=0.3,
    )

    assert decision.status == "blocked"
    assert decision.blocked_by == "is_hazard"


def test_triage_policy_reviews_risks_at_the_threshold() -> None:
    decision = decide_triage(
        {
            "body_sufficient": 0.95,
            "is_spam": 0.7,
            "is_toxic": 0.2,
            "is_hazard": 0.1,
        },
        risk_threshold=0.7,
        review_threshold=0.3,
        min_body_sufficiency=0.3,
    )

    assert decision.status == "review"
    assert decision.reason == "uncertain_risk"


def test_triage_policy_reviews_insufficient_body_first() -> None:
    decision = decide_triage(
        {
            "body_sufficient": 0.3,
            "is_spam": 0.99,
            "is_toxic": 0.99,
            "is_hazard": 0.99,
        },
        risk_threshold=0.7,
        review_threshold=0.3,
        min_body_sufficiency=0.3,
    )

    assert decision.status == "review"
    assert decision.reason == "insufficient_body"


def test_triage_policy_fails_open_on_invalid_answers() -> None:
    decision = decide_triage(
        {"body_sufficient": 0.9, "is_spam": 0.1},
        risk_threshold=0.7,
        review_threshold=0.3,
        min_body_sufficiency=0.3,
    )

    assert decision.status == "failed"


class FakeJevClient:
    def __init__(
        self,
        probabilities: Mapping[str, float] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self.probabilities = probabilities or {}
        self.fail = fail
        self.calls = 0
        self.last_state: dict[str, Any] = {}

    async def answer_nouls(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> dict[str, float]:
        self.calls += 1
        self.last_state = dict(state)
        if self.fail:
            raise RuntimeError("Jev unavailable")
        assert set(questions) == {
            "body_sufficient",
            "is_spam",
            "is_toxic",
            "is_hazard",
        }
        return dict(self.probabilities)


def test_mail_triage_service_skips_jev_for_an_empty_body() -> None:
    client = FakeJevClient(fail=True)
    service = MailTriageService(client=client)  # type: ignore[arg-type]

    decision = asyncio.run(
        service.screen_mail(sender="sender@example.com", subject="Subject", body=" ")
    )

    assert decision.status == "review"
    assert decision.reason == "empty_body"
    assert client.calls == 0


def test_mail_triage_service_fails_open_when_jev_fails() -> None:
    client = FakeJevClient(fail=True)
    service = MailTriageService(client=client)  # type: ignore[arg-type]

    decision = asyncio.run(
        service.screen_mail(
            sender="sender@example.com",
            subject="Subject",
            body="A substantive message body.",
        )
    )

    assert decision.status == "failed"
    assert client.calls == 1


class FakeStage:
    id = uuid.uuid4()
    external_id = "mail-external-id"
    status = "completed"
    mail_id = uuid.uuid4()
    result_summary: dict[str, Any] = {}


class FakeSession:
    def get(self, _model: Any, _identifier: Any) -> FakeStage:
        return FakeStage()


class FakeStorage:
    pass


class FakeTriageService:
    def __init__(self, decision: MailTriageDecision) -> None:
        self.decision = decision
        self.calls = 0

    async def screen_mail(
        self,
        *,
        sender: str,
        subject: str | None,
        body: str | None,
    ) -> MailTriageDecision:
        self.calls += 1
        return self.decision


class IngestTestService(MailIngestionService):
    def __init__(self, triage: FakeTriageService) -> None:
        super().__init__(
            session=FakeSession(),  # type: ignore[arg-type]
            storage=FakeStorage(),  # type: ignore[arg-type]
            triage_service=triage,  # type: ignore[arg-type]
        )
        self.staged_external_ids: list[str] = []
        self.omitted_attachment_summary: list[dict[str, str]] | None = None

    def start_ingestion(
        self, *, mail_in: MailStageCreate, user_id: uuid.UUID
    ) -> MailStagePublic:
        return MailStagePublic(
            ingestion_id=uuid.uuid4(),
            external_id=mail_in.external_id,
            status="receiving",
        )

    async def stage_attachment(
        self,
        *,
        ingestion_id: uuid.UUID,
        user_id: uuid.UUID,
        external_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        oversize: bool = False,
        measured_size: int,
    ) -> Any:
        self.staged_external_ids.append(external_id)
        return None

    async def finalize_ingestion(
        self,
        ingestion_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        omitted_attachment_summary: list[dict[str, str]] | None = None,
    ) -> FinalizedMailResult:
        self.omitted_attachment_summary = omitted_attachment_summary
        return FinalizedMailResult(mail_id=uuid.uuid4(), finalized_in_this_call=False)


def _mail_in() -> MailStageCreate:
    return MailStageCreate(
        external_id="external-id",
        sender="sender@example.com",
        received_at=datetime.now(UTC),
        subject="Subject",
        body="A substantive message body.",
    )


def _attachment_upload() -> AttachmentUpload:
    return AttachmentUpload(
        external_id="attachment-1",
        filename="brief.pdf",
        mime_type="application/pdf",
        content=b"content",
        oversize=False,
        measured_size=7,
    )


def test_ingest_does_not_read_attachments_when_triage_blocks() -> None:
    triage = FakeTriageService(
        MailTriageDecision(
            status="blocked", reason="risk_detected", blocked_by="is_spam"
        )
    )
    service = IngestTestService(triage)
    consumed: list[bool] = []

    async def attachments() -> AsyncIterator[AttachmentUpload]:
        consumed.append(True)
        yield _attachment_upload()

    result = asyncio.run(
        service.ingest_mail(
            mail_in=_mail_in(),
            user_id=uuid.uuid4(),
            attachments=attachments(),
            attachment_external_ids=["attachment-1", "attachment-2"],
        )
    )

    assert result.status == "completed"
    assert consumed == []
    assert service.staged_external_ids == []
    assert service.omitted_attachment_summary == [
        {"external_id": "attachment-1", "reason": "mail_triage_blocked"},
        {"external_id": "attachment-2", "reason": "mail_triage_blocked"},
    ]


def test_ingest_continues_with_attachments_when_triage_requires_review() -> None:
    triage = FakeTriageService(MailTriageDecision(status="review", reason="empty_body"))
    service = IngestTestService(triage)
    consumed: list[bool] = []

    async def attachments() -> AsyncIterator[AttachmentUpload]:
        consumed.append(True)
        yield _attachment_upload()

    asyncio.run(
        service.ingest_mail(
            mail_in=_mail_in(),
            user_id=uuid.uuid4(),
            attachments=attachments(),
            attachment_external_ids=["attachment-1"],
        )
    )

    assert consumed == [True]
    assert service.staged_external_ids == ["attachment-1"]
    assert service.omitted_attachment_summary == []
