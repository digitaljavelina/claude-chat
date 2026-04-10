# Claude Chat — Session Archive & Curator

## What This Is

A personal tool for turning cryptic Claude Code session files (`~/.claude/projects/*.jsonl`) into a browsable, searchable Obsidian library of human-titled conversations, and into a queryable memory that future Claude sessions can draw on. Today it is a zero-dependency Python CLI (`claude-chat.py`) for listing, searching, exporting, backing up, and scrubbing PII from Claude Code sessions. The next milestone turns it into an always-on curator that quietly syncs every Claude Code conversation Michael has — on either of his Macs — into his Obsidian vault, each one pre-titled and tagged by AI, ready to edit or forget.

## Core Value

**Every Claude Code conversation Michael has should become a titled, searchable, PII-scrubbed artifact in his Obsidian vault, so his past chats are browsable by gist rather than by cryptic session ID, and future Claude sessions can learn from his history.**

If everything else fails, this must work: chats flow into `~/.../Documents/Chats/` automatically, labeled well enough that Michael can find "that conversation where I debugged the RSS service" without opening files one by one.

## Requirements

### Validated

<!-- Already shipped in claude-chat.py — inferred from codebase map (2026-04-09). -->

- ✓ `list` — enumerate sessions across all projects with preview, sort by date/size, filter by project — existing
- ✓ `search` — keyword search across session contents — existing
- ✓ `export` — render a session to markdown, HTML, plain text, or LaTeX — existing
- ✓ `backup` — copy session JSONL files to a backup directory — existing
- ✓ `stats` — aggregate usage statistics across sessions — existing
- ✓ `extract` — pull specific content types (code blocks, tool calls, etc.) from sessions — existing
- ✓ `serve` — embedded HTTP server with HTML browsing UI on localhost — existing
- ✓ `protect` — scrub PII/credentials from session content — existing
- ✓ Interactive REPL mode for exploratory use — existing
- ✓ Lazy parsing (metadata eager, full content on-demand) for responsive listing — existing
- ✓ Zero external dependencies — Python standard library only — existing architectural commitment

### Active

<!-- Scope for the current milestone: the `/sync-chats` Claude Code skill. -->

- [ ] **Claude Code skill `/sync-chats`** — invokable from any Claude Code session, wraps `claude-chat.py`, orchestrates the full sync pipeline
- [ ] **Delta-sync scanner** — detect sessions in `~/.claude/projects/` that are new or updated since the last sync cursor
- [ ] **AI-generated labels** — for each session, Claude produces a short title (≤10 words), a 2-3 sentence gist, and 3-5 topical tags
- [ ] **PII scrub pass** — every exported chat passes through the existing `protect` command before it reaches the vault
- [ ] **Obsidian-shaped markdown writer** — produces files with filename `<machine>--YYYY-MM-DD--<slug>.md` and rich frontmatter (title, gist, tags, project, session_id, model, token_count, msg_count, machine, hostname, synced_at, needs_review)
- [ ] **Per-machine config** — `~/.claude-chat/config.json` stores the machine short label, set on first run via `/sync-chats --set-label <name>`
- [ ] **Per-machine state file** — `~/.claude-chat/state.json` tracks `last_sync_cursor`, `synced_session_ids`, kept strictly local (never in iCloud)
- [ ] **Idempotent, catch-up-aware execution** — safe to invoke any number of times; processes only deltas; handles multi-day sleep gaps in one run
- [ ] **MemPalace integration** — each synced chat becomes exactly one summary memory fed to MemPalace via the existing MCP tools
- [ ] **Sleep-safe scheduling** — `launchd` LaunchAgent with `StartInterval: 3600` + `RunAtLoad: true`, invoking `claude -p "/sync-chats"` — naturally catches up on lid-open because the skill is idempotent
- [ ] **Multi-machine coexistence** — two Macs syncing to the same iCloud `Chats/` folder never collide because filenames are machine-prefixed and state is strictly local
- [ ] **Sync summary output** — "Synced N new chats, flagged M for review" at the end of every run
- [ ] **Manual catch-up escape hatch** — running `/sync-chats` by hand after travel processes everything missed since the last cursor

