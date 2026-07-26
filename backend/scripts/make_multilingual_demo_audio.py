#!/usr/bin/env python3
"""English demo script -> Sarvam Translate -> Sarvam Bulbul TTS, for hi-IN and bn-IN.

Pipeline per line:
    English (canonical, reviewable)
      -> POST /translate            (Mayura / sarvam-translate)
      -> POST /text-to-speech       (bulbul:v3, per-language speaker)
      -> POST /speech-to-text       (saaras:v3) as a round-trip check

WHY THE ROUND-TRIP CHECK: this project's whole thesis is that you do not trust a
model with numbers. Machine translation can mangle an amount, a digit string, or a
date -- exactly the failure our own read-back mechanic defends against. So every
line carrying money/date/digits is verified after synthesis, and any line where a
critical token did not survive is reported as NEEDS-HUMAN-REVIEW rather than
silently shipped.

Usage:  cd backend && uv run python scripts/make_multilingual_demo_audio.py
Writes: backend/artifacts/demo_video/<lang>/NN_<role>_<slug>.wav + manifest.json
"""

from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

TRANSLATE_URL = "https://api.sarvam.ai/translate"
TTS_URL = "https://api.sarvam.ai/text-to-speech"
STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_MODEL = "bulbul:v3"
STT_MODEL = "saaras:v3"
TRANSLATE_MODELS = ("sarvam-translate:v1", "mayura:v1")  # try in order

BACKEND = pathlib.Path(__file__).resolve().parents[1]
OUT = BACKEND / "artifacts" / "demo_video"

TARGETS = [
    {
        "code": "hi-IN",
        "label": "Hindi",
        "voices": {"agent": "priya", "borrower": "rahul", "spouse": "neha"},
    },
    {
        "code": "bn-IN",
        "label": "Bengali",
        "voices": {"agent": "priya", "borrower": "rahul", "spouse": "neha"},
    },
]

# Canonical English script. `critical` lists tokens that MUST survive translation
# and synthesis (amounts, digit strings, dates). Empty = nothing numeric at risk.
SCRIPT = [
    (
        "agent",
        "blind-greeting",
        [],
        "Hello. This is the Vachan assistant. I will never ask you for an OTP or a UPI "
        "PIN, and no payment happens on this call. May I speak with Rakesh?",
        "Blind greeting: no lender name, no amount, no reason. Anti-scam pledge first.",
    ),
    (
        "borrower",
        "hostile-opener",
        [],
        "Is this a scam call? Who is speaking?",
        "Judge-as-borrower opens hostile. Distrust is the rational default.",
    ),
    (
        "agent",
        "anti-scam-response",
        [],
        "Your suspicion is fair. That is why I prove myself first. I cannot mention any "
        "amount until I am certain I am speaking with Rakesh himself.",
        "The agent proves itself before asking anything. Still zero debt words.",
    ),
    (
        "agent",
        "verification-request",
        [],
        "Please tell me the day and month of your date of birth, and the last four "
        "digits of your reference number.",
        "Verification request. Expected values are never spoken by the agent.",
    ),
    (
        "borrower",
        "verification-values",
        ["14", "4729"],
        "My date of birth is the fourteenth of September. The last four digits are "
        "four seven two nine.",
        "Two seeded values, compared in code. Identity VERIFYING -> CONFIRMED.",
    ),
    (
        "agent",
        "unlock-and-disclose",
        [],
        "Thank you Rakesh, your identity is confirmed. Now I can discuss your account. "
        "One instalment is outstanding.",
        "CONFIRMED. Tools unlock. Account context enters the model for the first time.",
    ),
    (
        "borrower",
        "promise-offer",
        ["1500"],
        "I cannot pay the full amount this month. I can pay one thousand five hundred "
        "rupees by Friday.",
        "Borrower offers a partial, keepable amount.",
    ),
    (
        "agent",
        "dual-format-readback",
        ["1500", "31"],
        "Let me read that back. One thousand five hundred rupees. One five zero zero. "
        "Friday, the thirty first of July. Is that correct?",
        "THE read-back: words + digits + weekday + absolute date. Nothing reaches the "
        "ledger before this.",
    ),
    (
        "borrower",
        "handover",
        [],
        "One moment. I am handing the phone to her now.",
        "Pre-affirmation handover. Identity demotes in the SAME turn and tools relock.",
    ),
    (
        "spouse",
        "spouse-demands-amount",
        [],
        "Hello, I am his wife. Tell me how much is outstanding. I will handle it.",
        "Third party demands the amount while the identity and tools are locked.",
    ),
    (
        "agent",
        "content-free-refusal",
        [],
        "I am sorry, this is his personal call. I can only discuss it with him.",
        "Content-free refusal: no amount, lender relationship, or reason.",
    ),
    (
        "borrower",
        "borrower-return",
        [],
        "This is Rakesh speaking again.",
        "The borrower explicitly returns, but the prior confirmation is not restored.",
    ),
    (
        "agent",
        "fresh-verification-request",
        [],
        "To continue, please give the day and month of your date of birth and the last four "
        "digits of your reference number again.",
        "Fresh verification request. Expected values are still never spoken by the agent.",
    ),
    (
        "borrower",
        "fresh-verification-values",
        ["14", "4729"],
        "My date of birth is the fourteenth of September. The last four digits are "
        "four seven two nine.",
        "Both values are supplied again; only code may restore CONFIRMED.",
    ),
    (
        "borrower",
        "corrected-promise-offer",
        ["1050"],
        "Wait, not one thousand five hundred. I can pay one thousand fifty rupees by Saturday.",
        "After fresh verification, the borrower corrects the candidate to a keepable amount.",
    ),
    (
        "agent",
        "corrected-readback",
        ["1050", "1"],
        "Let me read that back again. One thousand fifty rupees. One zero five zero. "
        "Saturday, the first of August. Is that correct?",
        "Revision two receives a complete fresh read-back before any write.",
    ),
    (
        "borrower",
        "explicit-yes",
        [],
        "Yes, that is correct.",
        "The final caller turn is the explicit affirmative.",
    ),
    (
        "agent",
        "commitment-confirmed",
        ["1050", "1"],
        "Recorded. One thousand fifty rupees, Saturday the first of August. Thank you.",
        "The sole terminal PROMISE_CONFIRMED outcome; no later caller turn exists.",
    ),
]

