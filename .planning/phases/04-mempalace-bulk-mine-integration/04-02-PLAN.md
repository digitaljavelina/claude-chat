---
phase: 04-mempalace-bulk-mine-integration
plan: 02
type: execute
wave: 2
depends_on:
  - "04-01"
files_modified:
  - sync_chats.py
  - tests/test_mine.py
autonomous: true
requirements:
  - MEM-02
must_haves:
  truths:
    - "When `shutil.which('mempalace')` returns None, cmd_mine prints `mempalace_mined: skipped (command not found)`, writes a warning to sync.log, and returns without raising"
    - "When `mempalace mine` exits non-zero, cmd_mine prints `mempalace_mined: false (exit N)`, writes the last 20 lines of stderr to sync.log, and returns without raising"
    - "When `subprocess.run` raises TimeoutExpired (300s), cmd_mine prints `mempalace_mined: false (timeout after 300s)`, writes a timeout warning to sync.log, and returns without raising"
    - "Process exit code from cmd_mine is always 0 (fail-soft); sync pipeline continues regardless"
  artifacts:
    - path: "sync_chats.py"
      provides: "cmd_mine with full graceful-degradation branches"
      contains: "except subprocess.TimeoutExpired"
    - path: "tests/test_mine.py"
      provides: "Three graceful-degradation tests green (4-02-01, 4-02-02, 4-02-03)"
      contains: "class TestCmdMineGracefulDeg"
  key_links:
    - from: "sync_chats.py::cmd_mine"
      to: "sync_chats.py::_log_sync"
      via: "warning/error message append on every non-success path"
      pattern: "_log_sync\\("
    - from: "sync_chats.py::cmd_mine"
      to: "subprocess.TimeoutExpired handler"
      via: "try/except around subprocess.run"
      pattern: "except subprocess\\.TimeoutExpired"
---

<objective>
Harden `cmd_mine` with the three graceful-degradation branches required by MEM-02: missing binary (D-08), non-zero exit (D-07, D-11), and TimeoutExpired (D-09). Every failure path writes to `sync.log` via the existing `_log_sync` helper and returns cleanly — the process exit code from `cmd_mine` is always 0, so the SKILL's sync pipeline continues regardless.

Purpose: Fulfill MEM-02 ("If `mempalace` CLI absent or fails, sync run continues with warning; vault writes must succeed regardless"). Also mitigate threats T-4-02 (availability under missing binary), T-4-03 (info-disclosure via stderr tail), and T-4-04 (DoS via hung process).

Output:

- Refactored `cmd_mine` with `try/except subprocess.TimeoutExpired`, non-zero `returncode` branch, and `_log_sync` calls on every non-success path
- Three graceful-degradation tests (`TestCmdMineGracefulDeg`) green
- `sync.log` receives stderr-tail on failure only, max ~20 lines (D-11)
  </objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-mempalace-bulk-mine-integration/04-CONTEXT.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-RESEARCH.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-VALIDATION.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-01-SUMMARY.md
@sync_chats.py
@tests/test_mine.py

<interfaces>
<!-- From Plan 01 (already implemented) -->

```python
# sync_chats.py
def cmd_mine(args) -> None:
    config = _require_config()
    vault_chats = str(Path(config["vault_path"]) / "Chats")
    if shutil.which("mempalace") is None:
        print("mempalace_mined: skipped (command not found)")
        return
    result = subprocess.run(
        ["mempalace", "mine", vault_chats, "--mode", "convos", "--extract", "general"],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode == 0:
        print("mempalace_mined: true")
    else:
        print(f"mempalace_mined: false (exit {result.returncode})")

# _log_sync(message: str) -> None  # at ~line 914; UTC-timestamped append to ~/.claude-chat/sync.log
```

