"""Unit tests for Phase 5: _write_last_run atomic writer (OBSERV-03).

Tests for Task 1 of Plan 05-01 (TDD RED phase).

Run with: pipx run pytest tests/test_phase5_last_run.py -v

These tests verify the _write_last_run helper and LAST_RUN_PATH constant.
They are written BEFORE the implementation — all tests should fail with
AttributeError on _write_last_run / LAST_RUN_PATH until Task 2 is done.

Test class:
  TestWriteLastRun — OBSERV-03 atomic writer contract

Python beginner note: importlib.reload(sync_chats) re-executes the module's
top-level code (like LAST_RUN_PATH = CLAUDE_CHAT_HOME / "last_run.json") after
we've changed CLAUDE_CHAT_HOME in the environment. Without reload(), the module
keeps the old path that was computed when the module was first imported.
"""

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# ─── Bootstrap: add project root to sys.path so 'import sync_chats' works ─────
#
# sys.path is the list of directories Python searches when you do 'import X'.
# We insert the project root (one level above 'tests/') so that
# 'import sync_chats' finds sync_chats.py at the project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync_chats


# ─── D-11 schema: minimal valid last_run.json dict ────────────────────────────
#
# This is the schema that _write_last_run must be able to store and round-trip.
# Every field from D-11 (05-CONTEXT.md) is represented here.


def _make_last_run_dict() -> dict:
    """Return a minimal D-11-compliant last_run.json dict for test use."""
    return {
        "schema_version": 1,
        "run_started_at": "2026-04-15T19:00:00+00:00",
        "run_finished_at": "2026-04-15T19:00:01+00:00",
        "trigger": "once",
        "machine_label": "test-machine",
        "hostname": "test-host",
        "synced": 2,
        "skipped": 0,
        "failed": 0,
        "flagged_for_review": 2,
        "mempalace_mined": "skipped",
        "mempalace_reason": "not run by hook (--once skips mine)",
        "exit_code": 0,
        "errors": [],
    }


class TestWriteLastRun(unittest.TestCase):
    """OBSERV-03: _write_last_run atomic writer contract.

    Each test points CLAUDE_CHAT_HOME at a fresh temp directory via env var,
    then reloads sync_chats so the module-level LAST_RUN_PATH rebinds to that
    temp dir. This is the same pattern used in test_mine.py.
    """

    def setUp(self):
        """Create a temp directory, point CLAUDE_CHAT_HOME at it, reload module."""
        self.tmp = tempfile.mkdtemp()
        # Save the original env value so we can restore it in tearDown
        self._orig_home = os.environ.get("CLAUDE_CHAT_HOME")
        # Override BEFORE reload so module-level paths rebind correctly
        os.environ["CLAUDE_CHAT_HOME"] = self.tmp
        # importlib.reload() re-runs the top-level code of sync_chats, which
        # re-evaluates LAST_RUN_PATH = CLAUDE_CHAT_HOME / "last_run.json"
        importlib.reload(sync_chats)

    def tearDown(self):
        """Restore original CLAUDE_CHAT_HOME and clean up temp dir."""
        if self._orig_home is not None:
            os.environ["CLAUDE_CHAT_HOME"] = self._orig_home
        else:
            del os.environ["CLAUDE_CHAT_HOME"]
        # Reload again so subsequent tests start fresh
        importlib.reload(sync_chats)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_file_with_expected_schema(self):
        """Given D-11 schema dict, _write_last_run creates last_run.json with identical contents.

        Round-trip: write dict -> read file back -> parse JSON -> should equal input dict.
        """
        d = _make_last_run_dict()
        sync_chats._write_last_run(d)

        last_run_path = Path(self.tmp) / "last_run.json"
        self.assertTrue(last_run_path.exists(), "last_run.json should exist after write")

        # Round-trip: loaded JSON should equal the dict we passed in
        loaded = json.loads(last_run_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded, d)

    def test_preserves_previous_as_bak(self):
        """First call writes v1; second call with different dict writes v2 AND leaves v1 as .bak.

        The .bak file provides one-run undo visibility for post-mortem (D-14).
        """
        v1 = _make_last_run_dict()
        v1["synced"] = 1  # distinguish v1 from v2
        sync_chats._write_last_run(v1)

        v2 = _make_last_run_dict()
        v2["synced"] = 99  # distinguishable value
        sync_chats._write_last_run(v2)

        bak_path = Path(self.tmp) / "last_run.json.bak"
        last_run_path = Path(self.tmp) / "last_run.json"

        # The .bak should contain v1's data
        self.assertTrue(bak_path.exists(), "last_run.json.bak should exist after second write")
        bak_data = json.loads(bak_path.read_text(encoding="utf-8"))
        self.assertEqual(bak_data["synced"], 1, ".bak should hold the first (v1) dict")

        # The main file should contain v2's data
        current_data = json.loads(last_run_path.read_text(encoding="utf-8"))
        self.assertEqual(current_data["synced"], 99, "last_run.json should hold the second (v2) dict")

    def test_atomic_no_tmp_leftover(self):
        """After a successful write, last_run.json.tmp should NOT exist.

        The tmp file is an implementation detail of the atomic write sequence
        (write to .tmp, fsync, rename). After rename it must be gone.
        """
        sync_chats._write_last_run(_make_last_run_dict())

        tmp_path = Path(self.tmp) / "last_run.json.tmp"
        self.assertFalse(
            tmp_path.exists(),
            "last_run.json.tmp should be cleaned up after a successful write (rename removes it)",
        )

    def test_honors_claude_chat_home_env(self):
        """With CLAUDE_CHAT_HOME overridden to a temp dir, file lands in temp dir — never ~/.claude-chat/.

        This validates T-05-01-01: path derives from CLAUDE_CHAT_HOME, not hardcoded.
        """
        # The setUp already overrode CLAUDE_CHAT_HOME and reloaded the module.
        # We verify the file lands in self.tmp, not in the real ~/.claude-chat/.
        sync_chats._write_last_run(_make_last_run_dict())

        real_home = Path.home() / ".claude-chat" / "last_run.json"
        temp_home = Path(self.tmp) / "last_run.json"

        self.assertTrue(temp_home.exists(), "File should exist in the overridden CLAUDE_CHAT_HOME temp dir")
        self.assertFalse(
            real_home.exists() and real_home.stat().st_mtime > (Path(self.tmp) / "last_run.json").stat().st_mtime,
            "File must NOT have been written to real ~/.claude-chat/ — use temp dir only",
        )
        # Confirm LAST_RUN_PATH itself points at our temp dir
        self.assertEqual(
            str(sync_chats.LAST_RUN_PATH.parent),
            self.tmp,
            "LAST_RUN_PATH should be inside the CLAUDE_CHAT_HOME temp dir",
        )

    def test_schema_fields_present(self):
        """Round-tripped dict has all 14 required D-11 schema keys.

        Verifies that _write_last_run stores ALL fields, not a subset.
        """
        required_keys = {
            "schema_version",
            "run_started_at",
            "run_finished_at",
            "trigger",
            "machine_label",
            "hostname",
            "synced",
            "skipped",
            "failed",
            "flagged_for_review",
            "mempalace_mined",
            "mempalace_reason",
            "exit_code",
            "errors",
        }
        sync_chats._write_last_run(_make_last_run_dict())
        loaded = json.loads((Path(self.tmp) / "last_run.json").read_text(encoding="utf-8"))
        missing = required_keys - set(loaded.keys())
        self.assertEqual(
            missing,
            set(),
            f"last_run.json is missing required D-11 fields: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
