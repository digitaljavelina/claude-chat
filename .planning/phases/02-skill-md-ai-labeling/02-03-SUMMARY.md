---
phase: 02-skill-md-ai-labeling
plan: "03"
subsystem: tests
tags: [testing, edge-cases, ultra-short-skip, user-message-counting]
dependency_graph:
  requires: [02-01, 02-02]
  provides: [LABEL-07-tests, LABEL-02-checkpoint]
  affects: [tests/test_phase2_labels.py]
tech_stack:
  added: []
  patterns:
    [module-level-test-helpers, tempfile-based-fixtures, boundary-value-testing]
key_files:
  created: []
  modified:
    - tests/test_phase2_labels.py
decisions:
  - count_user_messages uses len(text) > 5 threshold matching SKILL.md Step 2a exactly
  - should_skip_session is a thin wrapper returning count < 2 per D-05
  - tempfile.NamedTemporaryFile with delete=False used for inline fixture creation
metrics:
  duration: "~8 minutes"
  completed: "2026-04-13T18:43:24Z"
  tasks_completed: 1
  tasks_pending: 1
  files_modified: 1
requirements:
  - LABEL-07
  - LABEL-02
---

# Phase 2 Plan 03: Edge Case Tests and End-to-End Verification Summary

## One-liner

Edge case tests for D-05 ultra-short skip with 0/1/2 message boundary values, block-list format, and system-reminder filtering — all 97 tests green.

## Task Status

| Task | Name                                                               | Status                                | Commit  |
| ---- | ------------------------------------------------------------------ | ------------------------------------- | ------- |
| 1    | Add edge-case tests for ultra-short skip and user message counting | COMPLETE                              | 60c8ff8 |
| 2    | Verify /sync-chats skill works end-to-end                          | PENDING — awaiting human verification |

## What Was Built (Task 1)

Added to `tests/test_phase2_labels.py`:

**`count_user_messages(jsonl_path: str) -> int`** — module-level function replicating SKILL.md Step 2a counting logic. Handles plain-string and block-list content formats, skips `<system-reminder>` injections, skips messages with 5 or fewer characters, gracefully handles empty files and malformed JSONL lines.

**`should_skip_session(jsonl_path: str) -> bool`** — thin wrapper returning `count_user_messages(path) < 2` per D-05.

**`TestEdgeCases`** class with 9 tests:

- `test_count_short_session` — short_session.jsonl returns 1
- `test_count_multi_turn` — multi_turn_session.jsonl returns >= 6
- `test_count_empty_file` — empty file returns 0
- `test_count_skips_system_reminder` — system-reminder content not counted
- `test_count_block_list_format` — block-list content counted correctly
- `test_should_skip_0_messages` — 0 messages -> skip (True)
- `test_should_skip_1_message` — 1 message -> skip (True)
- `test_should_not_skip_2_messages` — 2 messages -> do not skip (False)
- `test_should_not_skip_multi_turn` — multi_turn -> do not skip (False)

Full suite result: **97 tests, 20 subtests, all passing.**

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None. Tests only read existing JSONL files and write to OS temp directory.

## Self-Check: PASSED

- `tests/test_phase2_labels.py` contains `def count_user_messages(` — FOUND
- `tests/test_phase2_labels.py` contains `def should_skip_session(` — FOUND
- `tests/test_phase2_labels.py` contains `class TestEdgeCases` — FOUND
- Commit 60c8ff8 exists — FOUND
- `pytest tests/test_phase2_labels.py::TestEdgeCases -v` exits 0, 9 passed — VERIFIED
- `pytest tests/ -v` exits 0, 97 passed — VERIFIED
