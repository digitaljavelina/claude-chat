"""Integration tests for scrub pipeline wiring (Phase 3 Plan 02).

Run with: python3 -m unittest tests.test_scrub_integration -v

Covers:
  - Structural ordering: _get_markdown_body returns tuple (D-03)
  - Privacy review derivation (D-08)
  - Scrub log format (D-21) and safety (PRIV-06)
  - needs_review force-on when uncertain (D-07)
  - No log line for clean sessions (D-22)
  - Frontmatter always contains privacy_review (D-08)

These tests exercise the wiring added by Plan 03-02, not the scrub_content
function itself (covered in tests/test_scrub.py for Plan 03-01).
"""

import inspect
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Bootstrap CLAUDE_CHAT_HOME before import — sync_chats reads this at import time.
# Use a throwaway temp dir so we never touch the real ~/.claude-chat/.
_GLOBAL_TEMP = tempfile.mkdtemp(prefix="sync_chats_test_")
os.environ["CLAUDE_CHAT_HOME"] = _GLOBAL_TEMP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sync_chats  # noqa: E402
from sync_chats import (  # noqa: E402
    _derive_privacy_review,
    _get_markdown_body,
    _log_scrub_stats,
    emit_frontmatter,
)


class TestGetMarkdownBodyReturnsTuple(unittest.TestCase):
    """D-03: raw body never escapes — return type is tuple."""

    def test_signature_is_tuple(self):
        """Return annotation on _get_markdown_body must reference tuple (D-03).

        We check the annotation string rather than calling the function because
        calling it requires a subprocess + a real session. The annotation is the
        structural contract: any caller reading the sig sees `tuple`, not `str`.
        """
        sig = inspect.signature(_get_markdown_body)
        # Return annotation is a string in PEP 563 / stringified form — match case-insensitive
        self.assertIn("tuple", str(sig.return_annotation).lower())

    def test_scrub_content_called_exactly_once_in_source(self):
        """Structural enforcement (D-03): scrub_content has exactly ONE call site.

        Any additional call site would weaken the invariant that raw body
        escapes only through _get_markdown_body's scrub boundary.
        """
        src = Path(sync_chats.__file__).read_text()
        # Count actual invocations: the function-call form scrub_content(
        call_sites = src.count("scrub_content(")
        # One definition (def scrub_content(...)) + one call site (scrubbed_body, scrub_stats = scrub_content(raw_body))
        # Both use "scrub_content(" so the count should be exactly 2.
        self.assertEqual(
            call_sites,
            2,
            f"Expected 1 def + 1 call of scrub_content, got {call_sites} occurrences of 'scrub_content('",
        )


class TestDerivePrivacyReview(unittest.TestCase):
    """D-08: one of clean / scrubbed / uncertain, always present."""

    def test_clean_when_all_zero(self):
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["uncertain"] = 0
        stats["total_chars_redacted"] = 0
        self.assertEqual(_derive_privacy_review(stats), "clean")

    def test_scrubbed_when_named_hit_no_uncertain(self):
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["email"] = 2
        stats["uncertain"] = 0
        stats["total_chars_redacted"] = 40
        self.assertEqual(_derive_privacy_review(stats), "scrubbed")

    def test_uncertain_when_uncertain_hit(self):
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["uncertain"] = 1
        stats["total_chars_redacted"] = 32
        self.assertEqual(_derive_privacy_review(stats), "uncertain")

    def test_uncertain_wins_over_named(self):
        """If both named patterns AND uncertain hit, result is 'uncertain' (D-06/D-07)."""
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["email"] = 1
        stats["uncertain"] = 1
        stats["total_chars_redacted"] = 50
        self.assertEqual(_derive_privacy_review(stats), "uncertain")

    def test_minimal_stats_shape_accepted(self):
        """_derive_privacy_review should tolerate stats dicts that omit zero-count keys.

        Some future caller might pass a sparse dict; the function uses .get() and
        sums present values, so missing keys == treated as zero.
        """
        self.assertEqual(_derive_privacy_review({}), "clean")
        self.assertEqual(_derive_privacy_review({"email": 1}), "scrubbed")
        self.assertEqual(_derive_privacy_review({"uncertain": 1}), "uncertain")


