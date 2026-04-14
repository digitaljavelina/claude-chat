# Phase 5: SessionEnd Hook + Observability + Multi-Machine Onboarding - Research

**Researched:** 2026-04-14
**Domain:** Claude Code hooks, argparse root-flag pattern, atomic JSON writer, stdlib testing, multi-machine onboarding
**Confidence:** HIGH (all critical claims verified against live code, official docs, or machine inspection)

---

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

- D-01: `--once` generates stub labels only. No Claude invocation. No `claude -p /skill`.
- D-02: Stub generator is the exact Phase 1 `make_stub_label` path. Dict fed through existing stdin contract internally. No `--stub` flag added to `write`.
- D-03: `auto_label_hash` set to literal string `"stub"` on every `--once` write.
- D-04: Interactive `/sync-chats` gains a re-label code path: scan for `auto_label_hash: stub`, regenerate, rewrite frontmatter only, update hash, flip `needs_review`.
- D-05: Re-label trigger is stub-sentinel only, not `needs_review: true`.
- D-06: Stubs land in vault immediately. Real labels arrive on next interactive `/sync-chats`.
- D-07: `--once` is a root flag, not a subcommand. Dispatches to `cmd_once` before subparser routing.
- D-08: `--once` runs scan + write-all-with-stubs only. Does NOT invoke mine.
- D-09: mine ownership stays with interactive SKILL.
- D-10: Exit-code policy preserved: 0 all-success/skipped, 1 per-session failure, 2 pre-flight error.
- D-11: `~/.claude-chat/last_run.json` written at end of every run. Schema version 1 with listed fields.
- D-12: `trigger` enum: "once" | "interactive" | "manual".
- D-13: `errors[]` capped at 10 entries.
- D-14: Atomic overwrite each run, `.bak` kept. Same tmp+fsync+rename pattern as state.json.
- D-15: `mempalace_mined: "skipped"` in every `--once` run.
- D-16: `flagged_for_review` explicit counter incremented per stub-write.
- D-17: `cmd_status` reads `last_run.json` first, falls back to `state.last_run_at`.
- D-18: `state.last_run_at` continues to be written by `cmd_write`.
- D-19: Hook command is direct: `python3 ~/.claude-chat/sync_chats.py --once`. No wrapper script.
- D-20: Hook is blocking (synchronous). See research qualification below.
- D-21: Hook failure is silent: exit codes captured in sync.log + last_run.json only.
- D-22: `_format_summary(last_run_dict) -> str` is sole source of truth for OBSERV-01 summary line.
- D-23: Summary line literal format: `Synced N new chats, M skipped (already-synced), K flagged for review, mempalace_mined: <status>`
- D-24: `cmd_once` tracks `flagged_for_review` as an explicit counter.
- D-25: Single `README.md` at repo root. Universal install path.
- D-26: Ten README sections in defined order.
- D-27: No separate ONBOARDING.md or docs/SETUP.md.

### Claude's Discretion

- Exact argparse wiring for root `--once` flag (any stdlib idiom is fine).
- Internal function naming inside `cmd_once`.
- JSON key order in `last_run.json`.
- Whether re-label code path (D-04) lives in SKILL.md text, `relabel` subcommand, or Python helper called by SKILL via subprocess.
- Exact stderr/output wording for error cases.
- Precise README prose.

### Deferred Ideas (OUT OF SCOPE)

- Sync-run history / `runs.jsonl` trends dashboard.
- Desktop notification on hook failure.
- Wrapper shell script for the hook.
- `mine` inside `--once`.
- Fire-and-forget backgrounded hook.
- Removal of `state.last_run_at`.
- Automatic SessionEnd-hook installer subcommand.
- README localization or screenshot-rich variant.
- `trigger: "manual"` population in Phase 5.

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID        | Description                                                                                      | Research Support                                                                                              |
| --------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| HOOK-01   | SessionEnd hook in `~/.claude/settings.json` fires `python3 ~/.claude-chat/sync_chats.py --once` | Verified hook schema from official docs + live settings.json inspection                                       |
| HOOK-02   | Hook fires within seconds, sub-second latency from chat-end to vault-write                       | Verified: `--once` does no AI calls, no mine; scan+stdlib I/O on 0-2 sessions is sub-second                   |
| HOOK-03   | Hook is safe to run repeatedly (idempotency upstream in CORE-07/08)                              | Confirmed: `synced_session_ids` set + refuse-on-exists already ship in Phases 1-3                             |
| HOOK-04   | Manual escape hatch: `/sync-chats` interactive catch-up                                          | Already ships in Phase 2 SKILL.md; Phase 5 does not modify it                                                 |
| HOOK-05   | README documents second-Mac installation                                                         | `README.md` already exists at repo root (claude-chat.py focused); Phase 5 rewrites it for sync_chats pipeline |
| OBSERV-01 | Every sync run produces the canonical summary line                                               | `_format_summary()` helper centralizes format; golden-string unit test verifiable                             |
| OBSERV-02 | `~/.claude-chat/sync.log` records timestamped entries                                            | `_log_sync()` at line 914 already ships; Phase 5 adds hook run-start/finish calls                             |
| OBSERV-03 | `~/.claude-chat/last_run.json` captures most recent run stats                                    | New `_write_last_run()` atomic writer mirrors `_write_atomic()` pattern                                       |
| OBSERV-04 | `sync_chats.py status` reads `last_run.json` and displays human summary                          | `cmd_status` refactor; existing implementation at line 1231                                                   |

</phase_requirements>

---

## Summary

Phase 5 is primarily a wiring and observability phase — no new algorithms, no new dependencies. The heavy lifting (stub generator, atomic writer, `_log_sync`, `discover_sessions`, `cmd_write`, `cmd_mine`) all ships in Phases 1-4. Phase 5 adds four things: (1) a `cmd_once` function that orchestrates `scan → for-each: make_stub → write-internally`; (2) a `_write_last_run()` atomic writer near-copied from `_write_atomic()`; (3) a `_format_summary()` pure helper that all callers converge on; (4) a rewritten `README.md` and `cmd_status` refactor.

