---
phase: 05
phase_name: sessionend-hook-observability-multi-machine-onboarding
audit_date: 2026-04-15
auditor: gsd-security-auditor (claude-sonnet-4-6)
asvs_level: default
threats_registered: 23
threats_closed: 23
threats_open: 0
---

# SECURITY.md

## Phase 5 — sessionend-hook-observability-multi-machine-onboarding

**Audit date:** 2026-04-15
**Auditor:** gsd-security-auditor (claude-sonnet-4-6)
**ASVS Level:** default (single-user local tool)
**Threats registered:** 23 | **Closed:** 23 | **Open:** 0

---

## Threat Verification

### Plan 05-01 — hook command extraction

| Threat ID  | Category               | Disposition | Status | Evidence                                                                                                                                          |
| ---------- | ---------------------- | ----------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-05-01-01 | Tampering              | mitigate    | CLOSED | `LAST_RUN_PATH = CLAUDE_CHAT_HOME / "last_run.json"` at sync_chats.py:44; `test_honors_claude_chat_home_env` at tests/test_phase5_last_run.py:148 |
| T-05-01-02 | Tampering              | mitigate    | CLOSED | `_write_session` extracted; full suite runs in verify block; SUMMARY.md confirms 169 tests passing post-refactor                                  |
| T-05-01-03 | Information disclosure | accept      | CLOSED | Single-user local tool; `~/.claude-chat/` not iCloud-synced (CORE-04); file is mode 0644. Accepted per plan rationale.                            |
| T-05-01-04 | Denial of service      | accept      | CLOSED | Only one `.bak` written per run (overwritten); no chain growth. Matches `_write_atomic` precedent. Accepted per plan rationale.                   |

### Plan 05-02 — --once command

| Threat ID  | Category               | Disposition | Status | Evidence                                                                                                                                                                                                                                                                                                                                                                                                 |
| ---------- | ---------------------- | ----------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-05-02-01 | Tampering              | mitigate    | CLOSED | `cmd_once` contains no `sys.stdin.read()` call (sync_chats.py:1478–1582); `test_does_not_block_on_stdin` at tests/test_phase5_once.py:279                                                                                                                                                                                                                                                                |
| T-05-02-02 | Information disclosure | mitigate    | CLOSED | Code writes one short line to stderr on failure (sync_chats.py:1577–1580); `test_one_session_fails` at tests/test_phase5_once.py:193 now patches `sys.stderr` with `io.StringIO` and asserts `len(captured_stderr) <= 200` plus `assertNotIn("Traceback", captured_stderr)` — provides regression net against future `traceback.print_exc()` additions. Closed via audit fix in response to initial gap. |
| T-05-02-03 | Injection              | mitigate    | CLOSED | `_log_sync` calls in `cmd_once` log only `run-start trigger=once machine=...` and `run-finish trigger=once {summary}` (sync_chats.py:1506, 1572); no session titles are logged. Verified by code inspection.                                                                                                                                                                                             |
| T-05-02-04 | Denial of service      | mitigate    | CLOSED | `if len(errors) < 10:` cap at sync_chats.py:1536; `test_errors_capped_at_10` at tests/test_phase5_once.py:217 asserts `len(lr["errors"]) == 10` with 15 failures                                                                                                                                                                                                                                         |
| T-05-02-05 | Elevation of privilege | mitigate    | CLOSED | Pre-dispatch branch before subcommand routing (sync_chats.py: `if args.once:` before subcommand-None guard); `test_once_flag_wins_over_no_subcommand` at tests/test_phase5_once.py:244                                                                                                                                                                                                                   |
| T-05-02-06 | Repudiation            | mitigate    | CLOSED | `_log_sync("run-start trigger=once ...")` + `_log_sync("run-finish trigger=once ...")` at sync_chats.py:1506, 1572; `test_run_start_and_finish_logged` at tests/test_phase5_once.py:259                                                                                                                                                                                                                  |

### Plan 05-03 — status summary

