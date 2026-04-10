# External Integrations

**Analysis Date:** 2026-04-09

## Overview

This tool has **zero external service integrations**. It reads Claude Code session data from local JSONL files created by Anthropic's Claude Code IDE and provides browsing/exporting/backup functionality entirely on the user's machine.

## Data Sources

**Local File System Only:**

- `~/.claude/projects/{project_name}/*.jsonl` - Claude Code session files
  - Source: Created by Claude Code IDE when saving conversations
  - Format: JSON Lines (one JSON object per line per message)
  - Access: Read-only (plus optional atomic write for settings)
  - No authentication required

**Settings File:**

- `~/.claude/settings.json` - Claude Code application settings
  - Modified only by `protect` command to set `cleanupPeriodDays`
  - Atomic write pattern: write to `.tmp` then rename to prevent corruption
  - Location: `SETTINGS_FILE` in code (`~/.claude/settings.json`)

## No External APIs

**Databases:** None - data is local JSONL files
**Cloud Services:** None - purely local tool
**APIs:** None - no HTTP calls to external services
**Authentication:** None required - reads user's own local files
**Webhooks:** None incoming or outgoing

## Local Storage

**Session Data:**

- Reads from: `~/.claude/projects/` directory
- Structure: Organized by project subdirectory
- Format: JSONL files (one per session)
- Parsing: Line-by-line with error tolerance (line parse failures don't stop whole file)

**Backup Storage:**

- Location: `~/claude-chat-backups/` (or user-specified `--output` directory)
- Behavior: Creates subdirectories per project
- Naming: `{session_short_id}_{YYYYMMDD_HHMMSS}.jsonl`
- Retention: Keeps last 5 backups per session, prunes older ones automatically (in `cmd_backup()`)

**Export Output:**

- User-specified location (default: current working directory)
- Formats: `.md`, `.html`, `.txt`, `.tex`
- No uploads or external storage

## Web Server (Local Only)

**Serve Command:**

- Localhost HTTP server (127.0.0.1 only)
- Default port: 3456 (configurable with `--port`)
- Endpoints:
  - `GET /` - Index page with session list
  - `GET /session/{session_id}` - Individual session view
  - `GET /search?q={query}` - Full-text search across sessions
- No authentication
- No network exposure (explicitly binds to 127.0.0.1)
- Optional: Opens in browser using `webbrowser.open()`

## File Format Integrations

**Input: JSONL Session Files**

- Source: Claude Code IDE creates these
- Structure per line:
  ```json
  {
    "message": {
      "role": "user|assistant",
      "content": "text|[{type, text|name, input}]",
      "model": "claude-...",
      "...": "..."
    }
  }
  ```
- Parsing: Custom `Session` class in `claude-chat.py` (lines 143-307)

**Output Formats:**

- Markdown - Rendered with code blocks, sections
- HTML - Styled dark theme, responsive, supports rich mode (KaTeX math, tables)
- Plain text - Simple text extraction
- LaTeX - Document ready for compilation

## Data Processing Pipeline

**Discover:** `find_all_sessions()` (line 309)

- Scans `~/.claude/projects/` for `.jsonl` files
- Filters by project name if specified
- Skips files < 100 bytes
- Sorts by modification time (newest first)

**Parse:** `Session.parse()` (line 158)

- Line-by-line JSON parsing
- Robust: continues on malformed lines
- Extracts messages, tool calls, thinking blocks
- Filters system reminders from user messages
- Caches parsed state to avoid re-parsing

**Extract:**

- Code blocks: `code_blocks()` method
- Ideas: User messages (first message skipped as summary)
- Decisions: Assistant messages with deliberation/thinking content

**Export:** Format-specific exporters

- `export_markdown()` (line 854)
- `export_html()` (line 1048)
- `export_txt()` (line 891)
- `export_tex()` (line 915)

## Environment Considerations

**No Environment Variables Required**

Tool uses hardcoded paths relative to user home directory:

- `CLAUDE_DIR = Path.home() / ".claude"`
- `PROJECTS_DIR = CLAUDE_DIR / "projects"`
- `BACKUP_DIR = Path.home() / "claude-chat-backups"`
- `SETTINGS_FILE = CLAUDE_DIR / "settings.json"`

**Optional Runtime Control:**

- `--output` flag for custom backup/export directory
- `--port` flag for custom web server port
- `--project` filter for scoping operations
- `--limit` for pagination

## Cross-Platform Considerations

**Windows:**

- Special encoding fix in `_fix_windows_encoding()` (line 49)
- Reconfigures stdout/stderr to UTF-8 (handles cp1252 console)
- `readline` import is optional (graceful fail)

**macOS/Linux:**

- Full readline support for enhanced terminal input
- ANSI escape sequences for colored output (if terminal supports)

## Security Notes

**Read-Only Operations:**

- All commands except `protect` are read-only
- Local file system only - no network exposure

**Protect Command:**

- Modifies `~/.claude/settings.json` atomically
- Sets `cleanupPeriodDays` to 99999 to prevent Claude Code from auto-deleting sessions
- Uses atomic rename pattern (write `.tmp`, then rename) to prevent corruption

**Web Server (`serve`):**

- Only binds to 127.0.0.1 (localhost)
- Warning printed: "Note: No authentication. Do not expose this port on a network."
- No credentials or secrets involved
- Optional `--no-open` flag to prevent browser launch

## Data Retention

**Session Files:**

- Controlled by Claude Code IDE cleanup settings
- `protect` command can disable auto-deletion by setting cleanup period to 99999 days

**Backups:**

- Explicit `backup` command with optional watch mode
- Configurable output directory
- Automatic pruning: keeps last 5 backups per session per project

---

_Integration audit: 2026-04-09_