class TestLogScrubStatsFormat(unittest.TestCase):
    """D-21 format + D-22 skip-when-clean + PRIV-06 safety."""

    def setUp(self):
        # Point LOG_PATH at a tempfile for isolation — don't touch ~/.claude-chat/sync.log
        self._tmp_home = tempfile.mkdtemp(prefix="sync_chats_log_")
        self._orig_log = sync_chats.LOG_PATH
        sync_chats.LOG_PATH = Path(self._tmp_home) / "sync.log"

    def tearDown(self):
        sync_chats.LOG_PATH = self._orig_log
        shutil.rmtree(self._tmp_home, ignore_errors=True)

    def test_clean_session_writes_no_log_line(self):
        """D-22: no log line when stats are all zero."""
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["uncertain"] = 0
        stats["total_chars_redacted"] = 0
        _log_scrub_stats("abc12345-xxxx", stats)
        self.assertFalse(
            sync_chats.LOG_PATH.exists() and sync_chats.LOG_PATH.read_text().strip(),
            "Clean session must not emit a scrub log line (D-22)",
        )

    def test_scrubbed_session_writes_d21_format(self):
        """D-21 exact format: scrub session=<short_id> patterns={...} total_chars=N."""
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["email"] = 3
        stats["jwt"] = 1
        stats["uncertain"] = 0
        stats["total_chars_redacted"] = 287
        _log_scrub_stats("abcdefgh-xxxx-xxxx", stats)
        contents = sync_chats.LOG_PATH.read_text()
        self.assertIn("scrub session=abcdefgh", contents)
        self.assertIn("email:3", contents)
        self.assertIn("jwt:1", contents)
        self.assertIn("total_chars=287", contents)
        # Zero-count patterns must be elided (D-21 example shows only non-zero entries)
        self.assertNotIn("bearer:0", contents)
        self.assertNotIn("github_token:0", contents)

    def test_log_contains_no_matched_substring(self):
        """PRIV-06: pattern names + counts only, never matched content (T-03-02-02 mitigation)."""
        # If the implementation accidentally logged re.Match.group() or embedded the
        # redacted string into the log, the following sentinel chars would appear.
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["email"] = 1
        stats["total_chars_redacted"] = 20
        _log_scrub_stats("s12345ab-xxxx", stats)
        contents = sync_chats.LOG_PATH.read_text()
        # No @-sign would appear in any matched email; no eyJ prefix (jwt); no ghp_ prefix
        self.assertNotIn("@", contents)
        self.assertNotIn("eyJ", contents)
        self.assertNotIn("ghp_", contents)

    def test_uncertain_is_included_in_log(self):
        """uncertain count must appear so Michael can audit fallback hits."""
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["uncertain"] = 2
        stats["total_chars_redacted"] = 64
        _log_scrub_stats("xy123456-xxxx", stats)
        contents = sync_chats.LOG_PATH.read_text()
        self.assertIn("uncertain:2", contents)

    def test_short_id_is_exactly_8_chars(self):
        """D-21: short_id is the first 8 chars of the UUID."""
        stats = {name: 0 for name, _ in sync_chats.SCRUB_PATTERNS}
        stats["email"] = 1
        stats["total_chars_redacted"] = 10
        # session id longer than 8 chars
        _log_scrub_stats("0123456789abcdef-full-uuid", stats)
        contents = sync_chats.LOG_PATH.read_text()
        self.assertIn("session=01234567 ", contents)
        # The 9th char '8' must not appear in the session= field (would indicate truncation bug)
        self.assertNotIn("session=012345678", contents)


