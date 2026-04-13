---
phase: 2
slug: skill-md-ai-labeling
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property               | Value                            |
| ---------------------- | -------------------------------- |
| **Framework**          | pytest (from Phase 1)            |
| **Config file**        | `tests/` directory               |
| **Quick run command**  | `python3 -m pytest tests/ -x -q` |
| **Full suite command** | `python3 -m pytest tests/ -v`    |
| **Estimated runtime**  | ~5 seconds                       |

---

## Sampling Rate

- **After every task commit:** Run `python3 -m pytest tests/ -x -q`
- **After every plan wave:** Run `python3 -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID  | Plan | Wave | Requirement | Threat Ref | Secure Behavior                          | Test Type   | Automated Command                       | File Exists | Status     |
| -------- | ---- | ---- | ----------- | ---------- | ---------------------------------------- | ----------- | --------------------------------------- | ----------- | ---------- |
| 02-01-01 | 01   | 1    | LABEL-01    | —          | N/A                                      | manual      | Verify SKILL.md frontmatter fields      | ❌ W0       | ⬜ pending |
| 02-01-02 | 01   | 1    | LABEL-09    | —          | N/A                                      | unit        | `python3 -m pytest tests/ -k label`     | ❌ W0       | ⬜ pending |
| 02-02-01 | 02   | 1    | LABEL-02    | —          | N/A                                      | integration | Manual `/sync-chats` invocation         | ❌ W0       | ⬜ pending |
| 02-02-02 | 02   | 1    | LABEL-03    | —          | N/A                                      | unit        | `python3 -m pytest tests/ -k title`     | ❌ W0       | ⬜ pending |
| 02-02-03 | 02   | 1    | LABEL-04    | —          | N/A                                      | unit        | `python3 -m pytest tests/ -k gist`      | ❌ W0       | ⬜ pending |
| 02-02-04 | 02   | 1    | LABEL-05    | —          | N/A                                      | unit        | `python3 -m pytest tests/ -k tags`      | ❌ W0       | ⬜ pending |
| 02-02-05 | 02   | 1    | LABEL-06    | —          | N/A                                      | unit        | `python3 -m pytest tests/ -k coherence` | ❌ W0       | ⬜ pending |
| 02-03-01 | 03   | 2    | LABEL-07    | —          | N/A                                      | unit        | `python3 -m pytest tests/ -k edge`      | ❌ W0       | ⬜ pending |
| 02-03-02 | 03   | 2    | LABEL-08    | T-02-01    | Shell injection prevented via json.dumps | unit        | `python3 -m pytest tests/ -k fallback`  | ❌ W0       | ⬜ pending |

_Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky_

---

## Wave 0 Requirements

- [ ] `tests/test_labeling.py` — stubs for LABEL-03 through LABEL-08 validation helpers
- [ ] Verify Phase 1 test suite still green before starting Phase 2

_Existing Phase 1 test infrastructure covers the pipeline; Phase 2 adds labeling-specific tests._

---

## Manual-Only Verifications

| Behavior                                   | Requirement                  | Why Manual                               | Test Instructions                                               |
| ------------------------------------------ | ---------------------------- | ---------------------------------------- | --------------------------------------------------------------- |
| `/sync-chats` skill loads in Claude Code   | LABEL-01                     | Requires interactive Claude Code session | Type `/sync-chats` in Claude Code and verify skill activates    |
| Claude generates quality titles/gists      | LABEL-02, LABEL-03, LABEL-04 | AI output quality is subjective          | Run skill on 3+ sessions, inspect vault files in Obsidian       |
| `disable-model-invocation: true` semantics | LABEL-01                     | Requires runtime verification            | Create skill with flag, invoke, confirm Claude can still reason |

_Most label format validations (length, kebab-case, YAML list) can be automated; content quality requires manual inspection._

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
