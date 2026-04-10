# Requirements: Claude Chat — `/sync-chats` Skill Milestone

**Defined:** 2026-04-10
**Core Value:** Every Claude Code conversation Michael has should become a titled, searchable, PII-scrubbed artifact in his Obsidian vault, so his past chats are browsable by gist rather than by cryptic session ID, and future Claude sessions can learn from his history.

> v1 here means **the first shippable version of the `/sync-chats` skill** — not v1 of `claude-chat.py` (which is already shipped). v1 of the skill = the SessionEnd hook is installed, chats appear in the vault automatically, and MemPalace gets fed.

## v1 Requirements

### CORE — Sync Pipeline & State

The deterministic, stdlib-only foundation. No AI, no MCP. This layer must be testable in isolation.

- [ ] **CORE-01**: User can run `python3 ~/.claude-chat/sync_chats.py scan` and see a list of session UUIDs in `~/.claude/projects/` that have not yet been synced (delta detection via mtime + size + content hash)
- [ ] **CORE-02**: User can run `python3 ~/.claude-chat/sync_chats.py write <session_id>` and a properly-named markdown file appears in the vault `Chats/` folder with valid YAML frontmatter
- [ ] **CORE-03**: `sync_chats.py` writes `~/.claude-chat/state.json` atomically (tmp + fsync + rename) with a `.bak` fallback, including a `schema_version` field
- [ ] **CORE-04**: `sync_chats.py` refuses to start if `~/.claude-chat/` resolves to a path containing `Mobile Documents` or `iCloud` (startup assertion that state is local)
- [ ] **CORE-05**: User can run `python3 ~/.claude-chat/sync_chats.py init --label <name>` to set the per-machine short label (e.g., `mbp`, `studio`), stored in `~/.claude-chat/config.json`
- [ ] **CORE-06**: Filenames follow the convention `<machine>--YYYY-MM-DD--<slug>.md` where `slug` is a kebab-cased title; verified by a unit test that no two machines could collide
- [ ] **CORE-07**: When the same `sync_chats.py` invocation is run twice in a row with no new sessions, the second run produces zero new files (idempotency property)
- [ ] **CORE-08**: When `sync_chats.py` is run after a session UUID has already been recorded in `synced_session_ids`, that session is NEVER re-exported, even if the corresponding vault file is missing (clobber defense layer 1)
- [ ] **CORE-09**: When `sync_chats.py` is run and the target vault filename already exists, the write is refused (clobber defense layer 2)
- [ ] **CORE-10**: Frontmatter includes an `auto_label_hash` sentinel — a hash of the originally-written body — that future runs can use to detect "is this still an unedited auto-labeled file?" (clobber defense layer 3)
- [ ] **CORE-11**: A new `export --stdout` flag is added to `claude-chat.py` so `sync_chats.py` can pipe rendered markdown without touching disk; backwards-compatible
- [ ] **CORE-12**: A `cmd_protect()` audit is performed in Phase 1 to determine whether `claude-chat.py protect` actually scrubs content; if not, a `protect --scrub-content` mode is added (~30 lines, backwards-compatible)
- [ ] **CORE-13**: `sync_chats.py status` prints sync state summary: machine label, last run timestamp, count of synced sessions, count of pending sessions

### LABEL — AI Title, Gist, Tags

The Claude-driven semantic layer. Lives inside SKILL.md, not `sync_chats.py`.

- [ ] **LABEL-01**: A Claude Code skill exists at `~/.claude/skills/sync-chats/SKILL.md` with proper frontmatter (`name`, `description`, `disable-model-invocation: true`, `allowed-tools` whitelist, `argument-hint`)
- [ ] **LABEL-02**: When invoked interactively (`/sync-chats`), the skill scans for new sessions, generates labels for each, and writes them to the vault using `sync_chats.py write`
- [ ] **LABEL-03**: AI-generated title is ≤10 words, verb-leading where applicable, captures the gist of the conversation
- [ ] **LABEL-04**: AI-generated gist is 2–3 sentences in past tense summarizing what happened in the chat
- [ ] **LABEL-05**: AI-generated tags are 3–5 kebab-case strings, stored as a YAML list (not comma-separated, not inline `#tag`) so Dataview can query them
- [ ] **LABEL-06**: A `coherence_score` (1–5) is generated alongside each label and stored in frontmatter for downstream filtering
- [ ] **LABEL-07**: Edge cases are handled by tags: ultra-short sessions (< 500 chars) are skipped entirely, low-signal sessions (mostly tool calls) get `low_signal` tag, multi-topic sessions get `multi_topic` tag
- [ ] **LABEL-08**: If JSON parsing of the AI's label response fails, the skill falls back to a deterministic stub label (`title = first 8 words of first user message`) rather than crashing the run
- [ ] **LABEL-09**: Phase 1 / Phase 2 boundary: `sync_chats.py write` accepts label JSON via stdin or flags so labels can be supplied either by the skill (Phase 2+) or by stub-label generation (Phase 1)

### PRIV — PII Scrub & Privacy

Generic credential and sensitive-content scrubbing. NO clinical-specific patterns (user confirmed out of scope).

