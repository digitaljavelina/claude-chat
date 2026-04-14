---
phase: 4
slug: mempalace-bulk-mine-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-14
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property               | Value                                       |
| ---------------------- | ------------------------------------------- |
| **Framework**          | `unittest` (stdlib) — pytest-compatible     |
| **Config file**        | none — `python3 -m unittest discover tests` |
| **Quick run command**  | `pipx run pytest tests/test_mine.py -v`     |
| **Full suite command** | `python3 -m unittest discover tests -v`     |
| **Estimated runtime**  | ~5 seconds (quick); ~15 seconds (full)      |

---

## Sampling Rate

- **After every task commit:** Run `pipx run pytest tests/test_mine.py -v`
- **After every plan wave:** Run `python3 -m unittest discover tests -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref                    | Secure Behavior                                                          | Test Type | Automated Command                                                                             | File Exists | Status     |
| ------- | ---- | ---- | ----------- | ----------------------------- | ------------------------------------------------------------------------ | --------- | --------------------------------------------------------------------------------------------- | ----------- | ---------- |
| 4-01-01 | 01   | 0    | MEM-01      | —                             | N/A (test stubs)                                                         | unit      | `pipx run pytest tests/test_mine.py -v`                                                       | ❌ W0       | ⬜ pending |
| 4-01-02 | 01   | 1    | MEM-01      | T-4-01 (list-form subprocess) | Pass argv as list, never `shell=True`                                    | unit      | `pipx run pytest tests/test_mine.py::TestCmdMine::test_runs_correct_command -x`               | ❌ W0       | ⬜ pending |
| 4-01-03 | 01   | 1    | MEM-01      | —                             | Vault path read from config (no hardcoded path)                          | unit      | `pipx run pytest tests/test_mine.py::TestCmdMine::test_vault_path_from_config -x`             | ❌ W0       | ⬜ pending |
| 4-02-01 | 02   | 2    | MEM-02      | T-4-02 (graceful missing bin) | `shutil.which` miss → exit 0 + `skipped` log                             | unit      | `pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg::test_binary_absent_skipped -x`   | ❌ W0       | ⬜ pending |
| 4-02-02 | 02   | 2    | MEM-02      | T-4-03 (non-zero exit)        | Non-zero exit → exit 0, log stderr tail (max 20 lines)                   | unit      | `pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg::test_nonzero_exit_false -x`      | ❌ W0       | ⬜ pending |
| 4-02-03 | 02   | 2    | MEM-02      | T-4-04 (DoS via hang)         | 300s timeout enforced; TimeoutExpired → exit 0, logged                   | unit      | `pipx run pytest tests/test_mine.py::TestCmdMineGracefulDeg::test_timeout_false -x`           | ❌ W0       | ⬜ pending |
| 4-03-01 | 03   | 3    | MEM-03      | —                             | Stdout prints `mempalace_mined: true` on success                         | unit      | `pipx run pytest tests/test_mine.py::TestCmdMineSummary::test_true_on_success -x`             | ❌ W0       | ⬜ pending |
| 4-03-02 | 03   | 3    | MEM-03      | —                             | Stdout prints `mempalace_mined: skipped (command not found)`             | unit      | `pipx run pytest tests/test_mine.py::TestCmdMineSummary::test_skipped_with_reason -x`         | ❌ W0       | ⬜ pending |
| 4-03-03 | 03   | 3    | MEM-03      | —                             | SKILL.md Step 4 calls `mine` after writes and appends outcome to summary | SKILL     | `pipx run pytest tests/test_mine.py::TestSkillMineStep -v` (skipped if no SKILL.md installed) | ❌ W0       | ⬜ pending |

_Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky_

---

## Wave 0 Requirements

- [ ] `tests/test_mine.py` — stubs for `TestCmdMine`, `TestCmdMineGracefulDeg`, `TestCmdMineSummary`, `TestSkillMineStep` (MEM-01, MEM-02, MEM-03)
- [ ] Reuse `tests/conftest.py` (no new fixtures expected; tmp_path + monkeypatch cover subprocess mocking)
- [ ] No framework install needed — unittest is stdlib; pytest via `pipx run pytest` per project convention

---

## Manual-Only Verifications

| Behavior                                                           | Requirement | Why Manual                                                              | Test Instructions                                                                                                                                                                                                                                                                               |
| ------------------------------------------------------------------ | ----------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| End-to-end: real `mempalace` binary ingests a freshly-synced vault | MEM-01      | Requires installed `mempalace` CLI + live vault; not reproducible in CI | 1) Run `python3 claude-chat.py sync` with ≥1 new chat. 2) Confirm stdout line `mempalace_mined: true`. 3) Confirm `mempalace search <snippet>` returns the synced chat.                                                                                                                         |
| Second-Mac graceful degrade                                        | MEM-02      | Requires a host where `mempalace` is NOT on PATH                        | 1) On Mac without `mempalace` installed, run `python3 claude-chat.py sync`. 2) Confirm exit code 0. 3) Confirm `sync.log` contains `mempalace: command not found — skipping mine`. 4) Confirm stdout `mempalace_mined: skipped (command not found)`. 5) Confirm vault files were still written. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`tests/test_mine.py`)
- [ ] No watch-mode flags (all commands single-run)
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
