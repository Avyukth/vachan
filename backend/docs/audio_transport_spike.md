# PCM16 streaming transport spike — 26 July 2026

Bead: `sarvam-qut`

## Result

**Working raw-PCM round trip.** The H0:45 decision can choose streaming:

```text
browser AudioWorklet
  → mono signed PCM16 at 16,000 Hz
  → binary browser WebSocket frames
  → FastAPI backend relay
  → Saaras v3 streaming WebSocket
  → finalized transcript events
```

The API key remains backend-only. The browser never connects directly to
Sarvam.

## Live dependency measurement

The existing clearly labeled synthetic fixture
`tests/fixtures/sarvam_stt_smoke_hi.wav` was read as PCM16 frames and streamed
in real-time-sized 100 ms chunks through the production Saaras v3 WebSocket.

| Measurement | Observed |
|---|---:|
| Audio | 2.653 s, mono PCM16, 16 kHz |
| WebSocket handshake | 521 ms |
| First finalized segment | 1,370 ms after start |
| Final segment processing latency reported by Saaras | 285 ms |
| Final transcript | `नमस्ते यह वचन की आवाज जांच है।` |

An unpaced send also succeeded, proving the raw codec contract independently
of real-time capture timing: handshake 218 ms, first result 239 ms after the
buffer was sent.

The same paced fixture was then sent through Vachan's mounted FastAPI browser
WebSocket relay (not directly to the SDK). It returned both transcript
segments in 3.619 seconds wall time; Saaras reported 82 ms and 177 ms
processing latency for the two segments.

No credential value was printed or persisted.

## Contract details and gotchas

- Connection: `wss://api.sarvam.ai/speech-to-text/ws`
- Model/mode: `saaras:v3`, `transcribe`
- Connection codec: `input_audio_codec=pcm_s16le`
- Sample rate: exactly `16000` on both connection and audio messages
- Payload: base64 PCM inside the documented `audio` JSON envelope
- Manual finalization: connection uses `flush_signal=true`; client sends
  `{"type":"flush"}` after stopping capture
- The official SDK currently fixes each message's `encoding` field to
  `audio/wav`; the connection-level raw codec controls interpretation. This
  exact combination was tested live.
- Browser-native sample rates are commonly 48 kHz. The AudioWorklet averages
  source windows into a continuous 16 kHz stream before signed-int16 encoding.
- `AudioContext.resume()` and microphone permission are initiated by the Start
  button to satisfy autoplay/user-gesture policy.
- Capture requests mono input with echo cancellation, noise suppression, and
  auto gain; wired headphones remain mandatory.

Official references:

- <https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api>
- <https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/ws>

## Honest boundary

The production Saaras PCM transport was exercised with a prerecorded synthetic
fixture. The browser AudioWorklet path is implemented and type-checked, but an
automated agent cannot grant macOS browser microphone permission or speak into
the physical device. The `/audio-spike` page is the explicit human hardware
check; it is separate from the operator flow and carries a spike label.
