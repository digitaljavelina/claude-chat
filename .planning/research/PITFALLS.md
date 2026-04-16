# Pitfalls Research — `/sync-chats` skill

**Domain:** macOS background automation writing to iCloud-synced Obsidian vault, orchestrated by a Claude Code skill, feeding an MCP memory store, with mandatory PII scrubbing for clinical/regulatory content
**Researched:** 2026-04-10
**Confidence:** MEDIUM-HIGH (launchd and iCloud claims verified against Apple Developer Forums and community writeups; MCP and LLM-labeling pitfalls drawn from general MCP/LLM practice and need per-phase validation)

---

## How to read this document

Every pitfall has four fields the roadmap writer cares about:

- **Severity** — `CATASTROPHIC` (PII leak, data loss, two-Mac corruption), `BAD` (lost work, silent wrong results), `ANNOYING` (degraded UX, recoverable)
- **Likelihood** — how often this actually bites in practice
- **Phase to address** — P1 (skeleton), P2 (labeling+scrub), P3 (vault writer), P4 (MCP integration), P5 (launchd + multi-machine), P6 (hardening)
- **Warning signs** — the earliest concrete symptom, so you catch it during dogfooding

The **single most important pitfall** is #17 (user edits in Obsidian → next run clobbers). The PII scrub ordering bug (#10) is the one with the worst blast radius. Read those first if you read nothing else.

---

## Critical Pitfalls

### 1. launchd `StartInterval` does NOT fire on every missed hour during sleep — it coalesces into one run

**What goes wrong:**
The naive mental model of `StartInterval: 3600` is "runs every hour, catches up any misses on wake." Reality: if the laptop sleeps from 22:00 to 09:00 (11 missed firings), launchd fires the job **exactly once** on wake, not 11 times. Apple Developer Forums and `launchd.info` confirm: "If multiple intervals transpire before the computer is woken, those events will be coalesced into one event upon wake from sleep."

**Why it matters for this skill:**
This is actually the behavior we want — but only if the skill is genuinely delta-sync and processes everything since `last_sync_cursor` on a single invocation. If the skill is written assuming "each run handles ~1 hour of new chats" and silently caps work at, say, 5 sessions, the coalesced wake-run will leak sessions forever.

**Why it happens:**
Developers test with `launchctl kickstart` which fires once, notice it works, never test the "laptop closed for 14 hours" path. The bug manifests only after a real sleep gap.

**How to avoid:**

- The delta-sync scanner must have **no artificial limit** on how many sessions one invocation can process. Explicitly — no `head -n 10`, no `break after 5`.
- On startup, log `found N new sessions since cursor <ts>` so a 50-session catch-up run is visible in logs.
- Add an integration test: set cursor to 48 hours ago on a machine with >20 new sessions, run once, assert all 20 landed in the vault.
- Do NOT rely on `StartInterval` as the only guarantee. Keep `RunAtLoad: true` so login-after-long-sleep also triggers a pass.

**Warning signs:**

- After a multi-day trip, the first `Chats/` file dated post-trip is missing hours 2-N of the sleep gap.
- `state.json` `last_sync_cursor` updates but `synced_session_ids` count grows slower than session files in `~/.claude/projects/`.

**Severity:** BAD (silent data loss) · **Likelihood:** HIGH (happens on first weekend) · **Phase:** P1 (delta scanner design) + P5 (launchd install)

---

### 2. launchd on wake has no network, no DNS, no PATH — and `claude -p` will fail silently

**What goes wrong:**
LaunchAgents running via `StartInterval` after a wake event fire **before network stack is up**. DNS may fail, `claude` CLI may not find the API endpoint, or Wi-Fi is still associating. The Slogger launchd-after-wake issue on GitHub and the `launchd-dev` mailing list both document this exact pattern.

Additionally, LaunchAgent-invoked processes inherit a minimal environment — no `PATH`, no `HOME`-relative shell aliases, no `nvm`/`pyenv` shims. `claude` CLI lives at `/opt/homebrew/bin/claude` (Apple Silicon) or `/usr/local/bin/claude` (Intel) and won't be on the inherited PATH.

**Why it happens:**
`launchctl kickstart` from a running terminal inherits your interactive shell's environment; running via `launchd` on wake does not. Developers test the former, ship to the latter.

**How to avoid:**

- Use **absolute paths** in the plist `ProgramArguments`. Not `claude`, but `/opt/homebrew/bin/claude` or whatever `which claude` returns on THIS Mac. Machine-specific — bake into install script.
- Set `EnvironmentVariables` in the plist explicitly: `PATH`, `HOME`, `USER`, plus any API tokens Claude Code needs.
- Add a **network readiness wait** at the top of the skill: loop `ping -c1 api.anthropic.com` (or `scutil --dns`) with a 30-second timeout before invoking anything Claude-dependent. Exit 0 (not failure) if network never arrives — next `RunAtLoad` will try again.
- Use `StandardOutPath` and `StandardErrorPath` in the plist to capture logs to `~/.claude-chat/logs/launchd.log`. Without this, silent failures are invisible.

**Warning signs:**

- Log file shows runs but zero new files in `Chats/` after wake.
- `stderr` log has "command not found: claude" or DNS errors.
- Skill works when you run it by hand but "never runs on its own."

**Severity:** CATASTROPHIC (skill never runs, appears to work during testing) · **Likelihood:** HIGH (it WILL happen on first real wake cycle) · **Phase:** P5

---

### 3. launchd has no entitlement to `~/Library/Mobile Documents/` unless Full Disk Access is granted

**What goes wrong:**
macOS sandboxing applies TCC (Transparency, Consent, Control) to LaunchAgents. A LaunchAgent that reads/writes `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/` may silently fail with EPERM or return an empty directory listing, even though `ls` in Terminal works fine. The shell you're running in inherits Terminal.app's TCC grants; the LaunchAgent inherits... nothing by default on modern macOS (Sequoia and later are stricter still).

**Why it happens:**
TCC is per-executable. `/opt/homebrew/bin/claude` and `/usr/bin/python3` need their own Full Disk Access grants if they're going to write into iCloud paths from a launchd context. Terminal has the grant; launchd-invoked processes don't.

**How to avoid:**

- At install time, the install script MUST print instructions: "Open System Settings → Privacy & Security → Full Disk Access → add `/opt/homebrew/bin/claude` and `/usr/bin/python3`."
- The skill should **self-diagnose**: on startup, attempt to `stat()` the target Obsidian `Chats/` folder and if it returns EPERM, write a clear error to stderr (caught by `StandardErrorPath`) — don't mask as "no new chats."
- Consider the simpler workaround: install the plist under `~/Library/LaunchAgents/` but invoke it via `launchctl bootstrap gui/$(id -u)` in a context where the user has explicitly granted access. Document this in README.

