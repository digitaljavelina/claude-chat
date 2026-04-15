---
phase: 05-sessionend-hook-observability-multi-machine-onboarding
plan: 02
subsystem: infra
tags: [python, argparse, session-end-hook, cli, observability]

requires:
  - phase: 05-01
    provides: _write_session, _write_last_run, LAST_RUN_PATH, auto_label_hash_override sentinel path
  - phase: 01-vault-write-pipeline
    provides: discover_sessions, make_stub_label, _require_config, _log_sync, _assert_not_icloud
provides:
  - cmd_once(args) — orchestrates scan → stub write-all → last_run.json → summary → exit
  - root --once argparse flag (action=store_true) + pre-dispatch branch in main()
  - last_run.json D-11 schema populated on every --once invocation
  - run-start + run-finish sync.log lines per --once run (OBSERV-02)
affects: [05-03-cmd-status, 05-04-relabel, 05-05-readme]

tech-stack:
  added: []
  patterns:
    - "Pre-dispatch root flag: handle --once BEFORE subparser routing (avoids argparse Pitfall 1)"
    - "Bounded error list: cap errors[] at 10 entries per D-13 to keep last_run.json small"
    - "One-line stderr on failure: no stack traces; detailed errors live in sync.log + last_run.json"

key-files:
  created:
    - tests/test_phase5_once.py
  modified:
    - sync_chats.py

key-decisions:
  - "Inline summary f-string in cmd_once as a temporary step — Plan 03 centralizes into _format_summary(dict)"
  - "exit_code logic: 1 on any per-session failure, 0 otherwise; _require_config's own sys.exit(2) handles pre-flight"
  - "cmd_once never reads stdin — D-02 / Pitfall 2; confirmed by TestCmdOnceNoStdin with an empty StringIO stdin"
  - "Use socket.gethostname() (not os.uname()) for cross-platform hostname capture per D-11 schema"

patterns-established:
  - "argparse root flag + pre-dispatch branch: add `--once` at top-level parser, check before subparser routing"
  - "Counter update pattern: synced / skipped / failed / flagged_for_review as separate ints so D-11 shape stays flat"
  - "Error capture: typed dicts ({session_id, error_class, error_message}) for JSON round-trip safety"

requirements-completed:
  - HOOK-01
  - HOOK-02
  - HOOK-03
  - HOOK-04
  - OBSERV-02
  - OBSERV-03

duration: ~25min
completed: 2026-04-15
---

# Phase 05-02 Summary

**Added `cmd_once` and the root `--once` flag — `python3 sync_chats.py --once` now scans unsynced sessions, writes each with a stub label (`auto_label_hash: stub` sentinel), persists `last_run.json` (D-11 schema), logs run-start/run-finish lines, prints the OBSERV-01 summary, and exits 0/1/2 per policy. This is the SessionEnd hook entry point.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 (TDD: RED → GREEN)
- **Files modified:** 2 (1 production, 1 test)
- **Tests added:** 9 (178 total, +9 from 169 baseline)

## Accomplishments

- `cmd_once(args)` orchestrates the full hook flow in ~70 lines: preflight → discover → for-each-session stub+write+count → last_run.json → summary/log → exit.
- Root `--once` flag wired via `action="store_true"`; pre-dispatch branch in `main()` runs `cmd_once(args)` before the subcommand-None help-print guard (RESEARCH Pitfall 1 avoided).
- `last_run.json` matches D-11 schema exactly: all 14 keys present, correct types, `trigger="once"`, `mempalace_mined="skipped"` (D-15).
- `errors[]` capped at 10 entries (D-13) verified with 15-failure stress test.
- stdin-safe: `cmd_once` never reads `sys.stdin` — verified by test with empty StringIO stdin under assertRaises(SystemExit).
- stderr discipline: on failure, exactly one short line to stderr; no stack traces (D-21 / Pitfall 6).

## Task Commits

1. **Task 1: RED tests for cmd_once** — `0046a0d` (test)
2. **Task 2: GREEN cmd_once + --once wiring** — `c379398` (feat)

## Files Created/Modified

- `sync_chats.py` — Added `cmd_once()` (~90 lines) below `cmd_mine`; added `--once` root argument and pre-dispatch branch in `main()`.
- `tests/test_phase5_once.py` — 9 unit tests across 8 classes covering happy path, empty queue, single + 15-way failures, sentinel, argparse pre-dispatch, sync.log coverage, preflight exit code, stdin-safety.

## Decisions Made

- Inline summary format string rather than extract `_format_summary` here — Plan 03 is the correct home (it also rewires `cmd_status`). Leaving duplication as a deliberate convergence marker for the next wave.
- `cmd_once` owns its own `sys.exit(exit_code)` — the wrapper pattern from `cmd_write` doesn't fit because `cmd_once` is the top-level dispatch (no outer orchestrator to decide policy).
- `flagged_for_review` increments only on `synced` (new writes) — `skipped`/`reconciled`/`edited` don't re-flag files that already exist.

## Deviations from Plan

None — plan executed exactly as written. Temporary inline summary is explicitly documented as a Plan 03 convergence point (plan line 159).

## Issues Encountered

None.

## Next Phase Readiness

- Plan 03 can now extract `_format_summary(last_run_dict) -> str` and replace both the `cmd_once` inline format (line ~1516) and `cmd_status`'s current last-run-at output.
- Plan 04 can search the vault for `auto_label_hash: stub` to drive its `relabel` subcommand — the sentinel is now being written by every `--once` invocation.
- Plan 05 can point users at `python3 ~/.claude-chat/sync_chats.py --once` in the onboarding README as the exact SessionEnd hook command.

---

_Phase: 05-sessionend-hook-observability-multi-machine-onboarding_
_Completed: 2026-04-15_
