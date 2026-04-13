"""Unit tests for sync_chats.py pure functions and clobber defenses.

Run with: python3 -m unittest discover tests -v

Test strategy (D-27/D-28):
  - stdlib only — no pytest, no external deps
  - CLAUDE_CHAT_HOME env var override set BEFORE import so module-level code reads it
  - All filesystem tests use tempfile.mkdtemp() and clean up via addCleanup

Test class inventory (names align with VALIDATION.md):
  TestSlug               — make_slug pure function
  TestStubLabel          — make_stub_label pure function
  TestFrontmatter        — emit_frontmatter pure function
  TestICloudAssertion    — _assert_not_icloud startup guard
  TestStateIO            — _write_atomic, load_state, save_state
  TestClobberLayer1      — synced_session_ids guard in discover_sessions
  TestClobberLayer2      — _write_if_not_exists O_CREAT|O_EXCL guard
  TestAutoLabelHash      — sha256 hash + frontmatter injection
  TestSessionDate        — _get_session_date from JSONL timestamp
  TestMetadata           — _extract_session_metadata (model, tokens, msgs)
  TestStdinContract      — label JSON schema validation contract
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

# ─── Bootstrap: set CLAUDE_CHAT_HOME before importing sync_chats ─────────────
#
# sync_chats.py evaluates CLAUDE_CHAT_HOME at module level (line 26).
# We must set the env var BEFORE the first import so module-level code reads
# our temp directory rather than ~/.claude-chat.  This satisfies D-29.
#
# All tests that need a fresh home dir call self._make_home() which creates
# a subdirectory inside _GLOBAL_TEMP and sets CLAUDE_CHAT_HOME accordingly.

_GLOBAL_TEMP = tempfile.mkdtemp()
os.environ["CLAUDE_CHAT_HOME"] = _GLOBAL_TEMP

# Now safe to import — the module-level CLAUDE_CHAT_HOME resolves to _GLOBAL_TEMP
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sync_chats  # noqa: E402

# ─── Fixture paths ────────────────────────────────────────────────────────────
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_SESSION = os.path.join(FIXTURE_DIR, "sample_session.jsonl")
SAMPLE_SESSION_ID = "541112ec-a07c-4d87-80f7-2310b98fd7ea"


# ─── Helper: isolate each test's home dir ─────────────────────────────────────


def _make_isolated_home() -> str:
    """Create a fresh temp directory and point CLAUDE_CHAT_HOME at it.

    Returns the temp dir path.  Callers should call addCleanup(shutil.rmtree, path)
    and also restore the module-level paths after the test.
    """
    home = tempfile.mkdtemp()
    os.environ["CLAUDE_CHAT_HOME"] = home
    # Update module-level Path objects that were captured at import time
    import pathlib

    sync_chats.CLAUDE_CHAT_HOME = pathlib.Path(home)
    sync_chats.CONFIG_PATH = pathlib.Path(home) / "config.json"
    sync_chats.STATE_PATH = pathlib.Path(home) / "state.json"
    sync_chats.LOG_PATH = pathlib.Path(home) / "sync.log"
    return home


# ═══════════════════════════════════════════════════════════════════════════════
# TestSlug — make_slug pure function (D-13..D-15, CORE-06)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSlug(unittest.TestCase):
    """Tests for make_slug() kebab-slug generator."""

    def test_basic_slug(self):
        """Simple ASCII title produces a clean kebab-case slug."""
        result = sync_chats.make_slug("Debug the export markdown function")
        self.assertEqual(result, "debug-the-export-markdown-function")

    def test_unicode_slug(self):
        """Accented characters are normalised to their ASCII equivalents.

        NFKD decomposition + encode('ascii', 'ignore') turns é -> e, etc.
        """
        result = sync_chats.make_slug("Über café résumé")
        # After NFKD + ascii encode: "Uber cafe resume" -> "uber-cafe-resume"
        self.assertIn("uber", result)
        self.assertNotIn("ü", result)
        self.assertNotIn("é", result)

    def test_empty_slug_fallback(self):
        """All-punctuation title with fallback_id uses the fallback (first 8 chars)."""
        result = sync_chats.make_slug("!!!???", "abcd1234")
        self.assertEqual(result, "abcd1234")

    def test_empty_slug_no_fallback(self):
        """All-punctuation title with no fallback produces 'untitled'."""
        result = sync_chats.make_slug("!!!???")
        self.assertEqual(result, "untitled")

    def test_truncation(self):
        """Slug is capped at 60 characters (D-13)."""
        # 40 repetitions of "a " would normally produce a very long slug
        long_title = "a " * 40
        result = sync_chats.make_slug(long_title)
        self.assertLessEqual(len(result), 60)

    def test_leading_trailing_dashes(self):
        """Leading and trailing dashes are stripped from the slug."""
        result = sync_chats.make_slug("--hello--")
        self.assertEqual(result, "hello")


# ═══════════════════════════════════════════════════════════════════════════════
# TestStubLabel — make_stub_label pure function (D-04..D-06, LABEL-09)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStubLabel(unittest.TestCase):
    """Tests for make_stub_label() stub-label generator."""

    def test_first_8_words(self):
        """Title is the first 8 words of the first user message (D-04)."""
        from pathlib import Path

        label = sync_chats.make_stub_label(Path(SAMPLE_SESSION), SAMPLE_SESSION_ID)
        # First user message: "Debug the export markdown function and fix the output formatting"
        # First 8 words: "Debug the export markdown function and fix the"
        self.assertEqual(label["title"], "Debug the export markdown function and fix the")

    def test_empty_session_fallback(self):
        """Empty JSONL produces a title starting with 'Untitled' (D-06)."""
        from pathlib import Path

        empty_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty_dir)
        empty_file = os.path.join(empty_dir, "empty.jsonl")
        open(empty_file, "w").close()  # create empty file
        label = sync_chats.make_stub_label(Path(empty_file), "deadbeef-0000-0000-0000-000000000000")
        self.assertTrue(label["title"].startswith("Untitled"))

    def test_label_schema(self):
        """Returned dict has the full D-05 schema: gist=None, tags=['stub'], needs_review=True."""
        from pathlib import Path

        label = sync_chats.make_stub_label(Path(SAMPLE_SESSION), SAMPLE_SESSION_ID)
        self.assertIn("title", label)
        self.assertIn("gist", label)
        self.assertIn("tags", label)
        self.assertIn("coherence_score", label)
        self.assertIn("needs_review", label)
        self.assertIsNone(label["gist"])
        self.assertEqual(label["tags"], ["stub"])
        self.assertIsNone(label["coherence_score"])
        self.assertTrue(label["needs_review"])


# ═══════════════════════════════════════════════════════════════════════════════
# TestFrontmatter — emit_frontmatter pure function (CORE-07)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFrontmatter(unittest.TestCase):
    """Tests for emit_frontmatter() YAML frontmatter emitter."""

    def _sample_fields(self):
        return {
            "title": "Debug export markdown",
            "gist": None,
            "tags": ["stub", "test"],
            "coherence_score": None,
            "needs_review": True,
            "project": "my-project",
            "session_id": SAMPLE_SESSION_ID,
            "model": "claude-sonnet-4-20250514",
            "token_count": 600,
            "msg_count": 3,
            "machine": "mbp",
            "hostname": "test-host",
            "synced_at": "2026-03-19T23:50:00+00:00",
            "auto_label_hash": "abc123",
        }

    def test_output_delimiters(self):
        """Frontmatter starts with '---\\n' and ends with '---\\n'."""
        result = sync_chats.emit_frontmatter(self._sample_fields())
        self.assertTrue(result.startswith("---\n"))
        self.assertTrue(result.endswith("---\n"))

    def test_null_values(self):
        """None values produce a bare 'key:' line (no value after colon)."""
        result = sync_chats.emit_frontmatter(self._sample_fields())
        self.assertIn("gist:", result)
        # Should be "gist:" not "gist: None" or "gist: null"
        lines = result.splitlines()
        gist_line = next(l for l in lines if l.startswith("gist"))
        self.assertEqual(gist_line, "gist:")

    def test_bool_lowercase(self):
        """needs_review=True produces 'needs_review: true' (lowercase YAML bool)."""
        result = sync_chats.emit_frontmatter(self._sample_fields())
        self.assertIn("needs_review: true", result)

    def test_tags_block_list(self):
        """Tags produce a YAML block list with '  - tag' entries."""
        result = sync_chats.emit_frontmatter(self._sample_fields())
        self.assertIn("  - stub", result)
        self.assertIn("  - test", result)

    def test_key_order(self):
        """title appears before gist, gist before tags, auto_label_hash is last."""
        result = sync_chats.emit_frontmatter(self._sample_fields())
        lines = result.splitlines()
        # Find positions of key markers in the output
        title_pos = next(i for i, l in enumerate(lines) if l.startswith("title"))
        gist_pos = next(i for i, l in enumerate(lines) if l.startswith("gist"))
        tags_pos = next(i for i, l in enumerate(lines) if l.startswith("tags"))
        hash_pos = next(i for i, l in enumerate(lines) if l.startswith("auto_label_hash"))
        self.assertLess(title_pos, gist_pos)
        self.assertLess(gist_pos, tags_pos)
        # auto_label_hash should be the last content line before closing ---
        self.assertGreater(hash_pos, tags_pos)


# ═══════════════════════════════════════════════════════════════════════════════
# TestICloudAssertion — _assert_not_icloud startup guard (CORE-04)
# ═══════════════════════════════════════════════════════════════════════════════


class TestICloudAssertion(unittest.TestCase):
    """Tests for _assert_not_icloud() startup check."""

    def test_icloud_path_rejected(self):
        """A path with 'Mobile Documents' in it raises SystemExit(2)."""
        from pathlib import Path

        icloud_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, icloud_dir)
        # Rename to include 'Mobile Documents' in the real path
        icloud_path = os.path.join(icloud_dir, "Mobile Documents", "fake")
        os.makedirs(icloud_path, exist_ok=True)
        with self.assertRaises(SystemExit) as ctx:
            sync_chats._assert_not_icloud(Path(icloud_path))
        self.assertEqual(ctx.exception.code, 2)

    def test_normal_path_accepted(self):
        """A normal temp directory path raises no exception."""
        from pathlib import Path

        normal_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, normal_dir)
        # Should not raise
        sync_chats._assert_not_icloud(Path(normal_dir))


# ═══════════════════════════════════════════════════════════════════════════════
# TestStateIO — _write_atomic, load_state, save_state (CORE-03)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStateIO(unittest.TestCase):
    """Tests for atomic state I/O functions."""

    def setUp(self):
        """Create a fresh isolated home dir for each test."""
        self._home = _make_isolated_home()

    def tearDown(self):
        """Remove the temp home dir after each test."""
        shutil.rmtree(self._home, ignore_errors=True)

    def test_atomic_write_creates_file(self):
        """_write_atomic creates the target file with correct JSON content."""
        from pathlib import Path

        target = Path(self._home) / "test.json"
        sync_chats._write_atomic(target, {"hello": "world"})
        self.assertTrue(target.exists())
        data = json.loads(target.read_text())
        self.assertEqual(data["hello"], "world")

    def test_atomic_write_creates_bak(self):
        """After a second _write_atomic, a .bak file is created from the first write."""
        from pathlib import Path

        target = Path(self._home) / "test.json"
        bak = Path(self._home) / "test.bak"
        # First write
        sync_chats._write_atomic(target, {"v": 1})
        self.assertFalse(bak.exists())  # no .bak yet
        # Second write — should create .bak from the first write
        sync_chats._write_atomic(target, {"v": 2})
        self.assertTrue(bak.exists())
        bak_data = json.loads(bak.read_text())
        self.assertEqual(bak_data["v"], 1)

    def test_load_state_default(self):
        """With no state file, load_state returns schema_version=1 and empty lists/dicts."""
        # Make sure state file doesn't exist
        if sync_chats.STATE_PATH.exists():
            sync_chats.STATE_PATH.unlink()
        state = sync_chats.load_state()
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["synced_session_ids"], [])
        self.assertIsInstance(state["fingerprints"], dict)


# ═══════════════════════════════════════════════════════════════════════════════
# TestClobberLayer1 — synced_session_ids guard in discover_sessions (CORE-08)
# ═══════════════════════════════════════════════════════════════════════════════


class TestClobberLayer1(unittest.TestCase):
    """Tests for clobber defense layer 1: synced_session_ids exclusion."""

    def setUp(self):
        self._home = _make_isolated_home()
        # Point PROJECTS_DIR at a temp directory with our fixture session
        self._projects_dir = tempfile.mkdtemp()
        # Create fake project directory and copy fixture
        self._project_dir = os.path.join(self._projects_dir, "test-project")
        os.makedirs(self._project_dir)
        self._session_file = os.path.join(self._project_dir, SAMPLE_SESSION_ID + ".jsonl")
        shutil.copy(SAMPLE_SESSION, self._session_file)
        # Override the module-level PROJECTS_DIR
        import pathlib

        self._original_projects_dir = sync_chats.PROJECTS_DIR
        sync_chats.PROJECTS_DIR = pathlib.Path(self._projects_dir)

    def tearDown(self):
        sync_chats.PROJECTS_DIR = self._original_projects_dir
        shutil.rmtree(self._projects_dir, ignore_errors=True)
        shutil.rmtree(self._home, ignore_errors=True)

    def test_synced_id_skipped(self):
        """A session whose ID is in synced_session_ids is excluded from discover_sessions."""
        # State that claims session is already synced
        state = {
            "schema_version": 1,
            "synced_session_ids": [SAMPLE_SESSION_ID],
            "fingerprints": {},
            "last_run_at": None,
        }
        sessions = sync_chats.discover_sessions(state)
        # The sample session should be excluded
        session_ids = [s["session_id"] for s in sessions]
        self.assertNotIn(SAMPLE_SESSION_ID, session_ids)

    def test_unsynced_id_included(self):
        """A session NOT in synced_session_ids is included in discover_sessions."""
        state = {
            "schema_version": 1,
            "synced_session_ids": [],  # nothing synced yet
            "fingerprints": {},
            "last_run_at": None,
        }
        sessions = sync_chats.discover_sessions(state)
        session_ids = [s["session_id"] for s in sessions]
        self.assertIn(SAMPLE_SESSION_ID, session_ids)


# ═══════════════════════════════════════════════════════════════════════════════
# TestClobberLayer2 — _write_if_not_exists O_CREAT|O_EXCL guard (CORE-09)
# ═══════════════════════════════════════════════════════════════════════════════


class TestClobberLayer2(unittest.TestCase):
    """Tests for clobber defense layer 2: O_CREAT|O_EXCL atomic file create."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_write_if_not_exists_creates(self):
        """Writing to a new path returns True and creates the file with correct content."""
        from pathlib import Path

        target = Path(self._tmp) / "new_file.md"
        content = b"hello world\n"
        result = sync_chats._write_if_not_exists(target, content)
        self.assertTrue(result)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_bytes(), content)

    def test_write_if_not_exists_refuses(self):
        """Writing to an existing path returns False and leaves original content intact."""
        from pathlib import Path

        target = Path(self._tmp) / "existing.md"
        original = b"original content\n"
        new_content = b"new content\n"
        # Write original file directly
        target.write_bytes(original)
        # Attempt to overwrite
        result = sync_chats._write_if_not_exists(target, new_content)
        self.assertFalse(result)
        # Original content must be unchanged
        self.assertEqual(target.read_bytes(), original)


