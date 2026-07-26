"""Pure whole-utterance suppression state for half-duplex voice calls."""

from dataclasses import dataclass

AGENT_FLOOR_REASON = "agent_floor"
INTERRUPTED_IN_PROGRESS_REASON = "agent_floor:interrupted_in_progress"


@dataclass(frozen=True, slots=True)
class FloorEdge:
    """One changed playback-floor edge and optional acquisition evidence."""

    held: bool
    interrupted_in_progress: bool

    @property
    def reason_code(self) -> str | None:
        """Return acquisition evidence without caller audio or text."""
        if not self.held:
            return None
        if self.interrupted_in_progress:
            return INTERRUPTED_IN_PROGRESS_REASON
        return AGENT_FLOOR_REASON


class AudioSuppressionGate:
    """Discard complete uncertain utterances instead of accepting fragments.

    A final received while the floor is held is always suppressed. If playback
    started after caller audio had already entered the STT stream, the first
    final after release is suppressed too: it may contain only the utterance
    tail captured after playback ended.
    """

    def __init__(self) -> None:
        self._floor_held = False
        self._interrupted_final_pending = False

    @property
    def floor_held(self) -> bool:
        """Whether agent playback currently owns the floor."""
        return self._floor_held

    @property
    def interrupted_final_pending(self) -> bool:
        """Whether the next post-floor final is unsafe to dispatch."""
        return self._interrupted_final_pending

    def set_floor(self, held: bool, *, caller_audio_pending: bool) -> FloorEdge | None:
        """Apply one edge; duplicate edges produce no evidence event."""
        if held == self._floor_held:
            return None

        self._floor_held = held
        interrupted = held and caller_audio_pending
        if interrupted:
            self._interrupted_final_pending = True
        return FloorEdge(held=held, interrupted_in_progress=interrupted)

    def consume_final(self) -> bool:
        """Return whether one final must be discarded, consuming it when safe."""
        if self._floor_held:
            return True
        if not self._interrupted_final_pending:
            return False
        self._interrupted_final_pending = False
        return True
