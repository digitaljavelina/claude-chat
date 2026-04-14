"""Unit tests for Phase 4: cmd_mine subcommand (MemPalace bulk-mine integration).

Run with: pipx run pytest tests/test_mine.py -v

Test classes map 1:1 to VALIDATION.md task IDs:
  - TestCmdMine          — MEM-01 happy path (4-01-02, 4-01-03)
  - TestCmdMineGracefulDeg — MEM-02 error paths (filled in Plan 02)
  - TestCmdMineSummary   — MEM-03 stdout format (filled in Plan 03)
  - TestSkillMineStep    — SKILL.md Step 4 (filled in Plan 03)

Python beginner note: unittest.TestCase is the standard Python testing base
class. Each method named test_* is run independently. self.skipTest() marks
a test as pending without failing the suite.
"""

import argparse
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ─── Bootstrap: add project root to sys.path so 'import sync_chats' works ──────
#
# sys.path is the list of directories Python searches when you do 'import X'.
# We insert the project root (one level above 'tests/') so that
# 'import sync_chats' finds sync_chats.py at the project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync_chats

# ─── SKILL.md path (per reference_skill_md_tests_ci.md) ─────────────────────────
#
# SKILL.md is per-user and not checked in to the repo (D-09 from Phase 2).
# Tests that read it must be guarded with @unittest.skipUnless so CI passes
# on machines where the skill is not installed.
_SKILL_PATH = Path.home() / ".claude" / "skills" / "sync-chats" / "SKILL.md"


