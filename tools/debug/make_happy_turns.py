#!/usr/bin/env python3
"""Generate the happy path as THREE separate caller utterances, not one blob.

Why this exists: the existing happy fixture is a single clip that jumps straight to
verification values. From UNVERIFIED, app/third_party.py only routes to VERIFYING on an
explicit borrower claim (_BORROWER_CLAIM_PATTERNS) or an LLM BORROWER_PRESENT label. A clip
that never self-identifies therefore loops on speaker_identity_unresolved forever and
identity can never reach CONFIRMED. Proven with route_speaker_utterance() and reproduced
end to end - see bead sarvam-3ox.

The gate is correct: accepting verification values from a speaker who has not said who they
are would defeat the whole product. So the ASSET is what changes here, not the matcher.

A real call is turn-taking: the agent asks who it is speaking to, the borrower answers, the
agent asks for two values, the borrower supplies them, then the borrower offers a promise.
Three utterances, each flushed separately, is that shape. One concatenated blob is not.

Each clip is transcribed back through Saaras before it is trusted - synthesising audio and
assuming the transcript is how you build a test suite that lies.

Usage:  cd backend && uv run python ../tools/debug/make_happy_turns.py
Writes: frontend/static/fixtures/audio_turn_happy_<n>_<name>.wav
"""

from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

TTS_URL = "https://api.sarvam.ai/text-to-speech"
STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_MODEL = "bulbul:v3"
STT_MODEL = "saaras:v3"
LANG = "hi-IN"
SPEAKER = "rahul"  # male: Rakesh Yadav

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "frontend/static/fixtures"

# Turn 1 MUST trip _BORROWER_CLAIM_PATTERNS (the regex is on मैं राकेश). Turn 2 carries the
# two seeded values. Turn 3 offers the promise. Nothing here is a lender name or an amount
# the agent has not already been told - the caller may say these; the agent may not.
TURNS = [
    {
        "n": 1,
        "name": "claim",
        "text": "मैं राकेश बोल रहा हूँ।",
        "must_contain": ["राकेश"],
        "why": "explicit borrower claim -> UNVERIFIED to VERIFYING",
    },
    {
        "n": 2,
        "name": "birthdate",
        "text": "मेरी जन्मतिथि चौदह सितंबर है।",
        "must_contain": ["चौदह", "सितंबर"],
        "why": "first field only; normalize_birth_day_month -> (14, 9)",
    },
    {
        # NOTE the wording. Saying "आखिरी चार अंक" ("the last FOUR digits") puts the word
        # चार = 4 into the utterance, so the digit collector reads [4,4,7,2,9] - five
        # digits - and normalize_reference_last4 returns None. "आखिरी अंक" avoids it.
        # Separately, the two fields MUST be separate turns: with both in one utterance the
        # adjacent digit-words चार सात trip the ambiguity guard in _parse_day_alias and the
        # date silently fails to parse. The split-turn attempt is the designed shape.
        "n": 3,
        "name": "reference",
        "text": "आखिरी अंक चार सात दो नौ हैं।",
        "must_contain": ["चार", "सात", "दो", "नौ"],
        "why": "second field only; normalize_reference_last4 -> 4729 -> CONFIRMED",
    },
    {
        "n": 4,
        "name": "promise",
        "text": "मैं शुक्रवार तक पंद्रह सौ रुपये दे दूँगा।",
        "must_contain": ["पंद्रह"],
        "why": "promise candidate -> read-back then COMMITTED",
    },
]


def api_key() -> str:
    """Keychain only. The key must never reach a file, a log, or the frontend."""
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", "sarvam-api", "-w"],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        sys.exit("Sarvam API key not found in Keychain under service 'sarvam-api'.")


def post(url: str, key: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"api-subscription-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        # Never echo the request body - it would put the key in the terminal.
        sys.exit(f"{url} failed HTTP {error.code}: {error.read()[:300]!r}")


def post_multipart(url: str, key: str, wav: bytes, fields: dict) -> dict:
    """Saaras expects multipart/form-data with the audio in a `file` part."""
    boundary = "----vachanhappyturns7f3a"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    )
    parts.append(wav)
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    request = urllib.request.Request(url, data=b"".join(parts), method="POST")
    request.add_header("api-subscription-key", key)
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        sys.exit(f"{url} failed HTTP {error.code}: {error.read()[:300]!r}")


def main() -> int:
    key = api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for turn in TURNS:
        tts = post(
            TTS_URL,
            key,
            {
                "text": turn["text"],
                "target_language_code": LANG,
                "speaker": SPEAKER,
                "model": TTS_MODEL,
            },
        )
        audios = tts.get("audios") or []
        if not audios:
            sys.exit(f"turn {turn['n']}: Bulbul returned no audio")
        wav = base64.b64decode(audios[0])

        path = OUT_DIR / f"audio_turn_happy_{turn['n']}_{turn['name']}.wav"
        path.write_bytes(wav)

        # Round-trip: does the REAL STT hear what we intended?
        # Saaras takes multipart with a `file` part, not base64 in JSON.
        stt = post_multipart(
            STT_URL,
            key,
            wav,
            {"model": STT_MODEL, "mode": "transcribe", "language_code": LANG},
        )
        transcript = (stt.get("transcript") or "").strip()
        missing = [token for token in turn["must_contain"] if token not in transcript]
        verdict = "OK" if not missing else f"MISSING {missing}"

        print(f"turn {turn['n']} ({turn['name']}): {len(wav) / 1024:.0f}KB  {verdict}")
        print(f"         why: {turn['why']}")
        if missing:
            print(f"         heard back: {transcript!r}")

        results.append({"turn": turn["n"], "path": str(path), "ok": not missing})

    ok = sum(1 for r in results if r["ok"])
    print(f"\n{ok}/{len(results)} turns verified by STT round-trip")
    print("files:")
    for r in results:
        print(f"  {r['path']}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
