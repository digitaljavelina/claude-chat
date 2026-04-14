"""End-to-end canary test: full pipeline on synthetic PII -> zero CANARY survivors.

Run with: python3 -m unittest tests.test_scrub_canary -v

This is the PRIV-04 acceptance test. It exercises:
  load (JSONL) -> scrub (scrub_content in _get_markdown_body) ->
  label (stub) -> write (cmd_write) -> grep vault bytes

Mocks claude-chat.py via patching subprocess.run so the test doesn't need a
real claude-chat.py install -- we stream the canary JSONL content back as if
claude-chat.py export had rendered it.

Asserts:
  - No CANARY substring in vault file (PRIV-04 / ROADMAP SC#1)
  - Private IPs (192.168.1.100, 127.0.0.1) preserved (D-10 skip-list)
  - Redaction tokens <REDACTED:...> present (scrub actually ran)
  - privacy_review frontmatter in scrubbed state (D-08)
  - sync.log D-21 scrub line present
  - sync.log contains no CANARY substring (PRIV-06 / ROADMAP SC#4)
"""

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

# Bootstrap CLAUDE_CHAT_HOME before import -- sync_chats reads it at import time.
_GLOBAL_TEMP = tempfile.mkdtemp(prefix="canary_bootstrap_")
os.environ["CLAUDE_CHAT_HOME"] = _GLOBAL_TEMP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sync_chats  # noqa: E402


CANARY_JSONL = os.path.join(os.path.dirname(__file__), "canary_session.jsonl")