**Warning signs:**

- Manual run writes files successfully; scheduled run produces no files and logs "Permission denied" or empty stat output.
- "It worked on MBP but not on Studio" — different TCC grants per machine.

**Severity:** CATASTROPHIC (skill silently does nothing) · **Likelihood:** MEDIUM-HIGH on Sequoia+ · **Phase:** P5 with loud self-diagnostic in P1

---

### 4. iCloud placeholder files: `os.stat()` on a not-yet-downloaded file gives wrong size and wrong content

**What goes wrong:**
When Mac A writes `mbp--2026-04-09--foo.md` to `Chats/`, Mac B's local filesystem shows it as a ~180-byte placeholder file with name `.mbp--2026-04-09--foo.md.icloud` (or, on Sonoma+, an opaque dataless file with the correct name but zero actual content in `read()`). If Mac B's skill lists `Chats/` looking for "existing files to avoid clobbering," it will see something that looks like a valid file but whose content cannot be read without triggering a download.

Modern macOS (Sonoma+) made this worse: the `.icloud` placeholder naming scheme is partially gone and replaced with dataless files that lie about their existence until first `open()`.

**Why it matters for this skill:**
The idempotence check "have I already written this session?" cannot rely on listing `Chats/` across machines — and the skill's design correctly avoids that by using a per-machine local `state.json`. Good. But **tools that help debug the state** (like "reconcile: list Chats/ and cross-check against state") will silently miss placeholders on the other machine's chats.

**How to avoid:**

- **Never read back files in `Chats/` on one machine to decide whether the other machine has synced.** Trust `state.json` only. This is already the design — preserve it.
- If a diagnostic command is added, it must detect placeholders before reading: check for `.*.icloud` sibling files, OR on Sonoma+ use `mdls -name kMDItemIsUbiquitous` / `NSMetadataUbiquitousItemDownloadingStatusKey` via a helper. Pure Python can't do this cleanly — shell out to `mdls` or `brctl monitor com.apple.CloudDocs` (deprecated but still functional on Sonoma).
- Never use `os.path.getsize()` as a completeness check on an iCloud file.

**Warning signs:**

- Diagnostic output shows "0 bytes" for files that are clearly non-empty on the other Mac.
- A debug script "sees" files but `cat` shows empty content until forced download.

**Severity:** BAD (diagnostic lies; main pipeline unaffected) · **Likelihood:** CERTAIN on any cross-machine inspection · **Phase:** P3 (vault writer) + P6 (any reconcile/diagnostic feature)

---

### 5. Two-Mac write collisions — the filename convention MUST contain the machine label, not just the session id

**What goes wrong:**
If file naming were `YYYY-MM-DD--<slug>.md`, two Macs generating slightly different slugs (or the same slug!) for different sessions on the same day would collide. iCloud's conflict resolution creates `foo (from mbp).md` copies that Obsidian sees as two separate notes, breaking any Dataview index built on stable filenames.

**Why it matters:**
The design already uses `<machine>--YYYY-MM-DD--<slug>.md`. Preserve this **religiously**. The moment anyone "simplifies" the filename by removing the machine prefix, this bug returns.

**How to avoid:**

- Filename generator is a single function (`build_filename(machine, date, slug)`) that requires machine as an argument. No default.
- Unit test: asserts two calls with different `machine` never produce the same filename even when date+slug collide.
- At write time, if the target filename already exists on disk (placeholder or real), refuse to overwrite and log to `needs_review` — never overwrite blindly.

**Warning signs:**

- iCloud generates `foo (from mbp).md` suffixes.
- Obsidian shows duplicate notes with parenthetical suffixes.
- Dataview queries return unexpected duplicates.

**Severity:** CATASTROPHIC (clobbers real chat content) · **Likelihood:** LOW if design preserved, CERTAIN if violated · **Phase:** P3

---

### 6. iCloud eventual-consistency delay: a file written from Mac A may take minutes-to-hours to appear on Mac B

**What goes wrong:**
iCloud Drive is not a filesystem; it's an eventually-consistent sync layer. Typical latency: seconds-to-minutes under good conditions, tens of minutes under bad ones, and indefinite if the user is offline. A chat written on MBP at 10:00 may land on Studio at 10:03 — or at 14:00 if MBP's lid was closed right after the write.

**Why it matters:**
Any workflow assumption like "write on A, verify on B" will fail flaky tests. More importantly, the MemPalace integration (one memory per chat) runs on the machine that did the export — and if the user queries MemPalace from the other machine before sync, the underlying chat file isn't there yet to link to.

**How to avoid:**

- MemPalace memories must NOT include absolute paths that assume the file is locally materialized. Use vault-relative paths (`Chats/mbp--2026-04-09--foo.md`) and document that Obsidian resolves them regardless of iCloud state.
- On the write side, after writing to `Chats/`, DO NOT then try to `read()` the file back as a verification step — iCloud may already be mid-upload and the local file handle is fine, but any trick that double-checks via a different path may race.
- Accept that "I just synced on MBP, it's not on Studio yet" is normal and not a bug. Document this in the skill's README.

**Warning signs:**

- MemPalace has memories whose referenced Chat file doesn't exist on the querying machine.
- Obsidian on Mac B shows an empty `Chats/` folder for 10+ minutes after a run on Mac A.

**Severity:** ANNOYING (eventually resolves) · **Likelihood:** CERTAIN · **Phase:** P4 (MCP integration) — document explicitly

---

### 7. `~/.claude-chat/state.json` lives in HOME, but HOME might be iCloud-synced via "Desktop & Documents"

**What goes wrong:**
The design says "state file is strictly local, never in iCloud." But if the user has enabled "Desktop & Documents in iCloud Drive," `~/Desktop` and `~/Documents` are iCloud-backed. `~/.claude-chat/` is a dotfile directory in `$HOME`, NOT under `~/Documents`, so it's safe by default. But:

- If the user ever moves the config for "neatness"
- If an installer helpfully puts it under `~/Documents/claude-chat/`
- If `$HOME` itself is ever symlinked through iCloud (rare but happens with some migration flows)

...then state.json is in iCloud and the two-Mac corruption bug fires.

**How to avoid:**

