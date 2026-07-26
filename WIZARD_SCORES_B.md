# Wizard B's Scores — Adversarial Review of A and C

Scoring axes per idea: rubric non-obviousness (against the specific parameter claimed, with
attention to double-counting), how much it would actually move a judge's score in a 120s
adversarial live demo, buildability inside 6 hours *alongside everything else already planned*,
and payoff vs. complexity/live-failure risk. Not graded on writing quality — graded on whether
I'd bet the demo slot on it.

Both A and C independently arrived at "kill the live-tamper hash-chain theater, keep a plain
ledger underneath" — I did not make that cut in my own submission (I kept mechanic 3 and layered
onto it). Having now read both critiques, I think they're right: chain-verify-green/red is
audit-integrity spectacle, and "audit integrity" is not one of the six scored parameters — a
skeptical judge reads it as a magic trick, which is uncomfortably close to "dashboard," which the
rules explicitly zero out. I'm flagging this once here rather than repeating it in every relevant
idea below.

---

## B on A

### A1 — Hesitation-priced promise (prosody-driven commitment confidence)
**Score: 700/1000**

Genuinely the right target — it's the only mechanic in either document where the *acoustics*, not
the words, change a real outcome, which is exactly what "Voice Experience" is supposed to mean
versus "we used Saaras and Bulbul." The self-critique is unusually honest (they pre-empt "voice
polygraph" skepticism in the demo script itself, which is smart judo). But the cost estimate is
optimistic: reliable turn-taking latency measurement via RMS-against-noise-floor, calibrated in the
first 1.5s, with browser audio echo/jitter in a hackathon room, is a harder engineering problem than
"60–75 min" suggests, and their own listed failure mode ("every turn reads confident, or every turn
reads hesitant") is the single most likely outcome under real room conditions, not an edge case. If
it degrades to hedge-lexicon-only (their stated fallback), it's a much weaker, more ordinary idea —
so the score reflects a real chance of demoing the floor, not the ceiling, of this idea.

### A2 — Two-way Vachan (own-voice recordings, self-audit, revocable)
**Score: 880/1000**

This is the strongest single idea across both documents, and it beats my own Memory pick (idea #1,
broken-promise-aware negotiation). Mine proves governed continuity *behaviorally* (strategy changes
because of history); this proves it *literally* — the borrower's own voice returning across a session
boundary is unfakeable, unmistakably not in-call flow, and cannot be mistaken for a script by even a
hostile judge. What actually wins here is the layer most teams (including mine) would skip: the agent
audits *itself* first, and is deliberately made to fail on stage and apologize — that is the exact
delta the rubric draws between Memory L3 (recall) and L5 (governed continuity), and the consent/delete
branch ("audio mita diya, sirf commitment likha hai") demonstrates *governance* as a distinct,
literal capability rather than an adjective. Cost is honest (~50 min, reuses MediaRecorder already
needed for other beats), and the demo-insurance move (seed call #1's blob before the slot so Memory
doesn't depend on a live call #1 going well) is exactly the kind of risk management a judge never
sees but a rehearsal desperately needs. My only knock: the ethical-hazard framing (replaying someone's
voice at them) is real and they know it, and the mitigation depends on disciplined execution under
demo adrenaline, not on anything code-enforced.

### A3 — "The line is not private" (acoustic privacy control loop)
**Score: 500/1000**

The framing shift is legitimately clever — disclosure risk lives in the *room*, not the handset, and
that's a real gap in the current gate (a CONFIRMED borrower with a spouse listening is currently
unhandled). But this is the riskiest idea in either document, and they say so themselves in the same
breath: "the hackathon room is loud... the agent enters privacy mode at 0:03 and never leaves." Their
own prescribed mitigation, if rehearsal shows it's too fragile, is to demote it to judge-triggered
only — but a manually-triggered privacy mode is a much weaker, much less "wow" idea than an
autonomous ambient-sensing control loop, so the honest expected value here is closer to the demoted
version than the pitched version. Distinguishing "background speech not addressed to the agent" from
room noise/breathing/the caller's own pauses in ~40 minutes of build time, reliably enough to trust
live, is optimistic; I'd bet on this either misfiring into permanent yes/no mode or needing the manual
fallback, in which case most of the Creativity payoff evaporates with it.

### A4 — The Gauntlet (self-graded regression suite + disclosed failure)
**Score: 800/1000**

This is the sharpest rubric reading in either document. JTBD L5 explicitly requires "85%+ across 3+
repeated cases, no builder intervention" — literally impossible inside a 120-second live demo — and
instead of ignoring that gap (which is what my submission does, and what C's does too), A builds the
workaround: run the suite for real before the slot, show a five-line monospace artifact with a
timestamp, and *disclose a specific, correctly-diagnosed failure* rather than a suspicious 4/4. That
last move is the smartest single sentence in either submission — a disclosed failure an adversarial
judge can't dent because they were about to go looking for it anyway. The explicit "do not run it
live" instruction shows real judgment about hackathon wifi and Sarvam rate limits. Only real risk:
judges have to trust that the timestamped run actually happened and wasn't touched up after — that
trust is earned by tone and specificity of the disclosed bug, which they've clearly thought about,
but it is still an appeal to honesty rather than something the judge can independently verify in 120s.

### A5 — The Agent That Says No (three refusals on one lock)
**Score: 740/1000**

Cheap (reuses the tool-lock primitive the gate already needs) and lands squarely on Delight's actual
rubric text ("honest judgment at the user's real point of friction") better than almost anything else
in either document — the "we already have your payment, we're wrong, sorry" beat in particular is a
genuinely disarming, realistic ops failure that no other idea in either file catches. My main
objection isn't the idea, it's the portfolio math: A's full revised plan now stacks hesitation
pricing + privacy mode + voice receipts + three refusals + a gauntlet runner onto one 120-second
adversarial demo. Each individual mechanic is well-costed in isolation, but six simultaneous new
surfaces sharing one take is a lot of rehearsal-dependent choreography, and adversarial judges by
design don't follow your script — if a judge dwells on one beat 15 seconds longer than planned, later
beats get cut live, not in rehearsal. Scored as a standalone idea it's excellent; as the fifth thing
bolted onto an already-full arc it inherits real timing risk that isn't really A's fault so much as
the cumulative effect of having five strong ideas at once.

---

## B on C

### C1 — "Vachan in your own voice" (recorded promise, replayed in call #2)
**Score: 780/1000**

Independently converges on the same core mechanic as A2 — two wizards reaching the same idea from a
blank README is a strong signal it's actually the right move, and it's adjacent to my own runner-up
(hardship-note playback). It's honestly costed (45–60 min), correctly identifies that it *replaces*
the tamper-theater slot rather than costing net-new time, and the fallback for a judge who refuses to
record ("the refusal itself is logged") is a nice touch — it turns a demo edge case into evidence
instead of a dead end. Where it loses to A's version: it stops at consent + replay, without A2's
self-audit-of-own-violations or the explicit delete-but-keep-text governance boundary — both of which
are what actually prove "governed" rather than merely "persisted," per the rubric's own wording. C1 is
a very good idea; A2 is the same idea taken one structurally important step further, which is the
difference between this score and A2's.

### C2 — Mid-call handset handover (gate survives the phone changing hands)
**Score: 820/1000**

This might be the single most practically important idea across both documents, and I'll say plainly
it's sharper than my own Voice Experience pick (barge-in cutoff). Barge-in is table-stakes — most
voice-agent teams will attempt *some* interrupt handling because it's the obvious "voice agent" tell.
Handset handover is not obvious at all: it's a direct, specific exploit of the README's own cited
evidence (shared handsets are the norm) against the plan's own gate, and it converts the single most
likely thing an adversarial judge will actually try — passing the phone mid-call rather than dialing
twice — from a probable embarrassment into the showcase beat. It's cheap because it's honest about
reusing existing demotion/challenge logic rather than claiming new infrastructure, and it even nets
back 15–20 demo-seconds by merging two call segments into one continuous call. The one soft spot is
"abrupt persona shift" as a trigger condition — that's vague and likely unbuildable reliably in the
time budget — but they hedge it correctly by scoping the *actual* trigger down to first-person
identity-claim phrases, which is buildable, so the idea survives its own vaguest sentence.

### C3 — The self-limiting collector (agent enforces limits on itself)
**Score: 650/1000**

Good instinct, cheap (~30 min, mostly prompt plus one counter plus one guarded button), and it's a
real, citable tie to the README's RBI-crackdown evidence rather than an invented compliance flourish.
My main issue is that this substantially overlaps with one-third of A's idea #5 (the "refuses to dial
due to contact cap" refusal) — two wizards independently proposed a code-enforced self-refusal on
calling frequency, which is good convergent signal for the *mechanic*, but it means C's version isn't
as novel as it's presented, and the Creativity label is shakier than claimed: an agent visibly
standing down at the user's point of friction reads to me as Delight evidence per the rubric's own
wording, not Creativity, which risks an awkward conversation with a judge who's already scoring the
"already paid, sorry" moment (if built) as Delight and now sees a second refusal fighting for the same
bucket.

### C4 — Truth-discount pricing + trust streak
**Score: 620/1000**

A reasonable, cheap sharpening of the existing negotiation mechanic (20–30 min) with real
adversarial foresight — scripting a probe question for the judge who fake-agrees to an implausibly
large number is exactly the kind of live-failure-mode thinking the other weaker ideas in both
documents lack. But it's the least *radical* idea in either top-5: making the incentive math explicit
in a negotiation is a sharpening of behavior the current plan already does, not a new interaction
mechanic or a non-obvious problem reframe, and "mechanism design, spoken aloud" is a more modest claim
than the Creativity write-up suggests. The streak-modulates-terms addition is a legitimate small
Memory-adjacent touch, and they correctly avoid double-counting it against C1's voice clip — that
discipline is worth crediting even where the idea itself is only incremental.

### C5 — Scam inoculation (borrower learns a portable fraud test)
**Score: 430/1000**

Correctly self-ranked last, and I agree with the placement. It's cheap (15–20 min) and it does connect
to the README's strongest standalone statistic (₹22,495 crore in voice-scam losses), but as a
*mechanic* it's thin: a two-sentence scripted lesson plus one ledger flag is closer to a marketing
beat bolted onto the pledge than a structurally new interaction, and "teach people to recognize scam
callers" is a fairly obvious, PR-friendly addition rather than a non-obvious framing — the Creativity
claim is the weakest-argued of any idea in either document. It also competes for demo seconds against
stronger beats (C2's handover, C1's voice replay) for a comparatively small, mostly-narrative return.

---

## Summary table

| # | Idea | Wizard | Primary parameter | Score |
|---|---|---|---|---|
| 1 | Two-way Vachan (voice replay + self-audit + governance) | A | Memory | 880 |
| 2 | Mid-call handset handover | C | Voice Experience | 820 |
| 3 | The Gauntlet (self-graded regression suite) | A | JTBD | 800 |
| 4 | "Vachan in your own voice" (voice replay) | C | Memory | 780 |
| 5 | The Agent That Says No (three refusals) | A | Delight | 740 |
| 6 | Hesitation-priced promise | A | Voice Experience | 700 |
| 7 | Self-limiting collector | C | Creativity (contested) | 650 |
| 8 | Truth-discount pricing + trust streak | C | Creativity/JTBD | 620 |
| 9 | Acoustic privacy control loop | A | Creativity | 500 |
| 10 | Scam inoculation | C | Impact/Creativity | 430 |
