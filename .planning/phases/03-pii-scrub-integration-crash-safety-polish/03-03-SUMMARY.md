---
phase: 03-pii-scrub-integration-crash-safety-polish
plan: 03
subsystem: crash-safety / reconcile
tags: [bugfix, crash-safety, reconcile, SC5, D-18, D-19, D-20]
requires: [03-01, 03-02]
provides:
  - three-way _reconcile_crash return (reconciled | edited | collision)
  - cmd_write edited branch (refuse + record + log + exit 0)
  - _read_frontmatter_field(path, key) generalized frontmatter reader
affects:
  - sync_chats.py (_read_auto_label_hash now thin wrapper; _reconcile_crash extended; cmd_write dispatcher extended)
tech-stack:
  added: []
  patterns:
    - "Three-way enum return from a classifier; dispatcher handles all branches"
    - "Thin-wrapper API preservation for backward compat (D-20)"
key-files:
  created:
    - tests/test_reconcile_edited.py (9 tests, 3 classes, ~215 lines after formatter)
  modified:
    - sync_chats.py (_read_frontmatter_field added; _read_auto_label_hash rewired; _reconcile_crash extended; cmd_write "edited" branch added)
decisions:
  - "D-18 implemented as three-way enum (reconciled | edited | collision); unknown-return defaults to collision in cmd_write else-branch"
  - "D-19 log line verbatim: 'skipped: user_edited (auto_label_hash mismatch, session_id matches) session=<8> file=<name>'"
  - "D-20 factored via _read_frontmatter_field(path, key); _read_auto_label_hash preserved as one-line wrapper"
metrics:
  duration: "~10 minutes"
  completed: 2026-04-13
  tasks: 2
  tests-added: 9
  tests-total: 149 (was 140)
---

# Phase 3 Plan 03: Manual-Edit Refusal + Crash-Reconcile Three-Way Summary

Closes ROADMAP SC#5 by fixing the latent Phase 1 defect at `sync_chats.py:858` where `_reconcile_crash`'s "collision" result was treated as a slug collision even when the existing vault file belonged to the SAME session but had been manually edited. The skill now refuses to touch user-edited files, records the session permanently, logs the refusal, and exits 0.

## Before / After `_reconcile_crash`

**Before (2-way):**

```
reconciled  (session_id unknown, only hash compared) | collision (hash mismatch)
```

**After (3-way, D-18):**

```
reconciled — existing_session_id == caller && hash matches  → update state, skip
edited     — existing_session_id == caller && hash differs  → caller refuses (D-19)
collision  — existing_session_id != caller (true slug clash) → caller runs -2/-3 loop

Legacy fallback: existing_session_id is None → hash comparison preserves Phase 1 behavior
  (match → reconciled, mismatch → collision).
```

## Exact `cmd_write` Dispatcher Change

Previously a two-branch `if/else`:

```python
if result == "reconciled":
    ...skip...
else:
    ...slug -2/-3 loop...
```

Now a three-branch dispatcher (safe-default else preserves unknown-return behavior):

```python
if result == "reconciled":
    ...skip, log "already_synced"...
elif result == "edited":
    # D-19: refuse permanently
    state["synced_session_ids"].append(args.session_id)
    state["fingerprints"][args.session_id] = fingerprint
    state["last_run_at"] = ...
    save_state(state)
    _log_sync("skipped: user_edited (auto_label_hash mismatch, session_id matches) session=<8> file=<name>")
    print(f"skipped: user_edited ({target.name})")
    return
else:
    ...slug -2/-3 loop (D-15 preserved)...
```

## D-19 Log Line (Verbatim)

```
[<iso-ts>] skipped: user_edited (auto_label_hash mismatch, session_id matches) session=11111111 file=mbp--2026-04-13--test.md
```

Greppable by canary tests and by the user from `sync.log`.

## Threat Mitigation (T-03-03-01 — T3 high)

> Broken reconcile overwrites user edits (creates `<slug>-2.md` with fresh auto-labels)

**Mitigated.** `tests/test_reconcile_edited.py::TestCmdWriteEditedBranch::test_edited_vault_file_refused_state_updated_exit_zero` asserts:

- `vf.read_bytes() == before_bytes` after the edited branch runs (vault unchanged)
- `save_state` is NOT called from inside `_reconcile_crash` on the edited path (cmd_write owns it)
- `sync.log` contains the D-19 exact substrings (`skipped: user_edited`, `auto_label_hash mismatch`, `session_id matches`, session_id[:8])
- State dict has the session in `synced_session_ids` and the fingerprint recorded

## Tests

9 new tests across 3 classes (all pass; full suite 149/149):

| Class                      | Test                                                             | Proves               |
| -------------------------- | ---------------------------------------------------------------- | -------------------- |
| TestReadFrontmatterField   | test_reads_session_id                                            | D-20 read session    |
| TestReadFrontmatterField   | test_reads_auto_label_hash                                       | D-20 read hash       |
| TestReadFrontmatterField   | test_returns_none_for_missing_key                                | D-20 missing key     |
| TestReadFrontmatterField   | test_backward_compat_wrapper                                     | D-20 API preserved   |
| TestReconcileCrashThreeWay | test_reconciled_when_session_and_hash_match                      | D-18 reconciled      |
| TestReconcileCrashThreeWay | test_edited_when_session_matches_but_hash_differs                | D-18 edited          |
| TestReconcileCrashThreeWay | test_collision_when_session_ids_differ                           | D-18 collision       |
| TestReconcileCrashThreeWay | test_collision_fallback_when_session_id_absent_and_hash_mismatch | D-18 legacy fallback |
| TestCmdWriteEditedBranch   | test_edited_vault_file_refused_state_updated_exit_zero           | D-19 E2E refusal     |

## Deviations from Plan

None — plan executed exactly as written.

## Commits

- `435d346` feat(03-03): three-way \_reconcile_crash + edited branch + frontmatter reader
- `eae471a` test(03-03): cover three-way \_reconcile_crash + cmd_write edited branch

## Next

Plan **03-04** will wire the full end-to-end canary validation (planting a JSONL, running write, grepping markdown for canary substrings) — confirming the edited-refusal path + PII scrub + ordering enforcement all hold under the realistic pipeline, not just unit tests.

## Self-Check: PASSED

- `sync_chats.py` — FOUND
- `tests/test_reconcile_edited.py` — FOUND
- Commit `435d346` — FOUND
- Commit `eae471a` — FOUND
- `grep -c 'return "edited"' sync_chats.py` = 1 (PASS)
- `grep -c 'result == "edited"' sync_chats.py` = 1 (PASS)
- `grep -c 'def _read_frontmatter_field' sync_chats.py` = 1 (PASS)
- `grep -c 'def _read_auto_label_hash' sync_chats.py` = 1 (PASS — backcompat wrapper preserved)
- `python3 -m unittest discover tests` exits 0, 149/149 tests pass (was 140 baseline)
