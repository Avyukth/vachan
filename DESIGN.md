# Design System: Vachan — Collections Voice Agent Console

## 1. Visual Theme & Atmosphere

A calm operator cockpit for high-stakes voice calls. Density sits at "daily-app
balanced leaning dense" (6/10): the live-call screen carries a real-time identity
ribbon, prosody meters, and a ledger feed without ever feeling like a trading
terminal. Variance is offset-asymmetric (6/10) — the call stage occupies a
dominant left column while evidence rails hang right. Motion is fluid but
restrained (5/10): state transitions glide with spring physics; nothing bounces
for decoration. The mood is "air-traffic control for trust" — clinical surfaces,
one warm accent reserved exclusively for moments of human commitment.

## 2. Color Palette & Roles

- **Graphite Night** (#101214) — Primary background surface (app canvas; never pure black)
- **Slate Panel** (#191D21) — Cards, rails, and console panels
- **Seam Border** (rgba(148,163,184,0.14)) — 1px structural dividers and panel seams
- **Bone Text** (#E7E5E0) — Primary text
- **Muted Steel** (#8A939E) — Secondary text, metadata, timestamps
- **Vachan Amber** (#D97B29) — The single accent: record-promise moments, primary CTA, active focus ring (saturation ~72%, never neon)
- **Held Green** (#4C9A6A) — Semantic-only: CONFIRMED identity state, kept promises, passing gauntlet rows
- **Demoted Rust** (#B4553F) — Semantic-only: identity demotion, guard blocks, failed gauntlet rows

Semantic colors appear only inside the identity ribbon, ledger rows, and
gauntlet results — never on buttons or navigation. Maximum one accent.
No purple, no neon, no gradients on text.

## 3. Typography Rules

- **Display:** Geist — track-tight, weight-driven hierarchy (600/500), controlled scale; headlines never shout
- **Body:** Geist — relaxed leading (1.6), 65ch max width, secondary color for descriptions
- **Mono:** JetBrains Mono — ALL numbers, amounts (₹1,500), timestamps, confidence readouts (pauses 41% · 2.1 wps · hedges 2), ledger rows, state labels (UNKNOWN / THIRD_PARTY / CLAIMED / CONFIRMED)
- **Devanagari:** Noto Sans Devanagari — transcript lines in Hindi, matched x-height with Geist
- **Banned:** Inter, all generic serifs. This is a dashboard: sans + mono exclusively.

## 4. Component Stylings

* **Buttons:** Flat fill, softly rounded (0.75rem). Primary = Vachan Amber with charcoal text; secondary = ghost with Seam Border. Tactile 1px press-down on active. No outer glows, no gradients.
* **Identity Ribbon:** A horizontal strip of per-turn state chips in JetBrains Mono; each chip carries the state color as a left border (3px), not a fill. Demotion animates a chip sliding in with a soft lock-click affordance.
* **Cards/Panels:** Slate Panel fill, 1rem radius, Seam Border, shadow tinted to background hue and barely visible. In the dense ledger rail, cards are replaced by border-top dividers.
* **Transcript Turns:** Alternating alignment (agent left, caller right), no bubbles — a 2px speaker rule in the margin instead. Blocked utterances render struck-through in Demoted Rust with a guard glyph.
* **Prosody Meters:** Thin horizontal bars (4px) under the live turn — pause ratio, speech rate, hedge count — labeled in mono, no radial gauges.
* **Inputs:** Label above, helper below, amber focus ring. No floating labels.
* **Loaders:** Skeletal shimmer matching layout dimensions; waveform placeholder is a flat pulsing bar, never a spinner.
* **Empty States:** Composed line-art of a resting handset with one sentence of guidance.

## 5. Layout Principles

CSS Grid throughout; max-width 1400px centered for console views. The live-call
screen is a 2:1 asymmetric split: call stage (transcript + ribbon + meters) left,
evidence rail (ledger, policy rows, commitments) right. Below 768px everything
collapses to a single column with the ribbon pinned above the transcript.
No overlapping elements, no absolute-position stacking, no 3-equal-card rows.
Full-height sections use min-h-[100dvh]. Touch targets ≥44px — judges will
open this on their phones.

## 6. Motion & Interaction

Spring physics (stiffness 100, damping 20) on all state changes. The identity
ribbon demotion is the signature move: the new state chip springs in while the
tool-lock icons visibly close. Ledger rows cascade with 40ms stagger on load.
Live-turn prosody bars animate width via transform scaleX only. The
record-promise moment pulses the amber ring in a slow perpetual loop while
capturing. Everything animates via transform and opacity exclusively.

## 7. Anti-Patterns (Banned)

No emojis in UI copy. No Inter. No pure black. No purple/neon/glow shadows.
No gradient headline text. No circular spinners. No 3-column equal card grids.
No centered hero layouts. No AI copy clichés ("seamless", "elevate", "empower").
No fake round numbers — use realistic figures (₹1,500, 73 days, 41%).
No generic names — personas are Rakesh Yadav (borrower), Sunita (spouse),
Nandini (collections lead). No overlapping elements. No custom cursors.
No "scroll to explore" filler.
