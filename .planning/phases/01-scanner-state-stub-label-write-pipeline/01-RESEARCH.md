# Phase 1: Scanner + State + Stub-Label Write Pipeline — Research

**Researched:** 2026-04-13
**Domain:** Python stdlib-only CLI development, JSONL parsing, atomic file I/O, iCloud path detection
**Confidence:** HIGH (all major claims verified against live codebase and running system)

---

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

**A — Label input contract for `write` (LABEL-09 seam)**

- D-01: `write <session_id>` reads label JSON from **stdin only**. No flags.
- D-02: Schema minimum: `{title: str, gist: str|null, tags: list[str], coherence_score: int|null, needs_review: bool}`. Unknown keys ignored. Missing `title` is fatal.
- D-03: Phase 1 stub generator builds this dict and feeds it through the same stdin path Phase 2 will use. No stub-only code path in `write`.

**B — Stub label shape**

- D-04: Stub title = first 8 words of first user message.
- D-05: Stub gist = null, tags = ["stub"], coherence_score = null, needs_review = true.
- D-06: Fallback when no user message: `"Untitled {first_8_chars_of_uuid}"`. Never refuse on label-generation grounds.

**C — Scanner discovery path**

- D-07: `scan` uses `pathlib.Path.rglob("*.jsonl")` + `.stat()`. Zero subprocess calls.
- D-08: Output = JSON array sorted by mtime ascending. Only sessions not in `state.synced_session_ids` AND with changed (mtime, size) fingerprint.
- D-09: Discovery is a ~20-line self-contained function. Deliberate duplication with `claude-chat.py` accepted.

**D — Delta detection tiering**

- D-10: mtime + size only. No hash fallback.
- D-11: "Changed" = (mtime, size) differs from recorded fingerprint OR session is new.
- D-12: Hash-based detection deferred to v2.

**E — Slug generation rules**

- D-13: `unicodedata.normalize("NFKD", title).encode("ascii","ignore").decode("ascii").lower()`, then replace non-`[a-z0-9]` runs with `-`, strip leading/trailing `-`, truncate to 60 chars (rstrip `-` after truncation).
- D-14: Empty slug after normalization falls back to first 8 chars of UUID.
- D-15: Collision → append `-2`, `-3`, etc. Same filesystem check as clobber defense layer 2.

**F — `protect` audit outcome**

- D-16: `cmd_protect()` (line 821) only sets `cleanupPeriodDays = 99999`. Does NOT touch session content.
- D-17: Phase 1 does NOT add `protect --scrub-content`. Writes raw (unscrubbed) exports.
- D-18: Scrubbing deferred to Phase 3.
- D-19: Acceptable because Phase 1 is manually-invoked, user is in the loop.

**G — Vault path configuration**

- D-20: `init --label <label> --vault <abs_path>`. Both flags required on first invocation.
- D-21: config.json schema: `{"schema_version": 1, "machine_label": str, "vault_path": str}`. Atomic write.
- D-22: Re-run `init` with new values → overwrite silently. `init` with no flags + config exists → print and exit 0.
- D-23: iCloud assertion applies to `~/.claude-chat/` only, not vault path.

**H — Write atomicity and cursor semantics**

- D-24: Write order per session: (1) render body+frontmatter to bytes; (2) compute auto_label_hash = sha256(body_bytes).hexdigest(); (3) inject hash into frontmatter; (4) write to `<target>.tmp`; (5) fsync + os.replace(tmp, target); (6) append to in-memory state; (7) atomic-rewrite state.json with .bak kept.
- D-25: Crash between steps 4 and 6 → file exists but state doesn't know → next scan re-emits session → write attempted → refuse-on-exists fires → compare auto_label_hash → if match, treat as already_synced and update state.
- D-26: state.json rewritten once per session (not batched). Crash-safety over throughput.

**I — Test strategy**

- D-27: Two test vehicles — `tests/test_sync_chats.py` (python -m unittest) and `tests/phase1_canary.sh` (bash).
- D-28: Both stdlib-only: `python3 -m unittest discover tests` and `bash tests/phase1_canary.sh`.
- D-29: `CLAUDE_CHAT_HOME` env var overrides `~/.claude-chat/` for testability.

**J — Error handling and exit codes**

- D-30: Per-session exception catch, log and continue. One bad session never blocks the run.
- D-31: Exit 0 = all succeeded/skipped; exit 1 = any session failed; exit 2 = preflight error.
- D-32: Summary line to stdout: `Synced N new, M skipped (already synced), K failed. See ~/.claude-chat/sync.log for details.`
- D-33: Append to `~/.claude-chat/sync.log` with ISO timestamp. No rotation.

### Claude's Discretion

- Internal function naming and module layout within `sync_chats.py` (keep single-file).
- Exact YAML emitter style (hand-rolled). Block form, keys in stable order, tags as YAML list.
- Exact error message wording (preserve failure-mode semantics from D-31).
- Whether to factor pure functions inline or as module-level helpers — optimize for beginner readability with inline comments.
- Whether `needs_review` is literal YAML boolean `true` or string `"true"` — pick one and document in-file.
- Precise text of `01-PROTECT-AUDIT.md` (must record: audit finding, file path + line number, Phase 3 owns the fix).

### Deferred Ideas (OUT OF SCOPE for Phase 1)

- Hash-based delta detection fallback
- Fingerprints cache file
- `protect --scrub-content` stdin/stdout mode (Phase 3)
- Scrub ordering enforcement (Phase 3)
- `sync_chats.py --once` batch mode (Phase 5)
- MemPalace bulk-mine shell-out (Phase 4)
- `sync_chats.py log` subcommand
- Log rotation
- `coherence_score` population (Phase 2)
- Interactive review queue

</user_constraints>

---

<phase_requirements>

## Phase Requirements

