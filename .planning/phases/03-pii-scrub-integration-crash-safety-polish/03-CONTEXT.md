# Phase 3: PII Scrub Integration + Crash Safety Polish - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Lock the `load → scrub → label → write` ordering by code structure (not comments), add generic credential/PII patterns covered by a canary CI gate, and harden the `auto_label_hash` sentinel so the "never touch a chat twice" invariant holds under state loss, filename renames, AND manual body edits.

Phase 3 inherits CORE-12 (the `protect` audit finding from Phase 1: `cmd_protect()` at `claude-chat.py:841` only flips `cleanupPeriodDays`, does NOT scrub content) and closes it by introducing scrub here — not as a `protect --scrub-content` mode on `claude-chat.py`, but as an in-process pure function in `sync_chats.py`.

Phase 3 does NOT add MemPalace integration (Phase 4), the SessionEnd hook (Phase 5), or clinical-specific PII patterns (explicitly out of scope per PROJECT.md). It does NOT rewrite the existing `cmd_write` flow — it inserts scrubbing between `_get_markdown_body`'s subprocess call and its return, and patches the crash-reconciliation branch to refuse manual-edit collisions.

The exit criterion: a user can plant a canary JSONL with 10+ synthetic credentials, run it through the full pipeline, `grep` the resulting markdown + frontmatter for every canary, and find zero matches — every time CI runs.

</domain>

<decisions>
## Implementation Decisions

### A — Where scrubbing lives (CORE-12 resolution)

- **D-01:** Scrubbing lives as a **pure in-process function in `sync_chats.py`** (or a new `scrub.py` module sibling — planner's call, see Claude's Discretion). It is NOT exposed as a `claude-chat.py protect --scrub-content` stdin/stdout mode. Rationale: `sync_chats.py` is the only caller; a second subprocess hop costs ~50-100ms per session × N sessions for zero functional benefit; keeping scrub in-process simplifies structural ordering enforcement (D-03).
- **D-02:** The `protect` mode on `claude-chat.py` is left unchanged. The audit note at `.planning/phases/01-scanner-state-stub-label-write-pipeline/01-PROTECT-AUDIT.md` remains the authoritative record that `cmd_protect` is a settings-only command. PROJECT.md's "possibly add `protect --scrub-content`" clause resolves to "not adding it — scrub lives in `sync_chats.py` instead."

### B — Structural enforcement of `scrub → label → write` ordering (PRIV-01, SC#6)

- **D-03:** Ordering is enforced by making `_get_markdown_body(session_id)` **internally call scrub before returning**. The raw (unscrubbed) body never escapes that function. Signature changes from `_get_markdown_body(session_id: str) -> str` to `_get_markdown_body(session_id: str) -> tuple[str, dict]` — the second element is the scrub stats dict (D-23). The tuple return is deliberate: it forces every caller to acknowledge stats exist (a caller that tries `body = _get_markdown_body(sid)` gets a TypeError at unpacking time, or silently assigns the tuple to `body` and immediately fails downstream string operations), making it structurally impossible to silently bypass the scrub-stats path.
- **D-04:** A code reviewer reading `cmd_write` sees `body, stats = _get_markdown_body(sid)` followed by `_log_scrub_stats(session_id, stats)` and then labeling / hashing / writing. The only way label generation could ever see unscrubbed content is if `_get_markdown_body` itself were broken — which the canary test (D-15) catches on every CI run. No `ScrubbedBody` wrapper class, no type gymnastics, no decorator — just function-boundary enforcement (scrub inside the function) plus tuple-unpacking (forces caller awareness of stats), matching Phase 1's D-07/D-09 ethos.
- **D-05:** `auto_label_hash` continues to be computed from the **body bytes that `_get_markdown_body` returns** — i.e., the scrubbed body. This means re-computing the hash on a stored file's scrubbed body deterministically reproduces the sentinel, so crash reconciliation (D-15) keeps working without knowledge of scrub internals.