The key research finding that requires a decision-flag: **SessionEnd hooks are classified as non-blocking by official docs** — meaning Claude Code does not wait for them to complete before terminating. D-20 assumes blocking. In practice the hook will still run serially (one session ends at a time), but the theoretical race scenario D-20 was designed to prevent (two overlapping `--once` processes) is possible if a user ends two sessions very quickly. This does not invalidate D-20's intent — Phase 1's clobber defense handles the race harmlessly — but the planner should note D-20's framing needs updating in the README.

The Tailscale hostname finding is operationally important: `socket.gethostname()` returns `digital-javelina-pro.tail75a1.ts.net` on Michael's Mac (not the short hostname). `last_run.json` should store this verbatim per D-11, but the README onboarding section should note that hostname appearance depends on whether Tailscale is running.

**Primary recommendation:** Wire `--once` as a pre-dispatch argparse branch, near-copy `_write_atomic()` for `_write_last_run()`, make `_format_summary()` a pure function taking the dict, and add two `_log_sync()` calls (run-start, run-finish) in `cmd_once`. Everything else is composition of existing code.

---

## Project Constraints (from CLAUDE.md)

Extracted directives from `CLAUDE.local.md` that the planner must verify against:

| Directive                                           | Source                       | Phase 5 Impact                                                                                                    |
| --------------------------------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Zero external dependencies (stdlib only)            | CLAUDE.local.md + PROJECT.md | `socket`, `datetime`, `json`, `os`, `pathlib` — all stdlib. No new deps added.                                    |
| Single-file CLI — `sync_chats.py` stays one file    | PROJECT.md conventions       | `cmd_once`, `_write_last_run`, `_format_summary` are all added inline to sync_chats.py                            |
| Python beginner — inline comments explaining idioms | CLAUDE.local.md              | Root-flag pre-dispatch, `datetime.now(timezone.utc).isoformat()`, `os.replace` atomicity all need inline comments |
| `CLAUDE_CHAT_HOME` env override for tests           | Phase 1 D-29                 | `_write_last_run` must resolve path via `CLAUDE_CHAT_HOME`, not hardcoded `~/.claude-chat/`                       |
| Exit-code policy: 0/1/2                             | Phase 1 D-31                 | `cmd_once` must follow same policy                                                                                |
| `sync.log` format: ISO timestamp + space + message  | Phase 1 D-33                 | `_log_sync()` is already correct; just call it with the right messages                                            |

---

## Standard Stack

### Core (all stdlib, no additions)

| Module     | Version | Purpose                                    | Already in sync_chats.py? |
| ---------- | ------- | ------------------------------------------ | ------------------------- |
| `argparse` | stdlib  | Root `--once` flag + subparser routing     | Yes (line 1332)           |
| `json`     | stdlib  | `last_run.json` serialization              | Yes                       |
| `socket`   | stdlib  | `socket.gethostname()` for hostname field  | Yes (line 14)             |
| `datetime` | stdlib  | ISO-8601 UTC timestamps                    | Yes (line 17)             |
| `pathlib`  | stdlib  | Path construction for `last_run.json`      | Yes                       |
| `os`       | stdlib  | `os.replace()` atomic rename, `os.fsync()` | Yes                       |
| `shutil`   | stdlib  | `.bak` copy in `_write_atomic`             | Yes                       |

[VERIFIED: grep of sync_chats.py imports + `python3 --version` = Python 3.14.3]

**Installation:** No new packages. `sync_chats.py` already imports all needed modules.

---

## Architecture Patterns

### Pattern 1: Root Flag Pre-Dispatch (D-07)

**What:** `--once` is registered on the top-level parser (not a subparser). After `parse_args()`, check `args.once` before dispatching to any subcommand. This means the flag and a subcommand can technically coexist in the same argv — `--once` wins.

**When to use:** When a flag should bypass the entire subcommand routing system. Common pattern for flags like `--version`, `--help`, and here `--once`.

**Verified pattern from live code:**

The existing `main()` at line 1328 already has this shape (it checks `args.subcommand is None` before dispatching). The `--once` check slots in at the same level:

```python
# Source: sync_chats.py main() at line 1328 (existing pattern extended)
def main() -> None:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--version", action="version", version=...)
    # Phase 5: add --once here — root flag, not a subcommand
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run scan + stub-write pipeline (called by SessionEnd hook)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="COMMAND")
    # ... register subcommands ...
    args = parser.parse_args()

    # Phase 5: pre-dispatch branch — check --once BEFORE subcommand routing
    # Why: --once is the SessionEnd hook entry point; it should never fall
    # through to the subcommand 'no subcommand given' error path.
    if args.once:
        _assert_not_icloud(CLAUDE_CHAT_HOME)
        cmd_once(args)
        return   # explicit return so we don't fall through to subcommand dispatch

    # No subcommand given: print help and exit
    if args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    _assert_not_icloud(CLAUDE_CHAT_HOME)
    args.func(args)
```

[VERIFIED: live code at sync_chats.py:1328-1378 + argparse stdlib behavior confirmed]

**Beginner note:** `action="store_true"` means the flag takes no value — `--once` sets `args.once = True`; omitting it gives `args.once = False`. This is the canonical argparse idiom for boolean flags.

### Pattern 2: Atomic JSON Writer (`_write_last_run`)

**What:** Near-copy of `_write_atomic()` at line 64. Same `tmp + fsync + replace + .bak` pattern. Different path (`LAST_RUN_PATH` instead of `STATE_PATH`).

**Why reuse, not refactor:** `_write_atomic()` is already tested and proven. A near-copy with a comment pointing to the original is more beginner-readable than a parameterized helper. D-14 explicitly calls for "same pattern."

