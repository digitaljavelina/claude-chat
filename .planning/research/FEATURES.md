# Feature Research — `/sync-chats` Skill

**Domain:** Claude Code session archival + Obsidian knowledge-base curation (+ MemPalace feeding)
**Researched:** 2026-04-10
**Confidence:** HIGH for prior-art landscape and table-stakes; MEDIUM for AI-labeling conventions (mostly derived from community practice rather than formal studies); HIGH for anti-features (user has already rejected several common patterns explicitly).

---

## Executive Summary

The "Claude Code sessions into Obsidian" space is already crowded with half-solutions. Every competitor solves one or two pieces of the problem and punts on the rest:

- **`claude-code-log`** (daaain) — pretty HTML output, lazy about deltas, no AI labels, no vault integration.
- **`claude-conversation-extractor`** (ZeroSumQuant) — raw export only; no titling, no tagging, no frontmatter.
- **`cctrace`** (jimmc414) — markdown + XML export for archival; no curation layer.
- **`claude-logging`** (antocuni) — HTML dumps; append-only.
- **`claude-vault`** (MarioPadilla) — the closest competitor. Does AI tags/summaries via local Ollama, has PII detection with redact/skip/tag modes, UUID-tracked bidirectional sync. **But** it explicitly punts on multi-machine sync ("requires manual coordination"), does full rescans rather than delta-sync, and depends on a separate Ollama service being up.
- **`Nexus AI Chat Importer`** (Obsidian plugin) — uses the conversation's original title as filename, zero AI labeling, date-based folder hierarchy, no tags.
- **Claude Code native "Session Memory"** (2025+) — extracts summaries every ~10k tokens to disk, but it's ephemeral working memory for Claude, not an archival artifact intended for a human to browse. Different problem.
- **MindStudio's Stop-hook + Obsidian pattern** — Stop hook fires at end of session, calls Claude again to extract patterns/decisions, writes to vault with frontmatter. Filter: skip transcripts under 100 chars. Closest philosophical match to our approach; weaker on multi-machine, idempotency, and PII.

**What this tells us:** Nobody has shipped the combination the user is asking for. The differentiators are the _integration_: AI labels + PII scrub + multi-machine distinction + MemPalace feed + sleep-safe catch-up + Obsidian-as-review-UI, all running without any external API keys (because the skill runs _inside_ Claude, so the labeler is free).

**Core insight driving prioritization:** Obsidian is the review UI. That single decision eliminates an enormous amount of scope (no web app, no TUI browser, no review command, no search engine, no curation queue), which means table stakes is narrow and quality of labeling matters more than quantity of features.

---

## Feature Landscape

### Table Stakes (Users Expect These — product fails without them)

Failure mode if missing: the product does not deliver Core Value ("Every Claude Code conversation Michael has should become a titled, searchable, PII-scrubbed artifact in his Obsidian vault").

| Feature                                                                       | Why Expected                                                                                                               | Complexity | Notes                                                                                                                                                                                                           |
| ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Delta-sync scanner** — find only new/changed sessions since last run        | Without this, every run re-processes everything. Bad for token budget, bad for idempotency, bad for MemPalace dedup.       | S          | Read `~/.claude-chat/state.json` cursor (mtime or session_id set), walk `~/.claude/projects/`, diff against cursor. `find_all_sessions()` already exists in `claude-chat.py`.                                   |
| **AI-generated title** (≤10 words, human-readable)                            | This is literally the user's goal #1. Cryptic session IDs are the bug.                                                     | S          | The skill runs _inside_ Claude, so the labeler is free. Prompt design matters more than infra. See "AI Labeling Best Practices" below.                                                                          |
| **AI-generated gist** (2–3 sentences)                                         | Differentiator for Obsidian search and for the Dataview inbox view; lets user triage without opening the file.             | S          | Same prompt call as title. One round-trip per session.                                                                                                                                                          |
| **AI-generated tags** (3–5 topical, lowercase, hyphenated)                    | Makes Obsidian's tag pane and graph view useful; feeds Dataview queries by topic.                                          | S          | Same prompt call. Constrain to a short controlled vocabulary in-prompt _or_ let them be free-form (see decision matrix below).                                                                                  |
| **PII scrub before write**                                                    | Non-negotiable per PROJECT.md constraint: vault is iCloud-synced, chats contain regulatory/clinical/credentials material.  | S          | `claude-chat.py protect` already exists. Compose, don't rewrite.                                                                                                                                                |
| **Obsidian-shaped markdown output** with YAML frontmatter                     | Without frontmatter, Dataview/Bases/graph don't work and the vault integration is purely cosmetic.                         | S          | `export_markdown()` in `claude-chat.py` already exists; needs a frontmatter wrapper.                                                                                                                            |
| **Machine-prefixed filename** (`<machine>--YYYY-MM-DD--<slug>.md`)            | User decision already made; required for multi-machine coexistence without collisions.                                     | S          | String formatting + slug function. `unicodedata.normalize` for ASCII slugs.                                                                                                                                     |
| **Per-machine config file** (`~/.claude-chat/config.json` with machine label) | Without it, filenames can't be prefixed and the user can't tell which Mac a chat came from.                                | S          | `/sync-chats --set-label <name>` on first run.                                                                                                                                                                  |
| **Per-machine state file** (local-only, `~/.claude-chat/state.json`)          | Without local-only state, two Macs racing on iCloud corrupt the cursor. Idempotency depends on this.                       | S          | JSON file with `last_sync_cursor`, `synced_session_ids` set. Atomic write via temp-file + rename (pattern already used in `cmd_protect`).                                                                       |
| **Idempotent execution**                                                      | Sleep-safe scheduling depends on it. Running the skill twice in a row should produce zero new writes.                      | S          | Check `session_id in synced_session_ids` before processing. Design falls out of state-file design if done right.                                                                                                |
| **"Skip already-synced" guard** (never re-title existing files)               | User explicitly flagged this in PROJECT.md key decisions. User edits titles in Obsidian; regeneration would clobber edits. | S          | Falls out of state file. Trivial once state is correct.                                                                                                                                                         |
| **Sync summary output** ("Synced N new, flagged M for review")                | Without feedback, the user has no way to tell if the scheduled run did anything.                                           | S          | Just a `print()` at the end.                                                                                                                                                                                    |
| **`needs_review: true` in frontmatter on every auto-labeled chat**            | The entire review flow depends on this — the user's inbox is `WHERE needs_review` in Dataview. No flag, no inbox.          | S          | Literal bool in YAML. Flip to `false` when user edits manually (see anti-features: we don't auto-detect this; user removes the field themselves, or Dataview query checks `contains(file.path, needs_review)`). |

