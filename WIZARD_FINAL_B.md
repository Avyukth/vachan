# Wizard B — Final Reply (Reveal Phase)

## Part 1 — Reaction to A on B and C on B

Scores received: A gave B1=780, B2=640, B3=560, B4=520, B5=480 (mean 596, ranked B "second" of
three, "patchwork conservatism"). C gave B1=700, B2=650, B3=560, B4=480, B5=520 (mean ~582, same
verdict — "protects points rather than winning them"). Both land in the same place independently,
which is itself evidence the critique is real and not noise. Taking each in turn, honestly:

**B2 — barge-in and the echo problem. A is right, and it's not a minor miss.** I designed the
failure analysis around ambient-room noise (loud venue, soft-spoken judge) and never modeled the
actual dominant failure mode of *any* browser-mic voice demo that plays TTS through open speakers:
the agent's own Bulbul output leaks from the laptop speakers back into the mic, the amplitude-VAD
reads it as user speech, and the agent barges in on itself — potentially in a self-sustaining loop,
which is a worse and more embarrassing failure than "misses a soft interruption." A 150–200ms
sustained-trigger buffer does nothing about this because the leaked audio is sustained by
construction. I accept the correction in full and revise my score down to roughly what A and C both
converged on (~630–650), because my stated cost estimate implicitly assumed a mitigation I hadn't
actually designed.

Does barge-in survive as a build item? **Yes, but as hygiene, not as the headline idea, and the fix
is almost entirely non-code.** The standard, near-zero-cost fix is physical: run the demo on
headphones/earbuds for TTS output rather than open laptop speakers, which removes the acoustic
leak path entirely — this is how every real-world voice-agent barge-in demo is actually run, not
a workaround unique to us. Layer a software backstop on top (the browser's native
`echoCancellation: true` constraint on `getUserMedia`, one boolean) and a short post-TTS-onset
cooldown window (~150ms during which the mic is gated, since no human can physically react and
start speaking in under that) as a second line of defense. None of that changes the 1–1.5hr
estimate materially, but it does change the honest risk profile from "might work" to "will work if
we remember the headphones," which is a very different thing to walk into a demo with. I'd keep
this in the plan exactly as A frames it: necessary so a judge talking over the agent doesn't read
as the disqualified cookbook agent, not scored as a differentiator in its own right.

**B3 — payment suppression. I concede this one loses outright, not on partially.** Both of you
independently made the same point from different angles: A calls the "toggle a flag, watch a call
not happen" beat "spending 10-15 seconds to show an absence, a non-event on stage," and C calls it
"the flattest possible demo beat: proving a negative in borrowed seconds." You're both right, and
A5(c) — the "maine already pay kar diya" apology-with-correction-row — takes the *identical*
underlying insight (stale dialler data vs. reality) and stages it as a live, emotionally legible
event instead of an absence. I withdraw B3 as a standalone top-5 slot. If A5(c) makes the final
build, B3's only remaining value is the `paid_status` field itself, which A5(c) needs anyway — it
becomes plumbing, not a pitched idea.

**B4 — situational rebuttal. Also a fair demotion, with one sharp catch I want to credit
specifically.** Both of you correctly diagnose that "let the LLM respond to what was actually said
instead of reciting a fixed line" is default good prompting, not a mechanic — a judge cannot
distinguish it from the model simply being competent, and it shouldn't have been pitched as a top-5
idea on its own. A's additional catch is the one I actually want to fix, not just concede: the
output guard I described only screens amount/loan-word disclosure, and does nothing to stop an
improvising model from fabricating regulatory credentials under pressure ("hum RBI-registered hain,
license 4471") — which in a compliance-themed demo is a *worse* failure than a canned line would
have been. That's a real hole and cheap to close (extend the guard's blocklist to any specific,
falsifiable institutional claim, not just money), so I'm keeping the fix, not the pitch.

**B5 — adaptive silence. Concede fully, and I'll note both of you converged on the same word for
it independently ("garnish").** The tell is in my own mitigation: if the pause only reads as
designed when the operator narrates it live, the evidence isn't self-supporting, which is the exact
bar every other surviving idea in this duel clears without a narrator. A filed the same idea as an
explicit runner-up rather than a top-5 pick; that's the correct shelf for it, and I'm moving it
there too.