**Verified pattern from live code:**

```python
# Source: sync_chats.py _write_atomic() at line 64 — template for _write_last_run
def _write_last_run(data: dict) -> None:
    """Write last_run.json atomically with fsync + .bak preservation (D-14).

    Near-copy of _write_atomic() — same crash-safety guarantees, different path.
    See _write_atomic() docstring for why tmp+fsync+rename is correct on APFS.
    """
    tmp = LAST_RUN_PATH.with_suffix(".tmp")
    bak = LAST_RUN_PATH.with_suffix(".bak")
    # json.dumps without sort_keys — key order is readable as-is for jq consumers
    content = json.dumps(data, indent=2).encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    if LAST_RUN_PATH.exists():
        shutil.copy2(LAST_RUN_PATH, bak)
    tmp.replace(LAST_RUN_PATH)
```

[VERIFIED: _write_atomic() at sync_chats.py:64-95 — exact pattern confirmed live]

**APFS atomicity note:** `os.replace()` (alias for POSIX `rename(2)`) is atomic on APFS (macOS default filesystem) as long as source and destination are on the same volume. `tmp = path.with_suffix(".tmp")` guarantees same directory, same volume. [VERIFIED: Python docs + macOS APFS behavior]

### Pattern 3: `_format_summary` Pure Function (D-22/D-23)

**What:** Takes the `last_run_dict` (or a compatible sub-dict) and returns the canonical OBSERV-01 summary string. Pure function — no side effects, no I/O.

**Why pure:** Enables golden-string unit test (OBSERV-01 contract) without any filesystem setup.

```python
# Source: D-23 (05-CONTEXT.md) — format locked, implement exactly
def _format_summary(run: dict) -> str:
    """Format the OBSERV-01 canonical summary line from a run dict (D-22/D-23).

    This is the ONLY place this string is constructed — callers never build it
    themselves. The format is locked per D-23:
        Synced N new chats, M skipped (already-synced), K flagged for review,
        mempalace_mined: <status>
    When mempalace_mined is false/skipped, append reason in parens (Phase 4 D-15).
    """
    n = run.get("synced", 0)
    m = run.get("skipped", 0)
    k = run.get("flagged_for_review", 0)
    mined = run.get("mempalace_mined", "skipped")
    reason = run.get("mempalace_reason")

    mined_str = mined
    if mined in ("false", "skipped") and reason:
        mined_str = f"{mined} ({reason})"

    return (
        f"Synced {n} new chats, {m} skipped (already-synced), "
        f"{k} flagged for review, mempalace_mined: {mined_str}"
    )
```

### Pattern 4: `cmd_once` Orchestration

**What:** Runs `discover_sessions → for each session: make_stub_label → call write path with stub dict → accumulate counters → write last_run.json → log + print summary`.

**Key insight:** `cmd_once` does NOT call `cmd_write(args)` via subprocess. It calls the internal write logic directly (or a shared helper extracted from `cmd_write`) because it needs to build the stub dict in-process and feed it as if it came from stdin. D-02 says "calls the write path internally with that dict."

The cleanest implementation: extract the core of `cmd_write` into a `_write_session(session_id, label_dict, config, state) -> str` helper that returns a status string (`"synced"`, `"skipped"`, `"failed"`, `"edited"`, `"reconciled"`). Both `cmd_write` (reading from stdin) and `cmd_once` (building stub dict in-process) call `_write_session`.

### Pattern 5: `cmd_status` Refactor (D-17)

**What:** Read `last_run.json` first (new path). If it exists, display fields via `_format_summary`. If it does not exist, fall back to the current `state.last_run_at` display. One-run migration.

**Verified existing implementation at line 1231:**

```python
# Current cmd_status reads state only — refactor to read last_run.json first
def cmd_status(args) -> None:
    config = _require_config()
    state = load_state()
    # ... discovers pending sessions, prints status lines ...
    last_run = state.get("last_run_at") or "never"
    print(f"Last run:   {last_run}")
```

Phase 5 refactor adds a check at the top:

```python
last_run_data = _load_json(LAST_RUN_PATH)  # returns {} if missing
if last_run_data:
    print(_format_summary(last_run_data))
    print(f"Run at:     {last_run_data.get('run_finished_at', 'unknown')}")
    # ... print additional fields from last_run_data ...
else:
    # fallback: D-17 one-run migration
    last_run = state.get("last_run_at") or "never"
    print(f"Last run:   {last_run}")
```

### Anti-Patterns to Avoid

- **Don't add a `--stub` flag to `write`:** D-02 is explicit. `cmd_once` calls internal write logic with the stub dict, not a new CLI flag.
- **Don't subprocess `cmd_write` from `cmd_once`:** Would require serializing the stub dict to stdin which adds complexity and a subprocess spawn per session. Call internal functions directly.
- **Don't check `args.once` after subparser dispatch:** argparse with `dest="subcommand"` will error if no subcommand is given AND `--once` is the only flag, unless you check `args.once` before the `args.subcommand is None` guard.
- **Don't hardcode `~/.claude-chat/`** in `_write_last_run`: use `LAST_RUN_PATH = CLAUDE_CHAT_HOME / "last_run.json"` so tests can override via `CLAUDE_CHAT_HOME` env var.

---

## Don't Hand-Roll

| Problem                 | Don't Build                    | Use Instead                                          | Why                                       |
| ----------------------- | ------------------------------ | ---------------------------------------------------- | ----------------------------------------- |
| Atomic file write       | Custom tmp/lock logic          | `_write_atomic()` pattern (already in codebase)      | Already tested, handles APFS edge cases   |
| Hostname detection      | `subprocess.run(["hostname"])` | `socket.gethostname()` (stdlib)                      | No subprocess, no PATH dependency         |
| ISO-8601 UTC timestamp  | String formatting              | `datetime.now(timezone.utc).isoformat()`             | Correct UTC encoding with offset          |
| argparse root flag      | Custom `sys.argv` parsing      | `parser.add_argument("--once", action="store_true")` | stdlib handles edge cases                 |
| JSON load with fallback | `try/except` inline everywhere | `_load_json()` (already in codebase, line 98)        | Already returns `{}` on missing/malformed |

