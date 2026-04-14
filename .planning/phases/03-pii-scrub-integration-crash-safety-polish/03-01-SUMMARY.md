---
phase: 03-pii-scrub-integration-crash-safety-polish
plan: 01
subsystem: sync_chats
tags: [pii-scrub, regex, stdlib, tdd]
dependency-graph:
  requires: []
  provides:
    - "sync_chats.scrub_content(body) -> (text, stats)"
    - "sync_chats.SCRUB_PATTERNS (13 named compiled regexes)"
    - "sync_chats.UNCERTAIN_PATTERN (high-entropy fallback)"
    - "sync_chats._is_private_ip(s) -> bool (D-10 skip-list)"
  affects:
    - "Plan 03-02 will import scrub_content and wire it into _get_markdown_body"
tech-stack:
  added: []
  patterns:
    - "Module-level re.compile() with inline `# matches:` comments (beginner-readable)"
    - "Default-arg binding in closure (`_name=name`) to avoid late-binding loop pitfall"
    - "Dict comprehension init so stats keys stay in lockstep with SCRUB_PATTERNS list"
key-files:
  created:
    - tests/test_scrub.py
  modified:
    - sync_chats.py
decisions:
  - "IPv6 regex expanded beyond D-09's example to handle :: zero-run compression (Rule 1 fix — original pattern failed on `2001:db8::1` and `::1`)"
  - "Pattern order locked: jwt/github/aws/slack/stripe/anthropic before openai before bearer/basic/ipv4/ipv6/phone; uncertain fallback runs second pass"
  - "Skip-list applied as post-match filter in replacement callback (not as pattern negation) — keeps the ipv4/ipv6 regex simple and the skip logic unit-testable"
metrics:
  duration: "~4 minutes"
  completed: "2026-04-14T00:14:16Z"
  tasks: 2
  commits: 2
  tests_added: 23
  tests_total_passing: 121
---

# Phase 3 Plan 01: scrub_content Pure Function — Summary

**One-liner:** Add `scrub_content(body) -> (text, stats)` to `sync_chats.py` with 13 credential/PII regexes + private-IP skip-list + high-entropy uncertain fallback, fully covered by 23 stdlib-unittest tests.

## What was built

### `sync_chats.py` additions (174 lines inserted between `emit_frontmatter` and `_extract_session_metadata`)

**SCRUB_PATTERNS (13 named regexes, evaluated in order):**

| #   | Name         | Pattern (verbatim)                                               | Source          |
| --- | ------------ | ---------------------------------------------------------------- | --------------- |
| 1   | email        | `[\w.+-]+@[\w.-]+\.[a-z]{2,}` (IGNORECASE)                       | D-09            |
| 2   | jwt          | `eyJ[\w-]+\.[\w-]+\.[\w-]+`                                      | D-09            |
| 3   | github_token | `(?:gh[psuor]_[A-Za-z0-9]{36,}\|github_pat_[A-Za-z0-9_]{82,})`   | D-09            |
| 4   | aws_key      | `(?:AKIA\|ASIA)[A-Z0-9]{16}`                                     | D-09            |
| 5   | slack        | `xox[bpoa]-\d{10,}-\d{10,}-[A-Za-z0-9]{24,}`                     | D-11            |
| 6   | stripe       | `sk_(?:live\|test)_[A-Za-z0-9]{24,}`                             | D-11            |
| 7   | anthropic    | `sk-ant-[A-Za-z0-9_-]{40,}`                                      | D-11            |
| 8   | openai       | `sk-(?!ant-)[A-Za-z0-9]{40,}` (neg-lookahead excludes Anthropic) | D-11            |
| 9   | bearer       | `Bearer\s+[A-Za-z0-9_.\-=]+`                                     | D-09            |
| 10  | basic_auth   | `Basic\s+[A-Za-z0-9+/=]+`                                        | D-09            |
| 11  | ipv4         | `\b(?:\d{1,3}\.){3}\d{1,3}\b`                                    | D-09            |
| 12  | ipv6         | multi-alternation regex (see below)                              | D-09 (extended) |
| 13  | phone        | `\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}`                            | D-09            |

**UNCERTAIN_PATTERN:** `\b[A-Za-z0-9+/=_-]{32,}\b` — runs after all named patterns; matches any bare high-entropy run not previously redacted (D-06 / D-11).

**IPv6 regex extension (Rule 1 deviation — see below):** The original D-09 example `\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{0,4}\b` does NOT match compressed forms like `2001:db8::1` or `::1`. Replaced with an alternation that covers full 8-group form, `x::y` with groups on both sides, trailing `x:y::`, leading `::x`, and bare `::`. All D-10 skip-list fixtures (`::1`, `fe80::1`, `fe80::abcd:1234`) now match and then get preserved unchanged by `_is_private_ip()`.

