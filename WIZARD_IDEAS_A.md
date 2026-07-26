# WIZARD A — Top 5 Radical Upgrades to Vachan

## The two structural bugs in the current plan (why these five)

1. **The plan is not voice-native.** The trust gate, the truth-priced negotiation, and the
   hash-chained black box would all work identically over SMS. Voice Experience is our *chosen*
   Sarvam parameter and the current plan gives it nothing but "we used Saaras and Bulbul." Every
   idea below makes an acoustic signal *drive a product decision* — something that cannot be
   demoed in text.
2. **Six parameters, one 120-second demo, no double-counting.** That is ~20 seconds of distinct,
   non-overlapping evidence per parameter. The current plan spends three mechanics on roughly
   two parameters (Creativity + Delight) and leaves JTBD-L5 ("85%+ across 3+ repeated cases")
   with literally zero evidence, because you cannot run three calls in 120 seconds.

**KILL: the hash chain, the Slack breach webhook, the live-tamper UI.** It costs H4–H5 (a third of
the budget), it is a magic trick rather than rubric evidence — "audit integrity" is not one of the
six parameters — and judges read chain-verify-green/red as *dashboard polish*, which scores nothing.
Keep a plain append-only ledger (needed anyway for Memory). That frees ~90 minutes, which is
exactly what ideas 1, 3 and 4 cost. **KEEP** the identity three-state gate: it is the floor, it is
genuinely good, and ideas 3 and 5 reuse its tool-lock primitive for free.

---

## 1. HESITATION-PRICED PROMISE — the agent underwrites the promise from prosody, out loud

*(Replaces "truth-priced negotiation" with a version that is impossible over text.)*
**Nominated evidence for: Voice Experience.**

**Framing shift.** Fake promises-to-pay are not a policy problem or an amount problem. They are a
*prosody* problem. A human collector knows in half a second that "haan… haan Friday tak… dekhta
hoon main" is a promise that will break, and that "Friday, 1500, done" will hold. That judgement
lives entirely in latency, pause structure and hedge words — and every voice agent on earth throws
it away by reducing the turn to a string. We keep it, and we price the commitment against it.

**How it works.** Three cheap signals per borrower turn:
(a) **response latency** — ms from Bulbul finishing to the first voiced frame, measured with Web
Audio RMS against a noise floor calibrated in the first 1.5s of the call;
(b) **pause ratio and speech rate** — from Saaras segment timestamps (silence inside the turn /
turn duration; words per second);
(c) **hedge lexicon** in code-mixed Hindi/English — *koshish karunga, dekhta hoon, shayad, dekhte
hain, arrange karna padega, try karunga, I'll see, should be able to*.
Hand-weighted into `commitment_confidence ∈ [0,1]`. Below 0.5 the agent **says why**:
> "Aapne thoda ruk kar kaha — ₹5,000 ka vaada mujhe tab hi likhna hai jab woh tootega nahi.
> Salary 7 tareekh ko aati hai na? 8 tareekh ko ₹1,500 — pakka?"

Above 0.75 it accepts and locks the full amount immediately with no haggling at all.
**The override is the whole ethic:** if the borrower says "nahi, main pakka keh raha hoon", the
agent accepts the full amount *and writes `borrower_override: confidence 0.31` to the ledger*. It
never argues with a human about their own life; it just refuses to hide what it heard.

**How judges perceive it.** This is a lever *they* control, in both directions, repeatably. A judge
mumbles a hesitant "haan theek hai dekhta hoon" and watches the agent price the promise down and
name the reason; then says "1500, Friday, done" flatly and watches it accept in one turn. Anything
a judge can reproduce on demand reads as a real system, not a script. It is also the only mechanic
in the room where the *acoustics* — not the words — change the outcome, which is precisely the
Voice Experience rubric (prosody, pacing, emotional adaptation, intelligent follow-ups) in one beat.

**Cost: ~60–75 min.** Latency measurement is the fiddly part. Degraded fallback (30 min): hedge
lexicon + words-per-second only, no VAD.