</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 4-02-01: Binary absent → skipped + sync.log warning (MEM-02, T-4-02)</name>
  <files>sync_chats.py, tests/test_mine.py</files>
  <behavior>
    - Test 4-02-01 (`TestCmdMineGracefulDeg.test_binary_absent_skipped`): When `shutil.which` returns None, cmd_mine prints exactly `mempalace_mined: skipped (command not found)`, calls `_log_sync` with a message containing "mempalace" and "not found", does NOT invoke subprocess.run, and returns None (never raises).
  </behavior>
  <action>
**Part A — Add `_log_sync` call to the existing skipped branch in `cmd_mine`:**

In `sync_chats.py`, update the `shutil.which` miss branch to also log. Python beginner note: the `is None` comparison is the idiomatic test here — `shutil.which` returns either a path string or `None`, not a falsy empty string.

Change:

```python
    if shutil.which("mempalace") is None:
        print("mempalace_mined: skipped (command not found)")
        return
```

to:

```python
    if shutil.which("mempalace") is None:
        # D-08: binary not found is "skipped" (three-state MEM-03), not "false".
        # T-4-02 mitigation: graceful degradation — second Mac without mempalace
        # installed still completes sync; vault writes succeed regardless.
        _log_sync("mempalace: command not found — skipping mine")
        print("mempalace_mined: skipped (command not found)")
        return
```

**Part B — Un-skip and implement test 4-02-01:**

```python
def test_binary_absent_skipped(self):
    """MEM-02: binary-not-found → exit 0, skipped outcome, sync.log warning, no subprocess call."""
    fake_args = argparse.Namespace()

    with patch("sync_chats.shutil.which", return_value=None), \
         patch("sync_chats._require_config", return_value={
             "vault_path": "/tmp/fake-vault", "machine_label": "t", "schema_version": 1,
         }), \
         patch("sync_chats._log_sync") as mock_log, \
         patch("sync_chats.subprocess.run") as mock_run, \
         patch("builtins.print") as mock_print:
        sync_chats.cmd_mine(fake_args)

    # No subprocess invocation when binary is absent
    mock_run.assert_not_called()
    # Exact stdout format (D-14/D-15)
    mock_print.assert_called_once_with("mempalace_mined: skipped (command not found)")
    # Sync log mentions mempalace + not found (exact wording is Claude's discretion per CONTEXT.md)
    mock_log.assert_called_once()
    log_msg = mock_log.call_args[0][0]
    self.assertIn("mempalace", log_msg)
    self.assertIn("not found", log_msg)
```

  </action>
  <verify>
    <automated>pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg::test_binary_absent_skipped -xvs</automated>
  </verify>
  <done>Test green. `cmd_mine` writes to sync.log on missing binary. Exit code 0.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4-02-02: Non-zero exit → false + stderr tail to sync.log (MEM-02, D-07, D-11)</name>
  <files>sync_chats.py, tests/test_mine.py</files>
  <behavior>
    - Test 4-02-02 (`TestCmdMineGracefulDeg.test_nonzero_exit_false`): When `subprocess.run` returns `returncode=2` with stderr containing 30 newline-separated lines of fake error text, cmd_mine prints `mempalace_mined: false (exit 2)`, calls `_log_sync` once with a message that contains the last 20 stderr lines (not the first 10), and returns None without raising.
  </behavior>
  <action>
**Part A — Replace the `else` branch in `cmd_mine` with the full non-zero handler:**

Change:

```python
    if result.returncode == 0:
        print("mempalace_mined: true")
    else:
        print(f"mempalace_mined: false (exit {result.returncode})")
```

to:

```python
    if result.returncode != 0:
        # D-07: fail-soft. D-11: log only on failure, only last ~20 lines,
        # to avoid polluting sync.log on healthy runs and to bound info-disclosure
        # blast radius if mempalace ever echoed content in its errors (T-4-03).
        # Python idiom: splitlines()[-20:] slices the last 20 lines of a list.
        # If stderr has <20 lines, slicing returns what's there — no IndexError.
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:])
        _log_sync(f"mempalace mine failed (exit {result.returncode}):\n{stderr_tail}")
        print(f"mempalace_mined: false (exit {result.returncode})")
        return

    print("mempalace_mined: true")
```

