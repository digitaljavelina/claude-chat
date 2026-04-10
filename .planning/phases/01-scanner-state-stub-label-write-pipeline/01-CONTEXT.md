# Phase 1: Scanner + State + Stub-Label Write Pipeline - Context

**Gathered:** 2026-04-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a stdlib-only Python helper `~/.claude-chat/sync_chats.py` with subcommands `init`, `scan`, `write`, `status` that detects new/changed Claude Code sessions in `~/.claude/projects/` on one Mac and emits properly-named, correctly-framed markdown files into the Obsidian vault `Chats/` folder. Phase 1 ships only the _deterministic, non-AI_ pipeline: stub labels, three-layer clobber defense, atomic state, iCloud startup assertion, and the `protect` audit. No Claude Code skill, no real AI labeling, no PII scrubbing patterns, no MemPalace shell-out, no SessionEnd hook — all downstream.

The exit criterion is that Michael can run the nine success-criteria commands from ROADMAP.md §Phase 1 by hand, in order, and observe the exact expected outcomes — including running `write` twice on the same session and getting `skipped: already_synced` the second time, and deleting `state.json` and still having the refuse-on-exists defense hold.

</domain>

<decisions>
## Implementation Decisions

### A — Label input contract for `write` (LABEL-09 seam)

- **D-01:** `sync_chats.py write <session_id>` receives label data as **JSON on stdin** only. No `--labels-json path` flag, no individual `--title`/`--gist`/`--tags` flags. Example: `echo '{"title":"...","gist":"...","tags":[...]}' | sync_chats.py write <uuid>`.
- **D-02:** Schema (Phase 1 minimum): `{title: str, gist: str|null, tags: list[str], coherence_score: int|null, needs_review: bool}`. Unknown keys are ignored (forward-compat for Phase 2 adding fields). Missing `title` is a fatal error for that session.
- **D-03:** Phase 1 has a tiny internal stub generator that builds this JSON dict and feeds it through the **same stdin path** the Phase 2 skill will use. There is no "stub-only" code path in `write`; `write` only knows how to read labels from stdin. This makes LABEL-09 a real contract, not a flag.

### B — Stub label shape (Phase 1's only label source)

- **D-04:** Stub `title` = first 8 words of the first user message in the session, joined with single spaces, stripped of leading/trailing whitespace. Mirrors LABEL-08's fallback so Phase 1 and the Phase 2 fallback share one implementation.
- **D-05:** Stub `gist` = `null`. Stub `tags` = `["stub"]`. Stub `coherence_score` = `null`. Stub `needs_review` = `true`. Frontmatter still includes all fields (nulls allowed as empty YAML values) so Phase 1 and Phase 2 files have a consistent schema that Dataview queries can rely on.
- **D-06:** If the session has no user message at all (edge case: parsing error, empty JSONL), stub title falls back to `"Untitled {session_short_id}"` where `session_short_id` is the first 8 chars of the UUID. Never refuse a session on label-generation grounds — the clobber-refusal path is only for write-time collisions.

### C — Scanner discovery path

- **D-07:** `sync_chats.py scan` walks `~/.claude/projects/` directly using `pathlib.Path.rglob("*.jsonl")` plus `.stat()`. Zero subprocess calls to `claude-chat.py` during scan.
- **D-08:** `scan` emits a JSON array on stdout: `[{"session_id": uuid, "project": proj_dir_name, "path": abs_path, "mtime": float, "size": int}, ...]`, sorted by `mtime` ascending (oldest first) so catch-up runs process in chronological order. Only sessions _not_ in `state.synced_session_ids` AND with (mtime, size) different from the cached fingerprint are included.
- **D-09:** Session discovery stays a tiny self-contained function (~20 lines). This decision explicitly accepts the small duplication of logic with `claude-chat.py`'s discovery, in exchange for keeping `sync_chats.py` independently runnable and testable even if `claude-chat.py` is mid-refactor.

### D — Delta detection tiering

