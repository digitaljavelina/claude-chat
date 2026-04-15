"""Unit tests for Phase 5: _write_session helper contract (Plan 05-01 Task 3/4).

Tests for Task 3 of Plan 05-01 (TDD RED phase).

Run with: pipx run pytest tests/test_phase5_write_session.py -v

These tests verify the _write_session(session_id, label, config, state) -> str
helper contract. Tests are written BEFORE the implementation — they should all
fail with AttributeError on sync_chats._write_session until Task 4 is done.

Test class:
  TestWriteSession — _write_session contract (return values + side effects)

Design notes for Python beginners:
  - unittest.mock.patch() temporarily replaces a function with a fake during the test.
    This lets us test _write_session without actually calling claude-chat.py (which
    requires the full installed tool + real sessions).
  - The harness uses CLAUDE_CHAT_HOME + CLAUDE_PROJECTS_DIR env overrides (same pattern
    as test_mine.py) to keep all file I/O inside a temp directory.
  - We DON'T use importlib.reload() here because we set env vars BEFORE the first import
    at module top-level (see the _GLOBAL_TEMP block below), matching test_sync_chats.py.
"""

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# ─── Bootstrap: set CLAUDE_CHAT_HOME + CLAUDE_PROJECTS_DIR before import ──────
#
# These must be set BEFORE 'import sync_chats' so the module-level constants
# (CLAUDE_CHAT_HOME, PROJECTS_DIR, STATE_PATH, etc.) resolve to our temp dirs.
# This is the same pattern used in test_sync_chats.py and test_reconcile_edited.py.

_GLOBAL_TEMP = tempfile.mkdtemp()
_GLOBAL_PROJECTS = os.path.join(_GLOBAL_TEMP, "projects")
os.makedirs(_GLOBAL_PROJECTS, exist_ok=True)

os.environ["CLAUDE_CHAT_HOME"] = _GLOBAL_TEMP
os.environ["CLAUDE_PROJECTS_DIR"] = _GLOBAL_PROJECTS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync_chats  # noqa: E402

# ─── Test session constants ───────────────────────────────────────────────────

_TEST_SESSION_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
_TEST_SESSION_ID2 = "11112222-3333-4444-5555-666677778888"

# Minimal JSONL content for a session: one human message + one assistant response.
# The timestamp must be a valid ISO string for _get_session_date() to parse.
_JSONL_CONTENT = (
    json.dumps(
        {
            "parentUuid": None,
            "type": "human",
            "message": {"role": "user", "content": "Hello world test message for write session"},
            "uuid": "msg-001",
            "timestamp": "2026-04-15T10:00:00.000Z",
            "sessionId": _TEST_SESSION_ID,
            "cwd": "/tmp/testproject",
        }
    )
    + "\n"
    + json.dumps(
        {
            "parentUuid": "msg-001",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-20250514",
                "content": [{"type": "text", "text": "Hello back from assistant."}],
                "usage": {"input_tokens": 50, "output_tokens": 20},
            },
            "uuid": "msg-002",
            "timestamp": "2026-04-15T10:00:05.000Z",
            "sessionId": _TEST_SESSION_ID,
        }
    )
    + "\n"
)

# Stub return value for _get_markdown_body — avoids subprocess call to claude-chat.py.
# The tuple is (body_str, scrub_stats_dict) per Phase 3 return signature.
_FAKE_BODY = "## Hello world test message for write session\n\nHello back from assistant."
_FAKE_SCRUB_STATS = {"redacted_count": 0, "patterns": []}


def _make_config(vault_path: str) -> dict:
    """Minimal config dict — same shape as _require_config() returns."""
    return {
        "schema_version": 1,
        "machine_label": "testmachine",
        "vault_path": vault_path,
    }


def _make_state() -> dict:
    """Minimal state dict — same shape as load_state() returns."""
    return {
        "schema_version": 1,
        "synced_session_ids": [],
        "fingerprints": {},
        "last_run_at": None,
    }


