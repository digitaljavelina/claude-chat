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

- [x] **Claude Code skill `/sync-chats`** — invokable from any Claude Code session, wraps `claude-chat.py`, orchestrates the full sync pipeline _(Validated in Phase 2: SKILL.md + AI Labeling)_
- [ ] **Stdlib helper `sync_chats.py`** — deterministic Python helper at `~/.claude-chat/sync_chats.py`. Owns scan/state/atomic-write/filename mechanics. Never calls Claude or MCP. Subcommands: `scan`, `init`, `write`, `status`, `log`.
- [ ] **Delta-sync scanner** — detect sessions in `~/.claude/projects/` that are new or updated since the last sync cursor (mtime+size cheap path, hash slow path)
- [x] **AI-generated labels** — for each session, Claude produces a short title (≤10 words), a 2–3 sentence gist, and 3–5 topical tags. Generated AFTER PII scrub, never before. _(Validated in Phase 2: SKILL.md + AI Labeling)_
- [x] **PII scrub before label** — chat content is scrubbed (general credentials, tokens, emails, IPs) BEFORE any label is generated, so titles and tags can never leak unscrubbed content into frontmatter. Locked ordering: `scrub → label → write`. Verified by canary test. _(Validated in Phase 3: PII Scrub Integration + Crash Safety Polish)_
- [ ] **Obsidian-shaped markdown writer** — files named `<machine>--YYYY-MM-DD--<slug>.md` with YAML frontmatter (title, gist, tags as YAML list, project, session_id, model, token_count, msg_count, machine, hostname, synced_at ISO, needs_review, auto_label_hash sentinel)
- [ ] **Per-machine config** — `~/.claude-chat/config.json` stores the machine short label, set on first run via `/sync-chats --set-label <name>`
- [ ] **Per-machine state file** — `~/.claude-chat/state.json` tracks `last_sync_cursor`, `synced_session_ids`, schema_version. Strictly local (startup assertion that path is not under `Mobile Documents` or `iCloud`). Atomic write (tmp + fsync + rename) with `.bak` fallback.
- [ ] **Three-layer clobber defense** — once a chat is in the vault the skill never touches it again. (1) Primary: `synced_session_ids` set in state.json. (2) Backup: refuse-on-exists filesystem check at write time. (3) Belt-and-suspenders: `auto_label_hash` sentinel in frontmatter (hash of the originally-written body). `needs_review: false` is explicitly NOT used as a hands-off marker.
- [ ] **Idempotent, catch-up-aware execution** — safe to invoke any number of times; processes only deltas; never re-exports a session whose UUID is in `synced_session_ids` even if the vault file is missing
- [ ] **MemPalace bulk-mine integration** — after all writes succeed in a run, shell out once to `mempalace mine <vault>/Chats --mode convos --extract general`. Replaces the per-chat MCP-call plan from the original PROJECT.md. ~10 lines of code.
- [ ] **Multi-machine coexistence** — two Macs syncing to the same iCloud `Chats/` folder never collide because filenames are machine-prefixed and state is strictly local
- [ ] **SessionEnd hook installation** — Claude Code `SessionEnd` hook in `~/.claude/settings.json` invokes `python3 ~/.claude-chat/sync_chats.py --once` after every Claude Code session ends. Event-driven (not scheduled): no launchd, no TCC issues, no headless slash command resolution, sub-second latency from chat-end to vault-write. Sleep-safe trivially (the hook only fires when Claude is in use).
- [ ] **Multi-machine onboarding doc** — short README explaining how to install `sync_chats.py` + the SessionEnd hook + machine label on a second Mac
- [ ] **Sync summary output** — "Synced N new chats, M skipped (already synced), K flagged for review, mempalace mined" at the end of every run
- [ ] **Manual escape hatch** — `/sync-chats` invoked interactively in any Claude session also runs the same pipeline, for ad-hoc catch-up after travel or for AI-quality re-labeling of stub-titled files (Phase 2+)

### Out of Scope