- **D-10:** Phase 1 uses **mtime + size only**. No hash fallback, no fingerprints file. The per-session fingerprint stored in `state.json` is `{"mtime": float, "size": int}`.
- **D-11:** "Changed" means `(mtime, size)` differs from the last recorded fingerprint OR the session is brand new (no fingerprint recorded). False positives from mtime-only diffing are acceptable because the three-layer clobber defense at `write` time refuses re-writes regardless.
- **D-12:** Hash-based delta detection is **deferred to v2** (see REQUIREMENTS.md §v2). Phase 1 does not create a `fingerprints.json` or any separate cache file.

### E — Slug generation rules

- **D-13:** Slug = `unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()`, then replace any run of characters not in `[a-z0-9]` with a single `-`, strip leading/trailing `-`, truncate to **60 characters** (at a word boundary if possible — i.e. truncate then rstrip `-`).
- **D-14:** If slug is empty after normalization (title was all non-ASCII or all punctuation), fall back to the short session id (first 8 chars of UUID).
- **D-15:** Collision handling: if `<machine>--YYYY-MM-DD--<slug>.md` already exists in the vault, append `-2`, then `-3`, etc., until a free name is found. The collision check reuses the same filesystem refuse-on-exists path as clobber defense layer 2 — no separate code path.

### F — `protect` audit outcome

- **D-16:** **Audit complete.** `cmd_protect()` in `claude-chat.py` (line 821) only sets `cleanupPeriodDays = 99999` in `~/.claude/settings.json`. It does **not** touch session content, does not scrub PII, and does not read any JSONL.
- **D-17:** Phase 1 does **not** add `protect --scrub-content`. The finding is documented in this CONTEXT.md (here) and in a short note appended to the phase directory (`01-PROTECT-AUDIT.md`) that future phases can cite. Phase 1's stub-label pipeline writes raw (unscrubbed) exports to the vault.
- **D-18:** Scrubbing is deferred to **Phase 3** (PRIV track), which will add both the `protect --scrub-content` stdin/stdout mode AND the generic credential/email/IP patterns together, alongside the PRIV-04 canary test. Phase 3 inherits CORE-12 as its entry task.
- **D-19:** **Caveat for Phase 1 users:** because no scrubbing happens yet, Phase 1 files land in the vault in raw form. This is acceptable because Phase 1 is a single-machine, manually-invoked pipeline gated behind `sync_chats.py write <uuid>` — the user is explicitly in the loop for every file. The SessionEnd hook (Phase 5) is NOT installed until after Phase 3 lands scrubbing.

### G — Vault path configuration

- **D-20:** `sync_chats.py init --label <short_label> --vault <absolute_path>` is the one-shot setup command. Both flags are required on first invocation.
- **D-21:** `config.json` schema: `{"schema_version": 1, "machine_label": str, "vault_path": str}`. Written atomically (tmp + fsync + rename).
- **D-22:** If `init` is re-run with new values, overwrite silently. If `init` is run without flags and config already exists, print the current config and exit 0. If any other subcommand (`scan`, `write`, `status`) runs before `init`, refuse with a clear message telling the user to run `init` first.
- **D-23:** The iCloud startup assertion (CORE-04) applies to `~/.claude-chat/` _only_. The vault path is expected to be in iCloud and is not subject to the assertion.

### H — Write atomicity and cursor semantics

- **D-24:** Write ordering per session: (1) render markdown body + frontmatter to a `bytes` buffer in memory; (2) compute `auto_label_hash = sha256(body_bytes).hexdigest()` and inject into frontmatter; (3) write to `<target>.tmp`; (4) `fsync(fd)` then `os.replace(tmp, target)`; (5) append session_id + fingerprint to in-memory state; (6) atomic-rewrite `state.json` (same tmp+fsync+rename pattern) with `.bak` kept as the previous version.
- **D-25:** If the process crashes between step 4 and step 6, the vault has the file but state doesn't know. On the next run, `scan` will re-emit the session (mtime+size still "dirty" because state has no fingerprint for it), `write` will be re-attempted, and **clobber defense layer 2 (refuse-on-exists) catches it**. Phase 1 adds a one-line reconcile: when refuse-on-exists triggers, check whether the existing file's `auto_label_hash` matches what we _would_ have written; if yes, treat as "already synced" and update state to record the fingerprint. This closes the crash-window loop without ever re-writing content.
- **D-26:** `state.json` is rewritten once **per session**, not batched at end of run. Phase 1 optimizes for crash-safety over throughput. Catch-up runs on hundreds of sessions will do hundreds of fsyncs; acceptable because this is the ceiling (v1) and user-facing latency is dominated by the export subprocess, not state flushes.