class TestCmdMine(unittest.TestCase):
    """MEM-01 happy path: cmd_mine invokes mempalace with correct argv.

    Task IDs: 4-01-02, 4-01-03
    """

    def test_runs_correct_command(self):
        """MEM-01: cmd_mine invokes subprocess.run with correct list-form argv."""
        fake_args = argparse.Namespace()

        with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), patch(
            "sync_chats._require_config",
            return_value={
                "vault_path": "/tmp/fake-vault",
                "machine_label": "test",
                "schema_version": 1,
            },
        ), patch("sync_chats.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            sync_chats.cmd_mine(fake_args)

        # Exactly one subprocess invocation
        self.assertEqual(mock_run.call_count, 1)
        argv, kwargs = mock_run.call_args
        # T-4-01: list-form argv (positional), not shell=True
        self.assertEqual(
            argv[0],
            [
                "mempalace",
                "mine",
                "/tmp/fake-vault/Chats",
                "--mode",
                "convos",
                "--extract",
                "general",
            ],
        )
        self.assertNotIn("shell", kwargs)  # or: self.assertFalse(kwargs.get("shell"))
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))
        self.assertEqual(kwargs.get("timeout"), 300)

    def test_vault_path_from_config(self):
        """MEM-01: vault path resolved dynamically from _require_config, not hardcoded."""
        fake_args = argparse.Namespace()

        for vault in ["/vault-one", "/vault-two"]:
            with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), patch(
                "sync_chats._require_config",
                return_value={
                    "vault_path": vault,
                    "machine_label": "t",
                    "schema_version": 1,
                },
            ), patch("sync_chats.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                sync_chats.cmd_mine(fake_args)
                argv, _ = mock_run.call_args
                # argv[0] is the subprocess argv list; index 2 is the vault_chats target.
                # Order: ["mempalace", "mine", vault_chats, "--mode", "convos", "--extract", "general"]
                # The vault_chats target must reflect the current config, not a stale value.
                self.assertEqual(argv[0][2], f"{vault}/Chats")


class TestCmdMineGracefulDeg(unittest.TestCase):
    """MEM-02 graceful degradation: binary absent, non-zero exit, timeout.

    Task IDs: 4-02-01, 4-02-02, 4-02-03
    (Filled in Plan 02 — stubs present so Plan 02 can un-skip without adding names.)
    """

    def test_binary_absent_skipped(self):
        """MEM-02: binary-not-found → exit 0, skipped outcome, sync.log warning, no subprocess call."""
        fake_args = argparse.Namespace()

        with patch("sync_chats.shutil.which", return_value=None), patch(
            "sync_chats._require_config",
            return_value={
                "vault_path": "/tmp/fake-vault",
                "machine_label": "t",
                "schema_version": 1,
            },
        ), patch("sync_chats._log_sync") as mock_log, patch("sync_chats.subprocess.run") as mock_run, patch(
            "builtins.print"
        ) as mock_print:
            sync_chats.cmd_mine(fake_args)

        # No subprocess invocation when binary is absent
        mock_run.assert_not_called()
        # Exact stdout format (D-14/D-15)
        mock_print.assert_called_once_with("mempalace_mined: skipped (command not found)")
        # Sync log mentions mempalace + not found (exact wording is Claude's discretion per CONTEXT.md)
        mock_log.assert_called_once()
        log_msg = mock_log.call_args[0][0]
        self.assertIn("mempalace", log_msg)
        self.assertIn("not found", log_msg)

    def test_nonzero_exit_false(self):
        """MEM-02 / D-07 / D-11: non-zero exit → false outcome, last 20 stderr lines logged."""
        fake_args = argparse.Namespace()
        # 30 lines so we can prove slicing takes the last 20, not the first 10.
        stderr_lines = [f"err line {i}" for i in range(30)]
        fake_stderr = "\n".join(stderr_lines)

        with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), patch(
            "sync_chats._require_config",
            return_value={
                "vault_path": "/tmp/fake-vault",
                "machine_label": "t",
                "schema_version": 1,
            },
        ), patch("sync_chats.subprocess.run") as mock_run, patch("sync_chats._log_sync") as mock_log, patch(
            "builtins.print"
        ) as mock_print:
            mock_run.return_value = MagicMock(returncode=2, stdout="", stderr=fake_stderr)
            sync_chats.cmd_mine(fake_args)

        mock_print.assert_called_once_with("mempalace_mined: false (exit 2)")
        mock_log.assert_called_once()
        logged = mock_log.call_args[0][0]
        # Last 20 lines present
        self.assertIn("err line 29", logged)
        self.assertIn("err line 10", logged)
        # First 10 lines NOT present (proves slicing is [-20:], not [:20])
        self.assertNotIn("err line 0\n", logged)
        self.assertNotIn("err line 9\n", logged)

    def test_timeout_false(self):
        """MEM-02 / D-09 / T-4-04: TimeoutExpired → false (timeout after 300s), sync.log warning."""
        fake_args = argparse.Namespace()

        with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), patch(
            "sync_chats._require_config",
            return_value={
                "vault_path": "/tmp/fake-vault",
                "machine_label": "t",
                "schema_version": 1,
            },
        ), patch(
            "sync_chats.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="mempalace", timeout=300),
        ), patch("sync_chats._log_sync") as mock_log, patch("builtins.print") as mock_print:
            # Must not raise
            sync_chats.cmd_mine(fake_args)

        mock_print.assert_called_once_with("mempalace_mined: false (timeout after 300s)")
        mock_log.assert_called_once()
        log_msg = mock_log.call_args[0][0]
        self.assertIn("timed out", log_msg)
        self.assertIn("300", log_msg)


class TestCmdMineSummary(unittest.TestCase):
    """MEM-03 stdout format: mempalace_mined line in sync summary.

    Task IDs: 4-03-01, 4-03-02
    (Filled in Plan 03.)
    """

    def test_true_on_success(self):
        """MEM-03: summary line reads 'mempalace_mined: true' on success."""
        self.skipTest("pending 4-03-01")

    def test_skipped_with_reason(self):
        """MEM-03: summary line includes reason when skipped or false."""
        self.skipTest("pending 4-03-02")


@unittest.skipUnless(_SKILL_PATH.exists(), "SKILL.md not installed on this host")
class TestSkillMineStep(unittest.TestCase):
    """SKILL.md Step 4: mine subcommand called as final pipeline step.

    Task ID: 4-03-03
    (Filled in Plan 03 — class-level skip guard matches reference_skill_md_tests_ci.md.)
    """

    def test_skill_step4_calls_mine(self):
        """SKILL.md Step 4 invokes 'python3 sync_chats.py mine' as final step."""
        self.skipTest("pending 4-03-03")


if __name__ == "__main__":
    unittest.main()
