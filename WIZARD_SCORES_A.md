# WIZARD A — Adversarial Scoring of B and C

**Calibration.** 900+ = moves two rubric levels on a whole parameter, cheap, judge-reproducible,
non-obvious. 750–850 = clear parameter-level payoff, cheap, low live risk. 600–750 = solid but
obvious, contested, or modestly staged. 450–600 = correct but marginal; competence rather than
creativity. 300–450 = costs more demo seconds than it returns. Below 300 = actively harmful.

Scored against: non-obviousness under the rubric's own exclusions (language swaps, API count,
dashboards, polish score nothing), no-double-counting discipline, movement of judge scores in 120
adversarial seconds, buildability inside 6 hours *alongside everything else*, and payoff vs.
live-failure risk.

| | Idea | Score |
|---|---|---|
| B1 | Broken-promise-aware negotiation | **780** |
| B2 | True barge-in | **640** |
| B3 | Payment-triggered call suppression | **560** |
| B4 | Situational anti-scam rebuttal | **520** |
| B5 | Adaptive silence tolerance | **480** |
| | **B mean** | **596** |
| C1 | Vachan in your own voice | **840** |
| C2 | Mid-call handset handover | **810** |
| C3 | The self-limiting collector | **700** |
| C4 | Truth-discount pricing + streak | **580** |
| C5 | Scam inoculation | **430** |
| | **C mean** | **672** |

---

## A on B

### B1 — Broken-promise-aware negotiation — **780**

The strongest thing on B's list and one of the two best ideas either of them filed. The framing —
"retrieval is the floor of Memory, not the ceiling; a judge who has watched five agents remember an
amount will not be impressed by a sixth" — is the correct read of a rubric that says *governed
continuity*, and "memory that is load-bearing rather than decorative" is a distinction most teams
will never articulate. My criticism is that the mechanic itself (branch on kept/broken, ask for
less) is what any competent team arrives at once a ledger exists, so the reframe is sharper than the
build; and its entire evidence is a *spoken sentence*, which is the weakest possible proof of
persistence. B's own mitigation gives it away: "show the raw DB query in terminal" is exactly the
artifact a skeptical judge assumes was faked thirty seconds ago. It also silently costs demo seconds
to establish that the prior promise broke — a third seeded state the narrator must explain.

### B2 — True barge-in — **640**

B is right that judges will talk over the agent whether or not it is built, and right that
"interruptions, barge-in, corrections" is verbatim rubric text — so this must ship. But it is the
single most predictable idea in this problem space; it is an engineering requirement wearing an
idea's clothes, and it buys Voice Experience competence, not Creativity, which the rubric explicitly
walls off from polish. The serious problem is that B's failure analysis misses the actual killer:
on a laptop with no headset, the agent's own Bulbul output bleeds from the speakers into the mic and
the agent barges in on *itself*, continuously. B mitigates for ambient chatter and soft-spoken
judges and never mentions acoustic echo — which is the way browser-mic voice demos usually die, and
which a 150–200ms sustained threshold does not fix. The 1–1.5hr estimate is honest for the audio
kill but optimistic once partial-utterance routing and echo suppression are real.

### B3 — Payment-triggered call suppression — **560**

The insight is good and B mines its own market research correctly: dialers harass people who already
paid because they call regardless of `paid_status`, so "an agent that stops calling the moment it
doesn't need to" is a real Impact reframe with a citable ratio. The staging is where it collapses.
B's demo beat is toggling a flag in a terminal and then watching a call *not happen* — spending
10–15 of 120 seconds to show an absence, which is a non-event on stage. The same insight staged as
an event (the agent is already mid-call, discovers the posted-but-unsynced payment, and apologises)
is strictly stronger and answers the probe judges actually run. Three of us independently landed
near this idea, which is itself evidence it is not very non-obvious, and B's own honest note that it
is "the first thing to cut" is a correct self-assessment that argues against its top-5 placement.

### B4 — Situational anti-scam rebuttal — **520**

The diagnosis is right — if the judge's sharpest accusation gets the same eight seconds as their
mildest one, the trust gate is a script in a costume — and riding the existing output guard is the
correct architectural instinct at 15–20 minutes. But "stop hardcoding the line and let the LLM
respond to what was actually said" is a bug fix on the current plan, not a radical upgrade; it is
using an LLM as intended. B also undersells its own risk: the output guard scans for
amounts and loan words while state ≠ CONFIRMED, which does nothing about the far likelier failure of
an improvising model fabricating credentials under pressure ("hum RBI-registered hain, license
4471"). A hallucinated regulatory claim in a compliance demo is worse than a canned pledge, and that
hole is unguarded.

### B5 — Adaptive silence tolerance — **480**

The observation that most teams rehearse to eliminate dead air when *dead air handled well is the
proof* is the nicest sentence in B's document, and "pacing" is named in the rubric. But this is a
supporting layer, not a top-five mechanic: it spends 2.5–3 seconds of a 120-second budget on a beat
that many judges will not register as designed, and B's own mitigation — have the operator narrate
it so it reads as intentional — concedes that it cannot stand alone. It also collides with B2 for
the Voice Experience nomination, and under no-double-counting only one of them can be the evidence,
so B has spent two of five slots competing for one parameter. I filed the same idea as a runner-up
in my own list and I would keep it there.

**Overall on B.** Disciplined and honest — B is the only one of the three of us who states
"one parameter each, so they don't fight" as an explicit *selection* criterion up front, which is the
right instinct about the binding constraint. But B chose "cheap patches onto the existing mechanics,
not a rewrite," and the brief asked for radical: three of the five (barge-in, responsive rebuttal,
VAD tuning) are competence upgrades that raise the floor rather than reframes that raise the ceiling.
B1 alone is genuinely first-rate.