| ID       | Description                                                                      | Research Support                                      |
| -------- | -------------------------------------------------------------------------------- | ----------------------------------------------------- | ------------ |
| CORE-01  | `scan` lists unsynced session UUIDs                                              | D-07/D-08: rglob, mtime+size delta, JSON array output |
| CORE-02  | `write <session_id>` creates named markdown in vault with YAML frontmatter       | D-20..D-26, frontmatter schema verified below         |
| CORE-03  | state.json written atomically (tmp+fsync+rename) with .bak                       | Verified: pattern works; see §Atomic State Write      |
| CORE-04  | Startup assertion: refuse if `~/.claude-chat/` resolves to Mobile Documents path | Verified: `os.path.realpath()` + string check         |
| CORE-05  | `init --label --vault` stores config.json                                        | D-20..D-22                                            |
| CORE-06  | Filename = `<machine>--YYYY-MM-DD--<slug>.md`; no two machines collide           | D-13..D-15, slug generator verified                   |
| CORE-07  | Second run with no new sessions produces zero files                              | Clobber defense layer 1 (state) covers this           |
| CORE-08  | Session in synced_session_ids never re-exported even if vault file missing       | Layer 1 clobber defense                               |
| CORE-09  | Target filename already exists → write refused                                   | Layer 2: O_CREAT                                      | O_EXCL check |
| CORE-10  | `auto_label_hash` in frontmatter = sha256 of body bytes                          | sha256 verified; computation order in D-24            |
| CORE-11  | `export --stdout` flag added to claude-chat.py; backwards-compatible             | Verified: argparse line 1540-1548; small change       |
| CORE-12  | `protect` audit: confirmed NOT a content scrubber (line 821)                     | Verified: only sets cleanupPeriodDays                 |
| CORE-13  | `status` prints machine label, last run timestamp, synced count, pending count   | Reads config.json + state.json + scan output          |
| LABEL-09 | `write` accepts label JSON via stdin; stub path uses same contract               | D-01..D-03                                            |

</phase_requirements>

---

## Summary

Phase 1 is a stdlib-only Python file (`~/.claude-chat/sync_chats.py`) plus one small backwards-compatible addition to `claude-chat.py` (`--stdout` flag). There are no external dependencies to install, no pypi packages to evaluate, and no third-party services to authenticate against. The entire research question reduces to: how do we use the right stdlib primitives in the right order?

The biggest planning surface is the three-layer clobber defense (state set, file-exists O_EXCL, auto_label_hash reconcile) and the crash recovery loop that ties them together. All three layers have been verified to work with stdlib primitives. The JSONL session structure has been inspected live on disk and the data shape matches what `claude-chat.py` already expects.

Two non-obvious findings follow. First, `~/.claude/projects/` contains both top-level `.jsonl` sessions (depth 2 from `projects/`) and subagent `.jsonl` files nested at depth 4+ (`<proj>/<session-uuid>/subagents/<agent>.jsonl`). The scanner must filter to depth 2 only — subagent files are sub-sessions of a parent and should not be independently synced. Second, the session "date" for the filename (YYYY-MM-DD) should come from the first `timestamp` field in the JSONL records, not from file mtime, because `copy2`/backup operations can shift mtime significantly (verified: mtime was 2026-03-29 while first message timestamp was 2026-03-19).

**Primary recommendation:** Build `sync_chats.py` as a single-file CLI (~350-450 lines) with section-commented structure matching `claude-chat.py`'s style. The implementation order that minimizes integration risk is: `init` → `scan` (discovery function) → stub label generator → `write` (full pipeline) → `status` → add `--stdout` to `claude-chat.py` → write unit tests → write canary script.

---

## Standard Stack

### Core

| Library       | Version     | Purpose                                                    | Why Standard                             |
| ------------- | ----------- | ---------------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------- | ---------- |
| `pathlib`     | stdlib 3.6+ | Path manipulation, rglob discovery                         | Already used throughout `claude-chat.py` |
| `json`        | stdlib      | Config/state file I/O, stdin label parsing                 | Zero deps, already used                  |
| `hashlib`     | stdlib      | `sha256(body_bytes).hexdigest()` for auto_label_hash       | No third-party needed                    |
| `unicodedata` | stdlib      | NFKD normalization for slug                                | D-13 spec                                |
| `subprocess`  | stdlib      | Shell out to `claude-chat.py export --stdout`              | No `import` boundary                     |
| `argparse`    | stdlib      | Subcommand routing (init/scan/write/status)                | Matches claude-chat.py idiom             |
| `socket`      | stdlib      | `socket.gethostname()` for frontmatter `hostname` field    | stdlib, no external                      |
| `os`          | stdlib      | `os.open(O_CREAT                                           | O_EXCL                                   | O_WRONLY)`, `os.fsync()`, `os.replace()`, `os.path.realpath()` | Atomic ops |
| `datetime`    | stdlib      | ISO timestamps, date parsing from JSONL, `synced_at` field | Already used                             |
| `unittest`    | stdlib      | Test runner (`python -m unittest discover tests`)          | D-28                                     |

[VERIFIED: live codebase inspection and system checks run 2026-04-13]

### Supporting

| Library    | Version | Purpose                                     | When to Use                             |
| ---------- | ------- | ------------------------------------------- | --------------------------------------- |
| `shutil`   | stdlib  | `copy2()` for `.bak` state file             | Already used in claude-chat.py backup   |
| `re`       | stdlib  | Whitespace normalization in text extraction | Already used                            |
| `tempfile` | stdlib  | `mkdtemp()` in canary test script only      | Bash canary can use `mktemp -d` instead |

**Installation:** None required — all stdlib.

---

## Architecture Patterns

### Recommended Project Structure

```
~/.claude-chat/              # MUST NOT be on iCloud (CORE-04)
├── sync_chats.py            # The new CLI (~350-450 lines, single file)
├── config.json              # Set by `init`; schema_version, machine_label, vault_path
├── config.tmp               # Transient during atomic write
├── state.json               # Synced session IDs + (mtime, size) fingerprints
├── state.bak                # Previous state (one version back)
├── state.tmp                # Transient during atomic write
└── sync.log                 # Append-only run log

tests/                       # Created as part of Phase 1
├── test_sync_chats.py       # python -m unittest (pure functions, clobber defenses)
└── phase1_canary.sh         # Bash end-to-end canary (9 success criteria)
```

### Pattern 1: Section-Commented Single-File CLI

Matches `claude-chat.py`'s structure exactly. Michael (a Python beginner) is comfortable with this layout.