**Table-stakes complexity is almost entirely SMALL.** That's because `claude-chat.py` already solves the hard parts (JSONL parsing, lazy metadata, protect, export_markdown). The skill is mostly glue: delta-diff → call Claude for labels → write YAML + markdown → append to state file.

---

### Differentiators (What makes this better than any existing tool)

| Feature                                                                                           | Value Proposition                                                                                                                                                                                                                                                                                           | Complexity | Notes                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **AI labels from the running Claude session itself** (no API key, no Ollama, no external service) | Every competitor requires either: (a) a separate Ollama install (`claude-vault`), (b) a paid API key, or (c) no labeling at all. Running the labeler inside Claude Code means zero infra, zero config, and the latest Opus for free.                                                                        | S          | This is essentially "paste the session text into the current Claude context and ask for title/gist/tags in JSON."                                                                                                         |
| **MemPalace integration** (one summary memory per synced chat)                                    | Nobody else does this. Claude Code's native Session Memory is _for Claude's own working context_, not a persistent cross-session knowledge base the user controls. MemPalace gives the user the ability to query "what have I done with Claude before?" and have Claude answer with real retrieved context. | M          | Depends on MemPalace MCP tools already being installed. One `mcp__mempalace__create_memory` (or equivalent) call per synced chat. Failure mode: MemPalace down → log warning, write chat to vault anyway, flag for retry. |
| **Multi-machine coexistence without dedup logic**                                                 | `claude-vault` explicitly says "requires manual coordination across devices." We get multi-machine for free because `~/.claude/projects/` is strictly local per Mac — session sets are disjoint. Filename prefix makes the source machine visible; local state files prevent races.                         | S          | This is architecture, not code. The _feature_ is "works on both Macs without thinking about it."                                                                                                                          |
| **Sleep-safe delta sync via `launchd RunAtLoad + StartInterval`**                                 | Laptops sleep. Scheduled jobs miss runs. Every competitor ignores this or handwaves it. We handle it with: (1) idempotency, (2) `RunAtLoad: true` catches the lid-open, (3) manual `/sync-chats` escape hatch for long travel gaps.                                                                         | S          | `launchd` plist is ~30 lines of XML. Idempotency is already table stakes.                                                                                                                                                 |
| **Obsidian-as-review-UI** (no separate review command, no TUI, no web UI)                         | Every competitor either builds their own review interface or has none. We reuse Obsidian's entire search/filter/graph/Dataview stack. User's existing muscle memory applies. Zero learning curve.                                                                                                           | S          | This is a _non-feature_ — its "implementation" is deliberately not building three other things. See "Anti-Features."                                                                                                      |
| **PII scrub built into the default path, not an optional mode**                                   | `claude-vault` has PII detection as a mode flag. We run `protect` on every chat, every time, because the vault is iCloud-synced and the user has regulatory/clinical exposure. Default-safe, not opt-in-safe.                                                                                               | S          | `claude-chat.py protect` already exists. Pipeline composition.                                                                                                                                                            |
| **Idempotent, reversible-by-omission design**                                                     | User can delete `state.json` and re-run → it re-syncs everything it doesn't already find in the vault. User can delete a chat file → next run notices and re-creates it (unless state says otherwise). Zero "repair tool" complexity because the design is self-healing.                                    | S          | Falls out of table-stakes state file + skip-existing-files guard, with one tweak: check if the target file exists on disk before writing, not just the state.                                                             |
| **Machine-stats frontmatter** (`machine`, `hostname`, `synced_at`)                                | Enables Dataview queries like `GROUP BY machine` to answer "how many chats came from each Mac?" without a separate command.                                                                                                                                                                                 | S          | Just extra YAML fields. `socket.gethostname()` from stdlib.                                                                                                                                                               |
| **Flat folder structure, sort-by-filename is sort-by-machine-then-date**                          | Every other tool either dumps into one giant folder with no ordering hint, or builds a year/month nested hierarchy (Nexus AI Chat Importer). The user's filename convention makes the flat folder self-organizing — `mbp--2026-04-10--debugging-rss-service.md` sorts visually.                             | S          | Just filename formatting.                                                                                                                                                                                                 |
| **Slug quality: AI-chosen, not first-user-message truncation**                                    | Nexus AI Chat Importer uses the conversation's own title verbatim (which for Claude Code is a session UUID — useless). `claude-code-log` uses "first user message" as summary (often boilerplate like "fix this bug"). AI-chosen slugs capture the _point_ of the conversation.                             | S          | Derive slug from the generated title: lowercase, kebab-case, strip stopwords, max 60 chars.                                                                                                                               |