### B1 — defending it, but not the way it was pitched

Both of you gave B1 your highest or near-highest score for me (780 / 700) and both raised the same
objection: its entire evidence is "a spoken sentence," which is weak, potentially indistinguishable
from scripting, and — per A — "what any competent team arrives at once a ledger exists." I accept
the second half of that (the branch logic *is* obvious once you have a ledger) but I want to push
back on where the idea should live in the final plan, because I think both of you evaluated it as
if it had to compete with A2 for the Memory slot, and it doesn't have to.

A2's evidence is a literal artifact: a played-back audio clip, hashed, consent-gated, deletable —
that is Memory's evidence, full stop, and I already conceded in my own scoring pass that it beats
my version on that exact ground. B1's evidence, properly used, isn't a competing claim to "this is
how we prove persistence" — it's a claim about *adaptivity under real conditions*, which is JTBD
territory, not Memory territory. The fix is to stop asking B1 to stand alone on a spoken line and
instead fold it into A4's Gauntlet as one of the pre-recorded regression cases: "case 5 — borrower
with a broken prior PTP — asserts the reopened ask is smaller than the prior ask, machine-checked
against the ledger diff, not spoken." That is strictly stronger evidence than anything either of
you scored, because it inherits the Gauntlet's core trick (an artifact judges already trust because
it's timestamped and pre-run, not a live claim), it costs zero *additional* demo seconds because it
rides on a beat A4 is already spending, and it lets B1's actual contribution — the articulation that
"load-bearing memory changes strategy, decorative memory just recalls facts" — do work as a *design
principle* that sharpens the Gauntlet's case list, rather than as a competing, weaker Memory pitch.
C independently said this exact framing ("load-bearing vs. decorative") should be "stolen verbatim
for the pitch, whoever wins" — I'll take that as confirmation the sentence is worth keeping even
though the standalone mechanic isn't. Revised placement: B1 doesn't get its own slot; it becomes a
Gauntlet test case and the one line of narration that explains why that test case matters.

---

## Part 2 — Blind Spot Probe

Reading all three slates side by side, the covered ground is dense: identity/consent (gate,
handover, acoustic privacy), negotiation (truth-pricing, hesitation-pricing, streaks), memory
(ledger, voice replay, self-audit), refusals (contact caps, hardship lock, wrong-data apology), and
JTBD's literal repeated-cases requirement (the Gauntlet). Three genuinely new gaps stood out to me
across all nine filed ideas plus my own five.

### 1. The lakh/crore trap — a mandatory dual-format number confirmation loop