```python
#!/usr/bin/env python3
"""sync_chats.py — Sync Claude Code sessions to Obsidian vault."""

import argparse, json, os, hashlib, pathlib, re, socket, subprocess, unicodedata
from datetime import datetime, timezone
from pathlib import Path

__version__ = "1.0.0"

# ─── Configuration ───────────────────────────────────────────────────────────
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CHAT_HOME", Path.home() / ".claude-chat"))
PROJECTS_DIR = Path.home() / ".claude" / "projects"

# ─── Startup Assertions ──────────────────────────────────────────────────────
# ─── Config I/O ──────────────────────────────────────────────────────────────
# ─── State I/O ───────────────────────────────────────────────────────────────
# ─── Session Discovery ───────────────────────────────────────────────────────
# ─── Stub Label Generator ────────────────────────────────────────────────────
# ─── Slug Generator ──────────────────────────────────────────────────────────
# ─── YAML Frontmatter Emitter ────────────────────────────────────────────────
# ─── Write Pipeline ──────────────────────────────────────────────────────────
# ─── Commands ────────────────────────────────────────────────────────────────
# ─── Entry Point ─────────────────────────────────────────────────────────────
```

[VERIFIED: matches claude-chat.py section-comment convention, CONVENTIONS.md 2026-04-09]

### Pattern 2: Atomic Config/State Write (tmp + fsync + rename)

`cmd_protect()` in `claude-chat.py` already uses `tmp.replace(target)`. Phase 1 extends this with `os.fsync()` for crash durability and `.bak` preservation:

```python
def _write_atomic(path: Path, data: dict) -> None:
    """Write JSON dict to path atomically with fsync + .bak preservation."""
    tmp = path.with_suffix(".tmp")
    bak = path.with_suffix(".bak")
    content = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())          # durability: survives power loss
    if path.exists():
        import shutil
        shutil.copy2(path, bak)       # keep one previous version
    tmp.replace(path)                 # atomic on POSIX (os.rename under the hood)
```

[VERIFIED: pattern tested live on this system, 2026-04-13]

### Pattern 3: Atomic Write-If-Not-Exists (O_CREAT|O_EXCL)

This is clobber defense layer 2. `os.open()` with `O_CREAT|O_EXCL` is atomic on POSIX — no race window between "check if exists" and "create":

```python
import errno

def _write_if_not_exists(path: Path, content_bytes: bytes) -> bool:
    """Write bytes to path only if it does not already exist. Returns True if written."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except OSError as e:
        if e.errno == errno.EEXIST:
            return False   # file already exists
        raise
    try:
        os.write(fd, content_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)
    return True
```

**iCloud caveat:** iCloud Drive can create `.icloud` placeholder files (e.g., `.mbp--2026-03-19--debug-export.md.icloud`) for files that haven't been downloaded to this machine. These placeholder files have different names (dot-prefixed, `.icloud` extension) so the `O_EXCL` check on the normal target path will not trip on them. However: if a placeholder exists for the target path (meaning the file was written on another machine and not downloaded yet), the O_EXCL check will NOT detect the collision because the placeholder has a different name. For Phase 1 (single-machine), this is acceptable. [ASSUMED: iCloud placeholder behavior based on macOS documentation knowledge; the specific collision edge case needs Phase 5 multi-machine testing to validate]

### Pattern 4: The Write Pipeline (D-24)

The write pipeline must follow this exact order to achieve the D-25 crash-safe reconciliation:

```
1. Read label JSON from stdin → parse into label dict
2. Parse session JSONL (call claude-chat.py export --stdout via subprocess)
3. Build frontmatter fields dict (all except auto_label_hash)
4. Compute body_bytes = frontmatter_placeholder + body
   → But wait: auto_label_hash must hash the FINAL bytes including the hash itself?
   → No: hash the body WITHOUT the frontmatter, then inject hash into frontmatter.
   → Or: hash the entire rendered document minus the auto_label_hash line.
   → Decision (Claude's Discretion): hash only the markdown body (everything after frontmatter).
   → This makes reconciliation simpler: re-render body, hash it, compare to stored hash.
5. Emit frontmatter with auto_label_hash = sha256(body_bytes).hexdigest()
6. final_bytes = frontmatter_bytes + body_bytes
7. write_if_not_exists(target, final_bytes)  ← clobber layer 2
8. If False (file exists): run reconciliation check (D-25)
9. If True (written): update in-memory state, atomic-write state.json
```

### Pattern 5: iCloud Path Detection (CORE-04)

```python
import os

def _assert_not_icloud(path: Path) -> None:
    """Abort if path resolves inside iCloud Drive (Mobile Documents)."""
    real = os.path.realpath(str(path))
    # macOS iCloud Drive: ~/Library/Mobile Documents/...
    # Also catches direct /private/var symlink chains
    if "Mobile Documents" in real or "/iCloud" in real:
        print(
            f"ERROR: {path} resolves to an iCloud path ({real}).\n"
            "~/.claude-chat/ must be a local (non-iCloud) directory.\n"
            "Symlinking state files into iCloud risks sync corruption.",
            file=sys.stderr,
        )
        sys.exit(2)
```

[VERIFIED: `os.path.realpath()` correctly follows symlinks on macOS; tested against actual iCloud vault path which contains "Mobile Documents", 2026-04-13]

### Pattern 6: Subprocess Bridge to `claude-chat.py` (CORE-11)

`sync_chats.py` must NOT `import claude_chat` (hyphen in filename enforces this). The bridge is subprocess:

```python
def _get_markdown_body(session_id: str, claude_chat_path: Path) -> str:
    """Call claude-chat.py export --format md --stdout and return the rendered markdown."""
    result = subprocess.run(
        ["python3", str(claude_chat_path), "export", session_id, "--format", "md", "--stdout"],
        capture_output=True,
        text=True,
        check=True,       # raises CalledProcessError on non-zero exit
    )
    return result.stdout
```

The `--stdout` flag is not yet implemented in `claude-chat.py`. Adding it requires:

1. argparse: add `p.add_argument("--stdout", action="store_true", help="Write to stdout instead of file")` after line 1547.
2. `cmd_export()`: add early-return path when `args.stdout` is True — call `_export_session()` (which returns a string), then `print(content, end="")` and return. The existing `_export_session()` function is not modified; only `cmd_export()` gains the branch.

[VERIFIED: argparse setup at lines 1540-1548, cmd_export at lines 479-518, export_markdown at lines 854-888, all read 2026-04-13]

### Anti-Patterns to Avoid