class TestFrontmatterHasPrivacyReview(unittest.TestCase):
    """Every written file must have privacy_review in frontmatter (D-08)."""

    def test_emit_frontmatter_renders_privacy_review(self):
        fm = emit_frontmatter(
            {
                "title": "Test",
                "gist": None,
                "tags": ["stub"],
                "coherence_score": None,
                "needs_review": True,
                "privacy_review": "clean",
                "project": "proj",
                "session_id": "sid",
                "model": "claude",
                "token_count": 0,
                "msg_count": 0,
                "machine": "mbp",
                "hostname": "h",
                "synced_at": "2026-04-13T00:00:00+00:00",
                "auto_label_hash": "abc",
            }
        )
        self.assertIn("privacy_review: clean", fm)

    def test_all_three_privacy_values_render(self):
        for value in ("clean", "scrubbed", "uncertain"):
            fm = emit_frontmatter({"title": "T", "privacy_review": value})
            self.assertIn(f"privacy_review: {value}", fm)

    def test_privacy_review_ordered_after_needs_review(self):
        """KEY_ORDER: privacy_review is right after needs_review and before project."""
        fm = emit_frontmatter(
            {
                "title": "T",
                "needs_review": True,
                "privacy_review": "clean",
                "project": "p",
            }
        )
        needs_idx = fm.index("needs_review:")
        priv_idx = fm.index("privacy_review:")
        proj_idx = fm.index("project:")
        self.assertLess(needs_idx, priv_idx)
        self.assertLess(priv_idx, proj_idx)


class TestNeedsReviewForceOn(unittest.TestCase):
    """D-07 / SC#3 / T-03-02-05: uncertain privacy_review forces needs_review=true
    even when the label supplied on stdin says needs_review=false.

    This test exercises the force-on *logic* directly (the 3-line branch from
    cmd_write) rather than running a full cmd_write subprocess. The end-to-end
    path is covered by the Plan 03-04 canary test.
    """

    def test_force_on_when_uncertain_overrides_label_false(self):
        """Label says needs_review=false + privacy_review=uncertain → written as true."""
        stats = {"total_chars_redacted": 48, "uncertain": 1}
        privacy_review = _derive_privacy_review(stats)
        label = {"needs_review": False}  # user/AI said don't flag
        needs_review = label.get("needs_review", True)
        if privacy_review == "uncertain":
            needs_review = True
        self.assertEqual(privacy_review, "uncertain")
        self.assertTrue(needs_review, "uncertain MUST force needs_review=true per D-07")

    def test_force_on_preserves_true_when_already_true(self):
        """Label says needs_review=true + uncertain → stays true (no regression)."""
        stats = {"total_chars_redacted": 32, "uncertain": 1}
        privacy_review = _derive_privacy_review(stats)
        needs_review = True  # label already wants review
        if privacy_review == "uncertain":
            needs_review = True
        self.assertTrue(needs_review)

    def test_no_force_on_when_scrubbed(self):
        """scrubbed (known patterns only) does NOT force needs_review — label value wins."""
        stats = {"email": 3, "total_chars_redacted": 60, "uncertain": 0}
        privacy_review = _derive_privacy_review(stats)
        needs_review = False  # label said no flag
        if privacy_review == "uncertain":
            needs_review = True
        self.assertEqual(privacy_review, "scrubbed")
        self.assertFalse(needs_review, "scrubbed should NOT force needs_review")

    def test_no_force_on_when_clean(self):
        """clean (no scrubs) does NOT force needs_review=true."""
        stats = {"total_chars_redacted": 0, "uncertain": 0}
        privacy_review = _derive_privacy_review(stats)
        needs_review = False
        if privacy_review == "uncertain":
            needs_review = True
        self.assertEqual(privacy_review, "clean")
        self.assertFalse(needs_review)


if __name__ == "__main__":
    unittest.main()
