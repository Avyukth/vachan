#!/usr/bin/env python3
"""Polish pass: 3 new beads, new deps, enrichment comments with test vectors. Run from repo root."""
import re
import subprocess
import sys

IDS = {
    "ep0": "sarvam-ibt", "t11": "sarvam-agu", "t12": "sarvam-qut", "t21": "sarvam-vmo",
    "t22": "sarvam-5n6", "t23": "sarvam-y8r", "t25": "sarvam-fm0", "t26": "sarvam-bb8",
    "t27": "sarvam-kmf", "t31": "sarvam-2w1", "t33": "sarvam-y4d", "t41": "sarvam-uz3",
    "t42": "sarvam-t5o", "t44": "sarvam-wdu", "t51": "sarvam-6dn", "t52": "sarvam-15h",
    "t61": "sarvam-j8o",
}

NEW = [
    ("t06", "Define frontend-backend protocol contract (REST + WS event schema)", "task", 0, """
WHY (found in bead review): t31 (STT transport), t41 (preflight), and t42 (operator UI) all
silently assume an API surface nobody defined. With parallel agents on backend/ and frontend/,
an undefined protocol is a guaranteed mid-build collision. This is a CONTRACT bead — decisions
only, ~10 minutes, part of the H0:00-0:20 freeze window.
WHAT — REST (all under /api, proxied by vite to :8000):
GET /api/cases -> seeded case list; POST /api/preflight {case_id} -> {result: READY|
BLOCKED_POLICY|BLOCKED_TECHNICAL, checks: [{name, pass, detail}]}; POST /api/call/start
{case_id} -> {call_id}; POST /api/call/end {call_id, reason}; POST /api/takeover {call_id};
POST /api/reset (403 during active call); GET /api/evidence/{call_id} -> ordered events.
REST-fallback transport only: POST /api/utterance {call_id, audio blob}.
WS /ws/call/{call_id}: client->server binary frames = PCM16 chunks (streaming transport only);
server->client JSON events {type: state_change|utterance|tool_decision|guard_block|disposition|
error, seq, ts, payload}. RULE: every server event mirrors a ledger row — the ledger is the
single source of truth; the UI never invents state.
ACCEPTANCE: schema written once as pydantic models + mirrored TS types; both scaffolds compile
against it; version-tagged v0 (no versioning machinery — just the tag).
"""),
    ("t07", "Scaffold backend: uv init, FastAPI skeleton, ruff+pytest wiring", "task", 0, """
WHY (found in bead review): the graph had no bead that CREATES backend/. AGENTS.md Layer 4
defines the conventions; this bead executes them. Runs in the H0:00-0:20 window in parallel
with contracts (different person/agent).
WHAT: uv init backend (Python 3.12+); uv add fastapi 'uvicorn[standard]'; uv add --dev ruff
pytest; module stubs per AGENTS.md: app/{main,states,verification,tools,guard,promise,
controller,sarvam_client,db,runner}.py; GET /healthz -> 200; Sarvam key loaded at startup from
macOS Keychain (security find-generic-password -s sarvam-api -w) with a FAIL-FAST clear error
if missing — never a silent None; vachan.db gitignored.
ACCEPTANCE: uv run uvicorn app.main:app --port 8000 serves /healthz 200; uv run pytest passes
(zero tests is fine); uv run ruff check . clean; key retrieval verified once so the macOS
permission dialog is answered NOW, not on stage.
"""),
    ("t08", "Scaffold frontend: SvelteKit via bun on :3000 with API/WS proxy", "task", 0, """
WHY (found in bead review): no bead created frontend/, yet the PCM spike (t12) needs a page to
run in, and the tunnel + mic permission are already bound to origin localhost:3000.
WHAT: bunx sv create frontend (minimal template, TypeScript); vite.config.ts: server.port=3000,
server.proxy {'/api': 'http://localhost:8000', '/ws': {target: 'ws://localhost:8000', ws: true}};
base +page.svelte with permanent 'DEMO / MOCK DATA' badge; Kinetic Operator CSS custom
properties (bg #101214, panel #191D21, accent #D97B29 — promise moments ONLY, green #4C9A6A,
rust #B4553F, monospace class for all numbers/state labels per DESIGN.md); a 'Request mic'
button stub that calls getUserMedia (permission prompt answered during setup, not on stage).
ACCEPTANCE: bun run dev serves :3000; /api/healthz returns 200 THROUGH the proxy; page loads via
https://sarvam.pathshala.dev (tunnel already points at 3000 — zero tunnel changes needed).
"""),
]

