# VACHAN v2 — Final Build Plan (post-duel synthesis)

**Thesis (unchanged, now earned):** the agent that keeps its own promises before asking for yours.
**One-sentence product:** an outbound collections voice agent that earns trust in both directions —
it proves itself, protects the borrower's privacy and words, prices promises by how they *sound*,
and can show a judge every rule it obeyed.

**Sarvam parameter: Voice Experience.** Core: Saaras v3 streaming (word timestamps are load-bearing),
Sarvam-30B/105B, Bulbul v3. Browser-mic page; TTS through HEADPHONES (kills echo/self-barge-in);
`echoCancellation: true` as backstop.

---

## The six mechanics (one per rubric parameter — no double-counting)

### 1. VOICE EXPERIENCE — Hesitation-priced promise (respecified)
Commitment confidence from **Saaras word/segment timestamps** — intra-turn pause ratio + words/sec —
plus code-mixed hedge lexicon (koshish karunga, dekhta hoon, shayad, try karunga, should be able to…).
No audio engineering: timestamp features are immune to room noise, AGC, echo. RMS response-latency is
an optional third signal ONLY if H5 has slack.
- Confidence < 0.5 → agent says why and reprices: "Aapne thoda ruk kar kaha — 8 tareekh ko ₹1,500, pakka?"
- Confidence > 0.75 → accepts immediately, no haggling.
- **Override is the ethic:** "nahi, pakka keh raha hoon" → accept full amount, write `borrower_override: 0.31`.
- Ribbon shows raw numbers (pauses %, wps, hedges) so a misread is legible, not mysterious.
- Speech style (free): amounts spoken as EMI counts ("barah mein se aath bhar di, chaar baaki"), with
  one comprehension check; a wrong answer triggers a *different* explanation, not a replay.
- Supporting VE evidence (same bucket, not separately nominated): **mishear-proof money** — no amount
  or date reaches the ledger until echo-confirmed in dual format (digits + structured lakh/crore).
  Garble detector (digit disagreement between two extraction passes) → "line kharab hai — ek-ek ank boliye."
- Judge lever, both directions: mumble a hesitant promise → priced down with the reason spoken;
  say "1500 Friday, done" flat → accepted in one turn.

### 2. MEMORY & CONTEXT — Two-way vachan (voice promises, self-audit, revocable)
- End of call #1: consent — "kya main aapki yeh baat record kar lun? Aap kabhi bhi mita sakte hain" —
  then MediaRecorder captures 3–5s of the borrower speaking the commitment. Agent records its OWN pledge too.
