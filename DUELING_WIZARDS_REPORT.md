# Dueling Idea Wizards Report — Vachan (Sarvam Epoch Buildathon)

## Executive Summary

Three models (Wizard A = Claude Opus, Wizard B = Claude Sonnet, Wizard C = Claude Fable) each
generated 20 ideas, winnowed to 5, then adversarially cross-scored each other (0–1000), reacted
to the reveal, and ran a blind-spot probe. 15 filed ideas + 8 blind-spot ideas → 7 survive into
the final plan. Top consensus picks: **A2 two-way vachan (avg 893)**, **A4 the gauntlet (823)**,
**C2 mid-call handover (815, raised to ~850 post-fix)**. Unanimous structural verdict: **kill the
hash-chain live-tamper theater** — all three models independently, unprompted.

## Methodology

Study → independent ideation (no cross-reading) → 3-way adversarial cross-scoring → reveal with
forced confrontation of score gaps → blind-spot probe ("what did NONE of us think of?") → synthesis.
Note: the intended cross-vendor duel (Claude vs Codex via ntm) was blocked by an expired Codex
auth token; the duel ran as Opus vs Sonnet vs Fable, which still produced sharp disagreement.

## Score Matrix

| Idea | Origin | Self-rank | Score 1 | Score 2 | Avg | Verdict |
|---|---|---|---|---|---|---|
| A2 Two-way vachan (voice promise, self-audit, revocation) | A | 2 | B:880 | C:905 | **893** | WINNER — Memory slot |
| A4 The gauntlet (self-run adversarial suite, failure disclosed) | A | 4 | B:800 | C:845 | **823** | WINNER — JTBD slot |
| C2 Mid-call handset handover | C | 2 | A:810→850 | B:820 | **815+** | WINNER (with pitch-demotion fix) |
| C1 Vachan in your own voice | C | 1 | A:840→800 | B:780 | **810** | MERGED into A2 (convergent, minus governance) |
| A1 Hesitation-priced promise | A | 1 | B:700 | C:870 | **785** | WINNER after respec (Saaras timestamps primary) |
| A5 The agent that says No (3 refusals) | A | 5 | B:740 | C:800 | **770** | WINNER — Delight slot (merged with C3) |
| B1 Broken-promise-aware negotiation | B | 1 | A:780 | C:700 | **740** | RELOCATED into A4 as regression case |
| C3 Self-limiting collector | C | 3 | A:700 | B:650 | **675** | MERGED into A5 (originator conceded) |
| B2 True barge-in | B | 2 | A:640 | C:650 | **645** | DEMOTED to hygiene (headphones + echoCancellation) |
| C4 Truth-discount pricing + streak | C | 4 | A:580 | B:620 | **600** | DEMOTED to policy layer on A1; threat-phrasing cut |
| A3 Acoustic privacy mode | A | 3 | B:500 | C:640 | **570** | KILLED as sensor (originator conceded); survives declarative, 10 min |
| B3 Payment-triggered suppression | B | 3 | A:560 | C:560 | **560** | WITHDRAWN by originator; paid_status becomes A5(c) plumbing |
| B4 Situational anti-scam rebuttal | B | 4 | A:520 | C:480 | **500** | KILLED; guard extended to block fabricated credentials |
| B5 Adaptive silence tolerance | B | 5 | A:480 | C:520 | **500** | KILLED (garnish; "operator must narrate it" = tell) |
| C5 Scam inoculation | C | 5 | A:430 | B:430 | **430** | KILLED as build item; one pitch line survives |

## Blind-Spot Round (ideas none of the three filed initially)

| Idea | Author | Verdict |
|---|---|---|
| Standing instruction — judge-authored memory, enforced against the operator | A | **ADOPT — Creativity slot.** Judge speaks an arbitrary rule; it persists as a policy row feeding the tool-lock/guard; the handover refusal quotes the judge's own words. Unscriptable by construction. |
| Mishear-proof money / lakh-crore dual-format confirm | C + B (convergent) | **ADOPT — VE support.** No amount or date reaches the ledger until echo-confirmed in two formats. "Noisy lines" is verbatim rubric text; nobody's filed ideas touched it. |
| Consent-scoped handoff brief (borrower redacts what the human collector sees) | C | **STRETCH.** Claims the rubric's orphaned "handoffs" word. Build only if ahead at H5. |
| Handoff that binds the human (agent polices the human collector live) | A | **STRETCH (same slot).** Strongest Impact story in the duel; needs judge role-play, so highest staging risk. |
| Radical incentive disclosure (agent states its commission conflict unprompted) | B | **ADOPT — 10-minute pitch weapon.** Pre-empts "you just want your cut." |
| Audible state — earcons fired by the state machine | C | **GARNISH.** 20 min, build if on schedule. |
| Comprehension-checked disclosure ("aapke hisaab se kitni baaki?") | A | **FOLD FREE** into negotiation speech style. |
| Crisis escalation override | B | **PRINCIPLE ONLY** — one spoken line; no lexicon-triggered live detection. |

## Meta-Analysis

- **Opus (A)** bet on voice-native signal processing and bold reframes; over-ambitious portfolio
  (conceded), but produced the two highest-scoring filed ideas and the best blind-spot idea. Its
  best move was *redesigning under criticism* (A1 → Saaras-timestamp features) rather than defending.
- **Sonnet (B)** was the honest engineer: cheapest ideas, most disciplined costing, and the duel's
  two most valuable *corrections* (acoustic echo; fabricated-credential hole in the guard). Its slate
  scored lowest because it patched rather than reframed — which it conceded.
- **Fable (C)** produced the tightest plan-craft (keep/sharpen/demote verdicts, budget reconciliation,
  cut order) and fixed its own weakest point under fire with the pitch-band demote-only tripwire —
  the duel's best example of adversarial pressure improving an idea.
- **Convergences to trust:** voice-recorded promises (A2/C1 independently), killing the tamper
  theater (all three), the "already paid" apology as the best Delight beat (A5c/B3/C3 from three
  angles), echo-confirmation of numbers (B and C independently).
- **Structural bias all three shared** (caught only in the probe): every filed idea treated the
  borrower as sole user, the system as sole author of memory, and the agent's last turn as the end
  of the job. The best late ideas (standing instruction, handoff governance) all came from breaking
  one of those three assumptions.

## Output

Final synthesized plan: see `VACHAN_PLAN_V2.md`. All duel artifacts: `WIZARD_IDEAS_{A,B,C}.md`,
`WIZARD_SCORES_{A,B,C}.md`, `WIZARD_FINAL_{A,B,C}.md`.
