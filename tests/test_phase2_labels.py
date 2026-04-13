"""Unit tests for Phase 2 AI label validation, JSON extraction, and stub fallback.

Run with: python3 -m pytest tests/test_phase2_labels.py -v

These tests cover:
  - Label shape validators (title length, tag format, coherence score, gist)
  - JSON extraction from Claude's fenced code block responses
  - Stub fallback shape via make_stub_label()
  - Fixture integrity (user message counts)

Python beginner note: each test class groups related tests. setUp/tearDown are
standard unittest hooks that run before/after each individual test method.
pytest can run unittest.TestCase classes natively.
"""

import json
import os
import re
import sys
import tempfile
import unittest

# ─── Bootstrap: add project root to sys.path so 'import sync_chats' works ─────
#
# sys.path is the list of directories Python searches when you do 'import X'.
# We insert the project root (one level above 'tests/') so that
# 'import sync_chats' finds sync_chats.py at the project root.
# This mirrors the pattern used in test_sync_chats.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync_chats  # noqa: E402

# ─── Module-level helpers for ultra-short skip logic ─────────────────────────
#
# These functions replicate the user message counting logic from SKILL.md Step 2a.
# They are module-level (not methods) so they can be tested in isolation and, if
# needed, imported by future plans.
#
# Python beginner note: a module-level function is defined at the top level of a
# .py file, outside any class. That makes it callable as count_user_messages(path)
# rather than instance.count_user_messages(path).


def count_user_messages(jsonl_path: str) -> int:
    """Count meaningful user messages in a JSONL file.

    Handles two content formats Claude Code uses:
      - Plain string: {"role": "user", "content": "some text"}
      - Block list:   {"role": "user", "content": [{"type": "text", "text": "some text"}]}

    Skips:
      - Messages whose content contains '<system-reminder>' (injected context, not real user input)
      - Messages whose text is 5 characters or fewer (too short to be meaningful)
      - Lines that are not valid JSON

    Args:
        jsonl_path: Absolute or relative path to a .jsonl session file.

    Returns:
        int: Number of meaningful user messages in the file. Returns 0 for an
             empty file or a file with no qualifying user messages.
    """
    count = 0
    # 'errors=replace' means garbled bytes in the file become ? instead of crashing.
    # This mirrors the SKILL.md Bash one-liner's 'errors=replace' flag.
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # Skip malformed lines — mirrors SKILL.md's 'except Exception: continue'
                    continue
                # JSONL lines may be wrapped: {"message": {...}} or be the message directly
                msg = obj.get("message", obj)
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "")
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    # Block-list format: join text from all text-type blocks
                    text = " ".join(
                        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                    ).strip()
                else:
                    text = ""
                # Skip system-reminder injections and trivially short content
                if "<system-reminder>" in text:
                    continue
                if len(text) > 5:
                    count += 1
    except (OSError, IOError):
        # File not found or unreadable — return 0 rather than crashing
        return 0
    return count


def should_skip_session(jsonl_path: str) -> bool:
    """Return True if a session should be skipped due to too few user messages.

    Per D-05: sessions with fewer than 2 user messages are ultra-short and
    skipped entirely (no vault file written). This mirrors the skip condition
    in SKILL.md Step 2a: "if count < 2, skip".

    Args:
        jsonl_path: Absolute or relative path to a .jsonl session file.

    Returns:
        bool: True if fewer than 2 meaningful user messages were found (skip).
              False if 2 or more were found (process normally).
    """
    return count_user_messages(jsonl_path) < 2


# ─── Fixture paths ────────────────────────────────────────────────────────────
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SHORT_SESSION = os.path.join(FIXTURE_DIR, "short_session.jsonl")
SHORT_SESSION_ID = "aaaaaaaa-0000-0000-0000-000000000001"
MULTI_TURN_SESSION = os.path.join(FIXTURE_DIR, "multi_turn_session.jsonl")


# ─── Validators ───────────────────────────────────────────────────────────────
#
# These helpers validate the shape of labels produced by Claude or make_stub_label().
# They are used both by tests and could be imported by future plans.


