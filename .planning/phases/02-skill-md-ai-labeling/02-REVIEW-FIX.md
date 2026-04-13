---
phase: 02-skill-md-ai-labeling
fixed_at: 2026-04-13T22:36:55Z
review_path: .planning/phases/02-skill-md-ai-labeling/02-REVIEW.md
iteration: 1
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-04-13T22:36:55Z
**Source review:** .planning/phases/02-skill-md-ai-labeling/02-REVIEW.md
**Iteration:** 1

**Summary:**

- Findings in scope: 3 (WR-01, WR-02, WR-03; Info findings excluded per fix_scope=critical_warning)
- Fixed: 3
- Skipped: 0

## Fixed Issues

### WR-01: Duplicate `_count_user_messages` in `TestFixtures` diverges from module-level function

**Files modified:** `tests/test_phase2_labels.py`
**Commit:** acc4f2c
**Applied fix:** Replaced the 35-line reimplementation of `TestFixtures._count_user_messages` with a one-line delegation to the module-level `count_user_messages()`. The private version lacked the `try/except (OSError, IOError)` guard present in the module-level function, meaning a missing fixture would raise an unhelpful traceback instead of a clean test failure. The delegation eliminates the divergence and picks up the error-handling for free.

---

### WR-02: `validate_gist` sentence counter undercounts when gist ends without `. `

**Files modified:** `tests/test_phase2_labels.py`
**Commit:** 916d04b
**Applied fix:** Replaced the `stripped.count(". ") + 1` heuristic in `validate_gist` with `len(re.findall(r"[.!?](?:\s|$)", stripped))` plus a fallback of 1 if no punctuation is found. The new regex matches sentence-ending punctuation (`.`, `!`, `?`) whether followed by a space or by end-of-string, so terminal sentences like `"Done."` are counted correctly. All existing passing tests continue to pass; a four-sentence gist now correctly returns False.

---

### WR-03: Stub label `gist=None` and `coherence_score=None` are structurally inconsistent with validators

**Files modified:** `tests/test_phase2_labels.py`
**Commit:** 2e8a551
**Applied fix:** Added `test_stub_gist_and_score_are_none` to `TestStubFallback`. The test asserts both fields are `None`, then confirms they return `False` from `validate_gist` and `validate_coherence_score`. This explicitly documents the intentional partial validity of stub labels (produced on AI labeling failure per D-08) so future maintainers understand the contract rather than assuming stubs are fully valid.

---

_Fixed: 2026-04-13T22:36:55Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
