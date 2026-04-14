# Phase 4: MemPalace Bulk-Mine Integration - Research

**Researched:** 2026-04-14
**Domain:** Python subprocess shell-out, graceful degradation, CLI integration
**Confidence:** HIGH

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** New standalone `mine` subcommand in `sync_chats.py` (`python3 sync_chats.py mine`). Shells out to `mempalace mine <vault>/Chats --mode convos --extract general` and reports outcome.
- **D-02:** SKILL.md orchestrator calls `mine` as the final step of a sync run. CLI stays single-purpose subcommands; orchestration in the SKILL.
- **D-03:** `mine` is independently callable by hand for manual catch-up and debugging.
- **D-04:** Mine the entire `<vault>/Chats/` directory every invocation. Idempotent-by-design; no per-file tracking.
- **D-05:** `mine` is skipped when zero new files were written in the current run. Reports `mempalace_mined: skipped`.
- **D-06:** Self-healing: if a run's mine fails, the next non-zero-write run re-scans the full directory, catching up missed files. No per-file state tracking.
- **D-07:** Fail-soft: non-zero exit from `mempalace mine` → `mempalace_mined: false`, last ~20 lines of stderr to `sync.log`, sync exits 0. Vault writes succeed regardless.
- **D-08:** Binary-not-found (`shutil.which("mempalace")` returns None) → `mempalace_mined: skipped`, warning `mempalace: command not found — skipping mine` to `sync.log`, sync exits 0.
- **D-09:** Timeout: 300 seconds via `subprocess.run(..., timeout=300)`. On `TimeoutExpired`: kill process, log `mempalace: timed out after 300s — skipping mine`, report `mempalace_mined: false`.
- **D-10:** No retry. Self-healing (D-06) handles transient failures.
- **D-11:** Stderr handling: success is silent. Failures log only last ~20 lines.
- **D-12:** Use `shutil.which("mempalace")` to detect the binary. Primary Mac has real PATH binary at `~/.local/bin/mempalace` (pipx-managed, mempalace 3.3.0). `shutil.which` works correctly.
- **D-13:** No fallback to `python -m mempalace` module invocation. Single-path detection.
- **D-14:** Summary gains one flat line: `mempalace_mined: <true|false|skipped>`. Matches existing key: value summary style.
- **D-15:** On `false` or `skipped`, inline reason shown: e.g. `mempalace_mined: skipped (command not found)` or `mempalace_mined: false (timeout after 300s)`.

### Claude's Discretion

