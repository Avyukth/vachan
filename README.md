# Vachan — वचन

A collections voice agent for Indian consumer lending that **earns trust in both directions**:
it proves itself before asking you to, refuses to reveal a debt until code — not the model —
confirms who is speaking, and writes every decision to an evidence ledger a regulator could read.

Built at the **Sarvam Epoch Buildathon** (GrowthX × Sarvam AI, Razorpay Arena, 26 July 2026) on
the Sarvam voice stack. *Vachan* means "promise" — the product's whole job is to make promises
worth the word: the borrower's, and its own.

## What This Is

An outbound voice agent that calls delinquent borrowers on behalf of a lender, in Hindi/English
code-mix, over a browser-mic demo page supervised by a human operator (Priya) who makes exactly
three moves per call: open case, start, inspect outcome.

**The thesis:** in Indian consumer collections, the scarce resource is not pressure — it is
trust, in every direction at once. The borrower can't trust callers (₹22,495 crore lost to
voice scams in 2025 — a suspicious borrower is being *rational*). The lender can't trust who
answered (shared handsets are the norm; the spouse learning the debt exists is the harm — and a
compliance violation). The lender can't trust promises ("haan, kal kar dunga" — fake
promises-to-pay poison dialler queues). The regulator can't trust call logs. Vachan attacks all
four with one architecture: **deterministic code controls identity, private context, and
writes; the language model only handles language.**

