# VACHAN v2 — Codex Critical Revision

**Constraint:** six build hours, a 60–120 second live demo, and no existing application code.

**MVP thesis:** a collections voice agent that cannot disclose debt or record a promise until the
right person is confirmed, and that gives a human operator a legible, auditable outcome.

**MVP product sentence:** Vachan proves who it is, verifies who answered, conducts one
privacy-safe promise-to-pay flow, and shows the operator exactly what happened.

This revision intentionally narrows the original plan. The product should first prove one
end-to-end job reliably. Memory experiments, behavioral scoring, speaker-change acoustics, and
the broader refusal suite belong after that vertical slice works.

---

## 1. Critical findings in the original plan

### Finding 1 — the load-bearing timestamp assumption is wrong for the live path

The original plan says Saaras v3 streaming word timestamps are load-bearing. Sarvam's current
API comparison says the WebSocket streaming endpoint returns transcripts per utterance and VAD
events, but **does not return timestamps**. Word/chunk timestamps are available on non-streaming
paths, not the live WebSocket path.

Therefore:

- live hesitation pricing based on word timestamps is not an MVP capability;
- the pause-ratio and words-per-second ribbon cannot be promised from the chosen live API;
- adding a second post-turn transcription request would add latency, cost, synchronization
  complexity, and a new failure mode;
- the demo must not imply that a raw ASR transcript proves confidence, willingness, or truth.

**Decision:** remove hesitation-priced promises from the MVP. Reintroduce them only as a
post-MVP experiment with an explicit validation dataset and a non-punitive UX.

Sources:

