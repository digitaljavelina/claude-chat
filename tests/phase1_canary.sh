#!/usr/bin/env bash
# phase1_canary.sh — End-to-end canary testing all 9 Phase 1 success criteria.
#
# Run from project root: bash tests/phase1_canary.sh
#
# Each criterion maps to a ROADMAP.md Phase 1 success criterion (1-9).
# The script uses an isolated temp environment: CLAUDE_CHAT_HOME and
# CLAUDE_PROJECTS_DIR both point at mktemp directories so real user state
# is never touched. A mock claude-chat.py stub satisfies the export bridge
# without requiring real sessions in ~/.claude/projects/.
#
# Exit 0 if all 9 criteria pass, exit 1 if any fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYNC="$PROJECT_DIR/sync_chats.py"
CLI="$PROJECT_DIR/claude-chat.py"

# ── Isolated temp environment ─────────────────────────────────────────────────
TMPDIR_BASE=$(mktemp -d)
trap 'rm -rf "$TMPDIR_BASE"' EXIT

export CLAUDE_CHAT_HOME="$TMPDIR_BASE/home"
VAULT="$TMPDIR_BASE/vault"
FAKE_PROJECTS="$TMPDIR_BASE/projects"
export CLAUDE_PROJECTS_DIR="$FAKE_PROJECTS"

# Set up directory structure
mkdir -p "$VAULT/Chats" "$FAKE_PROJECTS/test-project" "$CLAUDE_CHAT_HOME"

# Copy the test fixture into the fake projects directory
# The session UUID matches the fixture's sessionId field
SESSION_UUID="541112ec-a07c-4d87-80f7-2310b98fd7ea"
cp "$SCRIPT_DIR/fixtures/sample_session.jsonl" \
   "$FAKE_PROJECTS/test-project/${SESSION_UUID}.jsonl"

# ── Mock claude-chat.py ───────────────────────────────────────────────────────
# sync_chats.py calls claude-chat.py export <uuid> --format md --stdout to get
# the markdown body. In canary tests we point SYNC_CHATS_CLAUDE_CLI at this mock
# so the canary never needs a real session in ~/.claude/projects/.
MOCK_CLI="$TMPDIR_BASE/mock-claude-chat.py"
cat > "$MOCK_CLI" << 'PYEOF'
#!/usr/bin/env python3
"""Mock claude-chat.py for canary testing.
Handles: export <uuid> --format md --stdout  (returns canned markdown)
         export --help                        (shows --stdout flag in help)
"""
import sys

args = sys.argv[1:]

# Handle: export --help  (Criterion 7 checks for --stdout in help output)
if "export" in args and "--help" in args:
    print("usage: claude-chat.py export [-h] [--format FORMAT] [--stdout] session_id")
    print("")
    print("positional arguments:")
    print("  session_id    UUID of the session to export")
    print("")
    print("optional arguments:")
    print("  -h, --help    show this help message and exit")
    print("  --format      output format: md, html, txt, latex (default: md)")
    print("  --stdout      write output to stdout instead of a file")
    sys.exit(0)

# Handle: export <uuid> --format md --stdout  (Criterion 3 - write pipeline)
if "export" in args and "--stdout" in args:
    # Find the session UUID (positional arg after 'export')
    export_idx = args.index("export")
    # UUID is the first positional arg after 'export' (skip flags)
    uuid = None
    for arg in args[export_idx + 1:]:
        if not arg.startswith("--"):
            uuid = arg
            break
    print(f"# Claude Code Session: {uuid or 'unknown'}")
    print("")
    print("**Date:** 2026-03-19")
    print("")
    print("## User")
    print("")
    print("Debug the export markdown function and fix the output formatting")
    print("")
    print("## Assistant")
    print("")
    print("I will look at the export function.")
    sys.exit(0)

# Fallback: unknown command
print(f"Mock: unhandled args: {args}", file=sys.stderr)
sys.exit(1)
PYEOF
chmod +x "$MOCK_CLI"
export SYNC_CHATS_CLAUDE_CLI="$MOCK_CLI"

# ── Test helpers ──────────────────────────────────────────────────────────────
PASS=0
FAIL=0

pass() {
    echo "  PASS: $1"
    PASS=$((PASS + 1))
}

fail() {
    echo "  FAIL: $1"
    FAIL=$((FAIL + 1))
}

# ── Criterion 1: init --label (CORE-05) ───────────────────────────────────────
echo ""
echo "Criterion 1: init --label creates config.json with machine_label"
python3 "$SYNC" init --label mbp --vault "$VAULT"
if [ -f "$CLAUDE_CHAT_HOME/config.json" ] && grep -q "machine_label" "$CLAUDE_CHAT_HOME/config.json"; then
    pass "init creates config.json with machine_label"
else
    fail "init did not create config.json correctly"
fi

# ── Criterion 2: scan returns JSON with session UUID (CORE-01) ────────────────
echo ""
echo "Criterion 2: scan returns JSON containing session UUID"
OUTPUT=$(python3 "$SYNC" scan)
if echo "$OUTPUT" | grep -q "$SESSION_UUID" && echo "$OUTPUT" | python3 -m json.tool > /dev/null 2>&1; then
    pass "scan returns valid JSON containing session UUID"
