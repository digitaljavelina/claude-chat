---
phase: 03-pii-scrub-integration-crash-safety-polish
plan: 04
subsystem: scrub-canary-ci
tags: [pii-scrub, ci, canary, priv-04]
wave: 3
requirements: [PRIV-04]
dependency_graph:
  requires: [03-01, 03-02]
  provides:
    - "Canary fixture + end-to-end test that mechanically enforces ROADMAP SC#1"
    - "GitHub Actions CI gate that blocks scrub regressions (ROADMAP SC#2)"
    - "D-16 bash integration: phase1_canary.sh invokes the Python canary"
  affects: [tests/phase1_canary.sh]
tech_stack:
  added: [GitHub Actions (actions/checkout@v4, actions/setup-python@v5)]
  patterns:
    - "Synthetic-PII fixture with CANARY sentinel for unambiguous grep assertions"
    - "Paths-filtered CI trigger (docs edits don't waste CI minutes)"
    - "unittest discover as the single invocation across all test files"
key_files:
  created:
    - tests/canary_session.jsonl
    - tests/test_scrub_canary.py
    - .github/workflows/canary.yml
  modified:
    - tests/phase1_canary.sh
decisions:
  - "D-16 bash integration: phase1_canary.sh stays authoritative by calling the Python canary at the end"
  - "Removed CANARY tokens from surrounding prose in the fixture so the single assertion `assertNotIn(b'CANARY', vault_bytes)` is a true grep-style guard (any hit = real leakage)"
metrics:
  duration: "~15 minutes"
  completed_at: "2026-04-13"
  tasks_completed: 3
  tests_added: 2
  test_suite_total: 142
---

# Phase 3 Plan 4: Canary Fixture + CI Gate Summary

Plant a 13-pattern synthetic-PII fixture, wire it through the full `load -> scrub -> label -> write` pipeline with a unittest acceptance test that greps the resulting vault bytes for a `CANARY` sentinel (zero hits = pass), and add a `.github/workflows/canary.yml` CI workflow that runs the full test suite on every push/PR touching scrub-relevant paths. Extend `tests/phase1_canary.sh` per D-16 so the existing bash success-criteria runner invokes the Python canary too.

## Tasks Completed

| Task | Commit    | Files                                                                  |
| ---- | --------- | ---------------------------------------------------------------------- |
| 1    | `5523cf6` | `tests/canary_session.jsonl`                                           |
| 2    | `9dfb8c1` | `tests/test_scrub_canary.py`                                           |
| 3    | `807cc0e` | `.github/workflows/canary.yml`, `tests/phase1_canary.sh` (D-16 append) |

## Canary Fixture Pattern Coverage

Scrub stats when `tests/canary_session.jsonl` user message is passed through `sync_chats.scrub_content`:

| Pattern        | Hits | CANARY in secret? | Notes                                         |
| -------------- | ---- | ----------------- | --------------------------------------------- |
| `email`        | 1    | yes               | `canary.user+CANARY@example.com`              |
| `jwt`          | 1    | yes               | eyJ three-segment form with `CANARY_SIGPART`  |
| `github_token` | 6    | yes               | ghp/gho/ghu/ghs/ghr + github_pat variants     |
| `aws_key`      | 1    | yes               | `AKIAIOSFODCANARY0000` (exactly 16 post-AKIA) |
| `slack`        | 1    | yes               | `xoxb-...CANARY00` (24+ chars post-dash)      |
| `stripe`       | 1    | yes               | `sk_live_...CANARY` (32 chars post-prefix)    |
| `anthropic`    | 1    | yes               | `sk-ant-api-01-...CANARY`                     |
| `openai`       | 1    | yes               | `sk-...CANARY` (48 chars post-prefix)         |
| `bearer`       | 1    | yes               | `Bearer abcdef1234567890CANARY`               |
| `basic_auth`   | 1    | yes               | `Basic CANARYdXNlcjpwYXNz=`                   |
| `ipv4`         | 1    | n/a (digits only) | `203.0.113.42` (TEST-NET-3, public)           |
| `ipv6`         | 1    | n/a (hex only)    | `2001:db8:cafe:face::1`                       |
| `phone`        | 1    | n/a (digits only) | `(555) 867-5309`                              |
| `uncertain`    | 0    | —                 | all matches are named; no fallback fires      |

**Sentinel count:** `grep -o CANARY tests/canary_session.jsonl | wc -l` = **15** (embedded in every regex-containable secret).

**Negative canary (D-10 skip-list — must survive unchanged):**

- `192.168.1.100` (RFC-1918 Class C private) — survives
- `127.0.0.1` (loopback) — survives

Total chars redacted across the bundle: **731**.

## Test Suite Summary

| File                              | Tests   | Notes                                                   |
| --------------------------------- | ------- | ------------------------------------------------------- |
| `tests/test_scrub.py`             | 23      | Plan 03-01 unit tests on `scrub_content`                |
| `tests/test_scrub_integration.py` | 19      | Plan 03-02 wiring + frontmatter + D-21 log format       |
| `tests/test_scrub_canary.py`      | 2       | **This plan** — PRIV-04 end-to-end + PRIV-06 log safety |
| (all other Phase 1/2 tests)       | 98      | Scanner, state, write pipeline, stub labeler, etc.      |
| **Total**                         | **142** | Full suite passes: `python3 -m unittest discover tests` |

