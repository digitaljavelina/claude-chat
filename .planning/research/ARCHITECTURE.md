# Architecture Research — `/sync-chats` Skill

**Domain:** Claude Code skill + delta-sync pipeline + scheduled daemon
**Researched:** 2026-04-10
**Confidence:** HIGH (concrete design; grounded in existing codebase and Claude Code skill conventions)

---

## 1. Skill Orchestration Architecture

The cleanest separation puts **decisions in Claude**, **determinism in Python/bash**, and **heavy lifting in the existing `claude-chat.py`**.

### The Three Tiers

```
┌────────────────────────────────────────────────────────────────┐
│  Tier 1: SKILL.md  (what Claude reads and reasons about)       │
│  - Tells Claude: "call scan, then for each session in the      │
│    returned list, read it, produce {title, gist, tags}, then   │
│    call write, then call feed."                                │
│  - Owns: prompt language, invariants, failure policy, success  │
│    message format. NO business logic.                          │
├────────────────────────────────────────────────────────────────┤
│  Tier 2: sync_chats.py  (deterministic helper, stdlib-only)    │
│  - scan    → prints JSON list of session deltas                │
│  - write   → given {session_id, title, gist, tags}, produces   │
│              the markdown file, atomic rename, state update    │
│  - status  → prints state summary / last run info              │
│  - init    → sets machine label, writes config.json            │
│  - log     → appends to sync log                               │
│  - Owns: state.json, config.json, filename conventions,        │
│    frontmatter templating, atomic writes, crash safety.        │
│  - NEVER calls Claude; NEVER makes a decision; pure I/O + data │
├────────────────────────────────────────────────────────────────┤
│  Tier 3: claude-chat.py  (existing, untouched)                 │
│  - export  → markdown rendering from JSONL                     │
│  - protect → PII scrub on content                              │
│  - Invoked by sync_chats.py via subprocess                     │
│  - Owns: JSONL→markdown, PII rules, session discovery          │
└────────────────────────────────────────────────────────────────┘
```

### Where Each Decision Lives

| Decision                                 | Lives In                                     | Why                                    |
| ---------------------------------------- | -------------------------------------------- | -------------------------------------- |
| "Is this session new/updated/done?"      | `sync_chats.py scan`                         | Deterministic, testable without Claude |
| "What should the title be?"              | Claude (via SKILL.md)                        | Needs semantic understanding           |
| "What tags apply?"                       | Claude (via SKILL.md)                        | Same reason                            |
| "What does the markdown file look like?" | `sync_chats.py write`                        | Templating is mechanical               |
| "Where do we write it?"                  | `sync_chats.py write`                        | Path policy is mechanical              |
| "Was the PII scrubbed?"                  | `claude-chat.py protect` (called by `write`) | Existing logic                         |
| "Did it succeed? Log what?"              | `sync_chats.py log`                          | State mutation is mechanical           |
| "Should we feed MemPalace?"              | Claude, using MCP tools                      | MCP is Claude-native                   |

### Why Not Pure-Python or Pure-Skill?

**Pure Python (no Claude-in-the-loop):** You'd need an LLM API for titling. Kills the "runs inside Claude Code" advantage and adds API keys / billing.

**Pure SKILL.md (Claude does everything including bash loops):** Claude is non-deterministic. It will sometimes forget to update state, mis-order steps, or hallucinate filenames. Determinism must live outside the model.

**The split:** Claude decides semantic things, Python does mechanical things. Each side is good at what it owns.

### SKILL.md Pseudocode

```markdown
# /sync-chats

When invoked:

1. Run: `python3 ~/.claude-chat/sync_chats.py scan`
   → reads JSON array of deltas: [{session_id, path, kind: "new"|"updated", ...}]

2. If empty: print "No new chats." and exit.

3. For each delta (in order):
   a. Read the session JSONL via Read tool (or ask sync_chats.py to
   pre-render a compact form)
   b. Produce JSON: {title, gist, tags[]}
   c. Run: `python3 ~/.claude-chat/sync_chats.py write --session-id X
   --label-json '{...}'`
   → this shells out to claude-chat.py export + protect,
   writes the .md file, updates state.json atomically
   → prints the written path or "skipped: already exists"
   d. If write succeeded AND it was new, call mcp**mempalace**remember
   with the gist as content, title as label, tags as tags
   e. Run: `python3 ~/.claude-chat/sync_chats.py log --session-id X
   --status ok` (or --status failed --error "...")

4. Run: `python3 ~/.claude-chat/sync_chats.py log --finalize`
   → writes run summary line
5. Print summary: "Synced N new, M updated, K flagged, E errors."
```

