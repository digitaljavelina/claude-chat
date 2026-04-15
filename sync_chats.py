#!/usr/bin/env python3
"""sync_chats.py -- Sync Claude Code sessions to Obsidian vault."""

# Standard library imports only — zero external dependencies (project invariant)
import argparse
import errno
import hashlib
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────

__version__ = "1.0.0"

# CLAUDE_CHAT_HOME is overridable via env var so tests can point at /tmp instead of ~/.claude-chat
# This is the "escape hatch" that lets tests run without polluting the real user dir (D-29)
CLAUDE_CHAT_HOME = Path(os.environ.get("CLAUDE_CHAT_HOME", str(Path.home() / ".claude-chat")))

# Projects dir: where Claude Code stores sessions as JSONL files (one UUID.jsonl per session)
# CLAUDE_PROJECTS_DIR env var override allows tests (and the canary script) to point at a
# fake projects directory without touching real ~/.claude/projects/ (consistent with D-29).
PROJECTS_DIR = Path(os.environ.get("CLAUDE_PROJECTS_DIR", str(Path.home() / ".claude" / "projects")))

# All sync_chats state lives under CLAUDE_CHAT_HOME — strictly local, never iCloud (D-23)
CONFIG_PATH = CLAUDE_CHAT_HOME / "config.json"
STATE_PATH = CLAUDE_CHAT_HOME / "state.json"
LOG_PATH = CLAUDE_CHAT_HOME / "sync.log"
# New in Phase 5 (D-11/D-14): machine-readable record of the most-recent run;
# atomic-overwrite each run with .bak preservation (same pattern as state.json).
LAST_RUN_PATH = CLAUDE_CHAT_HOME / "last_run.json"

# ─── Startup Assertions ───────────────────────────────────────────────────────


def _assert_not_icloud(path: Path) -> None:
    """Abort if path resolves inside iCloud Drive (Mobile Documents).

    Per D-23: this assertion applies to CLAUDE_CHAT_HOME only, NOT the vault path.
    The vault is expected to be in iCloud; state must stay local to avoid sync races.
    """
    # os.path.realpath() follows all symlinks to get the true filesystem path
    real = os.path.realpath(str(path))
    # macOS iCloud Drive paths contain "Mobile Documents" (e.g. ~/Library/Mobile Documents/...)
    # Some systems also expose it via /private/var symlink chains that include "/iCloud"
    if "Mobile Documents" in real or "/iCloud" in real:
        print(
            f"ERROR: {path} resolves to an iCloud path ({real}).\n"
            "~/.claude-chat/ must be a local (non-iCloud) directory.\n"
            "Symlinking state files into iCloud risks sync corruption across machines.",
            file=sys.stderr,
        )
        sys.exit(2)


# ─── Config I/O ───────────────────────────────────────────────────────────────


def _write_atomic(path: Path, data: dict) -> None:
    """Write JSON dict to path atomically with fsync + .bak preservation.

    Why atomic? If the process crashes mid-write, a partial file is worse than
    no file. The tmp+fsync+rename pattern ensures we either have the old content
    or the new content — never a half-written hybrid.

    Steps:
      1. Write to a temp file (.tmp suffix)
      2. fsync: flush kernel buffer to disk — survives power loss
      3. If original exists, copy to .bak — one previous version for manual recovery
      4. Rename tmp -> target — atomic on POSIX (single syscall, no torn state)
    """
    # Write to a temp file alongside the target so the rename is on the same filesystem
    tmp = path.with_suffix(".tmp")
    bak = path.with_suffix(".bak")

    # json.dumps with sort_keys=True: consistent output regardless of dict insertion order
    # indent=2: human-readable for debugging state.json and config.json by hand
    content = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")

    with open(tmp, "wb") as f:
        f.write(content)
        f.flush()  # push Python's internal buffer into the OS kernel buffer
        os.fsync(f.fileno())  # push OS kernel buffer to physical disk (durability)

    if path.exists():
        # shutil.copy2 preserves metadata (timestamps) — keeps .bak recognizable
        shutil.copy2(path, bak)

    # tmp.replace(path) is os.rename() under the hood — atomic on POSIX filesystems
    tmp.replace(path)


def _write_last_run(data: dict) -> None:
    """Write last_run.json atomically with fsync + .bak preservation (D-14).

    Near-copy of _write_atomic() — same crash-safety guarantees, different path.
    See _write_atomic() docstring for why tmp+fsync+rename is atomic on APFS.

    WHY a near-copy instead of parameterizing _write_atomic():
      Per D-14 and the "Python beginner" note in CONTEXT.md, a near-copy with a
      comment is more readable than a generic helper that hides what's different.
      _write_atomic() uses sort_keys=True (for state.json determinism); here we
      omit sort_keys so the dict key order is preserved — jq-friendly for humans
      inspecting last_run.json.

    WHY shutil.copy2 (not rename) for .bak:
      copy2 preserves mtime — so the .bak timestamp tells you WHEN the previous
      run happened, useful for post-mortem after a hook failure.
    """
    # .tmp and .bak are alongside LAST_RUN_PATH — same directory, same filesystem.
    # We APPEND the suffix (last_run.json.tmp) rather than REPLACE it (last_run.tmp)
    # so the filenames remain recognizable at a glance: "that's the temp write for last_run.json".
    # Path(str(path) + ".tmp") appends; path.with_suffix(".tmp") would replace ".json".
    # On APFS (macOS default), rename(2) is atomic: readers see old OR new, never partial.
    tmp = Path(str(LAST_RUN_PATH) + ".tmp")
    bak = Path(str(LAST_RUN_PATH) + ".bak")

    # json.dumps without sort_keys — preserve caller's key order for readability.
    # indent=2: human-readable when inspecting with `cat ~/.claude-chat/last_run.json`.
    content = json.dumps(data, indent=2).encode("utf-8")

    with open(tmp, "wb") as f:
        f.write(content)
        f.flush()  # flush Python's buffer into the OS kernel buffer
        os.fsync(f.fileno())  # flush OS buffer to physical disk (durability on power loss)

    if LAST_RUN_PATH.exists():
        # Copy current file to .bak before overwriting — one-run undo for post-mortem.
        # shutil.copy2 preserves mtime so .bak timestamp shows when the prior run ran.
        shutil.copy2(LAST_RUN_PATH, bak)

    # Atomic rename: after this line, readers see only the new content.
    tmp.replace(LAST_RUN_PATH)