- **Importing `claude_chat`:** The hyphen in the filename prevents this. Do not work around it with `importlib` or `runpy`. The subprocess boundary is intentional (INTEGRATIONS.md).
- **`--stub` flag on `write`:** D-03 explicitly rejects this. Phase 1 uses the same stdin path as Phase 2.
- **Writing state.json once at end of run:** D-26 requires per-session writes for crash safety.
- **Using `Path.exists()` for clobber defense:** Not atomic. Always use `O_CREAT|O_EXCL` for layer 2.
- **Sorting scan output by mtime descending:** D-08 requires ascending (oldest first) for catch-up runs.
- **Including subagent `.jsonl` files in scan:** Subagent sessions (nested at depth > 2 in `projects/`) are sub-sessions of a parent and must be excluded. Filter: `len(f.relative_to(PROJECTS_DIR).parts) == 2`.

---

## Don't Hand-Roll

| Problem                 | Don't Build                 | Use Instead                                                   | Why                                                                         |
| ----------------------- | --------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------------------- | --------------------------- |
| YAML serialization      | Custom serializer           | Hand-roll with `json.dumps()` for string quoting              | We control the schema — 12 known field types; pyyaml would add a dependency |
| Atomic file rename      | Own temp-file logic         | `os.replace()` (Python stdlib)                                | POSIX-atomic; already used in claude-chat.py                                |
| Race-free file creation | Check-then-create           | `os.open(O_CREAT                                              | O_EXCL)`                                                                    | The only POSIX-safe pattern |
| Unicode slug            | ASCII transliteration table | `unicodedata.normalize("NFKD")` + `.encode("ascii","ignore")` | Handles accents, ligatures, compatibility chars correctly                   |
| Markdown export         | Custom renderer             | Subprocess to `claude-chat.py export --stdout`                | Reuse existing 250-line renderer; avoids drift                              |

---

## JSONL Session Layout — Verified Structure

This section answers "what constitutes a session and where is the stable UUID?"

**Directory layout:**

```
~/.claude/projects/
├── -Users-michaelhenry-Documents-Projects-Python-claude-chat/  # project dir (encoded CWD)
│   ├── 541112ec-a07c-4d87-80f7-2310b98fd7ea.jsonl              # session file (depth=2)
│   ├── f6f7d016-dd7f-4823-bc31-6e808f045532.jsonl              # another session (depth=2)
│   └── f6f7d016-dd7f-4823-bc31-6e808f045532/                   # subagent dir (same uuid as parent)
│       └── subagents/
│           └── agent-adc43d3e61e0c105e.jsonl                   # subagent session (depth=4, SKIP)
└── -Users-michaelhenry/                                         # another project
    └── 4327defb-ad82-4bd8-affa-814d44855a34.jsonl
```

**Stable session UUID:** The `.jsonl` file stem (e.g., `541112ec-a07c-4d87-80f7-2310b98fd7ea`). This matches the `sessionId` field in every top-level JSONL record. [VERIFIED: stem == sessionId confirmed live, 2026-04-13]

**Top-level JSONL record keys (verified live):**

- `parentUuid`, `isSidechain`, `promptId`, `type`, `message`, `uuid`, `timestamp`, `permissionMode`, `userType`, `entrypoint`, `cwd`, `sessionId`, `version`, `gitBranch`

**`message` object keys (user message):**

- `role` = "user", `content` = string or list of content blocks

**`message` object keys (assistant message):**

- `role`, `model`, `id`, `type`, `content` (list), `stop_reason`, `stop_sequence`, `usage`
- `usage` keys: `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `service_tier`, `inference_geo`

**Subagent detection:** Records with `agentId` key at top level and files nested at depth > 2 from `projects/`. The scanner must filter these out.

[VERIFIED: live inspection of ~/.claude/projects/ directory, 2026-04-13]

---

## Frontmatter Schema — Complete Specification

All fields required in every Phase 1 output file. Nulls written as empty YAML value (bare `key:`).

| Field             | YAML type       | Source                                                                        | Notes                                                                                 |
| ----------------- | --------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `title`           | string          | stdin label JSON `.title`                                                     | D-04 stub: first 8 words of first user message                                        |
| `gist`            | string or null  | stdin label JSON `.gist`                                                      | D-05 stub: null                                                                       |
| `tags`            | list of strings | stdin label JSON `.tags`                                                      | D-05 stub: `["stub"]`; block YAML list                                                |
| `coherence_score` | int or null     | stdin label JSON `.coherence_score`                                           | D-05 stub: null                                                                       |
| `needs_review`    | bool            | stdin label JSON `.needs_review`                                              | D-05 stub: true                                                                       |
| `project`         | string          | `f.parent.name` (the encoded CWD dir name)                                    | e.g., `-Users-michaelhenry-Documents-...`                                             |
| `session_id`      | string          | `f.stem` (UUID)                                                               | Full UUID4                                                                            |
| `model`           | string          | last `msg.model` seen in JSONL parsing                                        | `claude-sonnet-4-6` etc.                                                              |
| `token_count`     | int             | sum of `msg.usage.input_tokens + output_tokens` across all assistant messages | [VERIFIED: usage field confirmed live]                                                |
| `msg_count`       | int             | count of lines where `role` is `user` or `assistant`                          | Quick scan; matches `message_count()` approach                                        |
| `machine`         | string          | `config.machine_label`                                                        | Set by `init --label`                                                                 |
| `hostname`        | string          | `socket.gethostname()`                                                        | e.g., `digital-javelina-pro.tail75a1.ts.net`                                          |
| `synced_at`       | string          | `datetime.now(timezone.utc).isoformat()`                                      | ISO 8601 with UTC offset                                                              |
| `auto_label_hash` | string          | `hashlib.sha256(body_bytes).hexdigest()`                                      | body_bytes = rendered markdown body (AFTER frontmatter, BEFORE this hash is computed) |

**YAML emission rules (hand-rolled, no pyyaml):**

- Block form only. No flow scalars. Keys in the stable order above.
- Strings: plain if no special YAML characters (`:#{}[]|>&!*,`). Double-quoted (via `json.dumps()`) otherwise.
- `synced_at` always gets double-quoted (contains `+` and `:` which are safe but the `T` format is visually cleaner quoted).
- Tags: block list form (`\n  - tag`), never inline `[tag1, tag2]`.
- Null: bare `key:` with no value.
- Bool: lowercase `true` / `false` (YAML spec).

[VERIFIED: hand-rolled YAML tested live; Obsidian Dataview parses bare `key:` as null and lowercase bool correctly, ASSUMED based on Dataview documentation]

---

## Session Date for Filename

