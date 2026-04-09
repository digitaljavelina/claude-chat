---
name: export-test
description: Export a session to each format (md, html, txt) and open HTML in browser to visually check
---

Test the export functionality by exporting a recent session to all formats:

1. Run `python3 claude-chat.py list` to find a recent session ID
2. Pick the most recent session and export it to each format:
   - `python3 claude-chat.py export <session_id> -f md -o /tmp/test-export.md`
   - `python3 claude-chat.py export <session_id> -f html -o /tmp/test-export.html`
   - `python3 claude-chat.py export <session_id> -f txt -o /tmp/test-export.txt`
3. Open the HTML export in the browser: `open /tmp/test-export.html`

Report whether each export succeeded. If any failed, show the error.