def _load_json(path: Path) -> dict:
    """Load JSON from path; return empty dict if file is missing or malformed.

    Using try/except rather than if-exists check avoids a race condition where
    the file is deleted between the check and the read (unlikely but correct).
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


# ─── State I/O ────────────────────────────────────────────────────────────────


def load_state() -> dict:
    """Load state.json; return default structure if missing or empty.

    Default state has schema_version so future versions can migrate gracefully.
    synced_session_ids: the primary clobber defense (layer 1)
    fingerprints: mtime+size cache for delta detection
    """
    data = _load_json(STATE_PATH)
    if "schema_version" not in data:
        # First run or deleted state — start fresh
        return {
            "schema_version": 1,
            "synced_session_ids": [],
            "fingerprints": {},
            "last_run_at": None,
        }
    return data


def save_state(state: dict) -> None:
    """Write state dict to state.json atomically.

    Always stamps schema_version before writing — ensures every state file is self-describing.
    """
    state["schema_version"] = 1
    _write_atomic(STATE_PATH, state)


# ─── Config Loading ───────────────────────────────────────────────────────────


def load_config() -> dict | None:
    """Load config.json; return None if missing or not yet initialized.

    None signals "init hasn't been run yet" — callers should gate on this.
    """
    data = _load_json(CONFIG_PATH)
    # Empty dict or missing machine_label means init hasn't been run
    if not data or "machine_label" not in data:
        return None
    return data


def _require_config() -> dict:
    """Load config or abort with a clear message telling the user to run init.

    Exit code 2: pre-flight error (per D-31 exit code policy).
    """
    cfg = load_config()
    if cfg is None:
        print(
            "Error: no config found. Run 'sync_chats.py init --label <name> --vault <path>' first.",
            file=sys.stderr,
        )
        sys.exit(2)
    return cfg


# ─── Session Discovery ────────────────────────────────────────────────────────


def discover_sessions(state: dict) -> list:
    """Walk ~/.claude/projects/ and return unsynced/changed sessions sorted by mtime ascending.

    Returns a list of dicts: [{session_id, project, path, mtime, size}, ...]

    Why depth=2 filter? ~/.claude/projects/ has this layout:
      projects/<project-dir>/<uuid>.jsonl         <- depth 2, these are top-level sessions
      projects/<project-dir>/<uuid>/subagents/... <- depth 4+, these are sub-agent sessions

    Subagent files are sub-components of a parent session and should not be synced independently.
    """
    sessions = []
    synced = set(state.get("synced_session_ids", []))
    fingerprints = state.get("fingerprints", {})

    try:
        jsonl_files = list(PROJECTS_DIR.rglob("*.jsonl"))
    except (OSError, FileNotFoundError):
        return []

    for f in jsonl_files:
        # Depth filter: only top-level session files (depth=2), skip subagent files (depth>2)
        # relative_to gives the path parts below PROJECTS_DIR:
        #   "project-dir/uuid.jsonl" -> 2 parts (include)
        #   "project-dir/uuid/subagents/agent-xxx.jsonl" -> 4 parts (skip)
        try:
            rel_parts = f.relative_to(PROJECTS_DIR).parts
        except ValueError:
            continue

        # Depth filter: keep only files where len(rel_parts) == 2 (top-level sessions)
        if not (len(rel_parts) == 2):
            continue

        session_id = f.stem  # UUID (filename without .jsonl extension)
        project = f.parent.name  # encoded CWD directory name

        # Skip sessions already fully synced (clobber defense layer 1)
        if session_id in synced:
            continue

        try:
            stat = f.stat()
            mtime = stat.st_mtime
            size = stat.st_size
        except OSError:
            continue

        # Skip if fingerprint matches exactly — file hasn't changed since last scan
        cached = fingerprints.get(session_id)
        if cached and cached.get("mtime") == mtime and cached.get("size") == size:
            continue

        sessions.append(
            {
                "session_id": session_id,
                "project": project,
                "path": str(f),
                "mtime": mtime,
                "size": size,
            }
        )

    # Sort by mtime ascending (oldest first) so catch-up runs process in chronological order (D-08)
    sessions.sort(key=lambda s: s["mtime"])
    return sessions


# ─── Session Date Extraction ──────────────────────────────────────────────────


def _get_session_date(jsonl_path: Path) -> str:
    """Return YYYY-MM-DD for the session's start date.

    # Session date from first JSONL timestamp, NOT file mtime (mtime can drift from backups)
    # Verified live: file mtime was 10 days after session because the file was copied by cmd_backup
    """
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 50:  # Only scan first 50 lines for performance
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = obj.get("timestamp")
                if ts:
                    try:
                        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                        return dt.strftime("%Y-%m-%d")
                    except ValueError:
                        continue
    except (IOError, OSError):
        pass

    # Fallback: use file mtime (less accurate but always available)
    try:
        return datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ─── Stub Label Generator ─────────────────────────────────────────────────────


def extract_first_user_message(jsonl_path: Path) -> str:
    """Return the first non-system-reminder user message text from a JSONL session file.

    Handles the two content formats Claude Code uses:
      - content as a plain string (older format)
      - content as a list of typed blocks (newer format: [{type: "text", text: "..."}, ...])
    """
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

                # Top-level records wrap the message in a "message" key;
                # some older records have role/content at top level
                msg = obj.get("message", obj)

                if msg.get("role") != "user":
                    continue

                content = msg.get("content", "")
                # content can be a string or a list of typed blocks
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    # Block list: extract text from blocks where type == "text"
                    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    text = "\n".join(parts).strip()
                else:
                    text = ""

                # Skip Claude Code's injected system reminders (not user content)
                if "<system-reminder>" in text:
                    continue

                # Skip very short messages (e.g. "hi", "ok" — not useful as titles)
                if len(text) <= 5:
                    continue

                return text
    except (IOError, OSError):
        pass

    return ""


def make_stub_label(jsonl_path: Path, session_id: str) -> dict:
    """Build a stub label dict for Phase 1 (no AI labeling yet).

    Returns the same schema that Phase 2's AI labeler will produce (D-03).
    The write subcommand only knows how to read labels from stdin — there is no
    stub-only code path in write. This stub generates the dict and feeds it through
    the same contract.
    """
    text = extract_first_user_message(jsonl_path)

    if not text:
        # D-06: fall back to short session ID when no user message found
        title = f"Untitled {session_id[:8]}"
    else:
        # D-04: first 8 words, single spaces between them
        title = " ".join(text.split()[:8])

    # D-05: stub values for all optional label fields
    return {
        "title": title,
        "gist": None,
        "tags": ["stub"],
        "coherence_score": None,
        "needs_review": True,
    }


# ─── Slug Generator ───────────────────────────────────────────────────────────


def make_slug(title: str, fallback_id: str = "") -> str:
    """Generate a filesystem-safe kebab slug from a title (D-13..D-14).

    Examples:
      "Debug the export markdown function" -> "debug-the-export-markdown-function"
      "Über café résumé" -> "uber-cafe-resume"
      "!!!???" with fallback "abcd1234" -> "abcd1234"
      "a " * 40 -> 60-char max slug
    """
    # NFKD: decomposes accented chars (é -> e + combining accent), then encode drops non-ASCII
    # This turns "café" into "cafe" without a lookup table
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    # Replace any run of non-alphanumeric characters with a single dash
    s = re.sub(r"[^a-z0-9]+", "-", s)
    # Strip leading/trailing dashes from the result
    s = s.strip("-")
    # Truncate to 60 chars at word boundary (rstrip removes any trailing partial-word dash)
    if len(s) > 60:
        s = s[:60].rstrip("-")
    # Fallback for all-non-ASCII or all-punctuation titles
    if not s:
        s = fallback_id[:8] if fallback_id else "untitled"
    return s


# ─── YAML Frontmatter Emitter ─────────────────────────────────────────────────


def emit_frontmatter(fields: dict) -> str:
    """Hand-roll YAML frontmatter string from a fields dict (no pyyaml dependency).

    Key order is stable so Obsidian Dataview queries and grep patterns are predictable.
    Null values render as bare "key:" (no value) — Dataview parses this as null correctly.
    Booleans render lowercase (true/false) per YAML spec.
    Tags render as a block list (one "  - tag" per line) per Obsidian convention.
    synced_at is always double-quoted (contains colons and T which look cleaner quoted).
    """
    # Stable key order — Phase 2 will add fields but order won't change for existing keys
    KEY_ORDER = [
        "title",
        "gist",
        "tags",
        "coherence_score",
        "needs_review",
        "privacy_review",  # Phase 3 D-08 — always present, one of clean/scrubbed/uncertain
        "project",
        "session_id",
        "model",
        "token_count",
        "msg_count",
        "machine",
        "hostname",
        "synced_at",
        "auto_label_hash",
    ]

    lines = []
    for key in KEY_ORDER:
        if key not in fields:
            continue
        value = fields[key]

        if value is None:
            # Bare "key:" — Dataview and Obsidian parse this as null
            lines.append(f"{key}:")
        elif isinstance(value, bool):
            # YAML spec requires lowercase true/false (not Python's True/False)
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key}: {value}")
        elif isinstance(value, list):
            # Block list form — Obsidian renders this correctly in tag pane and Dataview
            # Example:
            #   tags:
            #     - stub
            #     - python
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, str):
            # synced_at always quoted (ISO timestamp contains colons, cleaner quoted)
            if key == "synced_at":
                lines.append(f"{key}: {json.dumps(value)}")
            # Check for YAML-special characters that require quoting
            elif re.search(r"[:#{}[\]|>&!*,]", value):
                # json.dumps produces valid double-quoted YAML string
                lines.append(f"{key}: {json.dumps(value)}")
            else:
                lines.append(f"{key}: {value}")

    return "---\n" + "\n".join(lines) + "\n---\n"


# ─── PII Scrub ────────────────────────────────────────────────────────────────
#
# Pure redaction primitives (Phase 3 Plan 01).
#
# Design notes (see .planning/phases/03-.../03-CONTEXT.md):
#   - Patterns live at module level as compiled regexes — matches existing
#     idiom (re.compile once, reuse forever) and makes them greppable.
#   - Order in SCRUB_PATTERNS matters: specific prefixes (jwt, github_token,
#     aws_key, slack, stripe, anthropic, openai) MUST precede the generic
#     high-entropy UNCERTAIN_PATTERN fallback so named counts are accurate.
#   - `anthropic` MUST precede `openai` because `sk-ant-...` would otherwise
#     be swallowed by the generic `sk-...` OpenAI regex.
#   - IPv4/IPv6 patterns match broadly; the _is_private_ip() skip-list
#     (D-10) filters RFC-1918 / loopback / link-local addresses so debug
#     logs stay useful (threat model = credentials + public identifiers,
#     not private network topology).
#   - Replacement format is `<REDACTED:pattern_name>` (D-12) — greppable,
#     makes post-hoc auditing trivial, never preserves the original bytes.
#   - scrub_content is NOT yet wired into _get_markdown_body — that wiring
#     is Plan 03-02's scope. This plan delivers a pure function only.

# Named patterns — high-confidence matches. Order: specific prefixes before generic.
# Each tuple: (pattern_name, compiled_regex). Names appear in stats dict and in
# <REDACTED:name> replacement tokens (D-12).
SCRUB_PATTERNS = [
    # Email — RFC-5322-ish, case-insensitive (D-09)
    # matches: user@example.com, user.name+tag@sub.example.co
    ("email", re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)),
    # JWT — three base64url segments separated by dots, eyJ prefix (D-09)
    # MUST come before UNCERTAIN_PATTERN so jwt count is accurate
    # matches: eyJhbGciOi...eyJzdWIiOi...signature
    ("jwt", re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")),
    # GitHub tokens — 6 variants (D-09). Combined into one regex under one name.
    # matches: ghp_XXXX..., gho_, ghu_, ghs_, ghr_, github_pat_XXXX...
    ("github_token", re.compile(r"(?:gh[psuor]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{82,})")),
    # AWS access keys — D-09
    # matches: AKIAIOSFODNN7EXAMPLE, ASIA<16 upper/digits>
    ("aws_key", re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    # Slack tokens — D-11
    # matches: xoxb-1234567890-1234567890-<24+ alphanumeric>
    ("slack", re.compile(r"xox[bpoa]-\d{10,}-\d{10,}-[A-Za-z0-9]{24,}")),
    # Stripe keys — D-11 (live and test keys; symmetric coverage)
    # matches: sk_live_XXXX..., sk_test_XXXX...
    ("stripe", re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{24,}")),
    # Anthropic keys — D-11. MUST come BEFORE OpenAI pattern (sk-ant-... would
    # otherwise match the generic sk- OpenAI regex).
    # matches: sk-ant-api-01-XXXX...
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")),
    # OpenAI keys — D-11. Negative lookahead excludes the sk-ant- prefix so
    # Anthropic keys are never double-counted.
    # matches: sk-<40+ alphanumeric>, but NOT sk-ant-<anything>
    ("openai", re.compile(r"sk-(?!ant-)[A-Za-z0-9]{40,}")),
    # Bearer tokens — D-09
    # matches: "Bearer eyJ..." or "Bearer xyz123"
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9_.\-=]+")),
    # Basic auth — D-09
    # matches: "Basic dXNlcjpwYXNz" (base64-encoded user:pass)
    ("basic_auth", re.compile(r"Basic\s+[A-Za-z0-9+/=]+")),
    # IPv4 — standard dotted quad. Skip-list applied post-match in scrub_content (D-10).
    # matches: 8.8.8.8, 127.0.0.1 (skip-list filters private ranges)
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # IPv6 — RFC-4291 full and compressed (:: zero-run compression). Skip-list
    # filters link-local/loopback in scrub_content (D-10).
    # The alternation handles (in order): full 8-group form; x::y with groups
    # on both sides; x:y:...:: trailing zeros; ::x leading zeros; bare ::.
    # matches: 2001:db8::1, fe80::1, ::1, 2001:0db8:...:0001
    (
        "ipv6",
        re.compile(
            r"(?:"
            r"(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"  # full 8 groups
            r"|[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6}"  # x::y with both sides
            r"::[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6}"
            r"|(?:[0-9a-fA-F]{1,4}:){1,7}:[0-9a-fA-F]{0,4}"  # x:...:: or x:...::y
            r"|::[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6}"  # ::x or ::x:y
            r"|::"  # bare :: (unspecified)
            r")"
        ),
    ),
    # US phone numbers — D-09
    # matches: (555) 123-4567, 555-123-4567, 555.123.4567, 5551234567
    ("phone", re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")),
]

# Uncertain fallback — bare 32+ char high-entropy run (D-06, D-11).
# MUST run AFTER all named patterns so we only flag truly unknown secrets.
# Replacements contain `<` and `>` (outside [A-Za-z0-9+/=_-]) which means this
# pattern cannot re-match already-scrubbed content on the second pass.
UNCERTAIN_PATTERN = re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b")


def _is_private_ip(s: str) -> bool:
    """Return True for RFC-1918 private / loopback / link-local IPs (D-10).

    These are preserved unchanged by scrub_content so debug logs stay readable.
    Threat model is credentials and public identifiers, not private network
    topology — an attacker seeing "127.0.0.1" or "192.168.1.1" learns nothing.
    """
    # IPv4 loopback
    if s == "127.0.0.1":
        return True
    # IPv4 RFC-1918 Class A private range
    if s.startswith("10."):
        return True
    # IPv4 RFC-1918 Class C private range (most home routers)
    if s.startswith("192.168."):
        return True
    # IPv4 link-local (APIPA) — 169.254.0.0/16
    if s.startswith("169.254."):
        return True
    # IPv4 RFC-1918 Class B private range — 172.16.0.0 through 172.31.255.255.
    # 172.15.x.x and 172.32.x.x are PUBLIC and must still be scrubbed.
    if s.startswith("172."):
        try:
            second = int(s.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (ValueError, IndexError):
            # Malformed IP — let the caller scrub it rather than preserve.
            pass
    # IPv6 loopback
    if s == "::1":
        return True
    # IPv6 link-local (fe80::/10). `.lower()` because IPv6 is case-insensitive.
    if s.lower().startswith("fe80"):
        return True
    return False


def scrub_content(body: str) -> "tuple[str, dict]":
    """Scrub credentials and PII from body text per D-09/D-10/D-11/D-12.

    Returns (scrubbed_text, stats) where stats has the shape:
        {pattern_name: count for each name in SCRUB_PATTERNS,
         "uncertain": int,
         "total_chars_redacted": int}

    All pattern keys are ALWAYS present (0 if no match) so the log-line format
    in D-21 is stable — callers never KeyError on a zero-count pattern.

    Replacement format: `<REDACTED:pattern_name>` (D-12). Consistent,
    greppable, never preserves original bytes (PRIV-06).

    This function is pure: no I/O, no globals mutated, no match substrings
    leak into the returned stats dict (T-03-01-01 mitigation).
    """
    # Initialize all counts to 0 so the stats dict has a stable shape (D-21).
    # Using a dict comprehension keeps the init in lockstep with SCRUB_PATTERNS —
    # adding a new pattern automatically adds a stats key.
    stats = {name: 0 for name, _ in SCRUB_PATTERNS}
    stats["uncertain"] = 0
    stats["total_chars_redacted"] = 0

    text = body

    # Pass 1: named patterns in SCRUB_PATTERNS order. Specific before generic
    # ensures jwt/github/aws/slack/stripe/anthropic/openai counts are accurate.
    for name, pattern in SCRUB_PATTERNS:
        # Replacement callback closes over `name` via a default-arg binding
        # (`_name=name`) — this is the stdlib idiom for capturing the CURRENT
        # loop value into a closure, avoiding the late-binding pitfall where
        # every closure would otherwise see the last loop value.
        def _replace(match, _name=name):
            matched = match.group(0)
            # IP skip-list: ipv4/ipv6 matches that are private get returned
            # unchanged so private IPs stay in debug logs (D-10).
            if _name in ("ipv4", "ipv6") and _is_private_ip(matched):
                return matched
            stats[_name] += 1
            stats["total_chars_redacted"] += len(matched)
            return f"<REDACTED:{_name}>"

        text = pattern.sub(_replace, text)

    # Pass 2: uncertain fallback — any bare 32+ char high-entropy run that
    # survived the named patterns (D-06). Running on already-scrubbed text is
    # safe because replacement tokens contain `<` and `>`, which are outside
    # the [A-Za-z0-9+/=_-] character class UNCERTAIN_PATTERN requires.
    def _replace_uncertain(match):
        matched = match.group(0)
        stats["uncertain"] += 1
        stats["total_chars_redacted"] += len(matched)
        return "<REDACTED:uncertain>"

    text = UNCERTAIN_PATTERN.sub(_replace_uncertain, text)

    return text, stats


# ─── JSONL Metadata Extraction ────────────────────────────────────────────────


def _extract_session_metadata(jsonl_path: Path) -> dict:
    """Extract model, token_count, and msg_count from a JSONL session file.

    Called by the write pipeline (Plan 03) to populate frontmatter metadata fields.
    Token usage is stored in the "usage" dict inside assistant message objects:
      {"role": "assistant", "usage": {"input_tokens": N, "output_tokens": M, ...}}
    """
    model = None
    token_count = 0
    msg_count = 0

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
                role = msg.get("role")

                if role in ("user", "assistant"):
                    msg_count += 1

                if role == "assistant":
                    # Track the last seen model — later messages use the same or newer model
                    if "model" in msg:
                        model = msg["model"]
                    # usage dict contains token counts for this assistant turn
                    # (cache_creation_input_tokens and cache_read_input_tokens also exist
                    #  but we only count the billable input + output tokens here)
                    usage = msg.get("usage", {})
                    if usage:
                        token_count += usage.get("input_tokens", 0)
                        token_count += usage.get("output_tokens", 0)
    except (IOError, OSError):
        pass

    return {
        "model": model or "unknown",
        "token_count": token_count,
        "msg_count": msg_count,
    }


# ─── Write Pipeline Helpers ───────────────────────────────────────────────────


def _write_if_not_exists(path: Path, content_bytes: bytes) -> bool:
    """Write bytes to path only if it does not already exist. Returns True if written.

    # O_CREAT|O_EXCL is atomic on POSIX -- no race between check and create
    # This is clobber defense layer 2: even if state.json is lost, we never overwrite an
    # existing vault file. os.O_EXCL guarantees the open() fails if the file already exists.
    """
    try:
        # O_CREAT: create the file; O_EXCL: fail if it already exists (atomic check+create)
        # 0o644: owner read+write, group+others read — standard file permissions
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except OSError as e:
        if e.errno == errno.EEXIST:
            return False  # file already exists -- clobber defense layer 2
        raise
    try:
        os.write(fd, content_bytes)
        os.fsync(fd)  # flush to disk before close — durability across power loss
    finally:
        os.close(fd)
    return True


def _get_markdown_body(session_id: str) -> "tuple[str, dict]":
    """Call claude-chat.py export --format md --stdout, scrub, return (body, scrub_stats).

    Structural ordering enforcement (Phase 3 D-03): the raw (unscrubbed) body NEVER
    escapes this function. The return type is a tuple, which means any caller that
    accidentally treated it as str would get a TypeError — the pipeline CANNOT
    regress silently.

    Why subprocess instead of import? claude-chat.py contains a hyphen, which makes it
    unimportable by Python's import system. The subprocess boundary is intentional and
    enforced by the filename (see INTEGRATIONS.md).

    Why scrub in here rather than in cmd_write? Function-boundary enforcement of the
    scrub → label → write ordering (D-04). A reviewer reading cmd_write sees
    `body, stats = _get_markdown_body(sid)` followed by labeling/hashing/writing —
    there is no API to get raw content, so labels CANNOT see pre-scrub data.
    """
    # SYNC_CHATS_CLAUDE_CLI env var lets tests (and the canary script) point at a mock
    # instead of the real claude-chat.py — same pattern as CLAUDE_CHAT_HOME override (D-29).
    # Production path: claude-chat.py side-by-side with this script, falling back to cwd.
    _cli_override = os.environ.get("SYNC_CHATS_CLAUDE_CLI")
    if _cli_override:
        claude_chat_path = Path(_cli_override)
    else:
        claude_chat_path = Path(__file__).resolve().parent / "claude-chat.py"
        if not claude_chat_path.exists():
            claude_chat_path = Path.cwd() / "claude-chat.py"

    try:
        result = subprocess.run(
            ["python3", str(claude_chat_path), "export", session_id, "--format", "md", "--stdout"],
            capture_output=True,  # capture stdout and stderr separately (no terminal output)
            text=True,  # decode bytes to str using system encoding
            check=True,  # raise CalledProcessError on non-zero exit code
        )
        raw_body = result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Export failed for session {session_id}: {e}\nstderr: {e.stderr}") from e

    # Scrub happens INSIDE this function (D-03) so raw body never escapes.
    # The returned body is the scrubbed version; auto_label_hash is computed
    # against it in cmd_write, which means crash reconciliation still works
    # (D-05: hash is deterministically reproducible from the stored body).
    scrubbed_body, scrub_stats = scrub_content(raw_body)
    return scrubbed_body, scrub_stats


def _derive_privacy_review(stats: dict) -> str:
    """Map scrub stats to one of three privacy_review values per D-08.

    Values (always one of these three — field is never omitted):
      "clean"     — no redactions at all
      "scrubbed"  — one or more known-pattern hits, zero uncertain hits
      "uncertain" — at least one high-entropy fallback hit (D-06) — file still
                    written (fail-open-with-flag per PRIV-05) but needs_review
                    is forced to true (D-07) so it surfaces in the review queue.
    """
    if stats.get("uncertain", 0) > 0:
        return "uncertain"
    # Sum all non-bookkeeping counts — every named pattern key contributes
    named_total = sum(v for k, v in stats.items() if k not in ("uncertain", "total_chars_redacted"))
    if named_total > 0:
        return "scrubbed"
    return "clean"


def _log_scrub_stats(session_id: str, stats: dict) -> None:
    """Emit one scrub log line to sync.log per D-21. Skip if zero scrubs (D-22).

    Log format (D-21, verbatim — any deviation breaks downstream log parsers):
        scrub session=<short_id> patterns={email:3, jwt:1, ...} total_chars=287

    Safety (PRIV-06): NEVER includes matched substrings. Only pattern names
    (module constants) and integer counts/char-lengths. Zero-count entries are
    omitted so the line stays grep-friendly.
    """
    # D-22: no log line for clean sessions — reduces noise in sync.log.
    # The `uncertain` count is user-visible signal, so it IS included in the
    # named_total check (an uncertain-only hit still warrants a log line).
    named_total = sum(v for k, v in stats.items() if k != "total_chars_redacted")
    if named_total == 0:
        return

    # Short id = first 8 chars of UUID (D-21).
    short_id = session_id[:8]
    # Stable key order for grep-friendly logs — sort keys, omit zero counts
    # (zero counts would add noise; D-21 example shows only non-zero pattern entries).
    nonzero = {k: v for k, v in stats.items() if k != "total_chars_redacted" and v > 0}
    # Render {name:count, name:count} with sorted keys for determinism.
    patterns_str = "{" + ", ".join(f"{k}:{v}" for k, v in sorted(nonzero.items())) + "}"
    total_chars = stats.get("total_chars_redacted", 0)
    _log_sync(f"scrub session={short_id} patterns={patterns_str} total_chars={total_chars}")


def _read_frontmatter_field(vault_file: Path, key: str) -> "str | None":
    """Read a single scalar frontmatter field's value from a vault file.

    Scans only the first 30 lines (frontmatter is always near top — D-20 efficiency cap).
    Returns the string value after `key: ` or None if the key isn't present or the file
    can't be read. Used by crash reconciliation to inspect both `auto_label_hash` and
    `session_id` without reading the whole file.

    Why hand-rolled instead of pyyaml? Zero-deps invariant (PROJECT.md). Frontmatter is
    simple enough (one scalar per line, no nested structures used) that a 15-line scan
    is cheaper than a dependency.
    """
    try:
        with open(vault_file, "r", encoding="utf-8", errors="replace") as f:
            in_frontmatter = False
            delimiter_count = 0
            prefix = f"{key}:"
            for i, line in enumerate(f):
                if i >= 30:  # frontmatter always near top — bounded scan (D-20)
                    break
                stripped = line.strip()
                if stripped == "---":
                    delimiter_count += 1
                    in_frontmatter = delimiter_count == 1
                    if delimiter_count == 2:
                        break  # past frontmatter — stop looking
                    continue
                if in_frontmatter and stripped.startswith(prefix):
                    parts = stripped.split(":", 1)
                    if len(parts) == 2:
                        return parts[1].strip()
    except (IOError, OSError):
        pass
    return None


def _read_auto_label_hash(vault_file: Path) -> "str | None":
    """Read the auto_label_hash value from an existing vault file's frontmatter.

    Thin wrapper over _read_frontmatter_field — preserves Phase 1's API so any
    existing callers/tests continue to work unchanged (D-20: factor without breaking).

    Used for crash reconciliation (D-25): if the process crashed after writing the file
    but before updating state.json, we re-derive the expected hash and compare to the
    stored hash to confirm the file is the one we would have written.
    """
    return _read_frontmatter_field(vault_file, "auto_label_hash")


def _reconcile_crash(vault_file: Path, body_bytes: bytes, session_id: str, state: dict, fingerprint: dict) -> str:
    """Handle the case where vault file exists but state.json doesn't know about it.

    Three-way return (D-18):
      "reconciled" — same session, hash matches → update state + skip (crash recovery)
      "edited"     — same session, hash differs → REFUSE + log + record session (D-19:
                     user manually edited; respect their edits; never touch again)
      "collision"  — different session occupying the same slug → fall through to -2/-3
                     naming loop in cmd_write (D-15 preserved)

    Per D-17: the previous implementation conflated "edited" with "collision" and
    fell into the slug-collision fallback, creating orphan `<slug>-2.md` files with
    fresh auto-labels. That was the Phase 1 bug closing SC#5 closes.
    """
    # Re-derive the hash we would compute for this session's body bytes
    expected_hash = hashlib.sha256(body_bytes).hexdigest()
    existing_session_id = _read_frontmatter_field(vault_file, "session_id")
    existing_hash = _read_frontmatter_field(vault_file, "auto_label_hash")

    # Case 1: different session → true slug collision (D-15 semantics unchanged)
    if existing_session_id and existing_session_id != session_id:
        return "collision"

    # From here on: existing_session_id is None OR equals session_id.
    # If it's None (malformed / legacy file), fall back to hash-based reconciliation
    # matching Phase 1's original behavior, to avoid being more restrictive than
    # necessary on files that predate Phase 3's session_id frontmatter field.

    if existing_hash and expected_hash == existing_hash:
        # Crash recovery: the file is exactly what we would have written — update state
        if session_id not in state["synced_session_ids"]:
            state["synced_session_ids"].append(session_id)
        state["fingerprints"][session_id] = fingerprint
        save_state(state)
        return "reconciled"

    # Same session, different hash → user edited. REFUSE per D-19.
    # (cmd_write will do the logging + state recording; we just classify here.)
    if existing_session_id == session_id:
        return "edited"

    # Fallback: existing_session_id is None AND hash mismatch. Treat as collision
    # to stay conservative — create a new file with a -2 suffix. This matches
    # Phase 1's original behavior for malformed/unknown-origin vault files.
    return "collision"


def _log_sync(message: str) -> None:
    """Append a timestamped line to sync.log (D-33).

    Log is append-only; no rotation in Phase 1. For personal use, this file is
    unlikely to grow past a few MB. cat ~/.claude-chat/sync.log to inspect.
    """
    # Create the parent directory if it doesn't exist (first run before init creates it)
    os.makedirs(str(LOG_PATH.parent), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        # ISO 8601 timestamp + space + message + newline
        f.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _resolve_vault_filename(config: dict, label: dict, session_date: str, session_id: str) -> Path:
    """Build the base vault Path for a session (no collision suffix applied here).

    Filename convention: <machine>--YYYY-MM-DD--<slug>.md (per D-13)

    NOTE: This function intentionally does NOT handle collisions. The write pipeline
    must first attempt the base name so that crash reconciliation (_reconcile_crash) can
    determine whether an existing file is a crash-recovery case or a true slug collision.
    Collision suffixes (-2, -3, ...) are applied in cmd_write ONLY after reconciliation
    confirms the existing file belongs to a different session (D-15).
    """
    slug = make_slug(label["title"], session_id)
    machine = config["machine_label"]
    base_name = f"{machine}--{session_date}--{slug}.md"

    # Chats/ subfolder in vault — create if needed (exist_ok: safe to call repeatedly)
    vault_dir = Path(config["vault_path"]) / "Chats"
    os.makedirs(str(vault_dir), exist_ok=True)

    return vault_dir / base_name


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_init(args) -> None:
    """Initialize or display sync_chats config.

    First run: --label and --vault are required.
    Re-run with new values: silently overwrites config (D-22).
    Re-run with no flags and existing config: prints current config and exits (D-22).
    """
    # Always check CLAUDE_CHAT_HOME is not iCloud (D-23)
    _assert_not_icloud(CLAUDE_CHAT_HOME)

    has_label = args.label is not None
    has_vault = args.vault is not None
    config_exists = CONFIG_PATH.exists()

    if not has_label and not has_vault:
        if config_exists:
            # Show current config and exit — useful for inspecting what's set
            cfg = _load_json(CONFIG_PATH)
            print(json.dumps(cfg, indent=2, sort_keys=True))
            sys.exit(0)
        else:
            print(
                "Error: Both --label and --vault are required on first run.\n"
                "Example: sync_chats.py init --label mbp --vault /path/to/vault",
                file=sys.stderr,
            )
            sys.exit(2)

    # If only one flag is provided and no existing config, require both
    if not (has_label and has_vault) and not config_exists:
        print(
            "Error: Both --label and --vault are required on first run.\n"
            "Example: sync_chats.py init --label mbp --vault /path/to/vault",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate vault path: must be absolute and exist as a directory
    vault_path = args.vault if has_vault else _load_json(CONFIG_PATH).get("vault_path", "")
    if vault_path:
        if not os.path.isabs(vault_path):
            print(f"Error: vault path must be absolute, got: {vault_path}", file=sys.stderr)
            sys.exit(2)
        if not os.path.isdir(vault_path):
            print(f"Error: vault path does not exist or is not a directory: {vault_path}", file=sys.stderr)
            sys.exit(2)

    # Build config dict (D-21 schema)
    config = {
        "schema_version": 1,
        "machine_label": args.label if has_label else _load_json(CONFIG_PATH).get("machine_label"),
        "vault_path": vault_path,
    }

    # Create CLAUDE_CHAT_HOME if it doesn't exist yet
    # exist_ok=True: safe to call even if directory already exists
    os.makedirs(str(CLAUDE_CHAT_HOME), exist_ok=True)

    _write_atomic(CONFIG_PATH, config)
    print(f"Config written to {CONFIG_PATH}")
    print(f"  machine_label: {config['machine_label']}")
    print(f"  vault_path:    {config['vault_path']}")


def cmd_scan(args) -> None:
    """Print a JSON array of unsynced/changed sessions to stdout.

    Output: [{session_id, project, path, mtime, size}, ...] sorted by mtime ascending.
    Requires init to have been run (loads config to enforce this).
    """
    _require_config()
    state = load_state()
    sessions = discover_sessions(state)
    print(json.dumps(sessions, indent=2))


def _write_session(session_id: str, label: dict, config: dict, state: dict) -> str:
    """Write a single session to the Obsidian vault and update state.

    Extracted from cmd_write so cmd_once (Plan 02) can call this in-process
    with a stub dict instead of piping through stdin (D-02 stdin contract
    preservation: cmd_write still reads stdin, then calls here).

    Steps 3–9 of the original cmd_write docstring:
      3. Check clobber defense layer 1 (synced_session_ids)
      4. Locate JSONL file, get session date and metadata
      5. Get markdown body via subprocess to claude-chat.py export --stdout
      6. Build frontmatter with all 15 fields including auto_label_hash
      7. Write via O_CREAT|O_EXCL (clobber defense layer 2)
      8. If file exists: reconcile or refuse (clobber defense layer 3)
      9. Update state atomically per-session

    Returns one of:
      "synced"      — session written for the first time
      "skipped"     — session already in synced_session_ids (layer 1 guard)
      "reconciled"  — crash-recovery write (layer 3), state updated
      "edited"      — user edited the vault file; recorded in state, not re-written

    Raises ValueError for invalid label (missing 'title'). Other unexpected
    exceptions are allowed to propagate — callers (cmd_write, cmd_once) decide
    the exit-code policy.
    """
    # Validate required "title" field (D-02): missing title is a fatal error.
    # WHY raise rather than sys.exit: _write_session is a helper; cmd_write and
    # cmd_once each handle the exit-code policy differently (D-10 / D-31).
    if "title" not in label:
        raise ValueError("label dict must contain a 'title' field (D-02)")

    # Step 3: Clobber defense layer 1 — check synced_session_ids (CORE-08)
    # This is the primary guard: if we've already synced this session, skip immediately.
    if session_id in state.get("synced_session_ids", []):
        _log_sync("Synced 0 new, 1 skipped (already synced), 0 failed.")
        return "skipped"

    # Step 4a: Locate the JSONL file for this session_id.
    # Walk PROJECTS_DIR and find the file whose stem matches the session UUID.
    jsonl_path = None
    try:
        for candidate in PROJECTS_DIR.rglob("*.jsonl"):
            if candidate.stem == session_id:
                # Only consider depth=2 files (top-level sessions, not subagents).
                # Depth-1 would be a project dir itself; depth>2 would be a sub-agent.
                try:
                    rel_parts = candidate.relative_to(PROJECTS_DIR).parts
                except ValueError:
                    continue
                if len(rel_parts) == 2:
                    jsonl_path = candidate
                    break
    except (OSError, FileNotFoundError):
        pass

    if jsonl_path is None:
        raise FileNotFoundError(f"session {session_id} not found in {PROJECTS_DIR}")

    # Step 4b: Get session date from JSONL (not mtime — mtime can drift from backups).
    session_date = _get_session_date(jsonl_path)

    # Step 5: Get scrubbed markdown body + scrub stats (D-03 structural enforcement).
    # _get_markdown_body returns a tuple — raw body does NOT escape that function.
    body, scrub_stats = _get_markdown_body(session_id)

    # D-21 / D-22: emit one scrub log line per scrubbed session. Skipped for clean sessions.
    _log_scrub_stats(session_id, scrub_stats)

    # Step 4c: Extract session metadata (model, token_count, msg_count).
    metadata = _extract_session_metadata(jsonl_path)

    # Step 6a: Compute auto_label_hash = sha256 of body bytes (not frontmatter).
    # `body` is the SCRUBBED version (D-05) — crash reconciliation reproduces the same
    # hash by re-rendering and re-scrubbing, which is deterministic.
    body_bytes = body.encode("utf-8")

    # D-03: cmd_once passes auto_label_hash_override="stub" so the interactive SKILL
    # can detect stub files (auto_label_hash: stub in frontmatter) and re-label them.
    # Real AI-labeled files get the SHA-256 hash; stubs get the literal "stub" sentinel.
    # Any value OTHER than "stub" is ignored — defensive against future callers.
    override = label.get("auto_label_hash_override")
    if override == "stub":
        # D-03: write the sentinel instead of the real hash.
        # The SKILL matches on 'auto_label_hash: stub' to find files needing re-label.
        auto_label_hash = "stub"
    else:
        # Default (Phase 1 D-24): SHA-256 of scrubbed body bytes, unchanged.
        auto_label_hash = hashlib.sha256(body_bytes).hexdigest()

    # D-08: derive privacy_review from scrub stats. Always present in frontmatter.
    privacy_review = _derive_privacy_review(scrub_stats)

    # D-07: force needs_review=true when uncertain, overriding any label value of false.
    # Fail-open-with-flag (PRIV-05): the chat IS still written, just flagged for audit.
    needs_review_value = label.get("needs_review", True)
    if privacy_review == "uncertain":
        needs_review_value = True

    # Step 6b: Build frontmatter fields dict (all 15 fields with privacy_review).
    # Fields come from four sources: label (caller), metadata (JSONL), config, computed.
    fields = {
        # From label (caller-supplied) — D-02 schema
        "title": label["title"],
        "gist": label.get("gist"),
        "tags": label.get("tags", ["stub"]),
        "coherence_score": label.get("coherence_score"),
        "needs_review": needs_review_value,
        # From Phase 3 scrub (D-08)
        "privacy_review": privacy_review,
        # From session metadata (JSONL)
        "model": metadata["model"],
        "token_count": metadata["token_count"],
        "msg_count": metadata["msg_count"],
        # From config
        "machine": config["machine_label"],
        # Computed
        "project": jsonl_path.parent.name,
        "session_id": session_id,
        "hostname": socket.gethostname(),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "auto_label_hash": auto_label_hash,
    }

    # Step 6c: Render frontmatter string.
    frontmatter_str = emit_frontmatter(fields)

    # Step 6d: Build final content: frontmatter + blank line + body.
    # The blank line between frontmatter and body is standard Obsidian convention.
    final_bytes = (frontmatter_str + "\n" + body).encode("utf-8")

    # Step 7: Resolve target vault filename (handles slug collision per D-15).
    target = _resolve_vault_filename(config, label, session_date, session_id)

    # Step 8: Clobber defense layer 2 — O_CREAT|O_EXCL atomic create (CORE-09).
    written = _write_if_not_exists(target, final_bytes)

    if not written:
        # File already exists — run crash reconciliation (D-25 / clobber layer 3).
        # Distinguishes two cases:
        #   "reconciled": our file from a previous crash — update state and skip
        #   "collision":  a different session's file with the same slug — try -2, -3, ...
        fingerprint = {
            "mtime": jsonl_path.stat().st_mtime,
            "size": jsonl_path.stat().st_size,
        }
        reconcile_result = _reconcile_crash(target, body_bytes, session_id, state, fingerprint)
        if reconcile_result == "reconciled":
            _log_sync("Synced 0 new, 1 skipped (already synced), 0 failed.")
            return "reconciled"
        elif reconcile_result == "edited":
            # D-19: user manually edited the vault file. REFUSE to touch it.
            # Record the session in state so no future run re-emits it from scan
            # (clobber defense layer 3 doing its job — a permanent decision:
            # once edited, the skill never writes over the user's work).
            if session_id not in state["synced_session_ids"]:
                state["synced_session_ids"].append(session_id)
            state["fingerprints"][session_id] = fingerprint
            state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state)

            # D-19 exact log message — greppable by canary tests and user audits.
            _log_sync(
                f"skipped: user_edited (auto_label_hash mismatch, session_id matches) "
                f"session={session_id[:8]} file={target.name}"
            )
            return "edited"
        else:
            # True slug collision: a different session produced the same filename.
            # Per D-15: try appending -2, -3, ... -99 until a free name is found.
            vault_dir = target.parent
            slug_base = target.stem  # e.g. "mbp--2026-03-19--debug-export"
            written = False
            for i in range(2, 100):
                target = vault_dir / f"{slug_base}-{i}.md"
                written = _write_if_not_exists(target, final_bytes)
                if written:
                    break
            if not written:
                raise RuntimeError(
                    f"Could not find a free filename after 99 attempts "
                    f"(slug base: {slug_base}). Manual intervention required."
                )

    # Step 9: Update state atomically per-session (D-26).
    # Do this immediately after each write — crash-safe even if later sessions fail.
    state["synced_session_ids"].append(session_id)
    state["fingerprints"][session_id] = {
        "mtime": jsonl_path.stat().st_mtime,
        "size": jsonl_path.stat().st_size,
    }
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    _log_sync(f"wrote {target.name} for session {session_id[:8]}")
    _log_sync("Synced 1 new, 0 skipped (already synced), 0 failed.")
    return "synced"


def cmd_write(args) -> None:
    """Write a single session to the Obsidian vault.

    Thin wrapper around _write_session (extracted in Phase 5 Plan 01).

    Full pipeline per D-24:
      1. Require config (abort if not initialized)
      2. Read label JSON from stdin (D-01/D-02)
      3–9. Delegate to _write_session (core write logic)

    WHY a thin wrapper: cmd_once (Plan 02) needs to call the same write logic
    in-process with a stub dict, without going through stdin. Extracting the
    core into _write_session lets both callers share the logic while each
    retaining their own entry-point (stdin-based vs in-process).
    """
    config = _require_config()
    state = load_state()

    # Step 2: Read label JSON from stdin only — no --stub flag, no --title flag (D-01/D-03).
    # The Phase 1 stub generator pipes through this same path, just like Phase 2 will.
    label_input = sys.stdin.read()
    try:
        label = json.loads(label_input)
    except json.JSONDecodeError as e:
        print(f"Error: invalid label JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate required "title" field (D-02): missing title is a fatal error.
    if "title" not in label:
        print("Error: label JSON must contain a 'title' field.", file=sys.stderr)
        sys.exit(1)

    # Steps 3–9: delegate to _write_session.
    try:
        result = _write_session(args.session_id, label, config, state)
    except SystemExit:
        raise  # let sys.exit() pass through
    except Exception as e:
        # Per D-30: catch all exceptions, print useful error, exit 1.
        print(
            f"Error writing session {args.session_id}: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Print status message matching existing stdout contract (callers like the SKILL
    # parse these messages). Behavior is identical to pre-extraction cmd_write.
    if result == "synced":
        # We don't have `target` here; _write_session logs it internally via _log_sync.
        # Print a generic success line — the SKILL only checks for non-error output.
        _log_sync(f"cmd_write synced session {args.session_id[:8]}")
        print(f"synced: {args.session_id}")
    elif result == "skipped":
        print("skipped: already_synced")
    elif result == "reconciled":
        print("skipped: already_synced (recovered from interrupted write)")
    elif result == "edited":
        print(f"skipped: user_edited")


def cmd_status(args) -> None:
    """Show sync status summary (CORE-13 + OBSERV-04).

    Primary path (D-17): read last_run.json and display the D-23 canonical
    summary plus run metadata. Fallback: use state.last_run_at until the first
    --once fires on this machine (covers the one-run migration window).
    """
    config = _require_config()
    state = load_state()

    if not PROJECTS_DIR.exists():
        print(f"Note: No Claude projects directory found at {PROJECTS_DIR}")
        pending = []
    else:
        pending = discover_sessions(state)

    # D-17 one-run migration: prefer last_run.json; fall back to state.last_run_at
    # until the first --once fires. `_load_json` returns {} on missing/malformed
    # — the truthy check below treats both as "fall back".
    last_run_data = _load_json(LAST_RUN_PATH)

    if last_run_data:
        # Primary path — canonical summary + run metadata.
        print(_format_summary(last_run_data))
        print(f"Run at:     {last_run_data.get('run_finished_at', 'unknown')}")
        print(f"Machine:    {last_run_data.get('machine_label', config['machine_label'])}")
        print(f"Trigger:    {last_run_data.get('trigger', 'unknown')}")
        print(f"Hostname:   {socket.gethostname()}")
        print(f"Vault:      {config['vault_path']}")
        print(f"Synced:     {len(state.get('synced_session_ids', []))} sessions")
        print(f"Pending:    {len(pending)} sessions")
    else:
        # Fallback — preserves existing Phase 1 CORE-13 output verbatim.
        last_run = state.get("last_run_at") or "never"
        print(f"Machine:    {config['machine_label']}")
        print(f"Hostname:   {socket.gethostname()}")
        print(f"Vault:      {config['vault_path']}")
        print(f"Last run:   {last_run}")
        print(f"Synced:     {len(state.get('synced_session_ids', []))} sessions")
        print(f"Pending:    {len(pending)} sessions")


def cmd_mine(args) -> None:
    """Shell out to `mempalace mine` after a sync run (MEM-01/02/03).

    Reports one of three outcomes via stdout:
      mempalace_mined: true
      mempalace_mined: false (<reason>)
      mempalace_mined: skipped (<reason>)

    Happy path only in Plan 01; error/timeout paths added in Plan 02.

    Python beginner note: Path / "Chats" uses pathlib's overloaded '/' operator
    to join path segments, same as os.path.join but more readable. str() converts
    the Path object to a plain string that subprocess.run expects in its argv list.
    """
    config = _require_config()
    # config["vault_path"] is the Obsidian vault ROOT; Chats/ is the subfolder
    vault_chats = str(Path(config["vault_path"]) / "Chats")

    # D-08: binary-not-found handling. shutil.which() searches PATH for the
    # binary, returning its full path or None if not found.
    # T-4-02 mitigation: graceful degradation — second Mac without mempalace
    # installed still completes sync; vault writes succeed regardless (MEM-02).
    if shutil.which("mempalace") is None:
        _log_sync("mempalace: command not found — skipping mine")
        print("mempalace_mined: skipped (command not found)")
        return

    # MEM-01 (per D-01, D-04): list-form argv, no shell=True. T-4-01 mitigation.
    # Using a list instead of a shell string means vault_chats metacharacters
    # (spaces, semicolons, etc.) are passed literally to the process, not
    # interpreted by the shell — this prevents command injection.
    try:
        result = subprocess.run(
            ["mempalace", "mine", vault_chats, "--mode", "convos", "--extract", "general"],
            capture_output=True,
            text=True,
            timeout=300,  # D-09; T-4-04 mitigation (DoS via hung process)
        )
    except subprocess.TimeoutExpired:
        # Python beginner note: subprocess.run in Python 3.3+ kills the child
        # process automatically before raising TimeoutExpired — no manual
        # process.kill() needed. Verified against Python 3.14 in RESEARCH.md.
        _log_sync("mempalace: timed out after 300s — skipping mine")
        print("mempalace_mined: false (timeout after 300s)")
        return

    if result.returncode != 0:
        # D-07: fail-soft. D-11: log only on failure, only last ~20 lines,
        # to avoid polluting sync.log on healthy runs and to bound info-disclosure
        # blast radius if mempalace ever echoed content in its errors (T-4-03).
        # Python idiom: splitlines()[-20:] slices the last 20 lines of a list.
        # If stderr has <20 lines, slicing returns what's there — no IndexError.
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:])
        _log_sync(f"mempalace mine failed (exit {result.returncode}):\n{stderr_tail}")
        print(f"mempalace_mined: false (exit {result.returncode})")
        return

    print("mempalace_mined: true")


# ─── SessionEnd hook entry point (Phase 5 Plan 02) ────────────────────────────


def _format_summary(run: dict) -> str:
    """Build the OBSERV-01 canonical summary line (D-22: sole producer).

    Pure function — no I/O, no logging, no side effects. Every caller that
    needs the summary string MUST call this helper so the format stays
    byte-identical across cmd_once, cmd_status, and future integrations.

    D-23 format (LOCKED):
        Synced {N} new chats, {M} skipped (already-synced),
        {K} flagged for review, mempalace_mined: {status}[ ({reason})]

    The parenthesized reason is appended iff `mempalace_mined` is "false" or
    "skipped" AND `mempalace_reason` is non-null (Phase 4 D-15). When status
    is "true", the reason is never appended even if one is present.

    Python beginner note: `dict.get(key, default)` returns the default if the
    key is missing. Using sparse defaults here makes the helper defensive
    against malformed last_run.json (e.g. hand-edited or from a future schema).
    """
    synced = run.get("synced", 0)
    skipped = run.get("skipped", 0)
    flagged = run.get("flagged_for_review", 0)
    mined = run.get("mempalace_mined", "skipped")
    reason = run.get("mempalace_reason")

    base = (
        f"Synced {synced} new chats, {skipped} skipped (already-synced), "
        f"{flagged} flagged for review, mempalace_mined: {mined}"
    )
    # D-15: reason is appended only when status is not "true".
    if mined != "true" and reason:
        return f"{base} ({reason})"
    return base


def cmd_once(args) -> None:
    """Run one full sync-all pass using stub labels — the SessionEnd hook entry.

    Flow (D-19 / RESEARCH §Pattern 4):
      1. Capture run_started timestamp.
      2. _require_config() — exits 2 on pre-flight (D-31 / D-10).
      3. Discover unsynced sessions via discover_sessions(state).
      4. For each: build stub label, tag with auto_label_hash_override='stub' (D-03),
         call _write_session in-process (D-02: no stdin).
      5. Write last_run.json (D-11) via _write_last_run.
      6. Log one run-start + one run-finish line (OBSERV-02).
      7. Print summary to stdout (OBSERV-01). Exit 0 / 1 per D-10.

    Intentionally does NOT call cmd_mine (D-08) — mining is a separate step.
    Intentionally does NOT read stdin (D-02 / Pitfall 2).

    Python beginner note: errors are collected as typed dicts rather than raw
    exception objects so last_run.json stays JSON-serializable. Only the first
    10 errors are kept (D-13) to bound the file size if something goes very
    wrong at 3 a.m.
    """
    run_started = datetime.now(timezone.utc).isoformat()

    # Preflight: _require_config() calls sys.exit(2) on missing/invalid config.
    config = _require_config()
    state = load_state()

    machine_label = config.get("machine_label", "unknown")
    _log_sync(f"run-start trigger=once machine={machine_label}")

    sessions = discover_sessions(state)

    synced = 0
    skipped = 0
    failed = 0
    flagged_for_review = 0
    errors: list = []

    for sess in sessions:
        sid = sess["session_id"]
        try:
            # Build stub label; inject D-03 sentinel so _write_session writes
            # auto_label_hash: stub (Plan 04's relabel subcommand uses this
            # to find re-labelable files).
            stub = make_stub_label(Path(sess["path"]), sid)
            stub["auto_label_hash_override"] = "stub"

            result = _write_session(sid, stub, config, state)
            if result == "synced":
                synced += 1
                # D-16: every stub-synced file starts life flagged for review.
                flagged_for_review += 1
            else:
                # "skipped" | "reconciled" | "edited" — all count as skipped
                # for the per-run counters; sync.log already captured details.
                skipped += 1
        except Exception as e:
            failed += 1
            if len(errors) < 10:  # D-13
                errors.append(
                    {
                        "session_id": sid,
                        "error_class": type(e).__name__,
                        "error_message": str(e),
                    }
                )

    exit_code = 1 if failed > 0 else 0

    last_run = {
        "schema_version": 1,
        "run_started_at": run_started,
        "run_finished_at": datetime.now(timezone.utc).isoformat(),
        "trigger": "once",
        "machine_label": machine_label,
        "hostname": socket.gethostname(),
        "synced": synced,
        "skipped": skipped,
        "failed": failed,
        "flagged_for_review": flagged_for_review,
        # D-15: --once never mines — mining is a later/interactive step.
        "mempalace_mined": "skipped",
        "mempalace_reason": "not run by hook (--once skips mine)",
        "exit_code": exit_code,
        "errors": errors,
    }

    _write_last_run(last_run)

    # D-22 / Plan 03: _format_summary is the sole producer of the OBSERV-01
    # canonical summary string. cmd_once, cmd_status, and future integrations
    # all route through it to stay byte-identical.
    summary = _format_summary(last_run)

    _log_sync(f"run-finish trigger=once {summary}")
    print(summary)

    if failed > 0:
        # D-21 / Pitfall 6: one short line on stderr — no stack traces.
        print(
            f"sync_chats --once: {failed} session(s) failed; see {LOG_PATH}",
            file=sys.stderr,
        )

    sys.exit(exit_code)


# ─── Relabel subcommand (Phase 5 Plan 04 — HOOK-04 / D-04 / D-05) ─────────────


def _split_frontmatter_and_body(path: Path) -> "tuple[dict, bytes]":
    """Split a vault file into (frontmatter fields dict, body bytes).

    Minimal YAML parser — only the scalar/list forms emit_frontmatter writes.
    Returns ({}, b"") if the file has no frontmatter delimiters (defensive).

    Python beginner note: `bytes` vs `str` matters here because the hash that
    gates D-05 re-label is computed over body BYTES (stable across encodings).
    We read the file as text for the YAML parse then re-encode the body for
    the hash; the body never round-trips through any transform that could
    alter its bytes (no normalization, no rstrip, no newline coercion).
    """
    text = path.read_text(encoding="utf-8")
    # Expected layout: "---\n<fm>\n---\n<body>"
    if not text.startswith("---\n"):
        return {}, b""

    # Split off the leading "---\n", then the block up to the next "---\n".
    after_first = text[4:]
    end = after_first.find("\n---\n")
    if end == -1:
        return {}, b""

    fm_block = after_first[:end]
    body = after_first[end + len("\n---\n") :]

    fields: dict = {}
    current_list_key: "str | None" = None
    for line in fm_block.split("\n"):
        if not line:
            current_list_key = None
            continue
        if line.startswith("  - ") and current_list_key is not None:
            # First list item: replace the seeded None with an empty list.
            if not isinstance(fields.get(current_list_key), list):
                fields[current_list_key] = []
            fields[current_list_key].append(line[4:].strip())
            continue
        # Scalar or list-header line.
        current_list_key = None
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            # Either a null value (bare `key:`) or the start of a block list.
            # We can't tell from this line alone — look ahead by seeding an
            # empty list; if no `  - ` lines follow, we treat it as None below.
            fields[key] = None
            current_list_key = key
            continue
        # Typed scalar parse — strings stay strings unless they look like
        # bool/int. This mirrors how emit_frontmatter writes them.
        if rest in ("true", "false"):
            fields[key] = rest == "true"
        else:
            try:
                fields[key] = int(rest)
            except ValueError:
                # Strip surrounding quotes if json.dumps wrapped the value.
                if rest.startswith('"') and rest.endswith('"'):
                    try:
                        fields[key] = json.loads(rest)
                    except json.JSONDecodeError:
                        fields[key] = rest.strip('"')
                else:
                    fields[key] = rest

    # Clean up bare `key:` entries whose list stayed empty — treat as None.
    for k, v in list(fields.items()):
        if v == []:
            fields[k] = None

    return fields, body.encode("utf-8")


def cmd_relabel(args) -> None:
    """Upgrade a stub-labeled vault file to AI-quality labels (HOOK-04 / D-04).

    D-05 guard: only files whose `auto_label_hash` is the literal sentinel
    "stub" may be rewritten. A real SHA-256 (previously AI-labeled) or any
    hand-edited value is REFUSED with exit 1 — never re-label a non-stub file.

    stdin contract matches `write` (D-01/D-02): label JSON with a `title` key.
    Body bytes are preserved verbatim; `auto_label_hash` is recomputed as the
    real SHA-256 of the body (upgrade stub → real hash); `needs_review` → false.
    """
    config = _require_config()

    # D-01/D-02: label JSON on stdin. Mirror cmd_write's validation.
    label_input = sys.stdin.read()
    try:
        label = json.loads(label_input)
    except json.JSONDecodeError as e:
        print(f"relabel: invalid label JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)
    if "title" not in label:
        print("relabel: label JSON must contain a 'title' field.", file=sys.stderr)
        sys.exit(1)

    # Locate the vault file for this session_id by scanning Chats/ frontmatter.
    chats_dir = Path(config["vault_path"]) / "Chats"
    if not chats_dir.exists():
        print(f"relabel: vault Chats/ not found at {chats_dir}", file=sys.stderr)
        sys.exit(1)

    candidates = [p for p in chats_dir.glob("*.md") if _read_frontmatter_field(p, "session_id") == args.session_id]
    if not candidates:
        print(f"relabel: no vault file for session {args.session_id}", file=sys.stderr)
        sys.exit(1)
    if len(candidates) > 1:
        # Collision edge case (T-05-04-03): warn and pick the first.
        print(
            f"relabel: warning — {len(candidates)} files match session {args.session_id}; using {candidates[0].name}",
            file=sys.stderr,
        )
    vault_file = candidates[0]

    # D-05 sentinel guard.
    existing_hash = _read_auto_label_hash(vault_file)
    if existing_hash != "stub":
        print(
            f"relabel: refusing to rewrite {vault_file.name} "
            f"(auto_label_hash is not 'stub' — D-05 sentinel-only trigger)",
            file=sys.stderr,
        )
        sys.exit(1)

    fields, body_bytes = _split_frontmatter_and_body(vault_file)
    if not fields:
        print(f"relabel: {vault_file.name} has no frontmatter to rewrite", file=sys.stderr)
        sys.exit(1)

    # Upgrade: stub → real SHA-256 of the (unchanged) body bytes.
    new_hash = hashlib.sha256(body_bytes).hexdigest()

    # Overwrite label-owned fields; preserve everything else (project, session_id,
    # model, token_count, msg_count, machine, hostname, synced_at, privacy_review).
    fields["title"] = label["title"]
    fields["gist"] = label.get("gist")
    fields["tags"] = label.get("tags", [])
    fields["coherence_score"] = label.get("coherence_score")
    fields["needs_review"] = False  # D-05: stub → real means review is done
    fields["auto_label_hash"] = new_hash

    new_fm = emit_frontmatter(fields)
    # Atomic write with .bak preservation (same discipline as _write_atomic).
    tmp_path = vault_file.with_suffix(".tmp")
    bak_path = vault_file.with_suffix(vault_file.suffix + ".bak")
    with open(tmp_path, "wb") as f:
        f.write(new_fm.encode("utf-8"))
        f.write(body_bytes)
        f.flush()
        os.fsync(f.fileno())
    shutil.copy2(vault_file, bak_path)
    os.replace(tmp_path, vault_file)

    print(f"relabeled: {vault_file.name}")


# ─── Entry Point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    # argparse: stdlib module for building CLI interfaces
    # RawDescriptionHelpFormatter preserves newlines in the description string
    parser = argparse.ArgumentParser(
        description="Sync Claude Code sessions to Obsidian vault.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    # --once (Phase 5 D-07/D-19): SessionEnd hook entry point.
    # action="store_true" is argparse's boolean-flag idiom — args.once is True
    # if --once appeared, False otherwise. Pre-dispatched BEFORE subparsers
    # because --once has no subcommand (RESEARCH Pitfall 1: without this
    # pre-dispatch, `sync_chats.py --once` would fall into the subcommand-None
    # branch and print help instead of running the hook).
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one sync pass using stub labels — SessionEnd hook entry point",
    )

    # subparsers: lets us have "sync_chats.py init", "sync_chats.py scan", etc.
    subparsers = parser.add_subparsers(dest="subcommand", metavar="COMMAND")

    # init subcommand
    p_init = subparsers.add_parser("init", help="Initialize config (--label, --vault)")
    p_init.add_argument("--label", type=str, help="Short machine label (e.g. mbp, studio)")
    p_init.add_argument("--vault", type=str, help="Absolute path to Obsidian vault root")
    p_init.set_defaults(func=cmd_init)

    # scan subcommand
    p_scan = subparsers.add_parser("scan", help="List unsynced sessions as JSON array")
    p_scan.set_defaults(func=cmd_scan)

    # write subcommand
    p_write = subparsers.add_parser("write", help="Write a session to the vault (reads label JSON from stdin)")
    p_write.add_argument("session_id", help="UUID of the session to write")
    p_write.set_defaults(func=cmd_write)

    # status subcommand
    p_status = subparsers.add_parser("status", help="Show sync status summary")
    p_status.set_defaults(func=cmd_status)

    # MEM-01: mine subcommand (D-01) — shell out to mempalace after writes
    p_mine = subparsers.add_parser(
        "mine",
        help="Mine vault Chats/ into MemPalace (post-run step)",
    )
    p_mine.set_defaults(func=cmd_mine)

    # HOOK-04: relabel subcommand (Phase 5 D-04/D-05) — upgrade stub-labeled
    # vault files to AI-quality labels. Sentinel-only trigger (auto_label_hash == "stub").
    p_relabel = subparsers.add_parser(
        "relabel",
        help="Upgrade a stub-labeled vault file with fresh label JSON from stdin",
    )
    p_relabel.add_argument("session_id", help="UUID of the session whose vault file to relabel")
    p_relabel.set_defaults(func=cmd_relabel)

    args = parser.parse_args()

    # Pre-dispatch branch: --once runs cmd_once directly, BEFORE the
    # subcommand-None guard below (RESEARCH Pitfall 1). Also honors the
    # iCloud assertion (D-14) which all writer paths must satisfy.
    if args.once:
        _assert_not_icloud(CLAUDE_CHAT_HOME)
        cmd_once(args)
        return

    # No subcommand given: print help and exit
    if args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    # iCloud assertion runs on every subcommand invocation (not just init)
    _assert_not_icloud(CLAUDE_CHAT_HOME)

    # Dispatch to the subcommand function set via set_defaults(func=...)
    args.func(args)


if __name__ == "__main__":
    main()