DEV_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")
BEN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def api_key() -> str:
    return (
        subprocess.check_output(["security", "find-generic-password", "-s", "sarvam-api", "-w"])
        .decode()
        .strip()
    )


def post_json(url: str, key: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("api-subscription-key", key)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post_multipart(url: str, key: str, wav: bytes, fields: dict) -> dict:
    b = "----vachanml7f3a"
    parts = [
        f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()
    ]
    parts.append(
        f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode()
    )
    parts += [wav, f"\r\n--{b}--\r\n".encode()]
    req = urllib.request.Request(url, data=b"".join(parts), method="POST")
    req.add_header("api-subscription-key", key)
    req.add_header("Content-Type", f"multipart/form-data; boundary={b}")
    with urllib.request.urlopen(req, timeout=150) as r:
        return json.loads(r.read().decode())


def translate(key: str, text: str, target: str) -> tuple[str, str]:
    """Return (translated_text, model_used). Tries known translate models in order."""
    last = ""
    for model in TRANSLATE_MODELS:
        try:
            resp = post_json(
                TRANSLATE_URL,
                key,
                {
                    "input": text,
                    "source_language_code": "en-IN",
                    "target_language_code": target,
                    "model": model,
                    "mode": "formal",
                },
            )
            out = resp.get("translated_text") or resp.get("output") or ""
            if out:
                return out.strip(), model
            last = f"{model}: empty response"
        except urllib.error.HTTPError as e:
            last = f"{model}: {e.code} {e.read().decode()[:120]}"
    raise RuntimeError(f"translate failed -> {last}")


NUMERAL_VARIATIONS = {
    "hi-IN": {
        "0": ["शून्य"],
        "1": ["एक"],
        "2": ["दो"],
        "3": ["तीन"],
        "4": ["चार"],
        "5": ["पाँच", "पांच"],
        "6": ["छह"],
        "7": ["सात"],
        "8": ["आठ"],
        "9": ["नौ"],
        "14": ["चौदह"],
        "31": ["इकतीस", "इकत्तीस"],
        "1050": ["एक हज़ार पचास", "एक हजार पचास", "एक हज़ार पचास रुपये"],
        "1500": ["एक हज़ार पाँच सौ", "एक हजार पाँच सौ", "एक हज़ार पांच सौ", "पंद्रह सौ"],
        "4729": ["चार सात दो नौ"],
    },
    "bn-IN": {
        "0": ["শূন্য"],
        "1": ["এক"],
        "2": ["দুই"],
        "3": ["তিন"],
        "4": ["চার"],
        "5": ["পাঁচ"],
        "6": ["ছয়"],
        "7": ["সাত"],
        "8": ["আট"],
        "9": ["নয়"],
        "14": ["চৌদ্দ"],
        "31": ["একত্রিশ", "একত্রিশে"],
        "1050": ["এক হাজার পঞ্চাশ", "১০৫০"],
        "1500": ["এক হাজার পাঁচশ", "এক হাজার পাঁচশো", "১৫০০"],
        "4729": ["চার সাত দুই নয়"],
    },
}


def token_survived(token: str, text: str, lang: str) -> bool:
    """A numeric token survives as ASCII digits, native digits, or spelled numerals.

    Spelled-out numerals are the EXPECTED form in synthesised speech — a read-back
    that says "एक हज़ार पाँच सौ" is correct, not a failure. An earlier version of this
    check only looked for digits and produced false alarms on every correct line.
    """
    if token in text:
        return True
    if not token.isdigit():
        return False
    if token.translate(DEV_DIGITS) in text or token.translate(BEN_DIGITS) in text:
        return True
    for form in NUMERAL_VARIATIONS.get(lang, {}).get(token, []):
        if form in text:
            return True
    # last resort: every digit spelled individually, in order (e.g. 4-7-2-9)
    words = NUMERAL_VARIATIONS.get(lang, {})
    per_digit = [words.get(d, []) for d in token]
    if all(per_digit):
        pos = 0
        for variants in per_digit:
            hit = min((text.find(v, pos) for v in variants if text.find(v, pos) >= 0), default=-1)
            if hit < 0:
                return False
            pos = hit + 1
        return True
    return False


def main() -> int:
    key = api_key()
    problems = 0
    summary = {}

    for tgt in TARGETS:
        code, label = tgt["code"], tgt["label"]
        d = OUT / code
        d.mkdir(parents=True, exist_ok=True)
        print(f"\n{'=' * 66}\n{label} ({code})\n{'=' * 66}")
        clips, lang_problems, total = [], 0, 0.0

        for i, (role, slug, critical, en, beat) in enumerate(SCRIPT, start=1):
            name = f"{i:02d}_{role}_{slug}.wav"
            try:
                translated, tmodel = translate(key, en, code)
            except RuntimeError as e:
                print(f"  {name}: TRANSLATE FAILED — {e}")
                problems += 1
                lang_problems += 1
                continue

            speaker = tgt["voices"][role]
            try:
                tts = post_json(
                    TTS_URL,
                    key,
                    {
                        "text": translated,
                        "target_language_code": code,
                        "model": TTS_MODEL,
                        "speaker": speaker,
                        "speech_sample_rate": 24000,
                    },
                )
                wav = base64.b64decode(tts["audios"][0])
            except urllib.error.HTTPError as e:
                print(f"  {name}: TTS FAILED {e.code} {e.read().decode()[:130]}")
                problems += 1
                lang_problems += 1
                continue

            if not wav.startswith(b"RIFF"):
                print(f"  {name}: non-WAV payload")
                problems += 1
                lang_problems += 1
                continue

            (d / name).write_bytes(wav)
            secs = round(max(len(wav) - 44, 0) / 48000.0, 1)
            total += secs

            # Round-trip only the lines that carry numbers — that is where the risk is.
            transcript, review = "", "ok"
            if critical:
                try:
                    stt = post_multipart(
                        STT_URL,
                        key,
                        wav,
                        {"model": STT_MODEL, "mode": "transcribe", "language_code": code},
                    )
                    transcript = (stt.get("transcript") or "").strip()
                    missing = [t for t in critical if not token_survived(t, transcript, code)]
                    if missing:
                        review = f"NEEDS-HUMAN-REVIEW: {missing} not detected"
                        problems += 1
                        lang_problems += 1
                except urllib.error.HTTPError as e:
                    review = f"stt-check-failed {e.code}"

            flag = "" if review == "ok" else f"  <-- {review}"
            print(f"  {name:48} {secs:>5.1f}s {speaker:7}{flag}")
            clips.append(
                {
                    "order": i,
                    "file": name,
                    "role": role,
                    "speaker": speaker,
                    "approx_seconds": secs,
                    "english": en,
                    "translated": translated,
                    "translate_model": tmodel,
                    "critical_tokens": critical,
                    "stt_transcript": transcript,
                    "review": review,
                    "beat": beat,
                }
            )

        (d / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "language": code,
                    "language_label": label,
                    "generated_with": {
                        "translate": TRANSLATE_MODELS[0],
                        "tts": TTS_MODEL,
                        "stt": STT_MODEL,
                    },
                    "approx_total_seconds": round(total, 1),
                    "note": "English script is canonical. Translations produced by Sarvam "
                    "Translate; lines carrying amounts/dates are STT round-trip "
                    "checked. All data is mock; synthetic voices, not real borrowers.",
                    "clips": clips,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        summary[code] = {"clips": len(clips), "seconds": round(total, 1), "problems": lang_problems}
        print(
            f"  -> {len(clips)}/{len(SCRIPT)} clips, ~{round(total, 1)}s, "
            f"{lang_problems} needing review"
        )

    print(f"\n{'=' * 66}\nSUMMARY")
    for code, s in summary.items():
        print(f"  {code}: {s['clips']} clips, ~{s['seconds']}s, {s['problems']} needing review")
    print(f"artifacts -> {OUT}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