---

## A on C

### C1 — Vachan in your own voice — **840**

The best single mechanic filed by either of them, and I have to concede it directly: this is the
core of my own #2, arrived at independently, and C's adversarial staging is sharper than mine — a
judge who denies the promise and is answered with their own voice is the strongest achievable moment
in 120 seconds. Hashing the clip into the chain is also a clean way to make the chain earn its keep
instead of being dead weight. Where C is beatable: this version is *one-directional*. The borrower's
promise is recorded and replayed at them with no consent flow, no revocation, and no reciprocal
recording of the agent's own pledge — which is (a) a debt-collector's weapon in front of judges
primed on RBI harassment, an optics risk C never names, and (b) the reason it stops short of Memory
L5, because the rubric's word is *governed*, and access control ("only played to the CONFIRMED
borrower") is not consent, retention, or revocation. Excellent core, missing the governance half
that a delete-on-request beat would buy for ten minutes of work.

### C2 — Mid-call handset handover — **810**

The idea I most regret not having, and I will say plainly that it exposes a gap in my own list: I
handled *the room is not private* and never handled *the handset changed hands mid-sentence*. C is
right that judges are told to play a pushy spouse, that the handover is the likeliest adversarial
move, and that a plan structured as two separate dial-ins gets broken live by it. The demo-economics
argument is the most sophisticated reasoning in either document — merging two segments into one
continuous call *returns* 15–20 seconds to the budget rather than spending them, which is thinking
about the actual binding constraint. The no-carryover rule (nothing said before re-verification is
summarised to the new speaker; nothing the spouse heard is assumed known by the borrower) is a
subtle compliance insight most teams would miss, and it is nearly free. My one real ding: C nominates
this for Voice Experience, but the trigger is *lexical* ("ab main khud bol raha hoon") — C correctly
killed voiceprint ID as undemoable, which leaves the acoustics driving nothing, so this is a state-machine
idea in Voice Experience clothing and a judge may say so.

### C3 — The self-limiting collector — **700**

The design principle is excellent and well-expressed: "provably incapable of harassment, not merely
polite about it," enforced in tooling rather than in the prompt, which C correctly identifies as the
same design language as the trust gate's tool-lock pointed at a different abuse — meaning it is
almost free to build and, as C notes, cannot break live because it is a counter check rather than an
LLM behaviour. Two problems. First, C names the no-double-counting rule and then claims this one
mechanic for Creativity *and* Impact *and* Delight inside a single section; only one nomination is
available, and pretending otherwise is the exact error the rubric is designed to punish. Second, the
rights recital is verbose — reciting call-hours, disclosure limits and complaint channels before
asking for anything is expensive in a 120-second budget, and it front-loads the demo with the agent
talking at the judge instead of the judge attacking the agent.

### C4 — Truth-discount pricing + trust streak — **580**

C correctly identifies that "negotiate down" is under-specified against a judge who simply
fake-agrees, and anticipating "theek hai, ₹5,000 pakka" as the probe is the right instinct. But the
fix — always probe once about the salary date before accepting — is a scripted turn that fires
identically on a genuinely confident borrower, which is both annoying and detectable by a judge in
two tries; it is a procedural approximation of a signal that is actually present in the audio.
Worse, C does not notice that this idea fights its own #3: an agent that opens by pricing in
"agla call, penalty, sab" is threatening consequences to extract honesty, which is precisely the
posture the self-limiting collector was built to disclaim, and a judge primed on the RBI crackdown
will hear it. The trust streak is fine but does less than B1 does with the same ledger data.

### C5 — Scam inoculation — **430**

The narrative is genuinely attractive and it mines the README's best statistic, but stripped of the
pitch this is the agent saying two more sentences — content, not mechanism — in a rubric that scores
nothing for narrative polish. C is honest enough to keep kept-promise as the single Impact metric and
to call inoculation "the beneficiary/frequency story around it," which is exactly right and also
concedes that the idea's real contribution is a better line in the pitch rather than a change in what
the system does. Spending 20 of 120 adversarial seconds teaching judges a lesson they did not ask for
is a poor trade, and C's own risk note ("cap it at two sentences or it eats the 120s") knows it. The
"inoculated: yes" flag so call #2 skips the lesson is a pleasant Memory garnish, correctly labelled a
garnish.

**Overall on C.** Clearly the stronger of the two filings. C's top two are the two best ideas outside
my own list, and C's meta-work is better than B's and better than mine in one respect: explicit
keep/sharpen/demote verdicts on the three existing mechanics, a budget reconciliation with named
offsets, a cut order, and a rewritten 120-second arc — that is a plan rather than a list. C's
decision to keep the hash chain as substrate for the voice-clip hash is the one place I think C is
wrong; hashing a blob needs one SHA-256 call, not a chain, and the chain's remaining ~45 minutes buys
nothing the rubric scores. C also breaks the no-double-counting rule it names, twice (idea 3, and the
Creativity/JTBD/Memory spread across ideas 1 and 4).