### I — Test strategy

- **D-27:** Two test vehicles, both stdlib-only:
  - `tests/test_sync_chats.py` using `python -m unittest`. Covers pure functions (slug generator, first-user-message extractor, delta fingerprint comparison, frontmatter renderer) and the clobber defenses individually.
  - `tests/phase1_canary.sh` — a bash script that walks the 9 success criteria from ROADMAP.md end-to-end against a temp vault and a temp `~/.claude-chat/` (override via env var `CLAUDE_CHAT_HOME`). Expected output is asserted with `grep`.
- **D-28:** Both are runnable with zero external dependencies: `python3 -m unittest discover tests` and `bash tests/phase1_canary.sh`. Neither requires pytest, neither adds a line to any dep file.
- **D-29:** `sync_chats.py` exposes a `CLAUDE_CHAT_HOME` env var override for the `~/.claude-chat/` path to make the canary script testable without polluting the real user dir. The iCloud startup assertion still runs against whatever `CLAUDE_CHAT_HOME` resolves to, so the canary can also negative-test the assertion by pointing it at a fake iCloud path.

### J — Error handling and exit codes

- **D-30:** `write` is wrapped per-session: any exception during a single session's write is logged with `{session_id, error_class, error_message}`, a failure counter is incremented, and the loop continues to the next session. No single bad session blocks the run.
- **D-31:** Exit code policy: `0` if all sessions succeeded (or were correctly skipped), `1` if any session failed, `2` for pre-flight errors (no config, iCloud assertion violation, unreachable vault dir). Phase 5's SessionEnd hook relies on exit code visibility, so silent-success-on-failure is explicitly rejected.
- **D-32:** Summary line at end of every run, to stdout: `Synced N new, M skipped (already synced), K failed. See ~/.claude-chat/sync.log for details.` Phase 1 uses this even though OBSERV is nominally a separate track, because `status` (CORE-13) needs something to display.
- **D-33:** `~/.claude-chat/sync.log` is appended to on every run with an ISO timestamp and the summary line. Phase 1 does not rotate it; log rotation is deferred.

### Claude's Discretion

The planner and executor have freedom on:

- Internal function naming and module layout within `sync_chats.py` (keep it single-file).
- Exact frontmatter YAML emitter (write it by hand — no `pyyaml` dependency). Style: block form, keys in stable order, tags as a YAML list.
- Exact error message wording, provided the failure mode (per D-31) is preserved.
- Whether to factor pure functions (slug, extractor, renderer) into module-level helpers or keep inline — optimize for beginner readability with inline comments explaining stdlib idioms.
- Whether the `needs_review` frontmatter field is literal boolean `true` (YAML) or string `"true"` — pick one and document in-file.
- The precise text of the `01-PROTECT-AUDIT.md` summary, provided it records: (1) the audit finding, (2) the file path + line number, (3) that Phase 3 owns the fix.

</decisions>

<specifics>
## Specific Ideas

