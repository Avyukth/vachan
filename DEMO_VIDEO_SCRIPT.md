# Vachan — 2:00 demo video script

**Total 120s. Narration ~290 words (≈150 wpm) — do not exceed; silence beats rushing.**
Every beat below was verified working on 26 Jul. Nothing here is aspirational.

**Setup before you hit record**
- `cd frontend && bun run build && bun run preview --port 3000` — **production build, never `bun run dev`**
  (HMR reloads wipe Svelte state mid-take).
- Backend: `cd backend && uv run uvicorn app.main:app --port 8000`
- Mic permission already granted on `localhost:3000` as **"Allow on every visit"**.
- **Wired headphones in** — open speakers feed Bulbul back into the mic.
- Reset demo data. **Scroll so the operator console is already in frame** (page is ~1960px;
  console sits ~1050px down — do not scroll on camera).
- Regenerate the artifact last: `uv run python -m app.runner` so its timestamp is after your
  final commit.
- If driving the caller from fixtures, arm simulated-caller mode **on camera** so the
  `SIMULATED CALLER — PRERECORDED AUDIO` banner is visible. Never hide it.
- The happy caller is three conversational utterances, with one flush and one agent response
  between each: **"मैं राकेश बोल रहा हूँ।" first**, then the two verification values, then the
  promise. Never lead with verification values or combine the three lines into one monologue.

---

| Time | Screen | Narration (say exactly this) |
|---|---|---|
| **0:00–0:10** | Slide 02 of the deck (the 4U problem slide) | "In Indian collections the dialler puts the borrower's name and overdue amount in line one. On a shared handset, a wife or a neighbour learns about the debt before anyone knows who answered." |
| **0:10–0:20** | Operator console. Cursor on the case list → click **Start mock call** | "This is Priya's console. She makes three actions all call. This is the first." |
| **0:20–0:34** | WATCH panel filling; identity chip reads **UNVERIFIED**; agent speaks the blind greeting | "The agent speaks first and reveals nothing — no lender, no amount, no reason. It promises it will never ask for an OTP or a PIN, then asks who it is talking to." |
| **0:34–0:50** | Caller says **"मैं राकेश बोल रहा हूँ।" first**; only after Vachan asks does he give the two values. Identity flips **UNVERIFIED → VERIFYING → CONFIRMED** (green). Tool-unlock row appears in EVIDENCE | "He identifies himself first. Then two seeded values are compared in code — never spoken by the agent, never sent to the model. Only now does the loan exist in this conversation at all." |
| **0:50–1:06** | Promise offered. Agent reads back. **Freeze/zoom the read-back line.** Amber COMMITTED chip | "Fifteen hundred rupees, by Friday. It reads that back twice over — words, digits, weekday, absolute date — so a misheard hazaar can never become a debt. Nothing is written until he says yes." |
| **1:06–1:22** | **THE BEAT.** Phone hands over. Identity chip → **THIRD_PARTY** (rust) in the same turn. Spouse asks the balance. Agent refuses | "Then he hands the phone to his wife. Identity demotes in that same turn, the tools relock — and she asks how much is owed." *(pause 1s, let the refusal play)* "No amount. No lender. No reason." |
| **1:22–1:34** | EVIDENCE column: scroll the ordered timeline; **FINAL DISPOSITION** bar | "Every decision is an append-only ledger row, including every refusal. One call, exactly one disposition." |
| **1:34–1:48** | Switch case to **Farida (cap 0)** → preflight → **BLOCKED_POLICY**, Start greyed out. Zoom the reason text | "And it refuses its own operator. Contact cap reached — Priya cannot override this. The call is stopped before a session even exists." |
| **1:48–1:58** | Terminal: the runner artifact, **17/17** | "Fourteen deterministic cases and three on real speech-to-text, regenerated minutes before this recording. If one had failed, you would be seeing the failure." |
| **1:58–2:00** | Title card: **Vachan — वचन** | "The safe call is the only call this system can make." |

---

## Shot discipline

- **One continuous screen recording** for 0:10–1:34. Do not cut inside the call — the whole
  claim is that this is one unbroken session.
- **Zoom twice only**: the read-back line (0:50) and the BLOCKED_POLICY reason (1:34). Those are
  the two things a judge must be able to read.
- Amber appears **once** — at COMMITTED. If anything else on screen is amber in your take,
  you are drawing the eye to the wrong thing.
- Let the refusal at 1:06 breathe. A one-second silence after "how much is owed" does more than
  narration.
- Do not narrate over the agent's own voice. Duck your commentary when Bulbul speaks.

## Latency handling (measured 3–7s per turn — plan for it)

Model time per turn is real and will show. Two legitimate options, pick one and be consistent:
1. **Cut the dead air** between turns in the edit, and say once at 0:20: *"turn latency trimmed"*
   on screen as a caption. Honest, and keeps the 2:00 budget.
2. **Leave it in** and drop one narration line to make room. Slower, but nothing to disclose.

Do **not** silently speed up the audio — a judge who hears chipmunked Hindi will distrust
everything else in the video.

## Honesty rules for this recording (non-negotiable)

- All data is mock; the `DEMO / MOCK DATA` badge must be visible in frame throughout.
- If simulated-caller mode drives any caller audio, its banner stays visible on camera.
- Verification is a demo mechanism, not production authentication — if you claim otherwise on
  camera it contradicts the submission notes.
- Do not show a runner artifact older than your last commit, and do not hand-edit it.

## If something breaks mid-take

| Symptom | Do this |
|---|---|
| Call will not start, preflight says `active_session` | Re-record after Reset; orphan reconciliation now handles restarts |
| Agent talks over itself | Headphones are unplugged. Stop, plug in, restart the take |
| Bulbul check hangs on CONNECTING | Do not double-click it; the second click aborts the first. Reload and click once |
| Takeover leaves audio check red | Expected — do the capped-case beat **before** any takeover, or re-run the check off camera |