- [Sarvam: Which Speech-to-Text API to Use](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/which-api-to-use)
- [Sarvam: Streaming Speech-to-Text API](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api)
- [Sarvam: Saaras model response format](https://docs.sarvam.ai/api/getting-started/models/saaras)

### Finding 2 — this is several prototypes presented as one MVP

The original six-hour critical path contains:

1. browser audio capture;
2. streaming STT;
3. LLM dialogue;
4. streaming TTS;
5. identity state machine;
6. pre-TTS disclosure guard;
7. five terminal collection states;
8. SQLite event persistence;
9. hesitation scoring;
10. audio consent, recording, replay, and deletion;
11. cross-call self-audit;
12. natural-language policy extraction;
13. pitch-based speaker-change detection;
14. an adversarial audio runner;
15. an operator console;
16. a polished 120-second performance.

Each can fail independently. The plan allocates almost no time for integration, API mismatch,
browser permission failures, latency tuning, or rehearsal. Its stated "floor" is not a floor
because it still depends on voice, identity, persistence, consent, and a seeded second call.

**Decision:** ship one vertical path and one guarded refusal. Everything else is a later phase.

### Finding 3 — inference is being treated as a compliance control

An LLM may classify intent and extract candidate values, but it must not decide whether debt can
be disclosed or whether a promise can be written. Those are authorization decisions.

**Decision:** use deterministic code for:

- identity state transitions;
- tool availability;
- amount/date confirmation;
- disclosure blocking;
- contact-cap and quiet-hour checks;
- ledger writes.

The LLM can propose dialogue and candidate structured values. Code validates and authorizes them.
If parsing is ambiguous, the system asks again; it does not guess.

### Finding 4 — a pitch tracker is not identity verification

Pitch varies with noise, illness, emotion, device, age, and the same person's speaking style.
A fixed 35% threshold is unvalidated and can create both false demotions and a misleading air of
biometric certainty. Voice-derived identity signals also raise privacy and governance questions
that the plan does not address.

**Decision:** no pitch-based identity mechanism in the MVP. A lexical handover such as
"phone de raha hoon" can conservatively demote the session to `UNVERIFIED`; re-verification is
required before any further disclosure. Acoustics may be researched later, never used to promote
identity, and never marketed as authentication.

### Finding 5 — voice replay is riskier than the plan admits

Playing a borrower's old voice is itself a disclosure action. "CONFIRMED speaker" is not a
sufficiently specified authentication standard, and deletion semantics are incomplete: browser
blobs, backups, logs, hashes, transcripts, and derived fields may survive. A clip hash does not
solve consent, retention, access, or deletion.

**Decision:** store structured commitment data only in the MVP. Defer audio recording/replay until
there is a defined purpose, consent record, retention period, access policy, complete deletion
contract, and threat model.

### Finding 6 — the operator journey is described, not designed

"Start → Watch → Export" omits the operator's real decisions:

- Why is this case callable now?
- What happens if the microphone or an API fails?
- When may the operator intervene?
- Does intervention stop the agent and its tools?
- How is an ambiguous or incomplete call dispositioned?
- Can the operator correct a transcription without rewriting history?
- How does the operator safely retry?

The proposed "47 agent actions" is vanity telemetry. It does not prove autonomy or safety.

**Decision:** define the human journey as states, allowed actions, failure recovery, and
acceptance criteria. Measure interventions and completed outcomes, not action counts.

### Finding 7 — the demo tries to prove too many rubric points at once

The 120-second arc includes hostility, anti-scam proof, verification, policy authoring,
negotiation, hesitation repricing, voice recording, handover, acoustic demotion, cross-call
memory, confession, deletion, and test evidence. Even if every component works, judges cannot
understand or trust that many claims in two minutes.

**Decision:** the live demo proves one job:

> a human operator starts an eligible case; the agent verifies the borrower, safely captures one
> promise, blocks a third-party disclosure, and returns a usable outcome.

Other rubric evidence appears on a static evidence panel or is deferred.

### Finding 8 — several claims need evidence or softer language

- Do not claim that timestamp features are immune to room noise or universally indicate promise
  confidence.
- Do not imply that a speaker's hesitation makes a promise less truthful without validation.
- Do not cite a commission percentage or regulatory conclusion in the product unless the source
  is verified and retained.
- Do not present a seeded violation or prerecorded gauntlet output as live product evidence.
- Do not say the system can "show a judge every rule it obeyed"; say it records the specific
  state transitions, guard decisions, and tool calls implemented in the MVP.

---

## 2. Product boundary

### The one MVP job

Given an eligible mock account and a browser microphone, Nandini starts a call. Vachan:

1. identifies itself without revealing debt;
2. asks for privacy-safe borrower verification;
3. unlocks account tools only after deterministic verification succeeds;
4. asks for one payment amount and date;
5. reads both back and requires an explicit yes;
6. writes the confirmed promise to SQLite;
7. demotes identity and blocks disclosure if the phone changes hands;
8. returns one clear operator disposition and evidence record.

### MVP users

- **Borrower — Rakesh Yadav:** wants to know the call is legitimate, avoid disclosure to others,
  and make a realistic commitment without being trapped by an ASR mistake.
- **Operator — Nandini:** wants eligible cases handled without live scripting, unsafe disclosure,
  or manual note-taking, while retaining a safe takeover and retry path.
- **Collections lead:** wants structured outcomes, guard evidence, and honest failure reasons.

### Explicit non-goals for the six-hour MVP

- production telephony;
- real lender or payment integration;
- voice biometrics or speaker recognition;
- hesitation/confidence scoring;
- cross-call audio replay;
- five fully implemented terminal branches;
- autonomous hardship adjudication;
- regulatory certification;
- production authentication, encryption, retention, or tenancy;
- a generic rules engine;
- proving collection uplift or kept-promise rate from demo data.

The UI must label all account, payment, eligibility, and verification data as **DEMO / MOCK**.

---

## 3. MVP architecture

### 3.1 Components

1. **Browser operator console**
   - microphone permission and audio-level check;
   - case preflight;
   - Start Call, End Call, and Break-glass Takeover;
   - live transcript, identity state, guard events, and final disposition;
   - headphones required for the demo.

2. **Voice session adapter**
   - streams supported WAV or raw PCM audio to Saaras v3;
   - receives final utterance transcripts and optional VAD start/end events;
   - sends approved response text to Bulbul v3 streaming TTS;
   - has explicit timeout, disconnect, and retry states.

3. **Deterministic call state machine**

   ```text
   READY
     -> CONNECTING
     -> UNVERIFIED
     -> VERIFYING
     -> CONFIRMED
     -> AWAITING_PROMISE
     -> AWAITING_ECHO_CONFIRMATION
     -> COMPLETED

   Any live state
     -> PAUSED_OPERATOR_TAKEOVER
     -> ENDED_MANUAL

   UNVERIFIED / VERIFYING / CONFIRMED
     -> THIRD_PARTY
     -> CALLBACK_ONLY

   Any integration failure
     -> DEGRADED
     -> ENDED_TECHNICAL
   ```

   Only deterministic application code changes these states. The LLM may emit a proposed intent;
   application code validates it against allowed transitions.

4. **Tool gate**
   - `verify_borrower(candidate_answers)` is available before confirmation;
   - `read_mock_account()` is available only in `CONFIRMED` or later borrower states;
   - `propose_promise(amount, date)` creates an uncommitted candidate;
   - `commit_promise(candidate_id)` works only after explicit echo confirmation;
   - all disallowed calls fail closed and create a guard event.

5. **Pre-TTS disclosure guard**
   - before `CONFIRMED`, block currency symbols, amount patterns, loan/account terms, overdue
     language, and mock-account fields;
   - after demotion, immediately restore the same block;
   - blocked output is never sent to TTS;
   - use a safe fixed response when a draft is blocked;
   - log the blocked category, not the sensitive draft text.

6. **SQLite evidence store**
   - `calls`: case, start/end time, final disposition, end reason;
   - `events`: monotonic sequence, call ID, timestamp, state before/after, event type;
   - `tool_calls`: tool, allowed/blocked, reason, redacted result;
   - `promise_candidates`: parsed amount/date, confirmation state;
   - `promises`: final amount/date, source candidate, committed timestamp;
   - append corrective events instead of editing past events.

### 3.2 Dialogue policy

- The agent first identifies itself and states it will never ask for a PIN or OTP.
- It does not mention debt, a lender relationship, balance, EMI, overdue status, or money before
  verification.
- Verification uses only seeded demo data and a deterministic comparison.
- The LLM returns typed candidates, never direct database commands.
- Every amount/date must be repeated in a normalized form and confirmed with an explicit yes.
- A correction replaces the **candidate**, not committed history.
- If the caller says someone else has the phone, the state demotes immediately.
- If the system is uncertain, it asks a short clarification or ends safely.
- No claim of legal status, regulatory approval, or guaranteed privacy is generated.

### 3.3 Fail-closed behavior

| Failure | System behavior | Operator sees |
|---|---|---|
| Microphone denied | Call cannot start | Permission fix and retry |
| STT socket cannot connect | Call cannot start | Technical failure; no attempt counted |
| STT drops mid-call | Stop TTS and tools; enter `DEGRADED` | End safely or take over |
| LLM timeout or invalid schema | One bounded retry, then fixed safe line | `MODEL_FAILURE` event |
| TTS fails | Show text; do not pretend audio played | End or operator takeover |
| Ambiguous verification | Ask once more, then callback-only | Verification failed safely |
| Ambiguous amount/date | Ask for the specific field again | Candidate remains uncommitted |
| Guard blocks a draft | Play fixed privacy-safe line | Block reason and state |
| Operator takes over | Stop agent audio and lock agent tools first | Takeover timer and reason |

---

## 4. Human operator journey — Nandini

This is the complete MVP journey. It replaces the underspecified
**Start → Watch → Export** description.

### 4.1 Before the call: understand and authorize

1. Nandini opens one seeded case.
2. The case page shows only the information needed to decide whether a demo call may start:
   mock borrower name, scheduled window, last contact time, contact-cap status, mock paid status,
   and data-source freshness.
3. A deterministic preflight returns one of:
   - `ELIGIBLE` — Start Call enabled;
   - `BLOCKED_CONTACT_CAP`;
   - `BLOCKED_QUIET_HOURS`;
   - `BLOCKED_ALREADY_PAID`;
   - `BLOCKED_STALE_DATA`;
   - `BLOCKED_TECHNICAL`.
4. If blocked, the button stays disabled and shows the exact rule and source field. Nandini cannot
   override a policy block in the MVP.
5. If eligible, Nandini checks headphones and microphone input, then presses **Start Call** once.

**Operator decision:** start an eligible call or leave it untouched.  
**Not an operator task:** scripting dialogue, choosing a collection amount, or bypassing policy.

### 4.2 During the call: supervise by exception

The primary display answers four questions without requiring transcript archaeology:

1. **Who is the agent allowed to speak to?**  
   Large state label: `UNVERIFIED`, `VERIFYING`, `CONFIRMED`, or `THIRD_PARTY`.

2. **What is the agent doing now?**  
   Current step: proving identity, verifying, asking, echo-confirming, or closing.

3. **What did code permit or block?**  
   Latest tool/guard event with a plain-language reason.

4. **Does Nandini need to act?**  
   A single alert appears only for a technical failure, repeated misunderstanding, or explicit
   request for a human.

Nandini has two actions:

- **End Call:** stop audio, lock tools, write `ENDED_MANUAL`, and require a reason.
- **Break-glass Takeover:** first stop TTS and revoke agent tool access, then enable Nandini's mic.
  The takeover is logged with time and reason. The agent cannot resume in the MVP.

Nandini cannot edit the live identity state, unlock tools, rewrite the transcript, or change a
promise candidate. This makes the demo's autonomy and safety claims inspectable.

### 4.3 After the call: resolve the work

The call ends with exactly one disposition:

- `PROMISE_CONFIRMED`;
- `CALLBACK_THIRD_PARTY`;
- `VERIFICATION_FAILED`;
- `ENDED_TECHNICAL`;
- `ENDED_MANUAL`.

The outcome page shows:

- the disposition and why it was selected;
- confirmed amount/date only when `PROMISE_CONFIRMED`;
- final identity state;
- guard blocks and tool decisions;
- whether an operator intervened;
- a chronological, read-only event list;
- **Copy Evidence Summary** for the demo.

Nandini may add a separate operator note, but cannot alter generated evidence. Corrections are new
events with author and timestamp.

### 4.4 Refusal journey

To demonstrate that the operator is also constrained, Nandini opens a second seeded case whose
contact cap is exhausted. **Start Call** is disabled with:

> Call blocked: 2 contacts already attempted in the configured window.

No agent session or audio connection is created. This is clearer and safer than starting a call
and asking the agent to refuse its operator afterward.

### 4.5 Recovery journey

If a dependency fails:

1. the agent stops speaking;
2. all account and commitment tools lock;
3. the UI names the failed dependency without exposing secrets;
4. Nandini chooses **End Safely** or **Break-glass Takeover**;
5. the case receives `ENDED_TECHNICAL`, not a fabricated business outcome;
6. retry is enabled only after preflight runs again.

### 4.6 Human-journey acceptance criteria

- Start is impossible for every blocked preflight state.
- The identity state and current step are understandable without reading the transcript.
- Takeover silences agent TTS and revokes agent tools before the operator mic opens.
- A completed call always has exactly one disposition.
- A promise cannot appear unless the matching candidate received explicit echo confirmation.
- Operator notes cannot mutate system events.
- A failed call can be retried only through a fresh preflight.
- The demo can be completed with three normal operator actions:
  **open case → start call → inspect outcome**. This is a usability target, not an autonomy metric.

---

## 5. MVP acceptance criteria

The MVP is complete only when all of these pass:

1. No amount, debt term, account field, or overdue status reaches TTS before `CONFIRMED`.
2. A third-party statement or explicit handover demotes the session and relocks tools before the
   next generated response.
3. Failed verification never unlocks `read_mock_account`.
4. A promise write requires parsed amount, parsed date, normalized read-back, and explicit yes.
5. Saying "no, I said 1,050" changes only the candidate and triggers another read-back.
6. Every state transition and tool decision produces an ordered evidence event.
7. Contact-cap preflight prevents session creation.
8. Operator takeover stops agent output and tool access before operator audio begins.
9. STT, LLM, or TTS failure produces `ENDED_TECHNICAL`, never `PROMISE_CONFIRMED`.
10. The happy path and privacy-refusal path each pass three consecutive rehearsals on venue
    hardware with no code or database edits between runs.

### Minimum test set

Use text fixtures for deterministic logic and two short prerecorded audio fixtures for the real
voice path.

| Case | Expected result |
|---|---|
| Correct borrower, ₹1,500 Friday, explicit yes | One committed promise |
| Correct borrower corrects ₹1,500 to ₹1,050 | Only ₹1,050 committed after second confirmation |
| Spouse answers and pushes for amount | No disclosure; callback-only |
| Borrower hands phone to spouse after confirmation | Immediate demotion; no later disclosure |
| Verification fails twice | No account tool access |
| LLM drafts an amount while unverified | Guard blocks TTS |
| Contact cap exhausted | Session never starts |
| STT disconnects before confirmation | Technical disposition; no promise |

The artifact must show the current run timestamp and per-case result. Do not substitute a static
claim such as "11/12 passed" for a reproducible test command.

---

## 6. 120-second demo

### Live path: one coherent story

| Time | Operator/borrower action | Visible proof |
|---|---|---|
| 0:00–0:10 | Nandini opens an eligible mock case and starts | Preflight passed; one Start action |
| 0:10–0:25 | Borrower asks "scam hai kya?" | Agent identifies itself, refuses PIN/OTP, reveals no debt |
| 0:25–0:40 | Borrower completes demo verification | State changes to `CONFIRMED`; account tool unlocks |
| 0:40–1:05 | Borrower offers ₹1,500 Friday | Candidate shown; agent reads amount/date back |
| 1:05–1:15 | Borrower explicitly confirms | One promise ledger event; disposition becomes confirmed |
| 1:15–1:35 | Phone is handed to spouse, who asks the balance | State demotes; tool relocks; safe refusal |
| 1:35–1:50 | Nandini opens outcome | Timeline shows verify → candidate → confirm → demote |
| 1:50–2:00 | Nandini opens contact-capped case | Start disabled with exact rule |

If the live path is running long, end after the confirmed promise and show third-party refusal
with a prerecorded **input fixture passed through the current pipeline**, clearly labeled.

### What the presenter says

> We are proving one thing: the voice model can converse, but code—not the model—decides when
> private data and write tools unlock. The operator supervises exceptions and receives a usable
> outcome.

Do not narrate deferred features as if they exist.

---

## 7. Six-hour build plan

Protect the last 90 minutes for integration and rehearsal. A feature that first works at H5:45 is
not demo-ready.

### H0:00–H0:30 — contracts and fixtures

- Freeze the state enum, allowed transitions, typed LLM response, and tool permissions.
- Seed two mock cases: one eligible and one contact-capped.
- Write the eight minimum logic fixtures before UI work.
- Verify Saaras and Bulbul credentials, model names, audio format, and quota with one request each.

**Exit:** API smoke tests pass and the state/tool contract is written.

### H0:30–H1:30 — privacy-safe text vertical slice

- Implement state machine, tool gate, disclosure guard, and SQLite events.
- Run the full happy path with typed text, no audio and minimal UI.
- Implement echo confirmation and correction.

**Exit:** text fixtures 1–7 pass; only confirmed candidate can be committed.

### H1:30–H2:30 — real voice vertical slice

- Add browser microphone capture with the supported audio format.
- Connect Saaras streaming STT and Bulbul streaming TTS.
- Add timeout/disconnect handling.
- Use headphones; verify no self-barge-in on venue hardware.

**Exit:** one spoken happy path reaches a correct uncommitted candidate.

### H2:30–H3:15 — operator console

- Build preflight, Start/End/Takeover, identity/current-step display, latest guard/tool event,
  and outcome page.
- Implement contact-cap refusal before session creation.

**Exit:** Nandini can perform the complete normal and refusal journeys without developer tools.

### H3:15–H4:00 — handover and failure safety

- Add explicit/lexical handover demotion.
- Ensure demotion relocks tools synchronously.
- Implement `DEGRADED`, technical ending, and safe takeover ordering.

**Exit:** spouse fixture, disconnect fixture, and takeover ordering pass.

### H4:00–H4:30 — evidence and reset

- Add ordered event timeline and Copy Evidence Summary.
- Add deterministic demo reset that restores only seeded mock data.
- Add visible DEMO / MOCK labels.

**Exit:** two runs produce clean independent call IDs and evidence.

### H4:30–H6:00 — integration and rehearsal

- Run the complete automated set.
- Rehearse happy path three consecutive times on venue hardware.
- Rehearse spouse refusal three consecutive times.
- Rehearse one forced API failure and operator takeover.
- Freeze features after H5:15; spend remaining time only on reliability, copy, and timing.

**Exit:** acceptance criteria pass and the live arc stays below 110 seconds, leaving ten seconds
of contingency.

### Cut order

If behind, cut in this order:

1. Copy Evidence Summary formatting;
2. live transcript polish and animation;
3. hostile "scam hai kya?" branch;
4. live post-confirmation handover from the main arc—retain the tested fixture;
5. LLM-generated phrasing—replace with fixed, bilingual state-specific templates.

**Never cut:** preflight, deterministic identity gate, pre-TTS disclosure guard, echo-confirmed
promise write, technical-failure disposition, headphones, or rehearsal.

---

## 8. Later phases

Nothing below is part of the minimum MVP or demo promise.

### Phase 1 — useful collection outcomes

- Add deterministic branches for already paid, dispute, hardship, and callback.
- Add human-desk routing with consent-scoped structured notes.
- Add contact-policy configuration and real source freshness.
- Define an evaluation corpus and require 85%+ end-to-end success across repeated cases.
- Measure completion rate, operator intervention rate, guard-block rate, false refusal rate, and
  technical failure rate.

### Phase 2 — governed cross-call memory

- Define the minimum fields required for continuity.
- Add explicit access, correction, retention, and deletion rules.
- Resume from structured commitments and standing instructions, not raw audio by default.
- Add a borrower-visible correction/delete flow.
- Test that memory is never replayed or summarized before fresh verification.

### Phase 3 — standing instructions

- Start with a small enumerated policy schema:
  `DO_NOT_DISCLOSE_TO_OTHERS`, `CONTACT_WINDOW`, and `CHANNEL_PREFERENCE`.
- Use the LLM only to propose a policy candidate.
- Read the candidate back and require explicit confirmation.
- Compile confirmed policies into deterministic preflight and pre-TTS guards.
- Add conflict handling, expiry, provenance, and operator visibility.

### Phase 4 — hesitation research, not production scoring

- Capture a consented, representative, multilingual evaluation dataset.
- Use an endpoint that actually supplies timestamps, or compute documented local timing features.
- Test repeatability across language, device, noise, disability, age, and speaking style.
- Measure calibration against kept promises rather than annotator impressions of confidence.
- Never increase pressure or deny a borrower choice based on hesitation.
- Present the signal as uncertain and allow an immediate borrower correction.
- Ship only if it beats a no-prosody baseline without unacceptable subgroup harm.

### Phase 5 — voice artifacts and acoustic handover research

- Complete privacy, consent, retention, deletion, access-control, and threat-model reviews first.
- Prove that any audio replay serves a user need not met by structured memory.
- Evaluate speaker-change signals as conservative alerts only.
- Never promote identity from acoustics alone.
- Do not store voiceprints in the initial implementation.

### Phase 6 — production readiness

- Replace mock identity and lender data with approved integrations.
- Add authentication, tenancy, encryption, secrets management, rate limits, observability, and
  incident response.
- Conduct security, privacy, legal/compliance, model-risk, accessibility, and abuse reviews.
- Pilot in shadow mode before any autonomous borrower contact.
- Establish rollback, human escalation, audit export, and complaint handling.

---

## 9. Product metrics and evidence discipline

### MVP engineering metrics

- end-to-end completion rate across the fixed test set;
- privacy guard false-negative count: target zero in the test set;
- privacy guard false-positive count;
- median and worst-case response latency on venue hardware;
- operator intervention rate;
- technical ending rate;
- incorrect promise-write count: target zero.

### Later business outcome

**Kept-promise rate** remains the proposed north-star business metric, but the hackathon demo
cannot prove movement in it. A real pilot must compare Vachan with the existing workflow on a
defined eligible population and time window. Promise-to-pay creation rate is a diagnostic metric,
not success by itself.

### Claims policy

- Label fixtures, mocks, seeded data, and prerecorded inputs.
- Separate current behavior from roadmap behavior on every slide.
- Retain sources for market, pricing, and compliance claims.
- Show failed tests honestly with the exact current run.
- Never describe a rule as enforced unless a deterministic test demonstrates it.

---

## 10. Final MVP definition

Vachan is demo-ready when Nandini can start one eligible mock case, a real voice conversation can
verify the borrower and capture one echo-confirmed promise, a third party cannot obtain debt
information, a blocked case cannot start, failures end safely, and the evidence timeline explains
each authorization decision.

If that works three times consecutively, the team has a minimum MVP.

Hesitation pricing, voice replay, cross-call self-confession, acoustic speaker tracking, five
terminal workflows, and the larger gauntlet are valuable only after this foundation is reliable.
