# claude-chat + sync_chats

**Auto-sync every Claude Code session to your Obsidian vault.**

Zero external dependencies. One symlink. Two Python files. Three decision tiers.

---

## 1. What it does

When you end a Claude Code session, a background hook fires `python3 ~/.claude-chat/sync_chats.py --once`. The script scans `~/.claude/projects/` for new sessions, scrubs PII (API keys, JWTs, emails, GitHub tokens, etc.), renders each to markdown, and lands a stub-titled file in `<vault>/Chats/` within ~1 second. No AI calls happen during the hook — it's pure stdlib I/O.

Later, when you run `/sync-chats` interactively inside Claude Code, a SKILL walks each stub-labeled file, reads the rendered body, generates an AI-quality title/gist/tags, and upgrades the frontmatter in place via `sync_chats.py relabel`. Body bytes never change — the original scrub is preserved byte-for-byte. If you have [MemPalace](https://github.com/anthropics/mempalace) installed, the SKILL also shells out once to `mempalace mine` so every new chat gets ingested into your semantic memory palace.

The design: single-file, stdlib-only Python — no external packages, no virtualenv, just `python3`.

---

## 2. Prerequisites

- **Python 3.9+** — `python3 --version`. macOS ships it via Xcode Command Line Tools.
- **An Obsidian vault** at a known absolute path. Any folder works; we write into `<vault>/Chats/`, created automatically on first write.
- **Claude Code** installed — this is what fires the SessionEnd hook.
- **Optional:** `pipx` + `mempalace` for MemPalace integration (see Section 7).
- **NOT iCloud-synced:** `~/.claude-chat/` must be local disk. The script asserts this at startup; if `CLAUDE_CHAT_HOME` resolves into `~/Library/Mobile Documents/` or contains `iCloud`, it refuses to run. See Section 9 if you need to relocate.

---

## 3. Install

```bash
git clone https://github.com/digitaljavelina/claude-chat.git <your-repo-clone-path>
mkdir -p ~/.claude-chat
ln -sf <your-repo-clone-path>/sync_chats.py ~/.claude-chat/sync_chats.py
```

Replace `<your-repo-clone-path>` with wherever you keep git repos — e.g., `~/Projects/claude-chat`, `~/code/claude-chat`, or `~/Documents/Projects/Python/claude-chat`. The clone path is yours to choose; the symlink decouples it from the stable path that the SessionEnd hook references.

**Why the symlink:** `~/.claude-chat/sync_chats.py` is the stable path referenced by the SessionEnd hook. Symlinking it into your repo clone means `git pull` updates the runtime copy automatically — no re-install step. Python's `Path(__file__).resolve().parent` follows the symlink, so `sync_chats.py` still finds its sibling `claude-chat.py` inside the cloned repo.

---

## 4. Configure

```bash
python3 ~/.claude-chat/sync_chats.py init \
  --label mbp \
  --vault "/Users/you/Library/Mobile Documents/iCloud~md~obsidian/Documents/YourVault"
```

- `--label` is this machine's short identity (e.g., `mbp`, `studio`, `thinkpad`). It prefixes every vault filename: `<label>--YYYY-MM-DD--<slug>.md`. Keep it short and alphanumeric.
- `--vault` is an absolute path to your Obsidian vault directory. The pipeline writes into `<vault>/Chats/` (created on first write if missing).
- Re-running `init` with the same flags is a safe no-op. Use this on the second Mac to verify config without fear of clobbering.

Verify:

```bash
cat ~/.claude-chat/config.json
```

Should show `{schema_version: 1, machine_label: "mbp", vault_path: "/Users/you/..."}`.

---

## 5. Install the SessionEnd hook

> **Back up `~/.claude/settings.json` before editing.** JSON syntax errors here will break Claude Code's hook runner for every tool, not just this one.
>
> ```bash
> cp ~/.claude/settings.json ~/.claude/settings.json.bak
> ```

Your `~/.claude/settings.json` likely already has a `hooks.SessionEnd` array with existing entries (from other plugins or prior setups). **APPEND the following entry to that array — do NOT replace the whole key:**

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "python3 ~/.claude-chat/sync_chats.py --once",
      "timeout": 60
    }
  ]
}
```

That JSON object is a single element in the `hooks.SessionEnd` array. If your existing `settings.json` already has `hooks.SessionEnd: [...]`, add this object inside the brackets (comma-separate it from existing entries).

<details>
<summary>If your <code>settings.json</code> has no <code>SessionEnd</code> array yet, use this full structure</summary>

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude-chat/sync_chats.py --once",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

</details>

**How the hook runs:** The hook executes synchronously on session end — Claude Code waits for it to complete before the session fully closes. Typical wall-clock is sub-second: no AI calls, no `mempalace mine`, just scan + stdlib I/O on however many new sessions appeared. If `--once` exits non-zero, Claude Code briefly surfaces the first line of stderr in the terminal; full details live in `~/.claude-chat/sync.log` and `~/.claude-chat/last_run.json`.

Validate your edit:

```bash
python3 -m json.tool < ~/.claude/settings.json
```

If this prints the parsed JSON without errors, you're good. If it prints a parse error, restore the backup and try again.

---

## 6. First run

1. End any Claude Code session (close the tab, hit `/exit`, or just close the terminal).
2. Within ~1 second, check your vault:
   ```bash
   ls -lt "/Users/you/Library/Mobile Documents/iCloud~md~obsidian/Documents/YourVault/Chats/" | head -3
   ```
   You should see a new `<label>--<date>--<slug>.md` file with a `[stub]`-style filename ending like `--session-about-x`.
3. Check the machine-readable run record:
   ```bash
   cat ~/.claude-chat/last_run.json | python3 -m json.tool
   ```
   Expected shape: `trigger: "once"`, `synced: 1` (or however many new sessions landed), `failed: 0`, `mempalace_mined: "skipped"`, `exit_code: 0`.
4. Human-readable summary:
   ```bash
   python3 ~/.claude-chat/sync_chats.py status
   ```

If nothing appears, jump to Section 9 troubleshooting.

### Second-Mac checklist

When bringing up a second machine (the HOOK-05 acceptance target — clean install → first sync in under 10 minutes), verify each step before trusting the hook:

1. `python3 --version` shows 3.9+.
2. `ls -l ~/.claude-chat/sync_chats.py` is a symlink pointing into your repo clone.
3. `python3 ~/.claude-chat/sync_chats.py --help` runs without error.
4. `~/.claude-chat/config.json` exists with `machine_label` + `vault_path` matching this machine.
5. `<vault>/Chats/` exists (or will be created on first write).
6. `~/.claude/settings.json` has the SessionEnd entry; `python3 -m json.tool < ~/.claude/settings.json` validates.
7. End a Claude Code session → new file appears in `<vault>/Chats/` within 2 seconds.
8. Optional: `which mempalace` returns a path (if you installed it in Section 7).

---

## 7. Optional: MemPalace

Installing [MemPalace](https://github.com/anthropics/mempalace) lets the interactive `/sync-chats` SKILL ingest your chats into a semantic memory palace. This is **optional** — the pipeline works without it. If `mempalace` is missing from `$PATH`, the SKILL logs `mempalace_mined: skipped (command not found)` and moves on (graceful degradation per Phase 4).

```bash
brew install pipx
pipx install mempalace
```

Verify:

```bash
which mempalace    # should show ~/.local/bin/mempalace or similar
```

The SKILL will call `mempalace mine <vault>/Chats --mode convos --extract general` once per interactive run, after all writes and relabels complete.

---

## 8. Daily use

- **Automatic:** Ending a Claude Code session writes a stub-titled chat to the vault. No action needed. Stub files carry `auto_label_hash: stub`, `tags: [stub]`, `needs_review: true`.
  - **What counts as "ending a session":** typing `/exit` or `/quit`, pressing `Ctrl+D` at an empty prompt, or closing the terminal window/tab. The SessionEnd hook does NOT fire on `/clear` (that keeps the session going, just resets context), `Ctrl+C` mid-response (interrupts but stays connected), model switches, or hard process kills / crashes. If a crash means a session never fires the hook, run `/sync-chats` interactively — it catches anything the hook missed.
- **Upgrade stubs to AI labels:** Open any Claude Code session and run `/sync-chats`. The SKILL finds every file with `auto_label_hash: stub` and rewrites just their frontmatter with a real title/gist/tags — body bytes are never touched (D-04). The hash flips from `stub` to a real SHA-256, and `needs_review` becomes `false`. If MemPalace is installed, it also shells out once to mine the whole `Chats/` folder.
- **Audit:** `python3 ~/.claude-chat/sync_chats.py status` shows the most-recent run summary (machine, trigger, counts, timestamps). `tail ~/.claude-chat/sync.log` shows timestamped history across all runs.
- **One-off re-label:** If you need to re-label a single stub file outside of the SKILL:
  ```bash
  echo '{"title":"...","gist":"...","tags":["..."],"coherence_score":4,"needs_review":false}' \
    | python3 ~/.claude-chat/sync_chats.py relabel <session_id>
  ```
  The `relabel` subcommand is sentinel-gated (D-05): it refuses with exit 1 on any file whose `auto_label_hash` is not the literal string `"stub"`. You can never accidentally clobber an AI-labeled file.

---

## 9. Troubleshooting

**"iCloud assertion failed" at startup.** `~/.claude-chat/` is inside an iCloud-synced path, or a symlink that resolves into one. The pipeline refuses to run because state-file corruption on iCloud is a known class of bug. Fix:

```bash
# Option A: relocate via env var (preferred — survives reboots if in shell rc)
export CLAUDE_CHAT_HOME=/Users/you/claude-chat-local
# then add the export to ~/.zshrc or ~/.bashrc

