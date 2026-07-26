# AGENTS.md — Operating Manual for AI Coding Agents (Vachan)

> **Quick Start**: Run `br ready` to find unblocked issues. Read `VACHAN_MVP_V2.md` for the
> operating plan and `VACHAN_MVP_codex.md` for the detailed spec. Run `br sync --flush-only`
> before ending your session.

This document provides standardized instructions for ANY AI coding agent (Claude, Gemini, GPT,
Codex, etc.) working in this codebase. Structure (mirrors mouchak-bees):

1. **Layer 0**: Inviolable safety rules (NEVER break these)
2. **Layer 1**: Universal tooling (br, bv, Agent Mail, rg)
3. **Layer 2**: Session workflow (start, work, land the plane)
4. **Layer 3**: Project-specific configuration (Vachan)
5. **Layer 4**: Stack-specific instructions (uv/Python backend · SvelteKit frontend)

---

## LAYER 0: INVIOLABLE SAFETY RULES

Adopted verbatim from mouchak-bees (decision recorded 26 Jul 2026). ABSOLUTE, all agents, all
contexts.

### Rule 1: NO FILE DELETION WITHOUT EXPLICIT PERMISSION

```
YOU ARE NEVER ALLOWED TO DELETE A FILE WITHOUT EXPRESS WRITTEN PERMISSION.
```

- Applies to ALL files: user files, test files, temporary files, files you created
- ASK and RECEIVE clear written permission before ANY deletion
- "I think it's safe" is NEVER acceptable justification
- Includes: `rm`, `unlink`, filesystem APIs, git clean operations

### Rule 2: NO DESTRUCTIVE GIT/FILESYSTEM COMMANDS

**Forbidden** (unless user provides the exact command AND acknowledges consequences in the same
message):

| Command | Risk |
|---------|------|
| `git reset --hard` | Destroys uncommitted work |
| `git clean -fd` | Deletes untracked files |
| `rm -rf` | Recursive deletion |
| `git push` | **NEVER** (user pushes) |
| `git push --force` | Overwrites remote history |

Protocol for any destructive operation: safer alternative first → restate command verbatim +
affected files → wait for explicit approval → document → refuse if ambiguous.

### Rule 3: PROTECT CONFIGURATION, SECRETS, AND EVIDENCE

- **`.env` files**: never overwrite; prefer NO `.env` at all — the Sarvam key lives in the macOS
  Keychain (see Layer 3 Secrets)
- **Lock files**: do not delete `uv.lock` or `bun.lock`
- **Databases**: never delete `.beads/beads.db` or the Vachan evidence DB (`backend/vachan.db`)
  without explicit permission — the evidence ledger IS the product's proof
- **The demo reset path is the ONLY sanctioned data wipe** and it reseeds demo data only; it is
  not a license to drop tables
- **Vachan-specific**: NEVER log or store borrower verification values, blocked LLM draft bodies,
  or the API key. These rules exist in code (see Security Invariants); do not weaken them "for
  debugging"

---

## LAYER 1: UNIVERSAL TOOLING

| Task | Tool | Command |
|------|------|---------|
| Find ready issues | br | `br ready` |
| Graph analysis | bv | `bv --robot-insights` (NEVER bare `bv` — it opens a TUI) |
| Text search | ripgrep | `rg "pattern"` |
| Multi-agent coordination | Agent Mail | MCP tools (see below) |

### br (Beads Rust) — Issue Tracking

Local DB at `.beads/` (prefix `sarvam`). **48 beads already exist** covering the entire build —
do NOT invent parallel TODO lists; the graph is the plan.

```bash
br ready                                  # unblocked work
br show <id>                              # full self-documenting body — READ IT, it contains
                                          # the exact contracts (state tables, tool matrix, etc.)
br update <id> --status in_progress       # claim
br close <id> --reason "..."              # complete (decision beads: record the decision here)
br create "Title" --description="why+what" -t bug|feature|task|chore -p 0-4   # discovered work
br dep add <id> <needs-id>                # id NEEDS needs-id ("X needs Y", not temporal order)
br sync --flush-only                      # export to JSONL at session end (then git add .beads/)
```

