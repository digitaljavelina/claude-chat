---
phase: 01-scanner-state-stub-label-write-pipeline
plan: "04"
subsystem: sync_chats
tags:
  [
    unit-tests,
    canary,
    test-isolation,
    clobber-defense,
    pure-functions,
    slug,
    stub-label,
    frontmatter,
    icloud-assertion,
    state-io,
  ]
dependency_graph:
  requires: [01-01, 01-02, 01-03]
  provides:
    [
      tests/test_sync_chats.py,
      tests/fixtures/sample_session.jsonl,
      tests/phase1_canary.sh,
    ]
  affects: [sync_chats.py]
tech_stack:
  added: []
  patterns:
    [
      python3 -m unittest stdlib test runner,
      CLAUDE_CHAT_HOME env var override for test isolation,
      CLAUDE_PROJECTS_DIR env var override for fake projects dir,
      SYNC_CHATS_CLAUDE_CLI env var override for mock subprocess,
      mktemp + trap EXIT for canary cleanup,
      O_CREAT|O_EXCL test for clobber defense layer 2,
    ]
key_files:
  created:
    [
      tests/__init__.py,
      tests/test_sync_chats.py,
      tests/fixtures/sample_session.jsonl,
      tests/phase1_canary.sh,
    ]
  modified: [sync_chats.py, .gitignore]
decisions:
  - "SYNC_CHATS_CLAUDE_CLI env var added to _get_markdown_body so canary can inject a mock without file manipulation"
  - "CLAUDE_PROJECTS_DIR env var added to PROJECTS_DIR for canary isolation consistent with CLAUDE_CHAT_HOME pattern (D-29)"
  - "__pycache__ added to .gitignore (generated output, should not be committed)"
metrics:
  duration_minutes: 20
  completed: "2026-04-13"
  tasks_completed: 2
  files_created: 4
  files_modified: 2
---

# Phase 1 Plan 04: Unit Tests + End-to-End Canary Script Summary

35-test unit suite covering all pure functions and clobber defenses, plus a 9-criterion bash canary that walks every Phase 1 ROADMAP success criterion end-to-end — both stdlib-only, zero external dependencies, fully isolated from real user state.

## Tasks Completed

