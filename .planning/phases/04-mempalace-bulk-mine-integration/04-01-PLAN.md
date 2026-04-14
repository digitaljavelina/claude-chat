---
phase: 04-mempalace-bulk-mine-integration
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - sync_chats.py
  - tests/test_mine.py
autonomous: true
requirements:
  - MEM-01
must_haves:
  truths:
    - "cmd_mine subcommand exists and is registered in argparse"
    - "When invoked, cmd_mine runs `mempalace mine <vault_path>/Chats --mode convos --extract general` via subprocess.run (list form, no shell=True)"
    - "Vault path is read dynamically from config.json via _require_config(), not hardcoded"
    - "tests/test_mine.py exists with TestCmdMine, TestCmdMineGracefulDeg, TestCmdMineSummary, TestSkillMineStep classes"
  artifacts:
    - path: "sync_chats.py"
      provides: "cmd_mine function + mine subparser registration"
      contains: "def cmd_mine"
    - path: "tests/test_mine.py"
      provides: "Wave 0 test scaffolding for all Phase 4 validation tasks"
      contains: "class TestCmdMine"
  key_links:
    - from: "sync_chats.py::cmd_mine"
      to: "sync_chats.py::_require_config"
      via: "function call reading vault_path"
      pattern: "_require_config\\(\\)"
    - from: "sync_chats.py::main (argparse)"
      to: "sync_chats.py::cmd_mine"
      via: "subparsers.add_parser('mine') + set_defaults(func=cmd_mine)"
      pattern: "add_parser\\(\"mine\""
---

<objective>
Create the `mine` subcommand in `sync_chats.py` and scaffold the Phase 4 test file that later plans will extend. This plan covers the happy path: binary exists, invocation succeeds, correct argv passed. Graceful degradation (binary absent, non-zero exit, timeout) lives in Plan 02.

Purpose: Establish the single integration point that MEM-01 requires — one shell-out to `mempalace mine <vault>/Chats --mode convos --extract general` using list-form subprocess.run. Also lays down Wave 0 test stubs so Plan 02 and Plan 03 (same wave execution) have a green framework to extend.

Output:

- `cmd_mine(args)` function in `sync_chats.py`
- `mine` subparser registered in the argparse dispatcher
- `tests/test_mine.py` with empty test classes matching VALIDATION.md task IDs
- Happy-path test (4-01-02, 4-01-03) passing green
  </objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-CONTEXT.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-RESEARCH.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-VALIDATION.md
@sync_chats.py
@tests/test_phase2_labels.py

<interfaces>
<!-- Key symbols from sync_chats.py that cmd_mine must reuse. Verified in RESEARCH.md. -->
<!-- Python beginner note: these are already imported / defined; cmd_mine must not reinvent them. -->

From sync_chats.py (existing):

```python
# Line ~11: import shutil          # for shutil.which
# Line ~14: import subprocess      # for subprocess.run, TimeoutExpired
# Line ~156: def _require_config() -> dict:
#     """Load ~/.claude-chat/config.json or exit(2) with a helpful message."""
#     # returns dict with at minimum: {"machine_label": str, "vault_path": str, "schema_version": int}
#
# Line ~914: def _log_sync(message: str) -> None:
#     """Append a UTC-timestamped line to ~/.claude-chat/sync.log (append-only)."""
#
# Line ~1268: subparsers pattern
#     p_status = subparsers.add_parser("status", help="Show sync status summary")
#     p_status.set_defaults(func=cmd_status)
```

Vault layout (CRITICAL — see RESEARCH.md §"Existing `_require_config()` + vault path access"):

- `config["vault_path"]` is the Obsidian vault ROOT
- `<vault_path>/Chats/` is the subfolder mempalace must target
- So `cmd_mine` passes `str(Path(config["vault_path"]) / "Chats")` to subprocess
  </interfaces>
  </context>

<tasks>

<task type="auto">
  <name>Task 4-01-01: Scaffold tests/test_mine.py (Wave 0)</name>
  <files>tests/test_mine.py</files>
  <action>
Create `tests/test_mine.py` with four `unittest.TestCase` classes matching VALIDATION.md task IDs:

1. `TestCmdMine` — covers MEM-01 happy path (4-01-02, 4-01-03)
2. `TestCmdMineGracefulDeg` — covers MEM-02 error paths (filled in Plan 02)
3. `TestCmdMineSummary` — covers MEM-03 stdout format (filled in Plan 03)
4. `TestSkillMineStep` — covers SKILL.md Step 4 (filled in Plan 03, uses `@unittest.skipUnless(_SKILL_PATH.exists(), ...)` per project convention `reference_skill_md_tests_ci.md`)

All test method stubs should be present with `self.skipTest("pending <task-id>")` so Plan 02/03 can un-skip one at a time without adding new method names. Stub method names required:

- `TestCmdMine.test_runs_correct_command` (4-01-02)
- `TestCmdMine.test_vault_path_from_config` (4-01-03)
- `TestCmdMineGracefulDeg.test_binary_absent_skipped` (4-02-01)
- `TestCmdMineGracefulDeg.test_nonzero_exit_false` (4-02-02)
- `TestCmdMineGracefulDeg.test_timeout_false` (4-02-03)
- `TestCmdMineSummary.test_true_on_success` (4-03-01)
- `TestCmdMineSummary.test_skipped_with_reason` (4-03-02)
- `TestSkillMineStep.test_skill_step4_calls_mine` (4-03-03)

