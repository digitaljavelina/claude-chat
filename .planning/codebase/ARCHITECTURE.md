# Architecture

**Analysis Date:** 2026-04-09

## Pattern Overview

**Overall:** Layered CLI + Web UI pattern

**Key Characteristics:**

- Single-file monolithic design optimizing for zero dependencies
- Clear separation between data model (Message, ToolCall, Session), discovery/parsing, command handlers, and export formatters
- Dual interface: command-line REPL and embedded HTTP server for web browsing
- Lazy parsing optimization: Session metadata loaded eagerly, full message content parsed on demand

## Layers

**Data Model Layer:**

- Purpose: Represent Claude conversation entities with efficient memory footprint
- Location: `claude-chat.py` lines 73-304
- Contains: `Message` class, `ToolCall` class, `Session` class with JSONL parsing logic
- Depends on: Standard library (json, pathlib, datetime, re)
- Used by: All discovery, search, export, and command handlers

**Session Discovery Layer:**

- Purpose: Locate and index session files across project directories
- Location: `claude-chat.py` lines 309-335
- Contains: `find_all_sessions()`, `find_session()`, session filtering
- Depends on: Data model layer (Session)
- Used by: All commands (list, search, export, serve, stats, extract, backup)

**Command Handler Layer:**

- Purpose: Execute user requests from CLI or interactive mode
- Location: `claude-chat.py` lines 365-849 (cmd\_\* functions)
- Contains: `cmd_list()`, `cmd_search()`, `cmd_export()`, `cmd_backup()`, `cmd_stats()`, `cmd_extract()`, `cmd_serve()`, `cmd_protect()`, `cmd_interactive()`
- Depends on: Session discovery layer, export formatters, HTTP server
- Used by: Main entry point dispatcher

**Export Formatter Layer:**

- Purpose: Convert Session objects to different output formats
- Location: `claude-chat.py` lines 854-1165
- Contains: `export_markdown()`, `export_txt()`, `export_tex()`, `export_html()`, with supporting functions for LaTeX/HTML rendering
- Depends on: Data model layer (Message, ToolCall, Session)
- Used by: `cmd_export()`, `cmd_serve()` (HTML variant)

**Web UI Layer:**

- Purpose: Serve interactive HTML interface for browsing sessions
- Location: `claude-chat.py` lines 703-818 (within `cmd_serve()`)
- Contains: `ChatHandler` (embedded HTTPRequestHandler subclass), route handlers (\_serve_index, \_serve_session, \_serve_search), HTML templates
- Depends on: Session discovery, export formatters (HTML)
- Used by: Direct end-user interaction via browser

**Template & Configuration Layer:**

- Purpose: Store HTML templates and application constants
- Location: `claude-chat.py` lines 63-69 (config), 1170-1356 (templates)
- Contains: Path constants (CLAUDE_DIR, PROJECTS_DIR, BACKUP_DIR), HTML_TEMPLATE, WEB_TEMPLATE_INDEX, WEB_TEMPLATE_SEARCH
- Depends on: None
- Used by: Web UI layer, protect command

## Data Flow

**Session Listing Flow:**

1. User invokes `list` command
2. `cmd_list()` calls `find_all_sessions(project_filter)`
3. Session discovery scans `~/.claude/projects/*/` for JSONL files
4. Sessions sorted by modification time (eager: only metadata loaded, parsing deferred)
5. `_session_preview()` extracts first ~50 lines to get summary without full parse
6. Output formatted as table with short ID, date, size, project, summary

**Export Flow:**

1. User invokes `export SESSION_ID --format FORMAT`
2. `cmd_export()` locates session via `find_session(session_id)`
3. Session object calls `.parse()` to load full message content from JSONL
4. Appropriate formatter (`export_markdown()`, `export_html()`, etc.) transforms Session
5. File written to output directory
6. If `--open` flag: subprocess opens in browser/editor

**Search Flow:**

1. User invokes `search QUERY`
2. `cmd_search()` calls `find_all_sessions()`
3. For each session: reads full JSONL file, counts query matches (case-insensitive)
4. Results sorted by match count, truncated to limit
5. Formatted as table with hit count
6. In `serve` mode: identical search via ChatHandler.\_serve_search()

**Web UI Session Browsing Flow:**

1. User opens browser to `http://127.0.0.1:3456`
2. HTTPServer accepts connection, routes to `ChatHandler.do_GET()`
3. Route `/` → `_serve_index()` → lists all sessions in clickable table
4. Route `/session/{id}` → `_serve_session()` → loads and renders single session as HTML
5. Route `/search?q=...` → `_serve_search()` → search results table
6. All HTML responses use embedded templates with server-side variable substitution

**Backup Flow:**