# Option B: physically move the folder somewhere local
mv ~/.claude-chat /Users/you/claude-chat-local
```

The assertion resolves symlinks (`Path.resolve()`), so symlinking `~/.claude-chat` to an iCloud path will still fail — the env-var route is cleanest.

**Hook doesn't fire on session end.**

1. JSON validity: `python3 -m json.tool < ~/.claude/settings.json` — if this errors, the backup copy (`settings.json.bak`) is your recovery.
2. Live-watch the log: `tail -f ~/.claude-chat/sync.log` in one terminal, end a Claude Code session in another. A `run-start trigger=once machine=<label>` line should appear. If nothing: the hook isn't firing.
3. `~` expansion: some shell contexts don't expand `~` in JSON-configured command strings. If in doubt, replace `~/.claude-chat/sync_chats.py` with an absolute path like `/Users/you/.claude-chat/sync_chats.py` in `settings.json`.
4. Timeout too tight: the default timeout is 60 seconds. If you have an enormous session backlog (hundreds of new sessions on first run), bump `timeout` in the hook JSON.

**`hostname` field in `last_run.json` looks weird** (e.g., `digital-javelina-pro.tail75a1.ts.net`). That's your Tailscale FQDN; `socket.gethostname()` returns it when Tailscale is active. This is informational — `machine_label` (from your `init --label`) is the canonical identity marker used in filenames and frontmatter.

**sync.log location.** `~/.claude-chat/sync.log`. Plain text, append-only, one line per event. Rotate manually if it grows large (log rotation is deferred to a future phase).

**First `--once` run reports `failed: N` in `last_run.json` with "Could not find a free filename after 99 attempts".** Expected on machines with significant Claude Code history. The filename generator appends `-2`, `-3`, ..., `-99` before giving up; if you have 100+ subagent warmup sessions (or any cluster of sessions whose first user message is literally identical — common with Claude Code task runners, vibe-log, or similar tools), sessions 100+ hit the cap. The workaround is a one-time manual quarantine:

```bash
# Scan returns only still-pending sessions; append their UUIDs to state so they're skipped forever.
python3 ~/.claude-chat/sync_chats.py scan | \
  python3 -c "