Imports must be stdlib only. Import `sync_chats` as module (top of repo already on path; see `tests/test_phase2_labels.py` for the import pattern). Use `unittest.mock.patch` for subprocess + shutil.which stubbing in Plan 02/03.

For the SKILL class: `_SKILL_PATH = Path.home() / ".claude" / "skills" / "sync-chats" / "SKILL.md"` and decorate class with `@unittest.skipUnless(_SKILL_PATH.exists(), "SKILL.md not installed on this host")` — matches project memory `reference_skill_md_tests_ci.md`.

Do NOT implement any test bodies beyond `self.skipTest(...)` in this task. The happy-path assertions are implemented in task 4-01-02 and 4-01-03 below; everything else is filled in Plan 02/03.
</action>
<verify>
<automated>pipx run pytest tests/test_mine.py -v</automated>
</verify>
<done>Eight test methods exist, all currently skip with reason "pending &lt;task-id&gt;". Pytest reports 8 skipped, 0 failed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4-01-02: Implement cmd_mine happy path + register mine subparser</name>
  <files>sync_chats.py, tests/test_mine.py</files>
  <behavior>
    - Test 4-01-02 (`TestCmdMine.test_runs_correct_command`): When `shutil.which` returns a fake path AND `subprocess.run` is mocked to return returncode=0, `cmd_mine(args)` invokes `subprocess.run` with argv list `["mempalace", "mine", "<vault>/Chats", "--mode", "convos", "--extract", "general"]`, `capture_output=True`, `text=True`, `timeout=300`. No `shell=True` anywhere (assert via call_args kwargs).
    - Argparse smoke: `python3 sync_chats.py mine --help` exits 0 and mentions "mine". (Verified via subprocess or argparse parsing in the test.)
  </behavior>
  <action>
**Part A — Implement `cmd_mine` in `sync_chats.py`** (place beside existing `cmd_status`, before `main()`):

```python
def cmd_mine(args) -> None:
    """Shell out to `mempalace mine` after a sync run (MEM-01/02/03).

    Reports one of three outcomes via stdout:
      mempalace_mined: true
      mempalace_mined: false (<reason>)
      mempalace_mined: skipped (<reason>)

    Happy path only in Plan 01; error/timeout paths added in Plan 02.
    """
    config = _require_config()
    # Python beginner note: Path / "Chats" is pathlib's overloaded '/' operator for joins.
    # str(...) because subprocess expects str args, not Path objects, in the argv list.
    vault_chats = str(Path(config["vault_path"]) / "Chats")

    # D-08: binary-not-found handling stubbed here; full implementation in Plan 02.
    # For now, if the binary is missing we still print skipped so the happy-path test
    # can distinguish "ran" from "didn't run". Plan 02 will add the _log_sync call and
    # refine the message.
    if shutil.which("mempalace") is None:
        print("mempalace_mined: skipped (command not found)")
        return

    # MEM-01 (per D-01, D-04): list-form argv, no shell=True. T-4-01 mitigation.
    result = subprocess.run(
        ["mempalace", "mine", vault_chats, "--mode", "convos", "--extract", "general"],
        capture_output=True,
        text=True,
        timeout=300,  # D-09; TimeoutExpired handling comes in Plan 02
    )

    # Plan 02 will replace this with the full returncode + TimeoutExpired branches.
    if result.returncode == 0:
        print("mempalace_mined: true")
    else:
        print(f"mempalace_mined: false (exit {result.returncode})")
```

Rationale for the "stub" shape: Plan 02 will wrap the `subprocess.run` call in `try/except subprocess.TimeoutExpired` and add `_log_sync` calls. Keeping the happy path first lets the test framework prove argv correctness before layering in error handling. This matches Interface-First Task Ordering.

**Part B — Register the subparser** (at sync_chats.py around line 1299, immediately after the `p_status` block, before `args = parser.parse_args()`):

```python
    # MEM-01: mine subcommand (D-01)
    p_mine = subparsers.add_parser(
        "mine",
        help="Mine vault Chats/ into MemPalace (post-run step)",
    )
    p_mine.set_defaults(func=cmd_mine)
```

**Part C — Un-skip and implement test 4-01-02** in `tests/test_mine.py::TestCmdMine::test_runs_correct_command`:

```python
def test_runs_correct_command(self):
    """MEM-01: cmd_mine invokes subprocess.run with correct list-form argv."""
    fake_args = argparse.Namespace()

    with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), \
         patch("sync_chats._require_config", return_value={
             "vault_path": "/tmp/fake-vault",
             "machine_label": "test",
             "schema_version": 1,
         }), \
         patch("sync_chats.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        sync_chats.cmd_mine(fake_args)

    # Exactly one subprocess invocation
    self.assertEqual(mock_run.call_count, 1)
    argv, kwargs = mock_run.call_args
    # T-4-01: list-form argv (positional), not shell=True
    self.assertEqual(argv[0], [
        "mempalace", "mine", "/tmp/fake-vault/Chats",
        "--mode", "convos", "--extract", "general",
    ])
    self.assertNotIn("shell", kwargs)  # or: self.assertFalse(kwargs.get("shell"))
    self.assertTrue(kwargs.get("capture_output"))
    self.assertTrue(kwargs.get("text"))
    self.assertEqual(kwargs.get("timeout"), 300)
```