def validate_title(title: str) -> bool:
    """Return True if title is a non-empty string with at most 10 words.

    Per D-02 / LABEL-03: titles are verb-leading action phrases, max 10 words.
    A "word" is defined as any whitespace-delimited token.
    """
    if not isinstance(title, str):
        return False
    stripped = title.strip()
    if not stripped:
        return False
    return len(stripped.split()) <= 10


def validate_tags(tags: list) -> bool:
    """Return True if tags is a list of 3-5 kebab-case strings.

    Per LABEL-05: each tag must be lowercase, digits allowed, hyphens between
    words, no spaces, no uppercase, no special characters except hyphens.

    Regex: ^[a-z0-9]+(-[a-z0-9]+)*$
      - starts with one or more lowercase letters/digits
      - optionally followed by groups of (hyphen + lowercase letters/digits)
      - hyphens must be between word segments, not at start or end
    """
    if not isinstance(tags, list):
        return False
    if not (3 <= len(tags) <= 5):
        return False
    pattern = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
    return all(isinstance(t, str) and pattern.match(t) for t in tags)


def validate_coherence_score(score) -> bool:
    """Return True if score is an integer in the range 1-5 (inclusive).

    Per D-13 / LABEL-06: coherence_score must be an int, 1 (scattered) to 5
    (single clear topic with resolution). Note: bool is a subclass of int in
    Python, so we explicitly reject booleans.
    """
    if isinstance(score, bool):
        return False
    if not isinstance(score, int):
        return False
    return 1 <= score <= 5


def validate_gist(gist: str) -> bool:
    """Return True if gist is a non-empty string consisting of 1-3 sentences.

    Per LABEL-04: gist is 2-3 sentences in past tense. We accept 1-3 for
    flexibility (stub labels may have shorter gists in edge cases).

    Sentence count heuristic: count sentence-ending punctuation marks (., !,
    or ?) that are followed by either a space or the end of the string. This
    correctly handles terminal sentences that end without a trailing space, and
    handles !, ? endings. It will still miscount abbreviations inside sentences,
    but is good enough for validation.
    """
    if not isinstance(gist, str):
        return False
    stripped = gist.strip()
    if not stripped:
        return False
    # Count sentence-ending punctuation followed by a space or end-of-string
    sentence_count = len(re.findall(r"[.!?](?:\s|$)", stripped))
    # Fall back to at-least-1 if no punctuation found
    if sentence_count == 0:
        sentence_count = 1
    return 1 <= sentence_count <= 3


# ─── JSON extraction helper ───────────────────────────────────────────────────


def extract_label_json(response_text: str):
    """Extract and parse the first ```json fenced code block from a response string.

    Returns a parsed dict if found and valid, or None on any failure.

    This function mirrors the extraction logic described in SKILL.md Step 2d.
    Claude is instructed to emit its label inside a ```json block, which makes
    extraction simple and reliable with a single regex.

    Args:
        response_text: The full text of Claude's response (may include
                       surrounding prose, thinking text, etc.)

    Returns:
        dict | None: Parsed label dict, or None if no block found or JSON is invalid.

    Python beginner note: re.DOTALL makes '.' match newlines too, so the .*?
    inside the block matches multi-line JSON. The '?' makes it non-greedy
    (matches as little as possible), so it stops at the first closing ```.
    """
    match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if not match:
        return None
    json_text = match.group(1).strip()
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# TestLabelValidation — validators for title, tags, coherence score, gist
# ═══════════════════════════════════════════════════════════════════════════════