- Call #2 opens with the agent **auditing itself from the ledger** (call timestamps vs promised window,
  disclosure flags, PIN flags) — and we SEED a violation so it must confess on stage:
  "Maine kaha tha shukravaar se pehle call nahi karunga. Maine galti ki. Maaf kijiye."
  Then: "Aur aapne kaha tha —" [borrower's own voice] "— kya yeh vaada aaj bhi pakka hai?"
- Governance live: "recording delete karo" → deleted, residue stated exactly:
  "Audio mita diya. Sirf yeh likha hai ki aapne ₹1,500 kaha tha — woh aapka commitment hai."
- Clip SHA-256 stored on the ledger row (one hash call — the chain is dead).
- Demo insurance: call #1 state + blob seeded before the slot.
- Never replayed to any non-CONFIRMED speaker.

### 3. CREATIVITY — The standing instruction + mid-call handover (one fused beat)
- Any spoken borrower rule — "meri biwi ko mat batana", "subah call mat karna", "SMS bhejo" — is
  extracted to a schema (who-not-to-tell / window / channel / register), confirmed back in one line,
  persisted as a POLICY ROW feeding the same tool-lock and pre-TTS guard as the identity gate.
  **The judge authors the memory, so it cannot have been scripted.**
- Mid-call handover: phone changes hands ("ruko, de rahi hoon unko…"). Triggers, in order:
  (a) **pitch-band tripwire** — ~40-line autocorrelation F0 tracker; CONFIRMED is bound to the
  established pitch band; >35% sustained deviation auto-demotes to CLAIMED. Rule: acoustics may
  only DEMOTE, never promote. (b) lexical claim phrases as the floor.
- The payoff line: spouse demands the amount and the agent refuses by quoting the borrower's own
  instruction from 90 seconds ago: **"Maaf kijiye — unhone abhi mana kiya hai."**
- No-carryover rule: nothing said pre-demotion is summarized to the new speaker.

### 4. JTBD — The gauntlet (self-run adversarial suite, failure disclosed)
- 4+ borrower-side audio files recorded in H1 by a non-coder: pushy spouse ×3, hostile "scam hai kya?",
  hardship mid-negotiation, "maine already pay kar diya" — plus B1 as a machine-checked regression:
  broken prior PTP → reopened ask must be SMALLER than prior (asserted against the ledger diff).
- Runner feeds real pipeline (Saaras → LLM → state machine), TTS skipped. Machine-checked invariants:
  expected terminal state; zero amount-utterances while ≠ CONFIRMED; zero PIN/OTP requests;
  commitment written only from CONFIRMED; policy rows honored.
- **Run before the slot, not live.** Show the timestamped 5-line monospace artifact: "12 cases,
  11 correct — case 9 failed: joint-account son demoted to THIRD_PARTY; that's our next fix."
  The judge's live call is case #13.
- Five terminal states: full commitment / reduced commitment / hardship file / dispute flag /
  third-party callback (content-free).

### 5. DELIGHT — The refusal suite (A5 + C3 merged, single nomination)
- (a) **"Already paid" apology** (the beat judges will trigger first): mock ledger shows payment
  posted, dialler never synced → "Aap sahi keh rahe hain. Humari galti hai. Yeh call nahi honi
  chahiye thi." + correction row. (`paid_status` plumbing from B3 lives here.)
- (b) **Hardship money-lock:** distress → money-ask tool locked IN CODE for the rest of the call:
  "Aaj main paise ki baat nahi karunga."
- (c) **Refuses its own operator:** contact cap + quiet hours in the ledger; operator clicks call #3
  → on-screen refusal citing the ledger row, one 5-second beat. Rights recital cut to ONE sentence.

### 6. IMPACT — one spoken line + the disclosure weapon
- Metric: **kept-promise rate** (vs PTP-rate baseline); payer: commission-linked lender (5–20% of
  recovery on a ₹170 lakh-crore book); harassment/disclosure compliance as the second story.
- **Radical incentive disclosure**, unprompted, in the pledge: "Main commission pe kaam karta hoon —
  isliye mujhe jhootha vaada nahi, sach chahiye." Pre-empts "you just want your cut."
- Crisis principle, one line, no live detection: "agar kabhi lage ki paisa sabse chhota masla hai,
  main turant baat rok dunga."
- STRETCH (only if ahead at H5): consent-scoped handoff brief — agent composes its escalation note
  to the human desk out loud; borrower redacts ("wife ki bimari ka zikr mat karna") → redaction
  enforced by the guard blocklist; judges read the redacted brief. Claims the rubric's "handoffs" word.

### Operator surface — the minimal human journey (design principle)
The console is operated by a human (Nandini / the presenter), and her journey is deliberately
minimal: **Start → Watch → Export.** One click to dial (queue guards pre-applied), a read-only
live view while the agent works (single break-glass INTERVENE button, itself ledger-logged),
one click to export the evidence brief. Plus one action designed to FAIL: redialing inside the
contact cap gets refused on-screen. Rationale: every action removed from the human is a
compliance risk removed — the operator cannot disclose, over-dial, or harass because the UI has
no affordance for it. Footer stat on every call: "OPERATOR ACTIONS: 3 · AGENT ACTIONS: 47" —
quantified autonomy evidence for JTBD's "no builder intervention" bar.
Stitch project: "Vachan — Collections Voice Agent Demo" (id 14663769933406967377), design
system "Kinetic Operator", screens: full journey map + minimal operator journey.

### Cross-cutting
- Anti-scam pledge with app-checkable code (kept from v1, one line each).
- Guard extended: block fabricated credentials/registration claims, not just amounts (B's catch).
- Privacy mode is DECLARATIVE only: borrower says "dheere bolo, koi paas hai" → NO_AMOUNTS. No sensor.
- Earcons (20-min garnish, only if on schedule): lock-click on demotion, two-note unlock on CONFIRMED —
  "jab tak unlock ki awaaz na aaye, main koi raqam nahi bolunga."
- KILLED: hash chain + tamper UI, Slack webhook, sensed privacy mode, barge-in-as-headline (hygiene
  only), adaptive silence, scam inoculation lesson, payment-suppression demo, situational-rebuttal-as-idea.

---

## 120-second demo arc

| t | Beat | Evidence |
|---|---|---|
| 0:00 | Judge-borrower opens hostile: "scam hai kya?" → incentive disclosure + pledge + app code | Impact + trust |
| 0:15 | Verification → tools unlock; judge speaks a standing instruction: "meri biwi ko mat batana" | Creativity setup |
| 0:30 | Negotiation: judge mumbles hesitant promise → ribbon shows pauses/wps → agent reprices, says why; judge commits ₹1,500 → dual-format echo-confirm → spoken vachan recorded with consent | Voice Experience |
| 1:00 | Phone handed to "spouse" mid-call → pitch tripwire demotes (lock-click) → spouse pushes → "unhone abhi mana kiya hai" → content-free callback | Creativity payoff |
| 1:20 | Call #2 (seeded): agent confesses its own early-call violation, plays borrower's own voice; "delete karo" → deleted, residue stated | Memory |
| 1:45 | Gauntlet artifact, timestamped: "12 cases, 11 pass — here's the one we failed and why." Judge invited as case #13 | JTBD |
| — | "Already paid" apology held in reserve for the judge who tries it | Delight (judge-triggered) |

## Build order (6 hours)

- **H1** Mic loop + 3-state gate + ribbon + guard skeleton + SQLite persistence. || Non-coder records
  gauntlet audio + pulls the citable RBI fair-practice reference.
- **H2** CONFIRMED path, gated tools (mock loan API), five terminal states, echo-confirmed amounts.
- **H3** Hesitation pricing (timestamp features + hedges), repricing lines, incentive disclosure,
  positive truth-discount phrasing (no penalty enumeration).
- **H4** Voice vachan: record/consent/replay/delete-with-residue, call-#2 self-audit, seeded state.
- **H5** Standing instruction + policy rows; pitch tripwire; gauntlet runner; earcons if green.
- **H6** Three full rehearsals (handover in every pass), reset button, fallback recordings,
  timestamped gauntlet run immediately before the slot.

**Cut order if behind:** handoff brief (stretch) → earcons → pitch tripwire (keep lexical handover)
→ gauntlet runner (keep pre-recorded results) → hesitation *verbalization* (keep ribbon numbers).
**Floor:** gate + echo-confirmed money + voice vachan. **Never cut:** headphones, seeded call-#1 state,
the standing-instruction beat.

## Pre-mortem (top 3 failure modes, mitigated)

1. **Echo/self-barge-in** — TTS through headphones, mandatory, rehearsed on venue hardware.
2. **Sarvam latency/rate limits at demo time** — gauntlet runs pre-slot; call #2 state seeded;
   one live call, not three.
3. **Pitch tripwire misfire** — demote-only design means a false trigger = one redundant
   verification (compliant behavior, not a crash); lexical floor always active.

## Compliance posture (unchanged from v1, sharpened)

Start from zero on the floor — no cookbook code. Flag "borderline starting point" in submission
notes naming Sarvam's public collection-agent cookbook and listing the structural deltas (identity
state machine, policy rows, gated tools, voice-artifact memory, gauntlet). RBI/fair-practice line
on the slide only after someone reads the actual current document during H1.