| Threat ID  | Category               | Disposition | Status | Evidence                                                                                                                                                                                 |
| ---------- | ---------------------- | ----------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-05-03-01 | Tampering              | mitigate    | CLOSED | `_load_json(LAST_RUN_PATH)` returns `{}` on malformed; truthy check at sync_chats.py:1359 falls back safely; `test_falls_back_on_empty_last_run_json` at tests/test_phase5_status.py:121 |
| T-05-03-02 | Information disclosure | mitigate    | CLOSED | `def _format_summary(run: dict)` at sync_chats.py:1443 is sole producer; 6 golden-string assertEqual tests in tests/test_phase5_summary.py                                               |
| T-05-03-03 | Denial of service      | accept      | CLOSED | File capped by D-13 (errors[] <= 10); practical size < 2 KB. Accepted per plan rationale.                                                                                                |

### Plan 05-04 — relabel

| Threat ID  | Category               | Disposition | Status | Evidence                                                                                                                                                                  |
| ---------- | ---------------------- | ----------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-05-04-01 | Tampering              | mitigate    | CLOSED | Body bytes read as raw bytes then written back unchanged (sync_chats.py:1717, 1738–1743); `test_body_is_untouched` in tests/test_phase5_relabel.py                        |
| T-05-04-02 | Tampering              | accept      | CLOSED | Single-user tool; user has full access to their own files. Accepted per plan rationale.                                                                                   |
| T-05-04-03 | Spoofing               | mitigate    | CLOSED | First-match-wins with stderr warning if >1 candidate (sync_chats.py:1699–1705: `if len(candidates) > 1: print(...warning..., file=sys.stderr)`); documented in SUMMARY.md |
| T-05-04-04 | Information disclosure | accept      | CLOSED | Single-user local tool, local stderr. Accepted per plan rationale.                                                                                                        |
| T-05-04-05 | Elevation of privilege | mitigate    | CLOSED | `if existing_hash != "stub": ... sys.exit(1)` at sync_chats.py:1709–1715; `test_refuses_when_hash_is_real_sha256` at tests/test_phase5_relabel.py:138                     |

### Plan 05-05 — README

| Threat ID  | Category               | Disposition | Status | Evidence                                                                                                                                                     |
| ---------- | ---------------------- | ----------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| T-05-05-01 | Tampering              | mitigate    | CLOSED | Section 5 opens with `cp ~/.claude/settings.json ~/.claude/settings.json.bak`; validation step `python3 -m json.tool < ~/.claude/settings.json` in Section 9 |
| T-05-05-02 | Information disclosure | accept      | CLOSED | Placeholder `<you>` / `you` used; no literal home path embedded. Accepted per plan rationale.                                                                |
| T-05-05-03 | Tampering              | mitigate    | CLOSED | Section 5 leads with append-to-array snippet and explicit "APPEND ... do NOT replace the whole key" warning                                                  |
| T-05-05-04 | Repudiation            | mitigate    | CLOSED | README is repo-versioned; Task 1 verify block uses `grep`-based checks against 9 required strings; SUMMARY.md confirms all 9 passed                          |
| T-05-05-05 | Elevation of privilege | mitigate    | CLOSED | Section 5 uses `python3 -m json.tool` and manual editor instructions; no `>` redirect destructive one-liners present in README                               |

---

## Accepted Risks Log

| Threat ID  | Rationale                                                                                     |
| ---------- | --------------------------------------------------------------------------------------------- |
| T-05-01-03 | Single-user local tool; `~/.claude-chat/` not synced to iCloud (CORE-04 asserted at startup). |
| T-05-01-04 | `.bak` is overwritten each run — no chain growth. Precedent set by `_write_atomic`.           |
| T-05-03-03 | `last_run.json` size is bounded by D-13 (errors[] <= 10); practical max ~2 KB.                |
| T-05-04-02 | Single-user local tool; user who wants to re-label their own file is not an adversary.        |
| T-05-04-04 | Single-user local tool; stderr is not a disclosure surface.                                   |
| T-05-05-02 | Placeholder `<you>` used; no real home path in README.                                        |

---

## Unregistered Flags

None. No `## Threat Flags` sections were present in the 05-01 through 05-05 SUMMARY files.

---

## Audit Trail

### Security Audit 2026-04-15

| Metric        | Count |
| ------------- | ----- |
| Threats found | 23    |
| Closed        | 23    |
| Open          | 0     |

**Initial audit:** 22 closed, 1 open (T-05-02-02 — code correct but named test assertion missing).

**Remediation:** Added `sys.stderr` patch with `io.StringIO` to `test_one_session_fails` (tests/test_phase5_once.py:204–210) asserting `len(captured_stderr) <= 200` and absence of "Traceback". Full suite: 199/199 passing.

**Final status:** threats_open: 0.