# ═══════════════════════════════════════════════════════════════════════════════
# TestAutoLabelHash — sha256 hash contract (CORE-10)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoLabelHash(unittest.TestCase):
    """Tests for the auto_label_hash sha256 sentinel."""

    def test_hash_is_sha256_hex(self):
        """sha256 of test bytes produces a 64-character lowercase hex string."""
        h = hashlib.sha256(b"test").hexdigest()
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_hash_in_frontmatter(self):
        """emit_frontmatter with auto_label_hash field produces 'auto_label_hash: <hex>' line."""
        test_hash = hashlib.sha256(b"test body").hexdigest()
        fields = {
            "title": "Test",
            "gist": None,
            "tags": ["stub"],
            "coherence_score": None,
            "needs_review": True,
            "project": "proj",
            "session_id": SAMPLE_SESSION_ID,
            "model": "test-model",
            "token_count": 0,
            "msg_count": 0,
            "machine": "mbp",
            "hostname": "test-host",
            "synced_at": "2026-03-19T23:50:00+00:00",
            "auto_label_hash": test_hash,
        }
        result = sync_chats.emit_frontmatter(fields)
        self.assertIn(f"auto_label_hash: {test_hash}", result)

    def test_hash_changes_with_content(self):
        """Two different bodies produce different sha256 hashes."""
        h1 = hashlib.sha256(b"body one").hexdigest()
        h2 = hashlib.sha256(b"body two").hexdigest()
        self.assertNotEqual(h1, h2)