| Task | Name                                                            | Commit  | Key Files                                                                           |
| ---- | --------------------------------------------------------------- | ------- | ----------------------------------------------------------------------------------- |
| 1    | Create test fixtures and unit tests for pure functions          | 63b02db | tests/**init**.py, tests/fixtures/sample_session.jsonl, tests/test_sync_chats.py    |
| 2    | Create canary script and add env var overrides to sync_chats.py | 4641ac0 | tests/phase1_canary.sh, sync_chats.py (CLAUDE_PROJECTS_DIR + SYNC_CHATS_CLAUDE_CLI) |

## What Was Built

**tests/**init**.py** — Empty package marker so `python3 -m unittest discover tests` can find `test_sync_chats.py`.

**tests/fixtures/sample_session.jsonl** — 3-line JSONL fixture with a real session structure (verified from RESEARCH.md §JSONL structure): one user message, one assistant response with usage dict (500 input + 100 output tokens), one follow-up user message. Session UUID `541112ec-a07c-4d87-80f7-2310b98fd7ea`, date `2026-03-19`.

**tests/test_sync_chats.py** — 572 lines, 11 test classes, 35 test methods covering:

| Class               | Tests | Coverage                                                                |
| ------------------- | ----- | ----------------------------------------------------------------------- |
| TestSlug            | 6     | make_slug: basic, unicode, fallback, truncation, dashes                 |
| TestStubLabel       | 3     | make_stub_label: 8-word title, empty fallback, schema                   |
| TestFrontmatter     | 5     | emit_frontmatter: delimiters, nulls, bool, tags, order                  |
| TestICloudAssertion | 2     | \_assert_not_icloud: iCloud path rejected, normal OK                    |
| TestStateIO         | 3     | \_write_atomic, load_state: create, bak, default state                  |
| TestClobberLayer1   | 2     | discover_sessions: synced id excluded, unsynced included                |
| TestClobberLayer2   | 2     | \_write_if_not_exists: creates new, refuses existing                    |
| TestAutoLabelHash   | 3     | sha256 hex format, hash in frontmatter, distinct hashes                 |
| TestSessionDate     | 2     | \_get_session_date: correct date, YYYY-MM-DD format                     |
| TestMetadata        | 3     | \_extract_session_metadata: model, token_count, msg_count               |
| TestStdinContract   | 4     | label JSON schema: valid, missing title, unknown keys, stub passthrough |

**tests/phase1_canary.sh** — 227-line bash script testing all 9 ROADMAP success criteria in an isolated `mktemp -d` environment with `trap EXIT` cleanup. Uses a mock `claude-chat.py` stub pointed at via `SYNC_CHATS_CLAUDE_CLI` so the canary never requires real Claude sessions.

**sync_chats.py changes** — Two one-line env var overrides added:

- `PROJECTS_DIR` now reads `CLAUDE_PROJECTS_DIR` env var (falling back to `~/.claude/projects/`)
- `_get_markdown_body()` now reads `SYNC_CHATS_CLAUDE_CLI` env var (falling back to resolved `claude-chat.py` path)

Both follow the same testability pattern as the existing `CLAUDE_CHAT_HOME` override (D-29).

## Verification Results

| Check                                                    | Result            |
| -------------------------------------------------------- | ----------------- |
| `python3 -m unittest discover tests -v` — 35 tests       | PASS (0 failures) |
| `bash tests/phase1_canary.sh` — 9 criteria               | PASS (0 failures) |
| Criterion 1: init creates config.json with machine_label | PASS              |
| Criterion 2: scan returns valid JSON with session UUID   | PASS              |
| Criterion 3: write creates vault file with frontmatter   | PASS              |
| Criterion 4: second write skipped (already_synced)       | PASS              |
| Criterion 5: clobber defense holds after state deletion  | PASS              |
| Criterion 6: iCloud assertion fires on iCloud path       | PASS              |
| Criterion 7: export --stdout flag registered             | PASS              |
| Criterion 8: status shows machine label                  | PASS              |
| Criterion 9: protect audit document exists               | PASS              |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] **pycache** not in .gitignore**

- **Found during:** Task 2 (post-commit git status check)
- **Issue:** Running tests created `__pycache__/` directories that appeared as untracked files
- **Fix:** Added `__pycache__/` and `*.pyc` to `.gitignore`
- **Files modified:** `.gitignore`
- **Commit:** `7f69afe`

No other deviations — plan executed as written.

## Known Stubs

None introduced in this plan. The test fixture intentionally exercises the Phase 1 stub label contract (`gist: null`, `tags: ["stub"]`, `needs_review: true`). These are documented stubs from Plan 03, not new ones.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. All files created are test infrastructure only. The two sync_chats.py changes add env var read points — both follow the existing CLAUDE_CHAT_HOME pattern and read from process environment only (no network, no disk beyond what the function already does).

## Self-Check: PASSED

- [x] `tests/__init__.py` exists at `tests/__init__.py`
- [x] `tests/test_sync_chats.py` exists (572 lines, > 100)
- [x] `tests/fixtures/sample_session.jsonl` exists (3 lines of valid JSON)
- [x] `tests/phase1_canary.sh` exists (227 lines, > 50)
- [x] Commit `63b02db` exists (`test(01-04): add unit tests...`)
- [x] Commit `4641ac0` exists (`feat(01-04): add canary script...`)
- [x] `python3 -m unittest discover tests -v` → 35 tests OK, 0 failures
- [x] `bash tests/phase1_canary.sh` → 9 passed, 0 failed
- [x] `grep -c "CLAUDE_PROJECTS_DIR" sync_chats.py` → 2 (>= 1)
- [x] `grep -c "SYNC_CHATS_CLAUDE_CLI" sync_chats.py` → 2 (>= 1)