The `YYYY-MM-DD` component of `<machine>--YYYY-MM-DD--<slug>.md` should be the **session start date**, derived from the `timestamp` field of the first JSONL record that has a `timestamp` key.

Format: ISO 8601 UTC string, e.g., `"2026-03-19T23:47:22.059Z"`. Parse with:

```python
from datetime import datetime, timezone

def _parse_jsonl_timestamp(ts: str) -> datetime:
    """Parse JSONL record timestamp to UTC datetime."""
    # Format: "2026-03-19T23:47:22.059Z"
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
```

**Why not file mtime?** Verified live: file mtime was 2026-03-29 (10 days after session) because the file was copied by `cmd_backup`. The JSONL first-message timestamp (2026-03-19) is the semantically correct session date.

**Fallback:** If no `timestamp` field found in the first 50 JSONL lines, fall back to `datetime.fromtimestamp(f.stat().st_mtime)`.

[VERIFIED: live comparison of mtime vs first JSONL timestamp, 2026-04-13]

---

## Slug Generation — Verified Implementation

```python
import unicodedata, re

def make_slug(title: str, fallback_id: str = "") -> str:
    """Generate a filesystem-safe kebab slug from title (D-13..D-15)."""
    # NFKD: decomposes accented chars (é -> e + combining accent), then strip non-ASCII
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    # Replace any run of non-alphanumeric chars with a single dash
    s = re.sub(r"[^a-z0-9]+", "-", s)
    # Strip leading/trailing dashes
    s = s.strip("-")
    # Truncate to 60 chars at word boundary (rstrip leftover dash after cut)
    if len(s) > 60:
        s = s[:60].rstrip("-")
    # Fallback for all-non-ASCII or all-punctuation titles
    if not s:
        s = fallback_id[:8] if fallback_id else "untitled"
    return s
```

Verified behaviors:

- `"Debug the export markdown function"` → `"debug-the-export-markdown-function"` (36 chars, under 60)
- `"Über café résumé"` → `"uber-cafe-resume"` (NFKD normalization works)
- `"!!!???"` with fallback_id `"qrs12345"` → `"qrs12345"` (empty after normalization)
- `"A" * 80` → 60-char slug (truncated)

[VERIFIED: tested live, 2026-04-13]

---

## Stub Title Extraction — Verified Implementation

Per D-04: first 8 words of the first user message.

```python
def extract_first_user_message(jsonl_path: Path) -> str:
    """Return the first non-system-reminder user message text from a JSONL session file."""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message", obj)
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "")
                # content can be str or list of blocks
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    parts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    text = "\n".join(parts).strip()
                else:
                    text = ""
                # Skip system reminders injected by Claude Code
                if text and "<system-reminder>" not in text and len(text) > 5:
                    return text
    except (IOError, OSError):
        pass
    return ""


def make_stub_title(jsonl_path: Path, session_short_id: str) -> str:
    """Return stub title per D-04/D-06."""
    text = extract_first_user_message(jsonl_path)
    if not text:
        return f"Untitled {session_short_id}"
    words = text.split()
    return " ".join(words[:8])
```

[VERIFIED: pattern derived from claude-chat.py Session.parse() and Session.summary() methods, lines 158-263]

---

## State.json Schema

```json
{
  "schema_version": 1,
  "synced_session_ids": ["uuid1", "uuid2"],
  "fingerprints": {
    "uuid1": { "mtime": 1234567890.123, "size": 45678 },
    "uuid2": { "mtime": 1234567900.456, "size": 12345 }
  },
  "last_run_at": "2026-04-13T16:00:00.000000+00:00"
}
```

**Why JSON, not JSONL:** State is read-and-rewritten as a whole on every session write (D-26). Append-safety would require JSONL, but the write-once-per-session pattern with atomic replace is crash-safe without append semantics. JSON is simpler to reason about for a beginner.

**Minimum fields for idempotency:**

- `synced_session_ids`: list — clobber defense layer 1
- `fingerprints`: dict keyed by session_id — delta detection

**`last_run_at`** is a convenience field for `status` output. Set to current time at the end of each run.

---

## The `protect` Audit (CORE-12)

**Finding (D-16, VERIFIED against live code):**

`cmd_protect()` at line 821 of `claude-chat.py`:

1. Reads `~/.claude/settings.json` (or starts with `{}`)
2. Sets `settings["cleanupPeriodDays"] = 99999`
3. Writes atomically via tmp + rename

It does **not** read any `.jsonl` files. It does **not** scrub content. It does not touch the message body in any way. The function is entirely about preventing Claude Code's auto-deletion timer.

**Phase 1 action (D-17):** Create `01-PROTECT-AUDIT.md` in the phase directory documenting this finding. No code changes to `cmd_protect()`. Phase 3 owns the `protect --scrub-content` mode.

[VERIFIED: read `cmd_protect()` lines 821-848 directly, 2026-04-13]

---

## The `export --stdout` Change (CORE-11)

**What exists:** `cmd_export()` at line 479. `_export_session()` at line 452. Export argparse at lines 1540-1548.

**What to add:**

1. **argparse** (line 1548, after `--rich`):

   ```python
   p.add_argument("--stdout", action="store_true", help="Write rendered output to stdout instead of a file")
   ```

2. **`cmd_export()`** — add early-exit branch after `session.parse()` (around line 513):
   ```python
   if getattr(args, "stdout", False):
       # Map format to content
       fmt = args.format or "md"
       if fmt == "md":
           content = export_markdown(session)
       elif fmt == "html":
           content = export_html(session, rich=getattr(args, "rich", False))
       elif fmt == "txt":
           content = export_txt(session)
       elif fmt == "tex":
           content = export_tex(session)
       else:
           print(f"Unknown format: {fmt}", file=sys.stderr)
           sys.exit(1)
       sys.stdout.write(content)
       return
   ```

This is backwards-compatible: `--stdout` defaults to `False`, so all existing behavior is unchanged.

[VERIFIED: `_export_session()` returns a string (line 452-476); `export_markdown()` returns `"\n".join(lines)` (line 888). The content variable is already the full string.]

---

## Common Pitfalls

### Pitfall 1: Subagent `.jsonl` Files Included in Scan

**What goes wrong:** `rglob("*.jsonl")` finds both top-level session files and deeply-nested subagent files (at depth 4+ in the projects tree). Subagent files have `agentId` in their records and are sub-components of a parent session. Syncing them independently would create orphaned vault files with no useful top-level context.

