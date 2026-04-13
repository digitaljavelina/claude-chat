# Roadmap: `/sync-chats` Claude Code Skill

## Overview

A brownfield milestone on the existing zero-deps `claude-chat.py` CLI. We are adding a thin three-tier orchestration layer — a deterministic stdlib helper (`sync_chats.py`), a Claude Code skill (`SKILL.md`), and a SessionEnd hook — that turns every Claude Code session on Michael's two Macs into an AI-titled, PII-scrubbed, MemPalace-fed markdown file in the iCloud-synced Obsidian vault, automatically, with zero cross-machine clobber risk.

Five phases, derived from the research-synthesis convergence (SUMMARY.md §5) and already approved by the user. Each phase ends with something end-to-end testable without the next. The ordering front-loads the deterministic write pipeline (Phase 1), adds semantic labeling on a provably-idempotent foundation (Phase 2), locks the `scrub → label → write` ordering with a CI-gated canary (Phase 3), feeds MemPalace only after chats are PII-safe (Phase 4), and automates the whole thing via an event-driven hook last (Phase 5).

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3, 4, 5): Planned milestone work
- Decimal phases (e.g., 2.1): Reserved for urgent insertions (none at roadmap time)

- [ ] **Phase 1: Scanner + State + Stub-Label Write Pipeline** - Deterministic delta-sync, atomic state, file-exists defense, stub labels, `protect` audit
- [ ] **Phase 2: SKILL.md + AI Labeling** - Claude Code skill with Claude-generated titles/gists/tags replacing stubs
- [ ] **Phase 3: PII Scrub Integration + Crash Safety Polish** - Locked scrub ordering, canary CI gate, `auto_label_hash` sentinel
- [ ] **Phase 4: MemPalace Bulk-Mine Integration** - Post-run shell-out to `mempalace mine --mode convos` with graceful degradation
- [ ] **Phase 5: SessionEnd Hook + Observability + Multi-Machine Onboarding** - Event-driven scheduling, sync.log, last_run.json, status command, README

## Phase Details

### Phase 1: Scanner + State + Stub-Label Write Pipeline

**Goal**: User can manually run a stdlib-only helper to detect new Claude Code sessions on one Mac and emit properly-named, correctly-framed markdown files into the Obsidian vault, with provable idempotency and no possibility of clobbering an existing file — setting up every downstream phase to be additive rather than corrective.
**Depends on**: Nothing (first phase)
**Requirements**: CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, CORE-06, CORE-07, CORE-08, CORE-09, CORE-10, CORE-11, CORE-12, CORE-13, LABEL-09
**Success Criteria** (what must be TRUE):

1. User runs `python3 ~/.claude-chat/sync_chats.py init --label mbp` and a `~/.claude-chat/config.json` with the machine label exists.
2. User runs `python3 ~/.claude-chat/sync_chats.py scan` and sees a JSON list of unsynced session UUIDs from `~/.claude/projects/`.
3. User runs `python3 ~/.claude-chat/sync_chats.py write <session_id>` and a file named `<machine>--YYYY-MM-DD--<slug>.md` appears in `<vault>/Chats/` with valid YAML frontmatter (title, gist, tags, project, session_id, model, token_count, msg_count, machine, hostname, synced_at, needs_review, auto_label_hash).
4. User runs the same `write` command twice in a row and the second invocation produces zero new files and prints `skipped: already_synced`.
5. User deletes `~/.claude-chat/state.json`, re-runs `write` on an already-synced session, and the file-exists check refuses the write (clobber defense layer 2 holds even with state loss).
6. User starts `sync_chats.py` after symlinking `~/.claude-chat` into an iCloud path and the program aborts at startup with an iCloud assertion error.
7. User runs `python3 claude-chat.py export <session_id> --format markdown --stdout` and rendered markdown flows to stdout without touching disk; omitting `--stdout` preserves the existing file-writing behavior.
8. User runs `python3 ~/.claude-chat/sync_chats.py status` and sees machine label, last run timestamp, synced count, and pending count.
9. The Phase 1 `protect` audit is documented: either `cmd_protect()` is confirmed to scrub content (and the path the pipeline will call is recorded), or a backwards-compatible `protect --scrub-content` stdin/stdout mode has been added to `claude-chat.py`.
   **Plans:** 4 plans

Plans:

- [x] 01-01-PLAN.md — Add export --stdout to claude-chat.py + protect audit doc
- [x] 01-02-PLAN.md — Create sync_chats.py with init, scan, and all pure functions
- [x] 01-03-PLAN.md — Write pipeline with 3-layer clobber defense + status subcommand
- [x] 01-04-PLAN.md — Unit tests + end-to-end canary script

### Phase 2: SKILL.md + AI Labeling

**Goal**: User can invoke `/sync-chats` in any Claude Code session and watch Claude produce high-quality titles, 2–3 sentence gists, 3–5 kebab-case tags, and coherence scores for every new chat, writing them through the Phase 1 pipeline that is already proven idempotent — so label-quality iteration and pipeline-correctness bugs stay decoupled.
**Depends on**: Phase 1 (the stub-label write pipeline must be provably idempotent before real labels are wired in, otherwise label-quality bugs and pipeline-correctness bugs would be entangled)
**Requirements**: LABEL-01, LABEL-02, LABEL-03, LABEL-04, LABEL-05, LABEL-06, LABEL-07, LABEL-08
**Success Criteria** (what must be TRUE):

1. User types `/sync-chats` in an interactive Claude Code session and the skill loads, scans for deltas, and processes each delta one at a time.
2. User opens a freshly-written file in Obsidian and sees a title of ≤10 words (verb-leading where applicable) that captures the conversation's gist.
3. User opens the same file and sees a 2–3 sentence past-tense gist, a YAML list of 3–5 kebab-case tags (not comma-separated, not inline `#tag`), and a `coherence_score` between 1 and 5.
4. User runs `/sync-chats` against a session that is <500 characters and the skill skips it entirely (no file written); user runs it against a mostly-tool-call session and the resulting file has a `low_signal` tag; against a clearly multi-topic session, a `multi_topic` tag.
5. User simulates a malformed JSON label response and the skill falls back to the Phase 1 stub label (`title = first 8 words of first user message`) and still writes the file — the run never crashes.
6. The skill file at `~/.claude/skills/sync-chats/SKILL.md` has the correct frontmatter (`name`, `description`, `disable-model-invocation: true`, `allowed-tools` whitelist, `argument-hint`) and is discoverable by Claude Code.
   **Plans**: TBD
   **UI hint**: no

### Phase 3: PII Scrub Integration + Crash Safety Polish

**Goal**: User can send a canary file full of synthetic credentials through the full pipeline and grep the resulting vault file for any canary — finding zero matches — because the `load → scrub → label → write` ordering is enforced by code structure, the canary test is a CI gate, and the `auto_label_hash` sentinel makes the "never touch a chat twice" invariant defensible even against state-file loss and filename renames.
**Depends on**: Phase 1 (the `protect` audit outcome determines whether scrubbing lives in `claude-chat.py protect --scrub-content` or a new module) and Phase 2 (we need to know what labels look like before we scrub the inputs that feed them, because labels are the most-indexed surface)
**Requirements**: PRIV-01, PRIV-02, PRIV-03, PRIV-04, PRIV-05, PRIV-06
**Success Criteria** (what must be TRUE):

1. User plants a canary file at `tests/canary_session.jsonl` containing a fake email, fake JWT (`eyJ...`), fake GitHub PAT of each variant (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), fake AWS access key, fake Bearer token, fake basic-auth string, fake IPv4, fake IPv6, and fake US phone number; runs it through the pipeline; and `grep` over the resulting markdown + frontmatter returns zero hits for every canary.
2. The canary test is wired into CI and runs on every change to the scrub or label code thereafter (not a one-shot Phase 3 gate).
3. User invokes the pipeline with content that trips the "uncertain" scrub path and the resulting file is still written, with `needs_review: true` and `privacy_review: uncertain` in frontmatter (fail-open-with-flag; never refuses to write).
4. User inspects the scrub log at `~/.claude-chat/sync.log` after a scrub-heavy run and sees pattern names plus char counts only — zero matched substrings appear in the log.
5. User manually edits the body of an auto-labeled vault file, re-runs `sync_chats.py write <session_id>`, and the skill refuses to touch the file — the `auto_label_hash` sentinel detects the edit even though state.json still says "synced" and the filename is unchanged (clobber defense layer 3).
6. Reading the `sync_chats.py write` code path, a reviewer can see that `scrub()` is called before any label JSON is read or generated; the ordering is enforced by function structure, not a comment.
   **Plans**: TBD
   **UI hint**: no

