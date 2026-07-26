from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import pytest

from app.llm import LLMFailureCategory, LLMUnavailable
from app.voice import ProductionDialogueClient


class _SuccessThenTimeoutChat:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        timeout_seconds: float,
        max_tokens: int,
    ) -> str:
        del messages, timeout_seconds, max_tokens
        self.calls += 1
        if self.calls == 1:
            return '{"intent":"clarify"}'
        raise LLMUnavailable(
            "sensitive-upstream-detail",
            category=LLMFailureCategory.TIMEOUT,
        )


def test_production_dialogue_replaces_success_timing_after_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ProductionDialogueClient("secret-must-not-leak")
    client._chat = _SuccessThenTimeoutChat()  # type: ignore[assignment]
    ticks = iter((100.0, 100.025, 200.0, 200.875))
    monkeypatch.setattr("app.voice.time.perf_counter", lambda: next(ticks))

    async def exercise() -> None:
        response = await client.chat_completion([{"role": "user", "content": "private-transcript"}])
        assert response["choices"][0]["message"]["content"] == '{"intent":"clarify"}'
        assert client.last_llm_ms == pytest.approx(25.0)

        with pytest.raises(LLMUnavailable) as caught:
            await client.chat_completion(
                [{"role": "user", "content": "another-private-transcript"}]
            )

        assert caught.value.category is LLMFailureCategory.TIMEOUT
        assert client.last_llm_ms == pytest.approx(875.0)

    asyncio.run(exercise())
