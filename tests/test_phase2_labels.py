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
import unittest

# ─── Bootstrap: add project root to sys.path so 'import sync_chats' works ─────
#
# sys.path is the list of directories Python searches when you do 'import X'.
# We insert the project root (one level above 'tests/') so that
# 'import sync_chats' finds sync_chats.py at the project root.
# This mirrors the pattern used in test_sync_chats.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync_chats  # noqa: E402

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

    Sentence count heuristic: count occurrences of '. ' (period + space) and
    add 1 for the final sentence. This is intentionally simple — it will
    miscount sentences with abbreviations, but is good enough for validation.
    """
    if not isinstance(gist, str):
        return False
    stripped = gist.strip()
    if not stripped:
        return False
    # Count sentence boundaries: '. ' separators, plus 1 for the last sentence
    sentence_count = stripped.count(". ") + 1
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

        Skips:
          - Non-user roles
          - Messages where content contains '<system-reminder>'
          - Messages where content is 5 or fewer characters (too short to be
            meaningful — mirrors the filter in extract_first_user_message)
        """
        count = 0
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message", obj)
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "")
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    text = " ".join(
                        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                    ).strip()
                else:
                    text = ""
                if "<system-reminder>" in text:
                    continue
                if len(text) > 5:
                    count += 1
        return count

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


if __name__ == "__main__":
    unittest.main()