- Hardcode `Path.home() / ".claude-chat" / "state.json"`. Never accept a CLI flag to relocate it.
- At startup, resolve `state.json`'s real path and check if it contains `Mobile Documents` or `iCloud`. If it does, refuse to run with a loud error: "state.json appears to be in iCloud. This corrupts two-machine sync. Move to a non-iCloud path."
- Document explicitly in README: "Do NOT relocate `~/.claude-chat/` into iCloud. Ever."

**Warning signs:**

- Both Macs show identical `synced_session_ids` even though each Mac has different sessions in `~/.claude/projects/`.
- `state.json` shows `.icloud` placeholder sibling.

**Severity:** CATASTROPHIC (corrupts sync cursor; sessions skipped on both machines) · **Likelihood:** LOW but devastating · **Phase:** P1 (state design) with startup assertion

---

### 8. `state.json` is not crash-safe: mid-write crash leaves it empty or truncated, losing the entire sync cursor

**What goes wrong:**
If the skill writes state.json via the naive `open("w")` + `json.dump` pattern and the process is killed mid-write (kernel_task, low memory, user sleeps laptop), the file becomes zero bytes or JSON-invalid. Next run reads it, crashes on parse, user loses `last_sync_cursor` AND `synced_session_ids`. Next run now thinks every single session is new, re-exports them all, writes 500 new files to `Chats/`, writes 500 memories to MemPalace, and Obsidian has to reindex half a gigabyte.

**Why it happens:**
`claude-chat.py` already uses the atomic write pattern for `settings.json` (line 841-845, per CONCERNS.md). That pattern must be applied here too. It often isn't, because "it's just a state file."

**How to avoid:**

- **Atomic write pattern, always:** write to `state.json.tmp` in the same directory, `fsync()` before close, then `os.replace()` to the final name. This is POSIX-atomic on the same filesystem.
- **Keep a backup:** before `os.replace()`, copy the current `state.json` to `state.json.bak`. On next startup, if `state.json` is invalid, fall back to `.bak` with a warning.
- **Schema version field:** `{"schema_version": 1, "last_sync_cursor": ..., "synced_session_ids": [...]}`. On a schema bump, migrate or refuse gracefully.
- **Never re-export sessions listed in `synced_session_ids` even if the file has been deleted from `Chats/`.** This prevents the "reindex storm" scenario if the user manually deletes files.

**Warning signs:**

- Startup log: "state.json parse error" or "state.json is empty."
- Unexpectedly large run count after a crash: "Exported 287 sessions" (should be 1-2).

**Severity:** BAD (recoverable but noisy; could double-write to MemPalace) · **Likelihood:** MEDIUM · **Phase:** P1

---

### 9. User manually deletes a file from `Chats/` → next run re-creates it → user deletes it again → infinite loop

**What goes wrong:**
User opens Obsidian, sees a chat they don't want archived (maybe it's trivial, maybe it leaked something), deletes the file. Next run sees `session_id` in `synced_session_ids`... OR DOESN'T, depending on implementation. If the skill lists `Chats/` and cross-references, the deleted file looks "missing" and gets re-created. The user deletes it again. The skill re-creates it again. Forever.

**Why it happens:**
Developers conflate "is this session synced?" with "does the file for this session exist on disk?" These are different questions. The first is answered by `state.json`; the second is answered by `os.path.exists()`. Only the first matters for idempotence.

**How to avoid:**

- **`synced_session_ids` is the ONLY source of truth for "have I handled this session?"** Never re-derive it from disk.
- Once a session_id is added to `synced_session_ids`, it stays there forever. Deletion of the Obsidian file does not remove it.
- Provide a separate `/sync-chats --forget <session_id>` escape hatch for the rare case the user really wants a session re-exported.

**Warning signs:**

- User reports "I deleted that chat and it came back."
- `Chats/` file count doesn't match user's expectation even though the skill "worked."

**Severity:** BAD (user loses control) · **Likelihood:** MEDIUM (it will happen the first time a user prunes) · **Phase:** P1

---

### 10. PII scrub runs AFTER labeling → title and gist leak scrubbed content into frontmatter

**What goes wrong:**
Pipeline A (WRONG):
`session → Claude labels it (sees raw content) → Claude returns title+gist+tags → write markdown → protect pass on body → commit to vault`

Claude saw the raw session. If the raw session contained "patient MRN 12345678 on protocol CORP-330-study-5," the title might be "Dosing for MRN 12345678" and the gist might mention the protocol code. The body gets scrubbed by `protect`, but **frontmatter is not scrubbed**. The title and tags sail through unscrubbed into an iCloud-synced vault.

This is the single worst possible bug. The user works in clinical research at a pharmaceutical company. Frontmatter PII leakage is a HIPAA-adjacent event with potential regulatory consequences.

Pipeline B (CORRECT):
`session → protect pass on body (in-memory) → Claude labels scrubbed content → write frontmatter + scrubbed body to vault`

**Why it happens:**
Developers think of `protect` as "the last step before writing" because it's the last thing `claude-chat.py export` does today. They don't think about the fact that the labeling LLM also needs scrubbed input.

**How to avoid:**

- **Scrub FIRST. Label SECOND. Write THIRD.** Non-negotiable ordering.
- Implement the pipeline as three explicit stages with names: `scrub_session() → label_scrubbed() → write_markdown()`. Comment above each: "IMPORTANT: labeling must see only scrubbed input."
- Unit test: feed in a session containing a known canary string (`CANARY-HIPAA-42`); assert that the canary appears nowhere in frontmatter, body, tags, filename, OR state.json, OR MemPalace memory content.
- Re-run the scrub over the FINAL written markdown file as a paranoid second pass. Yes, this is redundant. Yes, do it anyway. This is a belt-and-suspenders scenario for a file that WILL reach iCloud and potentially a second machine.
- The MemPalace memory content ALSO must be generated from scrubbed input, not raw.

**Warning signs:**

- Any test where a known PII string appears in any output field.
- Titles that mention specific identifiers, dates of birth, drug doses, or URLs.

**Severity:** CATASTROPHIC (regulatory + privacy harm) · **Likelihood:** HIGH if ordering wrong · **Phase:** P2 — this is the architectural decision that defines phase 2

---

### 11. Regex-based PII scrubbing misses clinical/research identifiers it was never taught

