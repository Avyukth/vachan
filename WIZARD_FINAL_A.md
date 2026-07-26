# WIZARD A — Reaction and Blind-Spot Probe

## PART 1 — REACTION

### A1 hesitation-pricing: B says 700 (noise-floor fragility), C says 870. Who is right?

**C is right about the value; B is right about the engineering — and B's objection has made the
idea better, so I am changing the design rather than the score.**

B's specific claim is that RMS-latency-against-a-calibrated-noise-floor is harder than 60–75 minutes
and that the likely live outcome is "every turn reads confident, or every turn reads hesitant." B has
the right instinct and the wrong mechanism. Room chatter is broadband and roughly stationary, and a
judge at 30cm from a laptop mic sits 15–20 dB above it, so *onset detection* survives a loud room
fine — I am not doing ASR, I am detecting a sustained energy step. The real failure is **impulsive**
noise (a laugh, a chair scrape) producing a false onset, which fails asymmetrically toward
*false-confident*, not toward random. And C names the deeper problem that neither B nor I stated
precisely: `getUserMedia` applies **automatic gain control** by default, which normalizes exactly the
level differences I am trying to measure, before I ever see a sample.

But both of them, and I, missed that the latency channel was never the load-bearing one. **Pause
ratio and speech rate come from Saaras word/segment timestamps** — computed downstream of an STT
engine that already solved segmentation, immune to AGC, echo, room noise and VAD tuning entirely.
Intra-turn silence fraction and words-per-second are the two most diagnostic hesitation features in
the literature and they cost zero audio engineering. **Revised design: Saaras-timestamp features are
primary, hedge lexicon is secondary, RMS latency is demoted to an optional third signal built only if
H5 has slack.** This keeps the property that carries the whole claim — acoustics, not words, drive
the pricing decision — while deleting the noise-floor dependency that generated B's 700. B is
therefore right that the *originally specified* version deserved ~700; the respecified version is
worth roughly C's number, and B earned that redesign.

I reject one part of B's reasoning specifically: B scores partly on "if it degrades to
hedge-lexicon-only it's a much weaker, more ordinary idea." That was true of my stated fallback and
is no longer true — the degraded path is now timestamp-only, which is still acoustic.

### A3 acoustic privacy mode (B 500 / C 640): do I concede?

**Yes — I concede the sensing loop and I am cutting it. I do not concede the framing.**

The argument that decides it is C's, and it is not "this might fail": it is that *A3's failure
corrupts other beats*. A privacy mode that false-triggers during identity verification takes the JTBD
beat down with it, and a mechanic whose misfire has negative externalities onto neighbouring evidence
is uninsurable in a 120-second take. Add the AGC/AEC problem above — browser noise suppression will
have already gated the background speech I claim to detect, and disabling the constraints to recover
it degrades A1 in the same breath. Two of my own mechanics were fighting over the same audio
constraints and I did not notice. My own mitigation ladder ending at "judge-triggered only" was, as B
says, quietly converting a control loop into a party trick.

**What survives, at near-zero cost:** both scorers called this the best pure framing in the duel, and
the framing does not require the sensor. Make privacy mode **declarative and borrower-invoked**
instead of sensed. The borrower says "dheere bolo, koi paas hai" — or the agent simply *asks* at the
moment the phone changes hands — and the output guard flips to `NO_AMOUNTS`. Zero sensor dependency,
identical compliance insight, same guard reuse, and it is strictly better on agency: the person whose
privacy is at stake controls the disclosure rather than an amplitude threshold guessing on their
behalf. Cost drops from 40 minutes to about 10.

### Where else they are right

B's portfolio critique under A5 and C's meta-note are the strongest criticisms either made, they are
the same criticism, and I concede it without defence: **my slate proposed more total ambition than
the plan it criticised for over-ambition.** Six new surfaces sharing one adversarial take is not a
plan, it is a wish. Cutting A3 buys the slack back, and the substitution below spends it better.

B is also right that A4's gauntlet ultimately rests on an appeal to honesty a judge cannot verify in
120 seconds. I have no fix for that and would not pretend otherwise; the mitigation is tone and the
specificity of the disclosed bug, which is exactly what B said.

### Scores I revise

- **C2 (mid-call handset handover): 810 → 850.** Not because the idea changed, but because my A3 is
  now cut and C2 covers part of the same ground — identity integrity under shared-handset conditions —
  with *zero sensor risk*. Its value rose when its competitor died. It goes into the final plan in
  A3's slot. C's own admission that A1 outranks it as VE evidence actually helps: it frees C2 to be
  nominated for something else.
- **C1 (vachan in your own voice): 840 → 800.** Consensus across all three of us, including C, is
  that C1 is A2 minus governance. My 840 was priced as if it were the full article.
- I hold B2 at 640 (C independently landed 650) and B1 at 780.

---

## PART 2 — BLIND-SPOT PROBE

Fifteen ideas across three slates, and the space they cover is: identity/trust, negotiation, memory,
refusal/compliance, voice mechanics, impact framing, and one meta-workflow move. Two structural
assumptions went unexamined by all three of us.

**First: every one of the fifteen ideas has the borrower as the user and the agent as the sole
actor.** Not one models the human collector, the restructuring desk, or the compliance officer — even
though the rubric's Memory text reads "persisted, governed continuity across sessions **/ handoffs**."
The word *handoffs* has been sitting there unclaimed in exactly the way "3+ repeated cases" was
unclaimed until the Gauntlet.

