# Testing Patterns

**Analysis Date:** 2026-04-09

## Current State

**No test framework or test files exist.** The codebase is a single-file CLI tool (`claude-chat.py`) with zero automated tests.

This document describes how testing SHOULD be structured if added (recommendations based on code analysis).

## Test Framework

**Recommended Runner:**

- pytest (standard Python testing, works well with CLI tools)
- Config file: `pytest.ini` or `pyproject.toml` with `[tool.pytest.ini_options]`

**Recommended Assertion Library:**

- pytest's built-in assert statements (pytest rewrites them for rich output)
- Optional: `pytest-mock` for mocking file I/O and external calls

**Run Commands (once tests added):**

```bash
pytest                              # Run all tests
pytest -v                           # Verbose output
pytest --tb=short tests/            # Run tests/ directory with short tracebacks
pytest -k "test_cmd_list"           # Run specific test
pytest --cov=claude_chat            # Coverage report
pytest -x                           # Stop on first failure
pytest --pdb                        # Drop into debugger on failure
```

## Recommended Test File Organization

**Location & Naming:**

- Separate `tests/` directory (not co-located)
- Test file naming: `tests/test_*.py` (pytest convention)
- Or module-specific: `tests/test_commands.py`, `tests/test_session_parsing.py`, `tests/test_export.py`

**Structure:**

```
tests/
├── __init__.py                    # Package marker
├── conftest.py                    # Shared fixtures (temp dirs, mock sessions)
├── test_commands.py               # Tests for cmd_list, cmd_search, cmd_export, etc.
├── test_session.py                # Tests for Session class, parsing, message extraction
├── test_export_formats.py         # Tests for export_markdown, export_html, export_txt, export_tex
├── test_html_helpers.py           # Tests for _md_table_to_html, _render_table, _auto_link_urls
└── fixtures/                      # Test data (sample JSONL files, expected outputs)
    ├── sample_session.jsonl       # A minimal valid session file
    └── complex_session.jsonl      # Session with code blocks, tool calls, thinking
```

## Recommended Test Structure

**Test Suite Pattern:**

```python
import pytest
from pathlib import Path
from claude_chat import Session, Message, ToolCall, cmd_list, find_all_sessions

class TestSessionParsing:
    """Tests for Session class and JSONL parsing."""

    def test_session_basic_parse(self, tmp_path):
        """Session.parse() correctly reads valid JSONL."""
        session_file = tmp_path / "test_session.jsonl"
        session_file.write_text(
            '{"message": {"role": "user", "content": "hello"}}\n'
            '{"message": {"role": "assistant", "content": "hi there"}}\n'
        )
        session = Session(session_file)
        session.parse()
        assert len(session.messages) == 2
        assert session.messages[0].role == "user"
        assert session.messages[1].role == "assistant"

    def test_session_handles_malformed_json(self, tmp_path):
        """Session.parse() gracefully skips invalid JSON lines."""
        session_file = tmp_path / "bad_session.jsonl"
        session_file.write_text(
            '{"message": {"role": "user", "content": "hello"}}\n'
            'NOT VALID JSON\n'
            '{"message": {"role": "assistant", "content": "hi"}}\n'
        )
        session = Session(session_file)
        session.parse()
        assert len(session.messages) == 2  # Malformed line skipped

    def test_session_summary_fast_path(self, tmp_path):
        """Session.summary() returns first user message without full parse."""
        session_file = tmp_path / "summary_test.jsonl"
        session_file.write_text(
            '{"message": {"role": "user", "content": "first question"}}\n'
            '{"message": {"role": "assistant", "content": "long response..."}}\n'
        )
        session = Session(session_file)
        summary = session.summary()
        assert "first question" in summary
        assert session._parsed is False  # Fast path did not trigger full parse

class TestExportFormats:
    """Tests for export functions."""

    def test_export_markdown_basic(self, mock_session):
        """export_markdown produces valid Markdown."""
        output = export_markdown(mock_session)
        assert "# Claude Code Session" in output
        assert "## You" in output
        assert "## Claude" in output

    def test_export_html_escapes_content(self, mock_session_with_code):
        """export_html properly escapes HTML entities."""
        output = export_html(mock_session_with_code)
        # Code blocks should be preserved, HTML should be escaped
        assert "&lt;" in output or "<pre>" in output
        assert "javascript:alert" not in output  # XSS protection

    def test_export_tex_escapes_special_chars(self, mock_session):
        """export_tex escapes LaTeX special characters."""
        output = export_tex(mock_session)
        assert r"\textdollar{}" in output or "$" not in output
        assert r"\{" in output or "{" not in output  # Braces escaped

    def test_md_table_to_html_converts_tables(self):
        """_md_table_to_html correctly converts markdown tables."""
        markdown = "| Header 1 | Header 2 |\n|----------|----------|\n| Cell 1 | Cell 2 |\n"
        html = _md_table_to_html(markdown)
        assert "<table" in html
        assert "<th>Header 1</th>" in html
        assert "<td>Cell 1</td>" in html

class TestCommands:
    """Tests for CLI command handlers."""

    def test_cmd_list_empty(self, capsys, tmp_path):
        """cmd_list handles no sessions gracefully."""
        # Mock PROJECTS_DIR to empty dir
        args = argparse.Namespace(project=None, limit=20, detail=False)
        cmd_list(args)
        captured = capsys.readouterr()
        assert "No sessions found" in captured.out

    def test_cmd_search_basic(self, capsys, mock_multiple_sessions):
        """cmd_search finds matching sessions."""
        args = argparse.Namespace(query="test", project=None, limit=20)
        cmd_search(args)
        captured = capsys.readouterr()
        assert "Found" in captured.out or "No results" in captured.out

    def test_cmd_export_session_not_found(self, capsys):
        """cmd_export handles missing session ID gracefully."""
        args = argparse.Namespace(
            session_id="nonexistent",
            all=False,
            format="md",
            output=None,
            open=False
        )
        cmd_export(args)
        captured = capsys.readouterr()
        assert "not found" in captured.out.lower()

class TestErrorHandling:
    """Tests for error handling and edge cases."""

    def test_session_parse_missing_file(self):
        """Session.parse() handles missing files without raising."""
        session = Session(Path("/nonexistent/session.jsonl"))
        session.parse()  # Should not raise
        assert session._parsed is True
        assert len(session.messages) == 0

    def test_file_io_interruption(self, tmp_path):
        """File reading gracefully handles I/O errors."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text('{"message": {"role": "user", "content": "test"}}\n')
        session = Session(session_file)

        # Simulate file deletion after creation but before parse
        session.parse()
        # Should handle gracefully even if file disappears
        assert isinstance(session.messages, list)
```

