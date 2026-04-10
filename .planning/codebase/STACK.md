# Technology Stack

**Analysis Date:** 2026-04-09

## Languages

**Primary:**

- Python 3.7+ - Single-file CLI tool (`claude-chat.py`, ~1601 lines)

## Runtime

**Environment:**

- CPython 3.7+
- Platform-agnostic (Windows, macOS, Linux)

**Package Manager:**

- None (zero external dependencies)
- Standard library only
- Lockfile: Not applicable

## Frameworks

**None.** Tool uses only Python standard library modules.

## Key Standard Library Modules

**Core:**

- `argparse` - CLI argument parsing and command routing
- `json` - JSONL file parsing for session data
- `pathlib` - Cross-platform file path handling
- `http.server` (HTTPServer, BaseHTTPRequestHandler) - Local web browser server for `serve` command

**Utilities:**

- `datetime` - Session timestamp handling and formatting
- `re` - Text search and regex operations
- `shutil` - File backup operations (copy2)
- `time` - Watch mode polling interval for backup command
- `shlex` - Shell command argument parsing in interactive mode
- `webbrowser` - Open local web server in default browser
- `html` (as html_mod) - HTML escaping for safe output rendering
- `urllib.parse` - URL parsing for web server routing
- `sys` - Version check, encoding fix for Windows console
- `subprocess` - Optional shell command execution in interactive mode (imported on demand)
- `readline` - Optional enhanced terminal input on Unix (imported on demand, graceful fail on Windows)

## Configuration

**Environment:**

- No environment variables required
- Reads from user's home directory structure only

**Hardcoded Paths:**

- `.claude/` - Base directory in user home (`~/.claude`)
- `.claude/projects/` - JSONL session files by project (`PROJECTS_DIR`)
- `.claude/settings.json` - Claude Code settings file for cleanup period (`SETTINGS_FILE`)
- `claude-chat-backups/` - Backup directory in user home (`BACKUP_DIR`)

**Tool Configuration File:**

- `ruff.toml` - Code formatting/linting config (development only)
  - Line length: 120 characters
  - Target version: Python 3.7
  - Linting rules: E, F, W, I (errors, warnings, imports)
  - Quote style: double quotes

## Build/Dev Tools

**Code Quality:**

- Ruff (development-time only, not runtime)
  - Config: `ruff.toml`
  - Enforced: Line length 120, Python 3.7 compatibility
  - No build step required

## File Format

**Input:**

- JSONL (JSON Lines) format - Session files at `~/.claude/projects/{project}/{session_id}.jsonl`
- Each line is a JSON object representing a conversation message or metadata
- Robust error handling: individual line parse failures do not stop parsing

**Output:**

- Markdown (--format md)
- HTML (--format html, supports rich mode with KaTeX and tables)
- Plain text (--format txt)
- LaTeX (--format tex)
- JSONL (backup format preserves original)

## Platform Requirements

**Development:**

- Python 3.7+
- Ruff (optional, for code quality)
- No other dependencies

**Runtime:**

- Python 3.7+
- No external packages required
- Works on any platform Python supports (Windows, macOS, Linux)

**Distribution:**

- Single `.py` file - copy `claude-chat.py` anywhere in PATH to use as command
- Or use as `python claude-chat.py`

## Deployment/Usage

**Invocation:**

```bash
python claude-chat.py [command] [options]
python3 claude-chat.py list
./claude-chat.py export a7e44ed0 --format html
```

**Interactive Mode:**

- REPL for command entry
- Shell escape support: `!command` to execute shell commands
- Enhanced terminal on Unix (readline module) with history and arrow keys

## Version

- Current: 1.0.0 (defined in `__version__` constant)
- No dependencies to version-lock

---

_Stack analysis: 2026-04-09_
