---
phase: 02-skill-md-ai-labeling
plan: "01"
subsystem: skill-authoring
tags:
  - skill-md
  - test-scaffolding
  - label-validation
  - fixtures
dependency_graph:
  requires:
    - 01-scanner-state-stub-label-write-pipeline (sync_chats.py with make_stub_label, cmd_scan, cmd_write)
  provides:
    - ~/.claude/skills/sync-chats/SKILL.md (invokable Claude Code skill)
    - tests/test_phase2_labels.py (label shape validators + JSON extraction helper)
    - tests/fixtures/short_session.jsonl (ultra-short skip testing)
    - tests/fixtures/multi_turn_session.jsonl (first/last extraction + both content formats)
  affects:
    - Phase 3 plans (test_phase2_labels.py validators ready to use)
    - Phase 5 (SKILL.md is the artifact the SessionEnd hook will invoke)
tech_stack:
  added: []
  patterns:
    - In-session labeling pattern (Claude is both executor and labeler; no external API)
    - json.dumps() serialization for safe shell pipe (T-02-01 mitigation)
    - make_stub_label() fallback on JSON parse failure (D-08)
key_files:
  created:
    - ~/.claude/skills/sync-chats/SKILL.md
    - tests/test_phase2_labels.py
    - tests/fixtures/short_session.jsonl
    - tests/fixtures/multi_turn_session.jsonl
  modified: []
decisions:
  - "SKILL.md is self-contained (no @-file references) — instruction set is compact enough to inline per RESEARCH.md recommendation"
  - "extract_label_json lives in test file only (not sync_chats.py) — it is a test-side validation helper; SKILL.md instructs Claude to do extraction inline"
  - "pytest installed via /tmp/test-venv rather than system-wide (PEP 668 restriction on this machine); tests run with /tmp/test-venv/bin/python3 -m pytest"
metrics:
  duration: "~30 minutes"
  completed: "2026-04-13T18:32:00Z"
  tasks_completed: 2
  files_created: 4
  tests_added: 45
  tests_passing: 45
---

# Phase 2 Plan 01: SKILL.md and Test Scaffolding Summary

**One-liner:** Created Claude Code skill file with full scan-label-write orchestration loop (with stub fallback) plus 45-test scaffolding for label shape validation and JSON extraction.

## Tasks Completed

| Task | Name                                                              | Commit         | Files                                                                                                          |
| ---- | ----------------------------------------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------- |
| 1    | Create SKILL.md with frontmatter and orchestration body           | (outside repo) | `~/.claude/skills/sync-chats/SKILL.md`                                                                         |
| 2    | Create test scaffolding and fixtures for Phase 2 label validation | `00e0ac8`      | `tests/test_phase2_labels.py`, `tests/fixtures/short_session.jsonl`, `tests/fixtures/multi_turn_session.jsonl` |

## What Was Built

### Task 1 — SKILL.md

`~/.claude/skills/sync-chats/SKILL.md` is a self-contained Claude Code skill with:

**Frontmatter (6 fields per D-09):**

- `name: sync-chats`
- `description: Sync Claude Code sessions to Obsidian vault with AI-generated labels`
- `disable-model-invocation: true`
- `allowed-tools: [Bash, Read]`
- `argument-hint: (no arguments - syncs all new sessions)`

**Body — 3-step sequential orchestration:**

1. **Scan:** `python3 $HOME/.claude-chat/sync_chats.py scan` → parse JSON delta list
2. **Per-session loop (5 sub-steps):**
   - 2a: Count user messages via Python one-liner; skip if < 2 (D-05)
   - 2b: Load JSONL via Read tool; extract first+last 5 user/assistant pairs
   - 2c: Present labeling prompt inline with 4 few-shot examples (debugging, setup, writing, exploratory) per D-03
   - 2d: Serialize label with `json.dumps()` and pipe to `sync_chats.py write` per T-02-01 mitigation
   - 2e: Fall back to `make_stub_label()` on JSON parse failure (D-08), no retry
3. **Summary line:** "Processed N sessions: M labeled, K stubbed, J skipped (ultra-short)."

Key security mitigation T-02-01 implemented: all label JSON goes through `python3 -c "import json; print(json.dumps({...}))"` to prevent shell injection from session titles containing quotes or apostrophes.

### Task 2 — Test Scaffolding (TDD)

`tests/test_phase2_labels.py` — 45 tests across 4 classes:

- **TestLabelValidation (32 tests):** `validate_title`, `validate_tags`, `validate_coherence_score`, `validate_gist` — each tested with valid and invalid inputs
- **TestExtractLabelJson (5 tests):** `extract_label_json` — valid extraction, missing block, malformed JSON, surrounding prose, empty block
- **TestStubFallback (4 tests):** `make_stub_label()` shape: all 5 required keys present, `needs_review is True`, `"stub" in tags`, title is non-empty string
- **TestFixtures (4 tests):** `short_session.jsonl` has exactly 1 user message; `multi_turn_session.jsonl` has ≥ 6; both exist; multi_turn has both content formats

**Fixtures:**

- `short_session.jsonl`: 1 user + 1 assistant message (for ultra-short skip test at D-05)
- `multi_turn_session.jsonl`: 6 user + 6 assistant messages, Flask session debugging conversation, includes both plain-string and block-list content formats

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written with one minor environment deviation:

**[Rule 3 - Blocking] pytest not installed system-wide**

- **Found during:** Task 2 verification
- **Issue:** `python3 -m pytest` not available; PEP 668 blocks pip install
- **Fix:** Created `/tmp/test-venv` venv and installed pytest there; all plan verify commands run via `/tmp/test-venv/bin/python3 -m pytest`
- **Note:** Tests are written as `unittest.TestCase` subclasses so they also run with `python3 -m unittest discover tests -v` (no pytest needed for CI)

**[Note] SKILL.md outside git repo**

- Task 1 produces no git-tracked files (skill lives at `~/.claude/skills/sync-chats/SKILL.md`)
- SKILL.md existence verified by acceptance criteria bash commands; committed indirectly via the SUMMARY referencing its path

## Threat Flags

No new threat surface introduced beyond what the plan's threat model already covers.

- T-02-01 mitigated: `json.dumps()` serialization pattern implemented in SKILL.md Step 2d
- T-02-03 mitigated: `extract_label_json()` returns None on parse failure; SKILL.md falls back to `make_stub_label()`. Test coverage in `TestExtractLabelJson`.

## Known Stubs

None. This plan creates scaffolding and a skill file — no stub data flows to any UI rendering path.

## Self-Check

Files exist:

- `~/.claude/skills/sync-chats/SKILL.md`: FOUND
- `tests/test_phase2_labels.py`: FOUND
- `tests/fixtures/short_session.jsonl`: FOUND
- `tests/fixtures/multi_turn_session.jsonl`: FOUND

Commits exist:

- `00e0ac8`: FOUND (Task 2)

All Phase 2 tests: 45 passed
All Phase 1 tests: 35 passed (no regressions)
