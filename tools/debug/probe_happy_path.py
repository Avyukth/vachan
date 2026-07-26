"""Drive the happy path over ONE /ws/call socket with a known-good caller fixture.

Why this exists: the browser run produced eleven turns with stt_ms in the 0-2 ms range
(no transcript) while still spending 3-10 s in the LLM and 2.6-9.6 s in TTS, and identity
never left UNVERIFIED. That symptom has two very different causes and the ledger alone
cannot separate them:

  (a) the backend receive loop / STT wiring is broken, or
  (b) the browser is at fault - capture stopping, or a second socket on the same call id
      displacing the session that owns the identity binding.

This probe removes the browser from the picture entirely. It opens exactly ONE socket,
streams a fixture whose transcript was already verified by STT round-trip, and prints every
server event with wall-clock offsets. If identity reaches CONFIRMED here, the backend is
sound and the bug is browser-side. If stt_ms stays at 0, the backend receive path is broken.

Deliberately prints only server events and state, never a transcript or a verification
value, so running it cannot leak borrower data into a terminal or a log.

Usage:
    cd backend && uv run python ../tools/debug/probe_happy_path.py [--case case-rakesh-001]
    cd backend && uv run python ../tools/debug/probe_happy_path.py --url ws://localhost:8000
"""

from __future__ import annotations

import argparse
import array
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import httpx
import websockets

REPO = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = REPO / "frontend/static/fixtures/audio_e2e_happy_verification_and_promise.wav"
TARGET_RATE = 16_000
CHUNK_SAMPLES = 1_600  # 100 ms, matching the browser mic worklet exactly.
FRAME_INTERVAL_S = 0.1

# Fields that could carry borrower speech or verification values. Never printed.
REDACT_KEYS = {"transcript", "text", "utterance", "draft", "body", "value", "values"}


