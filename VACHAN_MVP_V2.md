# VACHAN MVP V2 — post-critique operating plan

**Lineage:** supersedes `VACHAN_MVP.md` (kept, unmodified) after critical review of
`VACHAN_MVP_codex.md`. The Codex document is the detailed spec; THIS file is the operating plan.
Where they conflict, this file wins.

## Critique verdicts (what changed and why)

| Codex point | Verdict | Effect |
|---|---|---|
| §1.2 MediaRecorder≠PCM16: audio transport unspecified | **ADOPT — best catch in the doc** | Audio spike with hard H0:45 streaming-vs-REST decision |
| §1.5 Regex guard too brittle as primary boundary | **ADOPT** | 4 layers: context isolation → tool isolation → templates → guard |
| §1.10 Demo arc was two calls in disguise | **ADOPT** | One continuous call: verify → commit → handover → refuse |
| §1.4 Verification unspecified | **ADOPT** | 2 seeded values, never spoken, 2 attempts, handover invalidates |
| §1.6/1.7/1.8 Split state machines; candidate→committed events; ISO dates | **ADOPT** | Call / identity / promise enums; event-sourced promise; Asia/Kolkata |
| §1.9 No exception paths | **ADOPT (trimmed)** | 5 dispositions; takeover order; preflight |
| §5.6 Contact-cap refused at preflight, not mid-call | **ADOPT** | Stronger than agent refusing after dial |
| §1.12 Text-first build, dependency spike, H4:30 freeze | **ADOPT** | New clock below |
| §7 "Typed 12/13 is not test evidence" | **ADOPT** | Runner artifact regenerated pre-demo, real pass/fail |
| §1.3 Hesitation meters "impossible" | **PARTIAL** | Demoted for time; note: latency/wps ARE available client-side |
| Voice-vachan killed entirely | **PARTIAL** | Demoted to optional final polish w/ consent line — not deleted (duel score 893) |
| Fixed templates pre-CONFIRMED | **ADOPT w/ nuance** | LLM classifies intent, code picks template — deterministic output, responsive selection |
| Nandini admin = stakeholder only today | **ADOPT** | Matches user's "product first"; Stitch designs carry admin story |

## Layered scope (replaces "core + stretch ladder")

### Layer 1 — PRODUCT CORE (freeze gate; nothing else counts until green)
1. One browser operator page (Priya) with `DEMO / MOCK DATA` label.
2. Real Sarvam loop; transport decided at H0:45: **streaming PCM16/16kHz via AudioWorklet+WS**
   or **turn-based REST** (honest about no barge-in). Key stays on backend.
3. Three state machines in code, transitions ledgered:
   - call: IDLE→PREFLIGHT→READY→ACTIVE→ (COMPLETED | DEGRADED | OPERATOR_TAKEOVER | ENDED)
   - identity: UNVERIFIED→VERIFYING→CONFIRMED; →THIRD_PARTY; CONFIRMED→UNVERIFIED on handover;
     THIRD_PARTY→VERIFYING when the borrower reclaims the phone (fresh two-value challenge —
     amendment 26 Jul, closes the dead-end found in bead review). Never restored across calls.
   - promise: NONE→CANDIDATE→READ_BACK→CONFIRMED→COMMITTED; corrections force re-read-back;
     idempotent commit.
4. Verification contract: caller provides 2 seeded values (DOB day+month; last-4 of mock ref);
   compared in code, never spoken by agent, never sent to LLM; 2 attempts max → VERIFICATION_FAILED;
   handover/third-party language clears confirmation. Labeled a demo mechanism, not production auth.
5. Disclosure protection, four layers: (a) account data enters LLM context only at CONFIRMED;
   (b) account/commit tools unavailable before CONFIRMED (typed failure + guard event);
   (c) pre-CONFIRMED replies are fixed safe templates, LLM-selected by intent;
   (d) multilingual pre-TTS blocklist as last defense — on fire: discard draft, play fixed line,
   log OUTPUT_BLOCKED (never log the draft body).
6. Echo-confirmed promise: amount in minor units; date normalized to ISO in Asia/Kolkata; spoken
   back as digits + words + weekday + absolute date; explicit yes required; corrections re-read.
7. SQLite evidence: cases, calls, events (ordered, append-only), tool_decisions,
   promise_candidates, promises, operator_notes. Reset reseeds demo data only.
8. Exactly five dispositions: PROMISE_CONFIRMED · CALLBACK_THIRD_PARTY · VERIFICATION_FAILED ·
   ENDED_TECHNICAL · ENDED_OPERATOR. Technical failure never becomes a business outcome.
