# Project Research Summary

**Project:** `/sync-chats` Claude Code skill (brownfield milestone on `claude-chat.py`)
**Domain:** Claude Code session archival + Obsidian knowledge curation + MemPalace memory feed + sleep-safe macOS scheduling
**Researched:** 2026-04-10
**Confidence:** HIGH overall, with four named gaps concentrated in headless invocation, `protect` behavior, MemPalace surface, and Sequoia+ TCC

---

## Executive Summary

The four research tracks converged on a clear picture: `/sync-chats` is a thin orchestration layer over an existing, well-built `claude-chat.py` CLI. The hard parts (JSONL parsing, markdown rendering, PII scrubbing, lazy loading) are already solved; the new surface area is a deterministic Python helper (`sync_chats.py`) plus a Claude Code skill (`SKILL.md`) that together: detect session deltas against a local state file, render + scrub each delta to machine-prefixed markdown in the iCloud Obsidian vault, feed summaries to MemPalace, and run on a sleep-safe launchd schedule across two Macs. Most of the design falls cleanly out of a single invariant — **disjoint per-machine sessions + sticky local state + atomic per-session commits** — which makes multi-machine coexistence, crash safety, and idempotency nearly free.

But research surfaced **three non-negotiable corrections to PROJECT.md as written**, and they need to be resolved before Phase 1 begins. (1) `claude -p "/sync-chats"` does not work: Anthropic explicitly disables slash commands and user-invocable skills in headless mode. The launchd plan requires a new path. (2) PII scrub must run BEFORE AI labeling, not after, because the title and tags Claude generates become the most-indexed part of the file — labeling unscrubbed content leaks PII into frontmatter. The correct ordering is locked as `scrub → label → write`. (3) User-edit protection against clobber needs three independent layers (`synced_session_ids` set + refuse-on-exists filesystem check + `auto_label_hash` frontmatter sentinel); `needs_review: false` is explicitly rejected as a hands-off marker because users unset it casually.

The GOOD news: the competitive landscape scan found no existing tool that combines delta-sync + AI labels + PII scrub + multi-machine coexistence + memory feed. `claude-vault` is closest but explicitly punts on multi-machine and requires Ollama. The `StartInterval: 3600 + RunAtLoad: true` launchd approach is verified correct for sleeping laptops (launchd coalesces missed firings into one catch-up run on wake). MemPalace has a purpose-built bulk-mining command (`mempalace mine <dir> --mode convos --extract general`) verified live on the user's machine, which drastically simplifies integration: write all markdown files first, run one bulk mine at the end, rather than orchestrating per-chat MCP calls. Architectural decisions are HIGH confidence; open questions are concentrated around (a) headless path resolution, (b) actual behavior of `claude-chat.py protect`, (c) MemPalace MCP tool surface beyond the bulk command, and (d) macOS Sequoia+ TCC behavior on launchd-invoked processes touching iCloud paths.

---

## Cross-Cutting Findings (READ FIRST)

These emerged from multiple research tracks and materially change the PROJECT.md plan. The roadmapper MUST surface these to the user during requirements.

### 1. HEADLESS BLOCKER — `claude -p "/sync-chats"` does not work

**Source:** STACK.md §1 (verified against official Anthropic headless docs)

Anthropic's docs explicitly state: _"User-invoked skills like `/commit` and built-in commands are only available in interactive mode. In `-p` mode, describe the task you want to accomplish instead."_

This breaks the PROJECT.md plan of "launchd LaunchAgent invoking `claude -p '/sync-chats'`." Three plausible alternatives emerged, with tradeoffs — the user must choose during requirements:

