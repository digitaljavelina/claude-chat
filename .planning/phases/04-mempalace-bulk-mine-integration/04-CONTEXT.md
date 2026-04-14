# Phase 4: MemPalace Bulk-Mine Integration - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

After `sync_chats.py` writes N new chats to the Obsidian vault in a sync run, shell out exactly once to `mempalace mine <vault>/Chats --mode convos --extract general` so every new chat gets ingested into the MemPalace. The whole pipeline must degrade gracefully when the `mempalace` CLI is absent (second Mac without MemPalace installed still completes the sync and writes vault files successfully). The sync summary reports the mine outcome as `true | false | skipped`.

**Out of scope (belongs elsewhere):**

- The SessionEnd hook that triggers sync runs (Phase 5)
- `last_run.json` / observability plumbing (Phase 5)
- Second-Mac onboarding README (Phase 5)
- Per-chat MCP calls to `mempalace_kg_add` (explicitly rejected in PROJECT.md — bulk shell-out is the locked path)

</domain>

<decisions>
## Implementation Decisions

### Invocation Point

- **D-01:** A new standalone `mine` subcommand is added to `sync_chats.py` (signature: `python3 sync_chats.py mine`). It shells out to `mempalace mine <vault>/Chats --mode convos --extract general` and reports the outcome.
- **D-02:** The SKILL.md orchestrator (already runs `scan → write(each)`) calls `mine` as the final step of a sync run. The CLI stays a toolkit of single-purpose subcommands; orchestration lives in the SKILL. Phase 5's SessionEnd-hook wrapper will invoke the skill-equivalent entrypoint — the exact shape of that wrapper is a Phase 5 concern, not locked here.
- **D-03:** The `mine` subcommand is independently callable by hand (`python3 ~/.claude-chat/sync_chats.py mine`) for manual catch-up and debugging, matching the Unix-toolkit style of existing subcommands.

### Scope of Each Mine Call

- **D-04:** Mine the entire `<vault>/Chats/` directory on every invocation, not a file list of just-written chats. Matches the mempalace CLI's idempotent-by-design contract (verified in reference memory: "Idempotent — re-running on the same directory re-processes without duplicating").
- **D-05:** `mine` is **skipped** when zero new files were written in the current run. Rationale: no new content to index, so running a full-directory scan would be wasted work. `mempalace_mined: skipped` is reported in the summary in this case. This preserves the three-state MEM-03 semantics (`true | false | skipped`).
- **D-06:** Self-healing is a deliberate property: if any single run's mine fails, the next non-zero-write run runs the full directory again, automatically catching up any files the failed run missed. No per-file "mined/not-mined" state tracking is needed.

### Error Handling

- **D-07:** Fail-soft. Non-zero exit from `mempalace mine` → `mempalace_mined: false` in the summary, last ~20 lines of stderr written to `sync.log`, sync run as a whole exits 0. Vault writes succeed regardless (MEM-02 locked).
- **D-08:** Binary-not-found (i.e., `shutil.which("mempalace")` returns `None`) → `mempalace_mined: skipped`, warning `mempalace: command not found — skipping mine` written to `sync.log`, sync exits 0.
- **D-09:** Timeout: 5 minutes (300 seconds), implemented via `subprocess.run(..., timeout=300)`. On `TimeoutExpired`, kill the process, log `mempalace: timed out after 300s — skipping mine`, report `mempalace_mined: false`.
- **D-10:** No retry. The self-healing property from D-06 handles transient failures via the next successful run. Keeps the implementation small.
- **D-11:** stderr handling: success is silent (no stderr logged). Failures log only the last ~20 lines — enough to diagnose without polluting `sync.log` on healthy runs.

### Detection Strategy

- **D-12:** Use `shutil.which("mempalace")` to detect the binary. This is now the correct pattern on the user's primary Mac following the 2026-04-14 migration from zsh-alias-only to a pipx-managed PATH binary at `~/.local/bin/mempalace`. Second Mac onboarding (Phase 5) will instruct `brew install pipx && pipx install mempalace`, which also produces a PATH binary.
- **D-13:** No fallback to `python -m mempalace` module invocation. Keeps the detection logic single-path and honest: if `shutil.which` doesn't find it, treat mempalace as not installed and skip. This is consistent with the "graceful degradation, sync works regardless" contract.

### Reporting

- **D-14:** The sync summary (the same human-readable block that already reports written-count, skipped-count, etc.) gains one line: `mempalace_mined: <true|false|skipped>`. Format is flat key: value text, not structured JSON — matches existing summary style.
- **D-15:** On `false` or `skipped`, a supplementary reason is shown inline (e.g., `mempalace_mined: skipped (command not found)` or `mempalace_mined: false (timeout after 300s)`) so the user understands the outcome without digging through `sync.log`.

### Claude's Discretion

