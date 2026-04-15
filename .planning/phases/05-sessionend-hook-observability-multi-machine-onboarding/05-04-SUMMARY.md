---
phase: 05-sessionend-hook-observability-multi-machine-onboarding
plan: 04
subsystem: infra
tags: [python, cli, yaml-parser, sentinel-guard]

requires:
  - phase: 05-01
    provides: stub-sentinel write path (auto_label_hash_override = "stub")
  - phase: 05-02
    provides: cmd_once writing stub files to vault on SessionEnd
  - phase: 01-vault-write-pipeline
    provides: emit_frontmatter, _read_frontmatter_field, _read_auto_label_hash
  - phase: 02-ai-labeling
    provides: label JSON contract (title, gist, tags, coherence_score, needs_review)
provides:
  - cmd_relabel subcommand (D-05 sentinel-guarded, frontmatter-only rewrite)
  - _split_frontmatter_and_body helper (minimal YAML parser matching emit_frontmatter output)
  - SKILL.md Step 3a — interactive upgrade-stub-labels loop (per-user file, checkpoint-completed)
affects: [05-05-readme]

tech-stack:
  added: []
  patterns:
    - "Sentinel-only guard: never re-label a file whose auto_label_hash is anything other than literal 'stub' (D-05)"
    - "Frontmatter-only rewrite: body bytes byte-identical across relabel; scrub never re-runs"
    - "Atomic bytes write: tmp → fsync → .bak copy → rename, mirrors _write_atomic discipline"

key-files:
  created:
    - tests/test_phase5_relabel.py
  modified:
    - sync_chats.py
    - ~/.claude/skills/sync-chats/SKILL.md (per-user, not in repo)

key-decisions:
  - "cmd_relabel REFUSES with exit 1 on any non-stub auto_label_hash — never needs_review-driven, D-05 enforcement"
  - "_split_frontmatter_and_body is a minimal YAML parser (strings, ints, bools, null, block lists) matching emit_frontmatter's output — no pyyaml dependency"
  - "Relabel preserves filename (only rewrites frontmatter); original stub slug survives"
  - "SKILL.md Step 3a inserted between Step 3 (summary) and Step 4 (mine), reusing Step 2c labeling prompt on the already-rendered body"

patterns-established:
  - "Stub → real hash upgrade: new_hash = sha256(body_bytes).hexdigest(); sentinel 'stub' → 64-char hex marks 'reviewed by AI'"
  - "Atomic bytes write pattern: `with open(tmp, 'wb') as f: f.write(fm); f.write(body); f.flush(); fsync`; `shutil.copy2(target, bak)`; `os.replace(tmp, target)`"

requirements-completed:
  - HOOK-04

duration: ~35min (code) + 5-stub live smoke test
completed: 2026-04-15
---

# Phase 05-04 Summary

**Added `relabel <session_id>` subcommand with D-05 stub-sentinel guard — rewrites ONLY frontmatter on stub-labeled vault files, preserves body bytes byte-identically, upgrades `auto_label_hash` from "stub" to real SHA-256, flips `needs_review` to false. Plus SKILL.md Step 3a interactive upgrade loop.**

## Performance

- **Duration:** ~35 min code + 5 live relabels
- **Tasks:** 3 (TDD: RED → GREEN + human checkpoint)
- **Files modified:** 2 (1 production, 1 test) + 1 per-user SKILL.md
- **Tests added:** 9 (208 total, +9 from 199 baseline)

## Accomplishments

- `cmd_relabel(args)` — ~60 lines. Reads label JSON from stdin (same D-01/D-02 contract as `write`), locates the vault file by scanning Chats/ frontmatter for matching `session_id`, enforces the D-05 sentinel guard (`auto_label_hash == "stub"`), rebuilds frontmatter via `emit_frontmatter` preserving all non-label fields, and writes atomically with `.bak` preservation.
- `_split_frontmatter_and_body(path) -> (dict, bytes)` — ~55-line minimal YAML parser matching `emit_frontmatter`'s output shape. Handles scalars (str/int/bool/null), block lists (`  - item`), and json-quoted strings. Body is returned as raw bytes so the SHA-256 hash is stable across encodings.
- argparse: `relabel <session_id>` subparser registered in `main()`; confirmed via `python3 sync_chats.py --help`.
- SKILL.md Step 3a inserted between Step 3 (summary) and Step 4 (mine). Candidate discovery via `grep auto_label_hash: stub` over Chats/\*.md, then per-stub Read body → Step 2c labeling prompt → pipe JSON to `sync_chats.py relabel`.
- **Live smoke test 2026-04-15:** 5 real-signal stubs relabeled from the 657-stub cohort left by the morning's `--once` bulk run. All 5 `auto_label_hash` fields flipped from `stub` → 64-char hex; body bytes verified unchanged; filenames preserved.