| Option                                              | How It Works                                                                                                                                                                                                   | Upside                                                                                                  | Downside                                                                                                                                                               |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **(a) Interactive-only**                            | Drop launchd entirely. User types `/sync-chats` in a running Claude session when they feel like it.                                                                                                            | Simplest; zero new infra; AI labels are free and high-quality; no TCC/PATH/sleep bugs.                  | No "ambient catch-up" — if Michael forgets for a week, nothing syncs. Defeats the "set it and forget it" goal.                                                         |
| **(b) Plain Python wrapper + interactive re-label** | launchd invokes `sync_chats.py --headless` which does the full sync using heuristic (non-AI) titles. A separate interactive `/sync-chats` can be run ad hoc to upgrade stub-titled files to AI-quality titles. | Ambient catch-up works without going through Claude; deterministic, debuggable; no slash command issue. | Two code paths; initial titles are mediocre until the user manually re-labels.                                                                                         |
| **(c) Hybrid — provisional then upgrade**           | Headless wrapper writes provisional heuristic titles plus `needs_ai_label: true` frontmatter flag. Interactive `/sync-chats` scans for that flag and upgrades flagged files using Claude in-session.           | Best of both: ambient catch-up AND eventual AI quality. Uses Obsidian-as-queue naturally.               | Most complex; files get touched twice (once at initial write, once on upgrade), which violates the "never touch a chat twice" invariant and needs careful guard logic. |

**Recommendation:** Leave this for the user to decide during requirements. Do not pre-pick in the roadmap. Each option changes phase structure meaningfully.

### 2. MEMPALACE SIMPLIFICATION — use the bulk mine command, not per-chat MCP calls

