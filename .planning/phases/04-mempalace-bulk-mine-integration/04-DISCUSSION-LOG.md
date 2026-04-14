# Phase 4: MemPalace Bulk-Mine Integration - Discussion Log

**Date:** 2026-04-14
**Mode:** Interactive discussion (trade-off walk-through)
**Purpose:** Full audit trail of Q&A during context gathering. Not consumed by downstream agents — for human reference only.

---

## Pre-Discussion Codebase Scout

- Read `.planning/ROADMAP.md` §Phase 4 — goal, dependencies (Phase 3), 3 success criteria mapping 1:1 to MEM-01/02/03.
- Read `.planning/REQUIREMENTS.md` §MEM — 3 requirements.
- Read `.planning/PROJECT.md` §Key Decisions — confirmed "One bulk `mempalace mine --mode convos` shell-out at end of run" is locked.
- Read `.planning/STATE.md` — confirmed Phase 4 position, 0 plans, ready to plan.
- Read memory `reference_mempalace_bulk_mine.md` — verified CLI usage, idempotency, graceful-degradation pattern.
- Inspected `sync_chats.py` — subcommand layout (init/scan/write/status), no existing `mine` or `--once`, `_log_sync` helper at :914, argparse dispatcher at :1268.
- Inspected mempalace install state on user's machine — discovered mempalace was only a zsh alias, not a PATH binary.

## Mid-Discussion Discovery: Alias → PATH Binary

**User said:** "let's make mempalace more accessible. It should be a binary on path, correct?"

**Investigation:**

- `type mempalace` → alias for `python3.13 -m mempalace`
- `python3.13 -m pip show mempalace` → installed at `/opt/homebrew/lib/python3.13/site-packages/` (mempalace 3.1.0) with console_script entry point declared but `/opt/homebrew/bin/mempalace` missing (pruned by Homebrew/PEP 668).
- PEP 668 blocked direct `pip install --force-reinstall` reattempts.

**Action taken:**

- `pipx install mempalace` → installed mempalace 3.3.0 in its own venv, symlinked `/Users/michaelhenry/.local/bin/mempalace` (which is on PATH).
- Removed `alias mempalace='python3.13 -m mempalace'` from `~/.zshrc:32`.
- Verified: `zsh -ic 'whence -v mempalace'` → `mempalace is /Users/michaelhenry/.local/bin/mempalace` (no alias shadow).
- Updated memory `reference_mempalace_bulk_mine.md` to reflect resolved state.

**Impact on phase:** The "detection strategy" gray area collapsed from "how do we handle the alias gotcha" to "use standard `shutil.which`". Captured as D-12/D-13 in CONTEXT.md.

---

## Gray Areas Presented

After scout, presented four gray areas via AskUserQuestion (multiSelect):

1. Invocation point / entrypoint
2. Detection strategy
3. Scope of each mine call
4. Error handling & timeout

User requested clarification, then resolved the detection-strategy concern out-of-band by migrating to a pipx install (above). Remaining three areas were walked through with trade-off tables; user replied **"recommended"** to all three.

---

## Area 1: Invocation Point

**Question:** Where does the `mine()` call live in the codebase?

**Options presented:**

| Option                                                           | Pros                                                                                                                        | Cons                                                                                                     |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| A. New `sync` subcommand wrapping `scan → write(each) → mine`    | One entrypoint for humans and Phase 5 hook. Mine belongs with "a run finished". Matches PROJECT.md locked ordering.         | Introduces a pipeline inside CLI. Label generation (SKILL's job) would need a callback or move into CLI. |
| B. Standalone `mine` subcommand, SKILL chains it                 | Minimal code change. Single-purpose subcommand matches existing style. Orchestration stays in SKILL where it already lives. | Two callers (SKILL, future Phase 5 wrapper) must both remember to chain `mine` last.                     |
| C. Implicit call from `write` when it's the last pending session | Fully automatic.                                                                                                            | Tight coupling. `write` is supposed to be per-session. Detecting "last one" is brittle.                  |

**Recommended:** B
**User answer:** "recommended" → **B locked**
**Decisions captured:** D-01, D-02, D-03

---

## Area 2: Scope of Each Mine Call

**Question:** Does mine() process the whole `<vault>/Chats/` directory every time, or just the newly-written files?

**Options presented:**

| Option                                            | Pros                                                                                      | Cons                                                                                                                     |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| A. Whole directory every run                      | Matches CLI's idempotent contract. Self-healing on prior failures. Dead simple.           | Scales O(vault size) — fine for now, eventually slow.                                                                    |
| B. Only newly-written files (pass a file list)    | Efficient. Work proportional to actual new content.                                       | Mempalace CLI takes a directory, not a file list (verified). Loses self-healing. Needs mined_session_ids state tracking. |
| C. Whole directory, BUT skip when zero new writes | Preserves self-healing. Skips no-op runs. Maps cleanly to MEM-03's three-state semantics. | Slightly more decision logic.                                                                                            |

**Recommended:** C
**User answer:** "recommended" → **C locked**
**Decisions captured:** D-04, D-05, D-06

---

## Area 3: Error Handling & Timeout

**Question:** How does the mine step behave when subprocess fails, times out, or exits non-zero?

**Sub-decisions and options presented:**

| Decision          | Options                                                                                                       | Recommended                                                                                                     |
| ----------------- | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Failure semantics | (a) non-zero exit → `mempalace_mined: false`, sync still exits 0. (b) propagate failure, sync exits non-zero. | (a) — MEM-02 locks "vault writes must succeed regardless".                                                      |
| Timeout           | (a) none. (b) 5-min soft cap. (c) user-configurable via config.json.                                          | (b) — 300s is generous for current vault size, prevents hook wedging. Config-configurability deferred as YAGNI. |
| Retry             | (a) one-shot. (b) retry once on timeout.                                                                      | (a) — self-healing from Q2 makes retry redundant.                                                               |
| stderr capture    | (a) log full stderr always. (b) log last N lines on failure only.                                             | (b) — success silent, failures diagnosable.                                                                     |

**User answer:** "recommended" → all four sub-decisions locked
**Decisions captured:** D-07, D-08, D-09, D-10, D-11

---

## Deferred / Scope-Creep Items

None raised during discussion. The three items in CONTEXT.md `<deferred>` were considered during trade-off analysis and rejected in favor of simpler alternatives — they are deferred as "options rejected for Phase 4, revisit if the simpler choice ever bites".

---

## Canonical Refs Accumulated During Discussion

- `.planning/REQUIREMENTS.md` §MEM — referenced to ground MEM-01/02/03 mapping
- `.planning/PROJECT.md` §Key Decisions — referenced to confirm locked "bulk shell-out, not per-chat MCP"
- `sync_chats.py` — read to understand subcommand pattern, log helper, argparse dispatcher
- Memory: `reference_mempalace_bulk_mine.md` — referenced for CLI idempotency + pattern
- `mempalace mine --help` output — referenced for current CLI flags

All merged into CONTEXT.md `<canonical_refs>`.

---

## Summary

Discussion took one pass. User pre-resolved the detection gray area by migrating mempalace from alias-only to a pipx-managed PATH binary. Remaining three gray areas accepted all recommended defaults. Phase is ready to plan.

**Next step:** `/gsd-plan-phase 4` to generate RESEARCH.md and PLAN.md.