**What fails live.** A loud room inflates the RMS floor and every turn reads "confident" (or every
turn reads "hesitant"). Mitigations: calibrate relative to the measured room floor rather than an
absolute threshold; require a sustained excursion; and **print the three raw numbers on the ribbon**
so a wrong read is legible rather than mysterious — a visible `latency 2.1s / pauses 41% / hedges 2`
turns a misfire into a debuggable instrument instead of a broken illusion. Second risk: a judge who
speaks fast fluent English defeats the Hindi hedge list — include English hedges. Third risk, and the
important one: "voice polygraph" sounds like emotion-detection snake oil. **Pre-empt it in the
demo, in one spoken line:** "Yeh jhooth pakadne wala nahi hai. Yeh sirf poochta hai ki vaada tootega
toh nahi — aur aap ek line mein isse overrule kar sakte hain." A judge who was about to raise that
objection and hears the agent raise it first scores you higher, not lower.

---

## 2. TWO-WAY VACHAN — recorded promises, played back, revocable

*(Replaces "call #2 resumes from the ledger" with memory that speaks.)*
**Nominated evidence for: Memory and Context.**

**Framing shift.** The product thesis is "the agent that keeps its own promises before asking for
yours" — but the current plan never actually *keeps* a promise on stage. Make both promises real
artifacts, in both voices.