`tests/test_reconcile_edited.py` is plan 03-03's territory (parallel plan) — not included in the count above.

## CI Workflow

**File:** `.github/workflows/canary.yml` (first workflow in this repo)

**Trigger paths** (on both `push` and `pull_request`):

- `sync_chats.py` — the only module whose behavior affects scrub/label
- `scrub*.py` — reserved for future `scrub.py` sibling if extracted
- `tests/**` — any test change (unit, integration, canary, fixtures)
- `.github/workflows/canary.yml` — workflow self-change

**Runtime:** `python3 -m unittest discover tests -v` on `ubuntu-latest` with Python 3.12. Zero-deps invariant preserved: no `pip install`, no `requirements.txt`.

**First CI run duration:** TBD on first push to GitHub. Local suite runs in ~15ms, so expect <30s wall-clock including checkout + Python setup.

## D-16 Bash Integration

`tests/phase1_canary.sh` now runs 10 checks (was 9):

1. Criterion 1-9: original Phase 1 success criteria
2. **Phase 3 scrub canary (PRIV-04)**: invokes `python3 -m unittest tests.test_scrub_canary -v`

Verified end-to-end: `bash tests/phase1_canary.sh` exits 0 with `Results: 10 passed, 0 failed`.

## Requirements Closed

- **PRIV-04** — Canary test feeds a synthetic PII bundle through the full pipeline and asserts grep for every sentinel in the resulting vault file returns zero matches. Mechanically enforced by CI.
- **ROADMAP SC#1** — `grep -c CANARY <vault_file>` returns 0 after the pipeline run (`test_full_pipeline_zero_canary_survivors`).
- **ROADMAP SC#2** — `.github/workflows/canary.yml` runs on every scrub-relevant change; passing the full `unittest discover tests` is the CI gate.
- **ROADMAP SC#4** — `test_sync_log_contains_no_canary` asserts sync.log has pattern names + counts only (PRIV-06).

## Deviations from Plan

### Fixture prose cleanup (defensive)

- **Found during:** Task 1 verification. The original draft put `CANARY-email:` style labels around each secret for readability, which meant `CANARY` appeared in non-secret prose. After scrub, the redacted fixture still contained lots of `CANARY` substrings — but they came from the labels, not leaked secrets. That would have defeated the whole point of the `assertNotIn(b"CANARY", vault_bytes)` assertion (it would always fail, teaching us nothing about actual scrub behavior).
- **Fix:** Replaced `CANARY-email:` / `CANARY-jwt:` / etc. labels with plain `email:` / `jwt:` / etc. The `CANARY` sentinel now appears ONLY inside the synthetic secrets themselves. After scrub, a single `grep CANARY <vault>` definitively reports leaks (zero = safe, non-zero = bug).
- **Files modified:** `tests/canary_session.jsonl`
- **Rule:** Rule 1 (bug) — an assertion that always fails for the wrong reason is a broken test.

### Fixture token length fixes

- **Found during:** Task 1 verification. `github_pat_...CANARY` and `aws_key` initial drafts didn't hit the regex minimum lengths (77-char vs 82+ required for github_pat; 20-char vs exactly-16 required for AWS).
- **Fix:** Padded github_pat tail to 86 chars; rewrote AWS to `AKIAIOSFODCANARY0000` (exactly 16 post-AKIA). Re-verified `scrub_content` counts all 13 named patterns at >=1.
- **Files modified:** `tests/canary_session.jsonl`
- **Rule:** Rule 1 (bug).

### GitHub Actions security header

- **Found during:** Task 3 write. The editor security hook flagged workflow-injection risks.
- **Fix:** Added an explicit comment in `canary.yml` documenting that no `github.event.*` inputs are interpolated into `run:` blocks, so there is no command injection surface. The workflow uses only fixed commands.
- **Files modified:** `.github/workflows/canary.yml`
- **Rule:** Rule 2 (critical correctness — security note makes the safe pattern explicit for future editors).

## Known Stubs

None. This plan is pure test/CI infrastructure — no stubs, no mocks bleeding into production code.

## Self-Check

- [x] `tests/canary_session.jsonl` exists, valid JSONL, 13 patterns match, zero `CANARY` survivors after scrub, private IPs preserved.
- [x] `tests/test_scrub_canary.py` exists, 2 tests pass.
- [x] `.github/workflows/canary.yml` exists, paths filter includes all required triggers, uses `setup-python@v5` + Python 3.12, runs `unittest discover tests`.
- [x] `tests/phase1_canary.sh` extended with Phase 3 canary invocation (D-16), `bash -n` valid, end-to-end run exits 0 with 10/10 pass.
- [x] `python3 -m unittest discover tests` passes 142 tests (140 Phase 1/2 baseline + 2 new).
- [x] Commits: `5523cf6`, `9dfb8c1`, `807cc0e` — all exist on `plan-03-04-exec` branch.

## Self-Check: PASSED
