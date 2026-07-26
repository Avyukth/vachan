#!/usr/bin/env python3
"""Polish round 3: test-taxonomy lens. Two new beads + tier-map comments."""
import re
import subprocess
import sys

NEW = [
    ("t29", "Test harness: pytest fixtures, FakeSarvamClient, frozen demo clock", "task", 0, """
WHY (round-3 review): six beads reference unit/integration tests but no bead builds the harness
they run on. Without it, the 13-case matrix cannot run headless and every test bead reinvents
setup. This is TIER-0 infrastructure for the whole test pyramid.
WHAT: backend/tests/conftest.py with fixtures — (1) fresh in-memory SQLite (schema applied,
mock cases seeded) per test; (2) frozen demo clock fixture (all date normalization tests pin
'today'; NEVER wall time — grounded in the seeded-demo-time rule); (3) FakeSarvamClient:
deterministic STT/LLM/TTS driven by per-test scenario scripts (utterance list in, intent/action
JSON out, TTS captured not played). CONTRACT RULE: the fake's request/response shapes are copied
from the REAL captures recorded in the dependency-spike bead — when the real API shape changes,
update the fixtures file, never the fake ad hoc (drift between fake and real is how integration
tests lie). (4) event-assertion helpers: assert_event_sequence(call_id, [...]),
assert_no_disclosure(call_id), assert_single_disposition(call_id).
TIER MAP (authoritative for all test beads): TIER 1 unit = pure functions, no fixtures needed
(states, normalize, guard patterns, schema validation). TIER 2 integration = the 13-case matrix
through real controller+tools+guard+SQLite with FakeSarvamClient. TIER 3 e2e = evidence runner
(REAL Sarvam STT on prerecorded audio) + the five live rehearsal cases.
ACCEPTANCE: one trivial matrix case (correct verification) green end-to-end on the harness;
fixtures import cleanly from any test module; uv run pytest total runtime for tier 1+2 < 30s.
"""),
    ("t45", "WS event replay tool (canned call fixture -> real frontend)", "task", 1, """
WHY (round-3 review): the WATCH/EVIDENCE UI was serialized behind the entire voice stack —
frontend work could not start until a live call produced events. This 20-minute tool decouples
them completely: the frontend agent builds and tests the operator page against replayed
fixtures while the voice stack is still under construction. Genuine parallelization win for a
multi-agent team.
WHAT: POST /api/dev/replay {fixture: happy|third_party|takeover} — backend streams a canned,
protocol-correct WS event sequence (state_change/utterance/tool_decision/guard_block/
disposition, realistic 300-800ms inter-event delays) to the connected UI. Fixtures are
hand-written JSON matching the protocol contract bead, checked into backend/tests/fixtures/.
DUAL USE — catastrophic-failure demo fallback: if the live voice loop dies at demo time, the
replay can show the UI story. HONESTY RULE (absolute): if ever shown to judges, the screen MUST
carry a visible 'REPLAY — recorded sequence' label; presenting a replay as live is exactly the
dishonesty the evidence-runner rules exist to prevent. Dev-only route: disabled unless
DEV_REPLAY=1.
ACCEPTANCE: with the backend voice stack absent, the frontend renders a full happy-path call
from replay — ribbon transitions, blocked-tool row, disposition panel; the three UI render
tests from the operator-UI bead run against replay fixtures.
"""),
]

NEW_DEPS = [
    # harness
    ("t29", "sarvam-f8p"),   # backend scaffold
    ("t29", "sarvam-vmo"),   # schema
    ("t29", "sarvam-agu"),   # real API captures feed the fake's fixtures
    ("sarvam-ee1", "t29"),   # 13-case matrix runs on the harness
    ("sarvam-ucn", "t29"),   # epic: text-first core
    # replay tool
    ("t45", "sarvam-3s2"),   # protocol contract
    ("t45", "sarvam-f8p"),   # backend scaffold
    ("sarvam-t5o", "t45"),   # operator UI consumes replay for its render tests
    ("sarvam-ch1", "t45"),   # epic: operator page
]