- [ ] **PRIV-01**: Pipeline ordering is locked as `load → scrub → label → write`; this ordering is enforced by code structure, not convention
- [ ] **PRIV-02**: Scrub catches generic credentials: API keys, JWTs (eyJ prefix), GitHub tokens of all variants (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), AWS access keys, generic Bearer tokens, basic auth strings
- [ ] **PRIV-03**: Scrub catches general PII: email addresses, IPv4/IPv6 addresses, phone numbers (US format)
- [ ] **PRIV-04**: A canary test file with synthetic PII (fake email, fake JWT, fake API key, fake GitHub PAT, fake IP) is fed through the full pipeline and the resulting markdown + frontmatter is grep-checked for any of the canaries; canary test runs in CI
- [ ] **PRIV-05**: Fail-open-with-flag: if scrub is uncertain about a piece of content, the chat is still written but tagged `needs_review: true` and `privacy_review: uncertain` in frontmatter. NEVER refuse to write a chat.
- [ ] **PRIV-06**: Scrub log messages report only the pattern name and char count of redacted content, never the matched substring (so logs don't leak what was scrubbed)

### MEM — MemPalace Integration

- [ ] **MEM-01**: After all sessions in a sync run have been written to the vault, `sync_chats.py` (or the skill) shells out once to `mempalace mine <vault>/Chats --mode convos --extract general`
- [ ] **MEM-02**: If the `mempalace` CLI is not installed or fails, the sync run continues and emits a warning; vault writes must succeed regardless of MemPalace state
- [ ] **MEM-03**: Sync summary output includes a `mempalace_mined: true|false|skipped` line so the user can see whether MemPalace ran on each invocation

### HOOK — Event-Driven Scheduling

Replaces the originally-planned launchd LaunchAgent. Uses Claude Code's native hook system.

- [ ] **HOOK-01**: A `SessionEnd` hook is installed in `~/.claude/settings.json` that invokes `python3 ~/.claude-chat/sync_chats.py --once` after every Claude Code session ends
- [ ] **HOOK-02**: The hook fires within seconds of session end, with sub-second latency from chat-end to vault-write
- [ ] **HOOK-03**: The hook is safe to run repeatedly (idempotent property is enforced upstream by CORE-07/08)
- [ ] **HOOK-04**: Manual escape hatch: user can run `/sync-chats` interactively in any Claude session to force a catch-up sync
- [ ] **HOOK-05**: A short README documents how to install `sync_chats.py` + the SessionEnd hook + machine label on a second Mac (multi-machine onboarding)

### OBSERV — Observability

So Michael can answer "what happened on the last sync run?" without reading source.

- [ ] **OBSERV-01**: Every sync run produces a summary line: `Synced N new chats, M skipped (already-synced), K flagged for review, mempalace_mined: <status>`
- [ ] **OBSERV-02**: A local log at `~/.claude-chat/sync.log` records timestamped entries for every run (start, sessions processed, errors)
- [ ] **OBSERV-03**: A `last_run.json` at `~/.claude-chat/last_run.json` captures the most recent run's stats in machine-readable form
- [ ] **OBSERV-04**: `sync_chats.py status` reads `last_run.json` and displays a human summary

## v2 Requirements

Acknowledged but deferred. Tracked so we don't lose them.

### Future Catch-Up Safety Net

- **HOOK-V2-01**: Optional `launchd` LaunchAgent for time-based catch-up if the SessionEnd hook proves insufficient (e.g., user goes weeks without using Claude on a machine but wants the vault current anyway)

### Cross-Machine Stats

- **OBSERV-V2-01**: `sync_chats.py stats` aggregates Dataview-style counts across `Chats/` ("52 from mbp, 14 from studio, 8 flagged for review")
- **OBSERV-V2-02**: Bundled Dataview query templates dropped into the vault for "needs_review inbox", "by-machine", "by-tag", "recent"

### Label Quality Iteration

- **LABEL-V2-01**: User can run `/sync-chats relabel <session_id>` to regenerate labels for one specific chat (with heavy guards: only on auto-labeled files where `auto_label_hash` matches current body)
- **LABEL-V2-02**: User can configure prompt template for label generation (currently hardcoded in SKILL.md)

### Per-Project Frontmatter

- **CORE-V2-01**: Per-project frontmatter overrides (e.g., add a `project_type: blog` tag to all chats from `~/Documents/Blog/` projects)

## Out of Scope

Explicit exclusions documented to prevent scope creep. Most reasoning lives in PROJECT.md Out of Scope; this is a tighter table.

| Feature                                                                                             | Reason                                                                                                                                          |
| --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Mac menu bar app (rumps / SwiftUI)                                                                  | Skill + Obsidian fit better; no native packaging pain                                                                                           |
| Standalone web UI for browsing/curating chats                                                       | Obsidian IS the search UI (Dataview, Bases, graph, full-text)                                                                                   |
| Interactive review queue command (`/sync-chats review`)                                             | Obsidian Dataview query on `needs_review: true` is the review UI                                                                                |
| Real-time file watcher (fsevents)                                                                   | SessionEnd hook gives effectively-instant sync; file watcher adds complexity for no latency benefit                                             |
| `launchd` LaunchAgent (originally planned)                                                          | Replaced by SessionEnd hook (event-driven, no TCC/PATH/sleep edge cases). Anthropic disables `claude -p "/sync-chats"` in headless mode anyway. |
| `/schedule` (RemoteTrigger) for sync scheduling                                                     | Remote triggers run in Anthropic's cloud, no access to local files                                                                              |
| Per-chat MemPalace MCP calls                                                                        | `mempalace mine --mode convos` is a verified bulk command — replaces the entire orchestration loop                                              |
| Clinical-specific PII patterns (NCT IDs, EU/JMA/chiCTR codes, drug-dose prose, internal Amgen URLs) | User explicitly confirmed clinical content will not appear in these chats                                                                       |
| Per-user clinical canary file                                                                       | Same — clinical PII is out of scope                                                                                                             |
| Optional second-pass LLM scrub                                                                      | Was a clinical-edge-case mitigation; not needed for general PII                                                                                 |
| Custom search UI on top of `claude-chat.py`                                                         | Obsidian handles it                                                                                                                             |
| Dedup logic across machines                                                                         | Sessions are disjoint per machine (`~/.claude/projects/` is local)                                                                              |
| State file in iCloud                                                                                | Two machines would race; locked to local                                                                                                        |
| Mid-conversation re-titling / retroactive label regeneration                                        | Three-layer clobber defense ensures the skill never touches a chat once written                                                                 |
| Rewriting `claude-chat.py`                                                                          | 70% of needed functionality already exists; only `export --stdout` and possibly `protect --scrub-content` are added                             |
| External LLM API for summarization (Ollama, OpenAI, etc.)                                           | Claude is the summarizer for free inside the skill                                                                                              |
| Ephemeral / throwaway chat detection beyond char count                                              | Char-count threshold (< 500) is sufficient for v1                                                                                               |
| Search across MemPalace from the skill itself                                                       | The user queries MemPalace via its existing tools, not via `/sync-chats`                                                                        |

## Traceability

All 40 v1 requirements mapped to phases during roadmap creation (note: the original "38 total" count in this file was an undercount; actual count is 40 across CORE:13 + LABEL:9 + PRIV:6 + MEM:3 + HOOK:5 + OBSERV:4).

| Requirement | Phase   | Status  |
| ----------- | ------- | ------- |
| CORE-01     | Phase 1 | Pending |
| CORE-02     | Phase 1 | Pending |
| CORE-03     | Phase 1 | Pending |
| CORE-04     | Phase 1 | Pending |
| CORE-05     | Phase 1 | Pending |
| CORE-06     | Phase 1 | Pending |
| CORE-07     | Phase 1 | Pending |
| CORE-08     | Phase 1 | Pending |
| CORE-09     | Phase 1 | Pending |
| CORE-10     | Phase 1 | Pending |
| CORE-11     | Phase 1 | Pending |
| CORE-12     | Phase 1 | Pending |
| CORE-13     | Phase 1 | Pending |
| LABEL-01    | Phase 2 | Pending |
| LABEL-02    | Phase 2 | Pending |
| LABEL-03    | Phase 2 | Pending |
| LABEL-04    | Phase 2 | Pending |
| LABEL-05    | Phase 2 | Pending |
| LABEL-06    | Phase 2 | Pending |
| LABEL-07    | Phase 2 | Pending |
| LABEL-08    | Phase 2 | Pending |
| LABEL-09    | Phase 1 | Pending |
| PRIV-01     | Phase 3 | Pending |
| PRIV-02     | Phase 3 | Pending |
| PRIV-03     | Phase 3 | Pending |
| PRIV-04     | Phase 3 | Pending |
| PRIV-05     | Phase 3 | Pending |
| PRIV-06     | Phase 3 | Pending |
| MEM-01      | Phase 4 | Pending |
| MEM-02      | Phase 4 | Pending |
| MEM-03      | Phase 4 | Pending |
| HOOK-01     | Phase 5 | Pending |
| HOOK-02     | Phase 5 | Pending |
| HOOK-03     | Phase 5 | Pending |
| HOOK-04     | Phase 5 | Pending |
| HOOK-05     | Phase 5 | Pending |
| OBSERV-01   | Phase 5 | Pending |
| OBSERV-02   | Phase 5 | Pending |
| OBSERV-03   | Phase 5 | Pending |
| OBSERV-04   | Phase 5 | Pending |

**Coverage:** 40 mapped, 0 unmapped ✓

**Per-phase counts:**

- Phase 1 (Scanner + State + Stub-Label Write Pipeline): 14 requirements
- Phase 2 (SKILL.md + AI Labeling): 8 requirements
- Phase 3 (PII Scrub + Crash Safety Polish): 6 requirements
- Phase 4 (MemPalace Bulk-Mine Integration): 3 requirements
- Phase 5 (SessionEnd Hook + Observability + Multi-Machine Onboarding): 9 requirements

---

_Requirements defined: 2026-04-10_
_Last updated: 2026-04-10 — traceability populated by gsd-roadmapper (all 40 requirements mapped to 5 phases)_