**What goes wrong:**
`claude-chat.py protect` (per CONCERNS.md and user's note about lines 1170-1356) is a template-based regex scrubber. Regexes are famously bad at:

- Patient names (no regex can find "John" is a name when "John" is also a common English word)
- Protocol codes in novel formats (`CORP-330-5`, `NCT04123456`, `2024-503891-22-00` EU CT number, `JMA-IIA00456` Japanese trial ID, `CTR20200567` China)
- Drug doses in running prose ("15 mg/kg q2w")
- Internal corporate URLs (`internal.example.com/foo`, `corp.sharepoint.com/...`)
- Slack workspace/channel IDs (`T0123ABCD`, `C0456EFGH`)
- GitHub personal access tokens that don't match the `ghp_` prefix (classic tokens don't)
- JWT tokens inline in chat logs
- AWS access keys that were pasted in non-standard format
- MRNs that are just 8-12 digits (regex will either miss them or flag every phone number)

The user's professional context is exactly the worst case for regex scrubbers: clinical + multi-jurisdictional regulatory + industry side-projects + credentials.

**How to avoid:**

- **Audit the existing `TEMPLATES`** (claude-chat.py lines 1170-1356) and add categories: NCT IDs, EU CT numbers, Japan/China protocol IDs, employer-specific URL patterns, common drug-dose patterns, JWT regex, `gho_`/`ghu_`/`ghs_` token prefixes beyond `ghp_`, AWS `AKIA`/`ASIA` prefixes, Slack `T[A-Z0-9]{8}`/`C[A-Z0-9]{8}`.
- **Add a canary-word mode:** user can populate `~/.claude-chat/canaries.txt` with literal strings that must never appear in output (patient first names, protocol codenames, family member names). Scrubber checks for these before writing.
- **Second-pass LLM scrub:** after regex scrub + labeling, send the final content to Claude with a prompt "Return any PII you see in this content. Do not fix it, just list it." If the response is non-empty, set `needs_review: true` and mark the file with a `pii_flagged:` frontmatter field. Never block the write — the goal is to flag, not gate.
- **Fail-closed default:** if the scrubber encounters an ambiguous match (e.g., "looks like an MRN but could be an order number"), mark the file `needs_review: true` and include a warning in frontmatter. Do NOT refuse the write — refusal turns the skill into a silent lossy bucket. Write + flag.
- **Document explicitly that the scrubber is not sufficient for clinical data without user review.** The skill's `needs_review: true` default (which the user already plans via Dataview inbox) is the right mechanism.

**Warning signs:**

- Manual spot-check of any synced chat shows unscrubbed content.
- Canary file triggers zero hits on known-PII-containing historical sessions (false negative).

**Severity:** CATASTROPHIC · **Likelihood:** CERTAIN at baseline; MEDIUM with canary + second-pass · **Phase:** P2

---

### 12. Claude refuses to summarize clinical content → skill produces an untitled file

**What goes wrong:**
The user's sessions contain real clinical/medical reasoning. Claude's safety layer may respond to a summarization prompt with "I can't provide medical advice / summarize patient information" — especially if the scrubbed content still reads medical. The skill gets back a refusal instead of a title, and either crashes, writes an empty title, or writes the refusal text as the title ("I can't help with that").

**How to avoid:**

- **Prompt framing:** tell Claude it's labeling a development-log conversation, not clinical records. Example: "You are titling an entry in a developer's personal knowledge vault. The content may mention medical or scientific topics because the user is a clinical researcher who uses Claude Code for data analysis. Generate a terse descriptive title of the **conversation topic**, not a medical summary."
- **Refusal detection:** post-process the title. If it starts with "I can't", "I'm unable", "I'm sorry", or is empty, fall back to: `title = f"Untitled session {session.short_id}"`, set `needs_review: true`, add `label_refused: true` to frontmatter. Never crash.
- **Tag fallback:** same treatment for tags — if refused or empty, use `["unlabeled"]` and flag for review.

**Warning signs:**

- `Chats/` contains files with titles like "I can't help with that" or "Sorry, I cannot".
- Dataview inbox swells with `needs_review: true` files on days with heavy clinical content.

**Severity:** ANNOYING (files still written, just with bad titles) · **Likelihood:** MEDIUM · **Phase:** P2

---

### 13. Context-length overflow on 300k-token sessions during labeling

**What goes wrong:**
Claude Code power users have chats that span hours and include thousands of tool-call results, diffs, and paste-dumps. Feeding the entire transcript to a "write me a title" prompt will either blow the context window or cost a ton of tokens for no benefit.

**How to avoid:**

- **Summarize the summary:** extract the first user message (often the problem statement), the last user message, and the last assistant message. That triplet gives Claude enough context to title 95% of sessions without the middle.
- **Token-cap the feed:** hard cap at ~8k tokens of scrubbed content fed to the labeler. If the session is larger, sample: first 2k, middle 2k, last 4k.
- **`claude-chat.py extract` already exists** — reuse its code-blocks / ideas / decisions extraction to build a compact summary instead of raw transcript.
- Store the model's reported `token_count` in frontmatter so the user can spot outliers later.

**Warning signs:**

- Labeling step fails with context-length errors on long sessions.
- Labeling costs balloon unexpectedly.

**Severity:** ANNOYING · **Likelihood:** MEDIUM · **Phase:** P2

---

### 14. Tag vocabulary never converges — every run invents new tags for the same topic

**What goes wrong:**
First run: `["python", "debugging", "claude-chat"]`. Second run on a similar session: `["Python", "bug-fix", "cli-tool"]`. Dataview can't group these; the tag graph is noise. The user loses the ability to find "all Python debugging sessions" because there are 14 slightly different tags.

**How to avoid:**

- **Tag vocabulary file:** `~/.claude-chat/tag-vocabulary.txt` lists canonical tags the labeler is allowed to choose from. On each labeling call, the prompt includes: "Choose 3-5 tags from this list. If none fit, propose one new tag and mark it `(new)`."
- **New-tag review:** tags marked `(new)` are written with `tag_review: true` in frontmatter. User approves in Obsidian; approved tags get added to the vocabulary file on next run.
- **Lowercase, kebab-case, singular:** enforce in post-processing (`"Python"` → `"python"`; `"bug-fixes"` → `"bug-fix"`). Cheap deterministic normalization catches 80% of drift.
- **Seed vocabulary early:** start with ~30 tags that match the user's known domains (`python`, `obsidian`, `launchd`, `homelab`, `terraform`, `clinical-research`, `regulatory`, `blog`, `ios`, `macos`, `sql`, `analysis`, `debug`, `refactor`, `docs`).

**Warning signs:**

- Obsidian tag pane shows dozens of near-duplicate tags.
- Dataview queries by tag return far fewer results than expected.

