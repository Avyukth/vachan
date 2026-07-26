# VACHAN MVP — Codex Critical Revision

**Build constraint:** six hours, no existing application code, one browser-based demo, and a
60–120 second judging slot.

**MVP thesis:** code—not the language model—decides when private collection data and write tools
unlock.

**MVP job:** an eligible mock case moves from operator start to either:

1. a privacy-safe, explicitly confirmed promise-to-pay; or
2. a content-free third-party callback outcome.

Everything else is subordinate to making those two outcomes reliable, inspectable, and operable
by Priya without a developer touching the application.

---

## 1. Critical review of the original MVP

### 1.1 “Minimum that wins” combines two different goals

The original document describes a plausible product MVP, but its title implies that the core
alone can win the competition. Those are not the same claim.

The core demonstrates:

- a real voice loop;
- privacy-safe identity gating;
- one completed collections outcome;
- operator evidence.

It does **not** by itself strongly demonstrate:

- governed memory across calls;
- repeated end-to-end JTBD success;
- measurable business impact;
- a broad refusal/recovery experience.

**Decision:** distinguish three layers:

1. **Product core:** one safe end-to-end call;
2. **minimum competition evidence:** repeatable tests plus one small structured cross-call memory;
3. **later features:** audio memory, hesitation scoring, admin analytics, and broader workflows.

The product core is frozen first. Competition evidence may be added only after the core passes its
exit gate. “Winning” is an aspiration, not an acceptance criterion.

### 1.2 The browser microphone and Saaras streaming formats do not automatically match

The plan says “one browser page” and “Saaras v3 streaming STT” without specifying the audio
transport. This is a load-bearing omission.

Sarvam's streaming STT accepts WAV or raw PCM formats. Browser `MediaRecorder` commonly emits
compressed WebM/Opus instead. A browser cannot simply forward that default blob to the streaming
endpoint.

**Decision:** choose and time-box one of these paths:

- **Primary:** Web Audio API/AudioWorklet captures mono PCM16, resamples to 16 kHz, and sends
  chunks through the backend WebSocket connection.
- **Fallback:** record short utterances in the browser and send them to Sarvam's REST STT endpoint,
  which supports WebM. This is turn-based and less fluid, but preserves the real STT → LLM → TTS
  product loop.

If streaming PCM has not completed one round-trip by the H0:45 checkpoint, switch to REST for the
MVP. Do not spend the day debugging audio plumbing.

Sources:

- [Sarvam: Streaming Speech-to-Text](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api)
- [Sarvam: Speech-to-Text API comparison](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/which-api-to-use)
- [Sarvam: Speech-to-Text overview and formats](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/overview)

### 1.3 Streaming hesitation meters are based on a false capability assumption

The proposed stretch S2 derives pause percentage and words per second from “Saaras timestamps.”
Sarvam's current comparison documents no timestamps on the WebSocket streaming path. VAD events
are not word timestamps and cannot support the stated calculation.

Even if another endpoint supplies timestamps, hesitation is not validated as a reliable proxy for
truthfulness or promise quality.

**Decision:** remove hesitation meters and promise repricing from the hackathon ladder. Treat them
as a later research track with consent, calibration data, subgroup analysis, and an immediate
borrower override.

### 1.4 Identity verification is named but not specified

`CLAIMED → CONFIRMED` is not implementable until the plan answers:

- What does the caller provide?
- What mock data is compared?
- How many attempts are allowed?
- Does the agent ever read verification answers aloud?
- What happens after failure?
- Does verification survive a phone handover?

Without those answers, `CONFIRMED` risks becoming an LLM label rather than an authorization fact.

**Decision:** the mock MVP asks the caller to provide two seeded values; application code compares
normalized values. The agent never reads expected values aloud. Two failed attempts produce a
content-free callback outcome. Handover or explicit third-party language clears confirmation and
requires fresh verification.

This is a **demo verification mechanism**, not production borrower authentication. The UI and
submission notes must say so.