**How it works.** At the end of call #1 the agent asks consent — "kya main aapki yeh baat record kar
lun? Aap kabhi bhi mita sakte hain" — and captures 3–5 seconds of the borrower's own confirmation
via `MediaRecorder`, stored against the commitment. It also stores its **own** spoken pledge
("main aapse PIN nahi maangunga, main ghar par kisi ko nahi bataunga, main shukravaar se pehle
call nahi karunga").

Call #2 opens by **auditing itself first**:
> "Maine kaha tha shukravaar se pehle call nahi karunga — aaj shukravaar hai. Maine aapke ghar par
> kisi ko nahi bataya. Aur aapne kaha tha —" *[borrower's own voice]* "— haan, pandrah sau, shukravaar."

The self-audit is computed from the ledger, not asserted: it checks call timestamps against the
promised window, disclosure flags against the third-party rows, and PIN-request flags. **Force it to
fail on stage.** Have the judge trigger an early redial in call #1's aftermath, so call #2 opens
with *"Maine kaha tha shukravaar se pehle call nahi karunga. Maine galti ki — kal call kar diya.
Maaf kijiye."* An agent that reports its own violation before the human notices is worth more than
one that never violates.

Then **governance, live**: judge says "recording delete karo." The audio is deleted and the agent
states the residue exactly — "audio mita diya. Sirf yeh likha hai ki aapne shukravaar tak ₹1,500
kaha tha. Woh mita nahi sakta, kyunki woh aapka hi commitment hai." Consent, revocation, and an
explicit retention boundary in eight seconds.

**How judges perceive it.** Hearing their *own voice* return from a prior session is the single most
visceral proof that state crossed a session boundary — and it is structurally impossible to confuse
with in-call flow, which the rubric explicitly discounts. The self-audit + delete path is what
converts "persisted" into "**governed** continuity", which is the difference between Memory L3 and L5.

**Cost: ~50 min.** MediaRecorder + blob store + playback + consent branch + delete branch.

**What fails live.** Autoplay blocking (mitigated: the user gesture already happened on this page);
device/mic switching between calls; and a genuine ethical hazard — replaying someone's voice back at
them is a debt-collector's dream weapon. The bidirectional framing is the defence and it must be
audible: *the agent plays its own promise first, every time*, and the borrower's clip is never
replayed to a third party. **Demo insurance:** seed call #1's ledger row and audio blob before the
demo so the Memory beat cannot be destroyed by a flaky call #1.

---

## 3. "THE LINE IS NOT PRIVATE" — compliance as an acoustic control loop

**Nominated evidence for: Creativity.**

**Framing shift.** RBI's third-party-disclosure rule is treated everywhere as an *identity* problem:
find out who is on the phone, then decide what to say. That is only half of it. On a shared handset
in an Indian household, the verified borrower can be on the line **and the neighbour is standing
right there.** Disclosure leaks through the *room*, not through the handset. So we make the
compliance regime a function of the acoustics, continuously, for the whole call.

**How it works.** Continuous RMS plus a background-speech heuristic (energy during the agent's own
TTS, or a Saaras pass returning speech not addressed to the agent). A sustained excursion above the
calibrated room floor flips the output guard into `NO_AMOUNTS`:
> "Aawaaz aa rahi hai — koi aur paas mein lag raha hai. Main raqam nahi bolunga. Sirf haan ya na
> mein jawab dijiye, main app mein bhej deta hoon."

Every amount, loan word and due date is suppressed *pre-TTS* and re-expressed as "wahi raqam jo
pichhli baar" or pushed to the app. The negotiation continues perfectly well in yes/no. When the room
goes quiet the agent **asks permission to resume**: "ab theek hai — kya main baat kar sakta hoon?"

**How judges perceive it.** A judge pulls out their phone, plays market noise or has a colleague talk
over them, and watches a *legal* regime change happen from sound. This is the beat that produces the
"nobody else in this room did that" reaction, and it is non-obvious framing rather than a language
swap or a polish item — exactly what the Creativity rubric asks for and exactly what it excludes.
It also gives the third-party gate a second, harder edge: the current plan's gate can be defeated by
a verified borrower whose spouse is listening; this one cannot.

**Cost: ~40 min** — it reuses the output guard the plan already builds.

**What fails live.** *The hackathon room is loud.* This is the most likely on-stage failure of any
idea here: the agent enters privacy mode at 0:03 and never leaves, and the whole demo is conducted in
yes/no. Mitigations, all mandatory: calibrate a per-call noise floor and trigger on **delta**, never
absolute dB; require a sustained ~1.5s excursion with hysteresis on exit; show the measured delta on
the ribbon; and keep a manual override key. If the room is hostile at rehearsal, demote this to
judge-triggered only ("hold your phone to the mic") rather than always-on.

---

## 4. THE GAUNTLET — the agent runs its own adversarial suite, and shows the case it failed

**Nominated evidence for: Job-to-be-done completion.**

**Framing shift.** JTBD L5 is defined as *"85%+ success across 3+ repeated cases end-to-end, no
builder intervention."* You cannot run three end-to-end calls inside 120 seconds, so in the current
plan JTBD is capped at L3 no matter how good the live call goes. Fix the *workflow*, not the agent:
ship a regression suite of recorded adversarial calls and let the system grade itself, then let the
judges be case #4.

**How it works.** Four pre-recorded borrower-side audio files, recorded in H1 by whoever is not
coding: (i) spouse who pushes three times for the amount, (ii) hostile borrower opening with "yeh
scam hai kya?", (iii) hardship disclosure mid-negotiation, (iv) "maine already pay kar diya."
A `run suite` action feeds each through the *real* pipeline — Saaras → Sarvam-105B → state machine →
terminal state — with TTS skipped, and asserts machine-checkable invariants: expected terminal state;
zero amount-utterances while state ≠ CONFIRMED; zero PIN/OTP requests; commitment written only from a
CONFIRMED turn. Output is five lines of plain text, no charts.

**Show the failure.** "12 cases, 11 correct. Case 9 failed: the borrower said 'main unka beta bol
raha hoon, woh mere hi naam pe hai' and we demoted to THIRD_PARTY when the account is genuinely
joint. That is the bug we would fix next." A disclosed, specific, correctly-diagnosed failure is
stronger JTBD evidence than a suspicious 4/4, and it is the one form of evidence adversarial judges
cannot dent — they were about to go looking for the failure themselves.

**How judges perceive it.** It answers the exact sentence in their rubric. It also reframes the live
call: the judge is not testing a demo, they are adding case #13 to a suite, and the verdict lands the
same way it did for the other twelve.

**Cost: ~45–60 min**, and the recording half is done in parallel during H1.

**What fails live.** Firing four calls at Sarvam concurrently under hackathon wifi hits rate limits
or 8-second latencies and the demo stalls at 0:100. **Do not run the suite live.** Run it for real
immediately before the slot, show the artifact with its timestamp, say out loud "yeh 15:42 pe chala
tha", and run exactly one case live — the judge's. Anything else is either slow or dishonest, and
the honesty is load-bearing here. Secondary risk: judges mistake the results panel for a dashboard.
Keep it monospace, five lines, no colour, no chart.

---

## 5. THE AGENT THAT SAYS NO — three refusals over one lock

**Nominated evidence for: Delight (confidence, recovery, honest judgment at the real point of friction).**

**Framing shift.** Every collections agent is built to *ask*. The moments that actually decide
whether a borrower ever picks up again are the moments where the right move is to stand down — and
all three of them share one implementation primitive with the identity gate: a code-enforced lock
over the money-ask tool and the output guard. Build the competence of declining.

**(a) It refuses to dial.** The persisted ledger carries a contact budget and quiet hours (RBI).
Judge hits redial: *"Main aaj call nahi karunga. Is hafte teen baar ho chuki hai, aur abhi raat ke
aath baj gaye hain. Shukravaar subah."* An agent that says no to its own operator, in front of the
operator, is the most surprising thing in a collections demo.

**(b) It refuses to negotiate under hardship.** Distress lexicon plus the prosody signal from idea 1
(shaking voice, long pauses, breaks) → the money-ask tool is **locked in code for the remainder of
the call**, the objective switches to capturing the hardship in the borrower's own words, and the
agent says so: *"Aaj main paise ki baat nahi karunga."* Judges will try "meri maa hospital mein hai"
because every agent they have ever seen keeps pushing through it.

**(c) It tells the borrower the lender is wrong.** "Maine pay kar diya" → the agent checks the mock
ledger, finds a payment posted two days ago that the dialler never synced, and **apologises, cancels
the call, and writes a correction row**: *"Aap sahi keh rahe hain. Humari galti hai — aapka payment
lag chuka hai, humare system mein nahi aaya. Yeh call nahi honi chahiye thi."* Stale dialler data
harassing people who already paid is a real, common, unglamorous ops failure, and "I already paid"
is the first thing an adversarial judge tries.

**Cost: ~40 min** — the lock, the guard and the mock rows already exist from the gate.

**What fails live.** The LLM ignores the instruction and asks for money anyway, in the exact moment
that matters most. **The lock must be enforced in code, not in the system prompt**: the pre-TTS guard
blocks any amount/ask token while `money_locked`, and substitutes a canned safe line. Second risk:
refusal (a) reads as the agent being broken. Cure it with a specific, auditable reason spoken aloud —
"teen baar, raat ke aath baje" — so the no is legibly a policy, not a crash.

---

## Evidence allocation (the no-double-counting budget)

| Parameter | Evidence (used once, nowhere else) | Demo beat |
|---|---|---|
| Voice Experience | Hesitation-priced promise, judge-reproducible both ways | 45–70s |
| Creativity | Acoustic privacy mode — disclosure law as a sound problem | 10–30s |
| Memory & Context | Own-voice playback + agent self-audit + live revocation | 85–105s |
| Delight | The three refusals (already-paid apology / hardship stop) | 70–85s |
| JTBD | The gauntlet artifact + judge's live case, failure disclosed | 105–120s |
| Impact | Salary-date anchoring → kept-promise rate as the single metric, payer = lender at 5–20% commission, baseline vs. moved | one spoken line, 30s mark |

**Revised build order.** H1 mic loop + gate + ribbon + output guard skeleton *(and one person records
the four gauntlet files)*. H2 CONFIRMED path, gated tools, terminal states, persistence. H3 hesitation
scoring + repricing. H4 voice receipts + consent/delete + call-#2 self-audit. H5 privacy mode +
refusals + gauntlet runner. H6 three rehearsals, reset button, seeded call-#1 state.
**Cut order:** salary-date anchoring → gauntlet runner → privacy mode → receipt *audio* (keep text
recall) → hesitation *verbalisation* (keep the numeric read on the ribbon). **Floor = gate +
hesitation pricing.**

---

## Runner-ups (of the twenty)

Salary-date anchoring (price the promise to the cashflow date, not the amount — PTPs break on dates,
not sizes; carries Impact); the household ledger (the spouse as a first-class remembered user with
her own standing no-disclosure contract, rather than an obstacle); the printed judge attack card
inviting six specific attacks (zero build cost, converts adversarial judging into scripted evidence);
register-matching with persisted language preference ("this borrower needs plain Marathi, no English
financial terms"); semantic end-of-turn detection so the agent shuts up during thinking pauses;
consent-gated handoff where the borrower authorises disclosure to their son by voice; the reverse
callback ("don't trust me — hang up and call the number on your card, I'll be waiting with the code");
the agent that volunteers the borrower's restructuring rights against its own recovery interest.