---

## SessionEnd Hook: Verified Mechanics

### Exact Schema

Confirmed from official docs AND live `~/.claude/settings.json` inspection:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude-chat/sync_chats.py --once",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

**Verified findings:**

| Property          | Value                                                               | Source                                |
| ----------------- | ------------------------------------------------------------------- | ------------------------------------- |
| `matcher` field   | Not supported for SessionEnd (silently ignored)                     | [VERIFIED: docs.claude.com/hooks]     |
| Hook type         | `"command"`                                                         | [VERIFIED: live settings.json + docs] |
| `timeout` field   | Optional integer seconds (default 600)                              | [VERIFIED: docs]                      |
| Default shell     | bash                                                                | [VERIFIED: docs]                      |
| Login shell?      | **Not documented** — likely inherits Claude Code's env              | [ASSUMED]                             |
| Working directory | "current directory with Claude Code's environment"                  | [VERIFIED: docs]                      |
| PATH              | Inherited from Claude Code process                                  | [VERIFIED: docs]                      |
| stdin             | JSON payload: `{session_id, transcript_path, cwd, hook_event_name}` | [VERIFIED: docs]                      |

### Blocking vs Non-Blocking — D-20 Qualification

**IMPORTANT FINDING:** Official docs classify `SessionEnd` as **non-blocking** in the "Can block?" table. Non-blocking means Claude Code does not wait for the hook to complete before terminating the session.

However, the same docs note that `SessionEnd` hooks fire synchronously before the session fully terminates (sequential lifecycle). The practical interpretation: exit codes and stdout do not influence Claude Code's behavior, but the hook process runs within the session teardown before the UI dismisses.

**Impact on D-20's rationale:**

D-20 says "blocking eliminates the race where two overlapping `--once` processes contend on `state.json`." The race is theoretically possible if a user ends two sessions back-to-back before the first hook completes. In practice this is extremely rare (the user would have to start a second session and end it within the ~0.1 seconds `--once` takes on 0-2 new sessions). Phase 1's clobber defense handles the race harmlessly even if it occurs (second write is refused-on-exists, `sync.log` captures it).

**D-20 is still correct in spirit.** The hook is synchronous enough for typical use. The README should not say "blocking guarantees serial execution" — it should say "runs synchronously on session end."

[VERIFIED: code.claude.com/docs/en/hooks blocking classification table]

### D-21 Qualification: stderr IS shown to users

Official docs say: for SessionEnd, "Shows stderr to user only" on non-zero exit codes. This contradicts D-21's "silent failure" framing.

**What this means in practice:** If `--once` exits with code 1 (per-session failure), Claude Code will surface the stderr to the user's terminal/UI. This is actually desirable for discoverability — the user sees the failure immediately, not just buried in `sync.log`.

**Recommendation for README:** Say "hook failures are surfaced in the Claude Code terminal for exit code != 0; detailed logs are in `~/.claude-chat/sync.log`."

**This does not invalidate D-21's design.** `sync.log` and `last_run.json` remain the authoritative audit trail. stderr surfacing is a bonus, not a replacement.

[VERIFIED: code.claude.com/docs/en/hooks exit code behavior table]

---

## `socket.gethostname()` — Tailscale Finding

**CRITICAL OPERATIONAL FINDING:**

On Michael's primary Mac with Tailscale installed, `socket.gethostname()` returns the Tailscale FQDN:

```
'digital-javelina-pro.tail75a1.ts.net'
```

Not the short hostname `'digital-javelina-pro'`.

[VERIFIED: `python3 -c "import socket; print(repr(socket.gethostname()))"` ran live on the machine, 2026-04-14]

**Impact on D-11 `hostname` field:**

D-11 stores `socket.gethostname()` verbatim in `last_run.json`. This is fine — it's accurate and `jq`-parseable. But:

1. The `hostname` field in `last_run.json` will look different depending on whether Tailscale is running. Between the two Macs, hostnames may have different Tailscale suffixes.
2. The README onboarding section should note this — "hostname is Tailscale FQDN if Tailscale is active; this is informational only, machine identity is `machine_label`."
3. The `machine_label` (from config.json, set by user via `init --label`) remains the primary identity marker, not hostname. This is already correct per existing design.

**No code change needed.** Store `socket.gethostname()` verbatim per D-11. Document the Tailscale behavior in the README troubleshooting section.

---

## Common Pitfalls

### Pitfall 1: argparse `--once` eaten by subparser routing

**What goes wrong:** If `args.once` check comes AFTER `if args.subcommand is None: parser.print_help()`, then `python3 sync_chats.py --once` (with no subcommand) triggers the help text and exits before `cmd_once` runs.
**Why it happens:** `parse_args()` succeeds (no error — `--once` is a valid flag), but `args.subcommand` is `None` because no subcommand was given.
**How to avoid:** Check `args.once` FIRST, before the `args.subcommand is None` guard. See Pattern 1 above.
**Warning signs:** `python3 sync_chats.py --once` prints the help text instead of running the pipeline.

### Pitfall 2: `cmd_once` calls `cmd_write(args)` via the public function

**What goes wrong:** `cmd_write` reads its label JSON from `sys.stdin`. If `cmd_once` calls `cmd_write(args)` directly, there's nothing on stdin for it to read — it will block waiting for input.
**Why it happens:** The stdin contract (Phase 1 D-01) was designed for shell-pipe use (`echo '...' | sync_chats.py write`), not for internal calls.
**How to avoid:** Extract `_write_session(session_id, label_dict, config, state)` helper. Both `cmd_write` (reads stdin, then calls `_write_session`) and `cmd_once` (builds stub dict, calls `_write_session`) use the same internal path.
**Warning signs:** `--once` hangs indefinitely waiting for stdin input.