**Second: in all fifteen ideas, the system decides what to remember about the borrower.** Nobody let
the borrower *write* to memory. Every memory demo in the duel replays something the system chose to
store — which is precisely why B's own B1 is vulnerable to "did you script that?", a critique B
anticipated and could not answer.

### New idea 1 — THE STANDING INSTRUCTION: memory the judge writes, enforced against the operator

At any point the borrower can issue an arbitrary spoken standing instruction — "meri biwi ko mat
batana", "subah mat call karna, shaam ko", "English mein baat mat karo", "mujhe SMS bhejo, call mat
karo". The agent extracts it into a small schema (who-not-to-tell / time window / channel / register),
**confirms it back in one line**, persists it as a policy row, and thereafter is bound by it. Not
advisory — the row feeds the same tool-lock and output guard that the identity gate already uses.

The reason this is worth a slot is a property no other idea in the duel has: **the judge authors the
memory, so it cannot have been scripted.** Every other memory beat — mine included — replays a fact
the team chose in advance, and a hostile judge is right to discount it. Here the judge invents the
constraint on the spot and then watches it bind the system.

And it fuses with C2 into the best single beat available from the whole duel. Judge-as-borrower says
"meri biwi ko mat batana." Thirty seconds later the phone changes hands mid-call (C2), the ribbon
demotes, and the spouse demands the amount. The agent refuses **not by citing policy — which is
boring, impersonal, and arguable — but by citing the borrower's own instruction from ninety seconds
ago**: *"Maaf kijiye, unhone abhi mana kiya hai."* A policy refusal invites an argument. A refusal
that quotes the judge back to themselves ends it.

*Rubric:* nominate for **Creativity** — the reframe is that the collectee sets the collector's rules,
an inversion of the power relation rather than a feature. (Deliberately *not* nominated for Memory;
that stays A2's voice replay, different artifact, different beat.)
*Cost:* ~35 min — one extraction prompt, one policy table, one guard predicate. Everything downstream
already exists.
*Fails live:* judge issues an instruction unobservable inside 120 seconds ("call me next Tuesday").
Mitigate by constraining the confirm-back question ("kab, aur kaise?") so it lands in the schema, and
by honouring the who-not-to-tell class *within the same call*, which is the demoable class anyway.

### New idea 2 — THE HANDOFF THAT BINDS THE HUMAN: the agent polices its own operator

When the call escalates to a human collector, the agent does not hand over a summary. It hands over a
**contract**: here is what you may say, here is what you may not, here is the promise this system made
on your behalf. Then it stays on the line and enforces it. The human's channel runs through the same
STT and the same pre-TTS output guard, and when the human violates it — says the amount while the
ribbon reads THIRD_PARTY, or pushes after a hardship lock — the agent **interrupts the human**, live.

Demo: hand a judge the headset and tell them they are now the collector. They will immediately try to
say the thing collectors say. The agent cuts them off. An AI whose job is restraining the human is an
inversion nobody in this duel proposed, and it is the only idea here where the AI's user is the
collections agency rather than the borrower.

*Rubric:* nominate for **Impact**, where all three slates are weakest (B3's calls-per-recovery and
C5's inoculation are the two thinnest ideas in the duel). It re-points the payer: the buyer is a
commission-linked agency, and the product is not "3% better recovery" — it is *compliance insurance*,
metric = disclosure violations per 1,000 calls, against a baseline of RBI's documented crackdown. That
is a far easier sale than incremental recovery, and it also claims the rubric's orphaned "handoffs".
*Cost:* ~40 min — the guard exists; add STT on the human channel and a barge-in interjection.
*Fails live:* interjection latency makes the catch land two seconds late and read as sluggish rather
than vigilant. Mitigate with an immediate audible chime the instant the guard fires, with the spoken
correction following.

### New idea 3 — COMPREHENSION-CHECKED DISCLOSURE (runner-up, fold in free)

Voice has no scrollback. All fifteen ideas assume the borrower knows what they owe and is deciding
whether to pay; in reality much consumer-lending distress is *confusion across four loans*, and a
borrower who cannot reconstruct their own position disengages. So: never speak "₹47,382" — speak
"barah mein se aath EMI bhar di, chaar baaki" — and then **check that it landed**: "aapke hisaab se
kitni baaki hain?" A wrong answer means the agent failed to communicate, and it *knows*, and it
re-explains differently rather than repeating itself. Judge-reproducible: deliberately answer wrong
and get a genuinely different explanation, not a replay. This is voice-native (chunking, ordering,
verified receipt) but it competes with A1 for the Voice Experience nomination, so it earns no slot —
adopt it as a free speech-style rule inside A1's negotiation turns, at roughly zero build cost.

### Which deserves a slot

**Idea 1 takes A3's vacated Creativity slot**, at similar cost, with no sensor dependency, and it
makes C2 — which I was already promoting into the plan — land harder than either idea does alone.
Final allocation: VE = A1 (respecified, timestamp-primary) · Memory = A2 · JTBD = A4 · Delight =
A5(c) · **Creativity = standing instruction + C2 handover** · Impact = idea 2 if H5 runs early,
otherwise the kept-promise pitch.

**Idea 2 is the strongest thing to build with slack and the first thing to cut without it.** It is
the only idea in the duel that claims "handoffs" and the only credible Impact story any of us
produced, but it needs a judge to accept a second role, and a 120-second take that depends on the
judge playing along on cue is a risk I have already been correctly criticised for taking too often.