- "The three-layer clobber defense is already a safety net" — this is the reason D-10 (mtime+size-only delta detection) is acceptable. Weak upstream detection is fine _because_ downstream is strong. Downstream agents should not try to strengthen delta detection in Phase 1 on the grounds that "false positives might happen" — false positives are by design harmless here.
- "LABEL-09 is a contract, not a flag" — D-01..D-03. There is no Phase 1-only code path in `write` that generates labels inside the function. Phase 1 builds a dict externally and pipes it to stdin, exactly like Phase 2 will. Any planner instinct to add a `--stub` flag to `write` is a Phase 1↔2 coupling bug and should be rejected.
- Michael is a Python beginner. Planned code should err toward readable stdlib idioms over clever abstractions, with inline comments explaining non-obvious stdlib usage (`unicodedata.normalize`, `os.replace`, `pathlib.rglob`, `json.dumps(sort_keys=True)`, `shutil.copy2` for the `.bak` fallback, etc.).
- The canary script (D-27) is the executable expression of the nine success criteria. If the canary passes, Phase 1 is done. If a criterion is untestable via the canary, either the criterion is wrong or the design is wrong — do not relax the canary to match the code.

</specifics>

<canonical_refs>

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level

- `.planning/PROJECT.md` — Vision, Core Value, Active scope, Out of Scope, Constraints, and the Key Decisions table (many Phase 1 constraints originate here)
- `.planning/REQUIREMENTS.md` §CORE — CORE-01 through CORE-13 are Phase 1's acceptance criteria (deterministic pipeline layer)
- `.planning/REQUIREMENTS.md` §LABEL — specifically LABEL-08 (stub fallback) and LABEL-09 (Phase 1↔2 boundary)
- `.planning/ROADMAP.md` §"Phase 1: Scanner + State + Stub-Label Write Pipeline" — the nine success criteria
- `.planning/STATE.md` — current project state, milestone progress

### Codebase map (already generated)

- `.planning/codebase/ARCHITECTURE.md` — `claude-chat.py` layering (data model → discovery → commands → exporters → web UI)
- `.planning/codebase/CONVENTIONS.md` — existing code style, patterns, stdlib idioms used
- `.planning/codebase/STRUCTURE.md` — file layout, where to add `sync_chats.py`
- `.planning/codebase/STACK.md` — Python 3 stdlib only, zero deps invariant
- `.planning/codebase/TESTING.md` — testing strategy reference (informs D-27/D-28)
- `.planning/codebase/CONCERNS.md` — known issues
- `.planning/codebase/INTEGRATIONS.md` — subprocess boundary (why `import claude_chat` is blocked)

### Research (pre-Phase-1)

- `.planning/research/SUMMARY.md` — synthesized research convergence that set the 5-phase roadmap
- `.planning/research/ARCHITECTURE.md` — three-tier split (SKILL.md + sync_chats.py + claude-chat.py)
- `.planning/research/PITFALLS.md` — headless mode / scrub ordering / clobber defense failure modes
- `.planning/research/FEATURES.md` — feature decomposition by phase
- `.planning/research/STACK.md` — stdlib-only rationale

### Source to modify in Phase 1

- `claude-chat.py` — `cmd_export` at line 479 (needs `--stdout` flag added for CORE-11, backwards-compatible); `cmd_protect` at line 821 (audit target for CORE-12 — confirmed NOT a content scrubber)
- `claude-chat.py` — `export_markdown` at line 854 (understand current format so `--stdout` renders identically)

### No external ADRs

This project has no ADR directory. All decisions live in `.planning/PROJECT.md` §Key Decisions and the phase-level CONTEXT.md files.

</canonical_refs>

<code_context>

## Existing Code Insights

### Reusable Assets

- **`claude-chat.py` session discovery** — already knows how to enumerate `~/.claude/projects/*/*.jsonl`. Phase 1 deliberately does NOT import or subprocess this (D-07/D-09); instead, `sync_chats.py` walks the tree itself in ~20 lines of stdlib code. The discovery logic is simple enough that re-implementation is cheaper than coupling.
- **`claude-chat.py` export_markdown** (line 854) — produces the markdown body that Phase 1 wraps in YAML frontmatter. Phase 1 invokes `python3 claude-chat.py export <uuid> --format markdown --stdout` via `subprocess.run(capture_output=True, check=True)` and treats stdout as the body.
- **`claude-chat.py` atomic-write pattern** — `cmd_protect` (line 821) already demonstrates the tmp+rename idiom Michael's codebase uses (`SETTINGS_FILE.with_suffix(".tmp"); ...; tmp.replace(SETTINGS_FILE)`). Phase 1's `state.json` and `config.json` writers mirror this exactly, with an added `fsync` between write and rename for durability across crashes.

