---
phase: 5
slug: sessionend-hook-observability-multi-machine-onboarding
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-14
updated: 2026-04-14
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property               | Value                                                                        |
| ---------------------- | ---------------------------------------------------------------------------- |
| **Framework**          | pytest (invoked via `pipx run pytest`, per memory `feedback_pytest_pipx.md`) |
| **Config file**        | `pyproject.toml` / `pytest.ini` (existing)                                   |
| **Quick run command**  | `pipx run pytest tests/test_phase5_*.py -x`                                  |
| **Full suite command** | `pipx run pytest`                                                            |
| **Estimated runtime**  | ~30 seconds (existing suite: 159 tests)                                      |

---

## Sampling Rate

- **After every task commit:** Run the task's focused test file (quick).
- **After every plan wave:** Run `pipx run pytest` (full suite).
- **Before `/gsd-verify-work`:** Full suite must be green + manual end-to-end hook check must pass.
- **Max feedback latency:** 30 seconds.

---

## Per-Task Verification Map

_Populated by the planner during PLAN.md creation. Each executable task lands a row with an `<automated>` verify command OR a Wave 0 dependency. Checkpoints (human-verify / human-action) are listed for traceability but do not require automated verify commands — their `status` is `manual`._

| Task ID | Plan | Wave | Requirement             | Threat Ref    | Secure Behavior                                                                                   | Test Type           | Automated Command                                                                                                                                                                                                                            | File Exists | Status     |
| ------- | ---- | ---- | ----------------------- | ------------- | ------------------------------------------------------------------------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ---------- |
| 5-01-01 | 01   | 1    | OBSERV-03               | T-05-01-01    | `_write_last_run` honors `CLAUDE_CHAT_HOME`; no writes to real `~/.claude-chat/` from tests       | unit (RED)          | `pipx run pytest tests/test_phase5_last_run.py -x 2>&1 \| grep -E "(AttributeError\|ImportError\|FAILED)"`                                                                                                                                   | ⬜ W0       | ⬜ pending |
| 5-01-02 | 01   | 1    | OBSERV-03               | T-05-01-01    | Atomic tmp+fsync+rename with `.bak` preservation (same guarantee as state.json)                   | unit (GREEN)        | `pipx run pytest tests/test_phase5_last_run.py -x -v`                                                                                                                                                                                        | ✅          | ⬜ pending |
| 5-01-03 | 01   | 1    | OBSERV-03 / refactor    | T-05-01-02    | Contract for `_write_session` — stub-sentinel override path asserted before implementation        | unit (RED)          | `pipx run pytest tests/test_phase5_write_session.py -x 2>&1 \| grep -E "(AttributeError\|FAILED)"`                                                                                                                                           | ⬜ W0       | ⬜ pending |
| 5-01-04 | 01   | 1    | OBSERV-03 / refactor    | T-05-01-02    | Zero regressions — all 159 existing tests stay green after extraction                             | unit + regression   | `pipx run pytest tests/ -x -q`                                                                                                                                                                                                               | ✅          | ⬜ pending |
| 5-02-01 | 02   | 2    | HOOK-01..04 / OBSERV-02 | T-05-02-01    | cmd_once never reads stdin (never hangs); errors[] capped at 10; stub sentinel on every write     | unit (RED)          | `pipx run pytest tests/test_phase5_once.py -x 2>&1 \| grep -E "(AttributeError\|FAILED)"`                                                                                                                                                    | ⬜ W0       | ⬜ pending |
| 5-02-02 | 02   | 2    | HOOK-01..04 / OBSERV-02 | T-05-02-01,05 | Pre-dispatch --once branch wins over `subcommand is None` guard; stderr ≤ 1 line on failure       | unit + integration  | `pipx run pytest tests/test_phase5_once.py tests/ -x -q`                                                                                                                                                                                     | ✅          | ⬜ pending |
| 5-03-01 | 03   | 2    | OBSERV-01               | T-05-03-02    | Golden string for D-23 format; pure function (no I/O)                                             | unit (RED)          | `pipx run pytest tests/test_phase5_summary.py -x 2>&1 \| grep -E "(AttributeError\|ImportError\|FAILED)"`                                                                                                                                    | ⬜ W0       | ⬜ pending |
| 5-03-02 | 03   | 2    | OBSERV-01               | T-05-03-02    | `_format_summary` is sole producer; cmd_once converges to it                                      | unit (GREEN)        | `pipx run pytest tests/test_phase5_summary.py tests/test_phase5_once.py -x -q`                                                                                                                                                               | ✅          | ⬜ pending |
| 5-03-03 | 03   | 2    | OBSERV-04               | T-05-03-01    | cmd_status fallback on empty/malformed last_run.json (no crash)                                   | integration (RED)   | `pipx run pytest tests/test_phase5_status.py -x 2>&1 \| grep -E "FAILED"`                                                                                                                                                                    | ⬜ W0       | ⬜ pending |
| 5-03-04 | 03   | 2    | OBSERV-04               | T-05-03-01    | cmd_status reads last_run.json first; falls back to state.last_run_at (D-17); pending preserved   | integration (GREEN) | `pipx run pytest tests/ -x -q`                                                                                                                                                                                                               | ✅          | ⬜ pending |
| 5-04-01 | 04   | 3    | HOOK-04 (D-04/D-05)     | T-05-04-05    | Stub-sentinel-only guard; refuses AI-labeled files; body bytes untouched                          | unit (RED)          | `pipx run pytest tests/test_phase5_relabel.py -x 2>&1 \| grep -E "(AttributeError\|FAILED)"`                                                                                                                                                 | ⬜ W0       | ⬜ pending |
| 5-04-02 | 04   | 3    | HOOK-04 (D-04/D-05)     | T-05-04-01,05 | Frontmatter-only rewrite; `auto_label_hash` flips stub → real SHA-256; needs_review → false       | unit (GREEN)        | `pipx run pytest tests/ -x -q`                                                                                                                                                                                                               | ✅          | ⬜ pending |
| 5-04-03 | 04   | 3    | HOOK-04 (SKILL.md)      | —             | User pastes Step 3a into per-user SKILL.md (checkpoint — file not in repo)                        | manual              | N/A — `checkpoint:human-action` (SKILL.md is per-user per memory `reference_skill_md_tests_ci.md`)                                                                                                                                           | N/A         | ⬜ manual  |
| 5-05-01 | 05   | 4    | HOOK-05                 | T-05-05-01,03 | README has all 10 D-26 sections; backup warning; append-not-overwrite instruction; Tailscale note | structural (grep)   | `test -f README.md && grep -q "python3 ~/.claude-chat/sync_chats.py --once" README.md && grep -q "SessionEnd" README.md && grep -q "auto_label_hash: stub" README.md && grep -q "mempalace_mined" README.md && grep -ci "back up" README.md` | ⬜          | ⬜ pending |
| 5-05-02 | 05   | 4    | HOOK-05                 | —             | User reads end-to-end; Section 6 commands work on primary Mac (checkpoint)                        | manual              | N/A — `checkpoint:human-verify`                                                                                                                                                                                                              | N/A         | ⬜ manual  |

_Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · ⬜ manual (checkpoint)_

**Automated-task coverage check:** 5-01-01, 5-01-02, 5-01-03, 5-01-04, 5-02-01, 5-02-02, 5-03-01, 5-03-02, 5-03-03, 5-03-04, 5-04-01, 5-04-02, 5-05-01 all have `<automated>` verify commands. The two manual checkpoints (5-04-03 SKILL.md paste, 5-05-02 README read-through) are inherent — they touch files outside the repo or require human judgment. No 3 consecutive executable tasks lack automated verify.

---

## Wave 0 Requirements

Test files these Wave-0 stubs must exist before the corresponding RED tasks commit:

- [ ] `tests/test_phase5_last_run.py` — OBSERV-03 `_write_last_run` schema + atomic writer (created by task 5-01-01)
- [ ] `tests/test_phase5_write_session.py` — internal `_write_session` contract (created by task 5-01-03)
- [ ] `tests/test_phase5_once.py` — HOOK-01..04 + OBSERV-02/03 `cmd_once` orchestration (created by task 5-02-01)
- [ ] `tests/test_phase5_summary.py` — OBSERV-01 `_format_summary` golden string (created by task 5-03-01)
- [ ] `tests/test_phase5_status.py` — OBSERV-04 `cmd_status` last_run path + fallback (created by task 5-03-03)
- [ ] `tests/test_phase5_relabel.py` — HOOK-04 / D-04 / D-05 sentinel-only re-label (created by task 5-04-01)

_Existing infrastructure: pytest via pipx already configured; 159 tests passing at Phase 4 completion. All Phase 5 test files will use the established env-override harness pattern (CLAUDE_CHAT_HOME + CLAUDE_PROJECTS_DIR + importlib.reload) from `tests/test_mine.py`._

Note on "Wave 0": Phase 5's RED-task pattern is itself the Wave-0-equivalent — each RED task creates the test file and commits it failing before the GREEN task implements. No separate scaffolding wave is needed because Plan 01's tests land before any code is extracted.

---

## Manual-Only Verifications

| Behavior                                  | Requirement      | Why Manual                                                            | Test Instructions                                                                                                                              |
| ----------------------------------------- | ---------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| SessionEnd hook fires on real session end | HOOK-01, HOOK-02 | Requires ending a real Claude Code session — cannot fire from pytest  | End a Claude session; within 2s verify new file in `<vault>/Chats/`; verify `last_run.json` updated; verify `sync.log` has timestamped entries |
| Multi-machine onboarding in < 10 min      | HOOK-05          | Requires a second physical Mac + iCloud vault sync                    | Follow `README.md` on second Mac from clean state; time install → first successful sync; must be < 10 min                                      |
| `sync.log` tailable during a run          | OBSERV-02        | Human-observable streaming behavior                                   | `tail -f ~/.claude-chat/sync.log` while triggering a session end; verify timestamped lines appear live                                         |
| `status` human-formatted output           | OBSERV-04        | Visual formatting judgment                                            | Run `python3 sync_chats.py status`; verify legible summary matches last_run.json fields                                                        |
| SKILL.md Step 3a re-label loop            | HOOK-04 / D-04   | SKILL.md is per-user (not in repo); Claude invocation can't be mocked | After pasting Step 3a, run `/sync-chats` against a vault that contains ≥1 stub file; verify stub file's `auto_label_hash` flips to 64-char hex |
| README end-to-end clarity                 | HOOK-05          | Document-quality judgment                                             | Read README.md top to bottom; paste-test Section 6 commands against primary Mac; confirm no section is confusing or incorrect                  |

---

## Validation Sign-Off

- [x] All executable tasks have `<automated>` verify commands
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 stubs covered by RED tasks at start of each plan (TDD pattern)
- [x] No watch-mode flags
- [x] Feedback latency < 30s (full suite runtime ~30s, focused phase5 tests < 5s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready for execution
