---
name: verify
description: Smoke-test claude-chat.py after changes by running list and stats commands
---

Run these commands to verify claude-chat.py is working after changes:

1. `python3 claude-chat.py list` — should list recent sessions without errors
2. `python3 claude-chat.py stats` — should show usage statistics without errors

If either command fails, report the error and suggest a fix. If both succeed, confirm the tool is working.