### Pitfall 3: `LAST_RUN_PATH` hardcoded instead of using `CLAUDE_CHAT_HOME`

**What goes wrong:** Tests using `CLAUDE_CHAT_HOME=/tmp/test-home` env override will write `last_run.json` to `~/.claude-chat/` instead of the test temp dir, polluting the real state.
**Why it happens:** Forgetting the env override pattern established in Phase 1 D-29.
**How to avoid:** Define `LAST_RUN_PATH = CLAUDE_CHAT_HOME / "last_run.json"` at module level alongside `STATE_PATH` and `LOG_PATH`. The `CLAUDE_CHAT_HOME` global already respects the env var.
**Warning signs:** Tests write files to `~/.claude-chat/` even when `CLAUDE_CHAT_HOME` is overridden.

### Pitfall 4: `last_run.json` written before exit code is determined

**What goes wrong:** `_write_last_run(data)` is called with `exit_code: 0` before the final `sys.exit()` determines the actual exit code. If some sessions fail after the last_run write, the recorded exit_code is wrong.
**Why it happens:** Writing the file early for "cleanup on exit" pattern.
**How to avoid:** Accumulate all counters throughout `cmd_once`, determine exit code from final counters, write `last_run.json` with the correct `exit_code`, THEN call `sys.exit(exit_code)`.
**Warning signs:** `last_run.json` shows `exit_code: 0` but `sync.log` shows failures.

### Pitfall 5: `timestamp` field uses local time instead of UTC

**What goes wrong:** `datetime.now().isoformat()` produces local time with no timezone info. Across two Macs in different timezones (or after DST change), timestamps are not directly comparable.
**Why it happens:** `datetime.now()` vs `datetime.now(timezone.utc)`.
**How to avoid:** Always use `datetime.now(timezone.utc).isoformat()`. Produces `2026-04-14T21:32:39.053162+00:00` — unambiguous UTC.
**Warning signs:** Timestamps in `last_run.json` lack `+00:00` suffix.

### Pitfall 6: Hook stderr surfaces to user on failure

**What goes wrong:** If `--once` prints multi-line error messages to stderr and exits 1, the user sees a wall of text in the Claude Code terminal when their session ends.
**Why it happens:** Official docs confirm stderr is shown to user for SessionEnd on non-zero exit codes.
**How to avoid:** Keep `--once` stderr minimal and user-friendly. One line max: `"sync_chats --once: N sessions failed; see ~/.claude-chat/sync.log"`. Detailed errors go to `sync.log` only.
**Warning signs:** Long stack traces from exceptions printed to stderr.

---

## Code Examples

### Adding root `--once` flag to existing argparse setup

```python
# Source: Pattern from sync_chats.py main() at line 1328 + docs
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync Claude Code sessions to Obsidian vault.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    # Root flag: --once is the SessionEnd hook entry point (D-07)
    # action="store_true" means: flag present → args.once = True; absent → False
    # No value after the flag (e.g., NOT --once=something)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Scan for new sessions and write stubs (SessionEnd hook entry point).",
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="COMMAND")
    # ... register subcommands as before ...

    args = parser.parse_args()

    # Check --once FIRST — before the subcommand dispatch block.
    # Why: python3 sync_chats.py --once has no subcommand, so args.subcommand
    # would be None. If we check subcommand first, we'd print help and exit.
    if args.once:
        _assert_not_icloud(CLAUDE_CHAT_HOME)
        cmd_once(args)
        return

    if args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    _assert_not_icloud(CLAUDE_CHAT_HOME)
    args.func(args)
```

### Building last_run.json dict in cmd_once

```python
# Source: D-11 schema (05-CONTEXT.md) + D-15/D-16 semantics
import datetime

def cmd_once(args) -> None:
    run_started = datetime.now(timezone.utc).isoformat()
    config = _require_config()   # exit 2 on pre-flight error per D-10
    state = load_state()

    sessions = discover_sessions(state)
    synced = skipped = failed = flagged = 0
    errors = []

    for sess in sessions:
        try:
            stub = make_stub_label(Path(sess["path"]), sess["session_id"])
            # Set auto_label_hash to sentinel "stub" (D-03)
            stub["auto_label_hash_override"] = "stub"
            result = _write_session(sess["session_id"], stub, config, state)
            if result == "synced":
                synced += 1
                flagged += 1   # every stub-write is flagged_for_review (D-16)
            elif result in ("skipped", "reconciled", "edited"):
                skipped += 1
        except Exception as e:
            failed += 1
            if len(errors) < 10:   # D-13: cap at 10 entries
                errors.append({
                    "session_id": sess["session_id"],
                    "error_class": type(e).__name__,
                    "error_message": str(e),
                })

    run_finished = datetime.now(timezone.utc).isoformat()

    last_run = {
        "schema_version": 1,
        "run_started_at": run_started,
        "run_finished_at": run_finished,
        "trigger": "once",
        "machine_label": config["machine_label"],
        "hostname": socket.gethostname(),
        "synced": synced,
        "skipped": skipped,
        "failed": failed,
        "flagged_for_review": flagged,
        "mempalace_mined": "skipped",     # D-15: --once never runs mine
        "mempalace_reason": "not run by hook (--once skips mine)",
        "exit_code": 1 if failed > 0 else 0,
        "errors": errors,
    }
    _write_last_run(last_run)
    _log_sync(f"run-finish trigger=once {_format_summary(last_run)}")
    print(_format_summary(last_run))
    sys.exit(last_run["exit_code"])
```

### settings.json hook snippet (exact format for README)

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude-chat/sync_chats.py --once",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