**`_is_private_ip(s)` skip-list (D-10, verbatim):**

- IPv4: `127.0.0.1`, `10.*`, `192.168.*`, `169.254.*`, `172.(16-31).*`
- IPv6: `::1`, anything starting with `fe80` (case-insensitive)

**`scrub_content(body)` function:**

- Returns `(text, stats)` tuple (D-23).
- `stats` has stable shape: 13 named keys + `"uncertain"` + `"total_chars_redacted"` — all always present, zero when absent (D-21).
- Replacement format: `<REDACTED:pattern_name>` (D-12).
- Pure — no I/O, no globals mutated, no match substrings leak into stats (T-03-01-01 mitigation).

### `tests/test_scrub.py` (new, 271 lines, 23 tests across 5 classes)

| Class                  | Tests | Coverage                                                                                                       |
| ---------------------- | ----- | -------------------------------------------------------------------------------------------------------------- |
| TestScrubNamedPatterns | 10    | One test per named pattern family; ordering rules (jwt-before-uncertain, anthropic-before-openai)              |
| TestScrubIPs           | 6     | Public IPv4/IPv6 redacted; private IPv4/IPv6 preserved; 172.15/172.32 boundary; `_is_private_ip()` direct unit |
| TestScrubUncertain     | 3     | Bare 32+ char → uncertain; short strings → no uncertain; known-pattern hits do NOT also set uncertain          |
| TestScrubStatsShape    | 3     | Empty input → full-shape zero-stats dict; `total_chars_redacted` uses original length; multi-hit accumulation  |
| TestScrubAllTogether   | 1     | Cumulative fixture asserts every named pattern hit >= 1 on one body                                            |

All 23 pass via `python3 -m unittest tests.test_scrub -v`.

Full suite: **121 tests pass** (98 prior + 23 new) via `python3 -m unittest discover tests` — zero regression.

### Line-count delta

- `sync_chats.py`: 985 → 1174 (+189 net, of which 174 are the initial insertion and ~15 are from the IPv6 regex fix)
- `tests/test_scrub.py`: 0 → 271 (new file)

### Integration status

`scrub_content` is **NOT** yet called from `_get_markdown_body` — that wiring is explicitly Plan 03-02's scope (per the plan's Step 3 "DO NOT call scrub_content..."). This plan delivers only the pure-function foundation. Downstream Plan 03-02 can `from sync_chats import scrub_content` with no further changes to this module.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] IPv6 regex did not match compressed `::` forms**

- **Found during:** Task 2 (tests/test_scrub.py fails on first run)
- **Issue:** The IPv6 regex from D-09 (`\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{0,4}\b`) requires at least two `xxxx:` groups but does not accept the compressed `::` form, so `2001:db8::1`, `::1`, and `fe80::1` all failed to match. The skip-list logic would have been bypassed entirely because the regex never fired — defeating the purpose of D-10.
- **Fix:** Expanded the IPv6 pattern to a 5-way alternation covering (a) full 8-group form, (b) `x::y` with groups on both sides, (c) trailing `x:y::`, (d) leading `::x`, (e) bare `::`.
- **Files modified:** `sync_chats.py` (ipv6 entry in `SCRUB_PATTERNS`)
- **Commit:** `1b5d21f` (folded into the Task 2 test commit since the fix is what makes the tests pass)
- **Sanity check:** All 6 IPv6 test cases now behave correctly — `2001:db8::1` → `<REDACTED:ipv6>`; `::1`, `fe80::1`, `fe80::abcd:1234` → preserved unchanged via skip-list.

### Auth gates

None.

## Commits

| Hash      | Subject                                                                      |
| --------- | ---------------------------------------------------------------------------- |
| `860ca54` | feat(03-01): add scrub_content pure function with PII patterns               |
| `1b5d21f` | test(03-01): add test_scrub.py covering all patterns + skip-list + uncertain |

## Known Stubs

None — `scrub_content` is a complete pure function. The deferred integration into `_get_markdown_body` is called out in both the plan (Step 3) and this summary as Plan 03-02's scope, not a stub.

## Self-Check: PASSED

- FOUND: `sync_chats.py` modified (`def scrub_content` present, 13 patterns compile, `_is_private_ip` works)
- FOUND: `tests/test_scrub.py` created (23 tests across 5 classes)
- FOUND: commit `860ca54` in git log
- FOUND: commit `1b5d21f` in git log
- VERIFIED: `python3 -m unittest tests.test_scrub` exits 0
- VERIFIED: `python3 -m unittest discover tests` exits 0 (121 tests, zero regression)
- VERIFIED: `len(SCRUB_PATTERNS) == 13`
- VERIFIED: stats dict has 15 keys (13 named + uncertain + total_chars_redacted)
- VERIFIED: No `import pytest`, `import detect_secrets`, `import yaml`, etc. (zero-deps invariant)
