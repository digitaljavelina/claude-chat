"""Unit tests for Phase 5 Plan 02: cmd_once + root --once flag (HOOK-01..04, OBSERV-02/03).

Run with: pipx run pytest tests/test_phase5_once.py -v

Tests for Task 1 of Plan 05-02 (TDD RED phase).

Test classes map to VALIDATION.md:
  TestCmdOnceHappyPath   — HOOK-01 + OBSERV-03 (stub writes + last_run.json)
  TestCmdOnceEmpty       — HOOK-01 no-op path
  TestCmdOnceFailure     — OBSERV-03 errors[] + D-13 cap + D-10 exit codes
  TestCmdOnceSentinel    — D-03 auto_label_hash: stub
  TestCmdOnceArgparse    — RESEARCH Pitfall 1 (--once wins over subcommand-None)
  TestCmdOnceLog         — OBSERV-02 run-start/run-finish lines
  TestCmdOncePreflight   — Phase 1 D-31 (exit 2 on no config)
  TestCmdOnceNoStdin     — RESEARCH Pitfall 2 (never block on stdin)

Python beginner notes:
  - importlib.reload() rebinds module-level Path constants after env override.
  - unittest.mock.patch() temporarily swaps a function/attr for a fake.
  - SystemExit is raised by sys.exit(); catch with assertRaises(SystemExit) and
    inspect exc.code.
"""

import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# ─── Bootstrap BEFORE import sync_chats (env overrides rebind paths) ────────
_GLOBAL_TEMP = tempfile.mkdtemp()
_GLOBAL_PROJECTS = os.path.join(_GLOBAL_TEMP, "projects")
os.makedirs(_GLOBAL_PROJECTS, exist_ok=True)
os.environ["CLAUDE_CHAT_HOME"] = _GLOBAL_TEMP
os.environ["CLAUDE_PROJECTS_DIR"] = _GLOBAL_PROJECTS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync_chats  # noqa: E402


_SID_A = "aaaa1111-2222-3333-4444-555566667777"
_SID_B = "bbbb1111-2222-3333-4444-555566667777"


def _jsonl_content(session_id: str, first_msg: str = "Hello world test message") -> str:
    return (
        json.dumps(
            {
                "parentUuid": None,
                "type": "human",
                "message": {"role": "user", "content": first_msg},
                "uuid": "msg-001",
                "timestamp": "2026-04-15T10:00:00.000Z",
                "sessionId": session_id,
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
                "sessionId": session_id,
            }
        )
        + "\n"
    )


def _make_config(vault_path: str) -> dict:
    return {
        "schema_version": 1,
        "machine_label": "testmac",
        "vault_path": vault_path,
    }


def _make_state() -> dict:
    return {
        "schema_version": 1,
        "last_run_at": None,
        "synced_session_ids": [],
        "fingerprints": {},
    }


_FAKE_SCRUB_STATS = {"uncertain": 0, "total_chars_redacted": 0}