### bv — Graph Analysis

```bash
bv --robot-next          # single top pick
bv --robot-plan          # parallel execution tracks (useful for multi-agent split)
bv --robot-alerts        # cycles, orphans, bottlenecks
```

### Agent Mail — Multi-Agent Coordination (INCLUDED for this project)

Available as the `mcp-agent-mail` MCP server. Use when 2+ agents work this repo concurrently
(likely during the buildathon sprint):

| Step | Tool | Notes |
|------|------|-------|
| 1. Ensure project | `ensure_project` | slug = repo path, human_key = `vachan` |
| 2. Register | `register_agent` | name + program + task description |
| 3. Reserve files | `file_reservation_paths` | reason = bead ID (e.g. `sarvam-5n6`); exclusive; ttl 3600 |
| 4. Work | — | announce in thread_id = bead ID |
| 5. Release | `release_file_reservations` | on close |

Natural partition for parallel work: `backend/` vs `frontend/` vs test fixtures — reserve
accordingly. If MCP tools are unavailable, flag to the user; do not shell out to a CLI.

---

## LAYER 2: SESSION WORKFLOW

### Starting

```bash
br ready && bv --robot-next        # what to do
br show <id>                       # the bead body is the spec — self-contained by design
br update <id> --status in_progress
```

Read `VACHAN_MVP_V2.md` once per session (short). Consult `VACHAN_MVP_codex.md` only when a bead
references a detail (schemas, test matrix, acceptance criteria).

### During

- Found a bug? `br create` it immediately with a description, link with `br dep add`.
- **Dependency direction trap**: `br dep add A B` means A NEEDS B. Think requirements, never
  "phase 1 before phase 2". Verify with `br blocked`.
- Decision beads (e.g. `sarvam-ijb`, the H0:45 transport decision) are closed WITH the decision
  in the close reason — that is where future agents will look for it.

### Ending ("Landing the Plane") — MANDATORY

1. File remaining work as beads (with descriptions).
2. Run quality gates (Layer 4). File P0 bugs for failures.
3. `br close` / `br comments add` for everything touched.
4. `br sync --flush-only` then `git add .beads/` + commit (user pushes — never push yourself).
5. `git status` — clean or expected.
6. Leave a follow-up prompt: `Continue <id>: [title] — [1-2 sentences of context]`.

---

## LAYER 3: PROJECT-SPECIFIC CONFIGURATION (Vachan)

### What Vachan Is

An outbound **collections voice agent** for Indian consumer lending, built at the Sarvam Epoch
Buildathon (6-hour build, 120-second adversarial demo where judges play the borrower/spouse).

**Thesis: code — not the language model — decides when private collection data and write tools
unlock.** On a shared handset (the norm in India), the agent must establish WHO is speaking
before revealing that a loan exists. The spouse learning about the debt is the harm; refusing
to disclose IS the completed job.

**Two business outcomes**: a privacy-safe, echo-confirmed promise-to-pay (`PROMISE_CONFIRMED`),
or a content-free third-party callback (`CALLBACK_THIRD_PARTY`). Three safe non-business
endings: `VERIFICATION_FAILED`, `ENDED_TECHNICAL`, `ENDED_OPERATOR`. Every call ends in exactly
one disposition; a technical failure can NEVER become a business outcome.

**Personas**: Priya = collections operator (owns the UI; 3 actions per call: open case, start,
inspect outcome). Nandini = collections lead (stakeholder only today; admin console exists as a
Stitch design, NOT built). Rakesh Yadav = borrower. Sunita = spouse. ALL DATA IS MOCK — the UI
carries a permanent `DEMO / MOCK DATA` badge.

### Architecture

