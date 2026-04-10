# Technology Stack — `/sync-chats` Skill Milestone

**Project:** claude-chat (subsequent milestone)
**Researched:** 2026-04-10
**Scope:** NEW surface area only — Claude Code skill + launchd scheduler + Obsidian writer + MemPalace feeder + local state. The existing `claude-chat.py` Python stdlib-only CLI is LOCKED and not re-researched.
**Overall confidence:** HIGH (direct evidence from installed MemPalace plugin, official Anthropic skills docs, Apple launchd docs)

---

## CRITICAL FINDING (read first)

**Slash commands / user-invocable skills do NOT work in `claude -p` headless mode.** The Anthropic docs explicitly state: _"User-invoked skills like `/commit` and built-in commands are only available in interactive mode. In `-p` mode, describe the task you want to accomplish instead."_ ([source](https://code.claude.com/docs/en/headless))

**Implication for roadmap:** The original plan in PROJECT.md — "launchd LaunchAgent invoking `claude -p '/sync-chats'`" — **does not work as written**. The LaunchAgent must invoke `claude -p` with a natural-language prompt that describes the sync task, OR (much better) the LaunchAgent must invoke a plain Python/bash wrapper script that does the sync directly without going through a Claude session for the mechanical work, and only calls `claude -p` when it needs AI summarization for a specific session.

The recommended architecture (expanded under question 1 below): build the skill as a **thin orchestrator** that is invoked interactively (`/sync-chats` from within a Claude Code session, either by Michael when he's already chatting or by the LaunchAgent spawning a short-lived headless Claude session with a prompt like _"Run the sync-chats workflow"_). The skill's `SKILL.md` contains the playbook; the playbook shells out to `claude-chat.py` for mechanical work and uses the current Claude context for summarization.

This is a **material change** to the milestone plan and should be surfaced to Michael during roadmap review before Phase 1 starts.

---

## 1. Claude Code Skill Authoring — Structure & Invocation

### Recommendation: SKILL.md at `~/.claude/skills/sync-chats/SKILL.md`, task-style skill

**Directory layout** (official Anthropic pattern, verified from both the docs and from real skills in Michael's `~/.claude/skills/` like `obsidian-markdown` and `mempalace`):

```
~/.claude/skills/sync-chats/
├── SKILL.md              # REQUIRED — playbook + frontmatter
├── scripts/
│   ├── sync.py           # The actual sync engine (Python stdlib only)
│   ├── write_note.py     # Obsidian frontmatter + body writer
│   └── state.py          # State file reader/writer
├── references/
│   ├── FRONTMATTER.md    # Obsidian frontmatter schema (progressive disclosure)
│   └── LAUNCHD.md        # Reference plist template + install instructions
└── templates/
    └── note.md.tmpl      # Obsidian note template
```

**SKILL.md frontmatter (exact schema for 2026):**

```yaml
---
name: sync-chats
description: Sync new Claude Code sessions into the Obsidian vault with AI-generated titles, PII scrubbed, and one summary memory per chat into MemPalace. Use when the user asks to sync chats, export recent sessions, update their chat archive, or when running the scheduled sync. Also use when they mention catching up on conversations, updating the vault from Claude Code, or running sync-chats.
disable-model-invocation: true
allowed-tools: Bash(python3 *), Bash(~/.claude-chat/* *), Read, Write, Glob
argument-hint: "[--dry-run] [--since DATE] [--set-label NAME]"
---
```

**Field-by-field rationale (from [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)):**

| Field                               | Value                     | Why                                                                                                                                                                                 |
| ----------------------------------- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                              | `sync-chats`              | Becomes the `/sync-chats` slash command. Must be lowercase + hyphens, ≤ 64 chars.                                                                                                   |
| `description`                       | Pushy, front-loaded       | First 250 chars are what Claude sees in the always-loaded skill catalog. Front-load the triggering keywords.                                                                        |
| `disable-model-invocation: true`    | Yes                       | This is a task with side effects (writes files, feeds MemPalace). Michael should be the only one triggering it — Claude should not run it "helpfully" mid-conversation.             |
| `allowed-tools`                     | Space-separated whitelist | Pre-approves the bash commands the skill needs so there are no per-use permission prompts (matters for headless LaunchAgent invocation). Use prefix-match syntax `Bash(python3 *)`. |
| `argument-hint`                     | Shown in autocomplete     | Helps Michael remember flags.                                                                                                                                                       |
| (NOT using `user-invocable: false`) | —                         | Leave it default-true so Michael can type `/sync-chats` in an interactive session.                                                                                                  |
| (NOT using `context: fork`)         | —                         | The skill needs access to the current Claude session's ability to summarize; forking would lose that.                                                                               |

**Progressive disclosure pattern** (official Anthropic guidance — keep `SKILL.md` under 500 lines):

- Level 1 (always in context): `name` + `description` in frontmatter — ~100 words
- Level 2 (loaded on invoke): `SKILL.md` body — the playbook, under 500 lines
- Level 3 (loaded on demand): `references/FRONTMATTER.md`, `references/LAUNCHD.md`, `templates/note.md.tmpl`

**Invocation paths (three modes):**

1. **Interactive (primary):** Michael types `/sync-chats` in a running Claude Code session. This is the happy path — Claude has its tools, can read the playbook, can summarize each session in-context, and can call the MemPalace MCP tools directly.
2. **Headless from launchd (secondary):** `claude -p "Run the sync-chats workflow"` — but note the critical caveat above: **this will NOT match the `/sync-chats` slash command** because user-invocable skills are disabled in `-p` mode. Claude will instead discover the skill through its description (auto-invocation). To make this reliable, the `description` must be pushy enough that a prompt like "Run the sync-chats workflow" causes Claude to auto-load the skill.
   - Alternative: drop `disable-model-invocation: true` and rely on description-matching in headless mode. But then Claude may trigger it accidentally in interactive sessions — trade-off.
   - **Better alternative:** LaunchAgent invokes a plain `python3 ~/.claude/skills/sync-chats/scripts/sync.py --headless` wrapper that does NOT go through Claude Code at all. The wrapper does the mechanical sync, and for summarization it falls back to a simpler heuristic (e.g., first user message + last assistant message as "gist") OR invokes `claude -p` with an explicit natural-language prompt per-session. This is more robust, cheaper, and sleep-safe.
3. **Manual catch-up:** `/sync-chats` inside any Claude Code session — identical to path 1.

**What NOT to do:**

- ❌ Don't use `claude -p "/sync-chats"` — slash commands don't work in headless mode (per Anthropic docs).
- ❌ Don't rely on `context: fork` — a forked agent can't use the parent session's summarization context for free; you'd be paying for a fresh model call anyway.
- ❌ Don't omit `disable-model-invocation: true` in the interactive-first design — Claude would auto-trigger it mid-conversation and write to the vault uninvited.
- ❌ Don't put the mechanical sync logic in `SKILL.md` as bash blocks — `SKILL.md` is a prompt, not a script. Put the logic in `scripts/sync.py` and have `SKILL.md` tell Claude to run it.

**Confidence: HIGH** — directly verified against the official Anthropic skills docs ([code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)) and the [anthropics/skills GitHub repo](https://github.com/anthropics/skills).

**Sources:**

- [Claude Code Skills (official)](https://code.claude.com/docs/en/skills)
- [Headless mode limitations](https://code.claude.com/docs/en/headless)
- [anthropics/skills on GitHub](https://github.com/anthropics/skills)
- [Agent Skills spec](https://agentskills.io)

---

## 2. launchd LaunchAgent — Sleep-Safe Hourly Scheduling

### Recommendation: `StartInterval: 3600` + `RunAtLoad: true` (NO `StartCalendarInterval`)

**Plist template** — save to `~/Library/LaunchAgents/com.michaelhenry.sync-chats.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.michaelhenry.sync-chats</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>/Users/michaelhenry/.claude/skills/sync-chats/scripts/sync.py --headless</string>
    </array>

    <key>StartInterval</key>
    <integer>3600</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/michaelhenry/.claude-chat/sync.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/michaelhenry/.claude-chat/sync.err.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>/Users/michaelhenry</string>
    </dict>

    <key>WorkingDirectory</key>
    <string>/Users/michaelhenry</string>

    <key>ProcessType</key>
    <string>Background</string>

    <key>LowPriorityIO</key>
    <true/>

    <key>Nice</key>
    <integer>10</integer>
</dict>
</plist>
```

**Why `StartInterval: 3600` + `RunAtLoad: true` (and NOT `StartCalendarInterval`):**

From Apple's `launchd.plist(5)` man page and verified in the Apple Developer Forums ([thread 23361](https://developer.apple.com/forums/thread/23361), [thread 52369](https://developer.apple.com/forums/thread/52369)):

- **`StartInterval`** causes the job to run every N seconds. If the machine is asleep when an interval elapses, launchd **coalesces missed intervals into a single run on wake**. For a lid-open laptop that sleeps frequently, this is exactly the right behavior: one run per wake-up that catches up everything since the last sync.
- **`RunAtLoad: true`** fires the job once when the LaunchAgent is loaded (login, reboot, `launchctl load`). This ensures a sync happens immediately on boot without waiting an hour.
- **`StartCalendarInterval`** (hourly at `:00`) is actively worse for a sleeping laptop: if the machine is asleep at `:00`, the job runs once on wake, but if multiple `:00` firings are missed (e.g., machine asleep for 3 hours), they still coalesce into one run — so it's no better than `StartInterval`, AND it adds wall-clock-coupling that you don't need. Stick with `StartInterval`.
- **Idempotency backs this up:** because the sync reads a local cursor, running "once on wake after 3 missed intervals" processes all deltas in a single pass. The schedule is a hint, not a contract.

**`ProgramArguments` invocation choice — why `bash -lc`:**

- `bash -lc` runs a login shell, which loads `~/.zshrc`/`~/.bash_profile` for PATH setup. Without this, `python3`, `claude`, and `mempalace` may not be found because launchd's default PATH is minimal (`/usr/bin:/bin:/usr/sbin:/sbin`).
- **Cleaner alternative:** set `EnvironmentVariables > PATH` explicitly (as shown above) and invoke the script directly without `bash -lc`. More deterministic, fewer surprises. Recommended for production.

**`StandardOutPath` / `StandardErrorPath`:**

- Always redirect — otherwise stdout/stderr go to `/dev/null` and you can't debug. Point them at `~/.claude-chat/sync.log` (local, NOT iCloud).

**`ProcessType: Background` + `LowPriorityIO` + `Nice: 10`:**

- Tells macOS this is a background task so it gets deprioritized under thermal/power pressure, which is ideal for a laptop.

**`WorkingDirectory`:**

- Set explicitly. launchd's default cwd is `/`, which causes relative-path bugs.

**What NOT to do:**

- ❌ Don't use `KeepAlive: true` — that's for daemons that should always be running, not periodic tasks. It will respawn your sync continuously.
- ❌ Don't use `cron` on macOS — Apple has deprecated `cron` in favor of launchd since 10.4, and `cron` doesn't handle sleep/wake at all.
- ❌ Don't rely on `StartCalendarInterval` with `Minute: 0` expecting "exactly on the hour" — sleep/wake breaks that assumption anyway.
- ❌ Don't omit `EnvironmentVariables > PATH` — the #1 cause of "works in terminal, fails in launchd" bugs.
- ❌ Don't log to an iCloud path — iCloud file replacement can race with appending writes.

**Install/reload commands** (include these in the skill's install doc):

```bash
# Load (start watching)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.michaelhenry.sync-chats.plist

# Unload
launchctl bootout gui/$(id -u)/com.michaelhenry.sync-chats

# Force-run now (for testing)
launchctl kickstart -k gui/$(id -u)/com.michaelhenry.sync-chats

# Check status
launchctl print gui/$(id -u)/com.michaelhenry.sync-chats
```

Note: `launchctl load/unload` is deprecated in favor of `bootstrap/bootout` since macOS 10.11.

**macOS 15 Sequoia note:** There is a known Sequoia wake-from-sleep issue ([perez987/macOS-15-sequoia-sleep-issue](https://github.com/perez987/macOS-15-sequoia-sleep-issue)) where spurious wake events can happen. This doesn't affect correctness of `StartInterval` (it coalesces anyway) but may cause more runs than expected. Not a blocker.

**Confidence: HIGH** — behavior of `StartInterval` on sleep is documented in Apple's `launchd.plist(5)` man page and consistently confirmed across multiple Apple Developer Forum threads over the last 10+ years.

**Sources:**

- [launchd.info tutorial (authoritative third-party reference)](https://www.launchd.info/)
- [Apple Developer Forums: StartInterval and sleep](https://developer.apple.com/forums/thread/23361)
- [Apple Developer Forums: Jobs scheduled at midnight](https://developer.apple.com/forums/thread/52369)
- [Alvin Alexander: launchd plist examples](https://alvinalexander.com/mac-os-x/launchd-plist-examples-startinterval-startcalendarinterval/)
- [Kill The Yak: launchd guide](https://killtheyak.com/schedule-jobs-launchd/)

---

## 3. Obsidian Frontmatter Conventions

### Recommendation: ISO dates, YAML tag array, explicit `created`/`synced_at` fields

**Frontmatter schema for synced chat notes:**

```yaml
---
title: "Debugging the RSS polling loop"
aliases:
  - "rss-debug-2026-04-10"
tags:
  - chat
  - machine/mbp
  - project/digital-javelina
  - lang/python
gist: |
  Traced intermittent RSS failures to a timezone mismatch in the
  polling cursor. Fixed by normalizing to UTC before comparison.
  Added a regression test.
machine: mbp
hostname: michaels-mbp.local
project: digital-javelina
session_id: 0d57e32d-f2ec-4ddc-b4a1-3c8b171eade3
model: claude-opus-4-6
token_count: 18432
msg_count: 47
created: 2026-04-09
synced_at: 2026-04-10T08:42:15
needs_review: true
source: claude-code
---
```

**Field-by-field rationale:**

| Field                     | Format                                                           | Why                                                                                                                                                                                                                                                                                                                   |
| ------------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `title`                   | Quoted string                                                    | Obsidian uses this for display in some themes; quotes prevent YAML parsing bugs on titles with colons.                                                                                                                                                                                                                |
| `aliases`                 | YAML list                                                        | Obsidian uses aliases for link suggestions — include the machine-dated slug so `[[mbp--2026-04-10--rss-debug]]` autocompletes.                                                                                                                                                                                        |
| `tags`                    | YAML list (NOT comma string, NOT inline `#tag`)                  | Dataview and native Obsidian search both recognize YAML list tags. **Crucially:** a YAML list is the ONLY form Dataview and Bases can query uniformly. Inline `#tag` in the body works for search but not Dataview property filters.                                                                                  |
| `tags` values             | Use nested tags like `machine/mbp`, `project/foo`, `lang/python` | Obsidian's nested tag hierarchy gives you free faceted browsing in the tag pane and Dataview `WHERE contains(tags, "machine/")` queries.                                                                                                                                                                              |
| `gist`                    | Block-scalar `\|` multi-line                                     | Stays readable in the Obsidian property editor AND as raw YAML. Short enough to fit in Dataview table columns.                                                                                                                                                                                                        |
| `created`                 | ISO `YYYY-MM-DD`                                                 | **Dataview only parses dates in ISO format** (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`). Any other format is treated as a string and won't sort. This is the single most important frontmatter rule. Source: [Dataview data types docs](https://blacksmithgu.github.io/obsidian-dataview/annotation/types-of-metadata/). |
| `synced_at`               | ISO with time `YYYY-MM-DDTHH:MM:SS`                              | Time of sync, machine-local. Used by Dataview `WHERE synced_at > date(today) - dur(7 days)`.                                                                                                                                                                                                                          |
| `needs_review`            | Boolean `true`/`false`                                           | Dataview queries cleanly with `WHERE needs_review`. This enables Michael's zero-effort review inbox pattern.                                                                                                                                                                                                          |
| `source`                  | String literal `claude-code`                                     | Lets future Dataview queries distinguish hand-written notes from synced ones.                                                                                                                                                                                                                                         |
| (NOT using `date:`)       | —                                                                | Too ambiguous. Use `created` and `synced_at` explicitly. Obsidian's auto-injected `date` field from some plugins clashes.                                                                                                                                                                                             |
| (NOT using inline `#tag`) | —                                                                | Inconsistent with Dataview property-based queries. Stick to the `tags:` array.                                                                                                                                                                                                                                        |

**Obsidian Bases compatibility:**

Obsidian Bases (native database views, GA in 1.9) uses the same frontmatter as Dataview and expects the same formats. A `.base` file with `filters: and: - tags contains "chat"` will pick up every synced note. See `~/.claude/skills/obsidian-bases/SKILL.md` on the user's machine for the schema.

**Body template:**

```markdown
## Gist

{gist text}

## Conversation

{full exported markdown from claude-chat.py export --format md}

---

_Synced by `/sync-chats` on {synced_at} from {machine}. Edit title/tags freely; the sync will not overwrite edited notes._
```

**What NOT to do:**

- ❌ Don't use US date format `MM/DD/YYYY` — Dataview won't parse it.
- ❌ Don't use inline Dataview fields (`key:: value` in the body) for anything that could be in frontmatter — inconsistent and harder to query.
- ❌ Don't put `tags` as a comma-separated string — technically parses but Dataview treats it as one big tag.
- ❌ Don't rely on Obsidian auto-injecting `date:` from plugins like Daily Notes — explicit is better.

**Confidence: HIGH** — verified against Dataview official docs and confirmed via the `obsidian-markdown` and `obsidian-bases` skills already installed on Michael's machine.

**Sources:**

- [Dataview data types](https://blacksmithgu.github.io/obsidian-dataview/annotation/types-of-metadata/)
- [Dataview adding metadata](https://blacksmithgu.github.io/obsidian-dataview/annotation/add-metadata/)
- [Obsidian Properties help](https://help.obsidian.md/properties)
- Local: `~/.claude/skills/obsidian-markdown/SKILL.md` (user's skill)
- Local: `~/.claude/skills/obsidian-bases/SKILL.md` (user's skill)

---

## 4. MemPalace MCP Integration

### Recommendation: Use `mempalace mine --mode convos` on the Obsidian `Chats/` folder, NOT per-chat MCP tool calls

**KEY DISCOVERY:** MemPalace already ships a purpose-built mining mode for conversation exports. From `mempalace --help` (run live on Michael's machine):

> **Conversations:** `mempalace mine ~/chats/ --mode convos` (Claude, ChatGPT, Slack)
>
> Mines conversation exports from Claude, ChatGPT, or Slack into the palace.

And the plugin ships a `/mempalace:mine` skill at `~/.claude/plugins/cache/mempalace/mempalace/3.0.14/skills/mempalace/` that already wraps this workflow. There is **no need to build per-chat MCP calls** — the sync-chats skill should just invoke the existing CLI after writing the Obsidian files.

**Two viable integration patterns:**

### Pattern A (RECOMMENDED): Post-sync bulk mine

```bash
# After sync-chats has written N new .md files to the vault:
mempalace mine "/Users/michaelhenry/Library/Mobile Documents/iCloud~md~obsidian/Documents/Chats" \
  --mode convos \
  --extract general \
  --wing claude-code
```

**Why this is better than per-chat MCP calls:**

1. **Already built.** Zero code to write. The mempalace CLI handles all the ChromaDB indexing, duplicate detection (`mempalace_check_duplicate` equivalent is baked in), and classification.
2. **Auto-classification.** `--extract general` auto-classifies into decisions/milestones/problems — exactly the kind of structured retrieval Michael wants for future Claude sessions.
3. **Idempotent.** Running it repeatedly on the same folder is safe because mempalace deduplicates internally.
4. **Uses the ChromaDB path already patched for Python 3.13.** Works with Michael's existing MemPalace install without touching MCP tool routing.
5. **Works in headless mode.** It's a plain CLI — no need to spawn a Claude session.

**Wing choice:** Use `--wing claude-code` to keep synced chats grouped in their own palace wing, separate from project mining. This makes `mempalace search "X" --wing claude-code` feasible.

### Pattern B (fallback, only if A fails): Per-chat MCP `mempalace_add_drawer`

If for some reason the bulk mine mode can't ingest the written Obsidian files correctly (e.g., it doesn't understand the frontmatter), fall back to calling `mempalace_add_drawer` from the MCP server — once per chat, inside the running Claude Code session where the skill executes. MCP tool is available as confirmed in the live MCP server probe. Tool signature: `mempalace_add_drawer(content, room?, wing?, tags?)`.

**But:** this only works when the skill runs in interactive mode (where MCP tools are accessible). It does NOT work from a standalone launchd-invoked Python script because that script isn't inside a Claude Code MCP session.

**So the resilient design is:** Pattern A for the mechanical sync path, Pattern B only as an in-session enrichment step if Michael wants finer per-chat control.

**Available MCP tools (19 total) — verified from live `mempalace instructions help` output:**

- Write: `mempalace_add_drawer`, `mempalace_delete_drawer`
- Read: `mempalace_status`, `mempalace_search`, `mempalace_list_wings`, `mempalace_list_rooms`, `mempalace_get_taxonomy`, `mempalace_check_duplicate`, `mempalace_get_aaak_spec`
- KG: `mempalace_kg_add`, `mempalace_kg_query`, `mempalace_kg_invalidate`, `mempalace_kg_timeline`, `mempalace_kg_stats`
- Navigation: `mempalace_traverse`, `mempalace_find_tunnels`, `mempalace_graph_stats`
- Diary: `mempalace_diary_write`, `mempalace_diary_read`

**Environmental notes from the user's existing MemPalace setup memory** (`~/.claude/projects/.../reference_mempalace_setup.md`):

- MemPalace is installed into **Homebrew Python 3.13** via `uv pip install --python /opt/homebrew/opt/python@3.13/bin/python3.13 --break-system-packages mempalace`
- Shell alias `mempalace='python3.13 -m mempalace'` is in `~/.zshrc`
- MCP server command is `python3.13 -m mempalace.mcp_server` (patched in plugin.json — will need re-patching on plugin update)
- **The sync-chats LaunchAgent plist MUST put `/opt/homebrew/bin` in PATH** so `python3.13` resolves correctly.

**What NOT to do:**

- ❌ Don't call `mempalace_kg_add` per chat — the KG is for knowledge graph entries (entities/relations), not conversation summaries. Wrong tool.
- ❌ Don't try to use `mempalace_add_drawer` from a plain Python script — MCP tools only work inside an active Claude Code session that has the MCP server configured.
- ❌ Don't install mempalace in a different Python version — patched to 3.13 only, ChromaDB incompatible with 3.14.
- ❌ Don't ingest each chat as it's written during the sync loop — do one bulk `mempalace mine` at the end for atomicity.

**Confidence: HIGH** — directly verified by running `mempalace --help` and `mempalace instructions help` live on the user's machine, and by reading the installed plugin's `SKILL.md` at `~/.claude/plugins/cache/mempalace/mempalace/3.0.14/`.

**Sources:**

- Local: `mempalace --help` output (verified live)
- Local: `mempalace instructions help` output (verified live)
- Local: `~/.claude/plugins/cache/mempalace/mempalace/3.0.14/skills/mempalace/SKILL.md`
- Local: `~/.claude/plugins/cache/mempalace/mempalace/3.0.14/plugin.json`
- Local: `~/.claude/projects/.../reference_mempalace_setup.md` (user's own MemPalace setup notes)
- [milla-jovovich/mempalace GitHub](https://github.com/milla-jovovich/mempalace)

---

## 5. Python Subprocess Patterns — Wrapping `claude-chat.py`

### Recommendation: `subprocess.run` with `capture_output=True`, `check=True`, and `--format md` JSON-safe text

**Pattern:** The sync-chats skill's `scripts/sync.py` shells out to the existing CLI for mechanical work. Use Python stdlib `subprocess`:

```python
import subprocess
from pathlib import Path

CLAUDE_CHAT = Path.home() / "Documents/Projects/Python/claude-chat/claude-chat.py"

def list_sessions() -> list[dict]:
    """Shell out to claude-chat.py to get the session list."""
    result = subprocess.run(
        ["python3", str(CLAUDE_CHAT), "list", "--format", "json"],  # if --format json exists; else parse text
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    # Parse output...
    return parsed

def export_session(session_id: str, out_path: Path) -> None:
    """Export a single session to markdown."""
    subprocess.run(
        ["python3", str(CLAUDE_CHAT), "export", session_id, "--format", "md", "--out", str(out_path)],
        check=True,
        timeout=60,
    )

def protect_content(markdown: str) -> str:
    """Pipe markdown through the protect scrubber via stdin."""
    result = subprocess.run(
        ["python3", str(CLAUDE_CHAT), "protect", "--stdin"],  # assumes --stdin flag exists
        input=markdown,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout
```

**Rationale:**

- **`subprocess.run` not `Popen`**: simpler, blocking, exactly what a sequential sync needs. No concurrency concerns.
- **`capture_output=True, text=True`**: captures stdout+stderr as strings (UTF-8 decoded). `text=True` replaces the old `universal_newlines=True`.
- **`check=True`**: raises `CalledProcessError` if the CLI exits non-zero. Bubbles errors up instead of silently skipping.
- **`timeout=N`**: protects against hung subprocesses (e.g., if `claude-chat.py` deadlocks on a corrupt JSONL). Essential for an unattended LaunchAgent.
- **Pass paths as strings**: `Path` objects need `str()` conversion before going into `subprocess` args (works on most platforms but explicit is safer).
- **Don't use `shell=True`**: opens shell-injection risks. Pass a list of args.

**Caveat about the existing CLI's flags:** The existing `claude-chat.py` may not currently have `--format json` for list, `--stdin` for protect, or `--out` for export. **This is a gap the sync-chats milestone needs to fill** — either extend `claude-chat.py` with machine-friendly output flags (preserving the zero-deps invariant) OR have the sync script parse the human-readable output. Preference: extend `claude-chat.py` with a narrow JSON-output mode for `list` only; keep everything else as-is.

**Error handling:**

```python
try:
    result = subprocess.run(...)
except subprocess.CalledProcessError as e:
    # Log stderr, skip this session, continue
    log.warning(f"export failed for {session_id}: {e.stderr}")
    state.mark_failed(session_id)
    continue
except subprocess.TimeoutExpired:
    log.error(f"export timed out for {session_id}")
    state.mark_failed(session_id)
    continue
```

**Confidence: HIGH** — standard Python stdlib patterns.

**Sources:**

- [Python subprocess module docs](https://docs.python.org/3/library/subprocess.html)

---

## 6. Filesystem State File on macOS

### Recommendation: `~/.claude-chat/` (dotfile), NOT `~/Library/Application Support/`

**Directory structure:**

```
~/.claude-chat/                    # dotfile, local-only, never in iCloud
├── config.json                    # machine label, vault path, etc. (user-editable)
├── state.json                     # last_sync_cursor, synced_session_ids (machine-written)
├── sync.log                       # launchd stdout
└── sync.err.log                   # launchd stderr
```

**Why `~/.claude-chat/` and not `~/Library/Application Support/claude-chat/`:**

| Criterion                        | `~/.claude-chat/`                                                                            | `~/Library/Application Support/claude-chat/` |
| -------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------- |
| macOS idiomatic for GUI apps     | ❌                                                                                           | ✅                                           |
| macOS idiomatic for CLI tools    | ✅                                                                                           | ❌                                           |
| Consistent with `~/.claude/`     | ✅                                                                                           | ❌                                           |
| iCloud-safe (not synced)         | ✅                                                                                           | ✅ (both are local)                          |
| Easy to `cd` into and inspect    | ✅                                                                                           | ❌ (space in path is annoying)               |
| Discoverable (`ls -la ~`)        | ✅                                                                                           | Buried in `~/Library`                        |
| Backup-tool friendly             | ✅                                                                                           | ✅                                           |
| Convention the user already uses | ✅ (the existing CLI already references `~/.claude-chat/` patterns via `~/.claude/` sibling) | —                                            |

The `~/Library/Application Support/` convention is for **GUI/bundled apps** (`.app` packages). For CLI tools, the dotfile convention from Unix wins — and it's what every CLI tool Michael already has (`~/.claude/`, `~/.mempalace/`, `~/.ssh/`, `~/.zshrc`) uses. XDG Base Directory (`~/.config/`) is a Linux convention that Apple has never adopted; you'd be the odd one out.

**Critically: `~/.claude-chat/` is NOT in iCloud.** iCloud only syncs folders under `~/Library/Mobile Documents/`. A dotfile in `~/` stays strictly on the machine that created it — exactly what the "local-only state" requirement demands.

**Config vs state split (important convention):**

- `config.json` = user-editable, written once at setup time, read every run. Machine label, vault path overrides. Safe to `chmod 644`.
- `state.json` = machine-written, read/write every run. Cursor timestamp, synced session IDs set. Should be written atomically (temp file + rename) to survive crashes mid-sync. Use the same atomic-write pattern `cmd_protect` already uses in `claude-chat.py` (line 115-116 of the existing code per ARCHITECTURE.md).

**Atomic write pattern** (matches existing codebase style):

```python
import json, os
from pathlib import Path

def write_state(state: dict, path: Path) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, path)  # atomic on POSIX
```

**What NOT to do:**

- ❌ Don't put state in the project directory (`.planning/` or `~/Documents/Projects/Python/claude-chat/`) — the skill is global, not tied to one project checkout.
- ❌ Don't put it anywhere under `~/Library/Mobile Documents/` — that's iCloud and will corrupt cross-machine.
- ❌ Don't put it in `~/.claude/` — that's Claude Code's own directory and could conflict with future Claude Code features (this has already happened — Anthropic has added subdirectories over time).
- ❌ Don't use `/tmp` or `/var` — wiped on reboot (`/tmp`) or needs sudo (`/var`).
- ❌ Don't make state a single flat file if it could grow large — if `synced_session_ids` gets huge (thousands of sessions over years), consider SQLite. But for the foreseeable future, a JSON array is fine and stays zero-deps.

**Confidence: HIGH** — macOS filesystem conventions are well-established; the choice is mostly about matching surrounding tooling, and all of Michael's surrounding tooling uses dotfiles.

**Sources:**

- [Apple File System Programming Guide: Library directories](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/FileSystemOverview/FileSystemOverview.html)
- Convention verified against user's existing `~/.claude/`, `~/.mempalace/`, and `~/.zshrc` layout

---

## Summary: Recommended Stack

| Concern                | Choice                                                                                                         | Confidence |
| ---------------------- | -------------------------------------------------------------------------------------------------------------- | ---------- |
| Skill location         | `~/.claude/skills/sync-chats/`                                                                                 | HIGH       |
| Skill frontmatter      | `name`, `description` (pushy), `disable-model-invocation: true`, `allowed-tools` prefix-matched                | HIGH       |
| Skill layout           | `SKILL.md` + `scripts/` + `references/` + `templates/` (progressive disclosure)                                | HIGH       |
| Mechanical sync engine | Plain Python 3 stdlib script in `scripts/sync.py` — NOT bash in SKILL.md, NOT reliant on `claude -p`           | HIGH       |
| Headless invocation    | LaunchAgent runs `scripts/sync.py` directly, NOT `claude -p "/sync-chats"` (slash commands don't work in `-p`) | HIGH       |
| Scheduler              | launchd LaunchAgent with `StartInterval: 3600` + `RunAtLoad: true`                                             | HIGH       |
| Plist location         | `~/Library/LaunchAgents/com.michaelhenry.sync-chats.plist`                                                     | HIGH       |
| Env for launchd        | Explicit `PATH` with `/opt/homebrew/bin` first (mempalace needs python3.13)                                    | HIGH       |
| Obsidian frontmatter   | YAML list tags, ISO dates, explicit `created`/`synced_at`/`needs_review`/`machine` fields                      | HIGH       |
| Date format            | `YYYY-MM-DD` (Dataview-parseable)                                                                              | HIGH       |
| Tag format             | YAML list with nested like `machine/mbp`, `project/foo`                                                        | HIGH       |
| MemPalace integration  | `mempalace mine --mode convos --extract general --wing claude-code` on the vault folder (bulk, post-sync)      | HIGH       |
| MemPalace fallback     | `mempalace_add_drawer` MCP tool (only viable in interactive skill invocation)                                  | HIGH       |
| Subprocess wrapping    | `subprocess.run(..., capture_output=True, text=True, check=True, timeout=N)`                                   | HIGH       |
| State directory        | `~/.claude-chat/` (dotfile, strictly local, NOT `~/Library/Application Support/`)                              | HIGH       |
| State write pattern    | Atomic temp-file + `os.replace`                                                                                | HIGH       |

---

## Open Questions for Roadmap

1. **Headless invocation architecture.** The biggest surprise from this research: `claude -p "/sync-chats"` does not work because slash commands are disabled in headless mode. The roadmap needs to decide: (a) ditch the LaunchAgent path and make `/sync-chats` interactive-only, (b) have the LaunchAgent run a plain Python script that does the sync mechanically and uses a heuristic for summarization (no AI in the headless path), or (c) have the LaunchAgent run `claude -p "Please run the sync-chats workflow now"` and hope the skill auto-invokes via description matching. Option (b) is the most robust. Surface this to Michael before Phase 1.

2. **`claude-chat.py` JSON output flag.** The sync script needs machine-readable output from the existing CLI (at minimum for `list`). Does the roadmap include a small extension to `claude-chat.py` to add `--format json` for `list`? Or does the sync script parse the human-readable table output? Prefer the former — keeps the scrape-parsing out of the sync script.

3. **`protect` as a filter.** Does the existing `protect` command work as a stdin→stdout filter, or does it only operate on files? If the latter, the sync script needs a temp file dance. Minor but affects Phase 2 implementation.

4. **`mempalace mine --mode convos` on Obsidian `.md` files.** Need to verify that MemPalace's convos mode understands Obsidian frontmatter + body structure. If it expects raw Claude export JSONL, we'd want to mine from `~/.claude/projects/` directly rather than the vault. Quick experiment in Phase 3 to verify.

5. **Multi-machine install.** How does the skill get to the second Mac? Since `~/.claude/skills/` on Michael's first Mac is a symlink to `~/Sync/claude-code-config/.claude/skills` (verified during research), Syncthing/Sync already handles skill distribution across both Macs. The LaunchAgent plist, however, is per-machine and must be installed separately — should the skill have an `install-launchd` subcommand?

---

_Research complete: 2026-04-10_