## Task Commits

1. **Task 1: RED tests for cmd_relabel (9 tests)** — `c417643` (test)
2. **Task 2: GREEN cmd_relabel + argparse** — `f78d22f` (feat)
3. **Task 3: SKILL.md Step 3a checkpoint** — user-approved 2026-04-15 after 5-stub live smoke test (0 refused, 0 failed)

## Files Created/Modified

- `sync_chats.py` — Added `_split_frontmatter_and_body` + `cmd_relabel` below `cmd_once`; registered `relabel` subparser.
- `tests/test_phase5_relabel.py` — 9 tests across 5 classes: happy path (upgrades stub → real hash, body untouched), refuse (real hash, needs_review-true-but-real, file missing), stdin input (reads label, missing title fatal), frontmatter-only (scrub not re-run), argparse registered.
- `~/.claude/skills/sync-chats/SKILL.md` — Step 3a inserted (per-user file, not in repo).

## Decisions Made

- **`_split_frontmatter_and_body` as inline helper rather than full YAML library.** The file shape is strictly controlled by `emit_frontmatter` — we only need to parse what that function writes. 55 lines of hand-rolled parsing vs a pyyaml dependency and PROJECT.md's zero-deps invariant wins.
- **Body extracted as raw bytes, not text.** The SHA-256 hash in `auto_label_hash` is computed over body bytes. Decoding → re-encoding would be lossless in practice but theoretically risks encoding drift; bytes round-trip guarantees hash stability.
- **First-match-wins on session_id collision.** If two vault files share a `session_id` (edge case — should never happen, but `agent-*` prefixes + slug suffixes theoretically allow it), `cmd_relabel` warns on stderr and uses the first match. Test `T-05-04-03` documents this as a Spoofing-mitigation choice.
- **SKILL.md Step 3a reuses Step 2c labeling prompt** — the body is already the rendered session export, so the labeler sees the same content whether labeling fresh (Step 2) or upgrading a stub (Step 3a). One prompt, two callers, identical output format.

## Deviations from Plan

### Auto-fixed Issues

**1. `_split_frontmatter_and_body` list-append crash on first call**

- **Found during:** Task 2 GREEN run (immediately after implementation)
- **Issue:** Seeded `fields[key] = None` when encountering a bare `key:` line (could be null OR start of block list). Then on first `  - item` line, `fields.setdefault(current_list_key, []).append(...)` returned `None` (because the key was already set to `None`), raising `AttributeError: 'NoneType' object has no attribute 'append'`.
- **Fix:** Check `isinstance(fields.get(current_list_key), list)` first; replace `None` with `[]` before appending. One-line correction.
- **Files modified:** `sync_chats.py`
- **Verification:** `pipx run pytest tests/test_phase5_relabel.py -v` → 9/9 pass
- **Committed in:** `f78d22f` (bundled with Task 2 GREEN)

---

**Total deviations:** 1 auto-fixed (parser edge case).
**Impact on plan:** None on scope — the `setdefault` idiom assumed `fields[key]` was unset; seeding it as `None` broke that assumption. The fix is a 2-line defensive check.

## Issues Encountered

None beyond the deviation above. D-05 guard worked first time; body-bytes preservation verified via test `test_body_is_untouched` that computes sha256 before/after.

## Next Phase Readiness

- Plan 05 (README) can now show a realistic end-to-end flow: SessionEnd hook fires → `--once` stub-writes → user runs `/sync-chats` → SKILL's Step 3a upgrades stubs via `relabel`.
- The SKILL's Step 3a loop works interactively but is slow for large backlogs (5 stubs × ~30 sec ≈ 2-3 min including deliberation). A future Plan 05-06 could add a batch-relabel helper that calls Haiku via Anthropic SDK for formulaic low-signal clusters (see `reference_vibe_log_stub_cluster.md` memory).
- 652 stubs remain in the vault awaiting relabel — operational work, not blocking phase completion.

---

_Phase: 05-sessionend-hook-observability-multi-machine-onboarding_
_Completed: 2026-04-15_