```
Caller (judge) ⇄ mic/headphones
      │
      ▼
SvelteKit frontend  :3000  ← Cloudflare tunnel → https://sarvam.pathshala.dev
  (operator page: Start · Watch · Evidence; AudioWorklet capture; audio playback)
      │  vite proxy: /api/* and /ws → :8000
      ▼
FastAPI backend  :8000  (uv-managed Python)
  ├── dialogue controller — THREE state machines in code (call · identity · promise)
  ├── context isolation  — account data enters LLM context ONLY at CONFIRMED
  ├── gated tools        — typed failures; permission matrix in sarvam-kyf
  ├── pre-TTS output guard — multilingual blocklist; discard draft + safe line on fire
  ├── Sarvam APIs        — Saaras v3 STT · chat LLM (typed intent JSON) · Bulbul v3 TTS
  └── SQLite evidence    — cases · calls · events · tool_decisions · candidates · promises
```

The four disclosure layers, in order of strength: **context isolation → tool isolation → fixed
pre-CONFIRMED templates → output guard**. The model cannot leak what it was never given.

### Repository Layout

```
sarvam/
├── AGENTS.md                  # this file
├── VACHAN_MVP_V2.md           # operating plan (wins conflicts)
├── VACHAN_MVP_codex.md        # detailed spec (schemas, contracts, test matrix)
├── VACHAN_MVP.md / VACHAN_PLAN_V2*.md / DUELING_WIZARDS_REPORT.md   # lineage — do not edit
├── DESIGN.md                  # UI design system ("Kinetic Operator" — see Stitch project)
├── vachan_product.drawio      # architecture + call flow + state machine diagrams
├── vachan_*.png               # Stitch screen references (operator UI blueprint)
├── .beads/                    # br issue graph — THE plan (48 beads, 10 epics)
├── backend/                   # uv Python: FastAPI app  (create via bead sarvam-vmo onward)
│   ├── pyproject.toml         # managed by uv ONLY
│   ├── app/                   # states.py · verification.py · tools.py · guard.py ·
│   │                          # controller.py · sarvam_client.py · db.py · main.py
│   ├── tests/                 # pytest — the 13-case matrix (sarvam-ee1)
│   └── vachan.db              # SQLite evidence ledger (gitignored)
└── frontend/                  # SvelteKit (bun-managed)
    ├── package.json
    ├── vite.config.ts         # port 3000 + proxy /api,/ws → :8000 (ws: true)
    └── src/routes/            # operator page (single route today)
```

### Epic Structure (bead IDs are live — `br show <id>` for full bodies)

| Epic | ID | Priority | Scope |
|------|----|----------|-------|
| H0:00–0:20 Freeze contracts | `sarvam-ibt` | P0 | enums, schema, tool matrix, seeds, dispositions |
| H0:20–0:45 Dependency/audio spike | `sarvam-fq8` | P0 | creds, model IDs, PCM spike, transport DECISION |
| H0:45–1:45 Text-first safety core | `sarvam-ucn` | P0 | states, verification, isolation, promise, guard, tests |
| H1:45–2:45 Voice vertical slice | `sarvam-v8o` | P0 | STT, LLM, TTS, end-to-end spoken call |
| H2:45–3:30 Operator page | `sarvam-ch1` | P1 | preflight, 3 columns, takeover, reset |
| H3:30–4:10 Edge paths | `sarvam-elg` | P0 | third-party, handover, failures, contact-cap |
| H4:10–4:30 Evidence runner | `sarvam-pnx` | P1 | honest timestamped test artifact |
| H4:30–6:00 Freeze & rehearse | `sarvam-zlg` | P1 | rehearsals, venue-proofing, final artifact |
| Post-core competition evidence | `sarvam-shn` | P2 | CE1 memory, CE2 audio cases, CE3 impact slide — GATED |
| Demo & submission | `sarvam-262` | P1 | demo script, submission notes w/ borderline flag |

### Security Invariants (NEVER BREAK)

1. No account data (amounts, lender, dates, fields) in ANY LLM prompt while identity ≠ CONFIRMED.
2. `read_mock_account` / `create/correct/commit_promise` tools are structurally unavailable
   before CONFIRMED — typed failure + `tool_decisions` row, zero mutation.