def load_fixture_pcm16(path: Path) -> array.array:
    """Read a WAV and return mono PCM16 at exactly 16 kHz.

    Bulbul emits 24 kHz, so a resample is required; the browser gets this for free from
    OfflineAudioContext. Linear interpolation is plenty for a transport probe and keeps the
    script dependency-free (audioop was removed in Python 3.13 and numpy is not installed).
    """
    with wave.open(str(path)) as handle:
        if handle.getsampwidth() != 2:
            raise SystemExit(f"expected 16-bit PCM, got width {handle.getsampwidth()}")
        channels = handle.getnchannels()
        source_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())

    samples = array.array("h")
    samples.frombytes(raw)

    if channels > 1:  # downmix
        mono = array.array("h", (0 for _ in range(len(samples) // channels)))
        for index in range(len(mono)):
            total = sum(samples[index * channels + c] for c in range(channels))
            mono[index] = int(total / channels)
        samples = mono

    if source_rate == TARGET_RATE:
        return samples

    ratio = TARGET_RATE / source_rate
    out_len = int(len(samples) * ratio)
    out = array.array("h", (0 for _ in range(out_len)))
    for index in range(out_len):
        position = index / ratio
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        weight = position - left
        out[index] = int(samples[left] * (1.0 - weight) + samples[right] * weight)
    return out


def summarize(event: dict) -> str:
    """One compact line per server event, with anything speech-bearing withheld."""
    kind = event.get("type", "?")
    seq = event.get("seq", "-")
    payload = event.get("payload") or {}
    parts = []
    for key, raw in payload.items():
        if key in REDACT_KEYS:
            parts.append(f"{key}=<withheld {len(str(raw))}ch>")
        else:
            parts.append(f"{key}={raw}")
    return f"[{kind} seq={seq}] " + " ".join(parts)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="case-rakesh-001")
    parser.add_argument("--http", default="http://localhost:8000")
    parser.add_argument("--url", default="ws://localhost:8000")
    parser.add_argument(
        "--fixture",
        action="append",
        default=None,
        help="caller utterance WAV; repeat to send several turns in order",
    )
    parser.add_argument("--settle", type=float, default=25.0, help="seconds to wait after flush")
    parser.add_argument(
        "--gap",
        type=float,
        default=6.0,
        help="silence between utterances; must exceed the agent's reply so STT segments cleanly",
    )
    args = parser.parse_args()

    # Default to the three-utterance happy path. A single concatenated blob cannot drive
    # UNVERIFIED -> VERIFYING -> CONFIRMED because the agent must ASK before the borrower
    # supplies values; turn-taking is load-bearing, not cosmetic. See bead sarvam-3ox.
    fixture_paths = [Path(p) for p in (args.fixture or [
        str(REPO / "frontend/static/fixtures/audio_turn_happy_1_claim.wav"),
        str(REPO / "frontend/static/fixtures/audio_turn_happy_2_birthdate.wav"),
        str(REPO / "frontend/static/fixtures/audio_turn_happy_3_reference.wav"),
        str(REPO / "frontend/static/fixtures/audio_turn_happy_4_promise.wav"),
    ])]

    utterances = []
    for path in fixture_paths:
        pcm = load_fixture_pcm16(path)
        utterances.append((path.name, pcm))
        print(f"utterance: {path.name}  {len(pcm) / TARGET_RATE:.2f}s")

    # The browser attests these two checks over headers. This probe substitutes its own
    # caller audio and plays nothing back, so it asserts them explicitly rather than
    # pretending preflight passed. Stated out loud because a silent attestation in a debug
    # harness is exactly how a demo ends up depending on a check nobody actually performed.
    print("NOTE: attesting microphone/audio_output as a harness; no real mic or speaker involved.")
    attestations = {"X-Vachan-Microphone": "granted", "X-Vachan-Audio-Output": "confirmed"}

    async with httpx.AsyncClient(timeout=30.0, headers=attestations) as client:
        pre = await client.post(f"{args.http}/api/preflight", json={"case_id": args.case})
        pre.raise_for_status()
        body = pre.json()
        print(f"preflight: {body.get('result')}")
        for check in body.get("checks", []):
            if not check.get("pass"):
                print(f"  BLOCK {check.get('name')}: {check.get('detail')}")
        if body.get("result") != "READY":
            print("preflight is not READY; aborting so this probe cannot mask a policy block.")
            return 2

        start = await client.post(f"{args.http}/api/call/start", json={"case_id": args.case})
        start.raise_for_status()
        call_id = start.json()["call_id"]
        print(f"call_id: {call_id}")

    events: list[dict] = []
    began = time.monotonic()

    async with websockets.connect(f"{args.url}/ws/call/{call_id}", max_size=None) as socket:
        print(f"socket open (+{time.monotonic() - began:.2f}s) - streaming caller audio\n")

        async def reader() -> None:
            try:
                async for message in socket:
                    if isinstance(message, bytes):
                        print(f"+{time.monotonic() - began:6.2f}s  <audio {len(message)}B>")
                        continue
                    event = json.loads(message)
                    events.append(event)
                    print(f"+{time.monotonic() - began:6.2f}s  {summarize(event)}")
            except websockets.ConnectionClosed as closed:
                print(f"+{time.monotonic() - began:6.2f}s  SOCKET CLOSED code={closed.code} reason={closed.reason!r}")

        read_task = asyncio.create_task(reader())

        for index, (name, pcm) in enumerate(utterances, start=1):
            print(f"--- utterance {index}/{len(utterances)}: {name} ---")
            # Count agent REPLIES, not all events: the `ready` frame would otherwise satisfy
            # the wait immediately and we would talk over the agent's first turn.
            before = sum(1 for event in events if event.get("type") == "agent_audio")

            for offset in range(0, len(pcm), CHUNK_SAMPLES):
                chunk = pcm[offset : offset + CHUNK_SAMPLES]
                await socket.send(chunk.tobytes())
                await asyncio.sleep(FRAME_INTERVAL_S)

            print(f"+{time.monotonic() - began:6.2f}s  sent -> flush")
            await socket.send(json.dumps({"type": "flush"}))

            # Wait for the agent to actually answer before speaking again. Talking over the
            # agent is what a real caller would not do, and it would also let one utterance
            # be swallowed into the next STT segment.
            deadline = time.monotonic() + args.settle
            while time.monotonic() < deadline:
                if sum(1 for event in events if event.get("type") == "agent_audio") > before:
                    break
                if read_task.done():
                    break
                await asyncio.sleep(0.2)
            else:
                print(f"+{time.monotonic() - began:6.2f}s  no agent reply within {args.settle:.0f}s")

            if read_task.done():
                print("socket closed early; stopping")
                break
            # Streaming STT segments on silence, so the gap is load-bearing. Too short and
            # two utterances merge into one transcript - which silently breaks the split-turn
            # verification attempt, because a merged utterance carrying BOTH fields trips the
            # adjacent-digit ambiguity guard and the date stops parsing. A real borrower also
            # waits for the agent to stop talking.
            await asyncio.sleep(args.gap)

        print(f"\n+{time.monotonic() - began:6.2f}s  all utterances sent; settling\n")
        try:
            await asyncio.wait_for(read_task, timeout=args.settle)
        except asyncio.TimeoutError:
            read_task.cancel()
            print(f"+{time.monotonic() - began:6.2f}s  settle window elapsed")

    print("\n" + "=" * 72)
    print(f"events received: {len(events)}")
    timings = [
        event["payload"]["detail"]
        for event in events
        if isinstance(event.get("payload"), dict) and "turn_timing" in str(event["payload"].get("detail", ""))
    ]
    for line in timings:
        print(f"  {line}")

    identities = [
        event["payload"].get("identity_state")
        for event in events
        if isinstance(event.get("payload"), dict) and event["payload"].get("identity_state")
    ]
    print(f"identity progression: {' -> '.join(identities) if identities else '(none reported)'}")
    print(f"call_id for ledger inspection: {call_id}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