class _BaseCmdOnceTest(unittest.TestCase):
    """Shared setUp: isolate FS via CLAUDE_CHAT_HOME + CLAUDE_PROJECTS_DIR tmpdirs."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.projects = self.tmp / "projects"
        self.projects.mkdir()
        self.vault_dir = self.tmp / "vault" / "Chats"
        self.vault_dir.mkdir(parents=True)

        # Rebind module-level paths (faster than importlib.reload — same pattern
        # as test_phase5_write_session.py).
        sync_chats.CLAUDE_CHAT_HOME = self.tmp
        sync_chats.CONFIG_PATH = self.tmp / "config.json"
        sync_chats.STATE_PATH = self.tmp / "state.json"
        sync_chats.LOG_PATH = self.tmp / "sync.log"
        sync_chats.LAST_RUN_PATH = self.tmp / "last_run.json"
        sync_chats.PROJECTS_DIR = self.projects

        # Write a valid config (cmd_once pre-flight requires it)
        config = _make_config(str(self.tmp / "vault"))
        sync_chats.CONFIG_PATH.write_text(json.dumps(config))

        # Seed an empty state file
        state = _make_state()
        sync_chats.STATE_PATH.write_text(json.dumps(state))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_session(self, session_id: str, project: str = "testproject") -> Path:
        """Create a synthetic JSONL at projects/<project>/<session_id>.jsonl."""
        proj_dir = self.projects / project
        proj_dir.mkdir(exist_ok=True)
        p = proj_dir / f"{session_id}.jsonl"
        p.write_text(_jsonl_content(session_id))
        return p

    def _patch_markdown_body(self):
        return mock.patch(
            "sync_chats._get_markdown_body",
            return_value=("## Fake body\n\nHello.", _FAKE_SCRUB_STATS),
        )


class TestCmdOnceHappyPath(_BaseCmdOnceTest):
    def test_writes_stub_file_and_last_run_json(self):
        self._add_session(_SID_A)
        self._add_session(_SID_B)

        with self._patch_markdown_body():
            with self.assertRaises(SystemExit) as ctx:
                sync_chats.cmd_once(mock.Mock(once=True))

        self.assertEqual(ctx.exception.code, 0)

        # last_run.json was written with D-11 shape
        lr = json.loads(sync_chats.LAST_RUN_PATH.read_text())
        self.assertEqual(lr["trigger"], "once")
        self.assertEqual(lr["schema_version"], 1)
        self.assertEqual(lr["synced"], 2)
        self.assertEqual(lr["skipped"], 0)
        self.assertEqual(lr["failed"], 0)
        self.assertEqual(lr["flagged_for_review"], 2)
        self.assertEqual(lr["mempalace_mined"], "skipped")
        self.assertEqual(lr["exit_code"], 0)
        self.assertIn("run_started_at", lr)
        self.assertIn("run_finished_at", lr)
        self.assertIn("machine_label", lr)
        self.assertIn("hostname", lr)
        self.assertEqual(lr["errors"], [])


class TestCmdOnceEmpty(_BaseCmdOnceTest):
    def test_no_new_sessions(self):
        # All sessions already synced → discover_sessions returns []
        with self._patch_markdown_body():
            with self.assertRaises(SystemExit) as ctx:
                sync_chats.cmd_once(mock.Mock(once=True))
        self.assertEqual(ctx.exception.code, 0)

        lr = json.loads(sync_chats.LAST_RUN_PATH.read_text())
        self.assertEqual(lr["synced"], 0)
        self.assertEqual(lr["skipped"], 0)
        self.assertEqual(lr["failed"], 0)
        self.assertEqual(lr["flagged_for_review"], 0)


class TestCmdOnceFailure(_BaseCmdOnceTest):
    def test_one_session_fails(self):
        self._add_session(_SID_A)
        self._add_session(_SID_B)

        real_write = sync_chats._write_session

        def flaky_write(session_id, label, config, state):
            if session_id == _SID_A:
                raise RuntimeError("boom on A")
            return real_write(session_id, label, config, state)

        stderr_buf = io.StringIO()
        with self._patch_markdown_body(), mock.patch("sync_chats._write_session", side_effect=flaky_write), mock.patch(
            "sys.stderr", stderr_buf
        ):
            with self.assertRaises(SystemExit) as ctx:
                sync_chats.cmd_once(mock.Mock(once=True))

        self.assertEqual(ctx.exception.code, 1)
        captured_stderr = stderr_buf.getvalue()
        self.assertLessEqual(
            len(captured_stderr), 200, f"stderr too long ({len(captured_stderr)} chars): {captured_stderr!r}"
        )
        self.assertNotIn("Traceback", captured_stderr)
        lr = json.loads(sync_chats.LAST_RUN_PATH.read_text())
        self.assertEqual(lr["synced"], 1)
        self.assertEqual(lr["failed"], 1)
        self.assertEqual(len(lr["errors"]), 1)
        self.assertEqual(lr["errors"][0]["session_id"], _SID_A)
        self.assertEqual(lr["errors"][0]["error_class"], "RuntimeError")
        self.assertIn("boom on A", lr["errors"][0]["error_message"])

    def test_errors_capped_at_10(self):
        for i in range(15):
            self._add_session(f"cccc{i:04d}-2222-3333-4444-555566667777")

        with self._patch_markdown_body(), mock.patch("sync_chats._write_session", side_effect=RuntimeError("nope")):
            with self.assertRaises(SystemExit):
                sync_chats.cmd_once(mock.Mock(once=True))

        lr = json.loads(sync_chats.LAST_RUN_PATH.read_text())
        self.assertEqual(lr["failed"], 15)
        self.assertEqual(len(lr["errors"]), 10)  # D-13 cap


class TestCmdOnceSentinel(_BaseCmdOnceTest):
    def test_auto_label_hash_is_literal_stub(self):
        self._add_session(_SID_A)
        with self._patch_markdown_body():
            with self.assertRaises(SystemExit):
                sync_chats.cmd_once(mock.Mock(once=True))

        files = list(self.vault_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        content = files[0].read_text()
        self.assertIn("auto_label_hash: stub", content, "D-03 sentinel not present in frontmatter")


class TestCmdOnceArgparse(_BaseCmdOnceTest):
    def test_once_flag_wins_over_no_subcommand(self):
        # main() with sys.argv = ["sync_chats.py", "--once"] must dispatch cmd_once,
        # NOT print help and exit.
        self._add_session(_SID_A)

        with self._patch_markdown_body(), mock.patch.object(sys, "argv", ["sync_chats.py", "--once"]):
            with self.assertRaises(SystemExit) as ctx:
                sync_chats.main()

        self.assertEqual(ctx.exception.code, 0)
        # last_run.json must exist — proves cmd_once actually ran
        self.assertTrue(sync_chats.LAST_RUN_PATH.exists())


class TestCmdOnceLog(_BaseCmdOnceTest):
    def test_run_start_and_finish_logged(self):
        self._add_session(_SID_A)
        with self._patch_markdown_body():
            with self.assertRaises(SystemExit):
                sync_chats.cmd_once(mock.Mock(once=True))

        log_text = sync_chats.LOG_PATH.read_text()
        self.assertIn("run-start trigger=once", log_text)
        self.assertIn("run-finish trigger=once", log_text)


class TestCmdOncePreflight(_BaseCmdOnceTest):
    def test_exits_2_when_no_config(self):
        sync_chats.CONFIG_PATH.unlink()
        with self.assertRaises(SystemExit) as ctx:
            sync_chats.cmd_once(mock.Mock(once=True))
        self.assertEqual(ctx.exception.code, 2)


class TestCmdOnceNoStdin(_BaseCmdOnceTest):
    def test_does_not_block_on_stdin(self):
        # Replace stdin with a closed buffer; if cmd_once reads stdin, it would
        # either hang or raise. We assert it runs cleanly instead.
        self._add_session(_SID_A)
        with self._patch_markdown_body(), mock.patch.object(sys, "stdin", io.StringIO("")):
            with self.assertRaises(SystemExit) as ctx:
                sync_chats.cmd_once(mock.Mock(once=True))
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