### Out of Scope

<!-- Explicit boundaries. Reasoning included so we don't re-add them later. -->

- **Mac menu bar app (rumps / SwiftUI)** — the user flipped on this: command line is fine, a skill is better because it can use Claude itself as the summarizer without native-app packaging pain
- **Standalone web UI for browsing/curating chats** — Obsidian is already the search UI (full-text search, graph, tags, Dataview, Bases). Building another one would be rebuilding what Obsidian does better
- **Interactive review queue (`/sync-chats review`)** — auto-labels are written with `needs_review: true` in frontmatter; the user edits titles directly in Obsidian. A Dataview query (`WHERE needs_review`) gives a zero-effort inbox without a separate review command
- **Real-time file watcher (`fsevents`)** — hourly delta-sync is fresh enough. A file watcher adds complexity and still has to handle sleep/wake, offering little benefit over `launchd + RunAtLoad`
- **Custom search UI on top of `claude-chat.py`** — same reason as the web UI: Obsidian handles it
- **Dedup logic across machines** — `~/.claude/projects/` is strictly local per Mac, so the two machines have disjoint session sets; no dedup needed
- **State file in iCloud** — two machines writing to the same cursor file would corrupt sync; state must be strictly local
- **Mid-conversation re-titling / retroactive label regeneration** — once a file is written and Michael has edited it, the skill never touches it again (tracked by `session_id` in state)
- **Rewriting `claude-chat.py`** — it already does 70% of what the skill needs; the skill wraps and composes its existing commands
- **External LLM API for summarization** — the skill runs inside a Claude Code session by definition, so Claude is already the summarizer. No API keys, no prompt infrastructure

## Context

**Technical environment:**

- macOS (Darwin 25.x), Python 3 standard library only for `claude-chat.py`
- Claude Code is the primary runtime for the skill; MCP MemPalace server is already installed and operational
- Obsidian vault is iCloud-synced across Michael's two Macs; path: `/Users/michaelhenry/Library/Mobile Documents/iCloud~md~obsidian/Documents/`
- Target folder: `Chats/` (already exists at vault root, currently empty)
- Existing codebase: single-file `claude-chat.py` (~1500 lines), well-layered (data model → discovery → commands → exporters → web UI), lazy-parsing, zero deps — see `.planning/codebase/ARCHITECTURE.md`

**Relevant prior work:**

- Michael has already mapped this codebase with `/gsd-map-codebase` (2026-04-09); artifacts live in `.planning/codebase/`
- Michael is a Claude Code power user and physician-turned-clinical-research-MD at Amgen — he uses Claude Code across clinical informatics, blog writing (Digital Javelina), homelab IaC, iOS side projects, and regulatory work. The variety of contexts is exactly what makes chronological titling hard and AI summarization valuable
- Michael's global CLAUDE.md describes him as a "vibe-coder" who "builds to learn" — this project is both the thing he wants _and_ a learning vehicle for Python idioms, skill authoring, and `launchd` scheduling
- Michael is a Python beginner (per `CLAUDE.local.md`) — explanations should accompany implementation

**User behavior themes:**

- "I save aggressively to Inbox/ but rarely circle back" (from his global CLAUDE.md) — this project applies the same insight to Claude Code chats: capture everything automatically, let curation happen later through ambient editing rather than an explicit review step
- `Chats/` is a top-level vault folder, not nested under `AI/` — Michael keeps conversations as a first-class vault concept, peer to `daily/`, `Posts/`, `projects/`

**Known issues to address:**

