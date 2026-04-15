---
phase: 05-sessionend-hook-observability-multi-machine-onboarding
plan: 05
subsystem: docs
tags: [readme, onboarding, sessionend-hook, multi-machine]

requires:
  - phase: 05-02
    provides: cmd_once + --once flag (the exact command the README documents)
  - phase: 05-03
    provides: cmd_status last_run.json primary path (Section 6 first-run commands)
  - phase: 05-04
    provides: cmd_relabel subcommand (Section 8 daily use)
provides:
  - README.md — ten-section universal-install onboarding (first-Mac + second-Mac)
  - SessionEnd hook live on Daisy's primary Mac (appended alongside notchi-hook.sh)
  - Documented quarantine script for 99-slug-collision tail failures
affects: []

tech-stack:
  added: []
  patterns:
    - "Generic clone-path placeholder with per-user layout examples (decouples README from any one user's directory convention)"
    - "Atomic jq-append pattern for settings.json modifications (backup → jq-to-tmp → json.tool validate → mv)"

key-files:
  created: []
  modified:
    - README.md
    - ~/.claude/settings.json (per-user, hook installed live 2026-04-15)

key-decisions:
  - "Generic clone-path placeholder <your-repo-clone-path> with note explaining symlink decoupling — chosen over hardcoding the user's actual ~/Documents/Projects/Python/claude-chat or a generic ~/Projects/claude-chat"
  - "Retain original MIT attribution (Holger Morlok) — carry-forward rule captured in feedback_preserve_attribution.md memory"
  - "Section 9 expanded with two real-world gaps: 99-slug-collision failures + ghost-skip first-scan surprise"
  - "Install settings.json edit via jq-append pattern, not hand-edit — captured as reusable technique in reference_settings_json_jq_append.md"

patterns-established:
  - "Ten-section README shape: what-it-does / prerequisites / install / configure / hook / first-run / optional-deps / daily-use / troubleshooting / architecture"
  - "Every troubleshooting entry ties to a real failure mode hit during development, not hypothetical"
  - "Multi-machine verification as explicit 8-item checklist embedded in first-run section"

requirements-completed:
  - HOOK-05

duration: ~40min
completed: 2026-04-15
---

# Phase 05-05 Summary

**Rewrote README.md as a ten-section universal-install onboarding doc (first-Mac and second-Mac). Installed the SessionEnd hook live on the primary Mac alongside the existing notchi-hook.sh. HOOK-05 — the last v1 requirement — now closed.**

## Performance

- **Duration:** ~40 min (including two revision rounds on Section 3 clone-path + Section 9 troubleshooting gaps)
- **Tasks:** 2 (1 auto rewrite + 1 human-verify checkpoint)
- **Files modified:** 1 (README.md) + 1 per-user (~/.claude/settings.json)

## Accomplishments

- README.md rewritten in D-26 order: what-it-does → prerequisites → install → configure → SessionEnd hook → first-run → optional MemPalace → daily use → troubleshooting → architecture. 10/10 H2 sections, all 9 required grep strings present.
- Section 5 embeds the exact D-19 hook JSON with explicit APPEND-to-array warning and `settings.json` backup instruction.
- Section 6 includes an 8-item Second-Mac verification checklist from RESEARCH §Multi-Machine Onboarding.
- Section 9 expanded with two real-world failure paragraphs: (a) first-run 99-slug-collision tail failures (with a ready-to-paste quarantine script that preserves a `.bak-quarantine` rollback), (b) ghost-skip first-scan surprise explaining why `/sync-chats` can report "867 new" on a populous machine.
- SessionEnd hook installed live: `python3 ~/.claude-chat/sync_chats.py --once` appended to `~/.claude/settings.json`'s `hooks.SessionEnd` array via jq-atomic-append. Existing `notchi-hook.sh` entry preserved. Validation step confirmed the file parses.

## Task Commits