### 1.5 A regex blocklist is insufficient as the primary privacy boundary

Amounts and debt language can appear as:

- digits, words, lakh notation, or dates;
- Hindi, English, transliteration, or code-mix;
- indirect disclosures such as “your remaining four instalments”;
- mock account fields that do not contain a loan keyword.

A regex is useful defense in depth but too brittle to authorize speech.

**Decision:**

- before confirmation, use only fixed privacy-safe response templates;
- keep account data out of the LLM context until `CONFIRMED`;
- expose no account-reading tool until `CONFIRMED`;
- retain a multilingual pre-TTS blocklist as a last defense;
- if the guard fires, discard the generated draft and play a fixed safe line.

Preventing sensitive context from reaching the model is stronger than trying to scrub every
possible leak afterward.

### 1.6 The state machine is too compressed

`UNKNOWN → THIRD_PARTY / CLAIMED → CONFIRMED` mixes identity, dialogue progress, and terminal
outcomes. It does not describe connection failure, retry, echo confirmation, operator takeover,
or whether a promise is merely proposed versus committed.

**Decision:** use explicit call, identity, and promise states with a small transition table.
Every transition is performed by code and written to the evidence ledger.

### 1.7 “One commitment row” cannot prove the critical invariant

A final row does not prove:

- what candidate amount/date was parsed;
- whether it was read back;
- whether the caller corrected it;
- whether explicit confirmation occurred;
- which state authorized the write.

**Decision:** separate `promise_candidate` from `promise_committed`. Store candidate creation,
correction, read-back, and confirmation as ordered events. Only the final commit creates the
promise row.

### 1.8 “Friday” is not a ledger value

Relative dates depend on timezone and call time. A demo performed near midnight or replayed later
can produce ambiguity.

**Decision:** normalize the candidate to an ISO date in `Asia/Kolkata`, speak the absolute date
back with the weekday, and store both the caller's phrase and normalized date:

> “₹1,500 — ek hazaar paanch sau rupaye — Friday, 31 July 2026. Sahi hai?”

The actual demonstration date must be generated from seeded demo time rather than copied from this
example.

### 1.9 The operator journey has no exception path

“Start → Watch → Evidence” does not cover:

- microphone permission failure;
- STT, model, or TTS timeout;
- repeated misunderstanding;
- borrower request for a person;
- operator takeover;
- manual ending;
- safe retry.

Three clicks are a usability aspiration, not evidence of autonomy.

**Decision:** preserve a three-action happy path while designing explicit failure and takeover
journeys. The operator observes and handles exceptions; developers are not part of the runtime
workflow.

### 1.10 The 90-second demo is actually two calls compressed into one

“Judge-as-spouse pushes three times, then judge-as-borrower verifies” leaves the transition
between speakers undefined. If the phone changes hands, the system must deliberately reset and
reverify. If it is a new call, the first call must close and a second must start.

Three pushbacks also spend precious demo time proving the same invariant repeatedly.

**Decision:** use one live call:

1. borrower verifies and confirms a promise;
2. borrower explicitly hands the phone to a spouse;
3. the session demotes and refuses the spouse's single request.

Use a separate deterministic fixture to show that three repeated pushes also remain leak-free.

### 1.11 The stretch ladder is not ordered by dependency or risk

- Voice-vachan creates consent, retention, replay, access, and deletion work.
- Hesitation meters depend on an unavailable streaming field.
- Seeded call #2 depends on governed memory and voice-vachan.
- A prerecorded gauntlet artifact can become stale or look staged.
- An admin KPI console over a handful of seeded calls creates decorative metrics, not evidence.

**Decision:** replace the wow-feature ladder with a competition-evidence ladder:

1. reproducible test runner;
2. structured cross-call memory after fresh verification;
3. contact-cap preflight refusal;
4. only then optional polish.

### 1.12 The clock has no dependency verification or failure budget

