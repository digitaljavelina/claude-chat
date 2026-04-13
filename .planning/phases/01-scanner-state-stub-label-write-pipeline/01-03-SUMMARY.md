---
phase: 01-scanner-state-stub-label-write-pipeline
plan: "03"
subsystem: sync_chats
tags:
  [
    write-pipeline,
    cmd-write,
    cmd-status,
    clobber-defense,
    crash-reconciliation,
    frontmatter,
    subprocess-bridge,
    atomic-write,
  ]
dependency_graph:
  requires: [01-01, 01-02]
  provides:
    [
      cmd_write,
      cmd_status,
      _write_if_not_exists,
      _get_markdown_body,
      _reconcile_crash,
      _resolve_vault_filename,
      _log_sync,
      sync.log,
    ]
  affects: []
tech_stack:
  added: []
  patterns:
    [
      O_CREAT|O_EXCL atomic file create,
      sha256 body hash for crash reconciliation,
      subprocess bridge to claude-chat.py export --stdout,
      per-session atomic state update,
      collision suffix deferred past reconciliation,
    ]
key_files:
  created: []
  modified: [sync_chats.py]
decisions:
  - "Collision suffix (-2, -3) deferred to cmd_write after reconciliation — _resolve_vault_filename returns base name unconditionally so crash reconciliation can run first (Rule 1 fix)"
  - "auto_label_hash hashes only the markdown body (not frontmatter) — makes reconciliation simple: re-render body, hash, compare without frontmatter drift"
  - "5 _log_sync calls: definition + write-success (2 lines) + layer-1-skip + reconcile-skip — D-32 summary format on all paths"
metrics:
  duration_minutes: 30
  completed: "2026-04-13"
  tasks_completed: 2
  files_created: 0
  files_modified: 1
---

# Phase 1 Plan 03: Write Pipeline and Status Command Summary

Full `cmd_write` pipeline with three-layer clobber defense and crash reconciliation, plus `cmd_status` summary display — completing all Phase 1 CLI functionality in `sync_chats.py` (978 lines).

## Tasks Completed

| Task | Name                                                                   | Commit  | Key Files                |
| ---- | ---------------------------------------------------------------------- | ------- | ------------------------ |
| 1    | Implement cmd_write with full pipeline and three-layer clobber defense | ae33a02 | sync_chats.py (extended) |
| 2    | Implement cmd_status and summary line output                           | 100866d | sync_chats.py (extended) |

## What Was Built

**6 new helper functions** in sync_chats.py:

- `_write_if_not_exists(path, content_bytes) -> bool`: O_CREAT|O_EXCL atomic create — clobber defense layer 2. Returns False if file exists (EEXIST), raises on other errors.
- `_get_markdown_body(session_id) -> str`: subprocess bridge to `claude-chat.py export <uuid> --format md --stdout`. Raises `RuntimeError` with session context on CalledProcessError.
- `_read_auto_label_hash(vault_file) -> str | None`: reads `auto_label_hash:` from existing file's YAML frontmatter (first 30 lines), used by crash reconciliation.
- `_reconcile_crash(vault_file, body_bytes, session_id, state, fingerprint) -> str`: compares sha256(body_bytes) to stored `auto_label_hash`. Returns "reconciled" (crash recovery — update state) or "collision" (different session or user-edited — try suffix).
- `_log_sync(message)`: appends ISO-timestamped lines to `~/.claude-chat/sync.log` (D-33).
- `_resolve_vault_filename(config, label, session_date, session_id) -> Path`: builds `<machine>--YYYY-MM-DD--<slug>.md` base path in vault `Chats/`. Does NOT apply collision suffix (see Deviations).

**`cmd_write(args)`** — full D-24 pipeline:

1. `_require_config()` + `load_state()`
2. `sys.stdin.read()` + `json.loads()` — label JSON from stdin only (D-01/D-03)
3. Clobber layer 1: check `synced_session_ids` → print `skipped: already_synced` and return
4. Walk PROJECTS_DIR for JSONL file matching session_id at depth=2
5. `_get_session_date()`, `_get_markdown_body()`, `_extract_session_metadata()`
6. `sha256(body_bytes)` → `auto_label_hash` → `emit_frontmatter()` → `final_bytes`
7. `_resolve_vault_filename()` → base target path
8. Clobber layer 2: `_write_if_not_exists(target, final_bytes)`
9. If not written: `_reconcile_crash()` → "reconciled" (skip) or "collision" (try -2...-99)
10. If written: `save_state()` per-session (D-26) + `_log_sync()` + print `Wrote: {target}`