**The gap.** Every idea in every slate assumes the STT→amount pipeline is accurate once identity is
confirmed. Nobody addresses the single most Indian-specific, most catastrophic voice failure mode in
this domain: lakh/crore ambiguity and colloquial number phrasing ("pandrah sau" vs. "ek hazaar
paanch sau" vs. a mis-heard "pandrah hazaar") routinely produce 10x–100x amount errors in Indian
voice fintech pipelines, and this is a well-known, well-documented class of bug, not a hypothetical.
A1's prosody pricing prices *how confident the promise sounds*; nothing anywhere prices *whether the
number itself was heard correctly*.

**How it works.** Any amount the agent is about to lock as a commitment must first be spoken back in
two independent formats — digits ("ek hazaar paanch sau") and structured form ("₹1,500, pandrah sau
rupaye") — with an explicit yes/no confirmation gate before the write. If Saaras returns multiple
candidate transcriptions or a confidence score, the same gate should fire for anything below
threshold, generalizing to names and dates too — the agent should *say when it isn't sure*, instead
of silently picking the top hypothesis. Reuses the exact commitment-write lock already being built
for the trust gate; the marginal add is a formatting function and one confirmation turn.

**Judge perception / cost / risk.** This is a beat an adversarial judge can trigger on demand by
deliberately saying an ambiguous number, and a wrong number silently locked in front of judges who
know this is *the* Indian voice-fintech gotcha is a worse look than any other failure mode in this
document. Cost: ~15–20 minutes, pure logic and one extra confirmation turn, no new infrastructure,
essentially zero live-failure risk of its own (it can only make the system *more* conservative).
**Verdict: build it.** It's cheap enough that "should we build this" is barely a question, it's
genuinely Voice-Experience-native in a way that's more specific to Indian speech than most of what's
already been pitched, and it stacks as additional texture within the VE evidence bucket rather than
competing with A1/C2 for the parameter slot — multiple beats of VE evidence are fine; the
no-double-counting rule blocks reusing evidence across *different* parameters, not multiple pieces
of evidence for the same one.

### 2. Radical incentive disclosure — the agent states its own conflict of interest, unprompted

**The gap.** Every pledge in every slate is a *behavioral* promise (won't ask for PIN, won't
disclose to third parties, won't harass). Nobody has the agent disclose the one fact an adversarial
judge is most likely to weaponize and that no one preempts: the agent (or the system behind it) is
paid on a 5–20% commission of what it recovers — the README's own cited economics. Industry norm is
to hide this. The non-obvious move is to say it out loud, first, before being accused: "main jitna
zyada vasool karta hoon utna commission milta hai — isiliye main aapko sabse sasta, sabse pakka
raasta bata raha hoon, zyada nahi." Disclosing your own incentive *as* the trust move is the kind of
inversion that reads as clearly non-obvious to a judge, precisely because every collector they've
ever dealt with does the opposite.

**How it works.** Pure prompt content added to the existing trust-gate/pledge turn — no new
infrastructure, no new state, no new failure surface. It directly answers the single most obvious
line an adversarial judge holding the README's own commission stat would throw ("you just want your
cut, don't you") with an answer that was already on the table before they asked.

**Judge perception / cost / risk.** Cost: ~10 minutes, prompt-only. Risk: essentially none — it can't
break anything live because it's a static disclosure, not a sensed signal. **Verdict: build it, and
use it to replace what B4 was trying and failing to be.** B4 was correctly scored low by both of you
as "just a better prompt" with no distinguishing content; this gives the "respond to the specific
accusation" instinct an actual sharp line to reach for, which is the difference between "the LLM
being generically good" (your critique, and it was fair) and a rehearsed, quotable, non-obvious
answer to the single most predictable adversarial opener in the whole domain.

### 3. Crisis escalation override — collections stops being the objective, on purpose

**The gap.** Every hardship path in every slate — the original plan's hardship file, A5(b)'s
money-lock, C3's rights recital — stays inside the collections frame: the agent gets gentler, but
the goal is still eventually collecting or routing to restructuring. Nobody built the harder,
higher-order case: a call where continuing to talk about money at all would be the wrong thing to
do, full stop — genuine distress signals that go beyond financial hardship (a well-established,
real compliance and ethics practice at responsible collections shops, not an invented scenario).
This is the most conceptually radical gap in the entire duel: an agent whose priority ordering is
explicitly safety-before-compliance-before-collection, stated and demonstrated, not just implied by
being polite.

**How it works.** A small distress lexicon (self-harm language, medical emergency, domestic-violence
indicators) locks every money-related tool in code — reusing the identical lock primitive already
built for the trust gate and the refusals — switches to a terminal `CRISIS_ESCALATION` state, drops
the collections objective entirely, states that plainly, and (in a real deployment) offers a real
helpline number. The call ends without a single rupee being discussed.

**Judge perception / cost / risk — and why I would NOT build the live-detection version for this
demo.** Conceptually this is arguably the single most important idea in this document — it's the
one place where "the agent that keeps its own promises" is tested against the promise that actually
matters most. But operationally it's the riskiest kind of idea to run live in an adversarial 120
seconds: it requires a judge to specifically choose to play a distress scenario rather than the
spouse/hostile-borrower/already-paid attacks they're primed for, it risks landing as tonally
mismatched or performative in a competitive buildathon room if executed even slightly clumsily, and
unlike every other idea above, a *mistimed* trigger (false positive on an unrelated turn of phrase)
actively damages the demo rather than just costing seconds. **Verdict: ship the principle, not the
detection.** Add one spoken line to the existing pledge — "agar kabhi lage ki paisa sabse chhota
masla hai, main turant baat rok dunga" — which costs nothing and can't fail live, and leave the
actual lexicon-triggered lock out of the 6-hour build. It's worth saying explicitly in the pitch
that this is where the design stops on purpose, not from ordinary time pressure — a builder team
that names its own deliberate scope boundary on a sensitive case reads as more credible, not less,
than one that either overreaches into a fragile live demo or never mentions the case at all.
