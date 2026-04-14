---
phase: 04-mempalace-bulk-mine-integration
plan: "02"
subsystem: sync_chats
tags: [mine, mempalace, subprocess, graceful-degradation, tdd, error-handling]

# Dependency graph
requires:
  - phase: 04-01
    provides: cmd_mine happy path + test_mine.py scaffold with 3 skipped stubs
provides:
  - cmd_mine with all three graceful-degradation branches (D-07, D-08, D-09, D-11)
  - test_mine.py TestCmdMineGracefulDeg: 3 tests green (4-02-01, 4-02-02, 4-02-03)
  - _log_sync wiring on every non-success path
affects: [04-03, sync-chats-skill, observability]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - inverted-guard early-return (if returncode != 0: ...; return; then happy path)
    - splitlines()[-20:] for bounded stderr tail logging
    - try/except subprocess.TimeoutExpired wrapping subprocess.run

key-files:
  created: []
  modified: [sync_chats.py, tests/test_mine.py]

key-decisions:
  - "Inverted-guard shape (if != 0: return) matches existing shutil.which block — top-to-bottom failure-then-success"
  - "stderr tail logged only on failure, max 20 lines via splitlines()[-20:] — T-4-03 info-disclosure mitigation"
  - "_log_sync messages chosen: 'mempalace: command not found — skipping mine' (D-08), 'mempalace: timed out after 300s — skipping mine' (D-09), 'mempalace mine failed (exit N):\\n<stderr_tail>' (D-07)"

patterns-established:
  - "Fail-soft: every error path in cmd_mine calls _log_sync once then returns; never raises out of the function"
  - "Success is silent: no _log_sync on happy path, zero stderr written to disk on returncode 0 (D-11)"

requirements-completed: [MEM-02]

# Metrics
duration: ~8min
completed: "2026-04-14"
---

# Phase 04 Plan 02: cmd_mine graceful-degradation branches Summary

**`cmd_mine` hardened with three fail-soft branches: missing binary logs + skips (D-08), non-zero exit logs stderr tail (last 20 lines, D-07/D-11), and TimeoutExpired logs + returns (D-09/T-4-04) — all verified by three new green tests (MEM-02)**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-14T21:10:00Z
- **Completed:** 2026-04-14T21:18:00Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- Added `_log_sync` call to the binary-absent branch (D-08, T-4-02), completing the stub left intentionally in Plan 01
- Replaced the bare `else` returncode branch with an inverted-guard that logs the last 20 stderr lines and returns (D-07, D-11, T-4-03)
- Wrapped `subprocess.run` in `try/except subprocess.TimeoutExpired` so a hung `mempalace` process is killed automatically and sync continues (D-09, T-4-04)
- All three `TestCmdMineGracefulDeg` tests now pass; 159 prior-phase tests unchanged

## Task Commits

Each task was committed atomically:

1. **Task 4-02-01: Binary absent → \_log_sync + skipped** - `eee6cd4` (feat)
2. **Task 4-02-02: Non-zero exit → stderr tail + false** - `5409067` (feat)
3. **Task 4-02-03: TimeoutExpired → false + sync.log warning** - `beca121` (feat)

_Note: TDD tasks — each commit contains both the failing test implementation and the production code fix (RED verified in session, GREEN committed together)._

## Files Created/Modified

- `sync_chats.py` — `cmd_mine`: added `_log_sync` to binary-absent branch; replaced `else` with inverted-guard + `splitlines()[-20:]` stderr tail; wrapped `subprocess.run` in `try/except subprocess.TimeoutExpired`
- `tests/test_mine.py` — Added `import subprocess`; implemented `test_binary_absent_skipped`, `test_nonzero_exit_false`, `test_timeout_false` (replaced `skipTest` stubs)

## \_log_sync message wording (for Plan 03 reference)

Plan 02 chose these exact strings for `_log_sync` calls (discretionary per CONTEXT.md):

| Failure path         | \_log_sync message                                          |
| -------------------- | ----------------------------------------------------------- |
| Binary absent (D-08) | `"mempalace: command not found — skipping mine"`            |
| Timeout (D-09)       | `"mempalace: timed out after 300s — skipping mine"`         |
| Non-zero exit (D-07) | `"mempalace mine failed (exit N):\n<last 20 stderr lines>"` |

## Decisions Made

- Inverted-guard shape (`if returncode != 0: ...; return` then `print true`) chosen over `if/else` to match the early-return style of the `shutil.which` block above — reads top-to-bottom as failure-then-success
- stderr tail uses `splitlines()[-20:]` — the `[-20:]` slice is safe when stderr has fewer than 20 lines (returns what's there, no `IndexError`). This is Python's standard slice behavior.
- `import subprocess` added to test file (needed for `subprocess.TimeoutExpired` in test 4-02-03)

## Deviations from Plan

None — plan executed exactly as written.

All three code changes and tests matched the plan action blocks verbatim. The Plan 01 stubs were resolved exactly as the plan specified.

## Issues Encountered

None. The worktree required a `git reset --soft` + `git checkout HEAD -- .` to restore working tree to match the expected base commit before execution could start, but this is a routine worktree setup step, not a code issue.

## Threat Mitigations Verified

| Threat                                | Mitigation                                       | Test                                                     |
| ------------------------------------- | ------------------------------------------------ | -------------------------------------------------------- |
| T-4-02 (Availability: missing binary) | `shutil.which` pre-check + `_log_sync` + exit 0  | `test_binary_absent_skipped`                             |
| T-4-03 (Info-disclosure via stderr)   | Log only on failure, max 20 lines                | `test_nonzero_exit_false` (asserts `[-20:]` not `[:20]`) |
| T-4-04 (DoS via hung process)         | `timeout=300` + `except TimeoutExpired` + exit 0 | `test_timeout_false`                                     |

## Known Stubs

The following remain from Plan 01 by design — Plan 03 will resolve them:

| Stub                          | File               | Status                        |
| ----------------------------- | ------------------ | ----------------------------- |
| `test_true_on_success`        | tests/test_mine.py | `skipTest("pending 4-03-01")` |
| `test_skipped_with_reason`    | tests/test_mine.py | `skipTest("pending 4-03-02")` |
| `test_skill_step4_calls_mine` | tests/test_mine.py | `skipTest("pending 4-03-03")` |

These stubs do not prevent Plan 02's goal: all MEM-02 graceful-degradation paths are fully proven.

## Threat Surface Scan

No new network endpoints, auth paths, or trust boundaries introduced beyond what the plan's threat model covers. The `_log_sync` write path was pre-existing; this plan adds callers on failure paths only.

## Next Phase Readiness

- `cmd_mine` is now fully hardened — Plan 03 can proceed to `MEM-03` (summary output) and SKILL.md wiring
- Plan 03 needs the exact `_log_sync` wording documented in the table above to write summary-output assertions
- No blockers

---

_Phase: 04-mempalace-bulk-mine-integration_
_Completed: 2026-04-14_

## Self-Check: PASSED

Files exist:

- FOUND: sync_chats.py (modified, contains `except subprocess.TimeoutExpired`)
- FOUND: tests/test_mine.py (modified, contains `class TestCmdMineGracefulDeg`)

Commits exist:

- eee6cd4 — feat(04-02): binary absent → \_log_sync warning + skipped
- 5409067 — feat(04-02): non-zero exit → stderr tail + false outcome
- beca121 — feat(04-02): TimeoutExpired → false + sync.log warning
