# Wizard C — Scores on A and B

Scale 0–1000. Scored against: rubric leverage (no double-counting), movement of judge
scores in a 120s adversarial demo, buildability inside 6 hours alongside everything else,
and payoff vs. live-failure risk. Where a rival idea beats one of mine, I say so.

---

## C on A

**A1. Hesitation-priced promise (prosody underwriting) — 870**
The strongest Voice Experience evidence in this duel, mine included: acoustics *drive a
product decision*, the lever is judge-reproducible in both directions, and the spoken
override plus ledger-logged `borrower_override` neutralizes the "voice polygraph" objection
before a judge can raise it. The degraded fallback (hedge lexicon + speech rate, no VAD)
preserves most of the demo value at half the cost, which is exactly the right engineering
hedge. Honest deduction: full latency measurement against a calibrated noise floor is
fiddlier than 60–75 min on hackathon wifi in a loud room, and a fast fluent-English judge
stresses the hedge list. This beats my #2 (handset handover) as VE evidence; I'd now run
handover as the JTBD/gate stressor and A1 as the VE headline.

**A2. Two-way vachan — recorded, played back, revocable, self-auditing — 905**
Best single idea across all three files, and I must admit it: this is my #1 (own-voice
promise replay) with three extensions that each independently raise the Memory ceiling —
the agent auditing its *own* recorded pledge from ledger facts, the forced on-stage
self-violation confession, and live deletion with an explicitly stated retention residue.
The delete-with-residue line is the single sharpest proof of "governed" (not merely
persisted) continuity anyone proposed. Deductions: ~50 min is optimistic once consent,
delete, and self-audit branches are all real; and the staged early-redial confession is
theater that must be rehearsed cold or it reads as a bug. Seeding call #1's state as demo
insurance is the correct paranoia.

**A3. Acoustic privacy mode ("the line is not private") — 640**
The best pure *framing* in the duel — disclosure leaks through the room, not the handset —
and it genuinely closes a hole my plan and the original gate both have (verified borrower,
listening neighbour). But it carries the worst payoff-to-fragility ratio here: browser echo
cancellation muddies "energy during own TTS," amplitude cannot distinguish a second voice
from a loud judge leaning in, and their own mitigation ladder ends at "judge-triggered
only," which quietly converts a control loop into a party trick. A privacy mode that
false-triggers during identity verification actively damages the JTBD beat. 40 min is
underestimated. Brilliant on paper; I would build it last and demo it only if rehearsal is
clean.

**A4. The Gauntlet — self-run adversarial suite, failure disclosed — 845**
The only idea from any wizard (including me — I missed this entirely) that attacks the
literal JTBD L5 text: "85%+ across 3+ repeated cases, no builder intervention," which is
otherwise capped at L3 by the 120-second format. Showing the *failed* case with a correct
diagnosis is judge-psychology gold, and "run it at 15:42, show the timestamp, run the
judge's case live as #13" is the right honesty posture. Risks are real but managed: judges
may argue pre-recorded audio isn't "end-to-end," and the suite consumes H1 recording labor
plus a runner harness that competes with the floor build. Deduction mostly for aggregate
load: in A's own revised build order this is the fifth big item in six hours.

**A5. The agent that says NO — three refusals over one lock — 800**
Overlaps my self-limiting collector on refusal (a), but the bundle is better than mine in
one specific place: refusal (c), the "maine already pay kar diya" apology with a correction
row, is the first attack a judge will actually launch and the most disarming possible
recovery — stale-dialler harassment is real, unglamorous, and nobody else touched it.
The hardship money-lock (b) enforced in code, not prompt, is the correct architecture.
Deductions: three distinct refusal paths in ~40 min is optimistic even reusing the guard;
and refusal (b)'s dependence on A1's prosody signal creates a coupling where one misfire
degrades two demo beats at once.