class TestLabelValidation(unittest.TestCase):
    """Tests for label field validators.

    Each test method name describes what it validates. Tests cover both
    passing (valid input) and failing (invalid input) cases.
    """

    # ── validate_title ────────────────────────────────────────────────────────

    def test_validate_title_length_passes(self):
        """Title with exactly 10 words passes."""
        title = "Debug the export markdown function and fix output"  # 9 words
        self.assertTrue(validate_title(title))

    def test_validate_title_ten_words_passes(self):
        """Title with exactly 10 words passes."""
        title = "Set up Python virtual environment for the Django web project"  # 10 words
        self.assertTrue(validate_title(title))

    def test_validate_title_too_long_fails(self):
        """Title with more than 10 words fails."""
        title = "This is a title that is definitely way too long and should fail validation"
        self.assertFalse(validate_title(title))

    def test_validate_title_not_empty_passes(self):
        """Non-empty title passes."""
        self.assertTrue(validate_title("Fix bug"))

    def test_validate_title_empty_string_fails(self):
        """Empty string title fails."""
        self.assertFalse(validate_title(""))

    def test_validate_title_whitespace_only_fails(self):
        """Whitespace-only title fails."""
        self.assertFalse(validate_title("   "))

    def test_validate_title_non_string_fails(self):
        """Non-string title fails."""
        self.assertFalse(validate_title(None))
        self.assertFalse(validate_title(42))

    # ── validate_tags ─────────────────────────────────────────────────────────

    def test_validate_tags_format_passes(self):
        """Valid 3-tag list of kebab-case strings passes."""
        self.assertTrue(validate_tags(["python", "debugging", "flask"]))

    def test_validate_tags_five_tags_passes(self):
        """Valid 5-tag list passes."""
        self.assertTrue(validate_tags(["python", "flask", "session-management", "web", "debugging"]))

    def test_validate_tags_with_numbers_passes(self):
        """Tags with embedded numbers pass."""
        self.assertTrue(validate_tags(["python3", "flask2", "web-app"]))

    def test_validate_tags_too_few_fails(self):
        """Fewer than 3 tags fails."""
        self.assertFalse(validate_tags(["python", "debug"]))

    def test_validate_tags_too_many_fails(self):
        """More than 5 tags fails."""
        self.assertFalse(validate_tags(["a", "b", "c", "d", "e", "f"]))

    def test_validate_tags_uppercase_fails(self):
        """Tag with uppercase letter fails."""
        self.assertFalse(validate_tags(["Python", "debugging", "flask"]))

    def test_validate_tags_spaces_fail(self):
        """Tag with spaces fails (must use hyphens)."""
        self.assertFalse(validate_tags(["python debugging", "flask", "web"]))

    def test_validate_tags_special_chars_fail(self):
        """Tag with special characters other than hyphens fails."""
        self.assertFalse(validate_tags(["python_debug", "flask", "web"]))

    def test_validate_tags_leading_hyphen_fails(self):
        """Tag with leading hyphen fails."""
        self.assertFalse(validate_tags(["-python", "flask", "web"]))

    def test_validate_tags_trailing_hyphen_fails(self):
        """Tag with trailing hyphen fails."""
        self.assertFalse(validate_tags(["python-", "flask", "web"]))

    def test_validate_tags_not_list_fails(self):
        """Non-list tags fails."""
        self.assertFalse(validate_tags("python,debugging,flask"))

    # ── validate_coherence_score ──────────────────────────────────────────────

    def test_validate_coherence_score_1_passes(self):
        """Score of 1 passes."""
        self.assertTrue(validate_coherence_score(1))

    def test_validate_coherence_score_5_passes(self):
        """Score of 5 passes."""
        self.assertTrue(validate_coherence_score(5))

    def test_validate_coherence_score_3_passes(self):
        """Score of 3 passes."""
        self.assertTrue(validate_coherence_score(3))

    def test_validate_coherence_score_0_fails(self):
        """Score of 0 fails (out of range)."""
        self.assertFalse(validate_coherence_score(0))

    def test_validate_coherence_score_6_fails(self):
        """Score of 6 fails (out of range)."""
        self.assertFalse(validate_coherence_score(6))

    def test_validate_coherence_score_none_fails(self):
        """None fails (not an int)."""
        self.assertFalse(validate_coherence_score(None))

    def test_validate_coherence_score_string_fails(self):
        """String "3" fails (must be actual int, not string)."""
        self.assertFalse(validate_coherence_score("3"))

    def test_validate_coherence_score_float_fails(self):
        """Float 3.0 fails (must be int)."""
        self.assertFalse(validate_coherence_score(3.0))

    # ── validate_gist ─────────────────────────────────────────────────────────

    def test_validate_gist_one_sentence_passes(self):
        """Single sentence gist passes."""
        self.assertTrue(validate_gist("The user debugged a Flask session issue."))

    def test_validate_gist_two_sentences_passes(self):
        """Two-sentence gist passes."""
        self.assertTrue(
            validate_gist("The user debugged a Flask session issue. The fix was to use a stable SECRET_KEY.")
        )

    def test_validate_gist_three_sentences_passes(self):
        """Three-sentence gist passes."""
        gist = "The user reported a KeyError in Flask sessions. We traced it to a rotating SECRET_KEY. The fix was loading the key from an environment variable."
        self.assertTrue(validate_gist(gist))

    def test_validate_gist_empty_string_fails(self):
        """Empty string fails."""
        self.assertFalse(validate_gist(""))

    def test_validate_gist_none_fails(self):
        """None fails."""
        self.assertFalse(validate_gist(None))

    def test_validate_gist_non_string_fails(self):
        """Non-string gist fails."""
        self.assertFalse(validate_gist(42))