9. Operator journey: preflight (mic/audio/backend/Sarvam/eligibility/contact-cap) gates Start;
   watch-by-exception; End always available; break-glass takeover in strict order
   (revoke tools → cancel pending work → stop TTS → log → THEN the human speaks; no agent
   resume). Amendment 26 Jul: in the browser-mic demo, "open operator mic" is physical, not
   software — one laptop, one mic, one room; the software's obligations are guaranteed agent
   silence, a TAKEOVER banner, and End-with-reason.

### Layer 2 — COMPETITION EVIDENCE (only after Layer 1 gate, target start ≤ H4:00)
- **CE1 Structured cross-call memory (25-min box):** prior confirmed promise retrieved ONLY after
  fresh verification in a new call; correction appends an event; no audio stored. This is the
  Memory-parameter evidence.
- **CE2 Test runner artifact:** ≥8 deterministic scenarios through the real pipeline (prerecorded
  inputs labeled as such; TTS playback skippable); timestamped output regenerated immediately
  before the demo; honest failures shown. Minimum matrix: correct verify / one-wrong-then-right /
  two-wrong / spouse asks 3× / commit ₹1,500 / correction ₹1,050 / no-at-read-back / handover
  after confirm / LLM drafts balance while unverified / duplicate confirm / STT drop / takeover /
  contact-cap.
- **CE3 Impact framing:** kept-promise rate stated as the proposed pilot metric — no invented
  KPI values from seeded calls.

### Layer 3 — LATER (not today): audio memory (voice-vachan: optional final polish ONLY if
Layers 1–2 green — one consent line, no deletion claims beyond what's real), hesitation scoring
(client-side timing exists; research track), 5-branch outcomes, standing instructions, admin
analytics (Stitch designs carry it), telephony, hash chains, biometrics.

## Demo arc — ONE continuous call (~100s) + 20s refusal

| t | Beat | Proof |
|---|---|---|
| 0:00 | Priya opens Rakesh case → preflight READY → Start | 1 operator action; guards visible |
| 0:10 | "Scam hai kya?" → fixed anti-scam template | No debt words pre-verification |
| 0:25 | Rakesh gives 2 values → code flips to CONFIRMED | Tool unlock event on screen |
| 0:40 | Offers ₹1,500 "Friday" → read-back: digits + words + absolute date | Candidate + read-back events |
| 1:05 | Explicit "haan" → single committed promise | Idempotent commit row |
| 1:15 | Hands phone to Sunita; she asks balance | Demotion + relock + content-free refusal |
| 1:30 | Priya opens Evidence | Ordered timeline explains every decision |
| +20s | Second case: contact cap exhausted → Start DISABLED at preflight | Refusal before any session exists; then show fresh runner artifact |

Framing line: *"The voice model handles language. Deterministic code controls identity, private
context, and writes. Priya supervises exceptions — and is bound by the same rules as the agent."*

## Clock (six hours)

| Slot | Work | Exit gate |
|---|---|---|
| H0:00–0:20 | Freeze contracts: enums, transition table, LLM action schema, tool matrix, seeded cases (eligible + capped) | Implementable without product decisions |
| H0:20–0:45 | Dependency + audio spike: creds, model IDs, one STT req, one TTS req, PCM round-trip attempt | **H0:45: transport decision, permanent** |
| H0:45–1:45 | Text-first safety core: states, verification, isolation, promise logic, SQLite; tests WITHOUT voice | Safety tests pass in text mode |
| H1:45–2:45 | Voice vertical slice on chosen transport + timeouts/cancellation | One spoken call reaches a correct candidate |
| H2:45–3:30 | Operator page: preflight, 3 columns, End/Takeover, MOCK labels | Priya completes a call without dev tools |
| H3:30–4:10 | Edge paths: third-party, handover, 2-fail, technical end, contact-cap | All core cases pass once |
| H4:10–4:30 | Test runner + demo reset | Artifact generated from current build |
| H4:30–6:00 | **FREEZE.** Rehearse: 3× happy, 3× third-party, 1 forced failure + takeover; venue hardware; tunnel (sarvam.pathshala.dev); submission notes w/ borderline flag + cookbook deltas; final runner run | Live path ≤105s; all criteria green |

**Cut order if behind:** polish → dynamic anti-scam (keep one fixed line) → live transcript (keep
state + evidence) → contact-cap live demo (keep its test) → LLM phrasing post-confirm (fixed
templates). **Never cut:** audio fallback, gates/isolation, output guard, echo-confirm, technical
ending, takeover order, mock labels, rehearsal.

## Unchanged from before
Personas (Priya operator / Nandini stakeholder / Rakesh / Sunita) · Stitch design set (5 screens,
"Kinetic Operator") · Cloudflare tunnel live at sarvam.pathshala.dev · compliance posture
(from-zero build, borderline flag, cookbook delta list) · draw.io product diagram
(`vachan_product.drawio` — update state names to V2 enums when time permits).
