# Coding Conventions

**Analysis Date:** 2026-04-09

## Naming Patterns

**Files:**

- Single-file CLI tool: `claude-chat.py` — lowercase with hyphens

**Functions:**

- Public/command handlers: `cmd_*` prefix (e.g., `cmd_list`, `cmd_search`, `cmd_export`)
- Helper functions: `_` prefix for internal use (e.g., `_session_preview`, `_export_session`, `_fix_windows_encoding`)
- Export formatters: `export_*` prefix (e.g., `export_markdown`, `export_html`, `export_txt`, `export_tex`)
- HTML-specific helpers: `_md_table_to_html`, `_render_table`, `_auto_link_urls`

**Variables:**

- Constants: UPPERCASE (e.g., `CLAUDE_DIR`, `PROJECTS_DIR`, `BACKUP_DIR`, `SETTINGS_FILE`)
- Local variables: snake_case (e.g., `session_id`, `total_size`, `file_states`)
- Private module-level constants: \_UPPERCASE (e.g., `_INTERACTIVE_HELP`, `_VALID_COMMANDS`)

**Types:**

- Classes: PascalCase (e.g., `Message`, `ToolCall`, `Session`, `ChatHandler`)
- Slots defined in `__slots__` for memory efficiency

## Code Style

**Formatting:**

- Line length: 120 characters (configured in `ruff.toml`)
- Double quotes for strings (configured `quote-style = "double"`)
- Indentation: 4 spaces (Python default)

**Linting:**

- Tool: ruff (configured in `ruff.toml`)
- Selected rules: `["E", "F", "W", "I"]` (errors, style, warnings, import sorting)
- Target version: Python 3.7+

Configuration file: `ruff.toml`

## Import Organization

**Order:**

1. Standard library imports (e.g., `sys`, `json`, `re`, `time`, `pathlib`, `datetime`, `http.server`, `urllib.parse`)
2. Standard library with `as` aliases (e.g., `import html as html_mod`)
3. Conditional imports (e.g., `import readline` inside try/except for platform compatibility)
4. Deferred imports (e.g., `import subprocess` used only in interactive mode)

**Path Aliases:**

- None currently used. Imports use full module paths.

Imports are organized at top of file after module docstring and `__version__` definition.

## Error Handling

**Patterns:**

- Broad exception catching for file I/O: `except (IOError, OSError)` — used throughout file parsing (`parse()`, `summary()`, `message_count()`)
- JSON decode errors: `except json.JSONDecodeError` — gracefully skip malformed lines
- Keyboard interrupts: `except KeyboardInterrupt` — catch in watch loops (`cmd_backup`) and interactive REPL to print exit message
- Argparse system exit: `except SystemExit` — catch in interactive REPL to prevent exit on `--help`
- General exception catch in interactive mode: `except Exception as e` — print error message and continue REPL
- Port in-use errors: Named exception handling in `cmd_serve` with special case for errno 10048 (Windows)
- Windows encoding errors: `except Exception: pass` — silently fail if encoding reconfiguration not supported

Example from `cmd_backup`:

```python
try:
    while True:
        time.sleep(args.interval)
        n = do_backup()
except KeyboardInterrupt:
    print(f"\nStopped. Total backed up: {backed_up}")
```

Example from `cmd_serve`:

```python
try:
    server = HTTPServer(("127.0.0.1", port), ChatHandler)
except OSError as e:
    if "address already in use" in str(e).lower() or getattr(e, "errno", 0) == 10048:
        print(f"Port {port} is already in use. Try: claude-chat serve --port {port + 1}")
        return
    raise
```

## Logging

**Framework:** Console output only (no logging module)

**Patterns:**

- Use `print()` for all user-facing output
- Errors use standard print: `print(f"Error: {e}")`
- Status messages: `print(f"Exporting {len(sessions)} session(s) to {fmt}...")`
- Suppressed request logs in web handler: `def log_message(self, format, *a): pass`
- Progress indication: `print(f"  [{BACKUP] {s.short_id} -> ...")`
- Timestamps in watch mode: `print(f"  [{datetime.now().strftime('%H:%M:%S')}] {n} file(s) updated")`

## Comments

**When to Comment:**

- Complex parsing logic (e.g., JSONL message parsing with multiple content types)
- Regex patterns and special cases (e.g., `# Single-pass replacement to avoid double-escaping`)
- Platform-specific workarounds (e.g., Windows console encoding, readline on Unix)
- Non-obvious optimization (e.g., `# Fast path: scan first ~50 lines without full parse`)
- Skip patterns to explain why things are excluded (e.g., `# Skip the boot/first message`)

**Docstrings:**

- All classes and functions have single-line docstrings
- Format: Triple-quoted strings describing purpose
- Examples from codebase:
  - `"""A single message in a conversation."""`
  - `"""Parse the JSONL file into messages."""`
  - `"""Extract text from user message content (string or list)."""`
  - `"""Export session as Markdown."""`
- No parameter or return documentation (focus on purpose)

## Function Design

**Size:**

- Small helper functions: 3-15 lines (e.g., `_session_preview`, `_render_table`)
- Medium functions: 15-40 lines (e.g., `cmd_list`, `cmd_search`)
- Larger functions: up to 70 lines for complex operations (e.g., `export_html`, `cmd_backup`)
- Very large functions (150+ lines): formatters with template substitution and HTML generation

**Parameters:**

- Functions typically accept 1-3 parameters
- Optional parameters use default values (e.g., `max_len=100`, `embedded=False`, `rich=False`)
- Args objects passed from argparse used directly without parameter unpacking

**Return Values:**

- String returns for export functions
- None for command handlers (side effects via print)
- Tuples for composite returns (e.g., `(s, count, contexts)` in search)
- List returns for data collection (e.g., `code_blocks()`, `user_messages()`)

## Module Design

**Exports:**

- Public functions: `cmd_*` — command handlers callable from argparse
- Export functions: `export_*` — publicly called formatters
- Utility functions: named helpers without underscore prefix that may be used elsewhere
- Classes: `Message`, `ToolCall`, `Session` — data structures for parsing

**Barrel Files:**

- Not applicable — single file structure

**Section Dividers:**

- ASCII dividers used to organize code sections: `# ─── [Section Name] ───`
- Examples:
  - `# ─── Configuration ───────────────────────────────────────────────────────────`
  - `# ─── JSONL Parser ────────────────────────────────────────────────────────────`
  - `# ─── Session Discovery ───────────────────────────────────────────────────────`
  - `# ─── Commands ────────────────────────────────────────────────────────────────`
  - `# ─── Export Formatters ───────────────────────────────────────────────────────`
  - `# ─── HTML Templates ──────────────────────────────────────────────────────────`
- Dividers span to column 80 for visual balance
- Each major section is self-contained with related functionality grouped together

---

_Convention analysis: 2026-04-09_