- Exact wording of warning/failure messages in `sync.log` — follow existing `_log_sync` format (sync_chats.py:914).
- Precise stderr truncation length (target ~20 lines, adjust if stderr is line-sparse).
- Where in the existing summary output the `mempalace_mined` line appears (suggest: last line, since it's the last pipeline step).
- Whether to expose timeout/command overrides in `config.json` (default: don't — YAGNI for Phase 4).

### Deferred Ideas (OUT OF SCOPE)

- Configurable timeout / mempalace command path in `config.json`
- Retries on transient failure
- File-list scoping (only mine new files)
- SessionEnd hook wiring (Phase 5)
- `last_run.json` / `status` subcommand integration of mine results (Phase 5)
  </user_constraints>

<phase_requirements>

## Phase Requirements

| ID     | Description                                                                                                                                     | Research Support                                                                              |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| MEM-01 | After all sessions in a sync run are written to vault, shell out exactly once to `mempalace mine <vault>/Chats --mode convos --extract general` | `cmd_mine` function using `subprocess.run` with path from `_require_config()["vault_path"]`   |
| MEM-02 | If `mempalace` CLI absent or fails, sync run continues with warning; vault writes must succeed regardless                                       | `shutil.which` guard + `subprocess.SubprocessError` catch + fail-soft `_log_sync`             |
| MEM-03 | Sync summary includes `mempalace_mined: true\|false\|skipped` line                                                                              | `cmd_mine` prints machine-readable outcome line to stdout; SKILL reads and appends to summary |

</phase_requirements>

---

## Summary

Phase 4 adds a single new subcommand (`mine`) to the existing `sync_chats.py` toolkit. The implementation is straightforward: detect the `mempalace` binary via `shutil.which`, invoke it via `subprocess.run` with a 300-second timeout, and report one of three outcomes — `true` (ran successfully), `false` (ran but failed or timed out), or `skipped` (binary absent or zero new files written). Every error path exits 0 and writes to `sync.log` via the existing `_log_sync` helper.

The SKILL.md orchestrator grows a Step 4 that calls `python3 $HOME/.claude-chat/sync_chats.py mine` after all `write` calls complete, then appends the `mempalace_mined` result to the Step 3 summary line. The SKILL is a per-user file not in the repo (established as D-09 in Phase 2), so the SKILL-touching test class uses `@unittest.skipUnless(_SKILL_PATH.exists(), ...)` to pass CI.

The key complexity is threading the zero-new-files sentinel from SKILL (which knows how many sessions were written) into `cmd_mine` (which only knows the vault path). The cleanest solution: `cmd_mine` accepts an optional `--new-files N` argument; if N is 0, it skips immediately. Alternatively, `cmd_mine` with no argument always runs the mine and the SKILL conditionally skips calling it — both patterns are viable and the choice is Claude's discretion.

**Primary recommendation:** Add `cmd_mine` beside existing subcommands, use `_require_config()` + `_log_sync()` + `subprocess.run(timeout=300)`, pipe outcome back to SKILL via stdout, let SKILL append to summary.

---

## Standard Stack

### Core

| Library      | Version | Purpose                               | Why Standard                                                      |
| ------------ | ------- | ------------------------------------- | ----------------------------------------------------------------- |
| `subprocess` | stdlib  | Shell out to `mempalace` binary       | Only correct way to invoke external process from Python           |
| `shutil`     | stdlib  | `shutil.which()` for binary detection | Portable, reads PATH correctly from Python subprocess environment |

These are already imported in `sync_chats.py` (lines 14–15). [VERIFIED: grep of sync_chats.py imports]

### Supporting

| Library                         | Version | Purpose                                        | When to Use                                                                           |
| ------------------------------- | ------- | ---------------------------------------------- | ------------------------------------------------------------------------------------- |
| `subprocess.TimeoutExpired`     | stdlib  | Catch timeout exception                        | Raised by `subprocess.run(..., timeout=300)` when process exceeds limit               |
| `subprocess.CalledProcessError` | stdlib  | Not used directly — check `returncode` instead | Simpler than raising; `subprocess.run` without `check=True` returns completed process |

**Installation:** No new dependencies. Everything is already in `sync_chats.py`. [VERIFIED: sync_chats.py line 14 `import subprocess`, line 11 `import shutil`]

---

## Architecture Patterns

### Recommended Structure for `cmd_mine`

```
sync_chats.py
├── _log_sync()         # existing — use for all mine warnings/errors
├── _require_config()   # existing — use to get vault_path
├── cmd_mine(args)      # NEW — add beside cmd_init/cmd_scan/cmd_write/cmd_status
└── main()              # add "mine" subparser, same pattern as existing subcommands
```

### Pattern 1: Binary Detection + Graceful Degradation

**What:** Check for the binary before attempting to run it. If absent, log and return `skipped`.
**When to use:** Any external tool invocation where the tool is optional.

```python
# Source: D-12/D-13 locked decisions; shutil docs [CITED: docs.python.org/3/library/shutil.html#shutil.which]
import shutil

def cmd_mine(args) -> None:
    config = _require_config()
    vault_chats = str(Path(config["vault_path"]) / "Chats")

    # D-08: Binary not found → skipped (not false)
    if shutil.which("mempalace") is None:
        _log_sync("mempalace: command not found — skipping mine")
        print("mempalace_mined: skipped (command not found)")
        return
```

**Why `shutil.which` works here:** After the 2026-04-14 alias→pipx migration, `~/.local/bin/mempalace` is a real symlink. Python's `shutil.which` searches the process's `PATH` env var — confirmed to include `~/.local/bin` on the primary Mac. On a second Mac without `pipx install mempalace`, `shutil.which` returns `None` as expected. [VERIFIED: live test `python3 -c "import shutil; print(shutil.which('mempalace'))"` → `/Users/michaelhenry/.local/bin/mempalace`]

### Pattern 2: subprocess.run with Timeout

**What:** Invoke external process, capture stderr for failure logging, check returncode.
**When to use:** Any external CLI shell-out where you need to distinguish success/failure/timeout.

```python
# Source: D-07/D-09 locked decisions; subprocess docs [CITED: docs.python.org/3/library/subprocess.html]
import subprocess

try:
    result = subprocess.run(
        ["mempalace", "mine", vault_chats, "--mode", "convos", "--extract", "general"],
        capture_output=True,   # captures both stdout and stderr
        text=True,             # decodes bytes → str automatically
        timeout=300,           # D-09: 5 minute timeout
    )
except subprocess.TimeoutExpired as e:
    # D-09: kill is automatic when TimeoutExpired is raised by subprocess.run
    _log_sync("mempalace: timed out after 300s — skipping mine")
    print("mempalace_mined: false (timeout after 300s)")
    return

if result.returncode != 0:
    # D-07: log last ~20 lines of stderr, report false
    stderr_tail = "\n".join(result.stderr.splitlines()[-20:])
    _log_sync(f"mempalace mine failed (exit {result.returncode}):\n{stderr_tail}")
    print("mempalace_mined: false (non-zero exit)")
    return

print("mempalace_mined: true")
```

**Python beginner note:** `capture_output=True` is shorthand for `stdout=subprocess.PIPE, stderr=subprocess.PIPE`. `text=True` means subprocess decodes bytes to strings using the system encoding — no `.decode()` call needed. `result.stderr.splitlines()[-20:]` slices the last 20 lines of a list.

### Pattern 3: Registering the new subcommand

Follows the exact existing pattern at sync_chats.py:1282-1299. [VERIFIED: read sync_chats.py lines 1282–1299]

```python
# Source: sync_chats.py:1282-1299 [VERIFIED]
# Add after the p_status block, before args = parser.parse_args()

# mine subcommand
p_mine = subparsers.add_parser("mine", help="Mine vault Chats/ into MemPalace (post-run step)")
p_mine.set_defaults(func=cmd_mine)
```

No arguments needed for the basic case. The `--new-files` optional arg (for zero-write skip) is discretionary — see Open Questions.

### Pattern 4: SKILL.md Step 4 (mine invocation)

The SKILL currently ends at Step 3 (print summary). Add Step 4 after the summary:

```bash
# Step 4 — Mine vault into MemPalace (post-run)
python3 $HOME/.claude-chat/sync_chats.py mine
```

Capture the `mempalace_mined: ...` stdout line and append to the Step 3 summary. The SKILL already knows how many sessions were labeled (M counter from Step 2), so it can decide whether to skip calling `mine` when M == 0 (zero new files). That conditional can live in the SKILL rather than requiring a `--new-files` argument to `cmd_mine`.

### Anti-Patterns to Avoid

- **Checking for `mempalace` via `os.path.exists(os.path.expanduser("~/.local/bin/mempalace"))`:** Hard-codes a path that won't work on second Mac. Use `shutil.which("mempalace")` — it's portable and reads PATH correctly. [VERIFIED: D-12/D-13]
- **Using `subprocess.run(check=True)` and letting exception propagate:** Violates fail-soft requirement (D-07). Always check `returncode` manually and handle gracefully.
- **Piping `capture_output=True` without `text=True`:** Gives bytes objects. `stderr.splitlines()[-20:]` on bytes works but requires `.decode()`. Set `text=True` to stay consistent with the rest of the codebase.
- **Running `mine` in every SKILL invocation unconditionally:** If zero sessions were written (e.g., all skipped), running a full-directory scan is wasted work (D-05). The zero-write skip must fire.

---

## Don't Hand-Roll

| Problem          | Don't Build                     | Use Instead                               | Why                                                                       |
| ---------------- | ------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------- |
| Binary detection | Custom PATH-scanning loop       | `shutil.which("mempalace")`               | Handles PATH, symlinks, permissions check; stdlib                         |
| Process timeout  | `threading.Timer` + manual kill | `subprocess.run(..., timeout=300)`        | `subprocess.run` kills the process automatically on `TimeoutExpired`      |
| Stderr capture   | Redirect stderr to a temp file  | `capture_output=True`                     | Built into `subprocess.run` since Python 3.7                              |
| Log append       | Open/close in every log call    | `_log_sync(message)` at sync_chats.py:914 | Already handles directory creation, timestamp, append-only semantics      |
| Config loading   | Re-implement JSON read          | `_require_config()` at sync_chats.py:156  | Already handles missing config with correct error message and exit code 2 |

---

## Common Pitfalls

### Pitfall 1: zsh alias vs PATH binary

**What goes wrong:** On the primary Mac, `which mempalace` in a zsh interactive shell (and the old zsh alias) reports the alias. But Python's `shutil.which` consults the process's `PATH` env var, not the shell's aliases. Before the 2026-04-14 alias→pipx migration, `shutil.which("mempalace")` would have returned `None` even though `mempalace` "worked" in a terminal.
**Why it happens:** zsh aliases are shell-only; they don't exist in subprocess environments.
**How to avoid:** The pipx migration is already done. `shutil.which` now works. Do not add a fallback to `python -m mempalace` (D-13 explicitly forbids it).
**Warning signs:** `shutil.which("mempalace")` returns None on a machine where `mempalace --version` works interactively → means it's still alias-only, needs pipx install. [VERIFIED: live machine test confirmed `shutil.which` → `~/.local/bin/mempalace`]

### Pitfall 2: TimeoutExpired does NOT kill the process automatically in all Python versions

**What goes wrong:** In Python < 3.3, `TimeoutExpired` is not available. In Python 3.3+, `subprocess.run` with `timeout=` raises `TimeoutExpired` but in older versions the child process may persist as a zombie.
**How to avoid:** This project runs Python 3.14 (`python3 --version` → 3.14.3). [VERIFIED: live check] `subprocess.run` in Python 3.3+ handles process cleanup on timeout. No manual `process.kill()` needed.

### Pitfall 3: stdout from cmd_mine collides with other output

**What goes wrong:** If `cmd_mine` prints both diagnostic text AND the `mempalace_mined: ...` outcome line, the SKILL has to parse which line is the outcome.
**How to avoid:** Make the outcome line the ONLY stdout from `cmd_mine`. All diagnostic/error info goes to stderr or `sync.log`. This matches the pattern in `cmd_write` (only "Wrote: path" or "skipped: ..." goes to stdout; errors go to stderr).

### Pitfall 4: Zero-write skip not threaded correctly

**What goes wrong:** `cmd_mine` has no way to know how many files were written in the current run — that information lives in the SKILL. If `cmd_mine` always runs the mine regardless, it wastes time mining an unchanged vault.
**How to avoid:** Two options (both viable — see Open Questions). Either the SKILL conditionally calls `mine` only when write count > 0, or `cmd_mine` accepts `--new-files N` and skips when N=0. The SKILL approach is simpler (no new CLI flag needed).

### Pitfall 5: `mempalace mine` stderr leaking secrets

**What goes wrong:** If mempalace emits input content in its error messages (e.g., "failed to parse: <chat content>"), logging the last 20 lines of stderr could leak scrubbed content back into sync.log.
**How to avoid:** Log stderr tail only on failure (not on success). This is already in D-11. The risk is low because mempalace processes already-scrubbed vault files, not raw JSONL. [ASSUMED: mempalace error messages don't echo file content; not verified against mempalace source]

---

## Code Examples

Verified patterns from existing codebase:

### Existing `_log_sync` helper

```python
# Source: sync_chats.py:914-924 [VERIFIED]
def _log_sync(message: str) -> None:
    os.makedirs(str(LOG_PATH.parent), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
```

### Existing subcommand registration pattern

```python
# Source: sync_chats.py:1282-1299 [VERIFIED]
p_status = subparsers.add_parser("status", help="Show sync status summary")
p_status.set_defaults(func=cmd_status)
# New mine entry follows identical pattern immediately after
```

### Existing `_require_config()` + vault path access

```python
# Source: sync_chats.py:156-168, config schema confirmed via ~/.claude-chat/config.json [VERIFIED]
config = _require_config()
vault_chats = str(Path(config["vault_path"]) / "Chats")
# config["vault_path"] == "/Users/michaelhenry/Library/Mobile Documents/iCloud~md~obsidian/Documents/Chats"
# vault_chats == "/Users/michaelhenry/Library/Mobile Documents/iCloud~md~obsidian/Documents/Chats/Chats"
# NOTE: vault_path is already the vault ROOT; Chats/ is a subfolder one level inside
```

**Important:** `config["vault_path"]` is the Obsidian vault root. The Chats folder is `<vault_path>/Chats`. The `mempalace mine` target is `config["vault_path"] + "/Chats"`, NOT `config["vault_path"]`. [VERIFIED: config.json read, directory convention established in Phase 1 `_resolve_vault_filename`]

### Existing SKILL Step 3 summary format (before Phase 4 addition)

```
# Source: ~/.claude/skills/sync-chats/SKILL.md Step 3 [VERIFIED]
Processed N sessions: M labeled, K stubbed, J skipped (ultra-short).
```

Phase 4 adds `mempalace_mined: <status>` as a separate output line after this (or the SKILL appends it inline). D-14 says flat key: value format matching existing summary style.

### Full `cmd_mine` skeleton

```python
# [ASSEMBLED from D-07 through D-15 locked decisions + verified stdlib patterns]
def cmd_mine(args) -> None:
    """Shell out to mempalace mine after a sync run (MEM-01/02/03).

    Reports one of three outcomes via stdout:
      mempalace_mined: true
      mempalace_mined: false (<reason>)
      mempalace_mined: skipped (<reason>)
    """
    config = _require_config()
    vault_chats = str(Path(config["vault_path"]) / "Chats")

    # D-08: binary not found → skipped
    if shutil.which("mempalace") is None:
        _log_sync("mempalace: command not found — skipping mine")
        print("mempalace_mined: skipped (command not found)")
        return

    try:
        result = subprocess.run(
            ["mempalace", "mine", vault_chats, "--mode", "convos", "--extract", "general"],
            capture_output=True,
            text=True,
            timeout=300,           # D-09
        )
    except subprocess.TimeoutExpired:
        _log_sync("mempalace: timed out after 300s — skipping mine")
        print("mempalace_mined: false (timeout after 300s)")
        return

    if result.returncode != 0:
        # D-07/D-11: log last ~20 lines of stderr only
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:])
        _log_sync(f"mempalace mine failed (exit {result.returncode}):\n{stderr_tail}")
        print(f"mempalace_mined: false (exit {result.returncode})")
        return

    print("mempalace_mined: true")
```

---

## State of the Art

| Old Approach                                                 | Current Approach                                         | When Changed                      | Impact                                                                |
| ------------------------------------------------------------ | -------------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------- |
| zsh alias only (`alias mempalace='python3.13 -m mempalace'`) | pipx PATH binary at `~/.local/bin/mempalace`             | 2026-04-14                        | `shutil.which("mempalace")` now works; no `python -m` fallback needed |
| Per-chat MCP calls to `mempalace_kg_add`                     | One bulk `mempalace mine --mode convos` after all writes | Design decision (Phase 4 CONTEXT) | Simpler; idempotent; no per-chat retry logic                          |

**Deprecated/outdated:**

- `alias mempalace=...` pattern in `~/.zshrc`: removed 2026-04-14. The alias still shows in interactive shell sessions (zsh re-reads `.zshrc` on each interactive start) but the canonical binary is now the pipx one. Do not re-add the alias fallback.

---

## Validation Architecture

### Test Framework

| Property           | Value                                       |
| ------------------ | ------------------------------------------- |
| Framework          | `unittest` (stdlib)                         |
| Config file        | none — `python3 -m unittest discover tests` |
| Quick run command  | `pipx run pytest tests/test_mine.py -v`     |
| Full suite command | `python3 -m unittest discover tests -v`     |

**Note on test runner:** The project uses `python3 -m unittest` for CI (see `.github/workflows/canary.yml`) but tests are compatible with pytest (confirmed by `test_phase2_labels.py` docstring). `pipx run pytest` is the local convenience runner per project memory (`feedback_pytest_pipx.md`). New Phase 4 tests should be `unittest.TestCase` classes so they run in both contexts.

### Phase Requirements → Test Map

| Req ID | Behavior                                                                 | Test Type           | Automated Command                                                                           | File Exists? |
| ------ | ------------------------------------------------------------------------ | ------------------- | ------------------------------------------------------------------------------------------- | ------------ |
| MEM-01 | `cmd_mine` calls `subprocess.run` with correct command and target dir    | unit                | `pipx run pytest tests/test_mine.py::TestCmdMine::test_runs_correct_command -x`             | ❌ Wave 0    |
| MEM-01 | `cmd_mine` reads vault path from config, not hardcoded                   | unit                | `pipx run pytest tests/test_mine.py::TestCmdMine::test_vault_path_from_config -x`           | ❌ Wave 0    |
| MEM-02 | Binary absent → exits 0, prints `skipped`, logs to sync.log              | unit                | `pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg::test_binary_absent_skipped -x` | ❌ Wave 0    |
| MEM-02 | Non-zero exit from mempalace → exits 0, prints `false`, logs stderr tail | unit                | `pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg::test_nonzero_exit_false -x`    | ❌ Wave 0    |
| MEM-02 | TimeoutExpired → exits 0, prints `false (timeout)`, logs                 | unit                | `pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg::test_timeout_false -x`         | ❌ Wave 0    |
| MEM-03 | Stdout includes `mempalace_mined: true` on success                       | unit                | `pipx run pytest tests/test_mine.py::TestCmdMineSummary::test_true_on_success -x`           | ❌ Wave 0    |
| MEM-03 | Stdout includes `mempalace_mined: skipped (command not found)`           | unit                | `pipx run pytest tests/test_mine.py::TestCmdMineSummary::test_skipped_with_reason -x`       | ❌ Wave 0    |
| MEM-03 | SKILL.md Step 4 present and appends mine outcome to summary              | manual / SKILL test | `@skipUnless(_SKILL_PATH.exists(), ...)` class in test_mine.py                              | ❌ Wave 0    |

### Sampling Rate

- **Per task commit:** `pipx run pytest tests/test_mine.py -v`
- **Per wave merge:** `python3 -m unittest discover tests -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_mine.py` — all Phase 4 unit tests (`TestCmdMine`, `TestCmdMineGracefulDeg`, `TestCmdMineSummary`, `TestSkillMineStep`)
- [ ] No framework install needed — unittest is stdlib, pytest available via `pipx run pytest`

---

## Integration Map: Where `mine` Hooks In

The pipeline after Phase 4 is:

```
SKILL Step 1: scan
SKILL Step 2: for each session → label → write (cmd_write)
SKILL Step 3: print session summary
SKILL Step 4: call cmd_mine [NEW]  ← only if write count > 0
              append mempalace_mined line to summary output
```

`cmd_mine` is a CLI subcommand. The SKILL calls it. There is no direct call from `cmd_write` to `cmd_mine` — they are independent subcommands, and ordering is the SKILL's responsibility (D-02).

**Zero-write skip (D-05) placement:** The SKILL knows the write count (M from Step 2). The cleanest implementation: the SKILL conditionally skips calling `mine` when M == 0 (zero labeled + zero stubbed sessions were written), printing `mempalace_mined: skipped (no new files)` inline. This avoids adding any new argument to `cmd_mine`. `cmd_mine` itself always runs the mine when called — the SKILL is responsible for the "should we even bother?" gate.

---

## Environment Availability

| Dependency            | Required By          | Available | Version                                    | Fallback               |
| --------------------- | -------------------- | --------- | ------------------------------------------ | ---------------------- |
| `mempalace` binary    | MEM-01/02 mine step  | ✓         | 3.3.0 via pipx at `~/.local/bin/mempalace` | Graceful skip (MEM-02) |
| `python3`             | All of sync_chats.py | ✓         | 3.14.3                                     | —                      |
| `subprocess` (stdlib) | cmd_mine             | ✓         | stdlib                                     | —                      |
| `shutil` (stdlib)     | cmd_mine detection   | ✓         | stdlib, already imported                   | —                      |

[VERIFIED: `python3 -c "import shutil; print(shutil.which('mempalace'))"` → `/Users/michaelhenry/.local/bin/mempalace`; `pipx list` → `mempalace 3.3.0`]

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** `mempalace` on second Mac — graceful skip per MEM-02.

---

## Security Domain

> `security_enforcement` not explicitly set to false — included.

### Applicable ASVS Categories

| ASVS Category         | Applies          | Standard Control                                                                                            |
| --------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------- |
| V2 Authentication     | no               | —                                                                                                           |
| V3 Session Management | no               | —                                                                                                           |
| V4 Access Control     | no               | —                                                                                                           |
| V5 Input Validation   | yes (vault path) | `_require_config()` validates path via existing init guard; vault path is user-owned config, not user input |
| V6 Cryptography       | no               | —                                                                                                           |

### Known Threat Patterns for subprocess shell-out

| Pattern                               | STRIDE                 | Standard Mitigation                                                                                                                                                                                                   |
| ------------------------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Command injection via vault_path      | Tampering              | Vault path comes from `config.json` written by `cmd_init` with validated absolute path — not from user CLI input at `mine` runtime. Pass as list to `subprocess.run`, not shell string — no shell injection possible. |
| PII in stderr tail logged to sync.log | Information disclosure | mempalace processes already-scrubbed vault files. Risk is low. Log only on failure (D-11).                                                                                                                            |
| Process escape via timeout            | DoS                    | 300s timeout enforced; `TimeoutExpired` kills child process.                                                                                                                                                          |

**subprocess.run list form vs shell=True:** Always use list form (`["mempalace", "mine", vault_chats, ...]`) not `shell=True` with a string. List form bypasses shell interpretation entirely — no injection possible even if vault_path somehow contained shell metacharacters. [CITED: docs.python.org/3/library/subprocess.html#security-considerations]

---

## Assumptions Log

| #   | Claim                                                                                                                                                     | Section            | Risk if Wrong                                                                                                                               |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| A1  | `mempalace mine` stderr does not echo file content in error messages                                                                                      | Common Pitfalls §5 | sync.log could leak partial chat content on failure. Mitigation: log only last 20 lines (D-11) limits blast radius.                         |
| A2  | mempalace 3.3.0 accepts `--mode convos --extract general` flags (verified in reference memory but not re-tested against installed binary in this session) | Standard Stack     | mine command fails if flags changed between 3.0.14 (reference memory version) and 3.3.0. Planner should verify via `mempalace mine --help`. |

---

## Open Questions

1. **Zero-write skip: SKILL-side conditional vs `--new-files` arg to `cmd_mine`**
   - What we know: D-05 says `mine` is skipped when zero new files written. SKILL knows the write count; `cmd_mine` does not.
   - What's unclear: Whether to put the skip logic in the SKILL (simpler, no new CLI arg) or add `--new-files N` to `cmd_mine` (more testable in isolation).
   - Recommendation: SKILL-side conditional. Keeps `cmd_mine` simple (always mines when called), makes it easy to test the SKILL's conditional separately. The SKILL already has the write count in its M/K counters.

2. **`mempalace mine --help` flag verification for 3.3.0**
   - What we know: Reference memory confirms `--mode convos --extract general` was correct as of 3.0.14 (2026-04-10).
   - What's unclear: Whether 3.3.0 changed any flag names.
   - Recommendation: Planner or executor should run `mempalace mine --help` and confirm flags before writing the subprocess call.

---

## Sources

### Primary (HIGH confidence)

- `sync_chats.py` (project codebase) — `_log_sync` at line 914, `_require_config` at line 156, argparse pattern at lines 1268–1299, imports at lines 14–15
- `~/.claude-chat/config.json` — verified schema: `machine_label`, `vault_path`, `schema_version`
- `~/.claude/skills/sync-chats/SKILL.md` — current SKILL structure, Step 3 summary format
- Live binary check: `python3 -c "import shutil; print(shutil.which('mempalace'))"` → `/Users/michaelhenry/.local/bin/mempalace`
- Live version check: `pipx list` → `mempalace 3.3.0`
- `tests/` directory listing — test file inventory, `@skipUnless` pattern in `test_phase2_labels.py`
- `.github/workflows/canary.yml` — CI runs `python3 -m unittest discover tests -v`, zero deps

### Secondary (MEDIUM confidence)

- `reference_mempalace_bulk_mine.md` — confirmed CLI flags `--mode convos --extract general`, idempotency contract, graceful-degradation pattern, pipx migration note
- Python docs `subprocess.run` — `capture_output`, `text`, `timeout`, `TimeoutExpired` behavior [CITED: docs.python.org/3/library/subprocess.html]
- Python docs `shutil.which` — PATH-based binary lookup [CITED: docs.python.org/3/library/shutil.html#shutil.which]

### Tertiary (LOW confidence)

- A2 assumption: mempalace 3.3.0 flag names match 3.0.14 — not independently verified in this session

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — both subprocess and shutil are stdlib, already imported in the file
- Architecture: HIGH — all integration points verified by reading actual source code
- Pitfalls: HIGH for known issues (alias vs PATH, binary detection); MEDIUM for mempalace stderr content assumption
- Test structure: HIGH — existing test patterns in tests/ directory verified

**Research date:** 2026-04-14
**Valid until:** 2026-07-14 (stable stdlib patterns; mempalace flag names could change on major version bump)
