# Sarvam API dependency smoke — 26 July 2026

This note records the live dependency check for bead `sarvam-agu`. The requests
ran from the backend workspace with the API key loaded at runtime from macOS
Keychain (`service=sarvam-api`, `account=vachan`). The key was never printed,
written to an artifact, added to Codex configuration, or placed in an
environment file.

## Current production models

| Capability | Endpoint | Model ID | Decision |
|---|---|---|---|
| Speech to text | `POST https://api.sarvam.ai/speech-to-text` | `saaras:v3` | Use explicitly with a `mode`; current recommended/default STT model |
| Text to speech | `POST https://api.sarvam.ai/text-to-speech` | `bulbul:v3` | Current stable TTS model; 24 kHz WAV used in this smoke |
| Chat completion | `POST https://api.sarvam.ai/v1/chat/completions` | `sarvam-30b` | Preferred for the latency-sensitive voice-agent path |
| Chat completion | `POST https://api.sarvam.ai/v1/chat/completions` | `sarvam-105b` | Supported higher-quality, higher-latency alternative |

`sarvam-m` is deprecated and no longer accepted. The removed fixed-context
variants (`sarvam-30b-16k`, `sarvam-105b-32k`) must not be used.

Official references:

- [Saaras model](https://docs.sarvam.ai/api/getting-started/models/saaras)
- [Speech-to-text REST reference](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe)
- [Bulbul model](https://docs.sarvam.ai/api/getting-started/models/bulbul)
- [Text-to-speech REST reference](https://docs.sarvam.ai/api-reference/text-to-speech/convert)
- [Chat completion reference](https://docs.sarvam.ai/api-reference/chat/chat-completions)
- [June 2026 model changelog](https://docs.sarvam.ai/api/getting-started/changelog)

## Live STT result

The input is a clearly labeled synthetic/prerecorded fixture generated with the
macOS Hindi voice `Lekha`:

```text
backend/tests/fixtures/sarvam_stt_smoke_hi.wav
WAVE · PCM16 little-endian · mono · 16,000 Hz · 2.653 seconds
Spoken text: नमस्ते, यह वचन की आवाज़ जाँच है।
```

Request shape:

```http
POST /speech-to-text
api-subscription-key: <Keychain value>
Content-Type: multipart/form-data

file=<audio/wav>
model=saaras:v3
mode=transcribe
language_code=hi-IN
```

Observed result:

```json
{
  "request_id": "20260726_133e6072-550b-49d5-8077-677f5d95e988",
  "transcript": "नमस्ते, यह वचन की आवाज जांच है।",
  "language_code": "hi-IN",
  "language_probability": null
}
```

- HTTP status: `200`
- End-to-end request time: `0.856278s`
- Response size: `181` bytes
- Result: expected Hindi sentence transcribed correctly aside from harmless
  orthographic normalization of `आवाज़`/`जाँच`

## Live TTS result

Request shape:

```http
POST /text-to-speech
api-subscription-key: <Keychain value>
Content-Type: application/json

{
  "text": "नमस्ते। यह वचन की आवाज़ जाँच है। कृपया कोई ओटीपी साझा न करें।",
  "target_language_code": "hi-IN",
  "model": "bulbul:v3",
  "speaker": "priya",
  "pace": 1.0,
  "speech_sample_rate": 24000,
  "output_audio_codec": "wav",
  "temperature": 0.6
}
```

Response shape:

```json
{
  "request_id": "20260726_edfcb479-ff96-4db6-b780-7d502a599d4d",
  "audios": ["<base64 WAV>"]
}
```

- HTTP status: `200`
- End-to-end request time: `2.973516s`
- Encoded response size: `344,200` bytes
- Decoded audio:
  `backend/artifacts/sarvam_tts_smoke_hi.wav`
- Audio properties: WAVE · PCM16 · mono · 24,000 Hz · 5.376 seconds
- Playback: successfully played through macOS `afplay`

## Headers, quota, and retry contract

Both successful responses included `x-request-id`, `cache-control: no-store`,
and standard security headers. Neither response included `X-RateLimit-*`,
quota-remaining, nor `Retry-After` headers.

The integration therefore must not infer remaining quota from successful
response headers. It should:

1. use the account dashboard for the exact active plan/limits;
2. treat `429` and `503` as retryable with bounded exponential backoff;
3. treat `400`, `403`, and `422` as non-retryable until the request or
   credential is corrected.

Published limits are per account, not per API key. The documented Starter
limits are 60 STT REST requests/minute, 30 Bulbul v3 REST requests/minute, and
40 requests/minute for `sarvam-30b`/`sarvam-105b`.

Reference:
[Credits and rate limits](https://docs.sarvam.ai/api/getting-started/ratelimits).

## Codex MCP installation

The official `sarvam-mcp` package is installed globally for Codex as the
enabled stdio server `sarvam`.

```text
Codex command: /Users/amrit/.local/bin/codex-sarvam-mcp
Package launcher: uvx sarvam-mcp
Observed package version: sarvam-mcp 0.2.8
Observed MCP runtime: FastMCP 3.4.4
Authentication at handshake: configured
```

The wrapper is owner-only (`0700`) and reads the API key from Keychain at
process start. `~/.codex/config.toml` stores only the wrapper path and no
environment value. A new Codex session is required before the newly configured
MCP tools appear in the tool registry.

Reference:
[Official Sarvam MCP server](https://docs.sarvam.ai/api/developer-tools/mcp).
