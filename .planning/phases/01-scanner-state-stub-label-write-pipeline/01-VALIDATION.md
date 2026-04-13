---
phase: 01
slug: scanner-state-stub-label-write-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property               | Value                                                                  |
| ---------------------- | ---------------------------------------------------------------------- |
| **Framework**          | `python -m unittest` (stdlib, no install)                              |
| **Config file**        | None — runner uses `discover tests/` convention                        |
| **Quick run command**  | `python3 -m unittest discover tests -v`                                |
| **Full suite command** | `python3 -m unittest discover tests -v && bash tests/phase1_canary.sh` |
| **Estimated runtime**  | ~5 seconds                                                             |

---

## Sampling Rate

- **After every task commit:** Run `python3 -m unittest discover tests -v`
- **After every plan wave:** Run `python3 -m unittest discover tests -v && bash tests/phase1_canary.sh`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID  | Plan | Wave | Requirement | Threat Ref | Secure Behavior                         | Test Type   | Automated Command                                               | File Exists | Status     |
| -------- | ---- | ---- | ----------- | ---------- | --------------------------------------- | ----------- | --------------------------------------------------------------- | ----------- | ---------- |
| 01-01-01 | 01   | 0    | CORE-01     | —          | N/A                                     | unit        | `python3 -m unittest tests.test_sync_chats.TestScan`            | ❌ W0       | ⬜ pending |
| 01-01-02 | 01   | 0    | CORE-02     | —          | N/A                                     | integration | `bash tests/phase1_canary.sh` criterion 3                       | ❌ W0       | ⬜ pending |
| 01-01-03 | 01   | 0    | CORE-03     | —          | Atomic state write with .bak            | unit        | `python3 -m unittest tests.test_sync_chats.TestStateIO`         | ❌ W0       | ⬜ pending |
| 01-01-04 | 01   | 0    | CORE-04     | T-01-01    | Startup aborts on iCloud path           | unit        | `python3 -m unittest tests.test_sync_chats.TestICloudAssertion` | ❌ W0       | ⬜ pending |
| 01-01-05 | 01   | 0    | CORE-05     | —          | N/A                                     | integration | `bash tests/phase1_canary.sh` criterion 1                       | ❌ W0       | ⬜ pending |
| 01-01-06 | 01   | 0    | CORE-06     | —          | N/A                                     | unit        | `python3 -m unittest tests.test_sync_chats.TestSlug`            | ❌ W0       | ⬜ pending |
| 01-01-07 | 01   | 0    | CORE-07     | —          | Idempotent: zero new files on repeat    | integration | `bash tests/phase1_canary.sh` criterion 4                       | ❌ W0       | ⬜ pending |
| 01-01-08 | 01   | 0    | CORE-08     | —          | Session in synced_ids never re-exported | unit        | `python3 -m unittest tests.test_sync_chats.TestClobberLayer1`   | ❌ W0       | ⬜ pending |
| 01-01-09 | 01   | 0    | CORE-09     | —          | File-exists check refuses write         | unit        | `python3 -m unittest tests.test_sync_chats.TestClobberLayer2`   | ❌ W0       | ⬜ pending |
| 01-01-10 | 01   | 0    | CORE-10     | —          | N/A                                     | unit        | `python3 -m unittest tests.test_sync_chats.TestAutoLabelHash`   | ❌ W0       | ⬜ pending |
| 01-01-11 | 01   | 0    | CORE-11     | —          | N/A                                     | integration | `bash tests/phase1_canary.sh` criterion 7                       | ❌ W0       | ⬜ pending |
| 01-01-12 | 01   | 0    | CORE-12     | —          | Protect audit documented                | manual      | file exists + content check                                     | ❌ W0       | ⬜ pending |
| 01-01-13 | 01   | 0    | CORE-13     | —          | N/A                                     | integration | `bash tests/phase1_canary.sh` criterion 8                       | ❌ W0       | ⬜ pending |
| 01-01-14 | 01   | 0    | LABEL-09    | —          | Labels from stdin only                  | unit        | `python3 -m unittest tests.test_sync_chats.TestStdinContract`   | ❌ W0       | ⬜ pending |

_Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky_

---

## Wave 0 Requirements

- [ ] `tests/__init__.py` — package marker
- [ ] `tests/test_sync_chats.py` — unit tests for pure functions and clobber defenses
- [ ] `tests/phase1_canary.sh` — bash end-to-end script for all 9 success criteria
- [ ] `tests/fixtures/sample_session.jsonl` — minimal valid session for unit tests

_No framework install needed (`python -m unittest` is stdlib)._

---

## Manual-Only Verifications

| Behavior                 | Requirement | Why Manual                                   | Test Instructions                                                                       |
| ------------------------ | ----------- | -------------------------------------------- | --------------------------------------------------------------------------------------- |
| Protect audit documented | CORE-12     | Documentation artifact, not runtime behavior | Verify `01-PROTECT-AUDIT.md` exists in phase dir and documents `cmd_protect()` findings |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