- Sessions in `~/.claude/projects/` are named by UUID — no human can tell what any given file is about without opening it
- Michael uses two Macs but there's currently no way to see which machine a chat came from once exported
- Running a scheduled job on a laptop that sleeps frequently requires the job to be idempotent and catch-up-aware, not fire-and-forget

## Constraints

- **Tech stack**: Python 3 standard library only for `claude-chat.py` (preserve zero-deps invariant); skill is shell-scripted or markdown-with-bash-blocks, orchestrated by Claude Code runtime — **Why:** existing architectural commitment; keeps install trivial on any new Mac
- **Privacy**: every chat MUST pass through the `protect` command before landing in the iCloud vault — **Why:** vault is cloud-synced; chats contain regulatory work, patient-adjacent discussion, credentials, and side-project secrets. Leakage is not recoverable
- **Cross-machine safety**: state files MUST stay local, filenames MUST be machine-prefixed — **Why:** two Macs writing to the same iCloud state file will race and corrupt; machine-prefixed filenames guarantee no write collisions across the two machines
- **Idempotency**: the skill MUST be safe to run any number of times, at any interval, in any order — **Why:** laptop sleep/wake means scheduled runs are unreliable; idempotency turns the schedule into a hint rather than a contract
- **Reversibility**: the skill MUST NOT re-write, re-title, or re-scrub any chat once it exists in the vault — **Why:** Michael edits titles in Obsidian; regeneration would clobber his edits
- **Dependencies**: MemPalace MCP server must be installed and configured on each machine that runs the skill — **Why:** Goal B (context-for-future-Claude) depends on it
- **Budget / timeline**: side project, no deadline — quality over speed. But every phase should produce something testable end-to-end
- **Python familiarity**: Michael is a Python beginner; code should err on the side of readable over clever, with inline explanation of standard library idioms used

## Key Decisions

| Decision                                                                                      | Rationale                                                                                                                                                   | Outcome   |
| --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| Deliver as a Claude Code skill, not a Mac menu bar app or website                             | Skill runs inside Claude → Claude is the summarizer for free, no packaging pain, stays in terminal where Michael is already comfortable                     | — Pending |
| Wrap `claude-chat.py` rather than replace it                                                  | 70% of the needed functionality already exists (list, export, protect, extract); rewriting would trash working code and the zero-deps invariant             | — Pending |
| Auto-label on export, edit in Obsidian                                                        | Obsidian is the review UI; Dataview query on `needs_review: true` gives a zero-effort inbox without building a separate review command                      | — Pending |
| Always run `protect` before writing to the vault                                              | iCloud-synced vault + clinical/regulatory context + credentials = leakage is not recoverable                                                                | — Pending |
| Filename convention: `<machine>--YYYY-MM-DD--<slug>.md` (flat folder, machine prefix)         | Flat folder is easiest to navigate; machine prefix makes source Mac visible at a glance without clicking in; date sorts chronologically within each machine | — Pending |
| Machine label set by user on first run, not auto-detected                                     | Short clean labels (`mbp`, `studio`) beat whatever macOS calls the machine; stored in `~/.claude-chat/config.json` per machine                              | — Pending |
| State file local-only at `~/.claude-chat/state.json`, never in iCloud                         | Two Macs writing to the same state file in iCloud would race and corrupt; strict locality guarantees safety                                                 | — Pending |
| Idempotent delta-sync, scheduled via `launchd` with `StartInterval: 3600` + `RunAtLoad: true` | Laptop sleep makes fire-and-forget schedules unreliable; idempotency + RunAtLoad turns the schedule into a hint and catches up on wake                      | — Pending |
| One summary memory per chat in MemPalace                                                      | Balance retrieval precision with storage cost; finer granularity explodes memory count, coarser loses query accuracy                                        | — Pending |
| Hourly cadence                                                                                | Fresh enough to feel live, light enough to be invisible                                                                                                     | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):

1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):

1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---

_Last updated: 2026-04-10 after initialization_