3. Verification expected-values are never spoken by the agent, never sent to the LLM, never
   logged (log field names + pass/fail only). Max two attempts.
4. Every agent utterance passes the output guard BEFORE TTS. On fire: discard the ENTIRE draft,
   play a fixed safe line, write `OUTPUT_BLOCKED` — never log the draft body.
5. `commit_promise` requires read-back + explicit affirmative; idempotency key makes duplicates
   impossible; corrections force re-read-back.
6. Handover or third-party language clears CONFIRMED in the SAME turn, before any response.
7. Identity always starts UNVERIFIED per call. Never restored across calls.
8. events/promises tables are append-only. No UPDATE. Operator notes are append-only+attributed.
9. The Sarvam API key exists only backend-side. Never in frontend code, git, logs, or responses.
10. Technical failure fails CLOSED: tools lock, speech stops, disposition `ENDED_TECHNICAL`.
11. Takeover ordering is law: revoke tools → cancel pending work → stop TTS → log → THEN
    operator mic. The agent never resumes after takeover.

### Secrets

```bash
# Sarvam API key — already stored in macOS Keychain (service sarvam-api, account vachan):
security find-generic-password -s sarvam-api -w
```

Backend retrieves at startup via `subprocess` (see bead `sarvam-agu`). First access triggers a
macOS dialog — Always Allow during setup, never on stage. NO `.env` for this key.

### Demo Operations

- **Stage demo runs on `http://localhost:3000`** (never through the tunnel — venue Wi-Fi latency).
- Public link for submission/judges' phones: `https://sarvam.pathshala.dev` — Cloudflare tunnel
  `rust-fast-experiment` → localhost:3000. Restart: `cloudflared tunnel run rust-fast-experiment`.
- Headphones REQUIRED (open speakers = agent hears itself). `echoCancellation: true` backstop.
- Demo reset: UI action, outside active calls only, reseeds mock data + fresh call IDs.
- Compliance posture: built from zero on the floor; submission notes MUST carry the "borderline
  starting point" flag naming Sarvam's public collection-agent cookbook + our structural deltas
  (bead `sarvam-rwl`). Hiding origin = auto-disqualification.

---

## LAYER 4: STACK-SPECIFIC INSTRUCTIONS

### Backend: Python via uv (NEVER pip/venv/conda)

| Setting | Value |
|---------|-------|
| Package manager | `uv` ONLY (`uv add`, `uv sync`, `uv run`) |
| Framework | FastAPI + uvicorn, WebSocket support |
| Python | 3.12+ (uv-pinned in `pyproject.toml`) |
| DB | sqlite3 stdlib (or aiosqlite) — no ORM; schema in bead `sarvam-vmo` |
| Lint/format | `uv run ruff check .` · `uv run ruff format --check .` |
| Tests | `uv run pytest -x -q` — the 13-case matrix is the core suite |
| Run | `uv run uvicorn app.main:app --port 8000 --reload` |

Conventions: type hints everywhere; state machines are pure functions (no I/O) so the matrix
runs headless; typed exceptions for tool denials (never bare `raise Exception`); all Sarvam API
calls have explicit timeouts and cancellation checks (stale callbacks must check call state and
drop themselves); never `except: pass`.

### Frontend: SvelteKit via bun (NEVER npm/yarn/pnpm)

| Setting | Value |
|---------|-------|
| Package manager | `bun` (`bun install`, `bun run dev`, `bunx`) |
| Scaffold | `bunx sv create frontend` (minimal template, TypeScript) |
| Dev server | port **3000** (set in `vite.config.ts`) — owns the tunnel origin |
| API/WS proxy | vite `server.proxy`: `/api` → `http://localhost:8000`, `/ws` → `ws://localhost:8000` with `ws: true` |
| Checks | `bun run check` (svelte-check) |
| Styling | plain CSS per the Kinetic Operator system (DESIGN.md): #101214 bg, #191D21 panels, single amber #D97B29 accent (promise moments ONLY), green/rust semantic-only, monospace for ALL numbers and state labels. No component library today. |

