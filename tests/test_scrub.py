"""Unit tests for scrub_content pure function (Phase 3 Plan 01).

Run with: python3 -m unittest tests.test_scrub -v
Or as part of the full suite: python3 -m unittest discover tests

Test strategy:
  - stdlib only (matches D-28 zero-deps invariant)
  - Every pattern in D-09 and D-11 has at least one positive test
  - Skip-list from D-10 has negative tests (private IPs pass through unchanged)
  - Stats dict shape is asserted once globally to catch accidental key drift
  - Ordering rules from D-Discretion are explicitly tested
    (jwt before uncertain; anthropic before openai)
"""

import os
import sys
import tempfile
import unittest

# Bootstrap CLAUDE_CHAT_HOME before import (same pattern as test_sync_chats.py).
# sync_chats.py evaluates CLAUDE_CHAT_HOME at module level, so we must set the
# env var BEFORE the first import or the module will capture the real home dir.
_GLOBAL_TEMP = tempfile.mkdtemp()
os.environ["CLAUDE_CHAT_HOME"] = _GLOBAL_TEMP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sync_chats  # noqa: E402,F401  (import for side-effect: registers module)
from sync_chats import scrub_content, _is_private_ip, SCRUB_PATTERNS  # noqa: E402


class TestScrubNamedPatterns(unittest.TestCase):
    """One test method per pattern in D-09 and D-11."""

    def test_email(self):
        text, stats = scrub_content("contact user@example.com please")
        self.assertIn("<REDACTED:email>", text)
        self.assertEqual(stats["email"], 1)
        self.assertNotIn("user@example.com", text)

    def test_jwt_before_uncertain(self):
        # JWT must win over uncertain fallback — D-Discretion ordering rule.
        text, stats = scrub_content("token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature_part")
        self.assertIn("<REDACTED:jwt>", text)
        self.assertEqual(stats["jwt"], 1)
        self.assertEqual(
            stats["uncertain"],
            0,
            "jwt must match before uncertain fallback (D-Discretion)",
        )

    def test_github_pat_all_six_variants(self):
        # D-09: gh[psuor]_... variants share one regex under name "github_token".
        for prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
            payload = "A" * 36
            text, stats = scrub_content(f"key={prefix}{payload}")
            self.assertIn(
                "<REDACTED:github_token>",
                text,
                f"failed for {prefix}",
            )
            self.assertNotIn(prefix + payload, text)
        # github_pat_ requires 82+ chars per D-09.
        long_payload = "B" * 82
        text, stats = scrub_content(f"key=github_pat_{long_payload}")
        self.assertIn("<REDACTED:github_token>", text)

    def test_aws_keys(self):
        for prefix in ("AKIA", "ASIA"):
            payload = "IOSFODNN7EXAMPLE"  # 16 chars, uppercase/digits
            text, stats = scrub_content(f"aws={prefix}{payload}")
            self.assertIn("<REDACTED:aws_key>", text)

    def test_bearer_and_basic_auth(self):
        text, stats = scrub_content("Authorization: Bearer abc123def456")
        self.assertIn("<REDACTED:bearer>", text)
        self.assertEqual(stats["bearer"], 1)

        text, stats = scrub_content("Authorization: Basic dXNlcjpwYXNzd29yZA==")
        self.assertIn("<REDACTED:basic_auth>", text)

    def test_slack_token(self):
        text, stats = scrub_content(
            "slack=xoxb-1234567890-1234567890-" + "a" * 24,
        )
        self.assertIn("<REDACTED:slack>", text)

    def test_stripe_live_and_test(self):
        for prefix in ("sk_live_", "sk_test_"):
            text, stats = scrub_content(f"key={prefix}{'a' * 24}")
            self.assertIn("<REDACTED:stripe>", text)

    def test_anthropic_before_openai(self):
        # sk-ant-... must not be captured by the openai pattern.
        text, stats = scrub_content(f"key=sk-ant-api-01-{'a' * 40}")
        self.assertIn("<REDACTED:anthropic>", text)
        self.assertEqual(stats["anthropic"], 1)
        self.assertEqual(
            stats["openai"],
            0,
            "sk-ant-... must not match openai pattern (D-Discretion)",
        )

    def test_openai_key(self):
        text, stats = scrub_content(f"key=sk-{'A' * 40}B")
        self.assertIn("<REDACTED:openai>", text)
        self.assertEqual(stats["openai"], 1)

    def test_us_phone_three_formats(self):
        for phone in ("(555) 123-4567", "555-123-4567", "555.123.4567"):
            text, stats = scrub_content(f"call {phone} today")
            self.assertIn(
                "<REDACTED:phone>",
                text,
                f"failed for {phone}",
            )