Rationale for the inverted-guard shape (`if != 0: ...; return` then `print true`): matches the early-return style already used in the `shutil.which` block and reads top-to-bottom as failure-then-success. Functionally equivalent to the if/else version.

**Part B — Un-skip and implement test 4-02-02:**

```python
def test_nonzero_exit_false(self):
    """MEM-02 / D-07 / D-11: non-zero exit → false outcome, last 20 stderr lines logged."""
    fake_args = argparse.Namespace()
    # 30 lines so we can prove slicing takes the last 20, not the first 10.
    stderr_lines = [f"err line {i}" for i in range(30)]
    fake_stderr = "\n".join(stderr_lines)

    with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), \
         patch("sync_chats._require_config", return_value={
             "vault_path": "/tmp/fake-vault", "machine_label": "t", "schema_version": 1,
         }), \
         patch("sync_chats.subprocess.run") as mock_run, \
         patch("sync_chats._log_sync") as mock_log, \
         patch("builtins.print") as mock_print:
        mock_run.return_value = MagicMock(returncode=2, stdout="", stderr=fake_stderr)
        sync_chats.cmd_mine(fake_args)

    mock_print.assert_called_once_with("mempalace_mined: false (exit 2)")
    mock_log.assert_called_once()
    logged = mock_log.call_args[0][0]
    # Last 20 lines present
    self.assertIn("err line 29", logged)
    self.assertIn("err line 10", logged)
    # First 10 lines NOT present (proves slicing is [-20:], not [:20])
    self.assertNotIn("err line 0\n", logged)
    self.assertNotIn("err line 9\n", logged)
```

Python beginner note: `"err line 0\n"` with the trailing newline avoids matching "err line 0" as a substring of "err line 10", "err line 20", etc.
</action>
<verify>
<automated>pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg::test_nonzero_exit_false -xvs</automated>
</verify>
<done>Test green. `cmd_mine` logs stderr tail (last 20 lines) on non-zero exit. Exit code 0.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4-02-03: TimeoutExpired → false + sync.log warning (MEM-02, D-09, T-4-04)</name>
  <files>sync_chats.py, tests/test_mine.py</files>
  <behavior>
    - Test 4-02-03 (`TestCmdMineGracefulDeg.test_timeout_false`): When `subprocess.run` raises `subprocess.TimeoutExpired`, cmd_mine catches it, prints `mempalace_mined: false (timeout after 300s)`, calls `_log_sync` with a message containing "timed out" and "300", and returns None without re-raising.
  </behavior>
  <action>
**Part A — Wrap `subprocess.run` in try/except:**

Refactor `cmd_mine` to wrap the `subprocess.run` call:

```python
    try:
        result = subprocess.run(
            ["mempalace", "mine", vault_chats, "--mode", "convos", "--extract", "general"],
            capture_output=True,
            text=True,
            timeout=300,  # D-09; T-4-04 mitigation (DoS via hung process)
        )
    except subprocess.TimeoutExpired:
        # Python beginner note: subprocess.run in Python 3.3+ kills the child
        # process automatically before raising TimeoutExpired — no manual
        # process.kill() needed. Verified against Python 3.14 in RESEARCH.md.
        _log_sync("mempalace: timed out after 300s — skipping mine")
        print("mempalace_mined: false (timeout after 300s)")
        return
```

**Part B — Un-skip and implement test 4-02-03:**

```python
def test_timeout_false(self):
    """MEM-02 / D-09 / T-4-04: TimeoutExpired → false (timeout after 300s), sync.log warning."""
    fake_args = argparse.Namespace()

    with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), \
         patch("sync_chats._require_config", return_value={
             "vault_path": "/tmp/fake-vault", "machine_label": "t", "schema_version": 1,
         }), \
         patch("sync_chats.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="mempalace", timeout=300)), \
         patch("sync_chats._log_sync") as mock_log, \
         patch("builtins.print") as mock_print:
        # Must not raise
        sync_chats.cmd_mine(fake_args)

    mock_print.assert_called_once_with("mempalace_mined: false (timeout after 300s)")
    mock_log.assert_called_once()
    log_msg = mock_log.call_args[0][0]
    self.assertIn("timed out", log_msg)
    self.assertIn("300", log_msg)
```