# ═══════════════════════════════════════════════════════════════════════════════
# TestExtractLabelJson — JSON extraction from Claude response text
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractLabelJson(unittest.TestCase):
    """Tests for extract_label_json() — parsing ```json blocks from response text."""

    def test_extract_label_json_valid(self):
        """Response with a valid ```json block returns parsed dict."""
        response = """
I analyzed the session. Here is the label:

```json
{
  "title": "Debug Flask session KeyError issue",
  "gist": "The user traced a Flask KeyError to a rotating SECRET_KEY. The fix was to load the key from an environment variable.",
  "tags": ["flask", "debugging", "python"],
  "coherence_score": 5,
  "needs_review": false
}
```

That should work for this session.
"""
        result = extract_label_json(response)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Debug Flask session KeyError issue")
        self.assertEqual(result["coherence_score"], 5)
        self.assertIn("flask", result["tags"])
        self.assertFalse(result["needs_review"])

    def test_extract_label_json_missing(self):
        """Response with no ```json block returns None."""
        response = "I looked at the session but could not generate a label."
        result = extract_label_json(response)
        self.assertIsNone(result)

    def test_extract_label_json_malformed(self):
        """Response with invalid JSON in ```json block returns None."""
        response = """
```json
{title: "Missing quotes around key", coherence_score: 5}
```
"""
        result = extract_label_json(response)
        self.assertIsNone(result)

    def test_extract_label_json_with_surrounding_prose(self):
        """Extracts JSON even when surrounded by unrelated prose."""
        response = 'Some thinking text\n\n```json\n{"title": "Test", "tags": ["a"]}\n```\n\nMore text.'
        result = extract_label_json(response)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Test")

    def test_extract_label_json_empty_block_returns_none(self):
        """An empty ```json block returns None."""
        response = "```json\n\n```"
        result = extract_label_json(response)
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TestStubFallback — make_stub_label() shape and content
# ═══════════════════════════════════════════════════════════════════════════════