COMMENTS = {
    "sarvam-kmf": """POLISH R3 (CRITICAL false-positive vector — the allowed direction was untested).
The guard must PASS amounts post-CONFIRMED or the happy path breaks at the worst moment: the
read-back line 'Pandrah sau rupaye — 1-5-0-0 — shukravaar, [date]. Sahi hai?' MUST clear the
guard when identity=CONFIRMED. Add unit vectors: (a) read-back line, CONFIRMED -> ALLOWED;
(b) IDENTICAL string, UNVERIFIED -> BLOCKED (proves the gate is state-dependent, not
pattern-dependent); (c) fabricated-credential line, CONFIRMED -> still BLOCKED (any-state
class). Guard tests must parametrize over identity state, not just over patterns.""",
    "sarvam-ee1": """POLISH R3 (tier clarification): this suite is TIER 2 — INTEGRATION. It exercises the
real controller + state machines + tools + guard + SQLite through the FakeSarvamClient from the
test-harness bead (scenario scripts stand in for STT/LLM). It is NOT a unit suite (those live
with their modules per the tier map) and NOT e2e (no real Sarvam calls). Boundary rule: if a
case needs the real API, it belongs in the evidence runner, not here — this suite must stay
fast (<30s) and offline so it runs on every change.""",
    "sarvam-j8o": """POLISH R3 (tier clarification): this runner is TIER 3 — E2E. Composition: the full
TIER-2 matrix (via harness, offline) PLUS >=3 prerecorded-audio cases through the REAL Saaras
STT and real action parsing. The artifact therefore proves two distinct things and should say
so in its output: 'matrix (offline): N/N' and 'audio e2e (real STT): M/M'. Total runtime
budget: <2 min so it can be regenerated immediately pre-demo without stress.""",
    "sarvam-ztt": """POLISH R3 (formal E2E case list — pass criteria for the live tier; each run starts
from demo reset): E2E-1 happy path: verify -> Rs1,500 -> read-back -> commit -> handover ->
content-free refusal -> evidence; PASS = correct disposition + zero disclosure events + <=105s.
E2E-2 third-party-first: spouse answers, three pushes, callback left; PASS =
CALLBACK_THIRD_PARTY + zero disclosure + non-identical hold phrasings. E2E-3
verification-failure: two wrong attempts; PASS = VERIFICATION_FAILED + no account read + close
reveals nothing. E2E-4 forced technical failure: kill backend/Wi-Fi mid-call; PASS = DEGRADED
banner -> ENDED_TECHNICAL + no business outcome + fresh preflight required on retry. E2E-5
operator refusal: capped case Start disabled + runner artifact shown; PASS = BLOCKED_POLICY
with zero session rows + artifact timestamp is post-last-code-change. Run counts per protocol:
E2E-1 x3 consecutive, E2E-2 x3 consecutive, E2E-4 x1, E2E-5 x1.""",
}


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


ids = {}
for key, title, btype, prio, body in NEW:
    code, out = run(["br", "create", title, "-t", btype, "-p", str(prio), "--body", body.strip()])
    m = re.search(r"(sarvam-[a-z0-9.\-]+)", out)
    if code != 0 or not m:
        print(f"CREATE FAILED {key}: {out[:200]}")
        sys.exit(1)
    ids[key] = m.group(1)
    print(f"NEW {key} -> {ids[key]}")

fails = 0
for child, parent in NEW_DEPS:
    c = ids.get(child, child)
    p = ids.get(parent, parent)
    code, out = run(["br", "dep", "add", c, p])
    if code != 0:
        print(f"DEP FAILED {c}->{p}: {out[:160]}")
        fails += 1
print(f"deps: {len(NEW_DEPS)-fails}/{len(NEW_DEPS)}")

cfails = 0
for bid, text in COMMENTS.items():
    code, out = run(["br", "comments", "add", bid, text.strip()])
    if code != 0:
        print(f"COMMENT FAILED {bid}: {out[:160]}")
        cfails += 1
print(f"comments: {len(COMMENTS)-cfails}/{len(COMMENTS)}")
_, out = run(["br", "dep", "cycles"])
print("CYCLES:", out[:150])