**How to avoid:** Filter to depth 2 only: `len(f.relative_to(PROJECTS_DIR).parts) == 2`.

**Warning signs:** Files named `agent-*.jsonl` appearing in scan output; vault files with very short or tool-call-only content.

[VERIFIED: live directory inspection found 890 top-level vs 71 nested sessions, 2026-04-13]

### Pitfall 2: Using File mtime as Session Date

**What goes wrong:** `~/.claude-chat/state.json` uses mtime for delta detection (fine), but if you also use mtime for the filename's `YYYY-MM-DD`, you'll get the backup copy date rather than the conversation date — sometimes 10+ days off.

**How to avoid:** Parse the first `timestamp` field from JSONL records for the filename date. Use mtime only as delta-detection fingerprint.

[VERIFIED: live comparison showed mtime 2026-03-29 vs first-message timestamp 2026-03-19]

### Pitfall 3: Crash Between Vault Write and State Write (D-25 reconciliation)

**What goes wrong:** Process crashes after `os.replace(tmp, target)` but before `state.json` is updated. Next run: `scan` re-emits the session (state has no fingerprint), `write` is re-attempted, `O_EXCL` fires (file already exists). Without reconciliation, this looks like a clobber collision and returns a generic error. The session is permanently stuck in a "failed" state.

**How to avoid:** When `write_if_not_exists()` returns `False`, do the reconciliation check (D-25): re-render the body, compute its sha256, compare to `auto_label_hash` in the existing file's frontmatter. If they match → update state to "synced" and continue. If they don't match → this is a genuine collision (slug collision or renamed file), require user intervention.

**Warning signs:** Sessions that always appear in `scan` output even after `write` runs "successfully".

### Pitfall 4: iCloud Placeholders for Vault Files

**What goes wrong:** If the vault is on iCloud and a file was written on another Mac but not yet downloaded to this one, iCloud creates a placeholder file named `.<original_name>.icloud`. The `O_EXCL` check on the normal target path does NOT detect this — the placeholder has a different name. You'd write a duplicate on this Mac.

**How to avoid:** Phase 1 is single-machine. For Phase 5 (multi-machine), add a check: `if any(chats_dir.glob(f".{stem}.icloud")): refuse_with_message()`. [ASSUMED: placeholder naming pattern based on macOS behavior; verify in Phase 5]

### Pitfall 5: YAML Special Characters in Title/Gist

**What goes wrong:** A title like `Fix the "config: value" parsing bug` contains a colon and quotes. If emitted as a bare YAML scalar, parsers will choke.

**How to avoid:** In the YAML emitter, double-quote strings that contain any of `:#{}[]|>&!*,` using `json.dumps(s)` (JSON double-quoted strings are valid YAML double-quoted strings).

[VERIFIED: hand-rolled YAML emitter tested with `synced_at` ISO timestamp which contains `:` and `+`, 2026-04-13]

### Pitfall 6: `--stdout` Flag Conflicts with `--open` / `--output`

**What goes wrong:** If user passes both `--stdout` and `--open`, the session would be "opened" even though no file was written.

**How to avoid:** In the `--stdout` branch of `cmd_export()`, return immediately after `sys.stdout.write(content)` — never reach the `--open` logic.

---

## Code Examples

### iCloud Startup Assertion

```python
def assert_not_icloud(path: Path) -> None:
    """Abort with exit 2 if path resolves into iCloud Drive."""
    real = os.path.realpath(str(path))
    if "Mobile Documents" in real or "/iCloud" in real:
        print(
            f"ERROR: {path} resolves to an iCloud path:\n  {real}\n"
            "~/.claude-chat/ must be a local directory. "
            "Move it out of iCloud Drive and re-run init.",
            file=sys.stderr,
        )
        sys.exit(2)
```

### Session Scanner (~20 lines per D-09)

```python
def scan_sessions(state: dict) -> list:
    """
    Walk PROJECTS_DIR for top-level .jsonl sessions not yet synced or changed.
    Returns list of dicts sorted by mtime ascending (oldest first per D-08).
    """
    synced = set(state.get("synced_session_ids", []))
    fingerprints = state.get("fingerprints", {})
    results = []
    for f in PROJECTS_DIR.rglob("*.jsonl"):
        # Only top-level sessions (depth 2: <proj>/<session>.jsonl)
        if len(f.relative_to(PROJECTS_DIR).parts) != 2:
            continue
        try:
            st = f.stat()
        except (FileNotFoundError, OSError):
            continue
        if st.st_size <= 100:        # skip empty/tiny files (matches claude-chat.py)
            continue
        session_id = f.stem
        fp = {"mtime": st.st_mtime, "size": st.st_size}
        stored_fp = fingerprints.get(session_id)
        if session_id in synced and stored_fp == fp:
            continue                 # already synced, fingerprint unchanged
        results.append({
            "session_id": session_id,
            "project": f.parent.name,
            "path": str(f),
            "mtime": st.st_mtime,
            "size": st.st_size,
        })
    results.sort(key=lambda x: x["mtime"])   # ascending: oldest first
    return results
```

### Hand-Rolled YAML Frontmatter Emitter

```python
import json as _json

def emit_frontmatter(fields: dict) -> str:
    """
    Emit YAML frontmatter block (---...---) from an ordered dict.
    Supports: str, int, float, bool, None, list[str].
    Uses double-quotes (via json.dumps) for strings with YAML-special chars.
    """
    _YAML_SPECIAL = set(":#{}[]|>&!*,")
    lines = ["---"]
    for key, val in fields.items():
        if val is None:
            lines.append(f"{key}:")
        elif isinstance(val, bool):
            lines.append(f"{key}: {'true' if val else 'false'}")
        elif isinstance(val, (int, float)):
            lines.append(f"{key}: {val}")
        elif isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f"  - {item}")
        else:
            s = str(val)
            # Double-quote if contains YAML-special chars or leading/trailing space
            if any(c in s for c in _YAML_SPECIAL) or s != s.strip():
                lines.append(f"{key}: {_json.dumps(s)}")
            else:
                lines.append(f"{key}: {s}")
    lines.append("---")
    return "\n".join(lines) + "\n"
```

### SHA256 auto_label_hash Computation

```python
import hashlib

def compute_auto_label_hash(body_str: str) -> str:
    """SHA256 hex digest of the markdown body (text after frontmatter)."""
    return hashlib.sha256(body_str.encode("utf-8")).hexdigest()
```

