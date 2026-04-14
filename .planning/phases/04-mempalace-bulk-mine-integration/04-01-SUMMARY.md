---
phase: 04-mempalace-bulk-mine-integration
plan: "01"
subsystem: sync_chats
tags: [mine, mempalace, subprocess, argparse, tdd]
dependency_graph:
  requires: []
  provides: [cmd_mine, mine-subparser, test_mine-scaffold]
  affects: [sync_chats.py, tests/test_mine.py]
tech_stack:
  added: []
  patterns:
    [
      list-form subprocess.run,
      shutil.which detection,
      _require_config vault path,
      unittest.mock.patch,
    ]
key_files:
  created: [tests/test_mine.py]
  modified: [sync_chats.py]
decisions:
  - "cmd_mine placed beside cmd_status just before main() — consistent with existing command layout"
  - "No _log_sync calls in Plan 01 happy path — deferred to Plan 02 per plan spec"
  - "vault_chats built as str(Path(config['vault_path']) / 'Chats') — pathlib join, str() for subprocess compat"
  - "shell kwarg intentionally absent from subprocess.run call (not shell=False) — asserted by test"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-14T21:04:35Z"
  tasks_completed: 3
  files_modified: 2
requirements: [MEM-01]
---

# Phase 04 Plan 01: cmd_mine happy path + test scaffold Summary

One-liner: `cmd_mine` function + `mine` argparse subparser implementing MEM-01 list-form subprocess.run shell-out to `mempalace mine <vault>/Chats --mode convos --extract general`, with Wave 0 test scaffold for all Phase 4 validation tasks.

## What Was Built

### sync_chats.py — cmd_mine function

Added `cmd_mine(args)` beside existing command functions, immediately before `# Entry Point`. The function:

1. Loads vault path via `_require_config()` (never hardcoded)
2. Builds `vault_chats = str(Path(config["vault_path"]) / "Chats")`
3. Checks `shutil.which("mempalace")` — prints `mempalace_mined: skipped (command not found)` and returns if None (D-08 stub; Plan 02 adds `_log_sync`)
4. Calls `subprocess.run(["mempalace", "mine", vault_chats, "--mode", "convos", "--extract", "general"], capture_output=True, text=True, timeout=300)` — no `shell=True` (T-4-01 mitigated)
5. Prints `mempalace_mined: true` on returncode 0, else `mempalace_mined: false (exit N)` (Plan 02 adds TimeoutExpired branch + `_log_sync`)

### sync_chats.py — mine subparser registration

Added in `main()` immediately after `p_status` block:

```python
p_mine = subparsers.add_parser("mine", help="Mine vault Chats/ into MemPalace (post-run step)")
p_mine.set_defaults(func=cmd_mine)
```

`python3 sync_chats.py mine --help` exits 0 and outputs correct usage.

### tests/test_mine.py — Wave 0 scaffold

New file with 4 test classes and 8 methods:

| Class                  | Methods                                                                 | Status                      |
| ---------------------- | ----------------------------------------------------------------------- | --------------------------- |
| TestCmdMine            | test_runs_correct_command, test_vault_path_from_config                  | 2 PASSED                    |
| TestCmdMineGracefulDeg | test_binary_absent_skipped, test_nonzero_exit_false, test_timeout_false | 3 SKIPPED (pending 4-02-\*) |
| TestCmdMineSummary     | test_true_on_success, test_skipped_with_reason                          | 2 SKIPPED (pending 4-03-\*) |
| TestSkillMineStep      | test_skill_step4_calls_mine                                             | 1 SKIPPED (pending 4-03-03) |

`TestSkillMineStep` decorated with `@unittest.skipUnless(_SKILL_PATH.exists(), "SKILL.md not installed on this host")` per `reference_skill_md_tests_ci.md`.

## Verification Results

```
pipx run pytest tests/test_mine.py -v
  2 passed, 6 skipped in 0.01s

python3 -m unittest discover tests -v
  Ran 159 tests in 0.030s
  OK (skipped=6)   ← no regressions in prior phases
```

## Commits

| Task    | Hash    | Message                                                                         |
| ------- | ------- | ------------------------------------------------------------------------------- |
| 4-01-01 | e4cf397 | test(04-01): scaffold tests/test_mine.py with 8 stub test methods (Wave 0)      |
| 4-01-02 | 0ea22bb | feat(04-01): add cmd_mine + mine subparser + test_runs_correct_command (MEM-01) |
| 4-01-03 | 56ce407 | test(04-01): implement test_vault_path_from_config (4-01-03)                    |

## Deviations from Plan

None — plan executed exactly as written.

The plan explicitly deferred `_log_sync` calls and `TimeoutExpired` handling to Plan 02; the Plan 01 implementation matches the stub shape described in the plan action blocks.

## Known Stubs

The following are intentional stubs, per plan design — Plan 02 will resolve them:

| Stub                                         | File          | Line     | Reason                                                                                    |
| -------------------------------------------- | ------------- | -------- | ----------------------------------------------------------------------------------------- |
| No `_log_sync` on binary-absent skipped path | sync_chats.py | cmd_mine | Plan spec says "Plan 02 will add the \_log_sync call"                                     |
| No `TimeoutExpired` exception handling       | sync_chats.py | cmd_mine | Plan spec says "TimeoutExpired handling comes in Plan 02"                                 |
| No `_log_sync` on nonzero exit               | sync_chats.py | cmd_mine | Plan spec says "Plan 02 will replace this with full returncode + TimeoutExpired branches" |

These stubs do NOT prevent the plan's goal: the happy-path argv correctness (MEM-01) is fully proven. Plan 02 adds error handling on top.

## Threat Surface Scan

No new network endpoints, auth paths, or trust boundaries introduced beyond what the plan's threat model covers:

- T-4-01 (Tampering via shell injection): mitigated by list-form argv — verified by `test_runs_correct_command` asserting `shell` kwarg is absent
- T-4-05 (Information disclosure via stdout): happy-path stdout is literal `mempalace_mined: true` — no config or file contents

## Self-Check: PASSED

Files exist:

- FOUND: tests/test_mine.py
- FOUND: sync_chats.py (modified, contains cmd_mine)

Commits exist:

- e4cf397 — test(04-01): scaffold tests/test_mine.py
- 0ea22bb — feat(04-01): add cmd_mine + mine subparser
- 56ce407 — test(04-01): implement test_vault_path_from_config