class TestStubFallback(unittest.TestCase):
    """Tests for make_stub_label() from sync_chats.

    The stub label is the Phase 1 fallback used when Claude's label response is
    unparseable (D-08). We verify its shape matches the label contract so that
    SKILL.md's fallback path produces a valid label for sync_chats.py write.
    """

    def setUp(self):
        """Set CLAUDE_CHAT_HOME to a temp dir so make_stub_label doesn't need
        a real ~/.claude-chat directory to exist."""
        import pathlib
        import tempfile

        self._temp_home = tempfile.mkdtemp()
        # Initialize a minimal state so make_stub_label can run
        os.environ["CLAUDE_CHAT_HOME"] = self._temp_home
        sync_chats.CLAUDE_CHAT_HOME = pathlib.Path(self._temp_home)
        sync_chats.CONFIG_PATH = pathlib.Path(self._temp_home) / "config.json"
        sync_chats.STATE_PATH = pathlib.Path(self._temp_home) / "state.json"
        sync_chats.LOG_PATH = pathlib.Path(self._temp_home) / "sync.log"

    def tearDown(self):
        """Clean up temp dir."""
        import shutil

        shutil.rmtree(self._temp_home, ignore_errors=True)

    def test_stub_fallback_shape(self):
        """make_stub_label() returns dict with all required keys."""
        import pathlib

        label = sync_chats.make_stub_label(pathlib.Path(SHORT_SESSION), SHORT_SESSION_ID)
        self.assertIsInstance(label, dict)
        required_keys = {"title", "gist", "tags", "coherence_score", "needs_review"}
        self.assertEqual(required_keys, set(label.keys()))

    def test_stub_needs_review_is_true(self):
        """Stub label has needs_review = True (flags for Obsidian review queue)."""
        import pathlib

        label = sync_chats.make_stub_label(pathlib.Path(SHORT_SESSION), SHORT_SESSION_ID)
        self.assertTrue(label["needs_review"])

    def test_stub_tags_contain_stub(self):
        """Stub label tags contain 'stub' marker."""
        import pathlib

        label = sync_chats.make_stub_label(pathlib.Path(SHORT_SESSION), SHORT_SESSION_ID)
        self.assertIn("stub", label["tags"])

    def test_stub_title_is_non_empty_string(self):
        """Stub label title is a non-empty string."""
        import pathlib

        label = sync_chats.make_stub_label(pathlib.Path(SHORT_SESSION), SHORT_SESSION_ID)
        self.assertIsInstance(label["title"], str)
        self.assertTrue(label["title"].strip())

    def test_stub_gist_and_score_are_none(self):
        """Stub label intentionally has gist=None and coherence_score=None.

        Stubs are produced only when AI labeling fails (D-08). They are flagged
        with needs_review=True for manual follow-up. gist and coherence_score
        are left None and will fail the full content validators — this is by design.
        """
        import pathlib

        label = sync_chats.make_stub_label(pathlib.Path(SHORT_SESSION), SHORT_SESSION_ID)
        self.assertIsNone(label["gist"])
        self.assertIsNone(label["coherence_score"])
        # Confirm they fail the content validators (expected for stubs)
        self.assertFalse(validate_gist(label["gist"]))
        self.assertFalse(validate_coherence_score(label["coherence_score"]))