Note: the skill processes sessions **one at a time** so a failure on session 7 does not lose sessions 1–6. See §4.

---

## 2. Pipeline Stages and Data Flow

```
┌─────────────────────────────┐
│ ~/.claude/projects/*.jsonl  │  (source of truth, local per Mac)
└──────────────┬──────────────┘
               │
               ▼  [Stage 1: SCAN]  sync_chats.py scan
               │  compares file mtime + size + hash vs state.json
               │  emits: [{session_id, path, kind, mtime, size}]
               ▼
        ┌──────────────┐
        │ delta list   │  (in-memory JSON, ephemeral)
        └──────┬───────┘
               │
               ▼  [Stage 2: LABEL]  Claude reads + decides
               │  per-session: {title, gist, tags[]}
               ▼
        ┌──────────────┐
        │ labeled item │  (in-memory, one at a time)
        └──────┬───────┘
               │
               ▼  [Stage 3: RENDER]  sync_chats.py write
               │  calls: claude-chat.py export --format markdown
               │  calls: claude-chat.py protect  (PII scrub on content)
               │  assembles frontmatter + body
               ▼
        ┌──────────────────────┐
        │ scrubbed markdown    │  (in-memory string)
        └──────┬───────────────┘
               │
               ▼  [Stage 4: WRITE]  sync_chats.py write (same call)
               │  - compute target path
               │  - if target EXISTS: skip, mark "already present" in state
               │  - else: atomic write (tmp + rename) to Chats/
               ▼
     ┌──────────────────────────────────────┐
     │ Chats/<machine>--YYYY-MM-DD--slug.md │
     └──────┬───────────────────────────────┘
            │
            ▼  [Stage 5: COMMIT-STATE]  still inside write command
            │  atomic update of ~/.claude-chat/state.json
            │  (mark session_id as synced, record hash, mtime)
            ▼
     ┌──────────────────────┐
     │ state.json updated   │
     └──────┬───────────────┘
            │
            ▼  [Stage 6: FEED]  Claude calls MCP mempalace.remember
            │  uses gist as content, title as label, tags as tags
            ▼
     ┌──────────────────────┐
     │ MemPalace memory +1  │
     └──────┬───────────────┘
            │
            ▼  [Stage 7: LOG]  sync_chats.py log
            │  append one line to ~/.claude-chat/sync.log
            ▼
        (next session)
```

### Transformation Boundaries

1. **JSONL → Session object** — lives in existing `claude-chat.py`, Stage 3.
2. **Session → markdown** — `export_markdown()` in existing `claude-chat.py`.
3. **Markdown → PII-scrubbed markdown** — `protect` in existing `claude-chat.py` (note: this will need a mode that operates on content strings, not just settings.json — see §6 caveat).
4. **Scrubbed markdown + label → final .md with frontmatter** — new logic in `sync_chats.py`.
5. **Label → MemPalace memory** — Claude, via MCP tool.

### Per-Session Transactionality

Stages 3–7 execute **per session**. A crash on session 7 leaves sessions 1–6 fully committed (file + state + memory). Session 7 is simply retried next run because state.json was never updated for it.

**This is the single most important invariant.** Everything else in the design follows from it.

---

## 3. State Management

### `~/.claude-chat/state.json` Schema

```json
{
  "version": 1,
  "machine": "mbp",
  "last_run": {
    "started_at": "2026-04-10T08:00:12Z",
    "finished_at": "2026-04-10T08:00:47Z",
    "new_count": 3,
    "updated_count": 1,
    "error_count": 0,
    "status": "ok"
  },
  "sessions": {
    "a3f21c88-....-....": {
      "path": "~/.claude/projects/-Users-m-foo/a3f21c88-....jsonl",
      "first_synced_at": "2026-04-08T14:22:10Z",
      "last_synced_at": "2026-04-10T08:00:31Z",
      "source_mtime": 1712736012.441,
      "source_size": 48293,
      "content_hash": "sha256:9b4c...",
      "output_path": "~/.../Chats/mbp--2026-04-08--debug-rss.md",
      "msg_count_at_sync": 42,
      "status": "synced",
      "mempalace_fed": true
    },
    "b7e0...": {
      "status": "error",
      "last_error": "claude-chat.py export exited 1",
      "last_attempt_at": "2026-04-10T08:00:33Z",
      "retry_count": 2
    }
  }
}
```

