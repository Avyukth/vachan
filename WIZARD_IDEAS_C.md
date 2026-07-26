# WIZARD C — Top 5 Upgrade Ideas for Vachan

Worked from README.md only. 20 candidates generated; killed the undemoable (voice
biomarkers, voice-as-password, telephony-dependent missed-call flip) and the
double-counting traps; winnowed to the five below, ordered best to worst. Each is
costed against the 6-hour window and the 120-second adversarial demo, with explicit
verdicts on the three existing mechanics (keep / sharpen / demote).

---

## 1. "Vachan in your own voice" — the promise is a recording, not a row

**How it works.** At the moment of commitment, the agent asks the borrower to *speak*
the promise: "apne shabdon mein boliye — kitna, kab tak." The browser mic captures
that 4–6 second clip (MediaRecorder, already have the stream), stores the blob, and
writes its SHA-256 into the existing hash chain as the commitment row. Call #2 does
not open with a database read-back; it opens with the borrower's own voice:
"kal aapne yeh kaha tha —" [plays clip] — "kya yeh vaada aaj bhi pakka hai?"

**Why it's the best idea available.**
- **Memory (L4–L5):** the rubric demands *persisted, governed continuity across
  sessions* — a replayed voice artifact from call #1, hash-anchored and consent-gated
  (only played back to the CONFIRMED borrower, never to the spouse), is the most
  visceral proof of governed cross-session memory a judge will see all day. A text
  read-back ("kal aapne ₹1,500 kaha tha") is what every other team will do.
- **Delight:** commitment-consistency psychology made audible. Judges *feel* it.
- **On-brand:** the product is literally named "Vachan" (promise). This mechanic IS
  the thesis.
- **No double-counting:** the clip is Memory evidence; the negotiation that produced
  it stays Creativity/JTBD evidence; the hash anchoring stays audit evidence.

**Judge perception / adversarial surface.** A judge-borrower who denies the promise
("maine aisa kabhi nahi kaha") gets played their own voice — the single strongest
moment achievable in 120 seconds. If the judge refuses to record, the agent falls
back to spoken confirmation + text row (graceful, and the refusal itself is logged).

**Cost & failure modes.** ~45–60 min: capture snippet on commitment terminal state,
store blob keyed to ledger row, replay button/auto-play in call #2, hash the bytes.
Fails live if: autoplay policy blocks playback (pre-click an audio unlock on page
load), or clip catches crosstalk (trim to the STT-detected utterance window).
Pays for itself by **replacing the live-tamper theater** (see verdicts below).

---

## 2. Mid-call handset handover — the gate must survive the phone changing hands

**How it works.** Shared handsets are the norm (README market evidence), and the
realistic attack is not two separate calls — it is the phone being passed mid-call:
spouse says "ruko, de rahi hoon unko… haan main bol raha hoon, batao kitna baaki
hai." Upgrade the three-state machine so any *claim-of-identity phrase, speaker-change
cue, or even an abrupt persona shift* triggers demotion to CLAIMED and a fresh
leak-free challenge — with the crucial rule that **nothing said before re-verification
is ever summarized to the new speaker**, and nothing the spouse heard is assumed known
by the borrower. The live ribbon visibly drops from THIRD_PARTY → CLAIMED → CONFIRMED
during the handover.

**Why it ranks #2.**
- **Voice Experience (the chosen Sarvam parameter):** speaker handover is the
  hardest, most Indian voice phenomenon on the rubric's own list — interruptions,
  turn-taking, corrections, re-pacing after a mid-call identity break. This is VE
  evidence no language-swap can match.
- **JTBD robustness:** judges are *told* to play a pushy spouse. The most likely
  adversarial move is exactly this handover; a plan that only handles spouse-call and
  borrower-call as separate calls will be broken live. This idea converts the most
  probable attack into the showcase.
- **Demo economics:** merging the spouse-segment and borrower-segment into ONE
  continuous call *saves* 15–20 seconds of the 120 versus two dial-ins.

**Cost & failure modes.** ~30–45 min: the demotion path and challenge already exist
per the plan; add claim-phrase triggers ("ab main khud bol raha hoon", "de do mujhe")
and the no-carryover disclosure rule to the state machine + output guard context.
Fails live if the trigger over-fires on ordinary speech — scope it to first-person
identity claims, and let the guard (already blocking amounts while ≠ CONFIRMED) be
the backstop. Rehearse this handover in all three H5–6 rehearsal passes.

---

## 3. The self-limiting collector — an agent that enforces limits on ITSELF

**How it works.** Two moves, one mechanic. (a) On contact, before asking for
anything, the agent recites the borrower's rights *against it*: call-hours window,
no third-party disclosure, harassment-complaint channel — "pehle aapke haq, phir
mera kaam." (b) It then announces and *hard-enforces* its own contact cap: "vaada
nibhaiye, toh is hafte yeh meri aakhri call hai." The cap is written to the ledger;
when the operator clicks "place call #3" inside the cap window during the demo, the
system itself refuses on-screen with the ledger row as the reason. The collector is
provably incapable of harassment, not merely polite about it.

**Why it ranks #3.**
- **Creativity (L4–L5):** every team's agent will *promise* to behave; an agent whose
  own tooling physically refuses to dial is a non-obvious inversion of the collections
  power dynamic — the same design language as the tool-lock in the trust gate, pointed
  at a different abuse (harassment instead of disclosure).
- **Impact:** anchors directly to the README's RBI-crackdown evidence. Beneficiary:
  borrower AND lender (fines, license risk). Baseline: harassment complaints /
  contact-frequency violations. One metric, distinct from kept-promise rate, so no
  double-count.
