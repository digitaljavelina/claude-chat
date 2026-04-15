"""Golden-string unit tests for _format_summary (Phase 5 Plan 03, OBSERV-01).

Run with: pipx run pytest tests/test_phase5_summary.py -v

The D-23 canonical format is LOCKED — this test enforces the exact string
byte-for-byte. A failing assertion here means either the helper has drifted
or a new caller bypassed the helper (D-22 — _format_summary is the sole
producer of this line).

Python beginner notes:
  - Pure functions take input and return output without side effects. No
    tempdir / env overrides needed — just call and assertEqual.
  - We treat mempalace_reason == null (Python None) as absent so callers can
    safely set reason=None on the happy path.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync_chats  # noqa: E402


class TestFormatSummary(unittest.TestCase):
    def test_true_no_reason(self):
        run = {
            "synced": 3,
            "skipped": 1,
            "flagged_for_review": 2,
            "mempalace_mined": "true",
            "mempalace_reason": None,
        }
        expected = "Synced 3 new chats, 1 skipped (already-synced), 2 flagged for review, mempalace_mined: true"
        self.assertEqual(sync_chats._format_summary(run), expected)

    def test_skipped_with_reason(self):
        run = {
            "synced": 0,
            "skipped": 5,
            "flagged_for_review": 0,
            "mempalace_mined": "skipped",
            "mempalace_reason": "not run by hook (--once skips mine)",
        }
        expected = (
            "Synced 0 new chats, 5 skipped (already-synced), "
            "0 flagged for review, mempalace_mined: skipped "
            "(not run by hook (--once skips mine))"
        )
        self.assertEqual(sync_chats._format_summary(run), expected)

    def test_false_with_reason(self):
        run = {
            "synced": 1,
            "skipped": 0,
            "flagged_for_review": 1,
            "mempalace_mined": "false",
            "mempalace_reason": "timeout after 300s",
        }
        expected = (
            "Synced 1 new chats, 0 skipped (already-synced), "
            "1 flagged for review, mempalace_mined: false (timeout after 300s)"
        )
        self.assertEqual(sync_chats._format_summary(run), expected)

    def test_true_ignores_reason_if_present(self):
        run = {
            "synced": 0,
            "skipped": 0,
            "flagged_for_review": 0,
            "mempalace_mined": "true",
            "mempalace_reason": "leftover from prior run",
        }
        result = sync_chats._format_summary(run)
        self.assertTrue(
            result.endswith("mempalace_mined: true"),
            f"Expected result to end with 'mempalace_mined: true', got: {result!r}",
        )

    def test_missing_keys_default_to_zero_and_skipped(self):
        expected = "Synced 0 new chats, 0 skipped (already-synced), 0 flagged for review, mempalace_mined: skipped"
        self.assertEqual(sync_chats._format_summary({}), expected)

    def test_pure_function(self):
        run = {"synced": 1, "skipped": 2, "flagged_for_review": 0, "mempalace_mined": "true"}
        first = sync_chats._format_summary(run)
        second = sync_chats._format_summary(run)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