### Phase 4: MemPalace Bulk-Mine Integration

**Goal**: User completes a sync run and MemPalace has ingested every PII-safe chat in the vault via one purpose-built bulk-mine shell-out, with the whole pipeline degrading gracefully to a warning (not an error) when the `mempalace` CLI is absent — so a second Mac without MemPalace installed still writes chats to the vault successfully.
**Depends on**: Phase 3 (vault chats must be PII-safe before MemPalace ingests them; MemPalace memories propagate further than vault files, so a PII leak into MemPalace is worse than a PII leak into the vault)
**Requirements**: MEM-01, MEM-02, MEM-03
**Success Criteria** (what must be TRUE):

1. User runs a sync that writes N new chats to the vault and the pipeline then shells out exactly once to `mempalace mine <vault>/Chats --mode convos --extract general` after the last chat is committed.
2. User runs the same sync on a Mac where the `mempalace` binary is not on `PATH` and the sync completes successfully with a warning in `sync.log` like `mempalace: command not found — skipping mine`; the vault files are still written.
3. User reads the sync summary output and sees a line reporting `mempalace_mined: true` / `false` / `skipped` so the MemPalace state of the run is visible at a glance.
   **Plans**: TBD
   **UI hint**: no

### Phase 5: SessionEnd Hook + Observability + Multi-Machine Onboarding

**Goal**: User finishes a Claude Code session on either Mac and, within seconds, the new chat appears in the vault without any manual action — with a structured `last_run.json`, a tailable `sync.log`, a `status` subcommand, and a short README that lets the second Mac be onboarded in under ten minutes.
**Depends on**: Phase 4 (the full pipeline including MemPalace must be working interactively before it is automated; automating a broken pipeline multiplies the blast radius of bugs)
**Requirements**: HOOK-01, HOOK-02, HOOK-03, HOOK-04, HOOK-05, OBSERV-01, OBSERV-02, OBSERV-03, OBSERV-04
**Success Criteria** (what must be TRUE):

1. User ends a Claude Code session and within seconds a new file appears in `<vault>/Chats/` — no manual invocation needed. The SessionEnd hook in `~/.claude/settings.json` fires `python3 ~/.claude-chat/sync_chats.py --once` automatically.
2. User runs `/sync-chats` interactively at any time (the manual escape hatch from Phase 2) and the same pipeline runs for ad-hoc catch-up.
3. User `tail -f ~/.claude-chat/sync.log` during a run and sees timestamped entries for run start, each session processed, errors (if any), and run finish.
4. User `cat ~/.claude-chat/last_run.json` after a run and sees a machine-readable record of the most recent run's stats (timestamps, counts, status, mempalace_mined).
5. User runs `python3 ~/.claude-chat/sync_chats.py status` and sees a human-formatted summary backed by `last_run.json` (machine label, last run time, synced/pending counts, mempalace state).
6. User reads the end-of-run summary line and sees `Synced N new chats, M skipped (already synced), K flagged for review, mempalace_mined: <status>`.
7. A new user (the second Mac) follows the onboarding README and, in under ten minutes, has `sync_chats.py` installed at `~/.claude-chat/`, the SessionEnd hook installed in `~/.claude/settings.json`, a machine label set via `sync_chats.py init --label studio`, and a first successful sync completed.
   **Plans**: TBD
   **UI hint**: no

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase                                                         | Plans Complete | Status      | Completed |
| ------------------------------------------------------------- | -------------- | ----------- | --------- |
| 1. Scanner + State + Stub-Label Write Pipeline                | 0/4            | Planning    | -         |
| 2. SKILL.md + AI Labeling                                     | 0/TBD          | Not started | -         |
| 3. PII Scrub Integration + Crash Safety Polish                | 0/TBD          | Not started | -         |
| 4. MemPalace Bulk-Mine Integration                            | 0/TBD          | Not started | -         |
| 5. SessionEnd Hook + Observability + Multi-Machine Onboarding | 0/TBD          | Not started | -         |

---

_Roadmap created: 2026-04-10 from research-synthesis phase convergence (SUMMARY.md §5). 40 requirements across CORE/LABEL/PRIV/MEM/HOOK/OBSERV mapped to 5 phases. Granularity: coarse (5 phases). All 40 requirements mapped; zero orphans._
