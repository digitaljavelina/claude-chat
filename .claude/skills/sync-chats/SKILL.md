---
name: sync-chats
description: Sync Claude Code sessions to Obsidian vault with AI-generated labels
disable-model-invocation: true
allowed-tools:
  - Bash
  - Read
argument-hint: "(no arguments - syncs all new sessions)"
---

# Sync Chats to Obsidian

You are both the skill executor and the labeler in this skill. The instructions below describe a sequential pipeline you execute step-by-step. Claude (you) reads each session's content, generates a label, and pipes it into `sync_chats.py write`. No API calls are made — the labeling happens inline as you read and respond.

**Important:** Always use `$HOME` (not `~`) in Bash commands. Never use the Write tool — all vault writes go through `sync_chats.py write` via stdin pipe.

---

## Step 1 — Scan for new sessions

Run the scan command via Bash:

```bash
python3 $HOME/.claude-chat/sync_chats.py scan
```

Parse the JSON array from stdout. Each element looks like:

```json
{
  "session_id": "uuid-string",
  "project": "encoded-project-dir",
  "path": "/absolute/path/to/file.jsonl",
  "mtime": 1234567890.123,
  "size": 4096
}
```

- If the array is empty: print "No new sessions to sync." and stop.
- Otherwise: print "Found N new session(s) to process." and proceed to Step 2.

---

## Step 2 — Process each session sequentially

For each session in the delta list, follow steps 2a through 2e in order. Process one session at a time (do not batch).

### 2a. Check user message count (ultra-short skip)

Run a Bash one-liner to count user messages in the session's JSONL file. Handle both plain-string content and block-list content formats:

```bash
python3 -c "
import json, pathlib
path = pathlib.Path('SESSION_PATH_HERE')
count = 0
with open(path, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get('message', obj)
        if msg.get('role') != 'user':
            continue
        content = msg.get('content', '')
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = ' '.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text').strip()
        else:
            text = ''
        if '<system-reminder>' in text:
            continue
        if len(text) > 5:
            count += 1
print(count)
"
```

Replace `SESSION_PATH_HERE` with the session's `path` field. If the count is less than 2, print "Skipping SESSION_ID: fewer than 2 user messages" and continue to the next session. Increment the skip counter for the Step 3 summary.

### 2b. Extract first and last message pairs

Use the Read tool to load the JSONL file at the session's `path` field.

From the loaded content, identify user and assistant messages. Skip:

- Any message where content contains `<system-reminder>`
- Tool use blocks (content blocks where type is `tool_use` or `tool_result`)
- Lines that are not valid JSON

Extract the **first 5** and **last 5** user/assistant message pairs (by their sequence in the file). If the session has 10 or fewer messages, use all of them. For content that is a list of typed blocks, concatenate all `text`-type blocks. Format each message as:

```
[USER]: <content>
[ASSISTANT]: <content>
```

Truncate any single message to 500 characters if needed to keep the prompt manageable.

### 2c. Generate a label

Present the extracted messages to yourself with the following labeling prompt. You are both the executor and the labeler — generate the label now, inline, as part of executing this step.

---

**LABELING PROMPT — generate a label for this session:**

Below are excerpts from a Claude Code session. Your task is to generate a structured label for this session.

**Session ID:** SESSION_ID
**Project:** SESSION_PROJECT

**Session excerpts (first and last messages):**

[PASTE EXTRACTED MESSAGES HERE]

---

