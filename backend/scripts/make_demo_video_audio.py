#!/usr/bin/env python3
"""Generate the complete demo-video audio track with Sarvam Bulbul.

Produces every line of the scripted 120-second arc as a separate numbered clip,
plus an ordered manifest (with on-screen captions and the rubric beat each line
serves) so the clips can be assembled into a video or used for rehearsal.

Three distinct voices, deliberately:
  agent  = priya   (the Vachan agent)
  rakesh = rahul   (borrower, male)
  sunita = neha    (spouse, female)  -- a same-voice handover is not credible.

Usage:  cd backend && uv run python scripts/make_demo_video_audio.py
Writes: backend/artifacts/demo_video/NN_<role>_<slug>.wav + manifest.json
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
TTS_MODEL = "bulbul:v3"
LANG = "hi-IN"

VOICES = {"agent": "priya", "rakesh": "rahul", "sunita": "neha"}

BACKEND = pathlib.Path(__file__).resolve().parents[1]
OUT = BACKEND / "artifacts" / "demo_video"

# The scripted arc. `beat` names the rubric moment the line serves so the video
# editor knows what must be on screen when it plays.
SCRIPT = [
    (
        "agent",
        "blind-greeting",
        "नमस्ते। मैं वचन असिस्टेंट बोल रही हूँ। "
        "मैं आपसे कभी ओटीपी या यूपीआई पिन नहीं माँगूँगी, और इस कॉल पर कोई पेमेंट नहीं होती। "
        "क्या मैं राकेश जी से बात कर सकती हूँ?",
        "Blind greeting: no lender name, no amount, no reason. Anti-scam pledge first.",
    ),
    (
        "rakesh",
        "hostile-opener",
        "यह स्कैम कॉल है क्या? आप कौन बोल रहे हैं?",
        "Judge-as-borrower opens hostile — distrust is the rational default.",
    ),
    (
        "agent",
        "anti-scam-response",
        "आपका शक़ जायज़ है। इसीलिए मैं पहले खुद को साबित करती हूँ। "
        "मैं कोई राशि नहीं बता सकती जब तक यह पक्का न हो कि मैं राकेश जी से ही बात कर रही हूँ।",
        "The agent proves itself before asking anything. Still zero debt words.",
    ),
    (
        "agent",
        "verification-request",
        "कृपया अपनी जन्मतिथि का दिन और महीना बताइए, और रेफरेंस नंबर के आख़िरी चार अंक।",
        "Verification request. Expected values are never spoken by the agent.",
    ),
    (
        "rakesh",
        "verification-values",
        "मेरी जन्मतिथि चौदह सितंबर है। आख़िरी चार अंक चार सात दो नौ हैं।",
        "Two seeded values, compared in code. Identity: VERIFYING -> CONFIRMED.",
    ),
    (
        "agent",
        "unlock-and-disclose",
        "धन्यवाद राकेश जी, आपकी पहचान पुष्ट हो गई है। "
        "अब मैं आपके खाते की बात कर सकती हूँ। आपकी एक क़िस्त बाक़ी है।",
        "CONFIRMED. Tools unlock. Account context enters the model for the first time.",
    ),
    (
        "rakesh",
        "promise-offer",
        "इस महीने पूरा नहीं हो पाएगा। मैं शुक्रवार तक पंद्रह सौ रुपये दे सकता हूँ।",
        "Borrower offers a partial, keepable amount.",
    ),
    (
        "agent",
        "dual-format-readback",
        "ठीक है। मैं दोहरा देती हूँ — पंद्रह सौ रुपये, एक-पाँच-शून्य-शून्य, शुक्रवार, इकतीस जुलाई। क्या यह सही है?",
        "THE read-back: digits + words + weekday + absolute ISO date. Nothing is "
        "written to the ledger before this.",
    ),
    (
        "rakesh",
        "handover",
        "एक मिनट रुकिए, लो बात करो, मैं फ़ोन दे रहा हूँ।",
        "Pre-affirmation handover. Identity demotes in the SAME turn and tools relock.",
    ),
    (
        "sunita",
        "spouse-demands-amount",
        "हैलो, मैं उनकी पत्नी हूँ। आप मुझे बता दीजिए, कितना बकाया है? मैं देख लेती हूँ।",
        "Third party demands the amount while the identity and tools are locked.",
    ),
    (
        "agent",
        "content-free-refusal",
        "माफ़ कीजिए, यह उनकी निजी कॉल है। मैं उनसे ही बात कर सकती हूँ।",
        "Content-free refusal: no amount, lender relationship, or reason.",
    ),
    (
        "rakesh",
        "borrower-return",
        "मैं राकेश वापस बोल रहा हूँ।",
        "The borrower explicitly returns, but the prior confirmation is not restored.",
    ),
    (
        "agent",
        "fresh-verification-request",
        "वापस जुड़ने के लिए कृपया जन्मतिथि का दिन और महीना, और रेफरेंस नंबर के आख़िरी चार अंक फिर से बताइए।",
        "Fresh verification request. Expected values are still never spoken by the agent.",
    ),
    (
        "rakesh",
        "fresh-verification-values",
        "मेरी जन्मतिथि चौदह सितंबर है। आख़िरी चार अंक चार सात दो नौ हैं।",
        "Both values are supplied again; only code may restore CONFIRMED.",
    ),
    (
        "rakesh",
        "corrected-promise-offer",
        "रुकिए, पंद्रह सौ नहीं। मैं शनिवार तक एक हज़ार पचास रुपये दे सकता हूँ।",
        "After fresh verification, the borrower corrects the candidate to a keepable amount.",
    ),
    (
        "agent",
        "corrected-readback",
        "मैं फिर से दोहरा देती हूँ — एक हज़ार पचास रुपये, एक-शून्य-पाँच-शून्य, शनिवार, एक अगस्त। क्या यह सही है?",
        "Revision two receives a complete fresh read-back before any write.",
    ),
    (
        "rakesh",
        "explicit-yes",
        "हाँ, बिल्कुल सही है।",
        "The final caller turn is the explicit affirmative.",
    ),
    (
        "agent",
        "commitment-confirmed",
        "दर्ज कर लिया। एक हज़ार पचास रुपये, शनिवार एक अगस्त। धन्यवाद।",
        "The sole terminal PROMISE_CONFIRMED outcome; no later caller turn exists.",
    ),
]


def api_key() -> str:
    return (
        subprocess.check_output(["security", "find-generic-password", "-s", "sarvam-api", "-w"])
        .decode()
        .strip()
    )


def synth(key: str, text: str, speaker: str) -> bytes:
    body = json.dumps(
        {
            "text": text,
            "target_language_code": LANG,
            "model": TTS_MODEL,
            "speaker": speaker,
            "speech_sample_rate": 24000,
        }
    ).encode()
    req = urllib.request.Request(TTS_URL, data=body, method="POST")
    req.add_header("api-subscription-key", key)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        payload = json.loads(r.read().decode())
    return base64.b64decode(payload["audios"][0])


def main() -> int:
    key = api_key()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest, failures, total_bytes = [], 0, 0

    for i, (role, slug, text, beat) in enumerate(SCRIPT, start=1):
        speaker = VOICES[role]
        name = f"{i:02d}_{role}_{slug}.wav"
        try:
            wav = synth(key, text, speaker)
        except urllib.error.HTTPError as e:
            print(f"{name}: FAILED {e.code} {e.read().decode()[:140]}")
            failures += 1
            continue
        if not wav.startswith(b"RIFF"):
            print(f"{name}: non-WAV payload")
            failures += 1
            continue
        (OUT / name).write_bytes(wav)
        total_bytes += len(wav)
        # 24kHz mono 16-bit => ~48000 bytes/sec; minus 44-byte header
        secs = round(max(len(wav) - 44, 0) / 48000.0, 1)
        print(f"{name:52} {secs:>5.1f}s  {speaker}")
        manifest.append(
            {
                "order": i,
                "file": name,
                "role": role,
                "speaker": speaker,
                "approx_seconds": secs,
                "caption_hi": text,
                "beat": beat,
            }
        )

    runtime = round(sum(m["approx_seconds"] for m in manifest), 1)
    (OUT / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_with": {"tts": TTS_MODEL, "language": LANG, "voices": VOICES},
                "approx_total_seconds": runtime,
                "note": "Synthetic Sarvam Bulbul voices for the demo video and rehearsal. "
                "All data is mock. Not a recording of real borrowers.",
                "clips": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print(
        f"\n{len(manifest)}/{len(SCRIPT)} clips, ~{runtime}s of dialogue, "
        f"{total_bytes / 1_048_576:.1f} MB -> {OUT}"
    )
    if runtime > 105:
        print(
            f"WARNING: {runtime}s exceeds the 105s live-path budget — trim lines "
            f"or speed up delivery in the edit."
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