### New vs Updated vs Already-Synced Decision

`scan` walks `~/.claude/projects/**/*.jsonl` and for each file:

```
if session_id NOT in state.sessions:
    → NEW
elif state.sessions[id].status == "error" and retry_count < 5:
    → RETRY (treated as new)
elif file.mtime > state.sessions[id].source_mtime  OR
     file.size  != state.sessions[id].source_size:
    → UPDATED (see §5 for how this is handled — usually = skip)
else:
    → SYNCED (skip)
```

### Why mtime + size + hash (all three)?

- **mtime alone** → fragile; iCloud/`cp` can touch it.
- **size alone** → changes only when content grows; miss edits.
- **hash alone** → correct but requires reading the whole file every scan (slow at 100s of sessions).
- **Fast path**: mtime + size unchanged → skip (no read).
- **Slow path**: either changed → read + hash to confirm → only then mark dirty.

This is the classic `make`-style cheap-stat-then-confirm pattern.

### State Recovery

**If state.json is deleted:** On next run, `scan` sees every session as new. Write stage will encounter existing files in `Chats/` and **skip them** (the "file exists → skip" rule in §4 is what makes recovery safe). It will rebuild state.json gradually by recording each skipped-as-present session. No data loss; no duplicate files; worst case a few minutes of "catch-up" scanning.

**If state.json is corrupted:** `sync_chats.py` detects invalid JSON, renames it to `state.json.corrupt-<ts>`, and proceeds as if deleted. Log an error loudly.

**If session.json exists but source file disappeared:** Mark `status: "orphaned"`, never touch it again, leave the Obsidian file alone.

### "User Continued an Old Chat" (Same UUID, More Content)

This is the edge case. Per the PROJECT.md decision "_the skill never touches a chat once Michael has edited it_," the answer must be: **do not overwrite**.

Policy:

1. `scan` detects the delta (new hash).
2. `write` computes the target path, finds the file already present.
3. It does NOT overwrite. Instead:
   - Writes a sibling file `<machine>--YYYY-MM-DD--slug--continued-<N>.md` with the _new tail_ only (messages after `msg_count_at_sync`), OR
   - Simply records `status: "superseded_by_edit"` in state and logs it.
4. Update state's `source_mtime`, `source_size`, `content_hash` so future scans stop flagging it.

**Recommended default:** the second option (skip + log + update state). Add the "write tail" behavior only if Michael asks for it later. This preserves his Obsidian edits absolutely.

---

## 4. Idempotency and Crash Safety

### Golden Ordering (per session)

```
1. render  (pure function, no side effects — in memory only)
2. write_file_atomically  (tmp file + rename)         ← side effect #1
3. update_state_atomically (tmp file + rename)        ← side effect #2
4. feed_mempalace  (MCP call)                         ← side effect #3
5. append_log_line  (fsync-append)                    ← side effect #4
```

### Why This Ordering

- **File before state:** If we crash between 2 and 3, next run will re-scan, re-label, re-render, and then stage 4 (write) will see the file already exists on disk → skip cleanly. State self-heals by recording the skip.
- **State before MemPalace:** If we crash between 3 and 4, file is on disk, state says "synced", but MemPalace never got fed. Acceptable: the chat is safe in Obsidian (primary value), and we mark `mempalace_fed: false`. Next run has a cleanup pass: "any `mempalace_fed == false` → feed now."
- **Never ordering state before file:** If state says "synced" but no file exists, next run would skip → data loss.

### Crash Scenarios