**`cmd_status(args)`** — CORE-13:
Displays machine label, hostname, vault path, last run timestamp, synced count, pending count via `discover_sessions()`.

## Verification Results

| Check                                                                                                | Result |
| ---------------------------------------------------------------------------------------------------- | ------ |
| First write creates vault file with correct name                                                     | PASS   |
| Second write prints `skipped: already_synced` (layer 1)                                              | PASS   |
| Delete state.json, re-run → `skipped: already_synced (recovered from interrupted write)` (reconcile) | PASS   |
| Only 1 file in Chats/ after crash recovery (no spurious -2 file)                                     | PASS   |
| Frontmatter has all 14 fields with auto_label_hash                                                   | PASS   |
| `sync_chats.py status` shows Machine/Hostname/Vault/Last run/Synced/Pending                          | PASS   |
| sync.log contains timestamped entries                                                                | PASS   |
| Python syntax check (`python3 -m py_compile`)                                                        | PASS   |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Collision suffix bypassed crash reconciliation**

- **Found during:** Task 1 end-to-end testing
- **Issue:** `_resolve_vault_filename` applied `-2`/`-3` collision suffix before `_write_if_not_exists` was called. When `state.json` was deleted (crash simulation) and `write` was re-attempted, the function detected the existing base-name file and returned a `-2` path, bypassing `_reconcile_crash` entirely. The session was written again as a new file instead of being reconciled.
- **Fix:** `_resolve_vault_filename` now returns the base name unconditionally (no collision suffix). `cmd_write` calls `_reconcile_crash` on EEXIST, and only applies `-2`/`-3` suffixes if reconciliation returns "collision" (different session). This preserves D-25 semantics correctly.
- **Files modified:** `sync_chats.py`
- **Commit:** `6e7c0b3`

## Known Stubs

- `make_stub_label`: produces `gist: null`, `coherence_score: null` — Phase 2 AI labeler populates these
- `needs_review: true` on all Phase 1 writes — Phase 2 will set this based on coherence score

These are intentional per the Phase 1 stub label contract (D-03/D-05). Phase 2's AI labeler uses the same stdin path.

## Threat Surface Scan

All mitigations from the plan's threat register were implemented:

| Threat ID | Mitigation                                                                                                            | Implemented                                       |
| --------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| T-01-07   | O_CREAT\|O_EXCL atomic create prevents overwriting; `_reconcile_crash` compares auto_label_hash before updating state | Yes — `_write_if_not_exists` + `_reconcile_crash` |
| T-01-08   | `json.loads` with KeyError check on required "title"; unknown keys ignored                                            | Yes — `cmd_write` stdin validation                |
| T-01-09   | Every write logged to sync.log with ISO timestamp, session ID, filename                                               | Yes — `_log_sync` on all paths                    |
| T-01-10   | `subprocess.run(check=True)`; CalledProcessError caught and re-raised with session context                            | Yes — `_get_markdown_body`                        |
| T-01-11   | Raw unscrubbed exports acceptable for Phase 1 (manually-invoked pipeline)                                             | Accepted — Phase 3 adds scrubbing                 |

## Self-Check: PASSED

- [x] `sync_chats.py` exists at project root (978 lines)
- [x] Commit ae33a02 exists (`feat(01-03): implement cmd_write...`)
- [x] Commit 100866d exists (`feat(01-03): implement cmd_status...`)
- [x] Commit 6e7c0b3 exists (`fix(01-03): correct crash reconciliation...`)
- [x] `grep -c "def cmd_write" sync_chats.py` returns 1
- [x] `grep -c "def cmd_status" sync_chats.py` returns 1
- [x] `grep -q "O_CREAT" sync_chats.py` passes
- [x] `grep -c "auto_label_hash" sync_chats.py` returns 11 (>= 3)
- [x] End-to-end: first write, clobber layer 1, crash reconciliation all verified