class TestWriteSession(unittest.TestCase):
    """_write_session contract: return values + side effects.

    Each test uses a fresh temp directory tree:
      tmp/
        projects/<project_dir>/<session_id>.jsonl   <- fake JSONL session
        vault/Chats/                                 <- fake Obsidian vault
    """

    def setUp(self):
        """Create isolated temp dirs and JSONL fixture for each test."""
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

        # Project dir: must be exactly 2 levels deep under PROJECTS_DIR
        # (matches the depth=2 check in the JSONL locator)
        self.project_dir = self.tmp / "projects" / "testproject"
        self.project_dir.mkdir(parents=True)
        self.jsonl_path = self.project_dir / f"{_TEST_SESSION_ID}.jsonl"
        self.jsonl_path.write_text(_JSONL_CONTENT, encoding="utf-8")

        # Vault dir
        self.vault_dir = self.tmp / "vault" / "Chats"
        self.vault_dir.mkdir(parents=True)

        # Config + state
        self.config = _make_config(str(self.tmp / "vault"))
        self.state = _make_state()

        # Point module-level paths at our temp dirs so file writes land here
        sync_chats.CLAUDE_CHAT_HOME = self.tmp
        sync_chats.CONFIG_PATH = self.tmp / "config.json"
        sync_chats.STATE_PATH = self.tmp / "state.json"
        sync_chats.LOG_PATH = self.tmp / "sync.log"
        sync_chats.LAST_RUN_PATH = self.tmp / "last_run.json"
        sync_chats.PROJECTS_DIR = self.tmp / "projects"

    def _patch_markdown_body(self):
        """Context manager that stubs out _get_markdown_body (avoids subprocess call)."""
        return mock.patch(
            "sync_chats._get_markdown_body",
            return_value=(_FAKE_BODY, _FAKE_SCRUB_STATS),
        )

    def test_returns_synced_on_fresh_write(self):
        """Given a valid stub label + session not in state, returns 'synced' and creates vault file.

        This is the happy path: new session, not yet in synced_session_ids.
        """
        label = {
            "title": "Hello world test message for write session",
            "gist": None,
            "tags": ["stub"],
            "coherence_score": None,
            "needs_review": True,
        }

        with self._patch_markdown_body():
            result = sync_chats._write_session(_TEST_SESSION_ID, label, self.config, self.state)

        self.assertEqual(result, "synced", "_write_session should return 'synced' on first write")
        # A file should have been created in the vault's Chats/ dir
        chats_files = list(self.vault_dir.glob("*.md"))
        self.assertEqual(len(chats_files), 1, "Exactly one .md file should appear in vault/Chats/")

    def test_returns_skipped_on_already_synced(self):
        """When session_id is already in state['synced_session_ids'], returns 'skipped'.

        This is clobber defense layer 1 (CORE-08): state set is authoritative.
        No new file should be written.
        """
        # Pre-populate state as if session was already written
        self.state["synced_session_ids"].append(_TEST_SESSION_ID)

        label = {
            "title": "Already synced session",
            "gist": None,
            "tags": ["stub"],
            "coherence_score": None,
            "needs_review": True,
        }

        with self._patch_markdown_body():
            result = sync_chats._write_session(_TEST_SESSION_ID, label, self.config, self.state)

        self.assertIn(
            result,
            ("skipped",),
            "_write_session should return 'skipped' when session_id is already in state",
        )
        # No file should be created (session was already written, no new write)
        chats_files = list(self.vault_dir.glob("*.md"))
        self.assertEqual(len(chats_files), 0, "No new file should appear for already-synced session")

    def test_stub_sentinel_hash_supported(self):
        """When label has auto_label_hash_override='stub', frontmatter contains auto_label_hash: stub.

        This is D-03: cmd_once passes the sentinel so the re-label SKILL can find stub files.
        The sentinel distinguishes stub-titled files (awaiting AI re-label) from real-labeled ones
        (which have a SHA-256 hash). Note: test key name may adjust in Task 4.
        """
        label = {
            "title": "Hello world test message for write session",
            "gist": None,
            "tags": ["stub"],
            "coherence_score": None,
            "needs_review": True,
            "auto_label_hash_override": "stub",  # D-03 sentinel
        }

        with self._patch_markdown_body():
            result = sync_chats._write_session(_TEST_SESSION_ID, label, self.config, self.state)

        self.assertEqual(result, "synced", "Stub-sentinel write should still return 'synced'")
        chats_files = list(self.vault_dir.glob("*.md"))
        self.assertEqual(len(chats_files), 1, "A vault file should be created for stub-sentinel write")

        content = chats_files[0].read_text(encoding="utf-8")
        self.assertIn(
            "auto_label_hash: stub",
            content,
            "Frontmatter should contain 'auto_label_hash: stub' when override='stub'",
        )

    def test_raises_on_missing_title(self):
        """A label dict without 'title' raises ValueError (or similar fatal error).

        Matches the existing cmd_write fatal-error behavior per D-02.
        'title' is the only required field in the label schema.
        """
        label = {
            # 'title' deliberately absent
            "gist": None,
            "tags": ["stub"],
        }

        with self._patch_markdown_body():
            # _write_session should raise (ValueError, KeyError, or SystemExit) on missing title
            with self.assertRaises((ValueError, KeyError, SystemExit)):
                sync_chats._write_session(_TEST_SESSION_ID, label, self.config, self.state)

    def test_updates_state_on_success(self):
        """After a 'synced' return, state['synced_session_ids'] contains the session_id.

        State update is step 9 of the write pipeline (D-26) — must happen inside
        _write_session so cmd_once can also rely on per-session state persistence.
        """
        label = {
            "title": "Hello world test message for write session",
            "gist": None,
            "tags": ["stub"],
            "coherence_score": None,
            "needs_review": True,
        }

        with self._patch_markdown_body():
            result = sync_chats._write_session(_TEST_SESSION_ID, label, self.config, self.state)

        self.assertEqual(result, "synced")
        self.assertIn(
            _TEST_SESSION_ID,
            self.state.get("synced_session_ids", []),
            "session_id should be added to state['synced_session_ids'] after successful write",
        )
        # Verify state was also persisted to disk (save_state was called)
        state_on_disk = (
            json.loads((self.tmp / "state.json").read_text(encoding="utf-8"))
            if (self.tmp / "state.json").exists()
            else {}
        )
        self.assertIn(
            _TEST_SESSION_ID,
            state_on_disk.get("synced_session_ids", []),
            "state.json on disk should contain the session_id after a successful write",
        )


if __name__ == "__main__":
    unittest.main()
