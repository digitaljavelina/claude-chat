# Phase 5: SessionEnd Hook + Observability + Multi-Machine Onboarding - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Automate the full `scan → write` pipeline via a `SessionEnd` hook in `~/.claude/settings.json` so every ended Claude Code session turns into a vault file within seconds — without manual `/sync-chats` invocation. Add a `--once` root flag to `sync_chats.py` that is the hook's single entry point. Introduce `~/.claude-chat/last_run.json` as the machine-readable record of each run, refactor `cmd_status` to read it (with fallback to the existing `state.last_run_at`), centralize the OBSERV-01 summary line in one formatter, and ship a universal-install `README.md` at repo root that onboards a second Mac in under ten minutes.

**Explicitly out of scope:**

- AI label generation inside `--once` (headless `/skill` is disabled; stubs only — see D-01..03).
- `mempalace mine` inside `--once` (defers to interactive SKILL; see D-08..09).
- Any re-labeling of already-labeled files (the SKILL's re-label path targets the stub sentinel only — see D-05).
- Log rotation for `sync.log` (deferred, per Phase 1 D-33).
- A separate `pending.json` queue, a wrapper shell script for the hook, desktop notifications, or any history beyond the current+`.bak` `last_run.json`.

The exit criterion is that Michael can (1) end a Claude Code session and see a stub-labeled file appear in `<vault>/Chats/` within seconds, (2) `cat ~/.claude-chat/last_run.json` and see the schema below, (3) `sync_chats.py status` reads that file, (4) run `/sync-chats` interactively and watch stubs get upgraded to AI labels, (5) follow the repo-root `README.md` on a second Mac and be fully running in under ten minutes.

</domain>

<decisions>
## Implementation Decisions

### A — `--once` labeling strategy

- **D-01:** `sync_chats.py --once` generates **stub labels** for every new session it writes. It does NOT and CANNOT invoke Claude — `claude -p /skill` headless is disabled (ref: `memory/reference_claude_code_headless_limits.md`). Stubs are the only label source in hook-driven runs.
- **D-02:** The stub generator reused is the exact Phase 1 path: title = first 8 words of first user message, `gist: null`, `tags: ["stub"]`, `coherence_score: null`, `needs_review: true`. The stub dict is built in-process and fed through the **same stdin contract** Phase 1 D-01 locks (`write` only reads labels from stdin). No `--stub` flag is added to `write` — `cmd_once` builds the dict and calls the write path internally with that dict.
- **D-03:** `auto_label_hash` is set to the literal sentinel string `"stub"` on every `--once` write. This is the re-label trigger for the interactive SKILL. Real AI-labeled files get the Phase 3 SHA-256 hash; stubs get the sentinel. The two are trivially distinguishable at re-label time.
- **D-04:** Interactive `/sync-chats` (the SKILL) gains a re-label code path: scan `<vault>/Chats/` for files with `auto_label_hash: stub`, regenerate labels via Claude, rewrite **only the frontmatter** (not the body), update `auto_label_hash` to the real SHA-256, flip `needs_review` to `false`. The body is untouched, so the hash stays consistent with Phase 3's post-scrub contract.
- **D-05:** The re-label trigger is **stub-sentinel only**, not `needs_review: true`. This preserves the semantic distinction: `needs_review: true` means "human, look at this"; `auto_label_hash: "stub"` means "AI, finish your job." A user manually flagging a chat for review will never be silently re-labeled.
- **D-06:** Stubs land in the vault immediately (HOOK-02's sub-second latency). Real labels arrive on the next interactive `/sync-chats`. The user never has to wait for AI labels to see their chat in Obsidian.

### B — `--once` entrypoint shape and orchestration

- **D-07:** `--once` is a **root flag**, not a subcommand: `python3 sync_chats.py --once`. Implemented via argparse top-level `--once` action that dispatches to `cmd_once` before subparser routing. Rationale: ROADMAP §Phase 5 SC#1 names the flag literally, and the `settings.json` hook command reads cleaner as a flag.
- **D-08:** `--once` runs a **partial loop**: `scan → write-all-with-stubs`. It does **NOT** invoke `mine`. Rationale: stub titles are the worst possible substrate for MemPalace semantic search; mining them would actively pollute the memory palace with placeholder-quality embeddings.
- **D-09:** `mine` ownership stays with the interactive SKILL (Phase 4 D-02 unchanged). The SKILL runs `scan → write → re-label-stubs → mine` after AI labels exist. This means MemPalace always ingests real-title chats.
- **D-10:** Exit-code policy (Phase 1 D-31) is preserved in `cmd_once`: `0` on all-success-or-skipped, `1` on per-session failure, `2` on pre-flight error.

### C — `last_run.json` schema and writer

- **D-11:** A new file `~/.claude-chat/last_run.json` is written at the end of every run (both `--once` and interactive SKILL-driven). Schema version 1:
  ```json
  {
    "schema_version": 1,
    "run_started_at": "ISO-8601 UTC",
    "run_finished_at": "ISO-8601 UTC",
    "trigger": "once" | "interactive" | "manual",
    "machine_label": "<string from config>",
    "hostname": "<socket.gethostname()>",
    "synced": <int>,
    "skipped": <int>,
    "failed": <int>,
    "flagged_for_review": <int>,
    "mempalace_mined": "true" | "false" | "skipped",
    "mempalace_reason": "<string>" | null,
    "exit_code": 0 | 1 | 2,
    "errors": [{"session_id": "...", "error_class": "...", "error_message": "..."}]
  }
  ```
- **D-12:** `trigger: "once"` for hook runs, `"interactive"` for SKILL-driven runs, `"manual"` reserved for future one-shot `write <uuid>` runs (optional to populate in Phase 5; leave the enum open).
- **D-13:** `errors[]` is capped at **10 entries**. Additional errors are counted in `failed` but not listed in the array — prevents unbounded growth on pathological runs.
- **D-14:** Write strategy: **atomic overwrite each run**, with `.bak` kept as the previous version. Same `tmp + fsync + rename` pattern as `state.json`. Overwrites the previous `last_run.json`; the `.bak` gives one-run undo visibility for post-mortem.
- **D-15:** `mempalace_mined` is `"skipped"` in every `--once` run because `--once` never runs mine (D-08). Only interactive SKILL runs produce `"true"` or `"false"` here. Phase 4 D-05/D-06/D-07 semantics for the three states carry forward.
- **D-16:** `flagged_for_review` is an **explicit counter** incremented in `cmd_once` per stub-write. The SKILL increments it zero times (real labels have `needs_review: false`). The formatter never infers it from `trigger`.

### C' — `status` refactor

- **D-17:** `cmd_status` reads `last_run.json` first. If it exists, display fields from it via the shared formatter (D-20). If it does not exist, fall back to the current `state.last_run_at` display. This is a **one-run migration**: after Phase 5 ships and the hook fires once, `last_run.json` is authoritative forever.
- **D-18:** `state.last_run_at` continues to be written by `cmd_write` as it does today. Redundant with `last_run.json` but zero-cost and preserves forward/backward compatibility during the migration. A future phase can remove `last_run_at` from `state.json` once confidence is established; Phase 5 does not.

### D — SessionEnd hook shape

- **D-19:** Hook command is **direct**, not a wrapper script:
  ```json
  {
    "hooks": {
      "SessionEnd": [
        {
          "hooks": [
            {
              "type": "command",
              "command": "python3 ~/.claude-chat/sync_chats.py --once"
            }
          ]
        }
      ]
    }
  }
  ```
  Rationale: B.2(y) removes the only real env concern (pipx-PATH for `mempalace` was the motivator for a wrapper; `--once` doesn't run mine). One fewer file to install on the second Mac.
- **D-20:** Hook is **blocking** (synchronous). The `--once` path is fast — no AI calls, no mine, just scan + stdlib file I/O on 0–2 new sessions typical — so wall-clock is sub-second. Blocking eliminates the race where two overlapping `--once` processes contend on `state.json`. Phase 1's clobber-defense would catch the race harmlessly, but blocking prevents the `sync.log` noise.
- **D-21:** Hook failure is **silent**: non-zero exit from `--once` is captured only in `sync.log` and `last_run.json.exit_code`. No stderr flash to Claude Code UI, no desktop notification. User discovery is via `status`. Phase 1 D-31's exit-code policy already makes this a complete audit trail.

### E — Summary line ownership

- **D-22:** A single helper `_format_summary(last_run_dict) -> str` in `sync_chats.py` is the sole source of truth for the OBSERV-01 summary line. Signature takes the same dict that was (or will be) written to `last_run.json`. Callers: `cmd_once` (prints it at the end of a hook run), the SKILL (via reading `last_run.json` after `mine`, or via the CLI emitting it and the SKILL echoing), and `cmd_status` (displays the most-recent run).
- **D-23:** Summary line format (literal, matches OBSERV-01):
  ```
  Synced N new chats, M skipped (already-synced), K flagged for review, mempalace_mined: <status>
  ```
  When `mempalace_mined` is `false` or `skipped`, append the reason in parentheses (Phase 4 D-15 unchanged): `mempalace_mined: skipped (command not found)`.
- **D-24:** `cmd_once` tracks `flagged_for_review` as an explicit counter incremented per successful stub-write. It is passed into the `last_run.json` dict before `_format_summary` is called. No inference from `trigger`.

### F — README scope and location

- **D-25:** A single `README.md` at repo root. Covers both first-Mac and second-Mac installation via a **universal install path** — Phase 1 D-22 makes `init` re-runnable with the same flags a no-op, so one set of instructions works for any new machine regardless of how many the user already has.
- **D-26:** Scope — ten sections, in order:
  1. What it does (one paragraph)
  2. Prerequisites (Python 3.9+, Obsidian vault, optional: pipx-installed `mempalace`)
  3. Install (`git clone`, `mkdir ~/.claude-chat`, symlink `sync_chats.py`)
  4. Configure (`sync_chats.py init --label <short_label> --vault <absolute_path>`)
  5. Install the SessionEnd hook (exact JSON snippet for `~/.claude/settings.json`)
  6. First run (end a Claude session, `ls <vault>/Chats/`, `cat ~/.claude-chat/last_run.json`)
  7. Optional: MemPalace (`brew install pipx && pipx install mempalace`)
  8. Daily use (`/sync-chats` for AI-label upgrade of stubs, `status` for audit)
  9. Troubleshooting (iCloud assertion, hook not firing, `sync.log` location)
  10. Architecture (short) — three-tier split, link to `.planning/` for artifacts
- **D-27:** No separate `ONBOARDING.md` or `docs/SETUP.md`. No second-Mac-specific doc. One README, one path, one verification checklist.

### Claude's Discretion

The planner and executor have freedom on:

- Exact argparse wiring for the root `--once` flag (action vs pre-parse branch vs subparser-with-default — any stdlib idiom is fine as long as the hook command string `python3 ~/.claude-chat/sync_chats.py --once` works).
- Internal function naming inside `cmd_once` — whether to share helpers with SKILL-orchestrated `scan+write` loops or keep an independent copy. Optimize for readability.
- Exact JSON key order in `last_run.json` (the Python `json.dumps` default is fine; readability > parseability since consumers are `jq`-friendly).
- Whether the re-label code path (D-04) lives in SKILL.md text, as a `sync_chats.py relabel` subcommand, or as a Python helper the SKILL imports via subprocess. **Recommended:** a dedicated `relabel <session_id>` subcommand that the SKILL calls in a loop — matches Phase 1/4 toolkit philosophy of single-purpose subcommands. But the planner may choose otherwise if SKILL-only makes more sense.
- Exact stderr/output wording for error cases, provided `sync.log` format (Phase 3 D-21) and exit-code policy (Phase 1 D-31) are honored.
- Precise README prose — tone should match the existing `.planning/PROJECT.md` voice (direct, technical, minimal fluff).

</decisions>

<specifics>
## Specific Ideas

- **"Stubs are placeholders, not data" (A).** The whole point of writing stubs in `--once` is that they're guaranteed to be _replaced_ by the interactive SKILL. The stub sentinel `auto_label_hash: "stub"` is the contract between the hook-driven writer and the interactive re-labeler. Any planner instinct to improve stub quality (e.g., "we could generate better titles by running NLP on the first message") is a scope creep and should be rejected — stubs are deliberately cheap because they're ephemeral.
- **"Sub-second vault-write is the SLA" (D-06).** HOOK-02 requires sub-second latency from session-end to file-visible-in-Obsidian. That's achievable because (a) `--once` does no AI calls, (b) no `mine`, (c) typical new-session count per hook fire is 0–2. If any design decision would violate this (e.g., adding synchronous `mine`, adding a pre-write analysis step), the decision is wrong.
- **Michael is a Python beginner.** Carrying forward from Phase 1 — code should err toward stdlib idioms and inline comments over clever abstractions. `argparse` root-flag handling is subtle; add a comment explaining the pre-dispatch branch. The `last_run.json` atomic writer should be a near-copy of the existing `state.json` writer with a section comment pointing out what's shared and why.
- **The SessionEnd hook is the first piece of this project that runs outside Michael's conscious attention.** That elevates the bar for silent failure handling: the hook must never make Claude Code feel slower, must never print noise, and must record enough in `sync.log` + `last_run.json` to reconstruct what happened from a cold `status` invocation days later.
- **Canary parity reminder.** The Phase 3 canary test covers `scrub → label → write` for a single session. Phase 5 does NOT extend the canary to cover `--once` or the hook — per Phase 4 precedent, post-run steps stay out of the canary fixture. The nine Phase 5 success criteria are verified by end-to-end manual checks, not the canary.

</specifics>

<canonical_refs>

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Vision

- `.planning/REQUIREMENTS.md` §HOOK — HOOK-01 through HOOK-05 (hook install, latency, idempotency, interactive escape hatch, multi-machine README)
- `.planning/REQUIREMENTS.md` §OBSERV — OBSERV-01 through OBSERV-04 (summary line, sync.log, last_run.json, status subcommand)
- `.planning/ROADMAP.md` §Phase 5 — seven success criteria (the executable definition of "done")
- `.planning/PROJECT.md` §Key Decisions — three-tier split (hook → sync_chats.py → claude-chat.py), "SKILL orchestrates, CLI executes," no per-chat MCP calls

### Prior Phase Context (load-bearing for Phase 5)

- `.planning/phases/01-scanner-state-stub-label-write-pipeline/01-CONTEXT.md` — D-01..D-03 (LABEL-09 stdin-only contract), D-04..D-06 (stub shape reused in Phase 5), D-22 (`init` idempotency enables universal install in D-25), D-24..D-26 (atomic-write pattern to mirror for `last_run.json`), D-31..D-33 (exit codes, summary line, sync.log format all reused by Phase 5)
- `.planning/phases/02-skill-md-ai-labeling/02-CONTEXT.md` — SKILL.md orchestration pattern that the Phase 5 re-label code path (D-04) extends
- `.planning/phases/03-pii-scrub-integration-crash-safety-polish/03-CONTEXT.md` — `auto_label_hash` sentinel semantics (Phase 5 extends with literal `"stub"` value in D-03), scrub→label→write ordering (unchanged by Phase 5)
- `.planning/phases/04-mempalace-bulk-mine-integration/04-CONTEXT.md` — D-02 (SKILL owns mine, carried forward by Phase 5 D-09), D-14/D-15 (mempalace_mined three-state + reason format preserved in `last_run.json` and summary line)

### Codebase map

- `.planning/codebase/ARCHITECTURE.md` — claude-chat.py layering (unchanged by Phase 5 — no edits to this file are required)
- `.planning/codebase/CONVENTIONS.md` — single-file CLI, stdlib-only, subcommand-via-argparse
- `.planning/codebase/STACK.md` — zero external dependencies invariant (Phase 5 adds none)

### Existing Code (primary targets for Phase 5 edits)

- `sync_chats.py` — add `cmd_once`, root `--once` flag wiring, `_format_summary(last_run_dict)` helper, `_write_last_run(dict)` atomic writer. Extend `cmd_status` to read `last_run.json` with fallback to `state.last_run_at`.
- `sync_chats.py:914` — `_log_sync(message)` helper. Reuse as-is for all Phase 5 log lines.
- `sync_chats.py:1231` — `cmd_status` current implementation. Refactor per D-17/D-18.
- `sync_chats.py:1332+` — argparse dispatcher. Add root `--once` handling before subparser routing.
- `sync_chats.py:1265` — `cmd_mine` (Phase 4). Referenced only; Phase 5 does not modify it.
- `~/.claude/settings.json` — add `hooks.SessionEnd` entry with the exact command string from D-19. User-owned file, not committed.
- `<repo>/README.md` — create new (or rewrite existing, if any) per D-25/D-26.

### Reference Memory

- `~/.claude/projects/-Users-michaelhenry-Documents-Projects-Python-claude-chat/memory/reference_claude_code_headless_limits.md` — confirms `claude -p /skill` is disabled; the source of D-01's constraint
- `~/.claude/projects/-Users-michaelhenry-Documents-Projects-Python-claude-chat/memory/reference_mempalace_bulk_mine.md` — mine invocation and graceful degradation pattern (already honored by Phase 4, referenced here only because the SKILL's post-re-label `mine` still uses it)

### No external ADRs

No ADR directory in this project. All decisions live in `.planning/PROJECT.md` §Key Decisions and phase-level CONTEXT.md files.

</canonical_refs>

<code_context>

## Existing Code Insights

### Reusable Assets

- **Stub generator from Phase 1** — `sync_chats.py` already has the first-8-words-of-first-user-message extractor and the stub dict builder. `cmd_once` calls it per session, pipes the dict through the existing stdin-contract write path. Zero new stub logic.
- **Atomic writer pattern** — `state.json` and `config.json` writers at `sync_chats.py` (tmp + fsync + rename + `.bak` preservation) are the template for `_write_last_run()`. Near-copy with different path and dict.
- **`_log_sync()` at sync_chats.py:914** — unchanged append-only logger. Phase 5 uses it for hook run-start/run-finish and per-session progress lines.
- **`_require_config()` at sync_chats.py:156** — ensures `init` has run. `cmd_once` calls it first; pre-flight failure gives exit code `2` per Phase 1 D-31.
- **Existing argparse subparser idiom at sync_chats.py:1338** — the `_format_summary` helper is pure (dict in, string out), so it's trivially callable from any subcommand. `cmd_status` reuse is a one-liner.
- **Three-state `mempalace_mined` convention from Phase 4** — `true | false | skipped` with optional parenthesized reason. Phase 5 carries this format verbatim into `last_run.json` and the summary line.

### Established Patterns

- **Single-file Python CLI** — `sync_chats.py` stays single-file. No module split for Phase 5. The new `_format_summary` and `_write_last_run` are section-commented helpers next to the existing ones.
- **Zero external dependencies** — Phase 5 adds no deps. All new features use `argparse`, `json`, `socket.gethostname()`, `datetime`, `pathlib`, `os.replace`, `subprocess` (already present).
- **Subcommand-via-argparse** — root flags are unusual but supported. The argparse pattern for this is: define `--once` as a top-level argument with `action="store_true"`, then after `parse_args()`, branch on `args.once` BEFORE dispatching to any subcommand's `func`. Single-file clarity wins.

### Integration Points

- **`~/.claude/settings.json`** — new `hooks.SessionEnd` entry installed by the user per the README. This file is user-owned, not part of the repo. Phase 5 documents the exact JSON snippet; it does not automate the install.
- **`~/.claude-chat/last_run.json`** — new file introduced by Phase 5. Nothing in the existing codebase references it yet; Phase 5 is introducing it.
- **SKILL.md (per-user, not in repo, per memory `reference_skill_md_tests_ci.md`)** — Phase 5 updates the SKILL's orchestration to call the new `relabel` code path (if D-04 is implemented as a subcommand, the SKILL gains a `for each stub-file in vault: sync_chats.py relabel <id>` loop before `mine`). Tests that read SKILL.md use `@unittest.skipUnless` at class level per the memory.

</code_context>

<deferred>
## Deferred Ideas

The following surfaced during Phase 5 framing but belong elsewhere:

- **Sync-run history / trends dashboard** — a `runs.jsonl` append-only log alongside `last_run.json`. Would enable "how many chats synced this week" queries. Deferred; OBSERV-03 explicitly asks for most-recent only. Revisit if Michael ever wants a stats page.
- **Desktop notification on hook failure** — rejected by D-21 (silent). Revisit if a production incident makes silent failure feel insufficient; the fix would be an optional macOS `osascript` branch guarded by a config flag.
- **Wrapper shell script for the hook** — rejected by D-19 (direct command). Revisit only if the pipx-PATH or environment concern ever actually bites (unlikely given B.2(y)).
- **`mine` inside `--once`** — rejected by D-08. Revisit only if MemPalace gains a "skip stub-titled files" filter, which would make it safe to mine during hook runs. Currently not on MemPalace's roadmap as far as memory knows.
- **Fire-and-forget hook (backgrounded `&` spawn)** — rejected by D-20. Revisit only if the blocking wall-clock ever exceeds ~1 second in the typical case (would indicate a pipeline regression upstream, not a need for async).
- **Removal of `state.last_run_at`** — deferred by D-18. A future phase (post-v1) can drop it once confidence that every machine has rolled past Phase 5 is established.
- **Automatic SessionEnd-hook installer** (`sync_chats.py install-hook` subcommand that edits `~/.claude/settings.json`) — tempting for onboarding UX but rejected here because editing user-owned config files programmatically is risky and the README JSON snippet is a two-line paste. Revisit if the manual step becomes a common onboarding failure.
- **README localization / screenshot-rich variant** — personal tool, single-user audience; text-only README is enough. Deferred indefinitely.
- **`trigger: "manual"` population** — D-12 reserves the enum value but Phase 5 doesn't have to wire it. Any future single-session CLI path (e.g., `write <uuid>` outside the SKILL) can start populating it.

</deferred>

---

_Phase: 05-sessionend-hook-observability-multi-machine-onboarding_
_Context gathered: 2026-04-14 via /gsd-discuss-phase 5_