Devanagari rules (learned by shipping it broken — see `a116bef`):
- **Every font stack that can hold Hindi must name a Devanagari face.** `--font-mono` ended at
  `monospace`, which has no Devanagari coverage, so the ledger's Hindi was shaped by a
  Latin-only face and matras (ि े ै above, ु ृ below) collapsed into the base glyph. Keep the
  Latin mono faces FIRST so digits/states keep their grid; Devanagari falls through per glyph.
- **No `letter-spacing` on Devanagari — ever.** Devanagari is shaped, not tracked. The brand
  `वचन` inherited `-0.04em` (−1.28px at 32px) and rendered visibly crushed. Reset to `normal`.
- **Devanagari needs more size and leading than the equivalent Latin.** 0.68rem/1.4 left no
  vertical room for stacked matras; ledger rows are 0.8rem/1.85. Never set Hindi below ~12px.
- There is **no `@font-face` and no bundled font file** in this repo. Family names resolve only
  if the viewer has them, so `--font-deva` names faces that exist on the demo machine
  (Kohinoor Devanagari at `/System/Library/Fonts/Kohinoor.ttc`) with Nirmala UI for Windows.
  If you add a webfont, self-host it — do not rely on a CDN the venue may not reach.
- **Template bank copy is Devanagari, not romanized.** `STT_RECOVERY` shipped as
  `"line kharab hai, dobara boliye"`; Bulbul pronounces romanized Hindi as English and it
  renders in the wrong face. A test asserts the line is not ASCII.
- Verify by measuring, not by eye: read `getComputedStyle` for `fontFamily`, `fontSize`,
  `letterSpacing` on an element that actually contains `[ऀ-ॿ]`, then zoom a screenshot.

Audio rules (the hard-won ones):
- Capture via **AudioWorklet** → mono PCM16 @ 16 kHz (browser native rate is usually 48 kHz —
  resample; `MediaRecorder` WebM/Opus is ONLY acceptable on the REST fallback path).
- Resume `AudioContext` + unlock playback on the Start click (autoplay policy).
- One utterance playing at a time; End/Takeover kills playback immediately.
- The transport (streaming vs REST) is decided by bead `sarvam-ijb` at H0:45 and is PERMANENT.

### Quality Gates (before any commit)

```bash
cd backend  && uv run ruff check . && uv run ruff format --check . && uv run pytest -x -q
cd frontend && bun run check
```

The 13-case matrix (`sarvam-ee1`) is the gate that matters: if it is red, nothing ships, no
matter how good the demo looks.

### Test Strategy

| Tier | What | How |
|------|------|-----|
| 1 Unit (pure) | state transitions, verification normalize/compare, amount/date normalization (lakh/hazaar words → minor units; 'Friday' → ISO Asia/Kolkata), guard patterns (Hindi/English/code-mix) | pytest, no I/O |
| 2 Controller (text-mode) | the 13-case matrix end-to-end against real controller+tools+guard+SQLite, typed text in place of audio | pytest, headless, one command |
| 3 Evidence runner | matrix + ≥3 labeled prerecorded audio cases through the REAL pipeline (real STT), timestamped artifact regenerated immediately pre-demo | `uv run python -m app.runner` (bead `sarvam-j8o`) |

**Honesty rule (absolute)**: a typed results panel is not test evidence. Failures are shown and
diagnosed, never hidden — a disclosed failure with a correct diagnosis scores higher than a
suspicious perfect run.

---

## Reference Documents

| Document | Purpose |
|----------|---------|
| `VACHAN_MVP_V2.md` | Operating plan — wins all conflicts |
| `VACHAN_MVP_codex.md` | Detailed spec: schemas, contracts, dialogue controller, test matrix |
| `.beads/` (48 beads) | THE task graph — self-documenting, includes acceptance criteria |
| `vachan_product.drawio` | Architecture, call flow, and state machine diagrams |
| `DESIGN.md` + `vachan_*.png` | UI design system + Stitch screen blueprints |
| Stitch project `14663769933406967377` | Live design source (stitch.withgoogle.com, pathshaladotdev account) |

