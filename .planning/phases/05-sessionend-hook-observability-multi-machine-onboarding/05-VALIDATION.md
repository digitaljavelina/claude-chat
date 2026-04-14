---
phase: 5
slug: sessionend-hook-observability-multi-machine-onboarding
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-14
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

_Populated by the planner during PLAN.md creation. Each executable task must land a row here with an automated command or a Wave 0 dependency._

| Task ID | Plan | Wave | Requirement                 | Threat Ref | Secure Behavior | Test Type        | Automated Command                       | File Exists | Status     |
| ------- | ---- | ---- | --------------------------- | ---------- | --------------- | ---------------- | --------------------------------------- | ----------- | ---------- |
| 5-01-01 | 01   | TBD  | HOOK-01..05 / OBSERV-01..04 | —          | {expected}      | unit/integration | `pipx run pytest tests/test_phase5_...` | ⬜ W0       | ⬜ pending |

_Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky_

---

## Wave 0 Requirements

- [ ] `tests/test_phase5_once.py` — stubs for HOOK-01..05 (cmd_once behavior, stub writes, exit codes)
- [ ] `tests/test_phase5_last_run.py` — stubs for OBSERV-03 (last_run.json schema + atomic writer)
- [ ] `tests/test_phase5_summary.py` — stubs for OBSERV-01 (\_format_summary golden string)
- [ ] `tests/test_phase5_status.py` — stubs for OBSERV-04 (status reads last_run.json with fallback)
- [ ] `tests/fixtures/` — shared SessionEnd fixtures if needed (may extend existing conftest)

_Existing infrastructure: pytest via pipx already configured; 159 tests passing at Phase 4 completion._

---

## Manual-Only Verifications

| Behavior                                  | Requirement      | Why Manual                                                           | Test Instructions                                                                                                                              |
| ----------------------------------------- | ---------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| SessionEnd hook fires on real session end | HOOK-01, HOOK-02 | Requires ending a real Claude Code session — cannot fire from pytest | End a Claude session; within 2s verify new file in `<vault>/Chats/`; verify `last_run.json` updated; verify `sync.log` has timestamped entries |
| Multi-machine onboarding in < 10 min      | HOOK-05          | Requires a second physical Mac + iCloud vault sync                   | Follow `README.md` on second Mac from clean state; time install → first successful sync; must be < 10 min                                      |
| `sync.log` tailable during a run          | OBSERV-02        | Human-observable streaming behavior                                  | `tail -f ~/.claude-chat/sync.log` while triggering a session end; verify timestamped lines appear live                                         |
| `status` human-formatted output           | OBSERV-04        | Visual formatting judgment                                           | Run `python3 sync_chats.py status`; verify legible summary matches last_run.json fields                                                        |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
