---
phase: 05-sessionend-hook-observability-multi-machine-onboarding
plan: 01
subsystem: infra
tags: [python, atomic-writer, refactor, tdd]

requires:
  - phase: 01-vault-write-pipeline
    provides: cmd_write monolith + _write_atomic template + auto_label_hash (SHA-256 body)
  - phase: 02-ai-labeling
    provides: label dict schema (title, gist, tags, coherence_score, needs_review)
  - phase: 03-pii-scrub
    provides: scrub_content + _log_scrub_stats + _get_markdown_body (body, stats) tuple
provides:
  - _write_session(session_id, label, config, state) -> str helper (extracted from cmd_write)
  - _write_last_run(dict) atomic writer (tmp + fsync + rename + .bak)
  - LAST_RUN_PATH module-level constant (CLAUDE_CHAT_HOME / last_run.json)
  - Stub-sentinel auto_label_hash override path (label["auto_label_hash_override"] = "stub")
affects: [05-02-cmd-once, 05-03-cmd-status, 05-04-relabel]

tech-stack:
  added: []
  patterns:
    - "Near-copy atomic writer (not generic helper) — per D-14 readability preference"
    - "Helper raises ValueError on bad input; caller decides exit-code policy"
    - "Stub sentinel as label key, not a global flag — keeps D-02 stdin contract intact"

key-files:
  created:
    - tests/test_phase5_last_run.py
    - tests/test_phase5_write_session.py
  modified:
    - sync_chats.py

key-decisions:
  - "_write_session raises ValueError on missing title; cmd_write keeps its sys.exit(1) behavior in the wrapper"
  - "_write_last_run is a near-copy of _write_atomic (D-14) rather than parameterizing — readability over DRY"
  - 'auto_label_hash_override is a label-dict key, not a function arg — future callers (cmd_once) set label["auto_label_hash_override"] = "stub"'
  - "Test fake scrub_stats shape corrected to match real schema ({uncertain, total_chars_redacted}) — the RED test's placeholder {redacted_count, patterns:[]} broke _log_scrub_stats' int-sum"

patterns-established:
  - "Pure helper + thin CLI wrapper: cmd_write now just parses stdin → calls _write_session → prints result"
  - "last_run.json path follows CLAUDE_CHAT_HOME convention — tests override via env, never hardcode ~/.claude-chat/"

requirements-completed:
  - OBSERV-03

duration: ~45min
completed: 2026-04-15
---

# Phase 05-01 Summary

**Extracted \_write_session helper from cmd_write and added \_write_last_run atomic writer + LAST_RUN_PATH constant, unlocking cmd_once (Plan 02) to write sessions in-process without stdin plumbing.**

## Performance

- **Duration:** ~45 min (spread across two sessions — tasks 1–3 earlier, task 4 + SUMMARY finished this session)
- **Tasks:** 4 (TDD: RED → GREEN × 2 pairs)
- **Files modified:** 3 (1 production, 2 tests)

## Accomplishments

- `_write_last_run(dict)` atomic writer in place (tmp + fsync + `shutil.copy2` .bak + `os.replace`) with `LAST_RUN_PATH = CLAUDE_CHAT_HOME / "last_run.json"`.
- `_write_session(session_id, label, config, state) -> str` extracted verbatim from `cmd_write`. Returns `"synced" | "skipped" | "reconciled" | "edited"`; raises `ValueError` on missing title; `cmd_write` is now a thin stdin-reading wrapper.
- Stub-sentinel support: `label["auto_label_hash_override"] == "stub"` injects `auto_label_hash: stub` in frontmatter instead of the SHA-256 body hash — the D-03 path Plan 02 will use.
- Full suite stays green: 159 pre-existing + 10 new = **169 tests passing**.

## Task Commits

1. **Task 1: RED tests for \_write_last_run** — `4c15fae` (test)
2. **Task 2: GREEN \_write_last_run + LAST_RUN_PATH** — `2026774` (feat)
3. **Task 3: RED tests for \_write_session** — `2bdee5f` (test)
4. **Task 4: GREEN \_write_session extraction + stub-sentinel override** — `aac5e9f` (refactor)

## Files Created/Modified

- `sync_chats.py` — Added `LAST_RUN_PATH`, `_write_last_run`, `_write_session`; rewrote `cmd_write` as a thin wrapper.
- `tests/test_phase5_last_run.py` — 5 unit tests for the atomic writer (schema, .bak preservation, tmp cleanup, env override, field presence).
- `tests/test_phase5_write_session.py` — 5 unit tests for the helper contract (synced / skipped / stub-sentinel / missing title / state update).

## Decisions Made

- Near-copy `_write_last_run` instead of parameterizing `_write_atomic` — D-14 prioritizes readability for a Python-beginner maintainer; parameterization would save ~8 lines at the cost of a less obvious control-flow path.
- `ValueError` for missing title inside `_write_session` — lets `cmd_once` (Plan 02) catch per-session and aggregate into `errors[]` without dragging `sys.exit` into the helper.
- Stub-sentinel is a label-dict key, not a separate CLI flag — keeps the D-02 stdin JSON contract intact and lets future callers opt in without touching `cmd_write`'s interface.

## Deviations from Plan

### Auto-fixed Issues

**1. Test fixture shape mismatch — `_FAKE_SCRUB_STATS` broke `_log_scrub_stats`**

- **Found during:** Task 4 final green run
- **Issue:** The RED test stubbed `_get_markdown_body` with `{"redacted_count": 0, "patterns": []}`. The real shape is all-int (`{name: 0, ..., "uncertain": 0, "total_chars_redacted": 0}`). `_log_scrub_stats` sums non-`total_chars_redacted` values, so `sum(0, [])` raised `TypeError: int + list`.
- **Fix:** Updated the fake to `{"uncertain": 0, "total_chars_redacted": 0}`, matching the real schema. All 10 phase5 tests + 159 pre-existing tests now pass.
- **Files modified:** `tests/test_phase5_write_session.py`
- **Verification:** `pipx run pytest tests/ -q` → 169 passed
- **Committed in:** `aac5e9f` (bundled with Task 4 GREEN commit)

---

**Total deviations:** 1 auto-fixed (test-fixture shape bug).
**Impact on plan:** None on scope — the stub was wrong at RED time but didn't surface until the helper actually called `_log_scrub_stats`. Fix is a one-line test fixture correction; no production-code consequences.

## Issues Encountered

None beyond the deviation above.

## Next Phase Readiness

- `cmd_once` (Plan 05-02) can now call `_write_session(sid, stub_label, config, state)` in-process without stdin plumbing. Stub label builder is `make_stub_label(jsonl_path, session_id)` (already exists, Phase 1).
- `_write_last_run` ready for Plan 05-02's summary-line persistence and Plan 05-03's `cmd_status` rewire.
- Stub-sentinel path wired: Plan 05-04's `relabel` subcommand will look for `auto_label_hash == "stub"` to gate its frontmatter rewrite.

---

_Phase: 05-sessionend-hook-observability-multi-machine-onboarding_
_Completed: 2026-04-15_
