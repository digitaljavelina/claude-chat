---
phase: 01-scanner-state-stub-label-write-pipeline
plan: "01"
subsystem: claude-chat.py / planning-docs
tags: [export, stdout, protect-audit, core-11, core-12]
dependency_graph:
  requires: []
  provides:
    - "export --stdout flag for subprocess bridge (CORE-11)"
    - "protect audit document confirming cmd_protect() does not scrub (CORE-12)"
  affects:
    - "sync_chats.py (Phase 1 plans 02-04): subprocess call to claude-chat.py export --stdout"
    - "Phase 3 PRIV track: inherits CORE-12 as entry task for scrub-content implementation"
tech_stack:
  added: []
  patterns:
    - "sys.stdout.write(content) early-return pattern in cmd_export()"
    - "getattr(args, 'stdout', False) safe attribute access"
key_files:
  created:
    - .planning/phases/01-scanner-state-stub-label-write-pipeline/01-PROTECT-AUDIT.md
  modified:
    - claude-chat.py
decisions:
  - "CORE-12 audit confirmed: cmd_protect() only manages cleanupPeriodDays, no content scrub — Phase 3 must build scrubbing from scratch"
  - "--stdout flag placed in single-session path only; --all mode intentionally excluded (concatenating many sessions to stdout makes no sense)"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-13"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 2
---

# Phase 01 Plan 01: --stdout Flag and Protect Audit Summary

**One-liner:** Backwards-compatible `export --stdout` subprocess bridge added to `claude-chat.py`; protect audit confirms Phase 3 must build content scrubbing from scratch.

## What Was Built

### Task 1: --stdout flag on export subcommand (CORE-11)

Added two changes to `claude-chat.py`:

1. **argparse registration** (line 1568): `p.add_argument("--stdout", ...)` appended after the existing `--rich` argument on the export subparser.

2. **Early-return branch in `cmd_export()`** (lines 518–531): After `session.parse()`, if `args.stdout` is True, renders content using the appropriate formatter and calls `sys.stdout.write(content)` then returns immediately — skipping all file-write logic. The `--all` path is untouched.

This is the subprocess bridge that `sync_chats.py write` will use in Plans 02–04:

```bash
python3 claude-chat.py export <uuid> --format md --stdout
```

### Task 2: Protect audit document (CORE-12)

Created `01-PROTECT-AUDIT.md` documenting:

- `cmd_protect()` at line 821 only sets `cleanupPeriodDays = 99999` in `~/.claude/settings.json`
- Zero JSONL reads, zero content modifications
- Phase 3 (PRIV track) owns the `protect --scrub-content` implementation
- Phase 1 safety caveat: raw vault writes are acceptable because sync is manual; SessionEnd hook deferred to Phase 5 (post-Phase 3)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Both deliverables are complete and functional.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The `--stdout` flag routes the same content that the existing file-write path produces — no new information surface (T-01-01: accepted per plan's threat model).

## Self-Check: PASSED

| Check                          | Result |
| ------------------------------ | ------ |
| `claude-chat.py` exists        | FOUND  |
| `01-PROTECT-AUDIT.md` exists   | FOUND  |
| `01-01-SUMMARY.md` exists      | FOUND  |
| commit f3da699 (--stdout flag) | FOUND  |
| commit 59e8c1e (protect audit) | FOUND  |