**Severity:** ANNOYING (UX degradation, recoverable) · **Likelihood:** HIGH without intervention · **Phase:** P2

---

### 15. Title format drifts between runs — same session gets different titles on re-runs (if re-runs ever happen)

**What goes wrong:**
Run on day 1: `"Fix RSS feed parser bug"`. Re-run same session day 2 (because user `--force`d): `"Fixing the RSS Feed Parser Bug (2026)"`. User now has two files for one conversation.

**Why it mostly doesn't matter for this design:**
The skill is **explicitly non-reregenerating** (per PROJECT.md Out of Scope: "Mid-conversation re-titling / retroactive label regeneration"). As long as this invariant holds, drift between runs is impossible because there's only ever one run per session.

**How to avoid regression:**

- Never add a `--relabel` or `--force-regenerate` flag without heavy warnings and an explicit allowlist of session IDs.
- If the user DOES need to re-label (rare), delete the state entry AND the vault file as one atomic operation, then re-run.
- Unit test: assert that running the skill twice in a row produces zero changes on the second run.

**Severity:** BAD if invariant broken · **Likelihood:** LOW (design prevents it) · **Phase:** P1 (preserve invariant)

---

### 16. MemPalace MCP server not running → skill crashes OR silently skips memory step

**What goes wrong:**
The MemPalace MCP server is a separate process. It may not be running at wake time (launchd race), may be in an error state, may time out, may rate-limit if fed 50 memories in one coalesced catch-up run.

**How to avoid:**

- **Graceful degradation:** if MCP tool invocation fails, write the chat to the vault anyway (primary goal A is the vault; MemPalace is goal B). Add `memory_synced: false` to frontmatter; include `memory_error: "<error>"`.
- **Retry queue:** failed memories go into `~/.claude-chat/memory-queue.jsonl`. Next successful run drains the queue before processing new chats.
- **Rate-limit self-throttle:** after each MemPalace call, sleep 200ms. Fifty memories → 10 seconds of sleep, invisible to user, prevents hammering.
- **Duplicate detection:** check with `mempalace_check_duplicate` (or whatever the tool is called) before `mempalace_kg_add`. If the memory already exists (e.g., because a previous run crashed after MemPalace add but before state.json update), skip. This is the MCP-side idempotence story.
- **State ordering:** update `state.json` AFTER successful MemPalace write, not before. If MemPalace fails, the next run retries. If MemPalace succeeds and state.json crash-writes, the retry hits duplicate detection.

**Warning signs:**

- `Chats/` fills up but MemPalace query returns no matches.
- MemPalace error log shows rate-limit or duplicate-key errors.

**Severity:** BAD (goal B degraded, goal A intact) · **Likelihood:** MEDIUM · **Phase:** P4

---

### 17. THE BIG ONE: user edits title in Obsidian, next run clobbers the edit

**What goes wrong:**
Skill writes `mbp--2026-04-09--fix-rss.md` with auto title "Fix RSS feed parser." User opens in Obsidian, rewrites the title to "Debug Tyndall RSS encoding crash — turned out to be UTF-16 BOM." Next run somehow re-processes the session (crash recovery, forgotten state, whatever) and overwrites the file. User's hand-curated title is gone. This is the worst recoverable bug because the user's trust in the skill evaporates on first occurrence.

**Why it happens:**
Developers write idempotent skills by re-running the whole pipeline and writing the same file contents. This is wrong when the file is user-editable. The correct model is **write-once; never touch again**.

**Recommended strategy — ranked by the researcher:**

1. **Primary defense (REQUIRED): `synced_session_ids` in state.json is the authoritative "already handled" set.** Any session_id in this set is never re-processed. Full stop. This alone prevents clobbering in 99% of cases.

2. **Secondary defense (REQUIRED): refuse-on-exists.** Before writing a file in `Chats/`, check if the target filename already exists on disk. If it does, do NOT overwrite — log "skipping, file already exists" and add session_id to `synced_session_ids` to prevent retry loops. This catches the case where state.json was lost but the file survived.

3. **Tertiary defense (RECOMMENDED): content-hash sentinel in frontmatter.** Write `auto_label_hash: <sha256 of original generated title+gist>` at creation time. On any future re-examination, if the current file's title no longer matches this hash, the user has edited it — treat as sacred, never touch.

4. **NOT recommended: `needs_review: false` as a hands-off flag.** Too implicit. The user may flip it without intending "never touch again," and conversely the flag will be `true` on new files the user hasn't touched yet — the skill would treat brand-new un-reviewed files as "free to overwrite" and then fail to catch its own output after a state wipe.

5. **NOT recommended: re-reading the old file, diffing with the new, merging.** Too clever. Merge logic is where this class of tool goes to die. Write-once is the only safe contract.

**Combine defenses 1+2+3.** State.json is primary. File-exists check is backup. Content hash is the "I really mean it" belt-and-suspenders for the rare state wipe + manual resurrection scenario.

**Warning signs:**

- User reports "my title got overwritten."
- File modification timestamp in `Chats/` is more recent than file was last edited in Obsidian.
- Any log line containing "overwriting existing file."

**Severity:** CATASTROPHIC (trust destruction; user abandons skill) · **Likelihood:** CERTAIN without explicit defense · **Phase:** P3 — this is THE phase-3 requirement

---

### 18. Obsidian's file watcher reloads mid-write → shows half-written file

**What goes wrong:**
Obsidian watches the vault and reloads on change. If the skill writes the file with streaming I/O (`for chunk in ...: f.write(chunk)`), Obsidian may notice the file at the 30% point, open it in the editor, and display a broken half-file. User panics.

**How to avoid:**

- **Atomic write:** write the full markdown content to `.tmp` in the same directory, then `os.replace()`. Obsidian sees the file appear fully-formed in one event.
- **Never use append mode** for files in the vault.
- `os.replace()` within the same directory is POSIX-atomic; iCloud treats the rename correctly.

**Warning signs:**

- User sees "File was modified externally" warnings in Obsidian.
- Obsidian shows incomplete frontmatter or truncated body.

**Severity:** ANNOYING · **Likelihood:** LOW if atomic write used · **Phase:** P3

---

### 19. Filename characters that macOS or Obsidian reject

**What goes wrong:**
Session titles may contain `:`, `/`, `\`, `|`, `?`, `*`, `<`, `>`, `"`, leading dots, trailing spaces, NUL bytes from weird tool output, or Unicode that normalizes differently between HFS+/APFS and iCloud. The slug from "What's going on with ACME's Q4 report?" could fail in 3 different places.

