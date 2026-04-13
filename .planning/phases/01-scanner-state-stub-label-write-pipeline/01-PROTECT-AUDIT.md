# Protect Command Audit (CORE-12)

**Date:** 2026-04-13
**Auditor:** Phase 01 executor
**Requirement:** CORE-12 — Audit `cmd_protect()` before any Phase 3 scrub work begins

---

## 1. Audit Finding

`cmd_protect()` in `claude-chat.py` does **not** scrub session content. It does NOT read any
`.jsonl` files, does NOT touch message bodies, and does NOT perform any PII removal of any kind.

The function does exactly one thing: it reads `~/.claude/settings.json` and sets
`cleanupPeriodDays = 99999`, preventing Claude Code's built-in auto-deletion timer from
purging old sessions. It writes the file atomically (write to `.tmp`, then `os.replace`),
then exits.

The `protect` command is purely a retention guard — not a content scrubber.

---

## 2. File Path and Line Number

- **File:** `claude-chat.py`
- **Function:** `cmd_protect()`
- **Line:** 821 (line 821 in source)

Relevant excerpt (lines 821–848):

```python
def cmd_protect(args):
    """Prevent Claude Code from auto-deleting old sessions."""
    # Reads ~/.claude/settings.json, sets cleanupPeriodDays = 99999,
    # writes atomically. Does NOT read any .jsonl files. Does NOT scrub content.
    settings["cleanupPeriodDays"] = 99999
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
    tmp.replace(SETTINGS_FILE)
```

The full function touches only `~/.claude/settings.json`. Zero JSONL reads, zero content
modifications.

---

## 3. Phase 3 Ownership

Scrubbing is deferred to **Phase 3** (PRIV track). Phase 3 will:

1. Add a `protect --scrub-content` stdin/stdout mode to `claude-chat.py` (~30 lines,
   backwards-compatible — existing `protect` invocations are unaffected)
2. Implement generic credential/token/email/IP scrub patterns
3. Add the PRIV-04 canary test that verifies the `scrub → label → write` ordering is enforced

Phase 3 inherits CORE-12 as its entry task (the audit result documented here is the
handoff artifact).

---

## 4. Phase 1 Caveat

Because no scrubbing happens in Phase 1, vault files land in raw form (unscrubbed session
content). This is acceptable under the following conditions:

- Phase 1 is a **single-machine, manually-invoked pipeline** — every file write is gated
  behind an explicit `sync_chats.py write <uuid>` call. The user is in the loop for every
  file that enters the vault.
- The **SessionEnd hook** (Phase 5) is NOT installed until after Phase 3 lands scrubbing.
  Fully-automated sync of unscrubbed content into iCloud never occurs in Phase 1.
- The risk window is: user runs `sync_chats.py write <uuid>` and the session contains
  credentials or PII. The user must decide whether the session is safe to sync before
  running the command. This is acceptable for a development/testing phase.

Once Phase 3 scrubbing lands, this caveat is resolved and Phase 5 (SessionEnd hook) can be
installed safely.