### Established Patterns

- **Zero external dependencies** — enforced by existing code and architectural commitment. `sync_chats.py` follows the same rule. All YAML emission is hand-rolled; no `pyyaml`.
- **Single-file Python CLI** — `claude-chat.py` is one ~1500-line file organized by section comments. `sync_chats.py` follows the same shape: ~300-500 lines, section-commented, no sub-package.
- **Subcommand via argparse subparsers** — already how `claude-chat.py` routes commands. `sync_chats.py` uses the same idiom for `init`/`scan`/`write`/`status`.

### Integration Points

- **New `export --stdout` flag** on `claude-chat.py`'s `cmd_export` (CORE-11) — backwards-compatible; when present, skip the file-write path and emit the rendered format to stdout. Small change in `cmd_export` (line 479) + argparse registration.
- **Subprocess boundary** — `sync_chats.py` shells out to `python3 claude-chat.py export --stdout` with `subprocess.run(check=True, capture_output=True, text=True)`. Never `import`, never `runpy`. The hyphen in the filename is a natural enforcement mechanism for this boundary.
- **`~/.claude-chat/` directory** is a new thing Phase 1 creates on first `init`. Nothing in the existing codebase references it yet; Phase 1 is introducing it.

</code_context>

<deferred>
## Deferred Ideas

The following came up while framing Phase 1 but explicitly belong to later phases. Captured here so they're not lost and future-me doesn't re-discover them:

- **Hash-based delta detection fallback** — deferred from D-10/D-12. Move to v2 requirements if mtime-only produces false positives in practice.
- **Fingerprints cache file** (`~/.claude-chat/fingerprints.json`) — unnecessary in Phase 1 because fingerprints live inline in `state.json` per-session. Revisit if hash fallback is added.
- **`protect --scrub-content` stdin/stdout mode** — deferred to Phase 3 (D-18). Phase 3 inherits CORE-12 as its entry task and owns both the flag and the patterns.
- **Scrub ordering enforcement (`scrub → label → write`)** — locked in PROJECT.md but not exercised in Phase 1 because no scrubbing happens yet. Phase 3 will add the explicit ordering check plus the PRIV-04 canary test.
- **`sync_chats.py --once` batch mode** — the future SessionEnd hook entry point. Phase 1 supports single-session `write <uuid>`; the `--once` flag that means "scan then write-all" is deferred to Phase 5 when it's actually needed. Phase 2 will use `scan` + `write` in a loop from inside SKILL.md.
- **MemPalace bulk-mine shell-out** — deferred to Phase 4. Phase 1 `write` never invokes `mempalace`.
- **`sync_chats.py log` subcommand** — tail/view of `~/.claude-chat/sync.log`. Deferred; for Phase 1 the user can `cat ~/.claude-chat/sync.log` directly.
- **Log rotation for `sync.log`** — not in Phase 1 (D-33). Likely never needed for a personal tool but revisit if the file grows past ~10MB.
- **`coherence_score` in stub labels** — Phase 1 writes `null`. Phase 2 populates it from Claude's response.
- **Interactive review queue** — explicitly rejected in PROJECT.md; Obsidian Dataview handles this via `WHERE needs_review`.
- **`export --stdout` for formats other than markdown** — Phase 1 only needs markdown. Whether `--stdout` should also work for html/txt/tex is a nice-to-have that can be tackled when implementing CORE-11 if it's ~zero extra lines; otherwise defer.

</deferred>

---

_Phase: 01-scanner-state-stub-label-write-pipeline_
_Context gathered: 2026-04-10 via /gsd-discuss-phase 1_
