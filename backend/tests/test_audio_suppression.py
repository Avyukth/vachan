"""Whole-utterance guarantees for the half-duplex agent floor."""

from app.audio_suppression import (
    AGENT_FLOOR_REASON,
    INTERRUPTED_IN_PROGRESS_REASON,
    AudioSuppressionGate,
)


def test_clear_floor_window_suppresses_only_finals_received_while_held() -> None:
    gate = AudioSuppressionGate()

    edge = gate.set_floor(True, caller_audio_pending=False)
    assert edge is not None
    assert edge.reason_code == AGENT_FLOOR_REASON
    assert gate.consume_final()

    release = gate.set_floor(False, caller_audio_pending=False)
    assert release is not None
    assert release.held is False
    assert release.reason_code is None
    assert not gate.consume_final()


def test_interrupted_utterance_tail_is_discarded_after_floor_release() -> None:
    gate = AudioSuppressionGate()

    edge = gate.set_floor(True, caller_audio_pending=True)
    assert edge is not None
    assert edge.reason_code == INTERRUPTED_IN_PROGRESS_REASON
    assert gate.interrupted_final_pending

    gate.set_floor(False, caller_audio_pending=False)
    assert gate.consume_final()
    assert not gate.interrupted_final_pending
    assert not gate.consume_final()


def test_finals_while_held_do_not_consume_post_floor_interruption_marker() -> None:
    gate = AudioSuppressionGate()
    gate.set_floor(True, caller_audio_pending=True)

    assert gate.consume_final()
    assert gate.consume_final()
    assert gate.interrupted_final_pending

    gate.set_floor(False, caller_audio_pending=False)
    assert gate.consume_final()
    assert not gate.consume_final()


def test_duplicate_floor_edges_do_not_create_duplicate_evidence() -> None:
    gate = AudioSuppressionGate()

    assert gate.set_floor(True, caller_audio_pending=False) is not None
    assert gate.set_floor(True, caller_audio_pending=True) is None
    assert gate.set_floor(False, caller_audio_pending=False) is not None
    assert gate.set_floor(False, caller_audio_pending=False) is None
