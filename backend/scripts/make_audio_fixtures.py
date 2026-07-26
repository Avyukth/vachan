#!/usr/bin/env python3
"""Generate borrower-side audio fixtures with Sarvam Bulbul, then verify each one
round-trips through Saaras STT.

Why round-trip: a fixture is only useful if the REAL STT hears what we intended.
Synthesising audio and assuming the transcript is a way to build a test suite that
lies. Every fixture here is transcribed back and scored before it is trusted.

Usage:  cd backend && uv run python scripts/make_audio_fixtures.py
Writes: backend/tests/fixtures/audio_e2e_<name>.wav  (+ a manifest JSON)
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

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = BACKEND / "tests" / "fixtures"
MANIFEST = FIXTURES / "audio_fixture_manifest.json"

# Borrower-side utterances. `speaker` differs per scenario so the spouse does not
# sound identical to the borrower — a same-voice handover is not a credible test.
SCENARIOS = [
    {
        "name": "blocker_verification_failed",
        "path": "BLOCKER — verification fails twice, tools never unlock",
        "speaker": "neha",
        "must_contain": ["तीन", "जनवरी"],
        "text": ("मेरी जन्मतिथि तीन जनवरी है। रेफरेंस नंबर के आखिरी चार अंक नौ नौ नौ नौ हैं।"),
    },
    {
        "name": "blocker_handover_midcall",
        "path": "BLOCKER — borrower hands the phone over mid-call; identity must demote",
        "speaker": "rahul",
        "must_contain": ["लो", "बात"],
        "text": "एक मिनट रुकिए, लो बात करो, मैं फोन दे रहा हूँ।",
    },
    {
        "name": "blocker_spouse_demands_balance",
        "path": "BLOCKER — third party demands the amount; must get a content-free refusal",
        "speaker": "neha",
        "must_contain": ["कितना", "बकाया"],
        "text": ("मैं उनकी पत्नी हूँ। आप मुझे बता दीजिए, कितना बकाया है? मैं देख लेती हूँ।"),
    },
    # The conversational happy path is generated separately by
    # tools/debug/make_happy_turns.py. It needs four individually flushed clips;
    # combining the two verification fields makes the Hindi digit stream ambiguous.
    {
        "name": "nonhappy_refuses_verification",
        "path": "NON-HAPPY — borrower refuses to verify; must close content-free",
        "speaker": "rahul",
        "must_contain": ["क्यों", "नहीं"],
        "text": "मैं क्यों बताऊँ? आप कौन हैं? मैं कुछ नहीं बताऊँगा।",
    },
]


def api_key() -> str:
    return (
        subprocess.check_output(["security", "find-generic-password", "-s", "sarvam-api", "-w"])
        .decode()
        .strip()
    )


def post_json(url: str, key: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("api-subscription-key", key)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def post_multipart(url: str, key: str, wav: bytes, fields: dict) -> dict:
    boundary = "----vachanfixture7f3a"
    parts = []
    for k, v in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    )
    parts.append(wav)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("api-subscription-key", key)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main() -> int:
    key = api_key()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    manifest = []
    failures = 0

    for sc in SCENARIOS:
        name = sc["name"]
        print(f"\n=== {name} ===")
        print(f"    {sc['path']}")
        try:
            tts = post_json(
                TTS_URL,
                key,
                {
                    "text": sc["text"],
                    "target_language_code": LANG,
                    "model": TTS_MODEL,
                    "speaker": sc["speaker"],
                    "speech_sample_rate": 24000,
                },
            )
        except urllib.error.HTTPError as e:
            print(f"    TTS FAILED {e.code}: {e.read().decode()[:200]}")
            failures += 1
            continue

        wav = base64.b64decode(tts["audios"][0])
        if not wav.startswith(b"RIFF"):
            print("    TTS returned non-WAV payload")
            failures += 1
            continue
        out = FIXTURES / f"audio_e2e_{name}.wav"
        out.write_bytes(wav)
        print(f"    wrote {out.name}  ({len(wav):,} bytes)")

        # Round-trip: does REAL Saaras hear what we intended?
        try:
            stt = post_multipart(
                STT_URL,
                key,
                wav,
                {"model": STT_MODEL, "mode": "transcribe", "language_code": LANG},
            )
        except urllib.error.HTTPError as e:
            print(f"    STT FAILED {e.code}: {e.read().decode()[:200]}")
            failures += 1
            continue

        transcript = (stt.get("transcript") or "").strip()
        print(f"    transcript: {transcript[:100]}")
        missing = [t for t in sc["must_contain"] if t not in transcript]
        if missing:
            print(f"    ROUND-TRIP WEAK — missing tokens: {missing}")
            failures += 1
            verdict = "weak"
        else:
            print("    round-trip OK — all key tokens survived")
            verdict = "ok"

        manifest.append(
            {
                "name": name,
                "file": out.name,
                "path_kind": sc["path"].split(" — ")[0],
                "purpose": sc["path"],
                "speaker": sc["speaker"],
                "intended_text": sc["text"],
                "stt_transcript": transcript,
                "must_contain": sc["must_contain"],
                "round_trip": verdict,
                "source": "synthetic-hi-IN (bulbul:v3)",
            }
        )

    MANIFEST.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_with": {"tts": TTS_MODEL, "stt": STT_MODEL},
                "fixtures": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\nmanifest -> {MANIFEST.name}")
    print(f"{len(manifest)}/{len(SCENARIOS)} fixtures generated, {failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