1. User invokes `backup [--watch] [--interval 10]`
2. `cmd_backup()` traverses all sessions, copies JSONL files to BACKUP_DIR
3. If `--watch`: polls every N seconds for new/modified sessions, incremental backup
4. Uses `shutil.copy2()` to preserve modification times

**Protection Flow:**

1. User invokes `protect`
2. `cmd_protect()` reads/creates `~/.claude/settings.json`
3. Sets `cleanupPeriodDays` to 99999 (prevents Claude Code auto-deletion)
4. Atomic write via temp file + rename (crash-safe)

## Key Abstractions

**Message:**

- Purpose: Represent single conversation turn (user or assistant)
- Examples: `claude-chat.py` lines 73-88
- Pattern: Immutable data container with **slots** for memory efficiency
- Fields: role (str), text (str), tool_calls (List[ToolCall]), thinking (str), timestamp, model

**ToolCall:**

- Purpose: Represent invocation of Claude Code's tool (Read, Write, Bash, Glob, Grep, etc.)
- Examples: `claude-chat.py` lines 90-142
- Pattern: Data holder with summary() method for display
- Fields: name (str), input_data (dict), result (any)

**Session:**

- Purpose: Represent complete conversation file (JSONL) with lazy parsing
- Examples: `claude-chat.py` lines 143-304
- Pattern: Smart container with deferred parsing, optimization for metadata-only access
- Key methods: parse() (lazy), summary() (fast path), user_messages(), assistant_messages(), code_blocks(), all_text()
- Derived properties: session_id (stem), short_id (first 8 chars), project (parent dir name)

**Export Formatters:**

- Purpose: Polymorphic conversion of Session to output format
- Pattern: Pure functions taking Session, returning string
- Examples: export_markdown, export_html, export_tex, export_txt
- Reusable helpers: \_md_table_to_html(), \_render_table(), \_auto_link_urls()

**ChatHandler (Inner Class):**

- Purpose: HTTP request router for web UI
- Location: `claude-chat.py` lines 707-796 (within cmd_serve)
- Pattern: Standard library BaseHTTPRequestHandler subclass
- Routes: GET / → index, GET /session/{id} → detail, GET /search → results
- Template rendering: Simple string replacement with {{VARIABLE}} pattern

## Entry Points

**Command-Line Entry:**

- Location: `claude-chat.py` lines 1497-1601 (main function)
- Triggers: `python claude-chat.py [command] [args]`
- Responsibilities: Parse CLI arguments, dispatch to cmd\_\* handlers
- Pattern: Argument parser with subcommands, direct function dispatch
- Interactive fallback: If no command given, launches REPL mode (cmd_interactive)

**Interactive REPL Entry:**

- Location: `claude-chat.py` lines 1399-1495 (cmd_interactive)
- Triggers: Invoked when no CLI command provided
- Responsibilities: Read user input loop, parse pseudo-commands, dispatch to handlers
- Features: Command aliases (ls→list, grep→search, web→serve), shell command execution (! prefix)

**HTTP Server Entry:**

- Location: `claude-chat.py` lines 798-818 (within cmd_serve)
- Triggers: `python claude-chat.py serve [--port 3456]`
- Responsibilities: Create HTTPServer, spawn ChatHandler on each request
- Binding: Localhost-only (127.0.0.1:PORT) — no authentication

## Error Handling

**Strategy:** Defensive programming with fallback display

**Patterns:**

- JSONL parsing: Catches json.JSONDecodeError per-line, skips malformed entries (line 171-173)
- File I/O: Catches IOError/OSError in all file operations, continues (e.g., line 321-324)
- Session lookup: Returns None for missing sessions, handlers check and call send_error(404) (line 329-334)
- Port binding: Catches OSError for port-in-use, suggests alternative port (line 800-804)
- Windows encoding: Calls reconfigure() if available, silently fails otherwise (line 49-60)
- Export: Text extraction includes whitespace normalization and null checks (line 215-228)

## Cross-Cutting Concerns

**Logging:** None — designed for silent operation. HTTP handler suppresses logs (line 708-709). Errors printed to stdout/stderr.

**Validation:**

- Session ID: Accepts full or truncated (first 8 chars)
- Query string: URL-decoded by urllib.parse.parse_qs
- User input: Interactive mode strips/validates command via \_VALID_COMMANDS set
- File size: Skips tiny files (<100 bytes) to avoid empty sessions (line 321)

**Authentication:** Not applicable — localhost-only HTTP server with explicit warning (line 808)

**Character Encoding:**

- All file reads use UTF-8 with `errors="replace"` (line 165, 242, 773)
- HTML output encoded as UTF-8 (line 730)
- Windows console reconfigured to UTF-8 on startup (line 49-60)

---

_Architecture analysis: 2026-04-09_