The original schedule assumes the first hour's voice loop works and gives only 30 minutes to final
submission. It has no explicit API credential/quota check, audio-format decision, schema contract,
failure recovery, or feature-freeze buffer.

**Decision:** verify dependencies first, build the policy core with text before voice, reserve the
last 90 minutes for integration/rehearsal, and freeze features no later than H4:45.

---

## 2. Scope contract

### 2.1 Product core — must ship

1. One browser operator page.
2. One real Sarvam STT → Sarvam LLM → Bulbul TTS loop.
3. Deterministic mock borrower verification.
4. Account/tool access physically unavailable until verification succeeds.
5. Fixed safe pre-verification dialogue plus defense-in-depth output guard.
6. One amount/date candidate with correction and explicit echo confirmation.
7. SQLite call, event, tool-decision, and committed-promise records.
8. Two business outcomes:
   - `PROMISE_CONFIRMED`;
   - `CALLBACK_THIRD_PARTY`.
9. Three safe non-business endings:
   - `VERIFICATION_FAILED`;
   - `ENDED_TECHNICAL`;
   - `ENDED_OPERATOR`.
10. Operator preflight, live supervision, safe takeover, and evidence outcome.

### 2.2 Minimum competition evidence — only after core freeze

1. A timestamped test runner with at least eight deterministic scenarios.
2. Three consecutive happy-path runs with no developer intervention.
3. Three consecutive third-party refusal runs with zero disclosures.
4. One structured cross-call continuity beat:
   - retrieve a prior confirmed promise only after fresh verification;
   - allow correction by appending a new event;
   - do not store or replay voice audio.
5. One blocked contact-cap case, enforced before session creation.

These items improve rubric evidence without adding an independent media-governance or biometric
system.

### 2.3 Later, not today

- audio recording or replay;
- hesitation/confidence scoring;
- pitch or speaker biometrics;
- five collection branches;
- generic natural-language policy rows;
- real telephony;
- real lender/payment data;
- admin analytics;
- hash chains;
- Slack/webhooks;
- production authentication or regulatory claims.

---

## 3. Personas and responsibility

### Priya — collections operator

- selects an eligible seeded case;
- verifies that the microphone and headphones work;
- starts the call;
- supervises state, tools, and exceptions;
- ends or takes over a failed call;
- inspects the outcome.

Priya cannot:

- set or override identity state;
- unlock account or commitment tools;
- edit system evidence;
- silently change a promise;
- bypass a contact-policy block.

### Nandini — collections lead

For the MVP, Nandini is a stakeholder, not a second application role. She may view the same
read-only evidence summary after the demo. Do not build a separate admin route, authentication
model, or fake KPI dashboard today.

### Rakesh Yadav — borrower

- wants proof that the call is legitimate;
- wants debt details kept from third parties;
- wants ASR mistakes corrected before anything is committed;
- wants a clear end to the call.

### Sunita — spouse/third party

- may answer or receive the phone mid-call;
- receives no debt, amount, due-date, lender-relationship, or promise information;
- may only receive a content-free request for Rakesh to reconnect.

---

## 4. Technical design

### 4.1 Audio path with a deadline fallback

#### Primary path: streaming

```text
Browser microphone
  -> AudioWorklet mono PCM
  -> resample to signed 16-bit 16 kHz
  -> backend WebSocket proxy
  -> Saaras v3 streaming STT
  -> finalized utterance
  -> dialogue controller
  -> approved response text
  -> Bulbul v3 streaming TTS
  -> browser headphone playback
```

The subscription key remains on the backend. Never expose it in browser code.

#### Fallback path: turn-based REST

```text
Browser MediaRecorder short utterance
  -> backend upload
  -> Saaras REST STT
  -> dialogue controller
  -> Bulbul TTS
  -> browser headphone playback
```

Fallback limitations must be stated honestly:

- slower turn-taking;
- no live interruption/barge-in claim;
- the borrower presses or taps to finish an utterance if automatic turn detection is unreliable.

**Decision deadline:** streaming audio must complete one browser round-trip by H0:45. Otherwise
use REST and stop working on streaming.

