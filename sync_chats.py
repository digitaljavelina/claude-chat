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
PROJECTS_DIR = Path.home() / ".claude" / "projects"

# All sync_chats state lives under CLAUDE_CHAT_HOME — strictly local, never iCloud (D-23)
CONFIG_PATH = CLAUDE_CHAT_HOME / "config.json"
STATE_PATH = CLAUDE_CHAT_HOME / "state.json"
LOG_PATH = CLAUDE_CHAT_HOME / "sync.log"

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

        if len(rel_parts) != 2:
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


def cmd_write(args) -> None:
    """Write a session to the Obsidian vault. (Not yet implemented — Plan 03)"""
    print("Not yet implemented. Coming in Plan 03.", file=sys.stderr)
    sys.exit(1)


def cmd_status(args) -> None:
    """Show sync status summary. (Not yet implemented — Plan 03)"""
    print("Not yet implemented. Coming in Plan 03.", file=sys.stderr)
    sys.exit(1)


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

    args = parser.parse_args()

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