- **Delight:** "honest judgment at the user's real point of friction" — the friction
  of collections IS being hounded; the rights recital defuses the hostile "yeh scam
  hai kya?" opener better than any pledge alone.

**Judge perception / adversarial surface.** A judge who taunts "tum roz phone
karoge" gets a verifiable answer, then watches the refusal happen. Nothing to break:
the refusal is a counter check, not an LLM behavior.

**Cost & failure modes.** ~30 min: rights lines in the prompt, one counter column,
one guarded dial button. Failure mode is only wasted demo seconds — keep the
on-screen refusal to a 5-second beat.

---

## 4. Truth-discount pricing — say the incentive math out loud

**How it works.** Sharpen mechanic 2 from "negotiate down" into explicit, spoken
mechanism design: honesty is *priced cheaper* than a fake promise, and the agent says
so. "₹5,000 ka jhootha vaada mehenga padega — agla call, penalty, sab. Sach boliye
ki nahi ho payega, toh main bina penalty-call ke restructuring desk file kar deta
hoon. ₹1,500 pakka? Woh sabse sasta raasta hai." Add a two-line borrower trust
streak from the ledger: kept promise → call #2 opens with softer terms and shorter
verification ("pichhla vaada nibha — is baar seedha baat karte hain"); broken promise
→ smaller offers only. Trust is bidirectional AND compounding.

**Why it ranks #4.**
- **Creativity:** "negotiating down" is a behavior; *making honesty the dominant
  strategy and telling the borrower the payoff matrix* is a mechanism — a genuinely
  non-obvious workflow framing judges can quote back.
- **JTBD:** the five terminal states stop being labels and become incentive-compatible
  outcomes; the fake-PTP problem (README: poisoned dialler queues) is attacked at its
  cause, not its symptom.
- **Memory (secondary):** the streak is governed cross-session state that visibly
  changes agent behavior in call #2 — but the headline Memory evidence stays idea #1's
  voice replay, so no double-count: streak modulates *terms*, clip proves *continuity*.

**Cost & failure modes.** ~20–30 min: prompt surgery plus one kept/broken counter the
ledger already implies. Adversarial risk: a judge says "theek hai, ₹5,000 pakka" to
test whether the agent gullibly accepts the big number — the agent must probe once
("salary kab aati hai? ₹5,000 usse pehle kaise?") before accepting. Script that probe.

---

## 5. Scam inoculation — every collections call vaccinates the borrower

**How it works.** Extend the anti-scam pledge from a defensive credential into a
30-second public-health intervention: the agent *teaches* the borrower a portable
3-second test to use on ANY future caller — "koi bhi 'recovery agent' jo OTP, UPI
PIN, ya turant transfer maange, woh fraud hai; asli agent aapko app mein code check
karne ko kahega." The ledger tags the borrower "inoculated: yes," and call #2 skips
the lesson (small, clean Memory garnish). Close the loop symmetrically: end-of-call
spoken "vachan receipt" with a code checkable in the lender app — the same
trust-artifact shape at both ends of the call.

**Why it ranks #5.**
- **Impact narrative:** the README's own killer stat — ₹22,495 crore lost to voice
  scams, borrowers *rational* to distrust — becomes the pitch's opening and closing
  line: the only collections channel that reduces fraud losses while it collects.
  Keep kept-promise rate as the ONE Impact metric; inoculation is the beneficiary/
  frequency story around it (millions of collections calls = distribution channel).
- **Creativity:** reframes the collections call from extraction to inoculation — a
  problem-framing move, not a feature.
- **Delight:** the hostile "yeh scam hai kya?" opener is answered by making the
  *borrower* more powerful, which is the most disarming possible response.

**Cost & failure modes.** ~15–20 min, nearly pure prompt + one ledger flag. Risk is
verbosity: cap the lesson at two sentences or it eats the 120s. Lowest cost on this
list; highest narrative return per minute.

---

## Verdicts on the three existing mechanics

- **Trust gate: KEEP and harden** via idea #2 (mid-call handover). It is the floor
  and the most attacked surface.
- **Truth-priced negotiation: SHARPEN** into idea #4's explicit truth-discount +
  streak; "negotiate down" alone is under-specified against a judge who fake-agrees.
- **Hash chain: KEEP the chain, CUT the live-tamper theater.** The chain earns its
  keep as the substrate for the voice-promise hash, the contact cap, and the streak —
  but 15–20 seconds of DB-row editing mid-demo is fragile, reads as dashboard
  showmanship (which the rubric explicitly zeroes), and its slot is better spent on
  the call-#2 voice replay. Verify-green stays as a 3-second beat; tamper-red moves
  to "if judges ask."

**Budget reconciliation (~2.5h of additions, offset):** cut Slack webhook (~20m),
cut tamper UI (~45m), telephony already the last cut. New cut order if behind:
inoculation lesson → streak → contact-cap refusal button → handover trigger →
voice replay. Floor remains: gate + handover.

**Revised 120s arc:** hostile borrower opener → rights + pledge (idea 3+5, ~20s) →
verification, tools unlock → truth-discount negotiation to spoken vachan clip
(idea 4+1, ~40s) → phone handed to "spouse," ribbon demotes, gate holds ×2 (idea 2,
~25s) → call #2: streak-softened greeting + borrower's own voice replayed, chain
verify green (~25s) → operator tries call #3, system refuses (idea 3, ~5s).

**Notable runner-ups (one line each):** render guard-blocked utterances struck-through
live in the ops view (seatbelt visibly catching the crash); income-rhythm scheduling
("kamai kab aati hai?" anchors dates to cash-flow); a deliberate 10-second thinking
silence before commitment (pacing as Voice Experience); negotiation in the borrower's
mental-accounting units ("do din ki kamai"); missed-call-me-back initiation flip
(killed only by telephony dependence).
