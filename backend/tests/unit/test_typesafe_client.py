import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_typesafe import Noul

import app.integrations.typesafe_client as typesafe_client


class FakeClassifier:
    def __init__(self, noul: float, *, failures: int = 0) -> None:
        self.noul = noul
        self.failures = failures
        self.calls = 0
        self.request: dict[str, Any] | None = None

    async def ainvoke(self, request: dict[str, Any]) -> Any:
        self.calls += 1
        self.request = request
        if self.calls <= self.failures:
            raise RuntimeError("Jev unavailable")
        return SimpleNamespace(nouls={"is_spam": SimpleNamespace(noul=self.noul)})


def test_answer_nouls_returns_probabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classifier = FakeClassifier(0.8)
    monkeypatch.setattr(typesafe_client, "get_typesafe_classifier", lambda: classifier)
    client = typesafe_client.TypeSafeJevClient()

    result = asyncio.run(
        client.answer_nouls(
            state={"body": "A substantive message."},
            questions={"is_spam": Noul(instructions="Is this spam?")},
        )
    )

    assert result == {"is_spam": 0.8}
    assert classifier.request is not None
    assert classifier.request["state"] == {"body": "A substantive message."}
    assert set(classifier.request["questions"]) == {"is_spam"}


def test_answer_nouls_retries_with_linear_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classifier = FakeClassifier(0.8, failures=2)
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(typesafe_client, "get_typesafe_classifier", lambda: classifier)
    client = typesafe_client.TypeSafeJevClient()

    result = asyncio.run(
        client.answer_nouls(
            state={"body": "A substantive message."},
            questions={"is_spam": Noul(instructions="Is this spam?")},
        )
    )

    assert result == {"is_spam": 0.8}
    assert classifier.calls == 3
    assert delays == [1.0, 2.0]


def test_answer_nouls_raises_after_two_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classifier = FakeClassifier(0.8, failures=3)
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(typesafe_client, "get_typesafe_classifier", lambda: classifier)
    client = typesafe_client.TypeSafeJevClient()

    with pytest.raises(RuntimeError, match="Jev unavailable"):
        asyncio.run(
            client.answer_nouls(
                state={"body": "A substantive message."},
                questions={"is_spam": Noul(instructions="Is this spam?")},
            )
        )

    assert classifier.calls == 3
    assert delays == [1.0, 2.0]