<!-- bv-agent-instructions-v2 -->

---

## Beads Workflow Integration

This project uses [beads_rust](https://github.com/Dicklesworthstone/beads_rust) (`br`) for issue tracking and [beads_viewer](https://github.com/Dicklesworthstone/beads_viewer) (`bv`) for graph-aware triage. Issues are stored in `.beads/` and tracked in git.

### Using bv as an AI sidecar

bv is a graph-aware triage engine for Beads projects (.beads/beads.jsonl). Instead of parsing JSONL or hallucinating graph traversal, use robot flags for deterministic, dependency-aware outputs with precomputed metrics (PageRank, betweenness, critical path, cycles, HITS, eigenvector, k-core).

**Scope boundary:** bv handles *what to work on* (triage, priority, planning). `br` handles creating, modifying, and closing beads.

**CRITICAL: Use ONLY --robot-* flags. Bare bv launches an interactive TUI that blocks your session.**

#### The Workflow: Start With Triage

**`bv --robot-triage` is your single entry point.** It returns everything you need in one call:
- `quick_ref`: at-a-glance counts + top 3 picks
- `recommendations`: ranked actionable items with scores, reasons, unblock info
- `quick_wins`: low-effort high-impact items
- `blockers_to_clear`: items that unblock the most downstream work
- `project_health`: status/type/priority distributions, graph metrics
- `commands`: copy-paste shell commands for next steps

```bash
bv --robot-triage        # THE MEGA-COMMAND: start here
bv --robot-next          # Minimal: just the single top pick + claim command

# Token-optimized output (TOON) for lower LLM context usage:
bv --robot-triage --format toon
```

Before claiming, verify current state with `br show <id> --json` or `br ready --json`. `recommendations` can include graph-important blocked or assigned work; only `quick_ref.top_picks` and non-empty `claim_command` fields represent claimable work.

#### Other bv Commands

| Command | Returns |
|---------|---------|
| `--robot-plan` | Parallel execution tracks with unblocks lists |
| `--robot-priority` | Priority misalignment detection with confidence |
| `--robot-insights` | Full metrics: PageRank, betweenness, HITS, eigenvector, critical path, cycles, k-core |
| `--robot-alerts` | Stale issues, blocking cascades, priority mismatches |
| `--robot-suggest` | Hygiene: duplicates, missing deps, label suggestions, cycle breaks |
| `--robot-diff --diff-since <ref>` | Changes since ref: new/closed/modified issues |
| `--robot-graph [--graph-format=json\|dot\|mermaid]` | Dependency graph export |

#### Scoping & Filtering

```bash
bv --robot-plan --label backend              # Scope to label's subgraph
bv --robot-insights --as-of HEAD~30          # Historical point-in-time
bv --recipe actionable --robot-plan          # Pre-filter: ready to work (no blockers)
bv --recipe high-impact --robot-triage       # Pre-filter: top PageRank scores
```

### br Commands for Issue Management

```bash
br ready              # Show issues ready to work (no blockers)
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br create --title="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>  # Close multiple issues at once
br sync --flush-only  # Export DB to JSONL
```

### Workflow Pattern

1. **Triage**: Run `bv --robot-triage` to find the highest-impact actionable work
2. **Claim**: Use `br update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `br close <id>`
5. **Sync**: Always run `br sync --flush-only` at session end

### Key Concepts

- **Dependencies**: Issues can block other issues. `br ready` shows only unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers 0-4, not words)
- **Types**: task, bug, feature, epic, chore, docs, question
- **Blocking**: `br dep add <issue> <depends-on>` to add dependencies

### Session Protocol

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync --flush-only    # Export beads changes to JSONL
git commit -m "..."     # Commit everything
git push                # Push to remote
```

<!-- end-bv-agent-instructions -->