---

### Anti-Features (Deliberately NOT built — scope discipline)

These are features that other tools in this space commonly ship, that the user has either explicitly rejected or that would conflict with the core architecture. Documenting them so they don't creep back in during implementation.

| Feature                                                                                 | Why Requested / Why Other Tools Build It                                                                   | Why Problematic Here                                                                                                                                          | Alternative                                                               |
| --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **Mac menu bar app (rumps/SwiftUI)**                                                    | "Visible status" and "one-click sync" feel nice.                                                           | User flipped on this in PROJECT.md: native packaging pain, and skills run inside Claude so the summarizer is free. No value add over a scheduled skill.       | `launchd` + skill. Status visible via Obsidian frontmatter + Dataview.    |
| **Web UI for browsing/curating chats**                                                  | `claude-chat.py` already has `serve`, and it's tempting to extend it. `claude-code-log` ships HTML output. | Obsidian already has full-text search, tag browser, graph, Dataview, Bases. Building another UI re-builds what Obsidian does better.                          | Write to Obsidian, let Obsidian be the UI.                                |
| **Interactive review queue command** (`/sync-chats review`)                             | TUI review loops feel productive.                                                                          | `needs_review: true` + Dataview query (`WHERE needs_review`) gives the same outcome with zero code. User edits in Obsidian where he already lives.            | Frontmatter flag + one Dataview query the user writes once.               |
| **Real-time file watcher** (`fsevents`, `watchdog`)                                     | Sounds "modern" and instantaneous.                                                                         | Hourly delta-sync is fresh enough for a personal archive. A watcher still has to handle sleep/wake, so it offers zero benefit over `launchd + RunAtLoad`.     | `launchd` with `StartInterval: 3600`.                                     |
| **Dedup across machines**                                                               | `claude-vault` does UUID-based dedup because it worries about two machines syncing the same file.          | `~/.claude/projects/` is strictly local per Mac. The two machines' session sets are disjoint. There is literally nothing to dedup.                            | Do nothing. Machine prefix makes this a non-issue.                        |
| **State file in iCloud** (shared cursor across machines)                                | "Then both machines know what's synced!"                                                                   | iCloud is eventually consistent and allows concurrent writes → guaranteed corruption. Two machines, two cursors, strict locality.                             | Local-only state at `~/.claude-chat/state.json`.                          |
| **Retroactive re-titling** (regenerate labels on already-synced chats)                  | "What if the AI gave a bad title? Just regenerate."                                                        | User edits titles manually in Obsidian. Regeneration clobbers edits. No way to distinguish "user hasn't touched it" from "user edited and was happy with it." | Never touch an already-synced chat. Period.                               |
| **External LLM API for summarization** (OpenAI, Anthropic direct API)                   | Every competitor that does AI labeling needs _some_ inference source.                                      | The skill runs inside Claude Code. Claude _is_ the inference source. Adding a second path is free work and a second place to fail.                            | Use the running Claude session.                                           |
| **Custom search engine / index**                                                        | `claude-chat.py` already has `search`. Tempting to expose it.                                              | Obsidian's search is better than anything we'd build, and the user's muscle memory is already there.                                                          | Obsidian search.                                                          |
| **Configurable output schemas / template system**                                       | "Let the user pick their own frontmatter fields!"                                                          | This is a tool _for one user_ with a specific vault. Configurability is negative value here — it's a maintenance surface.                                     | Hardcode the schema. If the user wants different fields, edit the skill.  |
| **Multi-folder routing** (put Python chats in `Chats/Python/`, JS chats in `Chats/JS/`) | Some users like topical folders.                                                                           | Flat folder + tags is searchable via Obsidian faster than folder navigation, and tags aren't mutually exclusive. Folders are.                                 | Flat folder, tags in frontmatter, let Obsidian graph do topic clustering. |
| **Editing/retitling chats via a CLI command**                                           | "I want to rename a chat without opening Obsidian."                                                        | Obsidian is open. Renaming a file in Obsidian updates links automatically; renaming via CLI breaks wikilinks.                                                 | Use Obsidian.                                                             |
| **Git backing for the vault from within the skill**                                     | "Auto-commit every sync run."                                                                              | Vault is iCloud-synced (user's choice). Adding git on top is a separate concern and the user can do it manually if he wants.                                  | Let iCloud handle sync.                                                   |
| **Attachment / image extraction**                                                       | ChatGPT exporters do this.                                                                                 | Claude Code sessions don't produce user-uploaded attachments the way web chats do. Tool call results include file paths, which are preserved as-is.           | Nothing to do.                                                            |
| **OpenAI/Gemini chat import**                                                           | `claude-vault` and Nexus AI Chat Importer both support multiple sources.                                   | User has _one_ source (Claude Code) and no interest in others. Generalizing is premature.                                                                     | Claude Code only.                                                         |

---

### Edge Cases (AI Labeling Failure Modes)

The hardest question in this project is "what does the labeler do when the session doesn't have enough signal to label well?" Categories, observed from real `~/.claude/projects/` content and corroborated by community discussion:

| Category                                                                                                                   | Detection Rule                                                                                                                                                                                                                 | Handling                                                                                                                                                                                                                                                                                                            | Reasoning                                                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ultra-short sessions** (< 2 message pairs, or < ~500 chars of human text)                                                | Count user+assistant pairs; measure total non-tool-call text length. MindStudio's hook uses `len(transcript_text) < 100`; we should be more generous (< 500 chars of prose) because Claude Code sessions have tool-call noise. | **Skip entirely.** Do not write to vault. Record `session_id` in `state.json` as "skipped: too-short" so we don't re-evaluate every run. Do not feed to MemPalace.                                                                                                                                                  | These are "oops, wrong window" sessions or aborted starts. They don't represent real work. Writing them to the vault is pure noise.                       |
| **Tool-call-heavy, prose-light sessions** (≥ 90% of content is tool I/O, not human/assistant conversation)                 | Measure ratio: `len(prose) / len(tool_output)`. If < 0.1, flag.                                                                                                                                                                | **Sync but tag `low_signal`** in frontmatter. Generate title/gist/tags anyway — they may be correct if the tool calls themselves tell a coherent story (e.g. "Refactor 8 files in the auth module"). Set `needs_review: true` even if user hasn't configured manual review, so these surface in the Dataview inbox. | These can still be valuable (a long refactor session) but the labeler is more likely to hallucinate a topic from thin context. Human eyes should confirm. |
| **Topic-drift sessions** (started about X, ended about Y, topics changed mid-session)                                      | Detectable by asking the labeler to rate topic coherence on a 1-5 scale as part of the JSON response.                                                                                                                          | **Sync with `multi_topic: true` tag.** Title captures the dominant/final topic. Gist acknowledges the drift ("Session started with X, moved to Y, ended debugging Z"). Tags cover all topics.                                                                                                                       | The user's workflow crosses clinical, blog, homelab, iOS, and regulatory work — drift is realistic and valuable to label honestly.                        |
| **Project-switched sessions** (user manually pasted a different project's context mid-conversation)                        | Hard to detect automatically. Treat as a subcase of topic-drift.                                                                                                                                                               | Same as topic-drift.                                                                                                                                                                                                                                                                                                | Rare enough not to special-case.                                                                                                                          |
| **Test / throwaway / "what does this do" sessions** (short probes, smoke tests, hello-world)                               | Detectable by content heuristics: title says "test," "hello," "checking," OR total session is under 1 minute of activity.                                                                                                      | **Sync with `throwaway` tag, skip MemPalace feed.** Still write the file (user might want to find "that test I ran with X"), but don't pollute MemPalace.                                                                                                                                                           | MemPalace is for _durable_ learning. Test sessions are not durable.                                                                                       |
| **Sessions with summary generation failure** (labeler returns malformed JSON, times out, or refuses)                       | Try-except around the label call; fallback on any exception.                                                                                                                                                                   | **Sync with deterministic fallback title** (`<machine>--YYYY-MM-DD--session-<short_id>.md`), gist = first 200 chars of first user message, tags = `[unlabeled]`, `needs_review: true`. Log the failure.                                                                                                             | The worst outcome is a silent skip. The next-worst is a crash. A mediocre-but-present title beats both.                                                   |
| **Empty or parse-error sessions** (JSONL file exists but is 0 bytes or every line fails to parse)                          | File size < 100 bytes, or `Session.parse()` yields zero messages. Existing `claude-chat.py` already filters files < 100 bytes in `find_all_sessions()`.                                                                        | **Skip entirely.** Record as skipped in state.                                                                                                                                                                                                                                                                      | Not even a session, really.                                                                                                                               |
| **Credential-laden sessions** (PII scrub triggered heavy redaction)                                                        | Measure redaction count from `protect` output. If > 10 redactions, flag.                                                                                                                                                       | **Sync with `redacted` tag and `review_privacy: true`** in frontmatter. The scrub already happened, this is just a heads-up that the chat may read weirdly.                                                                                                                                                         | The user wants to know which chats had sensitive content, even after scrubbing, so he can decide whether to keep them.                                    |
| **Sessions in a language other than English** (user has non-English clinical content, or code comments in other languages) | Labeler is multilingual, but tag taxonomy might fragment.                                                                                                                                                                      | **Label in English, tag `language: <lang>`.** Don't try to localize.                                                                                                                                                                                                                                                | User works in English primarily. Keep the taxonomy consistent.                                                                                            |

**Design note on the labeler prompt:** The prompt should ask for a _single JSON object_ containing `title`, `gist`, `tags`, and a `coherence_score` (1-5). Parsing one JSON blob is simpler and cheaper than three separate calls. The prompt should include explicit constraints:

- Title: ≤10 words, verb-leading when possible ("Debug RSS service pagination" beats "RSS service debugging"), no emoji, no Markdown, no quotes.
- Gist: 2–3 sentences. First sentence = what the user was trying to do. Second = what was accomplished or where it ended. Third sentence only if there's a genuine insight worth preserving.
- Tags: 3–5 items, lowercase, kebab-case, no leading `#`, drawn from topical vocabulary (no meta-tags like `long` or `important`).
- Coherence score: 1 = completely incoherent / drift / nonsense, 5 = single clear topic start to finish.

This design is cribbed from the OpenAI community thread's "constraint-based prompts work better" finding and aligns with ChatGPT's own title convention (short, concrete, topic-leading). The MindStudio hook uses a similar JSON extraction pattern with good results.

---

## AI Labeling Best Practices (Synthesized)

From the prior art survey and community sources:

**Title conventions (MEDIUM confidence — community practice, not formal study):**

- **Length:** ≤10 words, ≤60 characters. ChatGPT's internal title prompt uses "5 words or fewer" per the OpenAI forum thread — that's too short for our use case (we want enough specificity to distinguish "Debug RSS pagination" from "Fix RSS feed dates"). 10 words is a reasonable ceiling.
- **Format:** Verb-leading when the session is a _task_ ("Debug RSS service pagination"); topic-leading when the session is an _exploration_ ("Python async context managers"). Don't force verb-first universally — it makes exploratory conversations sound like bug reports.
- **Excluded words:** no "the," "a," "how to," "with Claude," "in Python" (language goes in tags). No quotes, emoji, or ellipses.
- **Proper nouns:** keep them (company names, project names, specific library names). These are the most searchable tokens.

**Gist conventions:**

- 2–3 sentences, 40–80 words total.
- Structure: (1) what the user tried to do, (2) what was accomplished or where it ended, (3) optional insight/blocker.
- Present tense or past tense, be consistent. Prefer past tense ("Debugged the pagination bug in...") — reads better when browsing chronologically.

**Tag conventions:**

- 3–5 tags is the sweet spot (corroborated by community practice; more fragments the tag pane, fewer defeats the point).
- Lowercase, kebab-case (`clinical-trials`, not `ClinicalTrials` or `clinical_trials`) — matches Obsidian tag conventions.
- Topical, not meta: `python`, `rss-feed`, `obsidian-plugin`, not `long` or `important` or `session`.
- No leading `#` in YAML (Obsidian accepts both but kebab-case strings are cleaner for Dataview filtering).

**Frontmatter field naming (Obsidian conventions, HIGH confidence):**

- Use `tags:` (plural) as a YAML list — Obsidian's native tag pane reads this.
- Use `aliases:` only if you want the chat discoverable by multiple names (probably not for us).
- Dates as `YYYY-MM-DD` strings (Dataview parses both strings and native dates).
- Booleans as literal `true`/`false` (not `"true"`) so Dataview can filter on them.

---

## Feature Dependencies

```
per-machine config file
        |
        v
machine-prefixed filename (requires machine label)
        |
        v
Obsidian-shaped markdown writer (requires filename + frontmatter schema)
        ^
        |
AI-generated labels (title + gist + tags) --required-by-- frontmatter schema
        ^
        |
delta-sync scanner --feeds-- labels (label only new sessions)
        ^
        |
per-machine state file --enables-- idempotency + delta-sync + skip-existing-guard

PII scrub --must-run-before--> markdown writer (scrub happens before write, not after)

MemPalace integration --depends-on--> markdown writer (one memory per successful write)
                     --degrades-gracefully-if--> MemPalace unavailable

launchd LaunchAgent --depends-on--> idempotent execution (otherwise schedule races)
                    --enables--> sleep-safe catch-up

sync summary output --depends-on--> everything above (it reports what happened)

needs_review flag --depends-on--> frontmatter schema
                  --enables--> Obsidian-as-review-UI (anti-feature substitute)
```

### Dependency Notes

- **PII scrub must run before markdown write.** Not after. Post-write scrubbing would briefly leak content to disk. Compose the pipeline as `load session → scrub → label → write`.
- **Labels depend on scrubbed content, not raw.** If we label before scrubbing, the title could contain PII that then gets written to the filename. Scrub first, then label the scrubbed version.
- **MemPalace feed should be best-effort, not blocking.** If MemPalace is down, the vault write should still succeed. Record `mempalace_synced: false` in frontmatter and retry on next run (requires a separate retry queue in state.json, or just re-feed any chat where that field is false).
- **Idempotency is the spine.** Delta-sync, skip-existing, launchd scheduling, and multi-machine all depend on it. If idempotency is broken, everything downstream races or duplicates.

---

## MVP Definition

### Launch With (v1) — "the skill exists and does the job end-to-end"

Table stakes only. No differentiators beyond the ones that are free (AI labels from Claude itself is free; machine prefix is free; Obsidian-as-review-UI is free).

- [ ] `/sync-chats` skill exists and is invokable from any Claude Code session
- [ ] `/sync-chats --set-label <name>` writes `~/.claude-chat/config.json`
- [ ] Delta-sync scanner identifies new/changed sessions since last cursor
- [ ] For each new session: scrub → label (title + gist + tags + coherence) → write markdown with YAML frontmatter + machine-prefixed filename
- [ ] Per-machine state file updated after each successful write
- [ ] Skip-already-synced guard (never retitle existing files)
- [ ] Edge-case handling: skip ultra-short, tag low-signal, fallback on label failure
- [ ] Sync summary output at end of run
- [ ] `needs_review: true` on every auto-labeled chat

**Launch criterion:** Running `/sync-chats` once on a Mac with 200+ existing sessions produces 200+ titled, scrubbed, tagged markdown files in `Chats/`, each with a human-readable name. A second run produces 0 new files. That's MVP.

### Add After Validation (v1.x) — "the skill is reliable and the labels are good"

Triggered when: MVP has been running for a week and the user has validated the label quality.

- [ ] MemPalace integration (one summary memory per chat)
- [ ] `launchd` LaunchAgent plist (scheduled hourly, RunAtLoad for sleep catch-up)
- [ ] Manual catch-up escape hatch (`/sync-chats --force-rescan` that re-walks but still respects existing files)
- [ ] Retry queue for failed MemPalace writes (chats with `mempalace_synced: false` are retried on next run)
- [ ] Coherence score surfaced in frontmatter (`coherence: 3`) for Dataview filtering

**Why defer:** MemPalace adds a dependency and a failure mode. Ship vault writes first, validate label quality, _then_ add MemPalace so debugging is linear.

### Future Consideration (v2+) — "nice to have if the user asks"

- [ ] Per-machine stats command (`/sync-chats stats` → "52 chats from mbp, 14 from studio, 3 flagged for review")
- [ ] Dataview query templates bundled with the skill (written to `Chats/_templates/` so user has examples)
- [ ] `low_signal` auto-detection tuning (if user reports too many/few false positives)
- [ ] Title regeneration for a _specific_ session on user request (`/sync-chats relabel <session_id>` — but only with `--force`, and only if the user hasn't edited the file; check by comparing file mtime to sync time)
- [ ] Per-project override for frontmatter (e.g., work chats get extra `compliance_review: true` flag automatically)

**Why defer all of these:** They're all convenience features on top of a working system. None of them block Core Value.

---

## Feature Prioritization Matrix

| Feature                                                | User Value                   | Implementation Cost           | Priority |
| ------------------------------------------------------ | ---------------------------- | ----------------------------- | -------- |
| Delta-sync scanner                                     | HIGH                         | LOW                           | P1       |
| AI-generated title                                     | HIGH                         | LOW                           | P1       |
| AI-generated gist                                      | HIGH                         | LOW                           | P1       |
| AI-generated tags                                      | MEDIUM                       | LOW                           | P1       |
| PII scrub before write                                 | HIGH (non-negotiable)        | LOW                           | P1       |
| Obsidian markdown + frontmatter                        | HIGH                         | LOW                           | P1       |
| Machine-prefixed filename                              | MEDIUM                       | LOW                           | P1       |
| Per-machine config                                     | MEDIUM                       | LOW                           | P1       |
| Per-machine state file                                 | HIGH (enables everything)    | LOW                           | P1       |
| Idempotent execution                                   | HIGH (enables scheduling)    | LOW                           | P1       |
| Skip-already-synced guard                              | HIGH (protects user edits)   | LOW                           | P1       |
| `needs_review` flag                                    | HIGH (enables inbox)         | LOW                           | P1       |
| Edge-case handling (ultra-short, low-signal, fallback) | MEDIUM                       | LOW-MEDIUM                    | P1       |
| Sync summary output                                    | MEDIUM (feedback loop)       | LOW                           | P1       |
| MemPalace integration                                  | HIGH                         | MEDIUM                        | P2       |
| `launchd` scheduling                                   | HIGH                         | LOW                           | P2       |
| Manual catch-up escape hatch                           | MEDIUM                       | LOW                           | P2       |
| MemPalace retry queue                                  | LOW (until MemPalace flakes) | LOW                           | P2       |
| Per-machine stats command                              | LOW                          | LOW                           | P3       |
| Bundled Dataview templates                             | LOW                          | LOW                           | P3       |
| Title regeneration on demand                           | LOW                          | MEDIUM (edit-detection logic) | P3       |

**Priority key:**

- **P1:** Must have for the MVP to deliver Core Value. Skill fails without it.
- **P2:** Should have for the skill to feel "done." Add immediately after MVP validates.
- **P3:** Nice to have. Defer until explicitly requested.

---

## Competitor Feature Analysis

| Feature                              | claude-code-log                                | claude-conversation-extractor | claude-vault                              | Nexus AI Chat Importer                                 | MindStudio hook pattern                      | **Our Approach**                                                                                                                                                        |
| ------------------------------------ | ---------------------------------------------- | ----------------------------- | ----------------------------------------- | ------------------------------------------------------ | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input source**                     | Claude Code JSONL                              | Claude Code JSONL             | Claude Code JSONL + Claude Web + OpenCode | ChatGPT/Claude exports                                 | Claude Code Stop hook                        | Claude Code JSONL only                                                                                                                                                  |
| **Output format**                    | HTML + markdown (on-demand via TUI)            | Markdown + JSON               | Markdown for Obsidian                     | Markdown for Obsidian                                  | Markdown for Obsidian                        | Markdown for Obsidian                                                                                                                                                   |
| **AI-generated title**               | No (uses Claude-provided summaries if present) | No                            | Via local Ollama (optional)               | No (uses source title verbatim → UUID for Claude Code) | Via Claude (Stop hook)                       | **Via running Claude session** (no API key, no Ollama)                                                                                                                  |
| **AI-generated gist/summary**        | No                                             | No                            | Via Ollama or keyword fallback            | No                                                     | Yes (2-3 sentences via Claude)               | **Yes (2-3 sentences via Claude)**                                                                                                                                      |
| **AI-generated tags**                | No                                             | No                            | Via Ollama                                | No                                                     | Category tags only (#pattern/#mistake/etc.)  | **Yes (3-5 topical, AI-chosen)**                                                                                                                                        |
| **PII scrubbing**                    | No                                             | No                            | Yes (tag/redact/skip modes, opt-in)       | No                                                     | No                                           | **Yes, default-on, non-negotiable**                                                                                                                                     |
| **Frontmatter**                      | N/A (HTML)                                     | Basic                         | Yes (including PII risk)                  | Basic                                                  | Yes (date, project, session, tags)           | **Rich: title, gist, tags, project, session_id, model, token_count, msg_count, machine, hostname, synced_at, needs_review, coherence, low_signal, throwaway, redacted** |
| **Delta/incremental sync**           | No                                             | No                            | "Full rescans; strategies not detailed"   | No                                                     | Per-session via hook (no cross-run tracking) | **Yes, per-machine state file with cursor**                                                                                                                             |
| **Multi-machine support**            | N/A (local only)                               | N/A                           | "Requires manual coordination"            | N/A                                                    | N/A (single machine)                         | **Native: machine prefix + local state**                                                                                                                                |
| **MemPalace / external memory feed** | No                                             | No                            | No                                        | No                                                     | No (vault-only)                              | **Yes, one memory per chat**                                                                                                                                            |
| **Scheduling / automation**          | Manual                                         | Manual                        | Watch mode (per-file events)              | Manual                                                 | Stop hook (per-session)                      | **launchd hourly + RunAtLoad (sleep-safe)**                                                                                                                             |
| **Idempotent**                       | N/A                                            | N/A                           | UUID tracking                             | N/A                                                    | Per-session only                             | **Yes, across machines and runs**                                                                                                                                       |
| **Review UI**                        | HTML index page                                | None                          | None documented                           | Folder hierarchy                                       | None (vault-only)                            | **Obsidian + Dataview query on `needs_review`**                                                                                                                         |
| **Dependencies**                     | Python                                         | Python                        | Python + Ollama (for AI features)         | Obsidian plugin                                        | Python + Claude API or skill                 | **Python stdlib + Claude Code runtime (zero external)**                                                                                                                 |

**What this matrix makes obvious:**

1. **Nobody combines delta-sync + AI labels + PII scrub + multi-machine + external memory feed in one tool.** The closest competitor (`claude-vault`) hits three of those and explicitly punts on the other two.
2. **The "running inside Claude" architectural choice is a genuine moat.** Every other tool needs an inference source (API key, Ollama, manual tagging). We inherit the best available model for free and don't ship any inference infrastructure.
3. **Obsidian-as-review-UI is unique.** Every other tool either builds its own browse interface or has none. We get the best-in-class UI for free by matching Obsidian's conventions.
4. **Multi-machine is solved by architecture, not code.** The machine-prefixed filename + local-only state convention eliminates the entire problem space that `claude-vault` explicitly says is unsolved.

---

## Sources

**Prior art (Claude Code session export tools):**

- [claude-code-log (daaain)](https://github.com/daaain/claude-code-log) — HTML export, token stats, TUI browser, no AI labels, no delta sync
- [claude-conversation-extractor (ZeroSumQuant)](https://github.com/ZeroSumQuant/claude-conversation-extractor) — raw export, no curation
- [cctrace (jimmc414)](https://github.com/jimmc414/cctrace) — markdown/XML export for archival
- [claude-logging (antocuni)](https://github.com/antocuni/claude-logging) — append-only HTML dumps
- [claude-vault (MarioPadilla)](https://github.com/MarioPadilla/claude-vault) — closest competitor; Ollama-dependent AI features, PII detection, explicit multi-machine punt
- [claude-vault on PyPI](https://pypi.org/project/claude-vault/)
- [Claude Vault on Obsidian Forum](https://forum.obsidian.md/t/claude-vault-turn-your-claude-chats-into-a-knowledge-base-for-obsidian-free/109275)

**Prior art (ChatGPT → Obsidian, adjacent patterns):**

- [Nexus AI Chat Importer (Obsidian plugin)](https://github.com/Superkikim/nexus-ai-chat-importer) — uses source title verbatim, no AI labeling, date-folder hierarchy
- [Nexus AI Chat Importer on Obsidian Forum](https://forum.obsidian.md/t/plugin-nexus-ai-chat-importer-import-chatgpt-conversations-to-your-vault/71664)
- [Save ChatGPT to Obsidian (Chrome extension)](https://chromewebstore.google.com/detail/save-chatgpt-to-obsidian-markdo/ehacefdknbaacgjcikcpkogkocemcdil)

**Claude Code hook / memory patterns:**

- [Building a Self-Evolving Claude Code Memory System with Obsidian and Hooks (MindStudio)](https://www.mindstudio.ai/blog/self-evolving-claude-code-memory-obsidian-hooks) — Stop hook + Claude API + Obsidian; closest philosophical match
- [Claude Code Hooks Reference (official)](https://code.claude.com/docs/en/hooks)
- [Claude Code Session Memory (claudefa.st)](https://claudefa.st/blog/guide/mechanics/session-memory) — native Session Memory mechanics, ~10k token extraction interval, not a user-facing archive

**AI labeling conventions:**

- [OpenAI Community: Prompt for concise chat titles](https://community.openai.com/t/prompt-to-get-chatgpt-api-to-write-concise-chat-titles-as-it-does-in-chatgpt-chat-application/85644) — "Summarize in 5 words or fewer" pattern, constraint-based prompting
- [Methods for controlling character length for SEO tags](https://community.openai.com/t/methods-for-controlling-character-length-for-seo-tags/1081064) — length constraint strategies
- [How to Use AI to Craft Titles (Grammarly)](https://www.grammarly.com/blog/writing-with-ai/ai-titles/) — verb-leading action titles

**Obsidian frontmatter / Dataview conventions:**

- [Obsidian Dataview docs](https://blacksmithgu.github.io/obsidian-dataview/)
- [Dataview: Adding Metadata](https://blacksmithgu.github.io/obsidian-dataview/annotation/add-metadata/)
- [Tags in the era of YAML frontmatter abundance (Obsidian Forum)](https://forum.obsidian.md/t/tags-in-the-era-of-yaml-front-matter-abundance/18328)

**Confidence notes:**

- **HIGH confidence** on the competitor landscape and feature gaps — verified across GitHub repos, PyPI, and Obsidian Forum threads.
- **HIGH confidence** on the anti-features — most are already decided in PROJECT.md with explicit reasoning.
- **MEDIUM confidence** on the AI labeling conventions — based on community practice and one OpenAI forum thread; no formal research studies were located. Safe because the conventions are small, reversible, and tunable from the skill prompt itself.
- **MEDIUM confidence** on the edge case thresholds (e.g., "< 500 chars is ultra-short") — these are starting points that should be tuned against the user's actual session distribution in v1.x.

---

_Feature research for: `/sync-chats` Claude Code skill milestone_
_Researched: 2026-04-10_