### Token Count from JSONL

```python
def extract_session_metadata(jsonl_path: Path) -> dict:
    """
    Extract: model, token_count (sum input+output), msg_count, session_date.
    Returns dict with those keys. Single pass through file.
    """
    model = None
    total_tokens = 0
    msg_count = 0
    session_date = None   # from first timestamp field found
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Grab first timestamp for session date
                if session_date is None:
                    ts = obj.get("timestamp", "")
                    if ts:
                        try:
                            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
                            session_date = dt.strftime("%Y-%m-%d")
                        except ValueError:
                            pass
                msg = obj.get("message", obj)
                role = msg.get("role", "")
                if role in ("user", "assistant"):
                    msg_count += 1
                if role == "assistant":
                    if not model:
                        model = msg.get("model")
                    usage = msg.get("usage", {})
                    total_tokens += usage.get("input_tokens", 0)
                    total_tokens += usage.get("output_tokens", 0)
    except (IOError, OSError):
        pass
    return {
        "model": model or "unknown",
        "token_count": total_tokens,
        "msg_count": msg_count,
        "session_date": session_date,
    }
```

---

## Project Constraints (from CLAUDE.local.md)

| Directive                                            | Impact on Phase 1                                                                                 |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Zero external dependencies — stdlib only             | No PyYAML, no pytest, no requests. Use `python -m unittest`, hand-roll YAML.                      |
| Single-file CLI tool pattern                         | `sync_chats.py` is one file; no sub-package                                                       |
| Python beginner audience                             | Inline comments explaining stdlib idioms (`unicodedata.normalize`, `os.O_EXCL`, `os.fsync`, etc.) |
| No formatter configured yet — consider `ruff format` | Run `ruff format sync_chats.py` before committing                                                 |
| Run with `python3 <script> [command]`                | argparse subcommand pattern, matching claude-chat.py                                              |

---

## State of the Art

| Old Approach                                                      | Current Approach                                               | Impact                                                                                 |
| ----------------------------------------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------- |
| `PROJECTS_DIR.iterdir()` + `dir.glob("*.jsonl")` (claude-chat.py) | `PROJECTS_DIR.rglob("*.jsonl")` + depth filter (sync_chats.py) | Picks up sessions across all project dirs in one pass; depth filter excludes subagents |
| File-based write with `open("w")` (claude-chat.py export)         | `os.open(O_CREAT                                               | O_EXCL)`+`os.fsync` (sync_chats.py write)                                              | Race-free creation; survives power loss |
| `tmp.replace(target)` (claude-chat.py protect)                    | same + `os.fsync(fd)` before replace + `.bak` copy             | Durability against OS crash, plus one-step rollback                                    |

---

## Assumptions Log

| #   | Claim                                                                                                                                    | Section            | Risk if Wrong                                                                                                               |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| A1  | iCloud placeholder files for undownloaded content are named `.<original>.icloud`, so O_EXCL on the normal target path won't trip on them | Common Pitfalls §4 | Low for Phase 1 (single-machine); needs verification in Phase 5                                                             |
| A2  | Obsidian Dataview parses bare YAML `key:` as null and lowercase `true`/`false` as boolean                                                | Frontmatter Schema | Low: Dataview YAML parsing is well-documented and this is standard YAML                                                     |
| A3  | iCloud-synced vault files written by `os.replace()` are picked up by iCloud Drive daemon without extra extended-attribute calls          | Write Pipeline     | Low: verified that Chats dir exists and is writable; actual sync behavior confirmed by iCloud daemon watching the directory |

---

## Open Questions

1. **Session date from timestamp format variations**
   - What we know: Format is `"2026-03-19T23:47:22.059Z"` (millisecond precision, Z suffix)
   - What's unclear: Whether older sessions might use a different timestamp format (seconds only, no Z, etc.)
   - Recommendation: Wrap timestamp parsing in try/except with mtime fallback; log a warning if parsing fails

2. **100-byte minimum file size filter**
   - What we know: `claude-chat.py` skips files `<= 100` bytes. Phase 1 scanner should match.
   - What's unclear: Whether 100 bytes is the right threshold for empty sessions given Claude Code's JSONL structure
   - Recommendation: Match claude-chat.py's threshold exactly (100 bytes) for behavioral consistency

3. **`claude-chat.py` path discovery in `sync_chats.py`**
   - What we know: `sync_chats.py` will be at `~/.claude-chat/sync_chats.py`; `claude-chat.py` is at an unknown location per user
   - What's unclear: How to locate `claude-chat.py` reliably for the subprocess call
   - Recommendation: Store `claude_chat_path` in `config.json` (added to `init` flags); or hardcode `~/Documents/Projects/Python/claude-chat/claude-chat.py` as a discoverable default with a config override

---

## Environment Availability

| Dependency               | Required By                  | Available             | Version | Fallback                                      |
| ------------------------ | ---------------------------- | --------------------- | ------- | --------------------------------------------- |
| Python 3                 | sync_chats.py execution      | Yes                   | 3.14.3  | —                                             |
| `~/.claude/projects/`    | Session discovery            | Yes                   | —       | Abort with clear message                      |
| Obsidian vault Chats dir | Vault write                  | Yes (empty)           | —       | Create on first `init`                        |
| `claude-chat.py`         | `export --stdout` subprocess | Yes                   | 1.0.0   | —                                             |
| iCloud Drive             | Vault sync                   | Yes (vault is iCloud) | —       | Not required; vault writes succeed regardless |

[VERIFIED: all paths confirmed live, 2026-04-13]

---

## Validation Architecture

### Test Framework

| Property           | Value                                                                  |
| ------------------ | ---------------------------------------------------------------------- |
| Framework          | `python -m unittest` (stdlib, no install)                              |
| Config file        | None — runner uses `discover tests/` convention                        |
| Quick run command  | `python3 -m unittest discover tests -v`                                |
| Full suite command | `python3 -m unittest discover tests -v && bash tests/phase1_canary.sh` |

### Phase Requirements → Test Map