### 4.2 State model

Keep orthogonal concerns separate.

#### Call state

```text
IDLE
  -> PREFLIGHT
  -> READY
  -> CONNECTING
  -> ACTIVE
  -> COMPLETED

PREFLIGHT -> BLOCKED
CONNECTING / ACTIVE -> DEGRADED
ACTIVE / DEGRADED -> OPERATOR_TAKEOVER
ACTIVE / DEGRADED / OPERATOR_TAKEOVER -> ENDED
```

#### Identity state

```text
UNVERIFIED
  -> VERIFYING
  -> CONFIRMED

UNVERIFIED / VERIFYING
  -> THIRD_PARTY

CONFIRMED
  -> UNVERIFIED     # explicit handover or identity uncertainty
  -> THIRD_PARTY    # new speaker identifies as another person
```

Identity always begins `UNVERIFIED` for every call. It is never restored from the previous call.

#### Promise state

```text
NONE
  -> CANDIDATE
  -> READ_BACK
  -> CONFIRMED
  -> COMMITTED

CANDIDATE / READ_BACK
  -> CORRECTED
  -> READ_BACK

CANDIDATE / READ_BACK / CORRECTED
  -> ABANDONED
```

Only application code changes state. LLM output is a proposal validated against the current state
and a typed schema.

### 4.3 Demo verification contract

Use two values from a seeded mock profile, for example:

- caller-provided day and month of birth;
- caller-provided last four characters of a mock customer reference.

Rules:

1. The agent asks the caller to provide values; it never speaks expected values.
2. Normalize locally and compare in application code.
3. Do not send expected values to the LLM.
4. Allow at most two complete attempts.
5. Any mismatch keeps account tools locked.
6. Two failures produce `VERIFICATION_FAILED` and a content-free close.
7. Explicit phone handover invalidates confirmation.
8. Every attempt logs pass/fail and field names, not secret values.

### 4.4 Dialogue controller

Before `CONFIRMED`, choose responses only from reviewed fixed templates:

- introduction and anti-scam line;
- verification request;
- clarification request;
- verification failure close;
- third-party callback request;
- safe technical close.

After `CONFIRMED`, the Sarvam LLM may propose:

```json
{
  "intent": "offer_promise | correct_promise | confirm | deny | handover | request_human | other",
  "amount_minor": 150000,
  "date_phrase": "Friday",
  "response_draft": "..."
}
```

Application code:

1. validates the schema;
2. rejects fields not allowed in the current state;
3. normalizes amount/date;
4. invokes allowed tools;
5. renders or validates the final response;
6. passes it through the pre-TTS guard.

Do not let model prose directly trigger a database write.

### 4.5 Tool permissions

| Tool | Allowed state | Additional condition |
|---|---|---|
| `submit_verification` | `VERIFYING` | Two-attempt limit |
| `read_mock_account` | `CONFIRMED` | Active call |
| `create_promise_candidate` | `CONFIRMED` | Valid positive amount and future/allowed date |
| `correct_promise_candidate` | `CONFIRMED` | Existing uncommitted candidate |
| `commit_promise` | `CONFIRMED` | Candidate read back and explicit yes recorded |
| `schedule_content_free_callback` | `THIRD_PARTY` | No account fields in payload |
| `end_call` | Any active state | Valid end reason |

Disallowed calls return a typed failure, produce a guard event, and do not partially mutate data.

### 4.6 Disclosure protection

Use four layers:

1. **Context isolation:** no account data enters prompts before confirmation.
2. **Tool isolation:** account tools are unavailable before confirmation.
3. **Template isolation:** all pre-confirmation responses are fixed safe copy.
4. **Output guard:** scan every final response before TTS.

The guard checks, at minimum:

- currency symbols and digit amounts;
- Hindi/English number words used with money terms;
- EMI, loan, debt, due, overdue, balance, recovery, instalment, lender, and common transliterations;
- mock account fields and lender name;
- normalized promise date when paired with collection language.