**Output format:** Produce a single ```json fenced code block containing exactly these keys:

```json
{
  "title": "...",
  "gist": "...",
  "tags": ["...", "...", "..."],
  "coherence_score": 4,
  "needs_review": false
}
```

**Rules:**

- **title:** Verb-leading action phrase, maximum 10 words. Examples: "Debug RSS feed parsing in homelab service", "Set up Python virtual environment for Django project", "Configure nginx reverse proxy with SSL". Use a noun phrase only if the session is purely exploratory with no clear action taken.
- **gist:** 2–3 sentences in past tense summarizing what the user asked, what was explored or built, and what the outcome was.
- **tags:** A JSON array of 3–5 kebab-case strings (lowercase letters, digits, hyphens only — no spaces, no uppercase, no special characters). Store as a JSON array (not comma-separated, not inline #tags). Tags should capture: primary language/framework, problem domain, activity type. Examples: `["python", "virtual-env", "setup"]`, `["go", "rss-parsing", "debugging", "homelab"]`. "If this session is mostly automated tool output with little meaningful human conversation, include `low-signal` in the tags array." "If the conversation covers clearly distinct unrelated topics, include `multi-topic` in the tags array."
- **coherence_score:** An integer 1–5. 5 = Single clear topic, question answered or task completed. 4 = Single topic, partial resolution or ongoing work. 3 = Related topics, reasonable conversation flow. 2 = Multiple loosely related topics, some drift. 1 = Scattered, abandoned, or incoherent conversation. "This score is metadata only. Do not skip or treat any session differently based on the score."
- **needs_review:** Always `false` unless fallback triggers.

**Few-shot examples of ideal output:**

Example 1 (debugging session):

```json
{
  "title": "Debug RSS feed parsing in homelab service",
  "gist": "Debugged a failing RSS parser in a Go homelab service. The root cause was unescaped ampersands in feed URLs breaking the XML parser. Added a pre-parse sanitizer and a regression test.",
  "tags": ["go", "rss-parsing", "debugging", "homelab"],
  "coherence_score": 5,
  "needs_review": false
}
```

Example 2 (setup/configuration session):

```json
{
  "title": "Configure Tailscale VPN across two Macs",
  "gist": "Set up Tailscale on both a MacBook Pro and Mac Studio for secure remote access. Configured ACLs to allow SSH and HTTP traffic between machines. Verified connectivity with ping and curl tests.",
  "tags": ["tailscale", "vpn", "networking", "macos", "setup"],
  "coherence_score": 5,
  "needs_review": false
}
```

Example 3 (writing/documentation session):

```json
{
  "title": "Draft project README with installation guide",
  "gist": "Wrote a README.md for an open-source CLI tool. Included installation instructions for macOS and Linux, usage examples for the three main commands, and a contributing guide.",
  "tags": ["documentation", "readme", "open-source"],
  "coherence_score": 4,
  "needs_review": false
}
```

Example 4 (exploration session — noun phrase title):

```json
{
  "title": "Python async patterns and concurrency tradeoffs",
  "gist": "Explored different approaches to concurrency in Python including asyncio, threading, and multiprocessing. Compared performance characteristics for I/O-bound vs CPU-bound workloads. No code was written.",
  "tags": ["python", "async", "concurrency", "exploration"],
  "coherence_score": 3,
  "needs_review": false
}
```

---

Generate the label now. Produce only the ```json fenced code block — no other output after it.

### 2d. Extract JSON and write

After you generate the label above, extract the JSON values from the ```json block you just produced. Construct and run the following Bash command, filling in the actual values:

```bash
python3 -c "import json; print(json.dumps({'title': 'TITLE_HERE', 'gist': 'GIST_HERE', 'tags': ['TAG1', 'TAG2', 'TAG3'], 'coherence_score': SCORE_HERE, 'needs_review': False}))" | python3 $HOME/.claude-chat/sync_chats.py write SESSION_ID_HERE
```

Replace each placeholder with the actual label values. This pattern uses Python's `json.dumps()` to serialize the label safely — it avoids shell injection from titles or gists that contain quotes, apostrophes, or other shell-special characters.

If the write command outputs `Wrote: ...`, increment the labeled counter. If it outputs `skipped: already_synced`, note it but do not count as an error.

### 2e. Fallback on parse failure

If you cannot find a ```json fenced code block in your label response, or the JSON cannot be parsed, do NOT retry. Instead, fall back immediately to `make_stub_label()`:

```bash
python3 -c "
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path.home() / '.claude-chat'))
import sync_chats
label = sync_chats.make_stub_label(pathlib.Path('SESSION_PATH_HERE'), 'SESSION_ID_HERE')
print(json.dumps(label))
" | python3 $HOME/.claude-chat/sync_chats.py write SESSION_ID_HERE
```

Print a warning: "Label generation failed for SESSION_ID, using stub label." Increment the stubbed counter.

---

## Step 3 — Print summary

After processing all sessions, print a summary line:

```
Processed N sessions: M labeled, K stubbed, J skipped (ultra-short).
```

Where:

- N = total sessions from the scan delta list
- M = sessions where a label was successfully generated and written
- K = sessions where label generation failed and stub was used
- J = sessions skipped due to fewer than 2 user messages

---

## Step 3a — Upgrade stub labels from SessionEnd-hook runs

The SessionEnd hook (`python3 $HOME/.claude-chat/sync_chats.py --once`) writes every new chat to the vault with a placeholder label (`auto_label_hash: stub`, `needs_review: true`, `tags: [stub]`). Before mining, upgrade those stub files to AI-quality labels — one at a time, using the same labeling approach as Step 2c.