<!-- Explicit boundaries. Reasoning included so we don't re-add them later. -->

- **Mac menu bar app (rumps / SwiftUI)** — the user flipped on this: command line is fine, a skill is better because it can use Claude itself as the summarizer without native-app packaging pain
- **Standalone web UI for browsing/curating chats** — Obsidian is already the search UI (full-text search, graph, tags, Dataview, Bases). Building another one would be rebuilding what Obsidian does better
- **Interactive review queue (`/sync-chats review`)** — auto-labels are written with `needs_review: true` in frontmatter; the user edits titles directly in Obsidian. A Dataview query (`WHERE needs_review`) gives a zero-effort inbox without a separate review command
- **Real-time file watcher (`fsevents`)** — the SessionEnd hook gives effectively instant sync (sub-second from chat end to vault write). A file watcher adds complexity for no additional latency benefit.
- **`launchd` LaunchAgent (originally planned)** — replaced by Claude Code SessionEnd hook (event-driven). Research surfaced that `claude -p "/sync-chats"` does not work in headless mode (Anthropic disables slash commands in `-p`), and event-driven hooks fit the use case better than time-based scheduling: no TCC headaches, no PATH issues, no sleep edge cases, sub-second latency. May be reconsidered as an optional belt-and-suspenders catch-up daemon in a future milestone if event-only proves insufficient.
- **`/schedule` (RemoteTrigger) for sync scheduling** — `/v1/code/triggers` runs in Anthropic's cloud, which has no access to local `~/.claude/projects/`, the local iCloud-mounted vault, or the local state file. Investigated and rejected.
- **Per-chat MemPalace MCP calls** — the MemPalace CLI ships `mempalace mine <dir> --mode convos --extract general`, a purpose-built bulk command verified live on the user's machine. One shell-out at end of run replaces an entire orchestration loop. Per-chat MCP integration is unnecessary scope.
- **Clinical-specific PII patterns (NCT IDs, EU/JMA/chiCTR codes, drug-dose prose, internal Amgen URLs)** — user explicitly confirmed clinical content will not be in these chats. Generic credential/token/email/IP scrubbing remains in scope (still cheap and beneficial), but no clinical-specific augmentation, no per-user clinical canary file, no second-pass LLM scrub.
- **Custom search UI on top of `claude-chat.py`** — same reason as the web UI: Obsidian handles it
- **Dedup logic across machines** — `~/.claude/projects/` is strictly local per Mac, so the two machines have disjoint session sets; no dedup needed
- **State file in iCloud** — two machines writing to the same cursor file would corrupt sync; state must be strictly local. Startup assertion enforces this.
- **Mid-conversation re-titling / retroactive label regeneration** — once a file is written and Michael has edited it, the skill never touches it again. Three-layer defense (see Active items).
- **Rewriting `claude-chat.py`** — it already does 70% of what the skill needs; the skill wraps and composes its existing commands. The only additive change is `export --stdout` (and possibly `protect --scrub-content` pending Phase 1 audit), both small and backwards-compatible.
- **External LLM API for summarization** — the skill runs inside a Claude Code session by definition, so Claude is already the summarizer. No API keys, no prompt infrastructure.

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
- Michael's global CLAUDE.md describes him as a "vibe-coder" who "builds to learn" — this project is both the thing he wants _and_ a learning vehicle for Python idioms, skill authoring, and Claude Code hook configuration
- Michael is a Python beginner (per `CLAUDE.local.md`) — explanations should accompany implementation

**User behavior themes:**

- "I save aggressively to Inbox/ but rarely circle back" (from his global CLAUDE.md) — this project applies the same insight to Claude Code chats: capture everything automatically, let curation happen later through ambient editing rather than an explicit review step
- `Chats/` is a top-level vault folder, not nested under `AI/` — Michael keeps conversations as a first-class vault concept, peer to `daily/`, `Posts/`, `projects/`

**Known issues to address:**