| Scenario                                          | Result                                                                    | Recovery                                                                                                                                                                                                    |
| ------------------------------------------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Crash mid-rendering session 7 (sessions 1–6 done) | Sessions 1–6 fully committed. Session 7 has no file, no state, no memory. | Next run treats 7 as new. Clean.                                                                                                                                                                            |
| Crash after writing .md, before state update      | File exists, state unchanged, session still listed as new.                | Next run: label + re-render + write stage sees file present → skip, record state. No duplicate.                                                                                                             |
| Crash after state update, before MemPalace        | File + state committed. Memory missing.                                   | Next run: cleanup pass detects `mempalace_fed: false` → feeds.                                                                                                                                              |
| Two invocations overlap (cron + manual)           | Second invocation could also see the same deltas.                         | **Lock file:** `~/.claude-chat/sync.lock` with PID. Second invocation exits immediately with "already running (pid 1234)". Use `fcntl.flock` for race-free acquisition. Stale lock (PID gone) is reclaimed. |

### Atomic Writes (stdlib only)

```python
def atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)  # POSIX atomic rename
```

Use this for both `Chats/*.md` and `state.json`. Never write in place.

### File-Exists-Skip Rule (The Reversibility Guarantee)

`write` stage, immediately before rendering:

```python
if target_path.exists():
    record_in_state(session_id, status="already_present_on_disk",
                    output_path=str(target_path))
    return "skipped"
```

This single rule enforces the PROJECT.md invariant: **once a chat is in the vault, the skill never touches it.** It makes state.json loss non-fatal. It makes the skill safe to re-run after manual file copying. It is the cornerstone of the whole design.

---

## 5. Multi-Machine Coexistence

### The Three Scenarios from the Question

**(a) Machine A syncs a chat, Michael edits the title in Obsidian on machine B. Will machine A or B ever overwrite it?**

No. Two layers of protection:

1. Machine A's `state.sessions[id]` has `status: "synced"` → scan skips, never re-enters the pipeline.
2. Even if state.json were deleted on A, the file-exists-skip rule (§4) means the presence of `mbp--2026-04-08--debug-rss.md` (renamed or not) stops the write.

Wait — what if Michael renames the file in Obsidian? Then machine A no longer finds it at its recorded `output_path`, and would re-write under the original filename. Mitigation: when doing the file-exists-skip check, also check `state.sessions[id].status == "synced"` — **if state says it was synced, trust state over disk.** The state entry survives rename. This catches the rename case.

Put together: **state is sticky by session_id; disk presence is a safety net for state loss.** Both layers must fail for re-write to happen.

**(b) Two machines run their LaunchAgent at the same minute — iCloud conflict?**

No. Sessions are local per-machine (disjoint sets). Machine A writes `mbp--*.md`, machine B writes `studio--*.md`. They touch completely disjoint filenames. iCloud has no shared file to conflict on.

**(c) Machine A writes a file, iCloud hasn't synced to machine B yet — does anything break?**

No. Machine B doesn't look at other machines' files. It scans its own `~/.claude/projects/` and writes its own `studio--*.md` files. iCloud lag is invisible because there is no cross-machine dependency in the pipeline.

### Should There Be Shared State?

**Argue for:** A vault-wide counter would let us number chats `001`, `002`, ... globally.
**Argue against:** That counter would be the one file both machines would fight over. Any shared mutable state is a race waiting to happen across iCloud latency. Numbering is cosmetic — date-based slugs sort fine.

**Recommendation: NO shared state.** The "disjoint writes, local state" design is the reason this system is crash-safe across two Macs. Don't introduce the one thing that would break it.

The only "shared" thing is the `Chats/` folder itself as a **write-only append target** — neither machine ever reads files the other wrote.

---

## 6. Integration with Existing `claude-chat.py`

### Recommendation: **Shell out via subprocess, parse stdout/files.**

| Dimension               | Shell out (subprocess)                     | Import as module                                                                                      |
| ----------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| Coupling                | Loose (CLI is the contract)                | Tight (internal functions are the contract)                                                           |
| Crash blast radius      | Crash in claude-chat.py doesn't kill skill | Unhandled exception takes skill down                                                                  |
| Versioning              | Can upgrade claude-chat.py independently   | Lockstep                                                                                              |
| Python import gotchas   | None                                       | `claude-chat.py` has a hyphen in the name → can't `import claude-chat` without `importlib` gymnastics |
| Performance             | fork/exec per call (~100ms)                | fast                                                                                                  |
| Debuggability           | Easy — run the same command manually       | Requires Python debugger setup                                                                        |
| Matches existing design | Yes — it's already a CLI                   | Requires refactor to module                                                                           |