**What it replaces**: the dunning script — human or bot — that opens with the borrower's name
and overdue amount to whoever picks up. Sarvam's own public collection-agent cookbook is a
~60-line version of exactly that (hardcoded EMI, no identity handling). Vachan is the
structural opposite; see [Key Differences](#key-differences-from-the-sarvam-cookbook).

**What it keeps**: the full Sarvam stack — Saaras v3 (STT, code-mixed), a Sarvam chat LLM
(typed intent JSON), Bulbul v3 (TTS) — as the voice layer under a policy engine it cannot
override.

## The Problem, In Numbers

| Fact | Figure |
|---|---|
| India retail loan book | ₹170.2 lakh crore |
| Personal-loan accounts (3-year growth) | 73M → 146M |
| Gross NPAs | ~₹4.3 lakh crore |
| Collections economics | Commission-based, 5–20% of recovery |
| Lost to voice/cyber scams (2025) | ₹22,495 crore |
| Honest metric proposed | **Kept-promise rate** (not promise rate) + third-party disclosures per 1,000 calls (target: zero) |

## Architecture

```
Caller (borrower / spouse — judge, in the demo)  ⇄  mic / headphones
      │
      ▼
SvelteKit frontend :3000 ──── Cloudflare tunnel ──── https://sarvam.pathshala.dev
  Operator page (Priya): Start · Watch · Evidence   (public link / judges' phones;
  AudioWorklet PCM16 capture · TTS playback          stage demo runs on localhost)
      │  vite proxy: /api/* and /ws → :8000
      ▼
FastAPI backend :8000  (Python, uv-managed)
┌─────────────────────────────────────────────────────────────────┐
│  Dialogue controller — THREE state machines, transitions BY CODE │
│    call:     IDLE→PREFLIGHT→READY→ACTIVE→…→ENDED                 │
│    identity: UNVERIFIED→VERIFYING→CONFIRMED / THIRD_PARTY        │
│    promise:  NONE→CANDIDATE→READ_BACK→CONFIRMED→COMMITTED        │
│                                                                  │
│  Four disclosure layers (strongest first):                       │
│   1 context isolation — account data enters the LLM only at      │
│     CONFIRMED (the model cannot leak what it was never given)    │
│   2 tool isolation — account/commit tools throw unless CONFIRMED │
│   3 fixed templates pre-CONFIRMED (LLM selects, never writes)    │
│   4 pre-TTS output guard — multilingual blocklist, fail-closed   │
│                                                                  │
│  Sarvam APIs: Saaras v3 STT · chat LLM (typed JSON) · Bulbul v3  │
│  SQLite evidence ledger: cases · calls · events · tool_decisions │
│                          · promise_candidates · promises          │
└─────────────────────────────────────────────────────────────────┘
```

Diagrams: `vachan_product.drawio` (architecture · call flow · state machines).

## Product Mechanics

From the post-duel product plan (`VACHAN_PLAN_V2.md`), with honest build status
(`VACHAN_MVP_V2.md` governs what ships today):

`MVP core` below means the deterministic component and its offline safety tests are implemented.
It does **not** mean the real spoken-call or operator journey is complete: those release gates
remain tracked by `sarvam-v8o` and `sarvam-ch1`.

| Mechanic | What it does | Status |
|---|---|---|
| **Bidirectional trust gate** | Agent proves itself first (anti-scam pledge, no lender name, never asks OTP/PIN), then verifies the caller with two seeded values compared in code — never spoken, never sent to the LLM | **MVP core** |
| **Mid-call handover demotion** | "Lo, baat karo" — phone changes hands, identity demotes the same turn, tools relock, nothing said before is summarized to the new speaker | **MVP core** |
| **Echo-confirmed promise** | Amount in minor units, date normalized to ISO (Asia/Kolkata), read back in dual format — digits + words + weekday + absolute date — committed only on an explicit yes, idempotent | **MVP core** |
| **The refusal suite** | Refuses its own operator (contact-cap blocks Start at preflight), fails closed on technical errors, break-glass takeover silences the agent permanently | **MVP core** |
| **Evidence runner** | Timestamped test artifact regenerated before the demo; failures shown and diagnosed, never hidden | **MVP core** |
| **Structured cross-call memory** | A prior confirmed promise retrievable only after fresh verification in a new call; corrections append, never mutate | Competition evidence (gated) |
| **Truth-priced negotiation** | Negotiate *down* to a keepable amount; kept-promise rate as the metric | Pitch + roadmap |
| **Hesitation-priced promises** | Prosody (pause ratio, speech rate) prices commitment confidence, with a spoken borrower override | Research track (post-event) |
| **Two-way vachan (voice replay)** | The borrower's promise kept as their own recorded voice, consent-gated, deletable with stated residue | Later phase (needs real consent/retention governance) |
| **Admin results console** | Nandini (collections lead) sees aggregates only — never transcripts: least-disclosure applies to management too | Stitch design only (see below) |

## Requirements

- macOS with the **Sarvam API key in the Keychain** (already provisioned):
  `security add-generic-password -s sarvam-api -a vachan -w '<key>'`
- [uv](https://docs.astral.sh/uv/) — Python backend (never pip/venv)
- [bun](https://bun.sh) — SvelteKit frontend (never npm)
- **Wired headphones** — non-negotiable: open speakers feed Bulbul's voice back into the mic
  and the agent talks to itself
- Optional: `cloudflared` for the public link (tunnel `rust-fast-experiment` → localhost:3000)

## Quick Start

```bash
# Backend (terminal 1)
cd backend
uv sync
uv run uvicorn app.main:app --port 8000 --reload
# → key is read from Keychain at startup; first run triggers a macOS dialog: Always Allow

# Frontend (terminal 2)
cd frontend
bun install
bun run dev            # :3000, proxies /api and /ws to :8000

# Open http://localhost:3000 — grant mic permission ONCE during setup, never on stage

# Public link (optional, submission / judges' phones)
cloudflared tunnel run rust-fast-experiment   # → https://sarvam.pathshala.dev
```

> **Never** put the API key in `.env`, code, or the frontend. It exists in the Keychain and the
> backend process only.

## The Trust Model

| Layer | Question it answers | Mechanism | Failure mode |
|---|---|---|---|
| Anti-scam pledge | "Why should I trust this call?" | Fixed intro: no OTP/PIN ever, no payment on-call, no lender name pre-verification | — (template, cannot fail open) |
| Identity gate | "Who is speaking?" | Two seeded values (birth day-month, ref last-4) normalized and compared **in code**; two attempts; kinship terms ("haan boliye", "bhai") never count as confirmation | Fails to THIRD_PARTY / VERIFICATION_FAILED — never open |
| Context isolation | "What can the model leak?" | Account data is absent from every prompt until CONFIRMED | Nothing to leak |
| Tool gate | "What can the model do?" | `read_mock_account` / `commit_promise` throw typed failures unless CONFIRMED; every denial is a ledger row | Denied + logged |
| Output guard | "What if it tries anyway?" | Pre-TTS multilingual blocklist (amounts, debt words, lender name, fabricated credentials); entire draft discarded, safe line spoken | `OUTPUT_BLOCKED` event |
| Handover demotion | "What if the phone changes hands?" | CONFIRMED → UNVERIFIED in the same turn; instant relock; no carryover; borrower may re-verify (THIRD_PARTY → VERIFYING) | Fails to locked |

Every call ends in **exactly one disposition**:

| Disposition | Meaning |
|---|---|
| `PROMISE_CONFIRMED` | Echo-confirmed, idempotently committed promise (amount + ISO date) |
| `CALLBACK_THIRD_PARTY` | Content-free callback left — nothing disclosed **is** the completed job |
| `VERIFICATION_FAILED` | Two failed attempts; close reveals nothing, tools never opened |
| `ENDED_TECHNICAL` | A dependency broke; fails closed — never converts to a business outcome |
| `ENDED_OPERATOR` | Break-glass takeover; agent silenced permanently, reason required |

## Mounted API Surface

These routes are mounted by the current FastAPI application. REST under `/api` and WebSockets
under `/ws` are vite-proxied to :8000. The frozen schema is bead `sarvam-3s2`.

<!-- mounted-api:start -->
| Method | Path | Description |
|---|---|---|
| GET | `/api/cases` | Seeded mock cases |
| POST | `/api/preflight` | mic · audio · backend · Sarvam · eligibility · contact-cap → `READY` / `BLOCKED_POLICY` / `BLOCKED_TECHNICAL` |
| POST | `/api/call/start` | Start (only from `READY`) → `call_id` |
| POST | `/api/call/end` | End with reason |
| POST | `/api/takeover` | Break-glass: revoke tools → cancel work → stop TTS → log |
| POST | `/api/reset` | Reseed demo data (403 during active calls) |
| POST | `/api/audio/check` | Fixed reviewed Bulbul headphone/autoplay check |
| WS | `/ws/call/{call_id}` | PCM16 up (streaming transport) · JSON events down |
| GET | `/healthz` | Liveness |
<!-- mounted-api:end -->

### Frozen contract, not currently mounted

The v0 protocol reserves the following route, but the current application does not implement or
mount it. The operator console currently proves its view model with an explicitly labeled replay;
the live SQLite-backed event journey remains part of `sarvam-ch1`.

<!-- contract-api:start -->
| Method | Path | Description |
|---|---|---|
| GET | `/api/evidence/{call_id}` | Contracted ordered event timeline; not mounted |
<!-- contract-api:end -->

## The Demo (120 seconds, adversarial)

One continuous call — judges play the callers:

| t | Beat |
|---|---|
| 0:00 | Priya: preflight `READY`, Start — her first of three actions |
| 0:10 | Judge-as-Rakesh: "scam hai kya?" → anti-scam template, zero debt words |
| 0:25 | Two verification values → code flips `CONFIRMED`, tool-unlock visible |
| 0:40 | "₹1,500, Friday" → read-back: digits + words + weekday + absolute date |
| 1:05 | Explicit "haan" → one committed promise row |
| 1:15 | Phone handed to "Sunita"; she asks the balance → demotion, relock, content-free refusal |
| 1:30 | Evidence timeline explains every decision |
| +20s | Capped case: Start **disabled** at preflight — the system refuses its own operator — then the freshly generated runner artifact |

Framing line: *"The voice model handles language. Deterministic code controls identity, private
context, and writes. Priya supervises exceptions — and is bound by the same rules as the agent."*

## Development

Work is tracked as a **beads graph** — run `br stats` for current counts, `br ready` for
unblocked work, and `bv --robot-next` for the top pick. Bead bodies are self-contained specs with
acceptance criteria and test vectors. See `AGENTS.md` for the full operating manual.

```bash
# Quality gates
cd backend  && uv run ruff check . && uv run pytest -x -q     # 13-case matrix must be green
cd frontend && bun run check

# Evidence runner (tier-3, regenerated before any demo)
cd backend && uv run python -m app.runner
```

| Test tier | What | Where |
|---|---|---|
| 1 Unit | State machines, normalization (lakh/hazaar → paise, "shukravaar" → ISO), guard vectors | pure functions, no fixtures |
| 2 Integration | 13-case matrix through real controller + tools + guard + SQLite, FakeSarvamClient | offline, <30s |
| 3 Evidence | Runner: real Saaras STT on three labeled prerecorded `synthetic-hi-IN` WAVs, then code-owned controller boundaries; not a real human/live call | <2 min artifact |

Formal human/live rehearsals are a separate, still-pending gate in `sarvam-ztt`; they are not
included in the generated runner score.

```
backend/app/          states · verification · tools · guard · promise · controller ·
                      sarvam_client · db · runner · main
frontend/src/routes/  operator page (Start · Watch · Evidence)
.beads/               the task graph — THE plan
```

## Design

UI follows the **Kinetic Operator** design system (`DESIGN.md`): graphite `#101214`, panels
`#191D21`, one amber accent `#D97B29` reserved for promise moments, green/rust semantic-only,
monospace for every number and state label. Blueprints live in the Stitch project
*"Vachan — Collections Voice Agent Demo"* (6 screens: journey map, minimal operator journey,
two journey-card decks, admin results console, V2 card deck) — local exports: `vachan_*.png`.

## Key Differences from the Sarvam Cookbook

Declared in submission notes as a **"borderline starting point" flag** (the event's rules:
flagging is safe; hiding origin is auto-disqualification). Built from zero on the floor.

| Aspect | Sarvam collection-agent cookbook | Vachan |
|---|---|---|
| Identity | None — speaks to whoever answers | Three-state machine in code; two-value verification; handover demotion |
| Disclosure | Amount hardcoded in the system prompt | Context isolation: model never holds account data pre-CONFIRMED |
| Tools | None | Permission matrix; typed failures; every denial ledgered |
| Promise | Conversational only | Candidate → read-back → explicit yes → idempotent commit, ISO dates |
| Evidence | None | Append-only SQLite ledger + timestamped test artifact |
| Operator | None | Preflight-gated Start, watch-by-exception, break-glass takeover |
| Failure | Undefined | Fails closed; five dispositions; technical ≠ business outcome |

## Documents

| File | Purpose |
|---|---|
| `VACHAN_PLAN_V2.md` | Product vision — six mechanics, rubric mapping (this README's source) |
| `VACHAN_MVP_V2.md` | Build-day operating plan — layered scope, clock, cut order (wins conflicts) |
| `VACHAN_MVP_codex.md` | Detailed spec — schemas, contracts, dialogue controller, test matrix |
| `AGENTS.md` | Operating manual for AI coding agents (safety rules, tooling, stack) |
| `DUELING_WIZARDS_REPORT.md` | How the plan was adversarially derived (3-model duel) |
| `vachan_product.drawio` | Architecture, call-flow, and state-machine diagrams |
| `.beads/` | 53-bead implementation graph with dependencies |
