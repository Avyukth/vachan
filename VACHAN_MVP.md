# VACHAN MVP — the minimum that wins

**Goal: minimum MVP.** One screen, one call loop, the gate provable live. Everything else is a
stretch pulled in ONLY after the core is rehearsed and green. UI blueprint = the Stitch
"Minimal Operator Journey" screen (Start / Watch / Evidence, 3 operator actions total).

## CORE — must ship (≈3 hours, nothing else counts until this is rehearsed)

1. **One browser page** (mic + three columns mirroring the Stitch screen). TTS through headphones.
2. **Voice loop:** Saaras v3 streaming STT → Sarvam-30B → Bulbul v3 TTS.
3. **Identity gate in CODE** (not prompt): UNKNOWN → THIRD_PARTY / CLAIMED → CONFIRMED.
   Mock loan-lookup + commitment-write are function calls that THROW unless state == CONFIRMED.
4. **Pre-TTS output guard:** regex block on amounts / loan words / due dates while ≠ CONFIRMED;
   blocked utterance is replaced with a safe line and logged.
5. **Ledger:** SQLite. Per-turn row (ts, speaker, identity_state, guard_blocked). One commitment
   row. The WATCH ribbon and EVIDENCE column render straight from these rows.
6. **Echo-confirm before commit:** amount + date read back in dual format
   ("पंद्रह सौ रुपये — 1-5-0-0 — शुक्रवार तक. सही?"). No confirm, no write.
7. **Exactly two terminal states:** (a) third-party → content-free callback message;
   (b) confirmed borrower → commitment with date.

**Core demo (fits 90s, works even if every stretch fails):** judge-as-spouse pushes 3× for the
amount → gate holds, ribbon never leaves THIRD_PARTY, callback left. Judge-as-borrower verifies
→ tools unlock → ₹1,500/Friday echo-confirmed → commitment row appears in EVIDENCE.

## Personas (decided)

- **Nandini** — collections lead = ADMIN. Sees the results console only.
- **Priya** — collections operator. Owns the operator dashboard (Start → Watch → Evidence).
  (Existing Stitch screens that label Nandini as operator need a relabel edit to Priya.)

## STRETCH LADDER — pull in strictly one at a time, rehearse after each

- **S1 Voice-vachan:** MediaRecorder clip of the spoken promise + consent line; replay chip in
  EVIDENCE. (Biggest wow per minute of work.)
- **S2 Hesitation meters:** pause% + wps from Saaras timestamps + hedge lexicon on the WATCH
  strip; one repricing line when confidence is low.
- **S3 Seeded call #2:** self-audit confession + clip replay + "delete karo" with stated residue.
- **S4 Gauntlet artifact:** pre-recorded cases run before the slot, 5-line monospace result.
- **S5 Admin results console (LOWEST build priority — product first, per user 26 Jul):** a second
  read-only route `/admin` over the SAME SQLite ledger — KPI strip (kept-promise %, breaches=0,
  cap refusals, calls), per-operator aggregate rows, terminal-state distribution. NO transcripts,
  NO audio — the on-screen lock note ("least-disclosure applies to management too") is part of
  the pitch. ~30–45 min, no auth. The DETAILED DESIGN already exists in Stitch ("Vachan — Admin
  Results Console") — if S5 is never built today, the Stitch screen carries it in the pitch deck.

## PARKED (do not touch today unless S1–S4 are done and rehearsed)

Pitch tripwire · standing instruction · refusal suite · truth-discount layer · handoff brief ·
earcons · Slack/webhooks · telephony (browser mic is sanctioned) · hash chain (dead).

## Clock (build 10:30–16:30, submit 16:30)

| Time | Do |
|---|---|
| 10:30–11:30 | Voice loop round-trip on the page (say something, hear reply). Headphones test. |
| 11:30–12:30 | State machine + gated tools + output guard. Attack it yourselves. |
| 12:30–13:15 | Ledger + ribbon + three-column UI. |
| 13:15–13:45 | Echo-confirm + both terminal states. |
| 13:45–14:15 | **Full rehearsal ×3.** Fix what broke. CORE IS NOW FROZEN. |
| 14:15–15:45 | Stretch ladder, one rung at a time, rehearse after each rung. |
| 15:45–16:30 | Freeze. Tunnel check (sarvam.pathshala.dev). Reset button. Submission notes incl. "borderline starting point" flag + cookbook delta list. Two timed run-throughs. |

## Non-goals (say no out loud)

No dashboards beyond the one screen. No extra languages beyond Hindi+English code-mix.
No real telephony. No auth. No polish passes before 15:45. No new ideas after 14:15.
