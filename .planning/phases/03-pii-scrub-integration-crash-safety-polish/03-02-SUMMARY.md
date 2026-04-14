---
phase: 03-pii-scrub-integration-crash-safety-polish
plan: 02
subsystem: sync_chats
tags: [pii-scrub, write-pipeline, structural-ordering, frontmatter, stdlib]
dependency-graph:
  requires:
    - "03-01: scrub_content(body) -> (text, stats) pure function"
  provides:
    - "_get_markdown_body(session_id) -> tuple[str, dict] (scrub-before-return)"
    - "_derive_privacy_review(stats) -> Literal['clean','scrubbed','uncertain']"
    - "_log_scrub_stats(session_id, stats) -> None (D-21 format)"
    - "emit_frontmatter: privacy_review field always present between needs_review and project"
    - "cmd_write: needs_review force-on when privacy_review == 'uncertain' (D-07)"
  affects:
    - "Plan 03-03 (manual-edit refusal) — _reconcile_crash signature extension will touch the same cmd_write block"
    - "Plan 03-04 (canary) — will exercise the full wired pipeline end-to-end"
tech-stack:
  added: []
  patterns:
    - "Tuple-return as structural ordering enforcement (caller cannot get raw string — TypeError at unpack)"
    - "Default-arg binding already established in 03-01 scrub_content preserved"
    - "Sparse-dict-tolerant stats consumers (stats.get(k, 0) + sum over present keys)"
key-files:
  created:
    - tests/test_scrub_integration.py
  modified:
    - sync_chats.py
decisions:
  - "scrub_content has exactly 1 call site in sync_chats.py (the one inside _get_markdown_body) — enforced by TestGetMarkdownBodyReturnsTuple.test_scrub_content_called_exactly_once_in_source so any future regression fails loudly"
  - "_log_scrub_stats uses sparse-nonzero rendering (zero-count pattern keys elided from log dict) — matches D-21 example and keeps grep output readable"
  - "_derive_privacy_review treats sparse stats dicts (missing keys) as zero — tolerant of future stats-shape changes; tested explicitly via test_minimal_stats_shape_accepted"
  - "auto_label_hash is computed AFTER the tuple-unpack, over the SCRUBBED body bytes (D-05) — crash reconciliation remains deterministic because re-rendering + re-scrubbing reproduces the same hash"
metrics:
  duration: "~6 minutes"
  completed: "2026-04-13T17:30:00Z"
  tasks: 2
  commits: 2
  tests_added: 19
  tests_total_passing: 140
---

# Phase 3 Plan 02: Wire scrub_content into write pipeline — Summary

**One-liner:** Make `_get_markdown_body` internally call `scrub_content` and return `(body, stats)` — structurally locking the `scrub → label → write` ordering so labels can never see raw content — plus the `privacy_review` frontmatter field, D-07 force-on of `needs_review`, and D-21 log line.

## What was built

### `sync_chats.py` modifications (+90 / −9 lines, commit `8fbc3b3`)

**1. `_get_markdown_body` signature change (D-03)**

```python
# Before (Plan 01 baseline):
def _get_markdown_body(session_id: str) -> str:
    ...
    return result.stdout

# After (Plan 03-02):
def _get_markdown_body(session_id: str) -> "tuple[str, dict]":
    ...
    raw_body = result.stdout
    scrubbed_body, scrub_stats = scrub_content(raw_body)
    return scrubbed_body, scrub_stats
```

- Raw `raw_body` is a local variable; only the scrubbed form escapes.
- Return-type annotation is `tuple[str, dict]` — any caller that tried to treat the result as `str` would either TypeError on the tuple-unpack or fail string operations downstream.
- Test `TestGetMarkdownBodyReturnsTuple.test_scrub_content_called_exactly_once_in_source` asserts there is only one `scrub_content(` call site in the source (plus the definition line) — any future regression that adds a second call fails loudly.

**2. New helpers (lines ~770–830):**

- `_derive_privacy_review(stats) -> str` — returns one of `"clean" | "scrubbed" | "uncertain"` per D-08. Tolerates sparse stats dicts (missing keys = 0). Uncertain wins over named hits.
- `_log_scrub_stats(session_id, stats) -> None` — emits one D-21 line or nothing (D-22). Sparse-nonzero rendering keeps the log grep-friendly.

**3. `emit_frontmatter.KEY_ORDER` extended** — `"privacy_review"` inserted between `"needs_review"` and `"project"` (D-08, always present).

**4. `cmd_write` consumption (around line 1050):**

```python
body, scrub_stats = _get_markdown_body(args.session_id)
_log_scrub_stats(args.session_id, scrub_stats)
...
body_bytes = body.encode("utf-8")
auto_label_hash = hashlib.sha256(body_bytes).hexdigest()  # D-05: over scrubbed bytes

privacy_review = _derive_privacy_review(scrub_stats)
needs_review_value = label.get("needs_review", True)
if privacy_review == "uncertain":
    needs_review_value = True  # D-07 force-on
```

### `tests/test_scrub_integration.py` (new, 288 lines, 19 tests across 5 classes)