**Meta-note on A:** killing the hash chain outright ("audit integrity is not one of the six
parameters") is a harder and mostly correct version of my own demotion call — but A's full
slate (prosody scoring + voice receipts + self-audit + privacy mode + three refusals +
gauntlet) is *more* total ambition than the plan it criticizes. Their cut order is good;
they should expect to use it.

---

## C on B

**B1. Broken-promise-aware negotiation (memory that changes behavior) — 700**
The correct insight, cleanly stated: retrieval-memory is the floor, load-bearing memory
that visibly changes strategy is the ceiling, and the kept/broken branch is nearly free off
the existing ledger. This is the same mechanism as my trust-streak (my #4), better argued
for the Memory parameter. But as *headline* Memory evidence it loses decisively to A2's
own-voice playback with revocation — a strategy shift can be dismissed as scripting, and
B's proposed rebuttal ("show the raw DB query in a terminal") is weak against exactly the
adversarial judge it anticipates. High floor, modest ceiling.

**B2. True barge-in mid-TTS — 650**
Correct that judges will talk over the agent whether or not you build for it, and a bot
that finishes its sentence over a judge reads as the disqualified cookbook agent — so this
is genuinely demo-protective, and the manual push-to-interrupt fallback key is smart. But
it is the single most *obvious* Voice Experience move available; every serious voice team
attempts it, Pipecat/LiveKit-class stacks ship it as table stakes, and at 1–1.5h it is the
most expensive item on B's list for evidence that reads as hygiene rather than an idea.
Necessary engineering, weak differentiator: it protects points rather than winning them.

**B3. Payment-triggered call suppression — 560**
A real reframe ("stop calling the moment you don't need to") with a citable Impact metric
(calls per ₹ recovered), and honestly costed. But it is the weaker sibling of two rivals:
A5(c) turns the same "already paid" fact into an on-call apology with a correction row —
emotionally live evidence — while B's version is an operator toggling a field in a terminal
and a call *not* happening, which is the flattest possible demo beat: proving a negative in
10 borrowed seconds. B even concedes it's the first cut. Sound logic, low ceiling.

**B4. Situational anti-scam rebuttal — 480**
The diagnosis is right (a canned pledge cracks under a sharp judge; identical responses to
mild and sharp accusations expose the script) and the guard-backed safety argument is
sound. But the mechanic reduces to "write a better prompt" — that is default LLM behavior,
not a visible interaction mechanic or workflow choice, and judges cannot distinguish it
from the model simply being good. It mitigates a demo risk; it does not move a parameter.
Worth the 20 minutes, not worth a top-5 slot.

**B5. Adaptive silence tolerance with pacing check-in — 520**
Charming, cheap, and "pacing" is verbatim rubric text — this was my runner-up too. But B's
own mitigation gives the game away: if the operator must narrate "watch what happens when
we go quiet" for judges to read the pause as design rather than a hang, the evidence does
not speak for itself. Spending deliberate 2.5–3s silences inside a 120-second adversarial
demo is a bad exchange rate for a subtlety judges may not even register. Garnish, not a
mechanic.

**Meta-note on B:** the most disciplined and honestly-costed slate of the three — every
idea rides existing infrastructure, every failure mode is named — but it is patchwork
conservatism. Nothing in B's five produces the "nobody else in this room did that" moment;
A1, A2, A4, and my voice-vachan/handover all aim there. B would ship on time and place
second.

---

## Cross-duel admissions

1. **A2 > my #1** — same core mechanic; A's self-audit, forced confession, and
   delete-with-residue governance are strictly better Memory evidence.
2. **A1 > my #2 for Voice Experience** — prosody driving commitment pricing is stronger VE
   evidence than handover re-verification; my handover survives as the gate/JTBD stressor.
3. **A4 fills a gap all three of us otherwise left open** — nobody else, me included, had
   any answer to JTBD L5's "3+ repeated cases" requirement.
4. **B1's articulation of load-bearing vs. decorative memory** sharpens my trust-streak
   rationale and should be stolen verbatim for the pitch, whoever wins.