# ═══════════════════════════════════════════════════════════════════════════════
# TestEdgeCases — count_user_messages() and should_skip_session() edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases(unittest.TestCase):
    """Tests for the module-level count_user_messages() and should_skip_session().

    These tests verify LABEL-07 / D-05: sessions with fewer than 2 user messages
    are skipped entirely. They cover boundary cases (0, 1, 2 messages), both
    content formats (plain string and block-list), system-reminder filtering,
    and graceful handling of empty files.

    Python beginner note: tempfile.NamedTemporaryFile creates a real file on disk
    inside the OS temp directory. We use delete=False so we can close it and
    re-open it by name for testing. The tearDown method cleans up all temp files
    created during the test, even if a test assertion fails mid-way.
    """

    def setUp(self):
        """Track temp files created during each test for cleanup."""
        # self._temp_files is a list of paths to delete in tearDown.
        # setUp runs before each individual test method.
        self._temp_files = []

    def tearDown(self):
        """Delete all temp files created during this test."""
        # tearDown runs after each individual test method, even if the test fails.
        for path in self._temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _make_temp_jsonl(self, lines: list) -> str:
        """Write a list of JSONL strings to a temp file and return its path.

        Args:
            lines: List of already-serialized JSON strings (one per line).
                   Pass an empty list for an empty file.

        Returns:
            str: Absolute path to the temp file.
        """
        # suffix='.jsonl' is cosmetic — it does not affect file behaviour.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for line in lines:
                f.write(line + "\n")
            path = f.name
        self._temp_files.append(path)
        return path

    def _user_msg(self, text: str) -> str:
        """Serialize a plain-string user message as a JSONL line."""
        return json.dumps({"message": {"role": "user", "content": text}})

    def _user_block_msg(self, text: str) -> str:
        """Serialize a block-list user message as a JSONL line."""
        return json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": text}]}})

    def _assistant_msg(self, text: str) -> str:
        """Serialize an assistant message as a JSONL line (should not be counted)."""
        return json.dumps({"message": {"role": "assistant", "content": text}})

    # ── count_user_messages — fixture files ───────────────────────────────────

    def test_count_short_session(self):
        """short_session.jsonl has exactly 1 user message."""
        count = count_user_messages(SHORT_SESSION)
        self.assertEqual(count, 1, f"Expected 1 user message in short_session.jsonl, got {count}")

    def test_count_multi_turn(self):
        """multi_turn_session.jsonl has >= 6 user messages."""
        count = count_user_messages(MULTI_TURN_SESSION)
        self.assertGreaterEqual(count, 6, f"Expected >= 6 user messages in multi_turn_session.jsonl, got {count}")

    # ── count_user_messages — empty file ─────────────────────────────────────

    def test_count_empty_file(self):
        """An empty file returns 0."""
        path = self._make_temp_jsonl([])
        self.assertEqual(count_user_messages(path), 0)

    # ── count_user_messages — system-reminder filtering ───────────────────────

    def test_count_skips_system_reminder(self):
        """A user message whose content contains '<system-reminder>' is not counted.

        These are Claude Code context injections, not real user input.
        """
        path = self._make_temp_jsonl(
            [
                self._user_msg("<system-reminder>You are Claude Code.</system-reminder>"),
            ]
        )
        self.assertEqual(count_user_messages(path), 0)

    # ── count_user_messages — block-list content format ───────────────────────

    def test_count_block_list_format(self):
        """A user message in block-list format (list of typed blocks) is counted."""
        path = self._make_temp_jsonl(
            [
                self._user_block_msg("Hello world"),
            ]
        )
        self.assertEqual(count_user_messages(path), 1)

    # ── should_skip_session — boundary cases ──────────────────────────────────

    def test_should_skip_0_messages(self):
        """Empty file (0 user messages) should be skipped."""
        path = self._make_temp_jsonl([])
        self.assertTrue(should_skip_session(path))

    def test_should_skip_1_message(self):
        """short_session.jsonl (1 user message) should be skipped."""
        self.assertTrue(should_skip_session(SHORT_SESSION))

    def test_should_not_skip_2_messages(self):
        """A session with exactly 2 user messages should NOT be skipped.

        D-05 threshold: skip if count < 2, so 2 is the first passing value.
        """
        path = self._make_temp_jsonl(
            [
                self._user_msg("First real question here"),
                self._assistant_msg("Here is the answer."),
                self._user_msg("Follow-up question here"),
            ]
        )
        self.assertFalse(should_skip_session(path))

    def test_should_not_skip_multi_turn(self):
        """multi_turn_session.jsonl (6+ user messages) should NOT be skipped."""
        self.assertFalse(should_skip_session(MULTI_TURN_SESSION))


# ═══════════════════════════════════════════════════════════════════════════════
# TestFixtures — verify fixture files have the right message counts
# ═══════════════════════════════════════════════════════════════════════════════


