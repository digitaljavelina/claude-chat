"""Integration tests for cmd_status reading last_run.json (Phase 5 Plan 03, OBSERV-04).

Run with: pipx run pytest tests/test_phase5_status.py -v

Tests for Tasks 3/4 of Plan 05-03. The status command now prefers
last_run.json (when present) over state.last_run_at so users see the D-23
canonical summary line — same format that cmd_once prints on hook runs.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_GLOBAL_TEMP = tempfile.mkdtemp()
_GLOBAL_PROJECTS = os.path.join(_GLOBAL_TEMP, "projects")
os.makedirs(_GLOBAL_PROJECTS, exist_ok=True)
os.environ["CLAUDE_CHAT_HOME"] = _GLOBAL_TEMP
os.environ["CLAUDE_PROJECTS_DIR"] = _GLOBAL_PROJECTS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync_chats  # noqa: E402


_CANONICAL_LAST_RUN = {
    "schema_version": 1,
    "run_started_at": "2026-04-15T10:00:00+00:00",
    "run_finished_at": "2026-04-15T10:00:01+00:00",
    "trigger": "once",
    "machine_label": "test-mbp",
    "hostname": "test-host",
    "synced": 2,
    "skipped": 1,
    "failed": 0,
    "flagged_for_review": 2,
    "mempalace_mined": "skipped",
    "mempalace_reason": "not run by hook (--once skips mine)",
    "exit_code": 0,
    "errors": [],
}


class _BaseStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.projects = self.tmp / "projects"
        self.projects.mkdir()

        sync_chats.CLAUDE_CHAT_HOME = self.tmp
        sync_chats.CONFIG_PATH = self.tmp / "config.json"
        sync_chats.STATE_PATH = self.tmp / "state.json"
        sync_chats.LOG_PATH = self.tmp / "sync.log"
        sync_chats.LAST_RUN_PATH = self.tmp / "last_run.json"
        sync_chats.PROJECTS_DIR = self.projects

        sync_chats.CONFIG_PATH.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "machine_label": "config-label",
                    "vault_path": str(self.tmp / "vault"),
                }
            )
        )
        sync_chats.STATE_PATH.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "last_run_at": "2026-04-14T09:00:00+00:00",
                    "synced_session_ids": ["existing-a", "existing-b"],
                    "fingerprints": {},
                }
            )
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_status(self) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sync_chats.cmd_status(mock.Mock())
        return buf.getvalue()


class TestCmdStatusWithLastRun(_BaseStatusTest):
    def setUp(self) -> None:
        super().setUp()
        sync_chats.LAST_RUN_PATH.write_text(json.dumps(_CANONICAL_LAST_RUN))

    def test_reads_last_run_json_when_present(self):
        output = self._run_status()
        expected_line = sync_chats._format_summary(_CANONICAL_LAST_RUN)
        self.assertIn(expected_line, output)

    def test_displays_run_finished_at(self):
        output = self._run_status()
        self.assertIn("2026-04-15T10:00:01+00:00", output)

    def test_displays_machine_label(self):
        output = self._run_status()
        self.assertIn("test-mbp", output, "machine_label from last_run.json should appear")


class TestCmdStatusFallback(_BaseStatusTest):
    def test_falls_back_to_state_last_run_at(self):
        # No last_run.json — cmd_status falls back to state.last_run_at.
        self.assertFalse(sync_chats.LAST_RUN_PATH.exists())
        output = self._run_status()
        self.assertIn("2026-04-14T09:00:00+00:00", output)
        # Fallback path does NOT include the D-23 summary line (it's Phase 1 output).
        self.assertNotIn("Synced 2 new chats", output)

    def test_falls_back_on_empty_last_run_json(self):
        sync_chats.LAST_RUN_PATH.write_text("{}")
        output = self._run_status()
        # Empty dict triggers fallback — no crash, no KeyError.
        self.assertIn("2026-04-14T09:00:00+00:00", output)


class TestCmdStatusShape(_BaseStatusTest):
    def test_still_shows_pending_count(self):
        output = self._run_status()
        self.assertIn("Pending:", output, "CORE-13 pending count must still appear")


if __name__ == "__main__":
    unittest.main()