### 3a-1. Find stub candidates

Run a Bash one-liner to list every `.md` file in the vault Chats/ subdirectory whose frontmatter contains `auto_label_hash: stub`:

```bash
python3 -c "
import json, pathlib
config = json.loads((pathlib.Path.home() / '.claude-chat' / 'config.json').read_text())
chats_dir = pathlib.Path(config['vault_path']) / 'Chats'
stubs = []
for f in sorted(chats_dir.glob('*.md')):
    try:
        head = f.read_text(encoding='utf-8', errors='replace').split('\n', 30)
    except OSError:
        continue
    in_fm = False
    sid = None
    is_stub = False
    for line in head[:30]:
        s = line.strip()
        if s == '---':
            in_fm = not in_fm
            continue
        if not in_fm:
            continue
        if s.startswith('session_id:'):
            sid = s.split(':', 1)[1].strip()
        if s == 'auto_label_hash: stub':
            is_stub = True
    if is_stub and sid:
        stubs.append({'session_id': sid, 'path': str(f)})
print(json.dumps(stubs))
"
```

Parse the JSON array. If empty, print "No stub files to upgrade." and proceed to Step 4. Otherwise print "Found N stub file(s) to upgrade." and enter the loop.

### 3a-2. Upgrade loop (one stub at a time)

For each stub entry in the list, do the following **sequentially** — do not batch:

1. **Read the body:** Use the Read tool to load the `.md` file at the stub's `path` field. Skip the frontmatter (the block between the first two `---` lines) and use only the body below it.
2. **Generate a label:** Run the same Step 2c labeling prompt against the body. The body is already the rendered session export, so you don't need to re-open the JSONL. Output format identical to Step 2c — a single ```json fenced code block with `{title, gist, tags, coherence_score, needs_review: false}`.
3. **Extract and pipe to `relabel`:** Build the same `json.dumps(...) | sync_chats.py relabel SESSION_ID` command as Step 2d, but use `relabel` (not `write`):

   ```bash
   python3 -c "import json; print(json.dumps({'title': 'TITLE_HERE', 'gist': 'GIST_HERE', 'tags': ['TAG1', 'TAG2', 'TAG3'], 'coherence_score': SCORE_HERE, 'needs_review': False}))" | python3 $HOME/.claude-chat/sync_chats.py relabel SESSION_ID_HERE
   ```

4. **Expected output:** `relabeled: <filename>`. On refusal — stderr line containing `refusing to rewrite ... (auto_label_hash is not 'stub' — D-05 sentinel-only trigger)` — **SKIP and move on**. The file was manually labeled or already upgraded between scan and run. Do not retry.

5. **On JSON parse failure in step 2:** Skip this stub (do NOT fall back to another stub — it's already a stub). Log a warning: "Relabel generation failed for SESSION_ID, leaving as stub." Continue to the next candidate.

### 3a-3. Append upgrade summary

After the loop, append a line to the Step 3 summary:

```
Relabeled P stub(s) of Q discovered (R refused, S failed).
```

Where P = successfully relabeled, Q = total found in 3a-1, R = refused by D-05 guard, S = label generation failed.

**Design note (D-05):** This loop is **sentinel-driven**, not `needs_review`-driven. A user who manually flags `needs_review: true` on a real-labeled file must NOT trigger a re-label — the `relabel` subcommand will refuse and the SKILL honors that refusal by skipping.

---

## Step 4: Mine vault into MemPalace (post-run)

After all `write` calls in Step 2 complete, shell out **once** to the MemPalace bulk-mine CLI so every new chat gets ingested.

**Zero-write skip (D-05):** If Step 2 wrote zero files (M + K counters both 0), skip calling `mine` entirely and append the following line to the Step 3 summary instead:

```
mempalace_mined: skipped (no new files)
```

Rationale: a full-directory scan of an unchanged vault is wasted work.

**Otherwise**, run:

```bash
python3 $HOME/.claude-chat/sync_chats.py mine
```

Capture the single stdout line this prints — one of:

- `mempalace_mined: true`
- `mempalace_mined: false (<reason>)`
- `mempalace_mined: skipped (<reason>)`

Append it verbatim as the **last line** of the Step 3 summary block so the full summary reads:

```
Processed N sessions: M labeled, K stubbed, J skipped (ultra-short).
mempalace_mined: <status>
```

**Do not** raise or abort if `mine` reports `false` or `skipped`. The mine outcome is reportable state, not a blocker — vault writes are already committed by Step 2.