## Recommended Fixtures (conftest.py)

**Test Data Fixtures:**

````python
@pytest.fixture
def tmp_projects_dir(tmp_path, monkeypatch):
    """Create a temporary projects directory for testing."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr("claude_chat.PROJECTS_DIR", projects_dir)
    return projects_dir

@pytest.fixture
def mock_session(tmp_path):
    """Create a minimal valid test session."""
    session_file = tmp_path / "test_project" / "abc12345.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        '{"message": {"role": "user", "content": "What is a tree?"}}\n'
        '{"message": {"role": "assistant", "content": "A tree is a plant..."}}\n'
    )
    return Session(session_file)

@pytest.fixture
def mock_session_with_code(tmp_path):
    """Create a test session with code blocks."""
    session_file = tmp_path / "code_project" / "def67890.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        '{"message": {"role": "user", "content": "Write a function"}}\n'
        '{"message": {"role": "assistant", "content": '
        '"```python\\ndef hello():\\n    return \\"hi\\"\\n```"}}\n'
    )
    return Session(session_file)

@pytest.fixture
def mock_multiple_sessions(tmp_projects_dir):
    """Create multiple test sessions across projects."""
    for proj in ["project1", "project2"]:
        proj_dir = tmp_projects_dir / proj
        proj_dir.mkdir()
        for i in range(3):
            session_file = proj_dir / f"session{i}.jsonl"
            session_file.write_text(
                f'{{"message": {{"role": "user", "content": "query {i}"}}}}\n'
            )
    return tmp_projects_dir
````

## Test Types

**Unit Tests:**

- Scope: Individual functions and classes
- Approach: Test with mocked file system (tmp_path), no real ~/.claude directory
- Examples:
  - Session parsing with various JSON inputs
  - Export format functions with sample messages
  - Text extraction and regex patterns
  - Error handling for corrupted files

**Integration Tests:**

- Scope: Command handlers with realistic session data
- Approach: Use fixtures to create temporary session files, call cmd\_\* functions, verify output
- Examples:
  - cmd_list discovers sessions correctly
  - cmd_search finds matches across multiple sessions
  - cmd_export generates valid output files
  - cmd_backup copies files and maintains versions

**Manual/Smoke Tests (if automated testing not feasible):**

- Create a temporary project with sample JSONL files
- Run: `python claude-chat.py list` — verify output format
- Run: `python claude-chat.py search "pattern"` — verify search results
- Run: `python claude-chat.py export SESSION_ID --format html` — verify file created
- Run: `python claude-chat.py serve --no-open` — verify server starts
- Kill with Ctrl+C — verify graceful shutdown

## Mocking Strategy

**Framework:** pytest-mock (via `mocker` fixture)

**What to Mock:**

- File system I/O: Use `tmp_path` fixture instead (creates real temp files)
- Path operations: Mock `PROJECTS_DIR`, `BACKUP_DIR` using monkeypatch
- webbrowser.open: Mock to prevent opening actual browser
- datetime.now: Mock to test time-based formatting
- HTTPServer: Can test request handling with mock objects

**What NOT to Mock:**

- JSON parsing — test with real JSONL files (use tmp_path)
- Session.parse() — needs real file I/O to validate
- Regex patterns — test with actual strings to verify correctness

Example:

```python
def test_cmd_serve_port_in_use(mocker):
    """cmd_serve suggests alternative port if port taken."""
    mock_server = mocker.patch("claude_chat.HTTPServer")
    mock_server.side_effect = OSError("address already in use")

    args = argparse.Namespace(port=3456, no_open=False)
    cmd_serve(args)

    # Verify error message suggests next port
    # (need capsys to capture print output)
```

## Coverage Goals

**Current Coverage:** 0% (no tests exist)

**Priority Coverage Targets (if adding tests):**

1. **High Priority:** Session parsing and error handling — core functionality
   - JSONL parsing logic (test normal, malformed, empty files)
   - Message extraction (user, assistant, tool calls)
   - Summary generation (fast path and full parse paths)

2. **Medium Priority:** Export functions — visible user-facing functionality
   - Markdown, HTML, TXT, LaTeX export
   - HTML escaping and special character handling
   - Table and URL detection

3. **Medium Priority:** Command handlers — CLI interface
   - cmd_list, cmd_search, cmd_export, cmd_backup
   - Argument validation and error messages
   - Project filtering

4. **Lower Priority:** Helper functions
   - Text extraction and trimming
   - Regex patterns (unless complex logic)
   - HTML template rendering

**Coverage threshold (if enforced):** Consider 60-70% for a CLI tool with many integration points.

## Testing Python Version Compatibility

**Target:** Python 3.7+

**Considerations:**

- Test on Python 3.7 (oldest supported) and 3.11+ (current)
- Use pytest markers for version-specific tests if needed:
  ```python
  @pytest.mark.skipif(sys.version_info < (3, 8), reason="requires python 3.8+")
  ```
- Test Windows path handling (tmpdir creates correct separators on any platform)

## Common Test Patterns

**Testing async/file watch (cmd_backup --watch):**

```python
def test_cmd_backup_watch_mode(mocker, tmp_path):
    """Backup watch mode detects file changes."""
    # Mock time.sleep to avoid actual sleeping
    mocker.patch("time.sleep")

    # Mock webbrowser.open to avoid opening browser
    mock_open = mocker.patch("webbrowser.open")

    args = argparse.Namespace(
        watch=True,
        project=None,
        output=tmp_path,
        interval=1
    )
    # Call cmd_backup once and verify backup occurred
    # (full watch loop testing may not be practical)
```

**Testing interactive REPL (cmd_interactive):**

```python
def test_cmd_interactive_help(mocker, capsys):
    """Interactive mode shows help on startup."""
    mock_input = mocker.patch("builtins.input")
    mock_input.side_effect = ["help", "quit"]  # Simulate user input

    parser = argparse.ArgumentParser()
    # ... setup subparsers ...
    cmd_interactive(parser)

    captured = capsys.readouterr()
    assert "list" in captured.out  # Help should mention list command
```

## Suggested First Tests

If adding tests incrementally, start with:

1. **test_session_parsing.py** — Session class and JSONL parsing
   - Validates core data structure
   - Most critical functionality
   - Relatively easy to test in isolation

2. **test_export_markdown.py** — Markdown export formatter
   - Simple output format
   - Good model for testing other exporters
   - No file I/O complexity

3. **test_cmd_list.py** — List command with mock sessions
   - Tests command handler pattern
   - Demonstrates integration testing approach

---

_Testing analysis: 2026-04-09_

**Note:** No test framework currently configured. To add pytest:

1. Add `pytest` to development dependencies
2. Create `tests/` directory and `conftest.py`
3. Write tests following patterns above
4. Run: `pytest --cov=claude_chat` to check coverage