| Req ID   | Behavior                                           | Test Type            | Automated Command                                               | File Exists? |
| -------- | -------------------------------------------------- | -------------------- | --------------------------------------------------------------- | ------------ |
| CORE-01  | `scan` returns JSON list of unsynced sessions      | unit                 | `python3 -m unittest tests.test_sync_chats.TestScan`            | No — Wave 0  |
| CORE-02  | `write` creates named `.md` with YAML frontmatter  | integration (canary) | `bash tests/phase1_canary.sh` criterion 3                       | No — Wave 0  |
| CORE-03  | state.json atomic write with .bak                  | unit                 | `python3 -m unittest tests.test_sync_chats.TestStateIO`         | No — Wave 0  |
| CORE-04  | Startup assertion aborts on iCloud path            | unit                 | `python3 -m unittest tests.test_sync_chats.TestICloudAssertion` | No — Wave 0  |
| CORE-05  | `init` creates config.json                         | integration (canary) | `bash tests/phase1_canary.sh` criterion 1                       | No — Wave 0  |
| CORE-06  | Filename format `<machine>--YYYY-MM-DD--<slug>.md` | unit                 | `python3 -m unittest tests.test_sync_chats.TestSlug`            | No — Wave 0  |
| CORE-07  | Second run produces zero new files                 | integration (canary) | `bash tests/phase1_canary.sh` criterion 4                       | No — Wave 0  |
| CORE-08  | Session in synced_ids never re-exported            | unit                 | `python3 -m unittest tests.test_sync_chats.TestClobberLayer1`   | No — Wave 0  |
| CORE-09  | File-exists → write refused                        | unit                 | `python3 -m unittest tests.test_sync_chats.TestClobberLayer2`   | No — Wave 0  |
| CORE-10  | `auto_label_hash` = sha256 of body                 | unit                 | `python3 -m unittest tests.test_sync_chats.TestAutoLabelHash`   | No — Wave 0  |
| CORE-11  | `claude-chat.py export --stdout` works             | integration (canary) | `bash tests/phase1_canary.sh` criterion 7                       | No — Wave 0  |
| CORE-12  | protect audit documented in 01-PROTECT-AUDIT.md    | manual               | file exists + content check                                     | No — Wave 0  |
| CORE-13  | `status` shows label, timestamp, counts            | integration (canary) | `bash tests/phase1_canary.sh` criterion 8                       | No — Wave 0  |
| LABEL-09 | `write` reads labels from stdin only               | unit                 | `python3 -m unittest tests.test_sync_chats.TestStdinContract`   | No — Wave 0  |

### Sampling Rate

- **Per task commit:** `python3 -m unittest discover tests -v`
- **Per wave merge:** `python3 -m unittest discover tests -v && bash tests/phase1_canary.sh`
- **Phase gate:** Full suite green (all 9 canary criteria pass) before `/gsd-verify-work`

### Wave 0 Gaps

All test infrastructure must be created from scratch:

- [ ] `tests/__init__.py` — package marker
- [ ] `tests/test_sync_chats.py` — unit tests for pure functions and clobber defenses
- [ ] `tests/phase1_canary.sh` — bash end-to-end script for all 9 success criteria
- [ ] `tests/fixtures/sample_session.jsonl` — minimal valid session for unit tests

No framework install needed (`python -m unittest` is stdlib).

---

## Security Domain

`security_enforcement` not explicitly set in config; treating as enabled.

### Applicable ASVS Categories

| ASVS Category         | Applies       | Standard Control                                            |
| --------------------- | ------------- | ----------------------------------------------------------- |
| V2 Authentication     | No            | No network, no auth                                         |
| V3 Session Management | No            | No sessions/web UI                                          |
| V4 Access Control     | No            | Local file I/O only                                         |
| V5 Input Validation   | Yes (partial) | Validate stdin label JSON schema; reject if `title` missing |
| V6 Cryptography       | No            | sha256 is for content hashing, not security                 |

### Known Threat Patterns for Phase 1 Stack

| Pattern                                           | STRIDE    | Standard Mitigation                                                                                       |
| ------------------------------------------------- | --------- | --------------------------------------------------------------------------------------------------------- |
| Malformed JSON on stdin crashes `write`           | Tampering | `json.loads()` in try/except with clean error message                                                     |
| JSONL line with embedded newlines breaks parsing  | Tampering | Line-by-line parsing with per-line `json.loads()` catch (matches claude-chat.py pattern)                  |
| Vault path traversal via config.json `vault_path` | Elevation | Validate `vault_path` is absolute and not `~/.claude-chat/` itself; no user-controlled path interpolation |
| `session_id` arg injection in subprocess call     | Tampering | Pass as list (not shell string) to `subprocess.run()`; `check=True`                                       |

**Note:** The most important security property for Phase 1 is that raw (unscrubbed) session content goes only to the vault, not to any network endpoint. This is trivially satisfied by the stdlib-only, local-file-only design. Scrubbing is explicitly deferred to Phase 3 per D-17..D-19.

---

## Sources

### Primary (HIGH confidence)

- `claude-chat.py` lines 821-848 — `cmd_protect()` source code, verified audit
- `claude-chat.py` lines 309-334 — `find_all_sessions()`, session discovery pattern
- `claude-chat.py` lines 452-518 — `_export_session()`, `cmd_export()`, argparse registration
- `claude-chat.py` lines 854-888 — `export_markdown()` return format
- `~/.claude/projects/` live directory inspection — JSONL structure, subagent dirs, timestamp format
- Python stdlib documentation — `os.O_CREAT|O_EXCL`, `os.fsync`, `os.path.realpath`, `unicodedata.normalize`
- `.planning/codebase/ARCHITECTURE.md` — layer map, data flow
- `.planning/codebase/CONVENTIONS.md` — naming, style, section dividers
- `.planning/codebase/INTEGRATIONS.md` — subprocess boundary rationale

### Secondary (MEDIUM confidence)

- `.planning/codebase/TESTING.md` — recommended test structure (no tests exist yet)
- CONTEXT.md decisions D-01..D-33 — locked implementation decisions

### Tertiary (LOW confidence — see Assumptions Log)

- iCloud placeholder file naming behavior (A1) — based on training knowledge, not verified live
- Dataview YAML null/bool parsing behavior (A2) — based on training knowledge

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — all stdlib, verified on running system
- Architecture: HIGH — CONTEXT.md decisions are locked; JSONL structure verified live
- Pitfalls: HIGH for items verified live; MEDIUM for iCloud multi-machine edge cases
- JSONL layout: HIGH — verified against real session files

**Research date:** 2026-04-13
**Valid until:** 2026-05-13 (stable — Claude Code JSONL format changes rarely)
