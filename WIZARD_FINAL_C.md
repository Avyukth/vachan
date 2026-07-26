# Wizard C — Final: Reaction + Blind Spot Probe

## PART 1 — REACTION

### Where they are right

**A's ding on C2 ("a state-machine idea in Voice Experience clothing") is fair as filed —
and fixable acoustically within budget.** My trigger was lexical, so nothing acoustic drove
the decision. The cheap fix is a **pitch-band demotion tripwire**: during verified turns,
track median fundamental frequency (a ~40-line autocorrelation pitch detector on the Web
Audio stream — no library, no diarization, no voiceprint). Bind the CONFIRMED state to the
established F0 band; any subsequent turn deviating beyond ~35% auto-demotes to CLAIMED and
re-verifies — *before anyone claims anything*. The demo line writes itself: "the gate heard
the phone change hands." The design rule that makes this safe where voice-as-password was
not: **acoustics may only demote, never promote.** A false trigger costs one redundant
verification (compliant behavior); a missed trigger falls through to the lexical claim and
the leak-free challenge, which remain the floor. Cost ~45–60 min including tuning; a
male/female pitch gap (~100Hz vs ~200Hz) is robust even on a laptop mic, and a same-voice
judge playing both roles is exactly the case the lexical trigger still covers. With this,
C2's VE nomination is genuine, and I'd argue it now clears A's 810. The ding stands against
the version I filed.

**A's double-counting charge on C3 is correct.** I named the no-double-counting rule and
then advertised Creativity, Impact, and Delight in one section without committing a
nomination — the exact ambiguity the rubric punishes. B's added point lands too: a refusal
at the point of friction reads as Delight per the rubric's own wording, and it would collide
with A5(c)'s "already paid, sorry" beat in the same bucket. Resolution: **fold C3 into A5**
(they share the tool-lock primitive and one-third of their content), nominate the merged
refusal suite for Delight only, and cut the rights recital to a single sentence — A is also
right that a compliance monologue front-loads the demo with the agent talking at the judge.
Revised self-score for C3 standalone: 650.

**A's contradiction catch on C4 is a sharp, partial hit.** "Agla call, penalty, sab" is
threat-toned, and a judge primed on the RBI crackdown will hear the self-limiting collector
disclaiming harassment in one breath and pricing it in the next. My defense is only
half-good: disclosing a true mechanical consequence (a broken PTP re-enters the queue,
within the disclosed contact cap) is not a threat — but my *phrasing* enumerated punishments,
which is. Fix: price honesty positively and never enumerate penalties — "sach bataiye toh
seedha restructuring, koi extra call nahi" — and let the contact cap already on record do
the implicit work. A's deeper point I concede fully: my scripted salary-probe fires
identically on a confident borrower, and it is "a procedural approximation of a signal
actually present in the audio." In a merged plan, **C4 should become the policy layer on
A1's signal layer**: hesitation confidence decides *whether* to probe; truth-discount
decides *what to offer*. As a standalone: revised to 600. As A1's policy layer: worth more
than either alone.

**Both rivals scored C5 (scam inoculation) at 430 and both are right.** It is content, not
mechanism — two sentences and a flag. I demote it from a build item to one line in the
pitch and zero seconds of protected demo time.

**A on the hash chain: mostly right.** Hashing the voice clip needs one SHA-256 call, not a
chain. I'd quibble that a prev-hash column costs ~15 minutes, not 45 — but the quibble
isn't worth the minutes. Plain append-only ledger, clip hash stored per row. Chain dead.

### Where they are wrong

**B's 820 on C2 for the right reasons, but B's "abrupt persona shift is unbuildable" note
is now moot** — the pitch tripwire replaces that vague trigger with a concrete one.

**A slightly underrates C2's VE claim even as filed**: surviving an interruption-laden
handover with correct turn-taking and re-pacing *is* voice experience, not merely state
machinery — but since no acoustic signal drove a decision in my filed version, I won't die
on that hill; the fix above ends the argument.

**A's "C spread Creativity/JTBD/Memory across ideas 1 and 4" is overcharged.** C1 was
nominated for Memory and C4's streak was explicitly walled off from it ("streak modulates
terms, clip proves continuity") — B read the same text and credited the discipline. One
double-count (C3), not three.

### Revised rankings (my slate, post-duel)

C2 with acoustic tripwire (~850) > C1, superseded by A2 which I already conceded is
strictly better (adopt A2, credit both) > C4-as-policy-layer-on-A1 > C3-folded-into-A5 >
C5 demoted to pitch line.

---

## PART 2 — BLIND SPOT PROBE