else
    fail "scan output invalid or missing session UUID"
    echo "    scan output: $OUTPUT"
fi

# ── Criterion 3: write creates vault file with frontmatter (CORE-02) ─────────
echo ""
echo "Criterion 3: write creates vault file with YAML frontmatter"
LABEL='{"title":"Debug the export markdown function","gist":null,"tags":["stub"],"coherence_score":null,"needs_review":true}'
echo "$LABEL" | python3 "$SYNC" write "$SESSION_UUID"
VAULT_FILE=$(find "$VAULT/Chats" -name "mbp--*" -type f 2>/dev/null | head -1)
if [ -n "$VAULT_FILE" ] && grep -q "title:" "$VAULT_FILE" && grep -q "auto_label_hash:" "$VAULT_FILE"; then
    pass "write creates vault file with frontmatter (title + auto_label_hash present)"
else
    fail "write did not create vault file correctly"
    echo "    vault file: ${VAULT_FILE:-<not found>}"
    if [ -n "$VAULT_FILE" ]; then
        echo "    first 5 lines:"
        head -5 "$VAULT_FILE"
    fi
fi

# ── Criterion 4: second write is skipped (CORE-07 idempotency) ───────────────
echo ""
echo "Criterion 4: second write on same session is skipped"
OUTPUT2=$(echo "$LABEL" | python3 "$SYNC" write "$SESSION_UUID" 2>&1)
if echo "$OUTPUT2" | grep -q "already_synced"; then
    pass "second write skipped (already_synced)"
else
    fail "second write was not skipped"
    echo "    output: $OUTPUT2"
fi

# ── Criterion 5: clobber defense holds after state deletion (CORE-08/CORE-09) ─
echo ""
echo "Criterion 5: clobber defense holds after state.json deletion"
rm -f "$CLAUDE_CHAT_HOME/state.json"
COUNT_BEFORE=$(find "$VAULT/Chats" -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
OUTPUT3=$(echo "$LABEL" | python3 "$SYNC" write "$SESSION_UUID" 2>&1)
COUNT_AFTER=$(find "$VAULT/Chats" -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$COUNT_BEFORE" = "$COUNT_AFTER" ] && echo "$OUTPUT3" | grep -qi "already_synced\|reconcil"; then
    pass "clobber defense holds after state deletion (no new file, reconcile message)"
else
    fail "clobber defense failed after state deletion"
    echo "    files before: $COUNT_BEFORE  after: $COUNT_AFTER"
    echo "    output: $OUTPUT3"
fi

# ── Criterion 6: iCloud assertion fires on iCloud path (CORE-04) ─────────────
echo ""
echo "Criterion 6: iCloud assertion fires when CLAUDE_CHAT_HOME is in iCloud path"
ICLOUD_PATH="$TMPDIR_BASE/Library/Mobile Documents/fake-claude-chat"
mkdir -p "$ICLOUD_PATH"
OUTPUT4=$(CLAUDE_CHAT_HOME="$ICLOUD_PATH" python3 "$SYNC" scan 2>&1 || true)
if echo "$OUTPUT4" | grep -qi "icloud\|mobile documents"; then
    pass "iCloud assertion fires with iCloud path"
else
    fail "iCloud assertion did not fire"
    echo "    output: $OUTPUT4"
fi

# ── Criterion 7: export --stdout flag registered in claude-chat.py (CORE-11) ─
echo ""
echo "Criterion 7: claude-chat.py export --help shows --stdout flag"
if python3 "$CLI" export --help 2>&1 | grep -q "\-\-stdout"; then
    pass "export --stdout flag registered in claude-chat.py"
else
    fail "export --stdout flag missing from claude-chat.py export --help"
fi

# ── Criterion 8: status command shows machine label (CORE-13) ─────────────────
echo ""
echo "Criterion 8: status shows machine label and sync info"
OUTPUT5=$(python3 "$SYNC" status 2>&1)
if echo "$OUTPUT5" | grep -q "Machine:" && echo "$OUTPUT5" | grep -q "mbp"; then
    pass "status shows machine label (Machine: mbp)"
else
    fail "status output incomplete"
    echo "    output: $OUTPUT5"
fi

# ── Criterion 9: protect audit documented (CORE-12) ──────────────────────────
echo ""
echo "Criterion 9: protect audit document exists and records Phase 3 ownership"
AUDIT_FILE="$PROJECT_DIR/.planning/phases/01-scanner-state-stub-label-write-pipeline/01-PROTECT-AUDIT.md"
if [ -f "$AUDIT_FILE" ] && grep -q "cmd_protect" "$AUDIT_FILE" && grep -q "Phase 3" "$AUDIT_FILE"; then
    pass "protect audit document exists and records cmd_protect finding + Phase 3 handoff"
else
    fail "protect audit document missing or incomplete"
    echo "    looked for: $AUDIT_FILE"
    if [ -f "$AUDIT_FILE" ]; then
        echo "    file exists but missing required content"
    fi
fi

# ── Results ───────────────────────────────────────────────────────────────────
echo ""
echo "====================================="
echo "Results: $PASS passed, $FAIL failed"
echo "====================================="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
