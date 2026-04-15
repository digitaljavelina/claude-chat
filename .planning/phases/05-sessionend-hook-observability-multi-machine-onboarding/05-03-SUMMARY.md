---
phase: 05-sessionend-hook-observability-multi-machine-onboarding
plan: 03
subsystem: infra
tags: [python, pure-function, cli, observability]

requires:
  - phase: 05-01
    provides: LAST_RUN_PATH
  - phase: 05-02
    provides: cmd_once with temporary inline summary, last_run.json writer
  - phase: 01-vault-write-pipeline
    provides: cmd_status original CORE-13 output, _load_json helper, state.last_run_at
provides:
  - _format_summary(run_dict) -> str (sole producer of the D-23 canonical summary line)
  - cmd_status reads last_run.json first; falls back to state.last_run_at (D-17)
  - cmd_once now calls _format_summary (convergence — no more duplicate format strings)
affects: [05-04-relabel, 05-05-readme, future SKILL integrations]

tech-stack:
  added: []
  patterns:
    - "Sole-producer helper: one function owns a canonical string format (D-22)"
    - "Defensive defaults via dict.get(key, default) — sparse/malformed JSON never crashes cmd_status"
    - "Fallback path preserves legacy output byte-for-byte so Phase 1 CORE-13 tests keep passing"

key-files:
  created:
    - tests/test_phase5_summary.py
    - tests/test_phase5_status.py
  modified:
    - sync_chats.py

key-decisions:
  - "_format_summary is pure — no I/O, no logging — so the golden-string tests are trivial assertEqual"
  - "cmd_status adds extended metadata (Run at / Machine / Trigger) on the primary path but keeps the Phase 1 fallback shape intact to avoid breaking existing status tests"
  - "Empty-dict last_run.json counts as 'fall back' (truthy check on dict) — hand-edited or mid-write files degrade gracefully"

patterns-established:
  - "Canonical summary = one helper, one golden test, every caller imports it"
  - "cmd_status D-17 migration pattern: primary-then-fallback with no user-visible regression on old-world invocations"

requirements-completed:
  - OBSERV-01
  - OBSERV-04

duration: ~20min
completed: 2026-04-15
---

# Phase 05-03 Summary

**Centralized the OBSERV-01 summary in `_format_summary(run_dict)` and rewired `cmd_status` to read `last_run.json` first, falling back to `state.last_run_at` until the first `--once` fires.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 4 (TDD: RED → GREEN × 2)
- **Files modified:** 3 (1 production, 2 tests)
- **Tests added:** 12 (190 total, +12 from 178 baseline)

## Accomplishments

- `_format_summary(run)` is the sole producer of the D-23 canonical line — locked by 6 golden-string tests covering true/false/skipped variants, reason appending, missing-keys defensive defaults, and purity.
- `cmd_once` converges onto the shared helper — its temporary inline f-string is replaced by `_format_summary(last_run)`. Plan 02 tests still green.
- `cmd_status` now has two clearly-separated paths: `last_run.json` primary (summary + run metadata) and `state.last_run_at` fallback (legacy Phase 1 shape). An empty-dict `last_run.json` triggers fallback safely — no KeyError.
- `Pending:` count preserved on both paths (CORE-13 unbroken).

## Task Commits

1. **Task 1: RED \_format_summary golden-string tests** — `a2cd0c6` (test)
2. **Task 2: GREEN \_format_summary + cmd_once converge** — `fba7092` (feat)
3. **Task 3: RED cmd_status last_run.json tests** — `d5f7b66` (test)
4. **Task 4: GREEN cmd_status last_run.json + fallback** — `0891725` (refactor)

## Files Created/Modified

- `sync_chats.py` — Added `_format_summary`; refactored `cmd_once` to call it; rewired `cmd_status` with primary/fallback branches.
- `tests/test_phase5_summary.py` — 6 pure-function golden-string tests.
- `tests/test_phase5_status.py` — 6 integration tests using `contextlib.redirect_stdout` to capture stdout.

## Decisions Made

- `_format_summary` is placed above `cmd_once` in source order so the helper precedes its first caller — readability choice, no functional impact.
- Primary path shows **6 lines** (summary + 5 metadata) vs fallback's **6 lines** (classic Phase 1). Equal line count keeps terminal output rhythm consistent across the migration window.
- `_load_json` returns `{}` on both missing and malformed files, so both cases follow the same fallback branch — one less edge case to reason about.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Plan 04 (`relabel`) can now display an `_format_summary(last_run)` line after each re-label batch if desired (pattern is established; not required).
- Plan 05 (README) can reference the exact canonical summary line and `python3 sync_chats.py status` output knowing both come from the same helper.
- Any future caller (SKILL hooks, dashboards, cross-tool integrations) has a single import to call for byte-identical output.

---

_Phase: 05-sessionend-hook-observability-multi-machine-onboarding_
_Completed: 2026-04-15_
