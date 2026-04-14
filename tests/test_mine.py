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
        self.skipTest("pending 4-01-02")

    def test_vault_path_from_config(self):
        """MEM-01: vault path resolved dynamically from _require_config, not hardcoded."""
        self.skipTest("pending 4-01-03")


class TestCmdMineGracefulDeg(unittest.TestCase):
    """MEM-02 graceful degradation: binary absent, non-zero exit, timeout.

    Task IDs: 4-02-01, 4-02-02, 4-02-03
    (Filled in Plan 02 — stubs present so Plan 02 can un-skip without adding names.)
    """

    def test_binary_absent_skipped(self):
        """MEM-02: cmd_mine prints skipped when mempalace is not installed."""
        self.skipTest("pending 4-02-01")

    def test_nonzero_exit_false(self):
        """MEM-02: cmd_mine prints false when mempalace exits non-zero."""
        self.skipTest("pending 4-02-02")

    def test_timeout_false(self):
        """MEM-02: cmd_mine prints false on TimeoutExpired."""
        self.skipTest("pending 4-02-03")


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