def _canary_body_text() -> str:
    """Extract message text from canary_session.jsonl as markdown-ish body.

    Stands in for what claude-chat.py export --format md --stdout would render.
    scrub_content operates on the body string, so the exact markdown wrapping
    doesn't matter -- what matters is that every CANARY-bearing secret appears
    in the text we feed through the pipeline.
    """
    parts = []
    with open(CANARY_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            msg = obj.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                # assistant messages use a list of content blocks
                content = "\n".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
            if content:
                role = msg.get("role", "?")
                parts.append(f"## {role}\n\n{content}\n")
    return "\n".join(parts)


class TestCanaryPipeline(unittest.TestCase):
    """PRIV-04: feed canary through full pipeline, grep vault for CANARY -> zero."""

    def setUp(self):
        # Isolate home + vault + projects in tempdirs so no real user state is touched.
        self.tmp_home = Path(tempfile.mkdtemp(prefix="canary_home_"))
        self.tmp_vault = Path(tempfile.mkdtemp(prefix="canary_vault_"))
        self.tmp_projects = Path(tempfile.mkdtemp(prefix="canary_projects_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp_home, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(self.tmp_vault, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(self.tmp_projects, ignore_errors=True))

        # Save + override sync_chats module-level paths. sync_chats reads these
        # at import, so we swap them in setUp and restore in tearDown.
        self._saved = (
            sync_chats.CLAUDE_CHAT_HOME,
            sync_chats.CONFIG_PATH,
            sync_chats.STATE_PATH,
            sync_chats.LOG_PATH,
            sync_chats.PROJECTS_DIR,
        )
        sync_chats.CLAUDE_CHAT_HOME = self.tmp_home
        sync_chats.CONFIG_PATH = self.tmp_home / "config.json"
        sync_chats.STATE_PATH = self.tmp_home / "state.json"
        sync_chats.LOG_PATH = self.tmp_home / "sync.log"
        sync_chats.PROJECTS_DIR = self.tmp_projects

        # Seed a minimal config + empty state
        sync_chats.CONFIG_PATH.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "machine_label": "canary",
                    "vault_path": str(self.tmp_vault),
                }
            )
        )
        sync_chats.STATE_PATH.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "synced_session_ids": [],
                    "fingerprints": {},
                    "last_run_at": None,
                }
            )
        )

        # Place the canary JSONL at the right depth: PROJECTS_DIR/<proj>/<sid>.jsonl
        # (cmd_write walks PROJECTS_DIR.rglob for files whose stem == session_id
        #  and whose relative-path depth is 2; see sync_chats.cmd_write Step 4a.)
        self.session_id = "canary00-0000-0000-0000-000000000000"
        proj_dir = self.tmp_projects / "canary-project"
        proj_dir.mkdir()
        shutil.copy(CANARY_JSONL, proj_dir / f"{self.session_id}.jsonl")

    def tearDown(self):
        (
            sync_chats.CLAUDE_CHAT_HOME,
            sync_chats.CONFIG_PATH,
            sync_chats.STATE_PATH,
            sync_chats.LOG_PATH,
            sync_chats.PROJECTS_DIR,
        ) = self._saved

    def _run_write(self, label_overrides=None):
        """Invoke cmd_write with mocked subprocess + stdin. Returns the written vault file Path."""
        canary_body = _canary_body_text()
        # Pretend claude-chat.py export rendered the canary body. Scrub runs
        # AFTER this in _get_markdown_body, which is what we're testing.
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=canary_body, stderr="")
        label = {
            "title": "Canary test session",
            "gist": None,
            "tags": ["canary", "test"],
            "coherence_score": None,
            "needs_review": False,  # forced to True if privacy_review=="uncertain" (D-07)
        }
        if label_overrides:
            label.update(label_overrides)
        label_json = json.dumps(label)

        args = mock.MagicMock()
        args.session_id = self.session_id

        with mock.patch("sync_chats.subprocess.run", return_value=fake_result), mock.patch(
            "sys.stdin", io.StringIO(label_json)
        ):
            try:
                sync_chats.cmd_write(args)
            except SystemExit as e:
                if e.code not in (0, None):
                    raise

        chats_dir = self.tmp_vault / "Chats"
        vault_files = list(chats_dir.glob("*.md"))
        return vault_files

    def test_full_pipeline_zero_canary_survivors(self):
        """ROADMAP SC#1 + PRIV-04: grep vault for CANARY -> zero hits."""
        vault_files = self._run_write()
        self.assertEqual(len(vault_files), 1, f"expected 1 vault file, got {len(vault_files)}")
        vault_file = vault_files[0]
        vault_bytes = vault_file.read_bytes()

        # --- PRIV-04 / ROADMAP SC#1: zero CANARY substrings survive ---
        self.assertNotIn(
            b"CANARY",
            vault_bytes,
            f"CANARY substring survived scrub in {vault_file.name}",
        )

        # Sanity: redaction tokens actually present (proves scrub ran, not just stripped)
        self.assertIn(b"<REDACTED:", vault_bytes, "no <REDACTED:...> tokens in vault file -- did scrub run?")

        # --- D-10 skip-list: private IPs preserved unchanged ---
        self.assertIn(b"192.168.1.100", vault_bytes, "private IP 192.168.1.100 was wrongly redacted (D-10 skip-list)")
        self.assertIn(b"127.0.0.1", vault_bytes, "loopback 127.0.0.1 was wrongly redacted (D-10 skip-list)")

        # --- D-08: privacy_review frontmatter field present ---
        head = vault_file.read_text()[:2000]
        self.assertTrue(
            "privacy_review: scrubbed" in head or "privacy_review: uncertain" in head,
            f"privacy_review not in scrubbed|uncertain state -- frontmatter head:\n{head[:400]}",
        )

        # Spot-check a few specific redaction tokens are present
        self.assertIn(b"<REDACTED:email>", vault_bytes)
        self.assertIn(b"<REDACTED:jwt>", vault_bytes)
        self.assertIn(b"<REDACTED:github_token>", vault_bytes)

    def test_sync_log_contains_no_canary(self):
        """PRIV-06 + ROADMAP SC#4: sync.log has pattern names + counts only, no CANARY."""
        self._run_write({"title": "Canary log test", "tags": ["canary"]})

        log_text = sync_chats.LOG_PATH.read_text() if sync_chats.LOG_PATH.exists() else ""

        # PRIV-06: log must not contain the CANARY sentinel (would mean a matched substring leaked)
        self.assertNotIn(
            "CANARY",
            log_text,
            f"CANARY substring leaked into sync.log:\n{log_text}",
        )
        # D-21 format: "scrub session=<short> patterns={...} total_chars=N"
        self.assertIn("scrub session=", log_text, "expected a D-21 scrub log line in sync.log")
        self.assertIn("patterns={", log_text)
        # Spot-check: no @ sign (would indicate email leaked -- timestamps use + not @)
        self.assertNotIn("@", log_text, "@ sign in sync.log suggests email leaked")


if __name__ == "__main__":
    unittest.main()
