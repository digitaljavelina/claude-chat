# Phase 2: SKILL.md + AI Labeling - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-13
**Phase:** 02-skill-md-ai-labeling
**Areas discussed:** Prompt design, Edge case handling, Skill frontmatter & invocation

---

## Prompt Design

### Content strategy

| Option                  | Description                                                                                  | Selected |
| ----------------------- | -------------------------------------------------------------------------------------------- | -------- |
| First + last N messages | Feed the first ~5 and last ~5 user/assistant message pairs. Captures opening and resolution. | ✓        |
| Full session content    | Feed entire session. Most accurate but slow on huge sessions.                                |          |
| Truncated first N chars | Feed first ~10K characters. Simple but misses session endings.                               |          |

**User's choice:** First + last N messages
**Notes:** Recommended option. Keeps prompt bounded while capturing the arc of the conversation.

### Title style

| Option                  | Description                                                            | Selected |
| ----------------------- | ---------------------------------------------------------------------- | -------- |
| Verb-leading action     | e.g. "Debug RSS feed parsing in homelab service". Task summary style.  | ✓        |
| Topic-first noun phrase | e.g. "RSS feed parsing bug in homelab service". Subject heading style. |          |
| You decide              | Claude picks per session.                                              |          |

**User's choice:** Verb-leading action
**Notes:** Matches LABEL-03's "verb-leading where applicable" requirement.

### Few-shot examples

| Option                 | Description                                                                | Selected |
| ---------------------- | -------------------------------------------------------------------------- | -------- |
| 3-4 few-shot examples  | Include example sessions with ideal output. ~200 tokens, high consistency. | ✓        |
| Instructions only      | Rules without examples. Simpler but may drift.                             |          |
| Examples + style guide | Both. Most reliable but longest prompt.                                    |          |

**User's choice:** 3-4 few-shot examples
**Notes:** Good balance of consistency vs. prompt size for a personal tool.

### Output format

| Option                 | Description                                                              | Selected |
| ---------------------- | ------------------------------------------------------------------------ | -------- |
| JSON block in markdown | ```json fenced block. Easy regex extraction, resilient to preamble text. | ✓        |
| Raw JSON only          | Only JSON, no surrounding text. Simplest parse but fragile.              |          |
| Structured tool use    | Tool schema for label fields. Most robust but adds complexity.           |          |

**User's choice:** JSON block in markdown
**Notes:** Familiar pattern, reliable with Claude, easy to extract.

---

## Edge Case Handling

### Ultra-short session detection

| Option                             | Description                                                                | Selected |
| ---------------------------------- | -------------------------------------------------------------------------- | -------- |
| Character count < 500              | Count total chars across user messages. Matches LABEL-07 spec.             |          |
| User message count < 2             | Skip sessions with fewer than 2 user messages. Catches abandoned sessions. | ✓        |
| Combined: chars < 500 AND msgs < 2 | Only skip if both true. Most permissive.                                   |          |

**User's choice:** User message count < 2
**Notes:** User preferred message count over character count. Catches abandoned sessions where user typed one thing and never followed up.

### Low-signal detection

| Option             | Description                                                              | Selected |
| ------------------ | ------------------------------------------------------------------------ | -------- |
| User message ratio | If user messages < ~20% of total, tag low_signal. Python-side heuristic. |          |
| Let Claude decide  | Prompt instruction to tag low_signal if mostly tool output.              | ✓        |
| You decide         | Claude's discretion on method.                                           |          |

**User's choice:** Let Claude decide
**Notes:** Delegates nuanced judgment to Claude rather than a brittle ratio check.

### Multi-topic detection

| Option                      | Description                                                         | Selected |
| --------------------------- | ------------------------------------------------------------------- | -------- |
| Let Claude decide           | Prompt instruction to tag multi_topic if distinct unrelated topics. | ✓        |
| Heuristic: 3+ distinct tags | Auto-add multi_topic if tags span very different domains.           |          |

**User's choice:** Let Claude decide
**Notes:** Same reasoning as low-signal — Claude is better at detecting topic shifts than heuristics.

### Malformed JSON fallback

| Option                  | Description                                                                  | Selected |
| ----------------------- | ---------------------------------------------------------------------------- | -------- |
| Immediate stub fallback | One failed parse = use make_stub_label(). No retries. Fast.                  | ✓        |
| Retry once, then stub   | One retry with "please respond with valid JSON". Doubles latency on failure. |          |
| You decide              | Claude's discretion.                                                         |          |

**User's choice:** Immediate stub fallback
**Notes:** Keep runs fast and predictable. Stub gets needs_review: true for Obsidian review queue.

---

## Skill Frontmatter & Invocation

### Allowed tools

| Option              | Description                                                            | Selected |
| ------------------- | ---------------------------------------------------------------------- | -------- |
| Bash + Read only    | Bash for sync_chats.py calls, Read for JSONL content. Minimal surface. | ✓        |
| Bash + Read + Write | Also allow direct file writes. Likely unnecessary.                     |          |
| You decide          | Claude's discretion on minimal set.                                    |          |

**User's choice:** Bash + Read only
**Notes:** All vault writes go through sync_chats.py — no need for Write tool.

### Processing loop

| Option                    | Description                                                            | Selected |
| ------------------------- | ---------------------------------------------------------------------- | -------- |
| Sequential, one at a time | Scan → for each: read, label, write. Simple, matches success criteria. | ✓        |
| Batch prompt              | Multiple sessions per prompt. Faster but harder error handling.        |          |
| You decide                | Claude's discretion.                                                   |          |

**User's choice:** Sequential, one at a time
**Notes:** Matches ROADMAP success criterion #1: "processes each delta one at a time."

### Arguments

| Option                          | Description                                              | Selected |
| ------------------------------- | -------------------------------------------------------- | -------- |
| No arguments — always full scan | /sync-chats runs full pipeline every time. Simple.       | ✓        |
| Optional --label-only           | Re-label single session. Conflicts with clobber defense. |          |
| Optional --dry-run              | Preview without writing. Useful for testing.             |          |

**User's choice:** No arguments — always full scan
**Notes:** Re-labeling deferred to v2 (LABEL-V2-01). Dry-run deferred.

### Skill location

| Option                        | Description                                                        | Selected |
| ----------------------------- | ------------------------------------------------------------------ | -------- |
| ~/.claude/skills/sync-chats/  | Global skill, discoverable from any session. Matches LABEL-01.     | ✓        |
| Project-local .claude/skills/ | Scoped to this project only. Wrong — skill should work everywhere. |          |

**User's choice:** ~/.claude/skills/sync-chats/
**Notes:** Must be global since /sync-chats should work from any Claude Code session.

---

## Claude's Discretion

- Exact prompt wording and few-shot example content
- How to extract first+last N messages from JSONL
- JSON code block extraction regex
- Progress display during multi-session runs
- Exact N for first/last message pairs (5 is guidance)
- argument-hint text in SKILL.md frontmatter

## Deferred Ideas

- `--dry-run` flag for preview
- `--label-only <session_id>` for re-labeling (LABEL-V2-01)
- Configurable prompt template (LABEL-V2-02)
- Coherence score as a skip gate
- Batch prompting for faster labeling