**How to avoid:**

- **Slug sanitizer:** `[^a-z0-9-]` → `-`; collapse runs of `-`; strip leading/trailing `-`; lowercase; truncate to 60 chars; ensure result is non-empty (fallback to session short_id).
- **NFC normalize** the slug (`unicodedata.normalize('NFC', s)`) to avoid HFS+/APFS + iCloud round-trip issues with decomposed characters.
- Reject reserved names: `.`, `..`, `CON`, `NUL`, `PRN` (unlikely but cheap).
- **Unit test** with adversarial inputs: session titles containing slashes, emoji, Chinese characters, zero-width joiners.

**Severity:** BAD (write fails, session skipped) · **Likelihood:** MEDIUM · **Phase:** P3

---

### 20. Dataview frontmatter parsing is strict — one malformed field breaks the whole file's queryability

**What goes wrong:**
Dataview parses YAML frontmatter. A stray unescaped `:` in an AI-generated gist, an unquoted string starting with `@`, or a multi-line gist without proper YAML block style will fail YAML parsing. The file is still readable in Obsidian but invisible to Dataview queries. User's "inbox" (`WHERE needs_review`) silently excludes broken files.

**How to avoid:**

- **Always quote string values** in YAML frontmatter: `title: "Fix RSS parser"` not `title: Fix RSS parser`. Cheap and bulletproof.
- **Multi-line gist:** use YAML block scalar `gist: |-` or better, keep the gist on one line and enforce a length limit.
- **Escape embedded quotes** in values.
- **Use a YAML library** — Python stdlib has no `yaml` (external dep), but you can get away with a tiny hand-rolled writer that only emits quoted scalars, lists, and flat maps. Don't try to pretty-print.
- **Round-trip test:** write a test vault file, parse it with a YAML validator (e.g., `python3 -c "import yaml; yaml.safe_load(open('x.md').read().split('---')[1])"` using PyYAML in a dev-only context), assert success on 1000 random-fuzzed inputs.

**Warning signs:**

- Dataview query returns fewer files than `ls Chats/ | wc -l`.
- Obsidian shows "Invalid YAML" indicator on certain files.