The hyphen alone is almost decisive. Subprocess it is.

### Concrete Usage

```python
# In sync_chats.py
import subprocess, json
CLAUDE_CHAT = Path.home() / "Documents/Projects/Python/claude-chat/claude-chat.py"

def export_session(session_id: str) -> str:
    result = subprocess.run(
        ["python3", str(CLAUDE_CHAT), "export", session_id,
         "--format", "markdown", "--stdout"],  # NB: needs --stdout flag
        capture_output=True, text=True, check=True
    )
    return result.stdout
```

### Required Minor Additions to `claude-chat.py`

Two small, backwards-compatible tweaks to make integration clean — **not a refactor**:

1. **`export --stdout`** — today `export` writes to a file. Add a `--stdout` flag that writes to stdout instead. One new branch in `cmd_export()`.
2. **`protect --scrub-content`** _(maybe)_ — today `protect` operates on `settings.json` (auto-deletion). The PROJECT.md says "pass through `protect` before it reaches the vault," implying PII scrubbing on content. If the current `protect` doesn't do content-level scrubbing, either:
   - Add `protect --scrub-content` that reads markdown from stdin, writes scrubbed markdown to stdout, OR
   - Do the scrubbing in `sync_chats.py` using regex rules (duplicates logic, not ideal), OR
   - Use a third command/flag if one exists.

**This is a research flag for Phase 1:** verify what `protect` actually does today and whether content-level PII scrub logic exists.

### Stdout as the Protocol

Use JSON for structured stdout (delta list, export output if needed) and plain text for human messages. Pipe `stderr` to the sync log.

---

## 7. Suggested Build Order

The architecture naturally yields **five phases**, each ending with something end-to-end testable. This is the layering that unlocks iterative validation.

### Phase 1 — State + Scanner Foundation

Build: `sync_chats.py scan` + `init` commands, state.json schema, config.json, mtime/size/hash logic.
Unlocks testing: "does delta detection work?" You can run `scan` repeatedly, add a new chat via Claude Code, re-run, see it appear.
**No AI, no writing, no MemPalace, no launchd.** Pure observable delta detection.
Also add `--stdout` to `claude-chat.py export` here (small, self-contained).

### Phase 2 — Rendering Pipeline (Synchronous, No AI)

Build: `sync_chats.py write`, frontmatter template, atomic writes, file-exists-skip rule, subprocess calls to `claude-chat.py export` and `protect`.
AI label: hardcoded stub — `title = first 8 words of first user message`, `tags = []`, `gist = first 200 chars`.
Unlocks testing: "does the end-to-end pipeline produce a valid Obsidian file?" You can open the output in Obsidian, check frontmatter, verify scrubbing, verify idempotency (run twice, nothing changes).

### Phase 3 — SKILL.md + AI Labeling

Build: `.claude/skills/sync-chats/SKILL.md` that orchestrates the loop. Replace the hardcoded stub with Claude-produced `{title, gist, tags}`.
Unlocks testing: "does the skill produce high-quality labels?" Run it interactively from a Claude Code session. Iterate on prompt quality.

### Phase 4 — MemPalace Feed + Crash Safety Polish

Build: MCP integration in SKILL.md, `mempalace_fed` state field + cleanup pass, lock file, error handling, retry logic, `log` command, `last_run` summary.
Unlocks testing: "does memory get populated correctly?" Query MemPalace after a run.

### Phase 5 — LaunchAgent + Observability

Build: `~/Library/LaunchAgents/com.claude-chat.sync.plist`, `last_run.md` writer, load/unload scripts, documentation for installing on a second Mac.
Unlocks testing: "does it run overnight and does Michael know what happened in the morning?"

### Why This Order

- Each phase's output is observable **without** the next phase.
- Phase 1 alone is useful (delta detection is the trickiest invariant; verify it in isolation).
- Phase 2 gives you files in Obsidian _today_ even without good titles.
- Phase 3 only adds labels on top of a working pipeline — easy to iterate on prompts without fear of breaking writes.
- Phase 4 adds MemPalace _after_ the Obsidian path is rock-solid, because Obsidian is the primary value (per PROJECT.md: "If everything else fails, this must work").
- Phase 5 is last because it's the part that doesn't matter until everything else is boring.