When blocked:

- discard the entire draft;
- do not log the sensitive draft body;
- play a fixed safe line;
- write `OUTPUT_BLOCKED` with category and current state.

### 4.7 Echo-confirmed promise

1. Parse candidate amount into integer minor units.
2. Normalize the date into an ISO date using `Asia/Kolkata`.
3. Reject impossible, past, or unsupported dates.
4. Render amount in digits and natural language.
5. Render weekday and absolute date.
6. Ask one unambiguous confirmation question.
7. Accept only an explicit affirmative classified in the `READ_BACK` state.
8. A correction updates the candidate and forces another read-back.
9. Commit exactly once with an idempotency key.
10. Ending the call before confirmation marks the candidate abandoned.

### 4.8 SQLite evidence

Minimum tables:

- `cases`
  - mock case ID;
  - borrower display name;
  - eligibility/contact-cap fields;
  - mock-data label.
- `calls`
  - call ID;
  - case ID;
  - start/end time;
  - transport mode;
  - final disposition;
  - operator intervention flag.
- `events`
  - call ID;
  - monotonic sequence;
  - timestamp;
  - event type;
  - state before/after;
  - redacted reason.
- `tool_decisions`
  - tool;
  - allowed/blocked;
  - current identity/promise state;
  - reason.
- `promise_candidates`
  - caller phrase;
  - normalized amount/date;
  - revision number;
  - read-back timestamp;
  - confirmation timestamp.
- `promises`
  - candidate ID;
  - committed amount/date;
  - idempotency key;
  - committed timestamp.
- `operator_notes`
  - append-only note;
  - author;
  - timestamp.

System events are append-only. The reset action deletes and reseeds **demo data only** and is
available outside active calls.

---

## 5. Human operator journey — Priya

The happy path remains visually simple, but the journey includes policy and technical exceptions.

### 5.1 Start: decide whether the call can begin

1. Priya opens the seeded Rakesh case.
2. The page clearly displays `DEMO / MOCK DATA`.
3. Preflight checks:
   - browser microphone permission;
   - audible output/headphones confirmation;
   - backend health;
   - Sarvam STT and TTS configuration;
   - case eligibility and contact cap;
   - no other active session for the case.
4. The result is:
   - `READY`;
   - `BLOCKED_POLICY`;
   - `BLOCKED_TECHNICAL`.
5. Start Call is enabled only for `READY`.
6. If blocked, Priya sees the exact failed check and a safe remediation. She cannot override a
   policy block.

**Normal action 1:** open the case.  
**Normal action 2:** press Start Call.

### 5.2 Watch: supervise by exception

The screen has three columns, but each has a precise job.

#### CALL

- connection/audio status;
- current safe agent utterance;
- End Call;
- Break-glass Takeover.

#### WATCH

- identity state;
- dialogue step;
- promise state;
- latest tool decision;
- one alert only when Priya must act.

#### EVIDENCE

- ordered state transitions;
- blocked outputs/tools with reasons;
- candidate/read-back/confirmation events;
- final disposition when available.

Priya does not need to read the whole transcript to know whether the call is safe.

### 5.3 Break-glass takeover

Takeover order is safety-critical:

1. revoke agent tool access;
2. cancel pending model/TTS work;
3. stop TTS playback;
4. write `OPERATOR_TAKEOVER`;
5. only then open Priya's microphone.

The agent cannot resume after takeover in the MVP. Priya ends the call with a required reason.
This avoids two speakers or stale model output acting concurrently.

### 5.4 Technical failure

If STT, LLM, TTS, or the backend fails mid-call:

1. enter `DEGRADED`;
2. lock account and promise tools;
3. stop generated speech;
4. show the failed component and retryability;
5. let Priya choose End Safely or Break-glass Takeover;
6. write `ENDED_TECHNICAL` unless Priya took over;
7. require a fresh preflight before retry.

The system never converts a technical ending into a promise or callback business outcome.