1. **Task 1a: README rewrite (initial ten sections)** — `c0b521d` (docs)
2. **Task 1b: Restore MIT attribution to footer** — `a9b3b86` (docs) — caught by Daisy during checkpoint review
3. **Task 1c: Generic clone-path placeholder** — `7b88a6d` (docs) — addressed Daisy-specific path drift
4. **Task 1d: Slug-collision + ghost-skip troubleshooting paragraphs** — `3b9861d` (docs) — closed coverage gaps flagged in checkpoint
5. **Task 2: User-approved checkpoint** — 2026-04-15, after live-testing Section 6 commands against the existing last_run.json and installing the hook via jq-append

## Files Created/Modified

- `README.md` — 186 insertions, 57 deletions from Holger's original. Preserved the MIT/author footer; everything above it is the sync-chats onboarding.
- `~/.claude/settings.json` — SessionEnd array went from 1 entry (notchi) to 2 entries (notchi + sync-chats). Backup preserved at `~/.claude/settings.json.bak-preSyncChatsHook`.

## Decisions Made

- **Generic clone-path placeholder** (`<your-repo-clone-path>`) with a one-line note listing three example layouts (`~/Projects/claude-chat`, `~/code/claude-chat`, `~/Documents/Projects/Python/claude-chat`) instead of hardcoding any one. Rationale: the symlink design decouples the stable hook path from the repo location, and the README should explain that rather than hide it.
- **Ready-to-paste quarantine script in Section 9** (not just "see history for the fix"). The 99-slug-collision failure is operationally expected on any Mac with significant Claude Code history, so a self-service recovery path matters for the HOOK-05 acceptance test.
- **Kept `notchi-hook.sh` as the co-existing SessionEnd example in memory** — live-proves the "APPEND don't replace" pattern works in practice, not just in theory.

## Deviations from Plan

### Issues caught during checkpoint (all addressed inline)

**1. MIT attribution stripped in first draft.** Replaced `MIT — by [Holger Morlok](https://github.com/holbizmetrics)` with `Built 2026-04. MIT license.` — lost upstream attribution. Daisy flagged it ("retain this info"). Fix: restored verbatim in `a9b3b86`. Captured as permanent rule in `feedback_preserve_attribution.md` memory.

**2. Section 3 clone-path mismatch.** First draft used `~/Projects/claude-chat`; Daisy's actual layout is `~/Documents/Projects/Python/claude-chat`. After discussion of three options (hardcode-mine / generic / generic-with-note), chose generic-with-note in `7b88a6d`.

**3. Section 9 missed two real failure modes** that the project hit in actual live use:

- 99-slug-collision tail failures on bulk first-run (210 failures in Daisy's live run today).
- Large first-scan count from ghost-skipped ultra-short sessions (867 scanned vs 7 in state).

Both added in `3b9861d`, each tied to a reference memory (`reference_sync_chats_slug_collision_ceiling.md`, `reference_sync_chats_ghost_skip_accumulation.md`).

---

**Total deviations:** 3 caught during checkpoint review and auto-fixed. Zero scope creep.
**Impact on plan:** Strengthened the README — all three revisions reflect real operational intel that the initial plan text didn't encode.

## Issues Encountered

Nothing beyond the deviations. The jq-append hook install went first-try; Section 6 verification commands all produced correct output against the existing last_run.json.

## Next Phase Readiness

- **HOOK-05 (last v1 requirement) closed.**
- Hook is live on the primary Mac — next Claude Code session end will auto-fire `--once` and sync any new sessions without manual `/sync-chats` invocation.
- Second-Mac onboarding is unblocked: a clean machine following Sections 1-6 should reach first sync in under 10 minutes (HOOK-05 acceptance test).
- 652 stubs remain in the vault awaiting relabel — operational work, not blocking phase completion or milestone ship.
- Phase 5.1 candidates logged in milestone memory: (a) collision-ceiling proper fix (raise cap, hash-prefix slug, or dedup-by-body-hash), (b) batch-relabel helper using Haiku via Anthropic SDK for low-signal stub clusters.

---

_Phase: 05-sessionend-hook-observability-multi-machine-onboarding_
_Completed: 2026-04-15_
