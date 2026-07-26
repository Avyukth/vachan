"""Tests for the honest development-only replay transport."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.replay as replay_module
from app.protocol import PROTOCOL_VERSION
from app.replay import (
    DEV_REPLAY_ENV,
    REPLAY_LABEL,
    REPLAY_SOURCE,
    ReplayFixture,
    load_replay_fixture,
    router,
)


@pytest.fixture
def replay_app() -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    return application


@pytest.mark.parametrize("fixture", list(ReplayFixture))
def test_reviewed_fixtures_are_protocol_valid_ordered_and_visibly_labeled(
    fixture: ReplayFixture,
) -> None:
    frames = load_replay_fixture(fixture, call_id=f"test-{fixture.value}")

    assert [frame.event.seq for frame in frames] == list(range(1, len(frames) + 1))
    assert all(300 <= frame.delay_ms <= 800 for frame in frames)
    assert all(frame.event.api_version == PROTOCOL_VERSION for frame in frames)
    assert all(frame.event.payload["source"] == REPLAY_SOURCE for frame in frames)
    assert all(frame.event.payload["replay_label"] == REPLAY_LABEL for frame in frames)


def test_replay_route_is_absent_without_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    replay_app: FastAPI,
) -> None:
    monkeypatch.delenv(DEV_REPLAY_ENV, raising=False)

    response = TestClient(replay_app).post(
        "/api/dev/replay",
        json={"api_version": "v0", "fixture": "happy"},
    )

    assert response.status_code == 404


def test_enabled_replay_streams_one_shot_protocol_events(
    monkeypatch: pytest.MonkeyPatch,
    replay_app: FastAPI,
) -> None:
    monkeypatch.setenv(DEV_REPLAY_ENV, "1")
    no_delay = AsyncMock()
    monkeypatch.setattr(replay_module, "_sleep", no_delay)
    expected = load_replay_fixture(ReplayFixture.HAPPY, call_id="ignored")

    with TestClient(replay_app) as client:
        start = client.post(
            "/api/dev/replay",
            json={"api_version": "v0", "fixture": "happy"},
        )
        assert start.status_code == 200
        body = start.json()
        assert body["replay"] is True
        assert body["replay_label"] == REPLAY_LABEL

        with client.websocket_connect(body["websocket_path"]) as websocket:
            events = [websocket.receive_json() for _ in expected]

        assert [item["seq"] for item in events] == list(range(1, len(expected) + 1))
        assert all(item["call_id"] == body["call_id"] for item in events)
        assert all(item["payload"]["replay_label"] == REPLAY_LABEL for item in events)

        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(body["websocket_path"]),
        ):
            pass