### 5.5 Evidence: understand the result

A call ends with exactly one disposition:

- `PROMISE_CONFIRMED`;
- `CALLBACK_THIRD_PARTY`;
- `VERIFICATION_FAILED`;
- `ENDED_TECHNICAL`;
- `ENDED_OPERATOR`.

The outcome panel shows:

- disposition and reason;
- amount/date only for `PROMISE_CONFIRMED`;
- final identity state;
- whether the operator intervened;
- guard and tool decisions;
- read-only chronological evidence;
- optional append-only operator note.

Priya cannot edit evidence or silently correct the promise. A correction must be a new, attributed
event.

**Normal action 3:** inspect the outcome.

### 5.6 Contact-cap refusal

After the main call, Priya opens a second seeded case whose contact cap is exhausted.

- Preflight returns `BLOCKED_POLICY`.
- Start Call remains disabled.
- No STT/TTS connection or call row is created.
- The UI shows the exact rule and relevant mock count.

This is stronger than starting a prohibited call and relying on the agent to refuse afterward.

### 5.7 Operator-journey acceptance criteria

- A policy-blocked case cannot create a voice session.
- Priya can identify the current identity and promise state without reading the transcript.
- Only actionable exceptions interrupt the Watch column.
- Takeover locks agent tools and stops agent audio before Priya's microphone opens.
- Every call has exactly one final disposition.
- Operator notes cannot mutate system evidence.
- Technical retry always reruns preflight.
- The happy path requires only open case, start call, and inspect outcome.

---

## 6. Product-core acceptance criteria

Core is frozen only when all conditions pass:

1. A browser utterance completes a real Sarvam STT → LLM → Bulbul TTS round-trip.
2. The selected transport is explicit: streaming PCM or turn-based REST.
3. No account data is present in model context before `CONFIRMED`.
4. No amount, debt term, account field, or lender relationship reaches TTS before `CONFIRMED`.
5. Two failed verification attempts never unlock account tools.
6. Explicit handover invalidates confirmation before the next response.
7. A third party receives only a content-free callback response.
8. `commit_promise` is impossible before normalized read-back and explicit confirmation.
9. Correcting amount or date forces another read-back.
10. A repeated confirmation cannot create duplicate promise rows.
11. Every state transition and tool decision is visible in ordered evidence.
12. STT, LLM, TTS, or backend failure ends technical and writes no promise.
13. Operator takeover stops agent work before operator audio begins.
14. The happy path passes three times consecutively on venue hardware.
15. The third-party path passes three times consecutively with zero disclosure.

---

## 7. Minimum tests

Implement deterministic logic tests before depending on live model phrasing.

| Case | Expected result |
|---|---|
| Correct two-field verification | `CONFIRMED`; account tool unlocked |
| One wrong verification, then correct | Remains locked until second attempt succeeds |
| Two wrong verification attempts | `VERIFICATION_FAILED`; no account read |
| Spouse answers and asks amount three times | Three safe responses; zero disclosure |
| Borrower confirms ₹1,500 on generated absolute date | One committed promise |
| Borrower corrects ₹1,500 to ₹1,050 | Only revised candidate committed after second read-back |
| Borrower says no during read-back | No promise row |
| Borrower hands phone to spouse after confirmation | Immediate demotion and tool relock |
| LLM drafts balance while unverified | Entire draft blocked; fixed safe line |
| Duplicate affirmative/event delivery | One promise row due to idempotency |
| STT disconnects before confirmation | `ENDED_TECHNICAL`; no promise |
| Operator takeover during model response | Pending response canceled; no agent TTS afterward |
| Contact cap exhausted | Start disabled; no call/session row |

The evidence artifact must be regenerated immediately before the demo and show:

- run timestamp;
- commit/version identifier if available;
- transport mode;
- per-case pass/fail;
- honest failure details.

A manually typed “12/13 passed” panel is not test evidence.

---

## 8. Demo arc

### 8.1 Main 100-second live path

