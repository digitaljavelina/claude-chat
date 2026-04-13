---
phase: 01-scanner-state-stub-label-write-pipeline
plan: "02"
subsystem: sync_chats
tags:
  [
    scanner,
    state,
    stub-label,
    slug,
    frontmatter,
    atomic-write,
    icloud-assertion,
  ]
dependency_graph:
  requires: []
  provides:
    [
      sync_chats.py,
      discover_sessions,
      make_slug,
      make_stub_label,
      emit_frontmatter,
      cmd_init,
      cmd_scan,
    ]
  affects: [01-03-PLAN.md]
tech_stack:
  added: []
  patterns:
    [
      tmp+fsync+rename atomic write,
      NFKD slug normalization,
      hand-rolled YAML emitter,
      CLAUDE_CHAT_HOME env override,
    ]
key_files:
  created: [sync_chats.py]
  modified: []
decisions:
  - "CLAUDE_CHAT_HOME env var used as override so all tests can point at /tmp without polluting real user dir (D-29)"
  - "All pure functions (slug, stub label, frontmatter) co-located in single file — section-commented like claude-chat.py"
  - "depth filter uses len(rel_parts) == 2 to exclude subagent JSONL files at depth 4+"
metrics:
  duration_minutes: 3
  completed: "2026-04-13"
  tasks_completed: 2
  files_created: 1
  files_modified: 0
---

# Phase 1 Plan 02: Scanner + State + Stub-Label Foundation Summary

Single-file CLI `sync_chats.py` (647 lines) with `init` and `scan` subcommands, all pure helper functions, and atomic config/state I/O — the deterministic foundation that Plan 03's write pipeline builds on.

## Tasks Completed

| Task | Name                                                                          | Commit  | Key Files                |
| ---- | ----------------------------------------------------------------------------- | ------- | ------------------------ |
| 1    | Create sync_chats.py with skeleton, config/state I/O, iCloud assertion        | 4242570 | sync_chats.py (created)  |
| 2    | Add session discovery, scan subcommand, slug, stub label, frontmatter emitter | e4cb08f | sync_chats.py (extended) |

## What Was Built

**sync_chats.py** — a 647-line stdlib-only Python CLI with:

- `init` subcommand: creates `~/.claude-chat/config.json` atomically, validates vault path is absolute+exists, supports re-run (silent overwrite) and no-args (display current config)
- `scan` subcommand: walks `~/.claude/projects/`, filters depth=2 to exclude subagent files, skips sessions already in `synced_session_ids` or with matching mtime+size fingerprint, prints JSON array sorted by mtime ascending
- `_write_atomic`: tmp+fsync+rename+.bak pattern for crash-safe config and state writes
- `_assert_not_icloud`: startup assertion on `CLAUDE_CHAT_HOME` — blocks paths containing "Mobile Documents" or "/iCloud"
- `make_slug`: NFKD Unicode normalization + kebab-case + 60-char truncation + fallback to session ID
- `make_stub_label` / `extract_first_user_message`: first 8 words of first non-system-reminder user message; falls back to "Untitled {short_id}"
- `emit_frontmatter`: hand-rolled YAML emitter with stable 14-field key order, block list form for tags, lowercase bool, bare `key:` for null
- `_get_session_date`: first JSONL timestamp (not mtime — mtime can drift from backups)
- `_extract_session_metadata`: model, token_count, msg_count from JSONL assistant messages
- `CLAUDE_CHAT_HOME` env var override for test isolation

## Verification Results

| Check                                                                                     | Result |
| ----------------------------------------------------------------------------------------- | ------ |
| `python3 sync_chats.py --help` lists all 4 subcommands                                    | PASS   |
| `init --label test --vault /tmp` creates config.json with machine_label and vault_path    | PASS   |
| `scan` prints valid JSON array, exit 0, 891 sessions found in real data                   | PASS   |
| `make_slug("Debug the export markdown function")` == "debug-the-export-markdown-function" | PASS   |
| `make_slug("!!!???", "abcd1234")` == "abcd1234" (fallback)                                | PASS   |
| `len(make_slug("a " * 40))` <= 60 (truncation)                                            | PASS   |
| stub label extracts first 8 words correctly                                               | PASS   |
| iCloud assertion fires on Mobile Documents path                                           | PASS   |
| CLAUDE_CHAT_HOME env var override works                                                   | PASS   |

## Deviations from Plan

None — plan executed exactly as written.

The depth filter comment uses `len(rel_parts) == 2` inline (per acceptance criterion) alongside the actual `if not (len(rel_parts) == 2)` check.

## Known Stubs

- `cmd_write`: prints "Not yet implemented" and exits 1 — Plan 03 implements this
- `cmd_status`: prints "Not yet implemented" and exits 1 — Plan 03 implements this
- `make_stub_label`: produces `gist: null`, `coherence_score: null` — Phase 2 AI labeler populates these

These stubs are intentional per the plan scope. `cmd_write` and `cmd_status` are Plan 03's deliverables. The stub label format is the deliberate Phase 1 contract (D-03).

## Threat Surface Scan

All mitigations from the plan's threat register were implemented:

| Threat ID | Mitigation                                                                          | Implemented                               |
| --------- | ----------------------------------------------------------------------------------- | ----------------------------------------- |
| T-01-03   | Atomic write for state.json (tmp+fsync+rename+.bak)                                 | Yes — `_write_atomic`                     |
| T-01-04   | `_assert_not_icloud()` aborts on iCloud CLAUDE_CHAT_HOME                            | Yes — called in `main()` and `cmd_init()` |
| T-01-05   | `json.loads` in try/except per line, IOError caught in `extract_first_user_message` | Yes                                       |
| T-01-06   | Atomic write for config.json + vault path validated as absolute+exists directory    | Yes — `cmd_init`                          |

## Self-Check: PASSED

- [x] `sync_chats.py` exists at project root
- [x] Commit 4242570 exists (`feat(01-02): create sync_chats.py skeleton...`)
- [x] Commit e4cb08f exists (`feat(01-02): add session discovery, scan cmd...`)
- [x] `python3 sync_chats.py --help` exits 0 with all 4 subcommands
- [x] `cmd_scan` returns 891 sessions as valid JSON