**Source:** STACK.md (verified live on the user's machine)

`mempalace mine <dir> --mode convos --extract general` is a purpose-built bulk-mining command that scans a directory of conversation markdown files and extracts general memories. The PROJECT.md plan of "one summary memory per chat via per-chat MCP calls" should be replaced with: write all markdown files first, then run ONE bulk mine at the end of the sync run.

**Why this is better:**

- Simpler orchestration (no per-chat MCP failure handling)
- Fewer failure modes (mine is idempotent; re-running just re-processes)
- Frees roadmap budget previously allocated to per-chat MemPalace retry logic
- Doesn't force SKILL.md into a per-session loop with MCP calls mid-loop

**Phase impact:** MemPalace integration becomes "shell out to `mempalace mine` after all writes succeed" — a 10-line addition, not a phase of work.

### 3. SCRUB ORDER — `scrub → label → write` is locked

**Source:** PITFALLS.md #10 (CATASTROPHIC)

If Claude labels unscrubbed content, the resulting title, gist, and tags can contain PII — and frontmatter is the MOST-indexed part of the vault file (Obsidian tag pane, Dataview, graph view, search index). Labeling unscrubbed content leaks PII into the most visible, most queryable surface of every chat file.

**Locked ordering:** `load session → scrub content → label scrubbed content → render markdown → atomic write`.

**Required safeguard:** a canary test file with known synthetic PII (fake SSN, fake email, fake protocol code, fake token) that is scrub-labeled-written, then the output is grep'd for the canaries. This test runs before any Phase 3 work is accepted and on every change to the pipeline thereafter.

### 4. USER-EDIT CLOBBER DEFENSE — three layers, not one

**Source:** PITFALLS.md #17 (CATASTROPHIC, flagged as "the single most important pitfall")

The invariant "once a chat is in the vault, the skill never touches it again" must be enforced by three INDEPENDENT mechanisms:

| Layer                   | Mechanism                                                                 | Defeats What                                                                                                                   |
| ----------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Primary**             | `synced_session_ids` set in `state.json`                                  | The normal path                                                                                                                |
| **Backup**              | Refuse-on-exists filesystem check at write time                           | state.json loss, state.json reset, fresh install on same vault                                                                 |
| **Belt-and-suspenders** | `auto_label_hash` sentinel in frontmatter (hash of the auto-written body) | Accidental re-writes that pass both above checks; lets us detect "is this still an auto-labeled file or did the user edit it?" |

**Explicitly rejected:** `needs_review: false` as the "hands-off" marker. Users flip booleans casually and will unset the flag without realizing it disables the safeguard. Use the hash sentinel instead — it's invisible and only the skill knows how to read it.

### 5. PHASE-ORDER CONVERGENCE — Features and Architecture agreed independently

The Features agent (via MVP definition + dependency graph) and the Architecture agent (via §7 Suggested Build Order) independently proposed essentially the same phase sequence:

| Phase | Features agent                                    | Architecture agent              | Consensus                                                                              |
| ----- | ------------------------------------------------- | ------------------------------- | -------------------------------------------------------------------------------------- |
| 1     | Scanner + state + write pipeline with stub labels | State + scanner foundation      | **Scanner + state file + write pipeline, stub labels, one machine, manual invocation** |
| 2     | AI labeling                                       | Rendering pipeline (no AI)      | (divergence — see below)                                                               |
| 3     | PII scrub integration + polish                    | SKILL.md + AI labeling          |                                                                                        |
| 4     | MemPalace bulk integration                        | MemPalace + crash safety polish | MemPalace integration                                                                  |
| 5     | launchd + observability                           | LaunchAgent + observability     | **launchd scheduling + observability + first-run flood handling**                      |

**Divergence:** The Architecture agent put "rendering pipeline with no AI" as Phase 2 and "SKILL.md + AI labels" as Phase 3, whereas the Features agent put AI labeling as Phase 2 because the labeler is free inside Claude Code. Resolution: **Architecture's ordering is correct** — Phase 2 should deliver a working pipeline with stub labels so the whole pipeline is debugged in isolation from prompt quality, and Phase 3 adds the Claude-generated labels on top.

**Final suggested ordering:**

1. Scanner + state + stub-label write pipeline (one machine, manual)
2. SKILL.md + AI labeling (Claude in interactive session)
3. PII scrub integration + crash safety polish + canary test
4. MemPalace bulk-mine integration
5. launchd scheduling + observability + first-run flood handling

### 6. `protect` COMMAND BEHAVIOR IS UNVERIFIED

**Source:** ARCHITECTURE.md §6 (explicit research flag)

PROJECT.md assumes `claude-chat.py protect` performs content-level PII scrubbing. The Architecture agent flagged that this is not yet verified — `protect` may only manage `settings.json` auto-deletion config, not scrub content in exported markdown.

**Required before Phase 3:** a verification step (likely a 15-minute read of `cmd_protect()` in `claude-chat.py`) to confirm what `protect` actually does today. Three outcomes:

1. **`protect` already scrubs content** → nothing to do, Phase 3 proceeds as planned.
2. **`protect` only manages settings, no content scrubbing** → add `protect --scrub-content` mode to `claude-chat.py` that reads markdown from stdin, writes scrubbed markdown to stdout. Small, backwards-compatible addition (~30 lines). Must land before Phase 3.
3. **`protect` scrubs content but not in a way usable by the sync pipeline** → add the `--scrub-content` mode anyway, sharing rule logic with existing code.

**Phase 1 should include this verification as its first task.**

### 7. CLINICAL PII GAPS — regex scrubbers will miss clinical research tokens

**Source:** PITFALLS.md #11

The user works in clinical research. Standard PII regex templates miss:

- **Clinical trial identifiers:** NCT IDs (`NCT\d{8}`), EU protocol codes, Japan JMA codes, China chiCTR codes
- **Internal corporate URLs and project codenames** (not on any public list)
- **JWT tokens** (not caught by most generic credential scrubbers)
- **GitHub token prefixes beyond `ghp_`** (`gho_`, `ghu_`, `ghs_`, `ghr_`, fine-grained `github_pat_`)
- **Drug-dose prose** — "25 mg daily for 12 weeks" style content may identify a specific trial even without a code

**Recommendations (all four should be implemented):**

1. **Augment scrub templates** with clinical-specific patterns before Phase 3.
2. **Per-user canary test file** — a known-PII file Michael provides that MUST pass clean through the pipeline, stored locally (not in vault). Run on every CI pass.
3. **Optional second-pass LLM scrub** — after the regex pass, optionally ask Claude "does anything in this still look like PII to you?" as a second layer. Cheap (one call per chat), catches prose that regex missed.
4. **Fail-open-with-flag policy** — NEVER refuse to write a chat because scrub is uncertain. Always write, but tag `needs_review: true` and add a `privacy_review: uncertain` field. Refusing to write creates unbounded queues that the user will eventually turn off.

---

## Key Findings

### Recommended Stack

**Locked/existing (not re-researched):**

- Python 3 stdlib only for `claude-chat.py` — preserve zero-deps invariant
- Single-file CLI architecture

**New surface area (researched):**

- **Claude Code Skill** at `~/.claude/skills/sync-chats/SKILL.md` — task-style skill with `disable-model-invocation: true`, `allowed-tools` whitelist for pre-approved bash, progressive disclosure pattern (SKILL.md ≤500 lines, references/ for schema detail)
- **`sync_chats.py`** at `~/.claude-chat/sync_chats.py` — stdlib-only deterministic helper, never calls Claude, owns state.json/config.json/filename conventions/atomic writes. Subcommands: `scan`, `write`, `status`, `init`, `log`
- **Subprocess integration** with existing `claude-chat.py` — not `import` (the hyphen in the filename blocks normal imports). Requires adding `export --stdout` flag (small, backwards-compatible)
- **launchd LaunchAgent** — `StartInterval: 3600` + `RunAtLoad: true`, explicit `PATH` in `EnvironmentVariables`, `StandardOutPath`/`StandardErrorPath` to local log, `ProcessType: Background` + `LowPriorityIO` + `Nice: 10`
- **MemPalace integration** via the `mempalace mine` CLI (not per-chat MCP calls — see cross-cutting finding #2)
- **Obsidian frontmatter** — YAML tag array, ISO dates, `machine` + `hostname` + `synced_at` + `session_id` + `needs_review: true` + `auto_label_hash` sentinel

### Expected Features

**Must have (table stakes — fails Core Value if missing):**

- Delta-sync scanner (mtime + size cheap path, hash slow path for confirmation)
- AI-generated title (≤10 words), gist (2–3 sentences), tags (3–5 kebab-case)
- PII scrub before write (non-negotiable; ordering locked as scrub→label→write)
- Obsidian-shaped markdown with YAML frontmatter
- Machine-prefixed filename: `<machine>--YYYY-MM-DD--<slug>.md`
- Per-machine config + per-machine local state (never in iCloud)
- Idempotent, catch-up-aware execution
- Skip-already-synced guard (three layers — see finding #4)
- Sync summary output at end of run
- `needs_review: true` on every auto-labeled chat (for Obsidian-as-review-UI)

**Should have (differentiators — unique combination in the landscape):**

- AI labels from running Claude session (no API keys, no Ollama, no external service)
- MemPalace bulk-mine integration (competitive moat — nobody else does this)
- Multi-machine coexistence via disjoint session sets + machine-prefixed filenames
- Sleep-safe catch-up via launchd coalescing + idempotency
- Obsidian-as-review-UI (a deliberately-omitted feature that removes huge scope)
- PII scrub default-on, not opt-in
- Idempotent reversible-by-omission design (self-healing on state loss)

**Defer (v2+):**

- Per-machine stats command
- Dataview query template bundle
- Title regeneration for specific sessions (with heavy guards)
- Per-project frontmatter overrides (e.g., employer-specific compliance flags)

**Anti-features (deliberately NOT built):**
Menu bar app, web UI, review queue command, file watcher, dedup logic, shared state file, retroactive relabeling, external LLM API, custom search engine, configurable schemas, multi-folder routing, git backing, attachment extraction, multi-source importers.

### Architecture Approach

Three-tier separation with clean boundaries: **Claude makes semantic decisions** (titles, tags, gists), **`sync_chats.py` does deterministic mechanics** (state, atomic writes, filename policy), **existing `claude-chat.py` does the heavy lifting** (JSONL parsing, markdown export, PII scrub). Communication is subprocess + JSON over stdout; `sync_chats.py` never imports `claude-chat.py`, never calls Claude, never calls MCP.

**Core invariant:** per-session transactionality. Each session commits independently (render → atomic file write → atomic state update → mempalace bulk feed happens once at run end → log). A crash on session 7 leaves sessions 1–6 fully committed and retries session 7 on next run.

**Major components:**

1. **SKILL.md** (`~/.claude/skills/sync-chats/SKILL.md`) — Claude's playbook. Owns prompt language, orchestration loop, failure policy, success messages. NO business logic.
2. **`sync_chats.py`** (`~/.claude-chat/sync_chats.py`) — stdlib-only helper. Owns state.json, config.json, filename/frontmatter templating, atomic writes, crash safety, lock file (fcntl).
3. **`claude-chat.py`** (existing, +~30 lines for `export --stdout`, possibly `protect --scrub-content`) — owns JSONL parsing, markdown rendering, PII rules.
4. **State files** at `~/.claude-chat/` — `state.json`, `config.json`, `sync.log`, `last_run.json`, `sync.lock`.
5. **Output target** — `<vault>/Chats/` flat folder with machine-prefixed markdown files, plus `_sync-log.md` and `_sync-errors.md`.
6. **launchd LaunchAgent** (Phase 5) — `com.michaelhenry.sync-chats.plist` under `~/Library/LaunchAgents/`.

**Golden ordering (per session), cannot be reordered:**

1. Render (pure function)
2. Write file atomically (tmp + rename)
3. Update state atomically (tmp + rename)
4. Log (fsync append)
5. (After all sessions: run `mempalace mine` once)

**Never order state before file** — creates the possibility of "state says synced, no file exists" → permanent data loss.

### Critical Pitfalls (Top 5)

1. **PII scrub AFTER labeling (PITFALLS #10, CATASTROPHIC)** — see cross-cutting finding #3. Lock the ordering as scrub→label→write and enforce via canary test.
2. **User-edit clobber (PITFALLS #17, CATASTROPHIC)** — see cross-cutting finding #4. Three-layer defense.
3. **launchd wake with no PATH / no network / no TCC (PITFALLS #2, #3, CATASTROPHIC)** — absolute paths in plist, explicit `EnvironmentVariables > PATH`, network-readiness wait at skill start, self-diagnostic `stat()` of `Chats/` folder, install script prints Full Disk Access instructions.
4. **state.json crash-corrupts + re-export storm (PITFALLS #8, BAD → CATASTROPHIC cascade)** — atomic write pattern (tmp + fsync + rename), `state.json.bak` fallback, schema_version field, and critically: **never re-export sessions in `synced_session_ids` even if the vault file is missing** (this prevents the "user deletes a chat → infinite re-creation loop" PITFALLS #9).
5. **Clinical PII regex gaps (PITFALLS #11, CATASTROPHIC in context)** — see cross-cutting finding #7.

Also worth naming:

- **iCloud placeholder files on cross-machine reads (PITFALLS #4)** — never read other machine's files; trust state.json.
- **`~/.claude-chat/` accidentally in iCloud (PITFALLS #7)** — startup assertion that state.json path does NOT contain `Mobile Documents` or `iCloud`.
- **launchd StartInterval coalescing vs artificial work limits (PITFALLS #1)** — coalescing is GOOD (it's what we want), BUT only if the scanner has no artificial `--limit` on how many sessions one run can process.

---

## Implications for Roadmap

Suggested five-phase structure. Each phase ends with something end-to-end testable without the next phase.

### Phase 1 — Scanner + State + Stub-Label Write Pipeline (one machine, manual invocation)

**Rationale:** The delta-detection invariant is the trickiest thing in the design. Isolate it. No AI, no launchd, no MemPalace, no multi-machine concerns. Prove that "find new sessions, scrub them, write them to Chats/, never re-write, survive state.json loss" works on one machine with manual invocation.

**Delivers:**

- `sync_chats.py` with `scan`, `init`, `write`, `status`, `log` subcommands (stdlib only)
- `state.json` schema (v1) with atomic write + `.bak` fallback + schema_version
- `config.json` machine label setup
- Machine-prefixed filename + frontmatter generator
- File-exists-skip rule (backup clobber defense layer)
- Stub labels: `title = first 8 words of first user message`, `gist = first 200 chars`, `tags = []`
- `export --stdout` flag added to `claude-chat.py`
- **VERIFICATION TASK:** audit `cmd_protect()` to determine whether content scrubbing exists; if not, add `protect --scrub-content` mode (see cross-cutting finding #6)
- Startup assertion that state.json path is not in iCloud
- Canary test infrastructure (wired into CI in Phase 3)

**Addresses:** delta-sync scanner, per-machine config, per-machine state, idempotency, skip-already-synced guard (primary + backup layers), Obsidian markdown writer, machine-prefixed filename

**Avoids pitfalls:** #1 (no work limit), #5 (machine-prefixed filenames with unit test), #7 (startup iCloud assertion), #8 (atomic state writes), #9 (synced_session_ids is sticky, never re-derived from disk)

**Research flag:** LOW — standard patterns. Only research question is the `protect` verification.

### Phase 2 — SKILL.md + AI Labeling (Claude in interactive session)

**Rationale:** The write pipeline is proven. Swap stub labels for Claude-generated labels via a SKILL.md playbook. Prompt quality and skill authoring can iterate rapidly because the pipeline underneath is trusted. Initially runs interactively; headless path deferred to Phase 5.

**Delivers:**

- `~/.claude/skills/sync-chats/SKILL.md` with proper frontmatter (`name`, `description`, `disable-model-invocation: true`, `allowed-tools`, `argument-hint`)
- Orchestration loop in SKILL.md (call `scan`, loop over deltas, per-delta: read session, generate `{title, gist, tags, coherence_score}` JSON, call `write`)
- AI label prompt design (title ≤10 words verb-leading, gist 2–3 sentences past tense, tags 3–5 kebab-case topical, coherence score 1-5)
- Edge case handling: ultra-short skip, low-signal tag, topic-drift tag, fallback label on JSON parse failure

**Addresses:** AI-generated title, gist, tags, edge-case handling, sync summary output

**Research flag:** MEDIUM — exact SKILL.md invocation syntax and `allowed-tools` prefix matching semantics need live verification.

### Phase 3 — PII Scrub Integration + Crash Safety Polish

**Rationale:** Scrub integration is isolated from label quality. Lock the `scrub → label → write` ordering. Wire the canary test into CI. Add the `auto_label_hash` sentinel. Add fcntl lock file, retry logic, last_run.json, and Obsidian-native `_sync-log.md`.

**Delivers:**

- Scrub-before-label pipeline enforcement
- Canary test file with synthetic PII (SSN, fake email, fake NCT ID, fake JWT, fake GitHub tokens of all prefixes) — CI gate
- Clinical PII template augmentation (NCT, EU/JMA/chiCTR codes, JWT, GitHub token variants)
- Optional second-pass LLM scrub hook (configurable)
- Fail-open-with-flag policy: never refuse to write, always tag `needs_review: true` + `privacy_review: uncertain` when in doubt
- `auto_label_hash` sentinel in frontmatter
- `sync.lock` via fcntl.flock
- `last_run.json` + `_sync-log.md` observability
- Error surface via `_sync-errors.md`

**Addresses:** PII scrub before write (locked ordering), three-layer clobber defense, observability

**Avoids pitfalls:** #10 (scrub order), #11 (clinical gaps), #17 (user-edit clobber final layer)

**Research flag:** HIGH — `protect` behavior (if unresolved from Phase 1), clinical regex patterns, second-pass scrub prompt design. Strongly recommend `/gsd-research-phase` before kickoff.

### Phase 4 — MemPalace Bulk-Mine Integration

**Rationale:** All chats exist in the vault with good labels and are PII-safe. Run `mempalace mine <vault>/Chats --mode convos --extract general` once at the end of each sync run. This is a ~10-line addition.

**Delivers:**

- Post-write bulk mine invocation from SKILL.md
- Handling when `mempalace` command is missing (log warning, continue)
- Optional: `mempalace_mined_at` timestamp in sync summary
- Documentation of MemPalace path resolution for multi-machine (use vault-relative paths; see PITFALLS #6)

**Addresses:** MemPalace integration (simplified per cross-cutting finding #2)

**Avoids pitfalls:** #6 (absolute paths in memories breaking cross-machine)

**Research flag:** MEDIUM — exact `mempalace mine` CLI surface is verified but edge cases need live testing.

### Phase 5 — launchd Scheduling + Observability + First-Run Flood

**Rationale:** Everything is boring now. Make it headless. This phase depends on the unresolved headless-blocker decision (cross-cutting finding #1), so its exact shape is parameterized on the user's choice.

**Delivers:**

- LaunchAgent plist at `~/Library/LaunchAgents/com.michaelhenry.sync-chats.plist`
- Absolute paths in `ProgramArguments`
- Explicit `EnvironmentVariables > PATH`, `HOME`, `USER`
- `StandardOutPath`/`StandardErrorPath` to `~/.claude-chat/`
- `ProcessType: Background` + `LowPriorityIO` + `Nice: 10`
- Network-readiness wait at skill start (30s timeout, exit 0 not fail)
- Self-diagnostic `stat()` on `<vault>/Chats/` at startup
- Install script that prints TCC / Full Disk Access instructions
- Bootstrap/bootout scripts (modern `launchctl bootstrap gui/$(id -u)`)
- First-run flood handling: first invocation against 200+ existing sessions must work without rate-limiting or launchd watchdog kills
- Integration test: 48h stale cursor → one run → all deltas landed
- Documentation for installing on the second Mac

**Addresses:** launchd sleep-safe scheduling, sync summary output, manual catch-up escape hatch

**Avoids pitfalls:** #1 (coalescing + no artificial limits), #2 (PATH + network wait), #3 (TCC + self-diagnostic)

**Research flag:** HIGH — macOS Sequoia+ TCC behavior on launchd-invoked processes touching iCloud paths is only medium-confidence. Strongly recommend `/gsd-research-phase`.

### Phase Ordering Rationale

- **Pipeline before labels before scrub:** each phase's output is observable without the next.
- **MemPalace after Obsidian works:** per PROJECT.md's "if everything else fails, this must work" — Obsidian is primary value, MemPalace is additive.
- **launchd last:** don't schedule a thing that isn't working. Isolates the TCC/PATH/network rabbit hole.
- **`protect` verification in Phase 1:** front-load the unknown.
- **Headless path decision up front:** cross-cutting finding #1 changes Phase 5's shape. Resolve at requirements.

### Research Flags

**Phases likely needing deeper research during planning:**

- **Phase 3 (PII + crash safety):** HIGH — clinical regex patterns, second-pass scrub prompt design. Strongly recommend `/gsd-research-phase`.
- **Phase 5 (launchd):** HIGH — Sequoia+ TCC behavior, whether `claude` and `python3` need separate FDA entries. Strongly recommend `/gsd-research-phase`.
- **Phase 2 (SKILL.md):** MEDIUM — live verification of SKILL.md frontmatter + `allowed-tools` semantics. Optional.

**Phases with standard patterns (skip research):**

- **Phase 1 (scanner + state):** atomic writes, mtime+size+hash, stdlib subprocess — all well-trodden.
- **Phase 4 (MemPalace bulk mine):** shell out to one verified command.

---

## Confidence Assessment

| Area         | Confidence                                                        | Notes                                                                                                                                                                                          |
| ------------ | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stack        | HIGH                                                              | Verified against official Anthropic skills docs, Apple launchd docs, installed MemPalace plugin, live CLI testing. Headless blocker is also HIGH-confidence and explicit.                      |
| Features     | HIGH table stakes + anti-features; MEDIUM AI-labeling conventions | Anti-features reflect user's PROJECT.md decisions. Table stakes forced by Core Value. Labeling conventions are community practice.                                                             |
| Architecture | HIGH                                                              | Standard patterns. Two MEDIUM items: `protect` integration (Phase 1 verification), SKILL.md orchestration syntax (Phase 2 verification).                                                       |
| Pitfalls     | MEDIUM-HIGH                                                       | launchd and iCloud pitfalls verified against Apple Developer Forums. MCP and LLM-labeling pitfalls drawn from general practice. Clinical PII gaps are HIGH confidence (user's actual context). |

**Overall confidence:** HIGH for architectural skeleton and phase ordering; MEDIUM where four named gaps exist.

### Gaps to Address

1. **Headless invocation path unresolved** (cross-cutting #1) — three options, user's choice at requirements.
2. **`protect` command actual behavior unverified** (cross-cutting #6) — 15-minute audit in Phase 1.
3. **MemPalace MCP tool surface beyond bulk mine** (Phase 4 research flag) — bulk mine verified live; edge cases need testing.
4. **Sequoia+ TCC behavior on launchd** (Phase 5 research flag) — medium-high risk of "works interactively, silently fails from launchd."

---

## The Competitive-Landscape Moment (Good News)

No existing tool combines delta-sync + AI labels + PII scrub + multi-machine coexistence + memory feed:

- **`claude-code-log`** — HTML output, no deltas, no labels, no vault
- **`claude-conversation-extractor`** — raw export only
- **`cctrace`** — markdown/XML archival, no curation
- **`claude-vault`** (closest) — AI tags via Ollama, PII modes, UUID-tracked sync, but explicitly punts on multi-machine and depends on Ollama
- **Nexus AI Chat Importer** (Obsidian plugin) — session UUID as filename, zero AI, date hierarchy
- **MindStudio Stop-hook pattern** — writes to vault with frontmatter, weaker on multi-machine/idempotency/PII
- **Claude Code native Session Memory** — ephemeral working memory for Claude, not a human-browsable artifact

The user's specific combination — Obsidian-as-review-UI, running inside Claude so the labeler is free, local state for race-free multi-machine, clinical-grade PII defaults — is a real gap in the landscape.

---

## Sources

### Primary (HIGH confidence)

- [Claude Code Skills (official)](https://code.claude.com/docs/en/skills) — SKILL.md schema, progressive disclosure
- [Claude Code Headless mode](https://code.claude.com/docs/en/headless) — **the headless blocker finding**
- [anthropics/skills GitHub repo](https://github.com/anthropics/skills) — real SKILL.md examples
- Apple `launchd.plist(5)` man page — `StartInterval` coalescing
- [Apple Developer Forums thread 23361](https://developer.apple.com/forums/thread/23361) — StartInterval + sleep
- [Apple Developer Forums thread 52369](https://developer.apple.com/forums/thread/52369) — jobs scheduled during sleep
- [launchd.info](https://www.launchd.info/) — third-party launchd reference
- Live MemPalace CLI verification (`mempalace mine <dir> --mode convos --extract general`)
- Existing `claude-chat.py` codebase (~1500 lines, mapped 2026-04-09)

### Secondary (MEDIUM confidence)

- [Alvin Alexander: launchd plist examples](https://alvinalexander.com/mac-os-x/launchd-plist-examples-startinterval-startcalendarinterval/)
- [Kill The Yak: launchd guide](https://killtheyak.com/schedule-jobs-launchd/)
- Competitive landscape (daaain/claude-code-log, ZeroSumQuant, jimmc414/cctrace, antocuni, MarioPadilla/claude-vault, Nexus AI Chat Importer, MindStudio Stop-hook)
- OpenAI community forum on constraint-based title prompts
- Obsidian frontmatter conventions (Dataview/Bases)
- MCP general practice

### Tertiary (LOW confidence)

- [perez987/macOS-15-sequoia-sleep-issue](https://github.com/perez987/macOS-15-sequoia-sleep-issue) — informational, not a blocker
- Sequoia+ TCC behavior on launchd — inferred; needs live validation in Phase 5
- Clinical PII regex patterns (NCT, EU/JMA/chiCTR, employer-specific) — derived from user context; needs canary validation in Phase 3

---

_Research completed: 2026-04-10_
_Ready for roadmap: yes, with three cross-cutting findings (headless path, scrub order, clobber defense) to surface to user at requirements time_