- Exact wording of warning/failure messages in `sync.log` — follow existing log format (see `_log_sync` helper at sync_chats.py:914).
- Precise stderr truncation length (target ~20 lines, adjust if stderr is line-sparse).
- Where in the existing summary output the `mempalace_mined` line appears (suggest: last line, since it's the last pipeline step).
- Whether to expose timeout/command overrides in `config.json` (default: don't — YAGNI for Phase 4, can add later if the 300s default ever bites).

</decisions>

<canonical_refs>

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Vision

- `.planning/REQUIREMENTS.md` §MEM — MEM-01 (post-run shell-out), MEM-02 (graceful degradation), MEM-03 (`mempalace_mined` summary line)
- `.planning/PROJECT.md` §Key Decisions — "MemPalace: One bulk `mempalace mine --mode convos` shell-out at end of run, not per-chat MCP calls"
- `.planning/ROADMAP.md` §Phase 4 — Phase 4 goal and success criteria (three criteria map 1:1 to MEM-01/02/03)

### Existing Code

- `sync_chats.py` — Toolkit to extend. New `mine` subcommand goes beside existing `init/scan/write/status`. Log helper `_log_sync` at sync_chats.py:914 for `sync.log` writes. argparse dispatcher at sync_chats.py:1268 for registering the new subcommand.
- `~/.claude-chat/config.json` — Runtime config (vault path lives here). `mine` needs to read vault path to resolve `<vault>/Chats`.

### External / Reference

- `~/.claude/projects/-Users-michaelhenry-Documents-Projects-Python-claude-chat/memory/reference_mempalace_bulk_mine.md` — Verified usage of `mempalace mine --mode convos --extract general`, idempotency property, graceful-degradation pattern, and the 2026-04-14 alias→pipx transition note.
- `mempalace --help` and `mempalace mine --help` output — for planner to confirm CLI flags at plan time (version 3.3.0 via pipx on primary Mac as of 2026-04-14).

### Prior Phase Context (carried forward)

- Phase 3 locked the pipeline ordering `load → scrub → label → write` with a CI canary gate. Phase 4 extends this to `load → scrub → label → write → mine`. The canary gate does NOT cover mine (it tests per-session write correctness; mine is a post-run step and out of scope for the canary fixture).
- Phase 1 established that `sync_chats.py` subcommands are single-purpose and stdlib-only. The `mine` subcommand preserves stdlib-only (only uses `subprocess` and `shutil`, both stdlib).

</canonical_refs>

<code_context>

## Existing Code Insights

### Reusable Assets

- `_log_sync(message)` at sync_chats.py:914 — append-only logger to `sync.log`. Use for all warnings/errors from the mine step.
- `_require_config()` at sync_chats.py:156 — standard config loader with helpful error if init hasn't run. Use this in `cmd_mine` to get the vault path.
- Existing subparser pattern at sync_chats.py:1268 — concise `p_foo = subparsers.add_parser(...)` + `p_foo.set_defaults(func=cmd_foo)` idiom. New `mine` subcommand follows the same shape.

### Established Patterns

- Single-purpose subcommands: every existing command (init, scan, write, status) does one discrete thing. `mine` continues that pattern rather than bundling multiple steps.
- Stdlib-only dependency rule — `subprocess.run` with `timeout=`, `shutil.which`, no third-party additions.
- Failure mode: status-check commands (`scan`, `status`) print diagnostics and exit 0 even on "nothing to do". `mine` matches this — absence or failure is a reportable state, not an exit error.

### Integration Points

- The SKILL.md orchestrator will gain a `mine` invocation as its final step. SKILL.md is per-user and not in-repo (D-09 from Phase 2) — the skill update is a Phase 4 deliverable but tests for it are scoped at class-level (`@unittest.skipUnless` per the `reference_skill_md_tests_ci.md` memory).
- The sync summary output (currently printed at the end of a multi-write run orchestrated by the SKILL) gains the `mempalace_mined` line. This requires the SKILL to assemble summary data from the `write` results and the `mine` result — mostly a SKILL change, minor CLI change (mine must print a machine-readable outcome line on stdout).

</code_context>

<specifics>
## Specific Ideas

- **Detection pre-work completed during discussion:** On 2026-04-14 the user migrated `mempalace` from a zsh alias (`alias mempalace='python3.13 -m mempalace'` in `~/.zshrc:32`) to a real PATH binary via `pipx install mempalace`. The alias was removed. This unblocks `shutil.which("mempalace")` as the canonical detection pattern and removes a would-have-been brittle "try module invocation as fallback" branch from the plan.
- **User's preferred outcome semantics:** the three-state `true | false | skipped` in MEM-03 is not just "success/failure" — it intentionally distinguishes "didn't run because there's no work or no CLI" (skipped) from "ran and failed" (false). Planner must honor this distinction in the summary output.

</specifics>

<deferred>
## Deferred Ideas

- **Configurable timeout / mempalace command path in `config.json`** — considered (option C under "Error handling"), deferred as over-engineering for Phase 4. If the 300s default ever bites or the user's second Mac installs mempalace somewhere surprising, add then.
- **Retries on transient failure** — considered, deferred. The self-healing property (D-06) handles this automatically via the next non-zero-write run.
- **File-list scoping (only mine new files)** — considered, rejected. The mempalace CLI takes a directory, not a file list; implementing per-file would defeat the "bulk" point and lose self-healing.
- **SessionEnd hook wiring** — belongs to Phase 5 per ROADMAP.md.
- **`last_run.json` / `status` subcommand integration of mine results** — belongs to Phase 5 (OBSERV requirements).

</deferred>

---

_Phase: 04-mempalace-bulk-mine-integration_
_Context gathered: 2026-04-14_