**Testability unlock chain:**

```
Phase 1 makes delta detection testable without any output
  → Phase 2 makes write pipeline testable without launchd or AI
    → Phase 3 makes labels testable without scheduling
      → Phase 4 makes MemPalace testable without leaving the foreground
        → Phase 5 makes the whole thing headless
```

---

## 8. Observability

### Recommendation: **Three-tier observability, each with a different consumer.**

| Tier                   | File                           | Consumer                    | Format                           | Retention                           |
| ---------------------- | ------------------------------ | --------------------------- | -------------------------------- | ----------------------------------- |
| **1. Append-only log** | `~/.claude-chat/sync.log`      | Michael during debugging    | One line per session processed   | Rotate at 10MB                      |
| **2. Last-run marker** | `~/.claude-chat/last_run.json` | `sync_chats status` command | JSON snapshot of most recent run | Overwritten each run                |
| **3. Human summary**   | `<vault>/Chats/_sync-log.md`   | Michael during breakfast    | Markdown, one section per run    | Grows indefinitely, Obsidian-native |

### Why All Three

- **Append-only log** is the debug trail. Grep it when something's wrong. Never shown in normal use.
- **last_run.json** is queryable state. Lets `sync_chats status` or a future menu-bar widget show "last synced 37 minutes ago, 3 new chats" without parsing logs.
- **`_sync-log.md` in the vault** is the thing Michael actually sees each morning when he opens Obsidian. Leading underscore sorts it to the top of `Chats/`. This is where the "how does the user know what happened last night" question gets answered. Format:

  ```markdown
  ## 2026-04-10 08:00 — mbp

  - 3 new chats, 1 updated, 0 errors (14s)
  - `mbp--2026-04-10--debug-rss-feed.md`
  - `mbp--2026-04-10--refactor-auth-module.md`
  - `mbp--2026-04-10--planning-q2-roadmap.md`
  ```

  Michael can delete old entries or archive the file; it's just a markdown file in his vault. Dataview-queryable. No new tools needed.

### Why Not Just One?

- Just a log file → invisible until Michael goes looking. Fails the "how do I know what happened last night" question.
- Just `_sync-log.md` → too chatty for debugging; can't grep efficiently; slow to update (markdown parse + rewrite).
- Just `last_run.json` → loses history.

Three small files, three distinct jobs. All cheap.

### Silent Success, Loud Failure

On errors, also write a top-level `_sync-errors.md` (or prepend a `⚠️` section to `_sync-log.md`). The vault view makes errors impossible to miss without requiring notifications or a menu bar.

---

## Directory Layout of the Skill Itself

```
~/.claude/skills/sync-chats/
├── SKILL.md                    # The skill prompt — what Claude reads
└── (nothing else needed here)

~/.claude-chat/
├── sync_chats.py               # Deterministic helper (new — stdlib only)
├── state.json                  # Per-machine state (NEVER in iCloud)
├── config.json                 # Machine label, paths
├── sync.log                    # Append-only debug log
├── last_run.json               # Last run snapshot
└── sync.lock                   # fcntl lock file

~/Library/LaunchAgents/
└── com.claude-chat.sync.plist  # LaunchAgent (Phase 5)

<vault>/Chats/
├── _sync-log.md                # Human-readable run history
├── _sync-errors.md             # Loud failure surface (only if errors)
├── mbp--2026-04-08--debug-rss.md
├── mbp--2026-04-09--refactor-auth.md
├── studio--2026-04-09--homelab-terraform.md
└── ...

<claude-chat repo>/
└── claude-chat.py              # Existing, ~+20 lines added for --stdout
```

### Why `~/.claude-chat/` and not inside the repo?

- The skill runs from a fixed install location; the repo might move.
- state.json must be local and machine-specific; putting it in a git-tracked repo invites accidental commits.
- `~/.claude-chat/` parallels `~/.claude/` and `~/.claude-chat/backups` (already used by `claude-chat.py` per STRUCTURE.md). Consistent.