Use `from unittest.mock import patch, MagicMock` and `import argparse` at the top of the test file.
</action>
<verify>
<automated>pipx run pytest tests/test_mine.py::TestCmdMine::test_runs_correct_command -xvs</automated>
</verify>
<done>
`cmd_mine` exists in `sync_chats.py`. `mine` subparser registered. `python3 sync_chats.py mine --help` exits 0. `test_runs_correct_command` passes green. Other 7 tests still skip.
</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4-01-03: Verify vault_path comes from config (not hardcoded)</name>
  <files>tests/test_mine.py</files>
  <behavior>
    - Test 4-01-03 (`TestCmdMine.test_vault_path_from_config`): When `_require_config` is patched to return two different vault_path values in two separate invocations, the second subprocess.run call uses the second vault_path — proving the value is read fresh from config, not cached or hardcoded.
  </behavior>
  <action>
Un-skip `TestCmdMine::test_vault_path_from_config` and implement:

```python
def test_vault_path_from_config(self):
    """MEM-01: vault path resolved dynamically from _require_config, not hardcoded."""
    fake_args = argparse.Namespace()

    for vault in ["/vault-one", "/vault-two"]:
        with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), \
             patch("sync_chats._require_config", return_value={
                 "vault_path": vault, "machine_label": "t", "schema_version": 1,
             }), \
             patch("sync_chats.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            sync_chats.cmd_mine(fake_args)
            argv, _ = mock_run.call_args
            # The vault_chats target must reflect the current config, not a stale value.
            self.assertEqual(argv[0][2], f"{vault}/Chats")
```

No production code changes needed — this test verifies the happy path already implemented in 4-01-02 is config-driven. If it fails, the implementation is wrong (e.g., hardcoded path or module-level constant).

Python beginner note: `argv[0][2]` means "first positional arg to subprocess.run (which is the argv list), index 2 (the directory target)". Order matches the list in `cmd_mine`: `[0]="mempalace", [1]="mine", [2]=vault_chats, ...`.
</action>
<verify>
<automated>pipx run pytest tests/test_mine.py::TestCmdMine -xvs</automated>
</verify>
<done>Both `TestCmdMine` tests pass green. Full suite `python3 -m unittest discover tests -v` still green (no regressions in prior phases).</done>
</task>

</tasks>

<threat_model>

## Trust Boundaries

| Boundary                        | Description                                                                 |
| ------------------------------- | --------------------------------------------------------------------------- |
| `config.json` → subprocess argv | `vault_path` from user-owned config flows into subprocess.run argv list     |
| subprocess child process        | `mempalace` binary spawned as separate process; inherits PATH but not shell |

## STRIDE Threat Register

| Threat ID | Category               | Component                        | Disposition | Mitigation Plan                                                                                                                                                                                                                                                                                       |
| --------- | ---------------------- | -------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-4-01    | Tampering              | `cmd_mine` subprocess invocation | mitigate    | Pass argv as a **list** to `subprocess.run` (never `shell=True`). Even if `vault_path` contained shell metacharacters, list form bypasses shell interpretation entirely (docs.python.org/3/library/subprocess.html#security-considerations). Verified by test 4-01-02 asserting `shell` kwarg absent. |
| T-4-05    | Information disclosure | `cmd_mine` stdout                | accept      | Happy-path stdout is only the literal string `mempalace_mined: true` — no config or file contents leaked.                                                                                                                                                                                             |

</threat_model>

<verification>
Run full test suite to confirm no regressions:

```bash
python3 -m unittest discover tests -v
```

Manual smoke (optional — requires mempalace installed):

```bash
python3 sync_chats.py mine
# Expected: prints `mempalace_mined: true` (assuming real mempalace binary + valid vault)
```

</verification>

<success_criteria>

- [ ] `cmd_mine` function exists in `sync_chats.py` and follows the `_require_config()` + `subprocess.run(list form)` pattern
- [ ] `mine` subparser registered; `python3 sync_chats.py mine --help` exits 0
- [ ] `tests/test_mine.py` exists with 8 test methods (2 green, 6 skipped pending)
- [ ] `pipx run pytest tests/test_mine.py -v` reports 2 passed, 6 skipped
- [ ] `python3 -m unittest discover tests -v` reports zero failures (no regressions)
- [ ] MEM-01 traceable: test_runs_correct_command proves exact argv; test_vault_path_from_config proves config-driven vault
      </success_criteria>

<output>
After completion, create `.planning/phases/04-mempalace-bulk-mine-integration/04-01-SUMMARY.md` with: files modified, tests passing, any discretion choices made (e.g., exact `_log_sync` message text — deferred to Plan 02).
</output>
