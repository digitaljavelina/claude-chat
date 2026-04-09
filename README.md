# claude-chat

One tool for all your Claude Code conversations. Search, export, browse, and back up your session history.

Zero dependencies. One file. Works everywhere Python 3.7+ runs.

## Quick start

```bash
# Clone and run — no install needed
git clone https://github.com/digitaljavelina/claude-chat.git
cd claude-chat
python3 claude-chat.py list
```

## Commands

### list

List recent sessions with summaries, grouped by project.

```bash
python3 claude-chat.py list
python3 claude-chat.py list --project myapp --limit 50
python3 claude-chat.py list --detail    # show message previews
```

### search

Search across all conversations by keyword.

```bash
python3 claude-chat.py search "database migration"
python3 claude-chat.py search "auth" --project myapp
```

### export

Export a session to Markdown, HTML, plain text, or LaTeX.

```bash
python3 claude-chat.py export a7e44ed0 --format html --open
python3 claude-chat.py export a7e44ed0 --format md
python3 claude-chat.py export a7e44ed0 --format tex

# Export all sessions at once
python3 claude-chat.py export --all --format html --output ./exports
python3 claude-chat.py export --all --project myapp --format md
```

The HTML export includes syntax highlighting, dark theme, clickable links, and math rendering.

### serve

Browse all conversations in your browser with a local web UI.

```bash
python3 claude-chat.py serve           # opens http://localhost:3456
python3 claude-chat.py serve --port 8080
```

### stats

Show usage statistics — session counts, message totals, model breakdown, and project sizes.

```bash
python3 claude-chat.py stats
python3 claude-chat.py stats --project myapp
```

### extract

Pull out code blocks, your ideas/prompts, or decisions from a session.

```bash
python3 claude-chat.py extract a7e44ed0 --code
python3 claude-chat.py extract a7e44ed0 --ideas
python3 claude-chat.py extract a7e44ed0 --decisions
```

### backup

Back up session files, with optional continuous watch mode.

```bash
python3 claude-chat.py backup
python3 claude-chat.py backup --watch   # continuous backup
python3 claude-chat.py backup --output ~/my-backups
```

### protect

Prevent Claude Code from auto-deleting old sessions by setting `cleanupPeriodDays` to 99999.

```bash
python3 claude-chat.py protect
```

## How it works

Claude Code stores conversation sessions as JSONL files in `~/.claude/projects/`. This tool parses those files to let you search, export, and analyze your conversations without any external dependencies.

## Requirements

- Python 3.7+
- No external packages required

## License

MIT — by [Holger Morlok](https://github.com/holbizmetrics)