class TestFixtures(unittest.TestCase):
    """Tests to verify the integrity of test fixture JSONL files.

    These tests catch accidental changes to the fixture files that would
    invalidate test assumptions (e.g. short_session must have exactly 1 user
    message for the ultra-short skip logic to be testable).
    """

    def _count_user_messages(self, jsonl_path: str) -> int:
        """Count user messages in a JSONL file, handling both content formats.

        Delegates to the module-level count_user_messages() so there is only
        one implementation to maintain. The module-level version also handles
        OSError/IOError gracefully (returns 0 rather than crashing the test).
        """
        # Delegate to the shared module-level function so there is only one
        # implementation to maintain.
        return count_user_messages(jsonl_path)

    def test_short_session_fixture_has_one_user_message(self):
        """short_session.jsonl has exactly 1 user message.

        Used for ultra-short skip testing (D-05: skip if user messages < 2).
        """
        count = self._count_user_messages(SHORT_SESSION)
        self.assertEqual(count, 1, f"Expected 1 user message, got {count}")

    def test_multi_turn_fixture_has_six_or_more_user_messages(self):
        """multi_turn_session.jsonl has >= 6 user messages.

        Used for first/last message extraction testing (D-01).
        """
        count = self._count_user_messages(MULTI_TURN_SESSION)
        self.assertGreaterEqual(count, 6, f"Expected >= 6 user messages, got {count}")

    def test_fixtures_exist(self):
        """Both fixture files exist at expected paths."""
        self.assertTrue(os.path.isfile(SHORT_SESSION), f"Missing: {SHORT_SESSION}")
        self.assertTrue(os.path.isfile(MULTI_TURN_SESSION), f"Missing: {MULTI_TURN_SESSION}")

    def test_multi_turn_has_both_content_formats(self):
        """multi_turn_session.jsonl contains both plain string and block-list content.

        This ensures test coverage for both content formats that Claude Code uses.
        """
        has_string_content = False
        has_list_content = False
        with open(MULTI_TURN_SESSION, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message", obj)
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    has_string_content = True
                elif isinstance(content, list):
                    has_list_content = True
        self.assertTrue(has_string_content, "multi_turn_session.jsonl missing plain string content")
        self.assertTrue(has_list_content, "multi_turn_session.jsonl missing block-list content")


# ═══════════════════════════════════════════════════════════════════════════════
# TestFewShotExamples — validate that few-shot examples in SKILL.md pass validators
# ═══════════════════════════════════════════════════════════════════════════════


class TestFewShotExamples(unittest.TestCase):
    """Tests that the few-shot JSON examples embedded in SKILL.md are structurally valid.

    Why this matters: SKILL.md contains 4 few-shot examples that Claude sees before
    labeling a real session. If an example has a bad title (>10 words), invalid tags
    (not kebab-case), or an out-of-range coherence score, it trains Claude to produce
    similarly broken output. These tests catch that at CI time.

    Python beginner note: pathlib.Path.home() returns the user's home directory as
    a Path object (e.g., /Users/michaelhenry). The / operator on Path objects joins
    path segments, so Path.home() / '.claude/skills/sync-chats/SKILL.md' produces
    the full path to the skill file.
    """

    SKILL_PATH = __import__("pathlib").Path.home() / ".claude/skills/sync-chats/SKILL.md"

    def _load_skill_content(self) -> str:
        """Read SKILL.md and return its text content."""
        self.assertTrue(
            self.SKILL_PATH.exists(),
            f"SKILL.md not found at {self.SKILL_PATH} — is sync-chats skill installed?",
        )
        return self.SKILL_PATH.read_text(encoding="utf-8")

    def _extract_json_examples(self, content: str) -> list:
        """Extract and parse all ```json code blocks from a string.

        Returns a list of dicts for blocks that parse as valid JSON objects.
        Blocks that fail to parse are silently skipped (they are tested
        separately by TestExtractLabelJson).

        re.DOTALL makes '.' match newlines so multi-line JSON blocks are captured.
        re.findall returns a list of all non-overlapping matches.
        """
        raw_blocks = re.findall(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        examples = []
        for block in raw_blocks:
            try:
                parsed = json.loads(block.strip())
                # Only include objects that have the label keys we care about
                if isinstance(parsed, dict) and "title" in parsed:
                    examples.append(parsed)
            except json.JSONDecodeError:
                pass
        return examples

    def test_skill_md_has_at_least_four_examples(self):
        """SKILL.md contains at least 4 parseable JSON label examples."""
        content = self._load_skill_content()
        examples = self._extract_json_examples(content)
        self.assertGreaterEqual(
            len(examples),
            4,
            f"Expected at least 4 JSON label examples in SKILL.md, found {len(examples)}. "
            "Check that all 4 few-shot examples have valid JSON.",
        )

    def test_all_examples_have_valid_title(self):
        """Every few-shot example in SKILL.md has a valid title (non-empty, <=10 words)."""
        content = self._load_skill_content()
        examples = self._extract_json_examples(content)
        self.assertGreaterEqual(len(examples), 4)
        for i, example in enumerate(examples):
            with self.subTest(example_index=i, title=example.get("title")):
                self.assertIn("title", example, f"Example {i} missing 'title' key")
                self.assertTrue(
                    validate_title(example["title"]),
                    f"Example {i} title failed validation: {example['title']!r} "
                    f"({len(example['title'].split())} words, max is 10)",
                )

    def test_all_examples_have_valid_tags(self):
        """Every few-shot example in SKILL.md has valid tags (3-5 kebab-case strings)."""
        content = self._load_skill_content()
        examples = self._extract_json_examples(content)
        self.assertGreaterEqual(len(examples), 4)
        for i, example in enumerate(examples):
            with self.subTest(example_index=i, tags=example.get("tags")):
                self.assertIn("tags", example, f"Example {i} missing 'tags' key")
                self.assertTrue(
                    validate_tags(example["tags"]),
                    f"Example {i} tags failed validation: {example['tags']!r} "
                    "(must be 3-5 kebab-case strings matching ^[a-z0-9]+(-[a-z0-9]+)*$)",
                )

    def test_all_examples_have_valid_coherence_score(self):
        """Every few-shot example in SKILL.md has a valid coherence_score (int 1-5)."""
        content = self._load_skill_content()
        examples = self._extract_json_examples(content)
        self.assertGreaterEqual(len(examples), 4)
        for i, example in enumerate(examples):
            with self.subTest(example_index=i, score=example.get("coherence_score")):
                self.assertIn("coherence_score", example, f"Example {i} missing 'coherence_score' key")
                self.assertTrue(
                    validate_coherence_score(example["coherence_score"]),
                    f"Example {i} coherence_score failed validation: {example['coherence_score']!r} (must be int 1-5)",
                )

    def test_all_examples_have_valid_gist(self):
        """Every few-shot example in SKILL.md has a valid gist (non-empty, 1-3 sentences)."""
        content = self._load_skill_content()
        examples = self._extract_json_examples(content)
        self.assertGreaterEqual(len(examples), 4)
        for i, example in enumerate(examples):
            with self.subTest(example_index=i):
                self.assertIn("gist", example, f"Example {i} missing 'gist' key")
                self.assertTrue(
                    validate_gist(example["gist"]),
                    f"Example {i} gist failed validation: {example['gist']!r}",
                )

    def test_all_examples_have_needs_review_key(self):
        """Every few-shot example in SKILL.md has a 'needs_review' key."""
        content = self._load_skill_content()
        examples = self._extract_json_examples(content)
        self.assertGreaterEqual(len(examples), 4)
        for i, example in enumerate(examples):
            with self.subTest(example_index=i):
                self.assertIn(
                    "needs_review",
                    example,
                    f"Example {i} missing 'needs_review' key",
                )

    def test_low_signal_tag_in_skill(self):
        """SKILL.md contains the string 'low-signal' (edge-case tag per D-06)."""
        content = self._load_skill_content()
        self.assertIn(
            "low-signal",
            content,
            "SKILL.md must contain 'low-signal' (kebab-case) for D-06 edge-case tag instruction. "
            "Check the tags rule section in Step 2c.",
        )

    def test_multi_topic_tag_in_skill(self):
        """SKILL.md contains the string 'multi-topic' (edge-case tag per D-07)."""
        content = self._load_skill_content()
        self.assertIn(
            "multi-topic",
            content,
            "SKILL.md must contain 'multi-topic' (kebab-case) for D-07 edge-case tag instruction. "
            "Check the tags rule section in Step 2c.",
        )


if __name__ == "__main__":
    unittest.main()