**Severity:** BAD (files effectively lost to user's index) · **Likelihood:** MEDIUM-HIGH without careful YAML emission · **Phase:** P3

---

## Technical Debt Patterns

| Shortcut                                                | Immediate Benefit                        | Long-term Cost                                                                                | When Acceptable                                                         |
| ------------------------------------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Skip atomic writes for state.json ("it's just a cache") | 10 fewer lines of code                   | Crash-mid-write corrupts cursor, triggers re-export storm, writes duplicate MemPalace entries | NEVER                                                                   |
| Hardcode paths to `claude` CLI in the plist             | Install script works on tester's machine | Breaks on any Mac with different Homebrew prefix (Intel vs Apple Silicon)                     | Install-time detection acceptable; hardcoding in committed plist is not |
| Parse YAML frontmatter by hand (no quoting)             | No external dep                          | Will break on first title with a `:` in it                                                    | NEVER — quote everything                                                |
| Skip the canary/second-pass PII check to save tokens    | Faster runs                              | Clinical PII lands in iCloud vault and propagates to second Mac                               | NEVER in P2; could defer to P6 with loud `needs_review: true` default   |
| `print()` for logs                                      | Zero setup                               | Launchd discards stdout unless `StandardOutPath` set; debugging blind                         | Acceptable during P1 dev; must wire `StandardOutPath` by P5             |
| One giant prompt for title+gist+tags in one LLM call    | Fewer API calls                          | Refusal on one field kills all three; no per-field fallback                                   | Acceptable with good fallbacks; split if refusal rate > 5%              |
| Ignore `needs_review: true` as a hands-off marker       | Simpler logic                            | Ambiguous semantics; flag means both "unreviewed" and "overwritable"                          | NEVER use for clobber prevention (see pitfall #17)                      |

---

## Integration Gotchas

| Integration            | Common Mistake                                                  | Correct Approach                                                                    |
| ---------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| launchd                | Use relative `claude` in `ProgramArguments`                     | Absolute path + explicit `EnvironmentVariables` with `PATH`                         |
| launchd                | Test with `launchctl kickstart`, ship without `StandardOutPath` | Always set `StandardOutPath`/`StandardErrorPath` so failures are visible            |
| launchd                | Assume `StartInterval` re-fires each missed hour                | Know it coalesces to one run; design delta-sync to handle any backlog size          |
| iCloud Drive           | Use `os.stat()` to check completeness                           | Don't; accept eventual consistency; never cross-check across machines               |
| iCloud Drive           | Put state.json in `~/Documents/`                                | Keep in `~/.claude-chat/`; assert at startup that it's not in `Mobile Documents`    |
| Obsidian               | Write markdown directly with `open("w")`                        | Write to `.tmp` in same dir, `os.replace()` — prevents mid-write reload             |
| Obsidian frontmatter   | Unquoted YAML strings                                           | Quote everything; multi-line via block scalar or length-limit single-line           |
| MemPalace MCP          | Assume the server is up                                         | Try/except around every MCP call; retry queue for failures                          |
| MemPalace MCP          | Add without dedupe check                                        | Check duplicate first, OR make add idempotent on session_id key                     |
| Claude CLI (labeling)  | Feed raw session contents                                       | Feed SCRUBBED contents only; labeling is downstream of `protect`                    |
| TCC / Full Disk Access | Ship plist without FDA grant instructions                       | Install script must print the FDA grant instructions; skill self-diagnoses on EPERM |

---

## Performance Traps

| Trap                                                           | Symptoms                                                  | Prevention                                                                                           | When it breaks                  |
| -------------------------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------- |
| Re-reading every session every run (no delta sync)             | Hourly runs scan 1000+ files; I/O cost grows with history | Maintain `last_sync_cursor` + `synced_session_ids`; stat-only scan; full parse only for new sessions | ~200 sessions in                |
| Labeling LLM call on full transcripts                          | Token cost; context-length errors                         | Token-cap; sample first/middle/last; reuse `extract` output                                          | First session over ~100k tokens |
| Sync MemPalace calls one-by-one with no batching or throttling | Rate limits on catch-up runs                              | 200ms throttle; retry queue; consider batch API if MemPalace offers                                  | 20+ memories per run            |
| Listing `Chats/` and reading every file to rebuild state       | Scans grow with archive size                              | Never rebuild state from disk; state.json is authoritative                                           | 500 files in                    |
| Loading full session file into memory for scrubbing            | OOM on very large sessions                                | Stream the scrub line-by-line (matches existing claude-chat.py concern #7)                           | Sessions > 100MB                |

---

## Security Mistakes

| Mistake                                                                     | Risk                                                      | Prevention                                                                                    |
| --------------------------------------------------------------------------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Label before scrub → title/tags contain PII                                 | HIPAA-adjacent disclosure in iCloud + second machine      | Scrub first, label second, write third — with unit test canary (#10)                          |
| `protect` regex alone sufficient for clinical data                          | Patient names, protocol codes, internal URLs leak         | Augment templates + canary file + second-pass LLM review + `needs_review: true` default (#11) |
| state.json logs raw session content                                         | Disk-local PII retention                                  | state.json stores only IDs, timestamps, hashes — never content or titles                      |
| MemPalace memory contains raw scrubbed body                                 | Memory may propagate to other LLM contexts                | Generate memory from scrubbed-labeled version only; never raw                                 |
| launchd log files in iCloud path                                            | Logs may contain error messages quoting raw session lines | Logs stay in `~/.claude-chat/logs/`, NOT in vault, NOT in iCloud                              |
| `StandardErrorPath` captures scrubber warnings including the matched string | Logs leak exactly what you tried to hide                  | Scrubber log messages report only pattern name + char count, never the matched substring      |
| `~/.claude-chat/canaries.txt` itself is sensitive                           | Contains literal names / identifiers to protect           | `chmod 600`; document not to sync; assert not in iCloud on startup                            |
| Web-search or WebFetch fallbacks in the labeling prompt                     | Could exfiltrate content to a third party                 | Labeling prompt must not invoke tools — plain completion only                                 |

---

## UX Pitfalls

| Pitfall                                                       | User impact                                      | Better approach                                                                                      |
| ------------------------------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| Skill fails silently when launchd can't find `claude`         | User thinks it's working; weeks of chats missing | `StandardErrorPath` + manual-run diagnostic command (`/sync-chats --doctor`)                         |
| Every new tag added to vocabulary without approval            | Tag graph becomes noise                          | `(new)` suffix + `tag_review: true` + user-approves-to-vocabulary flow (#14)                         |
| `needs_review: true` on every file by default                 | Inbox feels like homework                        | Accept it — this is the point; Dataview query makes it a passive workspace                           |
| First-run processes 1000 historical sessions and floods vault | Obsidian freezes during reindex; user panics     | `--initial-batch-size N` flag; default to "today only" on first install; explicit opt-in to backfill |
| No "show me what you'd do" dry-run mode                       | User can't verify before writing to iCloud       | `/sync-chats --dry-run` that logs planned writes but touches nothing                                 |
| User can't tell which Mac a chat came from                    | Which of two machines? Which launchd run?        | Machine prefix in filename + `hostname:` frontmatter field                                           |

---

## "Looks Done But Isn't" Checklist

- [ ] **Delta scanner:** processes only new sessions — but does it handle the "state wiped / fresh install / 500 historical sessions" case without flooding? Verify with a mocked empty state + real sessions dir.
- [ ] **launchd plist:** loads and runs manually — but does it run on ACTUAL wake-from-sleep? Only a real overnight test confirms.
- [ ] **PII scrub pipeline:** scrubs known patterns — but does the label come from SCRUBBED content, not raw? Verify with canary test.
- [ ] **Atomic write:** uses `os.replace()` — but is the `.tmp` in the same directory as target? Different fs → not atomic.
- [ ] **state.json recovery:** handles invalid JSON on load — but does it recover gracefully, or crash? Test by `echo "garbage" > state.json` and running.
- [ ] **Obsidian filename:** avoids `/` and `:` — but does it handle emoji, NFC/NFD, 500-char titles, empty slugs?
- [ ] **MemPalace integration:** writes a memory per chat — but does it handle MCP server not running? Handle duplicate detection? Handle mid-run failure?
- [ ] **Cross-machine:** runs on both Macs — but do the two Macs actually have disjoint `~/.claude/projects/`? Verify via `diff <(ls mbp:~/.claude/projects) <(ls studio:~/.claude/projects)`.
- [ ] **Dataview query:** `WHERE needs_review` returns the inbox — but does every file have valid YAML frontmatter? Test with a YAML linter over all vault files.
- [ ] **Clobber protection:** re-running does nothing — but does re-running AFTER STATE.JSON DELETION re-process and overwrite user edits? Test this explicitly (pitfall #17).
- [ ] **Full Disk Access:** manual run works — but does it work when INVOKED BY LAUNCHD after a cold wake, which has different TCC context?
- [ ] **Long session handling:** labels 50k token sessions — but does it handle 500k token sessions without context overflow?

---

## Recovery Strategies

| Pitfall                                                           | Recovery cost        | Recovery steps                                                                                                                                                                                                                   |
| ----------------------------------------------------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| state.json corrupted (pitfall #8)                                 | LOW                  | Fall back to `state.json.bak`; if that fails, recompute `synced_session_ids` from existing `Chats/` filenames by extracting session_ids from frontmatter                                                                         |
| User deleted vault file, skill re-creates it (pitfall #9)         | LOW                  | Add `--forget <session_id>` command; document the pattern                                                                                                                                                                        |
| PII leaked to frontmatter of already-synced file (pitfall #10/11) | HIGH                 | Requires: (a) scrub fix, (b) audit all existing vault files, (c) manually re-scrub frontmatter, (d) if propagated to MemPalace, remove affected memories, (e) iCloud has already replicated to other Mac — must delete from both |
| Filename collision with `foo (from mbp).md` conflict copy         | MEDIUM               | Merge by hand in Obsidian; keep the machine-prefixed one; delete conflict copy; never reproduce                                                                                                                                  |
| MemPalace out of sync with vault                                  | LOW                  | Reconciliation tool: iterate vault, for each file check MemPalace for matching session_id, add if missing                                                                                                                        |
| User's hand-edited title clobbered (pitfall #17)                  | HIGH — trust damage  | Apologize; restore from iCloud version history if within 30 days (iCloud keeps ~30 days of versions); add the triple-defense from pitfall #17 before user returns                                                                |
| launchd runs but skill silently fails (pitfall #2/3)              | LOW (once diagnosed) | Run `/sync-chats --doctor` to dump: absolute claude path, PATH, TCC status, network reachability, state.json validity                                                                                                            |
| Initial catch-up storm writes 500 files                           | MEDIUM               | Never runs again after first pass; user reindexes Obsidian once; avoid by `--initial-batch-size` default                                                                                                                         |
| Claude labeling refused on a clinical session                     | LOW                  | `needs_review: true` flag + fallback title; user edits in Obsidian                                                                                                                                                               |
| Unknown PII category leaked (pitfall #11)                         | HIGH                 | Same as #10/11 recovery; add to canary file; rescrub                                                                                                                                                                             |

---

## Pitfall-to-Phase Mapping

Phase legend (aligned with expected roadmap):

- **P1** Skeleton: state machine, delta scanner, CLI shell
- **P2** Labeling & scrub pipeline (scrub-first architecture)
- **P3** Vault writer: filename, atomic write, frontmatter, clobber defense
- **P4** MemPalace MCP integration
- **P5** launchd install + multi-machine
- **P6** Hardening, diagnostics, canary/second-pass scrub

| #   | Pitfall                                    | Severity                  | Prevention phase        | Verification                                                     |
| --- | ------------------------------------------ | ------------------------- | ----------------------- | ---------------------------------------------------------------- |
| 1   | launchd coalesces missed intervals         | BAD                       | P1 design + P5 install  | Test: 20 new sessions, one run, all landed                       |
| 2   | No network / no PATH on wake               | CATASTROPHIC              | P5                      | Overnight real test; `StandardErrorPath` log review              |
| 3   | TCC Full Disk Access missing               | CATASTROPHIC              | P5                      | `/sync-chats --doctor` self-diagnostic                           |
| 4   | iCloud placeholder files lie               | BAD                       | P3 + P6                 | Cross-machine inspection test                                    |
| 5   | Filename collision without machine prefix  | CATASTROPHIC              | P3                      | Unit test asserting machine prefix mandatory                     |
| 6   | iCloud eventual-consistency delay          | ANNOYING                  | P4 (documentation)      | N/A — document only                                              |
| 7   | state.json accidentally in iCloud          | CATASTROPHIC              | P1                      | Startup assertion refuses to run                                 |
| 8   | state.json crash-write corruption          | BAD                       | P1                      | Kill-during-write test                                           |
| 9   | User deletes vault file → re-creation loop | BAD                       | P1                      | Delete-and-run test; `--forget` command                          |
| 10  | PII scrub ordered after labeling           | CATASTROPHIC              | P2                      | Canary unit test (`CANARY-HIPAA-42`)                             |
| 11  | Regex scrubber misses clinical PII         | CATASTROPHIC              | P2 + P6                 | Canary file; second-pass LLM scrub; `needs_review: true` default |
| 12  | Claude refuses to label clinical content   | ANNOYING                  | P2                      | Refusal-detection post-process; fallback title                   |
| 13  | Context overflow on long sessions          | ANNOYING                  | P2                      | Token cap; sampling strategy                                     |
| 14  | Tag vocabulary drift                       | ANNOYING                  | P2                      | Vocabulary file; new-tag review                                  |
| 15  | Title format drift                         | BAD (if invariant broken) | P1 (preserve invariant) | Re-run test: zero changes                                        |
| 16  | MemPalace MCP unavailable                  | BAD                       | P4                      | Graceful degradation; retry queue; doctor command                |
| 17  | **Clobber user's manual title edits**      | **CATASTROPHIC**          | **P3**                  | Edit-then-rerun test; state-wipe-then-rerun test                 |
| 18  | Obsidian sees mid-write file               | ANNOYING                  | P3                      | Atomic write via `.tmp` + `os.replace()`                         |
| 19  | Filename character issues                  | BAD                       | P3                      | Adversarial slug unit tests                                      |
| 20  | Dataview YAML parsing fails                | BAD                       | P3                      | Round-trip YAML validation test over fuzzed inputs               |

---

## Sources

- Apple Developer Forums — [launchd StartInterval and sleep behavior](https://developer.apple.com/forums/thread/52369) — confirms coalescing of missed intervals on wake (HIGH confidence)
- launchd-dev mailing list — [launchd StartInterval and sleep](https://launchd-dev.macosforge.narkive.com/ZF2IQriC/launchd-startinterval-and-sleep) — corroborates coalescing behavior (HIGH)
- [launchd.info tutorial](https://www.launchd.info/) — environment, KeepAlive, network state (HIGH)
- Slogger — [launchd fails when running after Wake (GitHub issue #23)](https://github.com/ttscoff/Slogger/issues/23) — real-world wake-without-network failure (HIGH)
- Apple Developer Forums — [Daemon & Network Availability](https://launchd-dev.macosforge.narkive.com/yc6oIdbJ/daemon-network-availability) — DNS-not-ready on wake (HIGH)
- Fatbobman — [Advanced iCloud Documents: placeholder files and download status](https://fatbobman.com/en/posts/advanced-icloud-documents/) — `NSMetadataUbiquitousItemPercentDownloadedKey`, placeholder detection (HIGH)
- The Eclectic Light Company — [macOS Sonoma has changed iCloud Drive radically](https://eclecticlight.co/2023/10/25/macos-sonoma-has-changed-icloud-drive-radically/) — modern placeholder semantics and `brctl` status (MEDIUM)
- Carlo Zottmann — [iOS iCloud Drive Synchronization Deep Dive](https://zottmann.org/2025/09/08/ios-icloud-drive-synchronization-deep.html) — eventual-consistency latency characteristics (MEDIUM)
- `.planning/codebase/CONCERNS.md` — existing `claude-chat.py` atomic-write pattern (line 841-845) is the blueprint for state.json write safety (HIGH — inspected directly)
- `.planning/codebase/INTEGRATIONS.md` — confirms no prior network/cloud integration; iCloud writes are a new surface for this codebase (HIGH — inspected directly)
- User context (personal CLAUDE.md) — clinical research at a pharmaceutical company + multi-jurisdictional regulatory work — drives the PII catastrophic-severity weighting (HIGH)
- MCP and LLM-labeling pitfalls (#12, #13, #14, #15, #16) are drawn from general LLM engineering practice and should be validated against MemPalace MCP's actual tool surface in P4 research (LOW-MEDIUM until verified against real MCP docs)

---

_Pitfalls research for: `/sync-chats` Claude Code skill_
_Researched: 2026-04-10_
_Author note: Pitfall #17 (user-edit clobber) and pitfall #10 (scrub-ordering) are the two that would ruin the project if shipped wrong. Everything else can be fixed in a patch release. Those two cannot._