Add `import subprocess` at the top of the test file if not already present (it's needed for `subprocess.TimeoutExpired`).
</action>
<verify>
<automated>pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg -xvs</automated>
</verify>
<done>All three `TestCmdMineGracefulDeg` tests green. Full suite `python3 -m unittest discover tests -v` green (no regressions). `cmd_mine` is now fail-soft on all three error paths.</done>
</task>

</tasks>

<threat_model>

## Trust Boundaries

| Boundary                 | Description                                                                                    |
| ------------------------ | ---------------------------------------------------------------------------------------------- |
| subprocess child process | `mempalace` output (stderr) flows back into Python; last 20 lines may be written to `sync.log` |
| mempalace availability   | External dependency may be missing on second Mac (MEM-02 contract)                             |
| process lifetime         | Hung `mempalace` process could block sync pipeline indefinitely absent timeout                 |

## STRIDE Threat Register

| Threat ID | Category               | Component                  | Disposition | Mitigation Plan                                                                                                                                                                                                                                                      |
| --------- | ---------------------- | -------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-4-02    | Availability / DoS     | `cmd_mine`                 | mitigate    | `shutil.which` pre-check returns None → `skipped` outcome + sync.log warning, exit 0. Verified by test 4-02-01.                                                                                                                                                      |
| T-4-03    | Information disclosure | `sync.log` via stderr tail | mitigate    | Log stderr tail **only on non-zero exit** (D-11), **max 20 lines** (`splitlines()[-20:]`). Success path writes zero stderr to disk. Verified by test 4-02-02. Residual risk ASSUMED per RESEARCH.md A1: mempalace's own stderr does not echo scrubbed vault content. |
| T-4-04    | Availability / DoS     | `subprocess.run`           | mitigate    | `timeout=300` kwarg. On `TimeoutExpired`, subprocess.run kills the child automatically (Python 3.3+). Verified by test 4-02-03.                                                                                                                                      |

</threat_model>

<verification>
Full test suite after this plan:

```bash
pipx run pytest tests/test_mine.py -v        # 5 passed, 3 skipped (Plan 03 stubs remain)
python3 -m unittest discover tests -v        # all prior-phase tests still green
```

Manual smoke on a host **without** mempalace installed (confirms fail-soft):

```bash
# Temporarily hide the binary
PATH="/usr/bin:/bin" python3 sync_chats.py mine
# Expected stdout: mempalace_mined: skipped (command not found)
# Expected exit:   0
# Expected sync.log: timestamped line "mempalace: command not found — skipping mine"
```

</verification>

<success_criteria>

- [ ] `cmd_mine` has three explicit graceful-degradation branches (missing binary, non-zero exit, TimeoutExpired)
- [ ] Every non-success path calls `_log_sync` exactly once
- [ ] Non-success stdout always formatted `mempalace_mined: <false|skipped> (<reason>)`
- [ ] Stderr tail on failure is max 20 lines (`splitlines()[-20:]`)
- [ ] `cmd_mine` never raises out of its try/except — exit code always 0
- [ ] `TestCmdMineGracefulDeg` (3 tests) all green
- [ ] No regressions in prior-phase test suites
- [ ] MEM-02 traceable: every failure mode covered by an automated test
- [ ] Threats T-4-02, T-4-03, T-4-04 mitigated with test-backed verification
      </success_criteria>

<output>
After completion, create `.planning/phases/04-mempalace-bulk-mine-integration/04-02-SUMMARY.md`. Note the exact wording chosen for each `_log_sync` message (discretionary per CONTEXT.md) so Plan 03 can match the format in summary output.
</output>