class TestScrubIPs(unittest.TestCase):
    """IP redaction with skip-list (D-10)."""

    def test_public_ipv4_redacted(self):
        text, stats = scrub_content("server at 8.8.8.8 responds")
        self.assertIn("<REDACTED:ipv4>", text)
        self.assertEqual(stats["ipv4"], 1)

    def test_private_ipv4_skipped(self):
        for ip in (
            "127.0.0.1",
            "10.0.0.1",
            "192.168.1.1",
            "172.16.0.1",
            "172.31.255.1",
            "169.254.1.1",
        ):
            text, stats = scrub_content(f"debug at {ip}")
            self.assertNotIn(
                "<REDACTED:ipv4>",
                text,
                f"private IP {ip} was wrongly redacted",
            )
            self.assertIn(
                ip,
                text,
                f"private IP {ip} should be preserved",
            )

    def test_172_edge_cases(self):
        # 172.15.x.x and 172.32.x.x are PUBLIC — should be redacted.
        text, stats = scrub_content("addr 172.15.0.1 here")
        self.assertIn("<REDACTED:ipv4>", text)
        text, stats = scrub_content("addr 172.32.0.1 here")
        self.assertIn("<REDACTED:ipv4>", text)

    def test_public_ipv6_redacted(self):
        text, stats = scrub_content("addr 2001:db8::1 here")
        self.assertIn("<REDACTED:ipv6>", text)

    def test_private_ipv6_skipped(self):
        for ip in ("::1", "fe80::1", "fe80::abcd:1234"):
            text, stats = scrub_content(f"debug at {ip}")
            self.assertNotIn(
                "<REDACTED:ipv6>",
                text,
                f"private IPv6 {ip} was wrongly redacted",
            )

    def test_is_private_ip_function(self):
        self.assertTrue(_is_private_ip("127.0.0.1"))
        self.assertTrue(_is_private_ip("10.99.99.99"))
        self.assertTrue(_is_private_ip("192.168.1.1"))
        self.assertTrue(_is_private_ip("172.16.0.1"))
        self.assertTrue(_is_private_ip("172.31.255.255"))
        self.assertFalse(_is_private_ip("172.15.0.1"))
        self.assertFalse(_is_private_ip("172.32.0.1"))
        self.assertTrue(_is_private_ip("::1"))
        self.assertTrue(_is_private_ip("fe80::1"))
        self.assertFalse(_is_private_ip("8.8.8.8"))


class TestScrubUncertain(unittest.TestCase):
    """Uncertain path (D-06, D-11)."""

    def test_bare_high_entropy_string_triggers_uncertain(self):
        # 32+ alphanumeric run not matching any named pattern.
        text, stats = scrub_content(
            "token: AbCdEfGhIjKlMnOpQrStUvWxYz123456",
        )
        self.assertIn("<REDACTED:uncertain>", text)
        self.assertEqual(stats["uncertain"], 1)

    def test_short_strings_do_not_trigger_uncertain(self):
        text, stats = scrub_content("hello world this is fine")
        self.assertEqual(stats["uncertain"], 0)
        self.assertNotIn("<REDACTED:uncertain>", text)

    def test_known_patterns_do_not_trigger_uncertain(self):
        # github_token matches first; uncertain must stay at 0.
        text, stats = scrub_content(f"key=ghp_{'A' * 36}")
        self.assertEqual(stats["github_token"], 1)
        self.assertEqual(stats["uncertain"], 0)


class TestScrubStatsShape(unittest.TestCase):
    """Verify stats dict shape is stable (D-21 log format depends on this)."""

    def test_empty_input_returns_full_stats_keys(self):
        text, stats = scrub_content("")
        expected_named = {name for name, _ in SCRUB_PATTERNS}
        for name in expected_named:
            self.assertIn(name, stats, f"missing stat key {name}")
            self.assertEqual(stats[name], 0)
        self.assertIn("uncertain", stats)
        self.assertIn("total_chars_redacted", stats)
        self.assertEqual(stats["total_chars_redacted"], 0)

    def test_total_chars_redacted_counts_original_length(self):
        # Redact one 36-char GitHub PAT → total_chars_redacted >= 40
        # ("ghp_" prefix + 36 payload chars).
        original = f"ghp_{'A' * 36}"
        text, stats = scrub_content(original)
        self.assertGreaterEqual(stats["total_chars_redacted"], 40)

    def test_multiple_hits_accumulate(self):
        text, stats = scrub_content("a@b.co c@d.co e@f.co")
        self.assertEqual(stats["email"], 3)


class TestScrubAllTogether(unittest.TestCase):
    """Cumulative test — one fixture with every pattern; all counts >= 1."""

    def test_every_pattern_hit_at_least_once(self):
        fixture = (
            "Email: a@b.co\n"
            "JWT: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig\n"
            "GitHub: ghp_" + "A" * 36 + "\n"
            "AWS: AKIAIOSFODNN7EXAMPLE\n"
            "Bearer: Bearer abc123\n"
            "Basic: Basic dXNlcjpwYXNz\n"
            "Slack: xoxb-1234567890-1234567890-" + "a" * 24 + "\n"
            "Stripe: sk_live_" + "a" * 24 + "\n"
            "Anthropic: sk-ant-" + "a" * 40 + "\n"
            "OpenAI: sk-" + "B" * 40 + "A\n"
            "IPv4: 8.8.8.8\n"
            "IPv6: 2001:db8::1\n"
            "Phone: (555) 123-4567\n"
        )
        text, stats = scrub_content(fixture)
        for name in (
            "email",
            "jwt",
            "github_token",
            "aws_key",
            "bearer",
            "basic_auth",
            "slack",
            "stripe",
            "anthropic",
            "openai",
            "ipv4",
            "ipv6",
            "phone",
        ):
            self.assertGreaterEqual(
                stats[name],
                1,
                f"{name} was not hit (got {stats[name]})",
            )


if __name__ == "__main__":
    unittest.main()