| Time | Beat | Evidence |
|---|---|---|
| 0:00–0:10 | Priya opens eligible Rakesh case and starts | Preflight `READY`; single operator action |
| 0:10–0:25 | Rakesh asks whether it is a scam | Fixed anti-scam introduction; no debt disclosure |
| 0:25–0:40 | Rakesh provides mock verification values | Code changes `VERIFYING → CONFIRMED`; account tool unlocks |
| 0:40–1:05 | Rakesh offers ₹1,500 by Friday | Normalized candidate; absolute-date read-back |
| 1:05–1:15 | Rakesh explicitly confirms | One committed promise and evidence event |
| 1:15–1:30 | Rakesh hands phone to Sunita; she asks the balance | Identity demotes; tools relock; content-free refusal |
| 1:30–1:40 | Priya opens evidence | Timeline explains every authorization decision |

### 8.2 Final 20-second operator refusal

Priya opens the contact-capped seeded case. Start is disabled before any call begins. The presenter
then shows the freshly generated test summary.

### 8.3 Presenter framing

> The voice model handles language. Deterministic code controls identity, private context, and
> writes. Priya supervises exceptions; she cannot bypass the same rules that constrain the agent.

Do not mention a stretch feature as current behavior unless it passed the current build's tests.

---

## 9. Six-hour execution plan

### H0:00–H0:20 — freeze contracts

- Write state enums and transition table.
- Write typed LLM action schema.
- Write tool permission matrix.
- Seed eligible and contact-capped mock cases.
- Define the five final dispositions.

**Blocks:** every implementation task.  
**Exit:** a developer can implement state and tools without deciding product behavior.

### H0:20–H0:45 — dependency and audio spike

- Verify credentials, quota, and exact Sarvam model identifiers.
- Verify one Saaras request and one Bulbul request.
- Attempt browser PCM round-trip.
- At H0:45 choose streaming PCM or REST fallback permanently for the build.

**Blocks:** live voice integration.  
**Exit:** one real utterance becomes text and one fixed line becomes audible speech.

### H0:45–H1:45 — text-first safety core

- Implement state machines and deterministic verification.
- Implement context/tool isolation.
- Implement candidate/read-back/commit logic and idempotency.
- Implement SQLite evidence.
- Run tests without voice.

**Blocks:** voice dialogue and UI.  
**Exit:** tests for verification, privacy, correction, and duplicate commit pass.

### H1:45–H2:45 — voice vertical slice

- Connect the chosen STT transport.
- Connect typed Sarvam LLM responses after confirmation.
- Connect Bulbul playback through headphones.
- Add timeouts and cancellation.

**Blocks:** live rehearsal.  
**Exit:** one real spoken call reaches a correct uncommitted candidate.

### H2:45–H3:30 — operator page

- Build Start / Watch / Evidence.
- Add preflight, state display, tool/guard events, final disposition.
- Add End and correctly ordered Takeover.
- Add DEMO / MOCK labels.

**Blocks:** operator acceptance and demo.  
**Exit:** Priya can complete a call without browser developer tools.

### H3:30–H4:10 — edge paths

- Implement third-party answer and explicit handover.
- Implement two-attempt verification failure.
- Implement technical ending and retry preflight.
- Implement contact-cap refusal.

**Blocks:** complete minimum tests.  
**Exit:** all product-core cases pass at least once.

### H4:10–H4:30 — evidence runner and reset

- Add repeatable test command/artifact.
- Add deterministic demo reset scoped to seeded mock data.
- Ensure each run uses a fresh call ID.

**Blocks:** trustworthy demo evidence.  
**Exit:** test result is generated from the current build.

### H4:30–H6:00 — freeze and rehearse

- No new product mechanics after H4:30.
- Fix only correctness, reliability, copy, and timing.
- Run happy path three consecutive times.
- Run third-party path three consecutive times.
- Force one technical failure and execute takeover.
- Test venue headphones, microphone, network, reset, and submission URL.
- Run final test artifact immediately before presentation.