### Why put `sync_chats.py` _next to_ state.json, not next to `claude-chat.py`?

Two reasons:

1. **Separation of concerns**: `claude-chat.py` is a standalone tool that exists independently. `sync_chats.py` is skill-machinery that exists only because of the skill. Keeping them apart lets `claude-chat.py` remain a zero-dep general tool.
2. **Install story**: installing the skill on a second Mac is `cp sync_chats.py ~/.claude-chat/ && cp SKILL.md ~/.claude/skills/sync-chats/` plus editing config.json. No repo checkout required.

---

## Component Boundaries (Who Talks to Whom)

```
 LaunchAgent ─────────┐
                      ▼
                  claude -p "/sync-chats"
                      │
                      ▼
                   SKILL.md  (Claude's runtime)
                      │
           ┌──────────┼──────────────────┐
           │          │                  │
           ▼          ▼                  ▼
     sync_chats.py   Read tool     mcp__mempalace__*
       (subprocess)  (JSONL files)      (MCP)
           │
           ├──▶ claude-chat.py export --stdout  (subprocess)
           ├──▶ claude-chat.py protect ...       (subprocess)
           ├──▶ state.json        (read/write, atomic)
           ├──▶ config.json       (read)
           ├──▶ sync.log          (append)
           ├──▶ last_run.json     (write, atomic)
           ├──▶ sync.lock         (fcntl flock)
           └──▶ <vault>/Chats/*.md (write, atomic, skip-if-exists)
```

### Boundary Rules

- **SKILL.md → sync_chats.py:** JSON over stdout/stdin. The CLI is the contract.
- **sync_chats.py → claude-chat.py:** subprocess only. Never `import`.
- **sync_chats.py ↔ state files:** atomic writes only. Never in-place edits.
- **SKILL.md → MCP:** direct MCP tool calls, per standard Claude Code skill conventions.
- **sync_chats.py ↔ MCP:** forbidden. Python helper is non-AI; MCP is Claude's world.
- **Either machine ↔ other machine's files:** forbidden. No cross-machine reads.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: State before file

Writing state.json before the .md file. Creates the possibility of "state says synced, no file on disk" → permanent data loss. **Always file first, state second.**

### Anti-Pattern 2: One big transaction across all sessions

"Process all 50 sessions, then write state once at the end." A crash at session 49 loses sessions 1–48. **Commit per session.**

### Anti-Pattern 3: Trust mtime alone

`cp -p`, iCloud, rsync, `touch` all can perturb mtime. Confirm any mtime-flagged delta with a content hash before treating it as dirty.

### Anti-Pattern 4: Claude updates state.json directly

Claude is non-deterministic; it will sometimes write invalid JSON or forget a field. State mutation is `sync_chats.py`'s exclusive job.

### Anti-Pattern 5: Importing `claude-chat.py` as a module

The hyphen breaks normal imports; using `importlib` works but couples the skill tightly to internal function signatures. Shell out.

### Anti-Pattern 6: Shared counter / shared state in iCloud

Every shared-mutable-state design eventually races. The disjoint-writes design makes races impossible; keep it that way.

### Anti-Pattern 7: Re-labeling chats on content update

The PROJECT.md invariant: once written + edited by Michael, never touched. Updates become "superseded_by_edit" state transitions, not rewrites.

### Anti-Pattern 8: Running PII scrub after writing

Scrub before atomic rename. A file on disk with unscrubbed content for even one second in an iCloud folder is already leaked.

---

## Confidence Notes

- **HIGH** on state/crash/idempotency design — these patterns are well-established (make, rsync, git).
- **HIGH** on subprocess-over-import decision — driven by concrete hyphen-in-filename constraint.
- **MEDIUM** on the exact `protect` integration — needs Phase-1 verification of whether `protect` can scrub content strings today, or if that's a gap.
- **MEDIUM** on SKILL.md orchestration syntax — needs verification against current Claude Code skill conventions during Phase 3. The pseudocode shown captures intent; exact invocation syntax will be confirmed then.
- **HIGH** on multi-machine coexistence — follows cleanly from the "disjoint sets + local state" invariant.

---

_Architecture research for: Claude Code `/sync-chats` skill milestone_
_Researched: 2026-04-10_