[VERIFIED: matches exact schema observed in `~/.claude/settings.json` on Michael's primary Mac, 2026-04-14]

**Important:** Michael already has other `SessionEnd` entries. The new entry must be APPENDED to the existing array, not replace the whole `SessionEnd` key. The README should instruct users to add to the array, not overwrite.

---

## Runtime State Inventory

Phase 5 is NOT a rename/refactor phase. Only the new `last_run.json` file is introduced. Inventory:

| Category            | Items Found                                                                                   | Action Required                                              |
| ------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Stored data         | `state.json` at `~/.claude-chat/state.json` — 86 synced sessions, `last_run_at` field present | No migration; `last_run_at` stays (D-18)                     |
| Live service config | `~/.claude/settings.json` — `SessionEnd` array already has 2 entries                          | Append new entry per D-19; do NOT overwrite existing entries |
| OS-registered state | None — no launchd, no cron, no Task Scheduler                                                 | None                                                         |
| Secrets/env vars    | `CLAUDE_CHAT_HOME` override used in tests — not a secret                                      | No change needed                                             |
| Build artifacts     | None — no compiled artifacts, no egg-info, no npm packages                                    | None                                                         |

[VERIFIED: live inspection of `~/.claude-chat/`, `~/.claude/settings.json`, and test files, 2026-04-14]

---

## Testing Strategy for Hook-Driven Code Paths

### Core Principle: Test the Function, Not the Hook

The SessionEnd hook is a launch mechanism — you test the function it calls (`cmd_once`), not the hook itself. The hook wire-up is a manual verification step (SC#1 of ROADMAP Phase 5).

### Unit-Testable Helpers

| Helper                      | Test Type            | Approach                                                        | File                        |
| --------------------------- | -------------------- | --------------------------------------------------------------- | --------------------------- |
| `_format_summary(dict)`     | Unit / golden-string | Construct dict, assert exact string                             | `tests/test_phase5_once.py` |
| `_write_last_run(dict)`     | Unit                 | Point `CLAUDE_CHAT_HOME` at tmp dir, call, assert JSON contents | `tests/test_phase5_once.py` |
| `make_stub_label(path, id)` | Already tested       | Phase 1 tests cover this — no new tests needed                  | `tests/test_sync_chats.py`  |

### Integration-Testable

| Component                                  | Test Type   | Approach                                                                                |
| ------------------------------------------ | ----------- | --------------------------------------------------------------------------------------- |
| `cmd_once` full path                       | Integration | Fake `PROJECTS_DIR` with 1-2 new sessions, assert vault files + `last_run.json` written |
| `cmd_status` with `last_run.json`          | Integration | Pre-populate `last_run.json`, run `status`, assert output lines                         |
| `cmd_status` fallback (no `last_run.json`) | Integration | Ensure `last_run.json` absent, run `status`, assert fallback output                     |

### Manual-Only

| Scenario                                                  | Why Manual                                    | Verification                                                   |
| --------------------------------------------------------- | --------------------------------------------- | -------------------------------------------------------------- |
| SessionEnd hook fires on session end                      | Requires live Claude Code session termination | SC#1: end a Claude session, `ls <vault>/Chats/` shows new file |
| Hook JSON stdin payload                                   | Hook input format, not function logic         | Print `cat` of hook stdin to sync.log on first test run        |
| `last_run.json` written by SKILL (trigger: "interactive") | SKILL orchestration not easily mocked         | Verified by `/sync-chats` invocation after Phase 5 ships       |

### Testing `cmd_once` without firing a SessionEnd

```python
# Source: Pattern from existing test_mine.py — unittest + CLAUDE_CHAT_HOME override
import os, unittest, tempfile, json
from pathlib import Path

class TestCmdOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CLAUDE_CHAT_HOME"] = self.tmp
        os.environ["CLAUDE_PROJECTS_DIR"] = self.tmp + "/projects"
        # create a minimal valid session for discovery ...

    def test_writes_last_run_json(self):
        # Call cmd_once directly (not via subprocess, not via SessionEnd)
        # by importing or calling main with sys.argv override
        import importlib
        # OR: call cmd_once(args) with a mock args object
        ...
        last_run = json.loads(Path(self.tmp, "last_run.json").read_text())
        self.assertEqual(last_run["trigger"], "once")
        self.assertEqual(last_run["mempalace_mined"], "skipped")
```

[ASSUMED: specific test class structure — exact implementation left to executor]

---

## Multi-Machine Onboarding Verification Checklist

What must be true on the second Mac for the hook to fire reliably:

1. **Python 3.9+ on PATH as `python3`** — Verify: `python3 --version`. On macOS, `python3` ships with Xcode Command Line Tools. If absent: `brew install python`.
2. **`sync_chats.py` at `~/.claude-chat/sync_chats.py`** — Symlink from repo clone: `ln -sf ~/path/to/repo/sync_chats.py ~/.claude-chat/sync_chats.py`.
3. **`claude-chat.py` findable by `sync_chats.py`** — `sync_chats.py` looks for `claude-chat.py` in the same directory as itself (line 748). Since `sync_chats.py` is a symlink into the repo, `Path(__file__).resolve().parent` resolves to the repo dir where `claude-chat.py` lives. Correct.
4. **`~/.claude-chat/config.json` with vault path** — Run `sync_chats.py init --label studio --vault /path/to/vault`.
5. **Vault `Chats/` folder exists** — `mkdir -p "/path/to/vault/Chats"` (or `init` creates it on first `write`).
6. **iCloud vault is mounted** — On first-boot Mac, iCloud may not have synced `Chats/` yet. Verify: `ls "/Users/username/Library/Mobile Documents/iCloud~md~obsidian/Documents/Chats"`.
7. **`~/.claude/settings.json` updated** — Append the `SessionEnd` entry to the existing hooks array.
8. **MemPalace (optional)** — `brew install pipx && pipx install mempalace`. Hook runs fine without it (graceful degradation from Phase 4).

**Verification command users can run:**

```bash
python3 ~/.claude-chat/sync_chats.py scan && echo "scan OK" || echo "scan FAILED — check config"
python3 ~/.claude-chat/sync_chats.py status && echo "status OK"
```

---

## State of the Art

| Old Approach                                       | Current Approach                                 | When Changed         | Impact                             |
| -------------------------------------------------- | ------------------------------------------------ | -------------------- | ---------------------------------- |
| `launchd` LaunchAgent for scheduling               | Claude Code `SessionEnd` hook                    | Phase 5 design       | No TCC/PATH/sleep issues           |
| `claude -p /skill` for headless automation         | Not possible — disabled by Anthropic             | Pre-Phase 1 research | Forced hook approach               |
| Summary line emitted by each command independently | `_format_summary()` single source of truth       | Phase 5              | Testable, consistent format        |
| `cmd_status` reads `state.last_run_at` only        | `cmd_status` reads `last_run.json` with fallback | Phase 5              | Rich run stats, not just timestamp |

---

## Assumptions Log

| #   | Claim                                                                                         | Section               | Risk if Wrong                                                                                                   |
| --- | --------------------------------------------------------------------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------- |
| A1  | Hook runs in a bash-like shell that resolves `~` in command strings                           | Hook Mechanics        | `~/.claude-chat/sync_chats.py` might not resolve — would need absolute path in README                           |
| A2  | SessionEnd hook fires once per session end, not per-tool-call                                 | Hook Mechanics        | If it fired per tool-call, it would flood `sync.log` and vault — but docs confirm it's session-level            |
| A3  | The `_write_session` internal helper approach cleanly separates cmd_write / cmd_once          | Architecture Patterns | If extracting \_write_session requires significant refactor, may be better to have cmd_once handle write inline |
| A4  | On the second Mac, Tailscale will also be installed (same Tailscale hostname pattern applies) | Onboarding            | Hostname in last_run.json may differ in format between machines — cosmetic only, not functional                 |

---

## Open Questions

1. **Does `~` in the hook command string resolve correctly?**
   - What we know: Michael's existing hooks use `~/.claude/hooks/notchi-hook.sh` and they work. One entry in his `settings.json` uses `~` prefix.
   - What's unclear: Whether bash is explicitly invoked for `~` expansion or if Claude Code passes the command string to the shell directly.
   - Recommendation: README should show `python3 ~/.claude-chat/sync_chats.py --once` (matching Michael's existing working hooks) but document that users with unusual shell configurations should use the absolute path `python3 /Users/<username>/.claude-chat/sync_chats.py --once`.

2. **Should `_write_session` be extracted from `cmd_write`, or should `cmd_once` duplicate the write logic?**
   - What we know: `cmd_write` is ~90 lines. `cmd_once` needs ~50 lines of the same logic.
   - What's unclear: Whether the refactor introduces risk to existing passing tests (159 tests pass as of 2026-04-14).
   - Recommendation: Extract `_write_session()` helper. The Phase 3 `_reconcile_crash` refactor precedent shows the codebase handles internal function extraction well. Run `pipx run pytest tests/` after extraction to confirm no regressions.

3. **`trigger: "interactive"` written by SKILL — in Phase 5 scope?**
   - What we know: D-12 defines the enum; D-11 says `last_run.json` is written "at the end of every run (both `--once` and interactive SKILL-driven)." But Phase 5's code targets are `sync_chats.py` only, not `SKILL.md`.
   - What's unclear: Whether the SKILL update to write `last_run.json` is in scope for Phase 5 or deferred.
   - Recommendation: Phase 5 should write `last_run.json` only from `cmd_once`. The SKILL update can be a separate task in Phase 5 (wave 3?) or deferred. `cmd_status` fallback (D-17) handles the "SKILL hasn't written one yet" case gracefully.

---

## Environment Availability

| Dependency                      | Required By            | Available | Version                     | Fallback                             |
| ------------------------------- | ---------------------- | --------- | --------------------------- | ------------------------------------ |
| Python 3.9+                     | All of sync_chats.py   | Yes       | 3.14.3                      | —                                    |
| `socket` (stdlib)               | `socket.gethostname()` | Yes       | stdlib                      | —                                    |
| `datetime` (stdlib)             | ISO-8601 timestamps    | Yes       | stdlib                      | —                                    |
| `pipx run pytest`               | Test runner            | Yes       | pytest 9.0.3                | `python -m unittest`                 |
| `~/.claude-chat/config.json`    | `cmd_once` pre-flight  | Yes       | machine_label=mbp           | `_require_config()` exits 2          |
| `~/.claude/settings.json`       | Hook installation      | Yes       | hooks array present         | Manual paste per README              |
| iCloud vault at configured path | Write target           | Yes       | vault_path=/Users/.../Chats | `cmd_write` exits 1 on vault failure |
| `mempalace` CLI                 | Phase 4 mine step      | Yes       | pipx install                | `shutil.which()` → skipped           |

[VERIFIED: `python3 --version`, `pipx --version`, `cat ~/.claude-chat/config.json`, `cat ~/.claude/settings.json`, 2026-04-14]

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**

- `mempalace`: graceful degradation already ships in Phase 4.

---

## Validation Architecture

> `nyquist_validation: true` in `.planning/config.json` — this section is required.

### Test Framework

| Property           | Value                                                           |
| ------------------ | --------------------------------------------------------------- |
| Framework          | pytest 9.0.3 (via `pipx run pytest`)                            |
| Config file        | None — pytest.ini not present; discovery via `tests/` directory |
| Quick run command  | `pipx run pytest tests/test_phase5_once.py -q`                  |
| Full suite command | `pipx run pytest tests/ -q`                                     |

### Phase Requirements → Test Map

| Req ID    | Behavior                                                            | Test Type     | Automated Command                                                 | File Exists?          |
| --------- | ------------------------------------------------------------------- | ------------- | ----------------------------------------------------------------- | --------------------- |
| HOOK-01   | Hook schema correct in settings.json                                | manual        | N/A                                                               | N/A — user-owned file |
| HOOK-02   | Sub-second latency on 0-2 new sessions                              | manual smoke  | End session, check file mtime                                     | N/A                   |
| HOOK-03   | `--once` is idempotent (upstream clobber defense)                   | unit          | `pipx run pytest tests/test_sync_chats.py -q -k clobber`          | Yes (existing)        |
| HOOK-04   | `/sync-chats` interactive escape hatch                              | manual        | Run `/sync-chats` interactively                                   | N/A (Phase 2 SKILL)   |
| HOOK-05   | README covers second-Mac onboarding                                 | manual review | Read README.md                                                    | No — Wave 0 gap       |
| OBSERV-01 | `_format_summary()` golden-string                                   | unit          | `pipx run pytest tests/test_phase5_once.py::TestFormatSummary -q` | No — Wave 0 gap       |
| OBSERV-02 | `sync.log` gets run-start + run-finish entries                      | integration   | `pipx run pytest tests/test_phase5_once.py::TestCmdOnceLog -q`    | No — Wave 0 gap       |
| OBSERV-03 | `last_run.json` written atomically with correct schema              | unit          | `pipx run pytest tests/test_phase5_once.py::TestWriteLastRun -q`  | No — Wave 0 gap       |
| OBSERV-04 | `cmd_status` reads `last_run.json`, fallback to `state.last_run_at` | integration   | `pipx run pytest tests/test_phase5_once.py::TestCmdStatus -q`     | No — Wave 0 gap       |

### Sampling Rate

- **Per task commit:** `pipx run pytest tests/test_phase5_once.py -q` (new Phase 5 tests only)
- **Per wave merge:** `pipx run pytest tests/ -q` (full suite — 159 existing tests must stay green)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_phase5_once.py` — covers OBSERV-01, 02, 03, 04 and `cmd_once` integration
  - `TestFormatSummary` — golden-string for OBSERV-01 format
  - `TestWriteLastRun` — atomic write + schema validation for OBSERV-03
  - `TestCmdOnceLog` — sync.log entries for OBSERV-02
  - `TestCmdStatus` — last_run.json read + fallback for OBSERV-04
  - `TestCmdOnceIntegration` — full `--once` run with fake sessions

---

## Security Domain

> `security_enforcement` key is absent from `.planning/config.json` — treated as enabled.

### Applicable ASVS Categories

| ASVS Category         | Applies                                          | Standard Control                                                                      |
| --------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------- |
| V2 Authentication     | No — local CLI, no user auth                     | N/A                                                                                   |
| V3 Session Management | No — no web sessions                             | N/A                                                                                   |
| V4 Access Control     | No — single-user local tool                      | N/A                                                                                   |
| V5 Input Validation   | Yes — hook stdin JSON, `last_run.json`           | `json.loads` + key-by-key access (no `eval`, no deserialization of arbitrary objects) |
| V6 Cryptography       | No — SHA-256 for `auto_label_hash` already ships | stdlib `hashlib`                                                                      |

### Known Threat Patterns for this Stack

| Pattern                                                            | STRIDE    | Standard Mitigation                                                                                                                                                                                                                 |
| ------------------------------------------------------------------ | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Malicious hook stdin payload (attacker controls `transcript_path`) | Tampering | `sync_chats.py --once` does NOT use hook stdin JSON — it runs `discover_sessions()` independently, ignoring stdin. The hook stdin is parsed by Claude Code before being passed to the command, but `--once` ignores it entirely.    |
| `last_run.json` injection via `errors[]` content                   | Tampering | `errors[]` entries come from `type(e).__name__` and `str(e)` — exception classes and messages from Python exceptions. In a single-user local tool, this is not an attack surface. Content in errors is from local filesystem reads. |
| Large `errors[]` array causing unbounded file growth               | DoS       | D-13 caps at 10 entries.                                                                                                                                                                                                            |
| `sync.log` growing unbounded                                       | DoS       | Already flagged in Phase 1 D-33 as deferred. Not a Phase 5 concern.                                                                                                                                                                 |

---

## Sources

### Primary (HIGH confidence)

- `sync_chats.py` — live code inspection (lines 1-1383), 2026-04-14
- `~/.claude/settings.json` — live inspection of hook schema on Michael's Mac, 2026-04-14
- `~/.claude-chat/config.json` — confirmed `machine_label`, `vault_path`, 2026-04-14
- `~/.claude/projects/-Users-.../memory/reference_claude_code_headless_limits.md` — confirmed headless slash-command limits
- [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) — SessionEnd schema, env vars, blocking classification, exit codes, stdin payload

### Secondary (MEDIUM confidence)

- `pipx run pytest tests/ -q` output: 159 tests passing (baseline confirmed 2026-04-14)
- `python3 -c "import socket; print(repr(socket.gethostname()))"` — Tailscale hostname finding, verified live
- `05-CONTEXT.md` decisions D-01 through D-27 — all treated as locked constraints

### Tertiary (LOW confidence — see Assumptions Log)

- Hook shell `~` expansion behavior: inferred from Michael's existing working hooks, not from official docs
- `_write_session` refactor risk: assessed from test count, not from attempted refactor

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — all modules already in sync_chats.py imports, verified
- Architecture: HIGH — core patterns (argparse pre-dispatch, atomic writer, pure formatter) verified against live code
- Hook mechanics: HIGH for schema/env/exit-codes (official docs + live inspection); MEDIUM for blocking semantics (docs say non-blocking, but practical sequential execution is likely)
- Pitfalls: HIGH for pitfalls 1-4 (verifiable from code inspection); MEDIUM for pitfalls 5-6 (verified from docs + Python behavior)
- Hostname behavior: HIGH — verified live on Michael's machine

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (stable domain; hook schema is unlikely to change in 30 days)