import json, sys, pathlib
state_path = pathlib.Path.home() / '.claude-chat' / 'state.json'
state = json.loads(state_path.read_text())
remaining = [s['session_id'] for s in json.load(sys.stdin)]
# Backup before writing
state_path.with_suffix('.json.bak-quarantine').write_text(json.dumps(state, indent=2))
seen = set(state.get('synced_session_ids', []))
state['synced_session_ids'] = list(state.get('synced_session_ids', [])) + [s for s in remaining if s not in seen]
state_path.write_text(json.dumps(state, indent=2))
print(f'quarantined {len(remaining)} session(s); backup at {state_path}.bak-quarantine')
"
```

**First interactive `/sync-chats` run reports a surprisingly large scan count** (e.g., "Found 867 new sessions"). Expected if the hook wasn't installed from session 1 — ultra-short sessions (fewer than 2 real user messages) are skipped at the SKILL layer rather than written, so they never enter `state.json` and get re-discovered on every scan. The first `--once` hook fire stub-writes all of them, after which future scans return near-zero. This isn't a bug; it's the SKILL's ultra-short filter showing its history.

**Verify the setup end-to-end without ending a session:**

```bash
python3 ~/.claude-chat/sync_chats.py scan && echo "scan OK"
python3 ~/.claude-chat/sync_chats.py status && echo "status OK"
```

---

## 10. Architecture

Three tiers, deliberately separated so each one can evolve independently:

1. **SessionEnd hook** in `~/.claude/settings.json` — the event source. Claude Code invokes the `command` string verbatim after every session end. We keep this layer dumb: no conditional logic, no arguments, just `python3 ~/.claude-chat/sync_chats.py --once`.
2. **`sync_chats.py`** — stdlib-only Python toolkit. Single file, zero external dependencies. Subcommands: `init`, `scan`, `write`, `status`, `mine`, `relabel`. Plus the `--once` root flag that wraps `scan` + stub-writes + `last_run.json` in one atomic pass for the hook. This is where all the deterministic file I/O, PII scrubbing, clobber defense, and atomic-write discipline lives.
3. **SKILL.md** at `~/.claude/skills/sync-chats/SKILL.md` — the interactive orchestrator. Per-user (not in this repo — sits on each machine alongside your other Claude Code skills). When you run `/sync-chats`, Claude reads each session's JSONL, generates an AI label inline, and pipes it into `sync_chats.py write` or `sync_chats.py relabel`. No API calls happen anywhere else in the pipeline — Claude (via the SKILL) is the labeler.

The underlying engine `claude-chat.py` (also in this repo) is a separate CLI for browsing and exporting sessions (`list`, `search`, `export`, `serve`, etc.). `sync_chats.py` shells out to `claude-chat.py export --stdout` to get the markdown body for each session. That's the only coupling between the two.

Full decision log and per-phase artifacts live in `.planning/` — see `.planning/PROJECT.md` for the milestone overview and `.planning/phases/` for every phase's context, research, plans, and summaries.

---

MIT — by [Holger Morlok](https://github.com/holbizmetrics)