| Class                           | Tests | Coverage                                                                                                    |
| ------------------------------- | ----- | ----------------------------------------------------------------------------------------------------------- |
| TestGetMarkdownBodyReturnsTuple | 2     | Return annotation references `tuple`; `scrub_content(` appears exactly twice in source (def + one call)     |
| TestDerivePrivacyReview         | 5     | clean/scrubbed/uncertain mapping; uncertain-wins-over-named; sparse stats dict tolerance                    |
| TestLogScrubStatsFormat         | 5     | D-22 skip-when-clean; D-21 exact format; PRIV-06 no-substring-leak; uncertain shown in log; 8-char short-id |
| TestFrontmatterHasPrivacyReview | 3     | emit_frontmatter renders privacy_review; all 3 values render; KEY_ORDER position verified                   |
| TestNeedsReviewForceOn          | 4     | force-on when uncertain; preserve-true when already true; no-force-on for scrubbed/clean                    |

Full suite: **140 tests pass** (121 prior + 19 new) via `python3 -m unittest discover tests` — zero regression.

## Before/after signature of `_get_markdown_body`

```diff
-def _get_markdown_body(session_id: str) -> str:
-    """Call claude-chat.py export --format md --stdout and return the rendered markdown."""
+def _get_markdown_body(session_id: str) -> "tuple[str, dict]":
+    """Call claude-chat.py export --format md --stdout, scrub, return (body, scrub_stats)."""
```

## Example log line (from `test_scrubbed_session_writes_d21_format`)

```
2026-04-13T17:28:42.123456+00:00 scrub session=abcdefgh patterns={email:3, jwt:1} total_chars=287
```

- `session=abcdefgh` is the first 8 chars of the UUID (D-21).
- `patterns={...}` contains only non-zero counts (zeros elided).
- `total_chars=287` counts bytes redacted (original match lengths summed).
- Zero matched substrings present — `PRIV-06` asserted by `test_log_contains_no_matched_substring`.

## Example frontmatter snippet (uncertain path, D-07 force-on in action)

When the body contains a bare 32+ char high-entropy run and the label JSON supplied `"needs_review": false`:

```yaml
---
title: Debug session with unknown token
gist: null
tags:
  - debug
coherence_score: 7
needs_review: true # forced by D-07 even though label said false
privacy_review: uncertain # D-08 three-value enum, always present
project: some-project
session_id: 0123...
...
---
```

## Deviations from Plan

None — plan executed exactly as written.

### Auth gates

None.

## Commits

| Hash      | Subject                                                                      |
| --------- | ---------------------------------------------------------------------------- |
| `8fbc3b3` | feat(03-02): wire scrub_content into \_get_markdown_body; add privacy_review |
| `dfb9617` | test(03-02): add integration tests for scrub wiring                          |

## Threat mitigation status

| Threat ID  | Category          | Disposition | Status                                                                                                                                                |
| ---------- | ----------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-03-02-01 | I (T1 from phase) | mitigate    | ✅ `test_signature_is_tuple` + `test_scrub_content_called_exactly_once_in_source` — raw body cannot escape the function, enforced by source assertion |
| T-03-02-02 | I (T2 from phase) | mitigate    | ✅ `test_log_contains_no_matched_substring` — log assertion bans `@`, `eyJ`, `ghp_` sentinels                                                         |
| T-03-02-03 | T                 | accept      | No change in cmd_write between tuple-unpack and hash computation (visually verified lines 1050–1059)                                                  |
| T-03-02-04 | R                 | mitigate    | `privacy_review` always emitted per D-08; absence would be a bug catchable via Dataview                                                               |
| T-03-02-05 | I                 | mitigate    | ✅ `test_force_on_when_uncertain_overrides_label_false` — D-07 branch converts label-false → written-true                                             |
| T-03-02-06 | D                 | accept      | O(n) scrub; bodies bounded by context window. No streaming needed for v1                                                                              |

Both HIGH-severity threats (T-03-02-01, T-03-02-02) blocked by passing tests.

## Success criteria status (from 03-02-PLAN.md)

- ✅ ROADMAP SC#3 (uncertain path written with privacy_review+needs_review flags): force-on branch in cmd_write; force-on tests pass
- ✅ ROADMAP SC#4 (log safety): `test_log_contains_no_matched_substring` passes
- ✅ ROADMAP SC#6 (structural ordering): signature is `tuple[str, dict]`; scrub call count asserted at 2 occurrences (1 def + 1 call)
- ✅ PRIV-01 (locked ordering by code structure) — function boundary
- ✅ PRIV-05 (fail-open-with-flag) — uncertain still writes
- ✅ PRIV-06 (non-leaking logs) — asserted

## Known Stubs

None. All wiring is complete and exercised by tests. Full end-to-end canary exercise (writing a real session + grep of resulting markdown) is explicitly Plan 03-04's scope.

## Self-Check: PASSED

- FOUND: `sync_chats.py` modified (tuple return annotation + privacy_review field + force-on branch)
- FOUND: `tests/test_scrub_integration.py` created (288 lines, 19 tests)
- FOUND: commit `8fbc3b3` in git log
- FOUND: commit `dfb9617` in git log
- VERIFIED: `python3 -m unittest tests.test_scrub_integration` exits 0 (19/19)
- VERIFIED: `python3 -m unittest discover tests` exits 0 (140 tests, zero regression)
- VERIFIED: `grep -c '"privacy_review"' sync_chats.py` = 2 (KEY_ORDER + fields dict)
- VERIFIED: `grep -c 'if privacy_review == "uncertain":' sync_chats.py` = 1 (force-on branch)
- VERIFIED: `scrub_content(` appears exactly 2 times in sync_chats.py (def + 1 call site)
- VERIFIED: No `import pytest`, no new dependencies (zero-deps invariant maintained)