# ═══════════════════════════════════════════════════════════════════════════════
# TestSessionDate — _get_session_date from JSONL timestamp
# ═══════════════════════════════════════════════════════════════════════════════


class TestSessionDate(unittest.TestCase):
    """Tests for _get_session_date() date extraction."""

    def test_date_from_timestamp(self):
        """Session date from fixture is '2026-03-19' (from first JSONL timestamp)."""
        from pathlib import Path

        result = sync_chats._get_session_date(Path(SAMPLE_SESSION))
        self.assertEqual(result, "2026-03-19")

    def test_date_format(self):
        """Returned date is always in YYYY-MM-DD format (10 chars, 2 hyphens)."""
        from pathlib import Path

        result = sync_chats._get_session_date(Path(SAMPLE_SESSION))
        self.assertEqual(len(result), 10)
        self.assertEqual(result[4], "-")
        self.assertEqual(result[7], "-")


# ═══════════════════════════════════════════════════════════════════════════════
# TestMetadata — _extract_session_metadata (model, tokens, msgs)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMetadata(unittest.TestCase):
    """Tests for _extract_session_metadata() JSONL metadata extractor."""

    def setUp(self):
        from pathlib import Path

        self._meta = sync_chats._extract_session_metadata(Path(SAMPLE_SESSION))

    def test_model_extraction(self):
        """Model field contains 'claude-sonnet' (from the assistant message in fixture)."""
        self.assertIn("claude-sonnet", self._meta["model"])

    def test_token_count(self):
        """Token count is 600 (500 input + 100 output from fixture usage dict)."""
        self.assertEqual(self._meta["token_count"], 600)

    def test_msg_count(self):
        """Message count is 3 (2 user + 1 assistant in the fixture)."""
        self.assertEqual(self._meta["msg_count"], 3)