### C — Uncertainty detection for `privacy_review: uncertain` (PRIV-05)

- **D-06:** `privacy_review: uncertain` is set in frontmatter when `scrub_content()` matches a high-entropy string that **did not match any known prefix pattern** but looks secret-shaped (e.g., a bare 32+ character base64 or hex run with no context). All known-pattern matches (email, JWT, GitHub tokens, etc.) are redacted without setting uncertain — those are high-confidence.
- **D-07:** When uncertain is set, `needs_review: true` is also forced on (overriding any label-supplied value of `false`). The chat is still written (fail-open-with-flag per PRIV-05); the flag makes it surface in Michael's existing Dataview "needs_review" inbox for manual audit.
- **D-08:** Frontmatter field `privacy_review` has three possible values: `"clean"` (no scrubs), `"scrubbed"` (known patterns hit, all redacted), `"uncertain"` (at least one high-entropy fallback hit). Always present — never omitted — so Dataview queries can filter reliably.

### D — Pattern coverage (PRIV-02, PRIV-03)

- **D-09:** Pattern set includes all canary-required patterns (PRIV-04, SC#1):
  - Email: RFC-5322-ish `[\w.+-]+@[\w.-]+\.[a-z]{2,}` (case-insensitive)
  - JWT: `eyJ[\w-]+\.[\w-]+\.[\w-]+`
  - GitHub tokens (6 variants): `gh[psuor]_[A-Za-z0-9]{36,}` and `github_pat_[A-Za-z0-9_]{82,}`
  - AWS access key: `(AKIA|ASIA)[A-Z0-9]{16}`
  - Bearer tokens: `Bearer\s+[A-Za-z0-9_.\-=]+`
  - Basic auth: `Basic\s+[A-Za-z0-9+/=]+`
  - IPv4: standard dotted-quad (with skip rule per D-10)
  - IPv6: RFC-4291 full and compressed forms (with skip rule per D-10)
  - US phone: `\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}`
- **D-10:** **Skip-list for IPs:** do NOT redact `127.0.0.1`, `::1`, `10.*.*.*`, `192.168.*.*`, `172.(16-31).*.*`, `169.254.*.*`, and `fe80::/10` link-local. These are RFC-1918 private / loopback / link-local addresses and redacting them makes debug logs useless without leaking anything sensitive.
- **D-11:** Include these extras beyond the canary list (cheap, common-in-vibe-coding leaks):
  - Slack tokens: `xox[bpoa]-[\d]{10,}-[\d]{10,}-[A-Za-z0-9]{24,}`
  - Stripe keys: `sk_live_[A-Za-z0-9]{24,}` (test keys `sk_test_` also included for symmetry)
  - OpenAI keys: `sk-[A-Za-z0-9]{40,}` when not matching `sk-ant-`
  - Anthropic keys: `sk-ant-[A-Za-z0-9_-]{40,}`
  - Generic high-entropy fallback (D-06): any bare 32+ char `[A-Za-z0-9+/=_-]` run not already matched, not inside a markdown code fence comment, triggers `uncertain`.
- **D-12:** Replacement token format: `<REDACTED:pattern_name>` (e.g., `<REDACTED:jwt>`, `<REDACTED:email>`). Consistent, greppable, makes post-hoc auditing obvious. The replacement preserves char count information roughly but NEVER the original substring (PRIV-06).

### E — Canary test + CI gate (PRIV-04, SC#1, SC#2)

- **D-13:** The canary lives at `tests/canary_session.jsonl` and contains 13 synthetic secrets covering every pattern in D-09 plus D-11. Each secret uses obviously-fake but pattern-matching values (e.g., `ghp_FAKE000000000000000000000000000CANARY`) so a grep for `CANARY` should return zero hits after the pipeline runs.
- **D-14:** The canary test is a new file `tests/test_scrub_canary.py` runnable via `python3 -m unittest tests.test_scrub_canary`. It exercises the full pipeline end-to-end (scan → write via the normal stdin path) against a temp vault, then `grep`s the resulting markdown bytes for every canary substring. Any hit fails the test.
- **D-15:** **CI = GitHub Actions workflow.** Add `.github/workflows/canary.yml` that runs on `push` and `pull_request` when any of `sync_chats.py`, `scrub*.py`, or `tests/**` change. Runs `python3 -m unittest discover tests` (covers existing Phase 1/2 tests + new canary). Uses `setup-python@v5` with Python 3.12. This closes SC#2 ("canary test is wired into CI and runs on every change to the scrub or label code thereafter").
- **D-16:** The canary test is additionally referenced from `tests/phase1_canary.sh` as a dependency check so running that bash canary also validates scrub works. Keeps the success-criteria verification script honest without duplicating assertions.

### F — Manual-edit refusal + crash-reconciliation fix (SC#5, Crash Safety Polish)

- **D-17:** **Bug fix in existing code.** Current `cmd_write` at `sync_chats.py:858` treats any `_reconcile_crash` "collision" result as a slug collision and falls into the `-2`, `-3`, … naming fallback. That is wrong when the existing file belongs to the SAME session but was edited — per SC#5, the skill must **refuse** to write in that case, not create `<slug>-2.md`.
- **D-18:** Modify `_reconcile_crash` (or a new helper) to read `session_id` from the existing vault file's frontmatter (same scan pattern as `_read_auto_label_hash`). Return values become three-way: `"reconciled"` (same session, hash matches — update state), `"edited"` (same session, hash differs — REFUSE, log, skip), `"collision"` (different session, same slug — fall through to `-2`/`-3` loop as today).
- **D-19:** On `"edited"`: `cmd_write` logs `skipped: user_edited (auto_label_hash mismatch, session_id matches)` to `sync.log`, prints the same to stdout, adds the session_id to `synced_session_ids` (because we've now made a permanent decision never to touch it again — this is clobber defense layer 3 doing its job), updates fingerprint to the current mtime/size so scan stops re-emitting it, and returns 0 exit. The user's edits stay untouched, and no future run will rewrite over them.
- **D-20:** Distinguishing "same vs different session" requires reading `session_id` from frontmatter. Extend the `_read_auto_label_hash` pattern (or factor into a general `_read_frontmatter_field(path, key)` helper — planner's call) and keep the 30-line scan cap for efficiency.

### G — Scrub logging (PRIV-06)

- **D-21:** Scrub produces one log line per session written to `~/.claude-chat/sync.log`:
  `[<iso-ts>] scrub session=<short_id> patterns={email:3, jwt:1, ipv4:2} total_chars=287`
  where `short_id` is the first 8 chars of the UUID. Never include any matched substring. **Zero-count pattern entries are omitted from the `patterns={...}` dict** (e.g., if no JWTs were matched, `jwt:0` does NOT appear — keeps lines short and grep-friendly). The `uncertain` key appears only when `uncertain > 0`. Any log parser should treat absent keys as count=0.
- **D-22:** When a session has zero scrubs (`privacy_review: "clean"`), no scrub log line is emitted — reduces noise in `sync.log`. The summary line at end of run (inherited from Phase 1 D-32) already reports counts.
- **D-23:** Scrub stats are returned from `scrub_content()` as the second element of a `(scrubbed_text, stats_dict)` tuple. `cmd_write` logs them immediately after `_get_markdown_body` returns. `stats_dict` shape: `{pattern_name: count, ..., "uncertain": int, "total_chars_redacted": int}`.

### Claude's Discretion

The planner and executor have freedom on:

- Whether `scrub_content()` lives as a function in `sync_chats.py` or as a new single-file `scrub.py` module at the same directory level. Both are acceptable — optimize for readability. If `sync_chats.py` grows past ~1200 lines with scrub inlined, factor out.
- Exact regex pattern wording, provided each canary in D-09/D-11 is caught by the test. Hand-rolled `re.compile` patterns are fine — do NOT pull in a dependency like `detect-secrets` or `presidio` (violates zero-deps invariant).
- Whether to use `re.sub` with named groups, a list of `(name, pattern)` tuples iterated in order, or a dispatch dict. Beginner-readable wins; inline comments explaining any non-obvious regex syntax.
- The precise phrasing of CI workflow YAML, provided it runs `python3 -m unittest discover tests` and triggers on the file paths named in D-15.
- How to factor the "read frontmatter field" helper (D-20) vs extending `_read_auto_label_hash`. The 30-line cap and the `in_frontmatter`/`delimiter_count` pattern should be preserved either way.
- Whether to emit `privacy_review: clean` explicitly or elide it when clean (D-08 says always present; Dataview reliability argues for always-present).
- Ordering of pattern matches in `scrub_content()` — but JWT must match before generic high-entropy fallback (D-11), and GitHub/AWS/Slack/Stripe/OpenAI/Anthropic prefixes must match before the generic fallback, so that specific-named counts are accurate and uncertain is only set when truly uncertain.
- Extending `tests/phase1_canary.sh` vs. writing a new `tests/phase3_canary.sh` — either is fine; don't duplicate success-criteria assertions.

</decisions>

<specifics>
## Specific Ideas

- **"Labels are the most-indexed surface in Obsidian"** — this is the core reason scrub MUST happen before label generation, not alongside or after. Tag panes, Dataview, graph view, and full-text search all read frontmatter first. A JWT leaked into `tags:` would be searchable across the entire vault indefinitely. The function-boundary enforcement (D-03) exists specifically because this leak direction is irreversible — once the vault is iCloud-synced, redacting retroactively doesn't help.
- **The canary is the spec.** Any pattern that appears in the canary but isn't scrubbed is a bug. Any pattern that's scrubbed but isn't in the canary is untested. The canary file is small enough that adding a new secret type = adding one line to `canary_session.jsonl` + one pattern to `scrub_content()` + one assertion in the test. Keep that symmetry tight.
- **Private IPs are signal, not PII.** D-10's skip-list matters because debug chats routinely mention `localhost`, `192.168.1.1`, `::1`. Redacting them produces useless logs without protecting anything. The threat model is credentials and public identifiers, not private network topology.
- **The manual-edit bug at `sync_chats.py:858` is a latent Phase 1 defect, not new Phase 3 scope.** ROADMAP SC#5 already required this behavior; Phase 1 got 80% there (hash computation + reconcile helper) but the three-way branching in `cmd_write` wasn't finished. Phase 3 closes the gap — this is bug-fix territory, not feature work. Flag as such in the PR.
- **`<REDACTED:pattern_name>` over `\***`or`[REDACTED]`.** The named form makes post-hoc scrub auditing trivially greppable. If Michael ever wonders "did scrub catch the thing from that one session?", `grep -c REDACTED:jwt Chats/\*.md`answers it.`\*\*\*` loses that.
- Michael is a Python beginner — favor `re.compile(pattern, re.IGNORECASE)` at module level with a `# matches:` comment over inline `re.sub(r"...", ..., flags=re.I)` calls. Regex is already opaque; giving it a name and a comment is cheap learning scaffolding.

</specifics>

<canonical_refs>

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-level

- `.planning/PROJECT.md` — Vision, Core Value, Out of Scope (esp. the clinical-pattern exclusion), Constraints (privacy, zero-deps), Key Decisions (scrub ordering)
- `.planning/REQUIREMENTS.md` §PRIV — PRIV-01 through PRIV-06 are Phase 3's acceptance criteria
- `.planning/REQUIREMENTS.md` §CORE — CORE-10 (auto_label_hash sentinel) and CORE-12 (protect audit) — both carry into Phase 3
- `.planning/ROADMAP.md` §"Phase 3: PII Scrub Integration + Crash Safety Polish" — the six success criteria
- `.planning/STATE.md` — current project state

### Phase 1 context (upstream dependency — scrub hooks into the write pipeline)

- `.planning/phases/01-scanner-state-stub-label-write-pipeline/01-CONTEXT.md` — all 33 D-\* decisions. Especially D-16/D-17/D-18 (protect audit → scrub deferred to Phase 3), D-24 (write ordering where scrub inserts), D-25 (crash reconciliation, which Phase 3 extends)
- `.planning/phases/01-scanner-state-stub-label-write-pipeline/01-PROTECT-AUDIT.md` — the `cmd_protect` audit record (claude-chat.py:841 is settings-only)

### Phase 2 context (upstream — labels must see scrubbed bodies)

- `.planning/phases/02-skill-md-ai-labeling/02-CONTEXT.md` — D-01..D-14. Labels flow through `sync_chats.py write` stdin per LABEL-09. Phase 3 doesn't change SKILL.md; scrubbing happens before labels are generated because labels are generated from `_get_markdown_body()`'s return value.

### Source to read before planning

- `sync_chats.py` — `cmd_write` (line 732), `_get_markdown_body` (line 534) — scrub integration point; `_read_auto_label_hash` (line 564), `_reconcile_crash` (line 595) — manual-edit refusal fix point
- `claude-chat.py` — `cmd_protect` (line 841) — NOT modified in Phase 3; left alone per D-02

### Codebase maps

- `.planning/codebase/ARCHITECTURE.md` — layering
- `.planning/codebase/CONVENTIONS.md` — stdlib style
- `.planning/codebase/TESTING.md` — current test harness (stdlib unittest + bash canary)

### Research (pre-milestone)

- `.planning/research/PITFALLS.md` — scrub ordering failure modes, clobber defense failure modes

### No external ADRs

All decisions live in `.planning/PROJECT.md` §Key Decisions and the phase-level CONTEXT.md files.

</canonical_refs>

<code_context>

## Existing Code Insights

### Reusable Assets

- **`sync_chats.py` `_get_markdown_body()`** (line 534) — the chokepoint for scrub insertion. Currently shells out to `python3 claude-chat.py export --stdout` and returns the stdout. Phase 3 adds a single line: `body, stats = scrub_content(body)` between the subprocess call and the return, plus a `_log_scrub_stats(session_id, stats)` side effect.
- **`sync_chats.py` `_read_auto_label_hash()`** (line 564) — the 30-line frontmatter scanner pattern. Phase 3 either extends this to also read `session_id` or generalizes to `_read_frontmatter_field(path, key)`.
- **`sync_chats.py` `_reconcile_crash()`** (line 595) — returns `"reconciled"`/`"collision"` today; Phase 3 extends to three-way (`"edited"` added per D-18).
- **`sync_chats.py` `cmd_write()`** (line 732–898) — the `if not written:` branch at line 843 dispatches on reconcile result; Phase 3 adds the `"edited"` case before the slug-collision fallback at line 858.
- **`emit_frontmatter()`** (line 392) — adds the new `privacy_review` field to the stable key order so existing tests continue to work.
- **`_log_sync()`** (line 618) — scrub log lines piggyback on this existing sync-log writer.

### Established Patterns

- **Hand-rolled everything** — no `pyyaml`, no `detect-secrets`, no `regex` (pypi). `re` module only.
- **`re.compile(...)` at module top** — existing code pattern; follow for scrub patterns.
- **Per-session atomic state update** (D-26 from Phase 1) — scrub doesn't change this; the `synced_session_ids.append` + `save_state(state)` pattern at `cmd_write:878-884` handles the `"edited"` case too.
- **Frontmatter is always present, nulls are explicit** — D-05 from Phase 1; Phase 3's `privacy_review` field follows suit (always emitted, one of `clean`/`scrubbed`/`uncertain`).
- **Subprocess boundary only for `claude-chat.py`** — scrub runs in-process, no second subprocess hop.

### Integration Points

- **Scrub insertion:** inside `_get_markdown_body()` only. One call site.
- **Logging:** one new line per scrubbed session via `_log_sync()` (existing).
- **Frontmatter:** one new field (`privacy_review`) added to `emit_frontmatter()`'s dict and key-order list.
- **Crash reconciliation:** three-way result from `_reconcile_crash`, dispatched in `cmd_write` at the existing `if not written:` branch.
- **CI:** new top-level `.github/workflows/canary.yml` — the first CI workflow in this project. Minimal: checkout, setup-python, `python3 -m unittest discover tests`.

### Surface area of changes

- `sync_chats.py`: ~150 lines net added (patterns + scrub_content + stats type + frontmatter field + 3-way reconcile branch)
- `tests/test_scrub_canary.py`: new file, ~100 lines
- `tests/canary_session.jsonl`: new fixture, ~30 lines
- `.github/workflows/canary.yml`: new file, ~25 lines
- `claude-chat.py`: zero lines changed
- `~/.claude/skills/sync-chats/SKILL.md`: zero lines changed (scrub happens before SKILL.md sees the body)

</code_context>

<deferred>
## Deferred Ideas

- **`claude-chat.py protect --scrub-content` stdin/stdout mode** — originally hedged in PROJECT.md as "possibly add." Resolved in D-01/D-02: scrub lives in `sync_chats.py` only. If a future milestone ever needs one-shot scrubbing of a standalone markdown file, revisit.
- **`ScrubbedBody` typed wrapper class** — considered for stronger ordering enforcement. Rejected (D-03/D-04) in favor of function-boundary enforcement. Revisit if Python type checking becomes part of the project (e.g., mypy adopted).
- **Clinical-specific PII patterns** — NCT IDs, EU/JMA/chiCTR codes, drug-dose prose, internal Amgen URLs. Explicitly out of scope per PROJECT.md; do NOT add in Phase 3.
- **Second-pass LLM scrub** — was originally a clinical-edge-case mitigation. Not needed for generic PII; if ever reconsidered, it would be its own milestone.
- **Log rotation for `sync.log`** — deferred from Phase 1 D-33; scrub-log lines land in the same file. Still deferred; revisit if file exceeds ~10MB in practice.
- **Re-scrub on existing files** — a `/sync-chats rescrub` command to retroactively apply scrub patterns to already-written vault files. Explicitly rejected by the three-layer clobber defense invariant: once a chat is in the vault, the skill never touches it again. Michael can manually scrub old files in Obsidian if ever needed.
- **Fingerprint scrub rules** — remembering _which_ scrub pattern set was active when a file was written, so re-running with an updated pattern set could flag "this file was scrubbed under v1 patterns." Unnecessary: the canary-in-CI model keeps patterns growing forward, not retroactively.
- **Configurable scrub pattern list** — user-supplied extra regexes via `config.json`. YAGNI for a personal tool; the generic set in D-09/D-11 is exhaustive for Michael's use case.
- **Scrubbing the `title`/`gist`/`tags` fields themselves as a belt-and-suspenders check** — currently labels are generated AFTER scrub, so unscrubbed PII cannot reach them. Belt-and-suspenders scrubbing of the label JSON output would add a second defense but doubles scrub work. Deferred unless a canary failure ever shows a label leak.
- **`coherence_score` influence on scrub strictness** — e.g., apply stricter scrub to low-coherence sessions. Unnecessary; scrub is uniform.
- **`privacy_review: uncertain` triggering a Dataview-visible banner in the rendered markdown body** — could prepend a callout like `> [!warning] Privacy review pending`. Considered; not in scope. The frontmatter flag + `needs_review: true` already surfaces via existing Dataview queries.

</deferred>

---

_Phase: 03-pii-scrub-integration-crash-safety-polish_
_Context gathered: 2026-04-13 via /gsd-discuss-phase 3_