- Sessions in `~/.claude/projects/` are named by UUID — no human can tell what any given file is about without opening it
- Michael uses two Macs but there's currently no way to see which machine a chat came from once exported
- Background sync on a laptop is tricky: original plan assumed `launchd` with `claude -p "/sync-chats"`, but research found Anthropic disables slash commands in headless mode. Resolved by switching to a Claude Code SessionEnd hook (event-driven, fires on every Claude session end, runs in user's local environment with no TCC/PATH/sleep edge cases). The "laptop sleeps" concern dissolves because the hook only fires when Claude is in active use anyway.

## Constraints

- **Tech stack**: Python 3 standard library only for `claude-chat.py` AND for the new `sync_chats.py` helper (preserve zero-deps invariant) — **Why:** existing architectural commitment; keeps install trivial on any new Mac. SKILL.md is the only non-Python artifact and orchestrates via Claude Code's bash blocks.
- **Privacy (general)**: every chat MUST pass through PII scrub BEFORE labeling, BEFORE writing to the vault — **Why:** vault is cloud-synced. Vibe-coding regularly produces credentials, API keys, JWTs, internal URLs, emails, and IP addresses that should not land in iCloud. Frontmatter is the most-indexed surface in Obsidian, so labels generated from unscrubbed content would leak PII into the most visible queryable layer. Locked ordering: `scrub → label → write`. (NOTE: clinical-specific patterns are NOT in scope — user confirmed no clinical content will appear in these chats.)
- **Cross-machine safety**: state files MUST stay local, filenames MUST be machine-prefixed, startup assertion verifies state path is not in `Mobile Documents`/`iCloud` — **Why:** two Macs writing to the same iCloud state file will race and corrupt; machine-prefixed filenames guarantee no write collisions across the two machines (sessions are also disjoint per machine, reinforcing the guarantee)
- **Idempotency**: the skill MUST be safe to run any number of times, at any interval, in any order; never re-exports a session whose UUID is in `synced_session_ids` even if the vault file is missing — **Why:** the SessionEnd hook can fire repeatedly and concurrently. Idempotency turns invocations into hints, not contracts.
- **Reversibility / no clobber**: the skill MUST NOT re-write, re-title, or re-scrub any chat once it exists in the vault. Three independent defenses (state set + refuse-on-exists + auto_label_hash sentinel) — **Why:** Michael edits titles in Obsidian; regeneration would clobber his edits. Single-layer defense is insufficient because state files can be lost.
- **Dependencies**: MemPalace CLI must be installed on each machine that runs the skill (degrades gracefully if missing — log warning, continue) — **Why:** Goal B (context-for-future-Claude) depends on it, but vault writes must succeed even when MemPalace is unavailable
- **Budget / timeline**: side project, no deadline — quality over speed. But every phase should produce something testable end-to-end
- **Python familiarity**: Michael is a Python beginner; code should err on the side of readable over clever, with inline explanation of standard library idioms used

## Key Decisions

| Decision                                                                                                                      | Rationale                                                                                                                                                                                                                                                                                                                                                                          | Outcome   |
| ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| Deliver as a Claude Code skill, not a Mac menu bar app or website                                                             | Skill runs inside Claude → Claude is the summarizer for free, no packaging pain, stays in terminal where Michael is already comfortable                                                                                                                                                                                                                                            | — Pending |
| Wrap `claude-chat.py` rather than replace it                                                                                  | 70% of the needed functionality already exists (list, export, protect, extract); rewriting would trash working code and the zero-deps invariant                                                                                                                                                                                                                                    | — Pending |
| Auto-label on export, edit in Obsidian                                                                                        | Obsidian is the review UI; Dataview query on `needs_review: true` gives a zero-effort inbox without building a separate review command                                                                                                                                                                                                                                             | — Pending |
| Always run `protect` before writing to the vault                                                                              | iCloud-synced vault + clinical/regulatory context + credentials = leakage is not recoverable                                                                                                                                                                                                                                                                                       | — Pending |
| Filename convention: `<machine>--YYYY-MM-DD--<slug>.md` (flat folder, machine prefix)                                         | Flat folder is easiest to navigate; machine prefix makes source Mac visible at a glance without clicking in; date sorts chronologically within each machine                                                                                                                                                                                                                        | — Pending |
| Machine label set by user on first run, not auto-detected                                                                     | Short clean labels (`mbp`, `studio`) beat whatever macOS calls the machine; stored in `~/.claude-chat/config.json` per machine                                                                                                                                                                                                                                                     | — Pending |
| State file local-only at `~/.claude-chat/state.json`, never in iCloud                                                         | Two Macs writing to the same state file in iCloud would race and corrupt; strict locality guarantees safety                                                                                                                                                                                                                                                                        | — Pending |
| Event-driven sync via Claude Code SessionEnd hook (NOT launchd, NOT `/schedule`)                                              | Research found `claude -p "/sync-chats"` is disabled in headless mode (Anthropic restriction). `/schedule`'s RemoteTrigger runs in cloud with no local file access. SessionEnd hook fires after every Claude session in the user's local environment — sub-second latency, no TCC/PATH issues, no sleep edge cases, trivially sleep-safe. Replaces the entire launchd-plist phase. | — Pending |
| MemPalace bulk-mine via `mempalace mine --mode convos`, NOT per-chat MCP calls                                                | Verified live on user's machine: `mempalace mine <vault>/Chats --mode convos --extract general` is a purpose-built bulk command. One shell-out at end of run replaces a per-session MCP loop with retry logic. Drastically simpler.                                                                                                                                                | — Pending |
| PII scrub ordering locked: `scrub → label → write`                                                                            | If labeling runs first, the title and tags Claude generates can contain unscrubbed PII — and frontmatter is the most-indexed surface in Obsidian (tag pane, Dataview, graph, search). Scrubbing the body alone is insufficient. Verified by canary test.                                                                                                                           | — Pending |
| Three-layer clobber defense: `synced_session_ids` set + refuse-on-exists + `auto_label_hash` frontmatter sentinel             | Single-layer defense is insufficient. State files can be lost. `needs_review: false` is explicitly REJECTED as a hands-off marker because users casually flip booleans. The hash sentinel is invisible and only the skill knows how to read it.                                                                                                                                    | — Pending |
| Drop clinical-specific PII patterns (NCT, EU/JMA/chiCTR, drug-dose prose)                                                     | User confirmed clinical content will not appear in these chats. Generic credential/token/email/IP scrubbing is still in scope (cheap and beneficial). Removing clinical-specific work meaningfully shrinks Phase 3.                                                                                                                                                                | — Pending |
| Phase 1 includes a `protect` command audit before any other Phase 3 work begins                                               | PROJECT.md assumed `claude-chat.py protect` scrubs content; research surfaced this is not yet verified — `protect` may only manage `settings.json` auto-deletion. If content scrubbing is missing, Phase 1 adds a small `protect --scrub-content` mode (~30 lines, backwards-compatible).                                                                                          | — Pending |
| Three-tier component split: SKILL.md (semantic) + `sync_chats.py` (deterministic stdlib) + `claude-chat.py` (existing engine) | Clean separation: Claude makes title/tag decisions inside the skill, the helper does atomic writes and state mechanics, the existing CLI does JSONL parsing and rendering. Subprocess + JSON over stdout, never `import` (the hyphen in `claude-chat.py` blocks normal Python imports).                                                                                            | — Pending |
| One summary memory per chat in MemPalace (via bulk mine)                                                                      | Bulk mine handles this automatically by mining each .md file in `Chats/`. We don't need to control granularity per call.                                                                                                                                                                                                                                                           | — Pending |

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

_Last updated: 2026-04-13 after Phase 2 completion — `/sync-chats` skill at `~/.claude/skills/sync-chats/SKILL.md` with full scan → per-session label → write orchestration, 4 few-shot examples, kebab-case `low-signal`/`multi-topic` tags, `make_stub_label` fallback, `json.dumps()` pipe safety. 97 tests passing (62 Phase 2 + 35 Phase 1). E2E verified live in a Claude Code session._