**Exit:** live path stays under 105 seconds and every product-core criterion passes.

### Cut order

If behind:

1. animations and visual polish;
2. dynamic anti-scam dialogue—retain one fixed safe line;
3. live transcript history—retain current state and evidence;
4. contact-cap demo—retain the deterministic test;
5. LLM-generated collection phrasing—use fixed post-confirmation templates.

**Never cut:** working audio fallback, identity/tool gate, context isolation, output guard,
echo-confirmed promise, technical ending, operator takeover safety, mock labels, or rehearsal.

---

## 10. Post-core competition evidence

Only begin this section if all product-core acceptance criteria are green by H4:00. Otherwise use
the remaining time for reliability.

### CE1 — structured cross-call memory

This is the smallest governed continuity feature:

1. Seed or create one prior confirmed structured promise.
2. Start a new call with identity reset to `UNVERIFIED`.
3. Do not place prior promise fields in model context.
4. Freshly verify the borrower.
5. Retrieve and summarize the prior promise only after `CONFIRMED`.
6. Let the borrower correct it by appending a correction event.
7. Store no audio.

**Time box:** 25 minutes.  
**Cut immediately** if it destabilizes the core call.

### CE2 — repeated-case evidence

Run the real pipeline against short prerecorded inputs for:

- correct borrower and promise;
- spouse pressure;
- promise correction.

The runner may skip TTS playback but must exercise real STT, action parsing, state transitions,
guards, and tools. Label prerecorded inputs clearly.

### CE3 — impact slide

State kept-promise rate as the proposed business metric, not a measured hackathon result. Separate:

- baseline to be measured in a pilot;
- payer hypothesis;
- expected mechanism;
- experiment needed to prove movement.

Do not invent KPI values from seeded demo calls.

---

## 11. Later phases

### Phase 1 — additional terminal outcomes

- already paid;
- dispute;
- hardship;
- human callback;
- contact-policy configuration.

Each branch needs deterministic tool rules, a final disposition, operator recovery, and tests.

### Phase 2 — governed structured memory

- standing instructions with an enumerated schema;
- provenance and explicit confirmation;
- expiry, correction, and deletion;
- fresh verification before retrieval;
- consent-scoped human handoff summaries.

### Phase 3 — audio-memory research

Before recording or replaying a borrower:

- define user benefit;
- capture explicit purpose-bound consent;
- define access and replay authorization;
- set retention and deletion rules;
- enumerate blobs, backups, transcripts, hashes, and derived data;
- test that deletion covers every promised copy;
- complete privacy and threat-model review.

Do not call a clip hash “governance.”

### Phase 4 — hesitation/prosody research

- select an endpoint or local pipeline that actually yields the needed timing data;
- collect consented multilingual evaluation data;
- test device/noise/language/subgroup sensitivity;
- compare against a no-prosody baseline;
- calibrate against kept promises, not perceived honesty;
- never increase pressure or deny an option based on hesitation;
- provide an immediate borrower correction/override.

### Phase 5 — production readiness

- approved identity/authentication flow;
- real lender integration and freshness guarantees;
- encryption, tenancy, secrets, and access control;
- production telephony and consent;
- monitoring, incident response, and rollback;
- security, privacy, accessibility, model-risk, and legal/compliance review;
- complaint and human-escalation workflow;
- shadow-mode pilot before autonomous contact.

---

## 12. Final MVP definition

Vachan's product core is complete when Priya can open one eligible mock case, start a real Sarvam
voice interaction, deterministically verify Rakesh, capture one corrected-or-confirmed
amount/date without premature disclosure, safely refuse Sunita after a handover, and inspect a
read-only explanation of every state and tool decision.

It must do this repeatedly, fail closed when a dependency breaks, and require no developer action
between runs.

Only after that foundation is green should the team add structured cross-call continuity or
competition polish. Voice replay, hesitation pricing, biometrics, and dashboards are later
projects—not MVP stretches.
