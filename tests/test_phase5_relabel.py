"""Unit tests for Phase 5 Plan 04: cmd_relabel subcommand (HOOK-04 / D-04 / D-05).

Run with: pipx run pytest tests/test_phase5_relabel.py -v

Enforces the D-05 sentinel-only guard: re-label trigger is `auto_label_hash == "stub"`,
never `needs_review` alone. Body bytes MUST be preserved byte-for-byte across a
relabel (the Phase 3 scrub was already applied at original write time).
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
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


_SID = "aaaa1111-2222-3333-4444-555566667777"
_BODY = "# Chat Body\n\nHello world. This is the existing scrubbed body.\n"


def _stub_frontmatter(session_id: str = _SID) -> dict:
    return {
        "title": f"Untitled {session_id[:8]}",
        "gist": None,
        "tags": ["stub"],
        "coherence_score": None,
        "needs_review": True,
        "privacy_review": "clean",
        "project": "testproject",
        "session_id": session_id,
        "model": "claude-sonnet-4-20250514",
        "token_count": 70,
        "msg_count": 2,
        "machine": "test-mbp",
        "hostname": "test-host",
        "synced_at": "2026-04-15T10:00:00+00:00",
        "auto_label_hash": "stub",
    }


def _fresh_label() -> dict:
    return {
        "title": "Debug the export markdown function",
        "gist": "Fixing the claude-chat export --stdout bug.",
        "tags": ["python", "claude-chat", "debug"],
        "coherence_score": 4,
        "needs_review": False,
    }


class _BaseRelabelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.projects = self.tmp / "projects"
        self.projects.mkdir()
        self.vault = self.tmp / "vault"
        self.chats = self.vault / "Chats"
        self.chats.mkdir(parents=True)

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
                    "machine_label": "test-mbp",
                    "vault_path": str(self.vault),
                }
            )
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_vault_file(self, frontmatter: dict, body: str = _BODY) -> Path:
        fm_str = sync_chats.emit_frontmatter(frontmatter)
        path = self.chats / "test-mbp--2026-04-15--untitled.md"
        path.write_text(fm_str + body, encoding="utf-8")
        return path

    def _run_relabel(self, session_id: str, label: dict) -> int:
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(label))):
            try:
                sync_chats.cmd_relabel(mock.Mock(session_id=session_id))
                return 0
            except SystemExit as e:
                return int(e.code) if e.code is not None else 0


class TestRelabelHappyPath(_BaseRelabelTest):
    def test_upgrades_stub_sentinel_to_real_hash(self):
        path = self._write_vault_file(_stub_frontmatter())
        expected_hash = hashlib.sha256(_BODY.encode("utf-8")).hexdigest()

        code = self._run_relabel(_SID, _fresh_label())
        self.assertEqual(code, 0)

        updated = path.read_text(encoding="utf-8")
        self.assertIn(f"auto_label_hash: {expected_hash}", updated)
        self.assertIn("title: Debug the export markdown function", updated)
        self.assertIn("needs_review: false", updated)
        self.assertIn("- python", updated)
        self.assertIn("coherence_score: 4", updated)

    def test_body_is_untouched(self):
        path = self._write_vault_file(_stub_frontmatter())
        self._run_relabel(_SID, _fresh_label())

        # Extract body from updated file by splitting on --- delimiters.
        updated = path.read_text(encoding="utf-8")
        parts = updated.split("---\n", 2)
        # parts == ["", "<frontmatter>", "<body>"]
        self.assertEqual(parts[2], _BODY, "body bytes must be byte-identical after relabel")


class TestRelabelRefuse(_BaseRelabelTest):
    def test_refuses_when_hash_is_real_sha256(self):
        fm = _stub_frontmatter()
        real_hash = hashlib.sha256(_BODY.encode("utf-8")).hexdigest()
        fm["auto_label_hash"] = real_hash
        fm["needs_review"] = False
        path = self._write_vault_file(fm)
        before_bytes = path.read_bytes()

        code = self._run_relabel(_SID, _fresh_label())
        self.assertEqual(code, 1)

        self.assertEqual(path.read_bytes(), before_bytes, "file must be unchanged after refusal")

    def test_refuses_when_needs_review_true_but_hash_is_real(self):
        fm = _stub_frontmatter()
        fm["auto_label_hash"] = hashlib.sha256(_BODY.encode("utf-8")).hexdigest()
        fm["needs_review"] = True  # user-flagged but hash is real
        path = self._write_vault_file(fm)
        before = path.read_bytes()

        code = self._run_relabel(_SID, _fresh_label())
        self.assertEqual(code, 1, "D-05: sentinel-only; needs_review alone is not a trigger")
        self.assertEqual(path.read_bytes(), before)

    def test_refuses_when_file_missing(self):
        # No vault file created — cmd_relabel should report + exit 1.
        code = self._run_relabel("00000000-0000-0000-0000-000000000000", _fresh_label())
        self.assertEqual(code, 1)


class TestRelabelInput(_BaseRelabelTest):
    def test_reads_label_from_stdin(self):
        self._write_vault_file(_stub_frontmatter())
        # Invalid JSON on stdin → exit 1.
        with mock.patch.object(sys, "stdin", io.StringIO("not valid json{{")):
            with self.assertRaises(SystemExit) as ctx:
                sync_chats.cmd_relabel(mock.Mock(session_id=_SID))
        self.assertEqual(ctx.exception.code, 1)

    def test_missing_title_is_fatal(self):
        self._write_vault_file(_stub_frontmatter())
        bad_label = {"gist": "no title here", "tags": [], "coherence_score": None, "needs_review": False}
        code = self._run_relabel(_SID, bad_label)
        self.assertEqual(code, 1)


class TestRelabelFrontmatterOnly(_BaseRelabelTest):
    def test_scrub_not_re_run(self):
        # Ship a body that contains an email-looking string that scrub WOULD redact.
        # If cmd_relabel re-ran scrub, "michael@example.com" would be replaced with
        # <REDACTED:email>. We assert the string is preserved verbatim.
        body = "Here is an email: michael@example.com — preserved verbatim.\n"
        fm = _stub_frontmatter()
        path = self._write_vault_file(fm, body=body)

        self._run_relabel(_SID, _fresh_label())

        updated = path.read_text(encoding="utf-8")
        self.assertIn("michael@example.com", updated, "scrub must NOT re-run on relabel")


class TestRelabelArgparse(unittest.TestCase):
    def test_subcommand_registered(self):
        # Invoke `python3 sync_chats.py --help` and confirm 'relabel' appears.
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(repo_root / "sync_chats.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertIn("relabel", result.stdout, "relabel subcommand missing from --help")


if __name__ == "__main__":
    unittest.main()