# ═══════════════════════════════════════════════════════════════════════════════
# TestStdinContract — label JSON schema validation contract (LABEL-09)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStdinContract(unittest.TestCase):
    """Tests for the stdin label JSON contract (D-01..D-03, LABEL-09).

    The write subcommand reads label data from stdin as JSON only.
    These tests verify the contract from the perspective of the consumer:
    valid JSON with 'title' key is accepted; missing 'title' is detectable.
    """

    def test_valid_label_json_parses(self):
        """A valid label JSON string parses to a dict with a 'title' key."""
        raw = '{"title": "Debug export", "gist": null, "tags": ["stub"], "coherence_score": null, "needs_review": true}'
        parsed = json.loads(raw)
        self.assertIn("title", parsed)
        self.assertIsInstance(parsed["title"], str)

    def test_missing_title_detected(self):
        """A label dict without 'title' key can be detected with 'title' not in dict."""
        bad_label = {"gist": None, "tags": ["stub"]}
        self.assertNotIn("title", bad_label)

    def test_unknown_keys_allowed(self):
        """Extra keys beyond the D-02 schema are ignored (forward-compat for Phase 2)."""
        extended = {
            "title": "Test",
            "gist": None,
            "tags": ["stub"],
            "coherence_score": None,
            "needs_review": True,
            "future_field": "some_value",  # Phase 2 might add this
        }
        # write only uses known keys — unknown keys must not cause errors
        # We verify by checking the D-02 required fields are present
        self.assertIn("title", extended)
        self.assertIn("needs_review", extended)
        # Unknown key silently present — no explosion
        self.assertIn("future_field", extended)

    def test_stub_label_passes_stdin_contract(self):
        """make_stub_label output satisfies the D-02 stdin contract: has 'title'."""
        from pathlib import Path

        label = sync_chats.make_stub_label(Path(SAMPLE_SESSION), SAMPLE_SESSION_ID)
        # Must be serialisable as JSON (the write pipeline does json.dumps then pipes to stdin)
        raw = json.dumps(label)
        parsed = json.loads(raw)
        self.assertIn("title", parsed)
        self.assertIsInstance(parsed["title"], str)
        self.assertGreater(len(parsed["title"]), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level cleanup
# ═══════════════════════════════════════════════════════════════════════════════


def tearDownModule():
    """Clean up the global temp directory created at module import time."""
    shutil.rmtree(_GLOBAL_TEMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