NEW_DEPS = [
    ("ep0", "t06"), ("ep0", "t07"), ("ep0", "t08"),
    ("t11", "t07"),
    ("t12", "t08"),
    ("t21", "t07"),
    ("t31", "t06"),
    ("t33", "t08"),
    ("t41", "t06"),
    ("t42", "t06"), ("t42", "t08"),
    ("t44", "t08"),
]

COMMENTS = {
    "t22": """POLISH (test enumeration + table AMENDMENT). Amendment adopted into VACHAN_MVP_V2.md:
new legal edge THIRD_PARTY -> VERIFYING (borrower reclaims the phone; fresh two-value challenge;
consistent with the handover bead). Without it the identity machine dead-ends the moment a spouse
answers first — the borrower could never take the call.
UNIT TESTS to write: (a) every legal edge accepted — call: IDLE>PREFLIGHT, PREFLIGHT>READY,
PREFLIGHT>BLOCKED, READY>CONNECTING, CONNECTING>ACTIVE, CONNECTING>DEGRADED, ACTIVE>COMPLETED,
ACTIVE>DEGRADED, ACTIVE>OPERATOR_TAKEOVER, DEGRADED>OPERATOR_TAKEOVER, ACTIVE>ENDED,
DEGRADED>ENDED, OPERATOR_TAKEOVER>ENDED; identity: UNVERIFIED>VERIFYING, VERIFYING>CONFIRMED,
UNVERIFIED>THIRD_PARTY, VERIFYING>THIRD_PARTY, CONFIRMED>UNVERIFIED, CONFIRMED>THIRD_PARTY,
THIRD_PARTY>VERIFYING; promise: NONE>CANDIDATE, CANDIDATE>READ_BACK, READ_BACK>CONFIRMED,
CONFIRMED>COMMITTED, CANDIDATE>CORRECTED, READ_BACK>CORRECTED, CORRECTED>READ_BACK,
CANDIDATE>ABANDONED, READ_BACK>ABANDONED, CORRECTED>ABANDONED.
(b) illegal samples rejected WITH event row: IDLE>ACTIVE, UNVERIFIED>CONFIRMED (must pass
VERIFYING), NONE>COMMITTED, COMMITTED>anything, READY>COMPLETED.
(c) identity is UNVERIFIED at every call start regardless of prior call state.
(d) every accepted transition writes exactly one events row with state_before/state_after.""",
    "t23": """POLISH (attempt semantics DECIDED + test vectors). Ambiguity found in review: what counts as
one of the two allowed attempts? DECISION: an attempt increments only when BOTH values have been
provided and compared. Clarification exchanges and partial answers do not increment. A mismatch
on either field fails the WHOLE attempt and the agent must NOT reveal which field was wrong
(naming the failing field is an information leak to an impostor).
TEST VECTORS: DOB normalization 'pandrah march' == '15/03' == '15 March' == '१५ मार्च';
ref last-4: '4-7-2-9' == '4729' == 'char saat do nau'; right DOB + wrong ref -> attempt 1
failed, response does not contain the word 'reference' or 'birth'; wrong+wrong then right+right
-> CONFIRMED on attempt 2; two failed attempts -> VERIFICATION_FAILED + content-free close.
PROMPT-CAPTURE TEST: string-scan every LLM payload constructed during verification for the
seeded expected values — zero occurrences.""",
    "t25": """POLISH (entity-name policy DECIDED + selection tests). Decision from review: the blind
greeting does NOT name the lender pre-CONFIRMED. The agent self-identifies as 'Vachan assistant'
+ the anti-scam pledge; the lender name enters speech only after CONFIRMED (it is part of
account context, which is isolated anyway). One consistent intro everywhere.
TEMPLATE IDS: INTRO_ANTISCAM, ASK_FOR_BORROWER, VERIFY_REQUEST, CLARIFY, VERIFY_FAILED_CLOSE,
THIRD_PARTY_CALLBACK (3 phrasing variants — three identical holds sound scripted),
TECH_DIFFICULTY_CLOSE.
SELECTION TESTS (intent -> template): 'scam hai kya?' -> INTRO_ANTISCAM; 'kaun bol rahe ho?' ->
INTRO_ANTISCAM; 'haan boliye' -> ASK_FOR_BORROWER (ambiguous, NOT confirmation); 'main unki wife
hoon' -> THIRD_PARTY_CALLBACK family; garbled/low-confidence -> CLARIFY.
INVARIANT TEST: every template string passes the output guard (templates are constructed
amount-free, but the guard still runs on them — defense against future template edits).""",
    "t26": """POLISH (normalization test vectors). Amounts (to integer paise): 'pandrah sau' -> 150000;
'dedh hazaar' -> 150000; 'ek hazaar paanchas' -> 105000 (the correction case!); 'paanch sau' ->
50000; '1500' -> 150000; '1.5k' -> clarify (do not guess). Dates (ISO, Asia/Kolkata, from the
SEEDED demo clock, never wall time): 'Friday'/'shukravaar' -> next Friday; 'kal' -> +1 day;
'31 July' -> that date; 'agle hafte' -> CLARIFY (ambiguous — never guess a specific day);
'30 February' -> reject + clarify; any past date -> reject + clarify.
READ-BACK FORMAT ASSERTION: the rendered string contains ALL of: digit amount, Hindi words,
weekday, absolute date — e.g. 'Pandrah sau rupaye — 1-5-0-0 — shukravaar, 31 July. Sahi hai?'
IDEMPOTENCY TEST: deliver the same explicit affirmative event twice -> exactly one promises row
(unique idempotency key), second delivery logged as duplicate-suppressed.""",
    "t27": """POLISH (adversarial vector list). BLOCKED pre-CONFIRMED: 'aapka balance pandrah sau hai';
'आपकी EMI बाकी है'; '1500 rupaye due hain'; 'aapki chaar kisht baaki hain' (indirect count);
any utterance containing the seeded lender name; 'shukravaar tak jama kar dijiye' (date +
collection verb). BLOCKED in ANY state (fabricated-credential class): 'hum RBI-registered hain,
license 4471'; 'main government se bol raha hoon'. ALLOWED pre-CONFIRMED: every member of the
template bank (test iterates the bank through the guard).
ON-FIRE BEHAVIOR TESTS: (a) response delivered to TTS equals the fixed safe line EXACTLY (whole
draft discarded — never partial redaction, which leaks structure); (b) OUTPUT_BLOCKED event row
carries category + identity/promise state; (c) the draft body appears NOWHERE — not in DB, not
in logs (scan test).
NOTE from review: the guard is the 4th layer; the indirect-disclosure class ('remaining four
instalments') is primarily defended by context isolation (layer 1) — the guard only catches the
enumerable patterns. Do not chase regex completeness; chase context emptiness.""",
    "t31": """POLISH (timeout/cancellation specifics). STT request timeout 8s -> on timeout speak
CLARIFY-line ('line kharab hai, dobara boliye') ONCE, second consecutive timeout -> DEGRADED.
No auto-reconnect mid-utterance (a silent reconnect can splice two utterances). STALE-CALLBACK
TEST: schedule an STT result to arrive after call end/takeover -> result dropped, no event row,
no TTS. Transport comes from the H0:45 decision bead — implement exactly one path.""",
    "t41": """POLISH (test cases). (a) mic permission denied (simulate via browser settings) ->
BLOCKED_TECHNICAL with check name 'microphone'; (b) capped case -> BLOCKED_POLICY + assert NO
calls row was inserted (DB-level check, not UI); (c) double-start race: POST /api/call/start
while a call is ACTIVE for the same case -> 409, no second session; (d) backend down ->
BLOCKED_TECHNICAL 'backend'; (e) all green -> READY and Start enabled. Preflight results render
per-check (name, pass, detail) so Priya sees WHICH check failed, with safe remediation text.""",
    "t42": """POLISH (protocol + render tests). Consumes the WS event schema from the protocol contract
bead (all events mirror ledger rows — the UI must never hold state the DB does not).
RENDER TESTS: (a) replay a recorded WS event sequence -> ribbon shows UNVERIFIED>VERIFYING>
CONFIRMED in order; (b) guard_block event -> visible blocked-utterance row with reason;
(c) tool_decision denied -> visible within 1s; (d) disposition event -> outcome panel renders
exactly once and the page stops accepting call events; (e) WS drop mid-call -> UI shows
DEGRADED banner (does not silently freeze).""",
    "t51": """POLISH (ambiguity vector table — the Voice Experience core). 'haan boliye' -> stays
UNVERIFIED, agent repeats ASK_FOR_BORROWER (NOT third-party, NOT confirmation); 'main unki wife
hoon' -> THIRD_PARTY; 'wo ghar pe nahi hai' -> THIRD_PARTY; 'bhai bol raha hoon' -> ambiguous
kinship (could be the borrower called bhai) -> CLARIFY once, then classify; 'Rakesh bol raha
hoon' -> VERIFYING (claim, start challenge); silence/garble -> CLARIFY. Three THIRD_PARTY pushes
use the 3 phrasing variants (assert non-identical responses).
CALLBACK PAYLOAD TEST: schedule_content_free_callback payload string-scanned against every
seeded account field + lender name + amounts -> zero hits.""",
    "t61": """POLISH (artifact format spec). Example output (monospace, one block):
=== VACHAN EVIDENCE RUN ===
ts: 2026-07-26T15:42:07+05:30  transport: REST  build: <git-sha-or-'dirty'>
01 verify-correct           PASS
02 verify-one-wrong         PASS
...
09 handover-after-confirm   FAIL  seq: [evt 14 CONFIRMED>UNVERIFIED missing]
score: 12/13
REQUIREMENTS: exit code nonzero on any FAIL; artifact regenerated by command, never edited by
hand; the timestamp MUST be later than the last code change at demo time (checked in the freeze
bead); prerecorded-audio cases carry the label 'input: prerecorded-wav' per line.""",
}


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    for key, title, btype, prio, body in NEW:
        code, out = run(["br", "create", title, "-t", btype, "-p", str(prio),
                         "--body", body.strip()])
        m = re.search(r"(sarvam-[a-z0-9.\-]+)", out)
        if code != 0 or not m:
            print(f"CREATE FAILED {key}: {out[:300]}")
            sys.exit(1)
        IDS[key] = m.group(1)
        print(f"NEW {key} -> {IDS[key]}")
    fails = 0
    for child, parent in NEW_DEPS:
        code, out = run(["br", "dep", "add", IDS[child], IDS[parent]])
        if code != 0:
            print(f"DEP FAILED {child}->{parent}: {out[:160]}")
            fails += 1
    print(f"deps: {len(NEW_DEPS)-fails}/{len(NEW_DEPS)}")
    cfails = 0
    for key, text in COMMENTS.items():
        code, out = run(["br", "comments", "add", IDS[key], text.strip()])
        if code != 0:
            print(f"COMMENT FAILED {key}: {out[:200]}")
            cfails += 1
    print(f"comments: {len(COMMENTS)-cfails}/{len(COMMENTS)}")
    _, out = run(["br", "dep", "cycles"])
    print("CYCLES:", out[:200])


if __name__ == "__main__":
    main()