Surveying all fifteen ideas: every wizard built the agent's behavior on a clean channel,
inside the voice modality, ending at a terminal state. Three surfaces none of us touched:
**what happens after the agent's last turn (the handoff), what happens when the channel
itself lies (mishearing), and the borrower's legal ownership of the memory we kept
celebrating.**

### N1. The consent-scoped handoff brief — memory that survives leaving the agent

**The gap.** The Memory rubric says "persisted, governed continuity across sessions **/
handoffs**." Fifteen ideas, three wizards — nobody touched the word *handoffs*. Real
collections always escalates to a human (dispute, hardship, aggression), and that seam is
where disclosure actually leaks in the field: the note the human collector reads.

**How it works.** When any escalation terminal state fires, the agent composes its brief
to the human desk *out loud, to the borrower first*: "Rakesh ji ko yeh bataunga — ₹1,500
shukravaar, hardship note, bas. Kuch aisa hai jo aap NAHI chahte main aage bhejun?"
Borrower: "meri wife ki bimari ka zikr mat karna" → a redaction row is written, the brief
regenerates without it, and a second screen (the "human collector's view") shows the
redacted brief judges can read. The borrower governs what memory propagates across the
organizational boundary — consent-scoped continuity, which is the literal difference
between *persisted* and *governed*.

**Judges / cost / failure.** A judge names any secret and watches it provably absent from
the handoff artifact — a 15-second beat that is impossible to mistake for in-call flow.
~40–50 min: brief generation from existing ledger rows, one redaction flag, one static
second view. Fails if the LLM paraphrases the secret back into the brief — so the redaction
is enforced by the existing output guard (blocklist built from the borrower's named terms),
not by the prompt. **Verdict: deserves a slot.** It complements rather than double-counts
A2: A2 proves continuity across *sessions*; this proves governance across *handoffs* —
two distinct evidences for the two halves of the rubric sentence.

### N2. Mishear-proof money — the agent that knows when the line is lying to it

**The gap.** Every slate implicitly assumed STT works. "Noisy lines" is verbatim VE rubric
text, and the single most likely *real* live failure is none of our fifteen ideas — it is
Saaras confidently hallucinating a number when a judge mumbles, covers the mic, or
cross-talks. Every wizard built mechanics on top of the transcript; nobody built honesty
about the transcript.

**How it works.** A hard rule in code: **no monetary amount or date reaches the ledger
until echo-confirmed** — "maine suna pandrah sau, shukravaar — sahi suna?" (which is also
exactly what good human collectors do). Plus a garble detector (turn-length anomaly, digit
disagreement between two extraction passes) that, when tripped, makes the agent say the
most disarming sentence available to a voice agent: "line kharab hai — main galat samajh
sakta hoon. Ek-ek ank boliye." The commitment row stores heard-vs-confirmed.

**Judges / cost / failure.** Adversarial judges *will* mumble — this converts the demo's
most probable disaster into its most honest beat, and it is Delight's "honest judgment at
the real point of friction" where the friction is the channel itself. ~30 min; the
echo-confirm is a prompt rule backed by a ledger-write gate in code. Failure mode is mild
annoyance if it confirms too often — scope it to money and dates only. **Verdict: deserves
a slot as cheap structural insurance**; it protects every other beat in the arc.

### N3. Audible state — the gate you can hear

**The gap.** All three of us rendered the security state machine *visually* (the ribbon) —
in a voice product, for a voice rubric. Nobody rendered state in the call's native medium.

**How it works.** Three earcons: a soft lock-click when the state demotes (the spouse takes
the phone and *hears the vault close*), a two-note unlock only on CONFIRMED, a low tick
when the output guard suppresses an utterance. The agent teaches it once: "jab tak unlock
ki awaaz na aaye, main koi raqam nahi bolunga" — which also gives the anti-scam pledge a
verifiable audio signature real lender calls would carry.

**Judges / cost / failure.** ~20 min (three static sounds on state transitions). The risk
is that it reads as sound-design polish rather than mechanic — the defense is that the
sounds are *load-bearing* (they fire from the state machine, and a judge can trigger the
lock-click at will by grabbing the phone). **Verdict: garnish, not a slot** — but at 20
minutes it is the cheapest memorability in the whole duel, so build it if H5 is on
schedule.

### Final-plan recommendation

Adopt into the merged plan: **N1 (handoff brief)** and **N2 (mishear-proof money)** as
full slots; N3 as optional garnish. Alongside the duel's surviving winners — A2 (governed
voice-vachan), C2 with the acoustic pitch-demotion tripwire, A1 + C4 as signal + policy,
A4 (gauntlet), and the merged A5/C3 refusal suite under a single Delight nomination — this
covers all six parameters with distinct evidence, including the two rubric words
("handoffs," "noisy lines") that fifteen prior ideas collectively missed.
