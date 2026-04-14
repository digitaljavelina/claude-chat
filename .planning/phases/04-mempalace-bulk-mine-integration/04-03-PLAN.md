---
phase: 04-mempalace-bulk-mine-integration
plan: 03
type: execute
wave: 3
depends_on:
  - "04-01"
  - "04-02"
files_modified:
  - tests/test_mine.py
  - ~/.claude/skills/sync-chats/SKILL.md
autonomous: false
requirements:
  - MEM-03
must_haves:
  truths:
    - "cmd_mine prints exactly `mempalace_mined: true` on success (sole stdout)"
    - "cmd_mine prints `mempalace_mined: skipped (command not found)` when binary absent (verified in Plan 02, re-asserted here as the MEM-03 contract)"
    - "SKILL.md Step 4 invokes `python3 $HOME/.claude-chat/sync_chats.py mine` after the last `write` call, conditional on write-count > 0 (D-05 zero-write skip)"
    - "When SKILL skips `mine` due to zero writes, the summary line reads `mempalace_mined: skipped (no new files)` (three-state MEM-03 contract)"
    - "The `mempalace_mined: ...` line is the last line of the SKILL's sync summary output"
  artifacts:
    - path: "tests/test_mine.py"
      provides: "TestCmdMineSummary + TestSkillMineStep — MEM-03 stdout + SKILL integration tests"
      contains: "class TestCmdMineSummary"
    - path: "~/.claude/skills/sync-chats/SKILL.md"
      provides: "Step 4 mine invocation with zero-write skip + summary append"
      contains: "mempalace_mined"
  key_links:
    - from: "SKILL.md Step 4"
      to: "sync_chats.py::cmd_mine"
      via: "bash invocation `python3 $HOME/.claude-chat/sync_chats.py mine` after last write, conditional on write-count > 0"
      pattern: "sync_chats\\.py mine"
    - from: "SKILL.md Step 3 summary"
      to: "SKILL.md Step 4 output"
      via: "appending `mempalace_mined: <status>` line to the end of the summary block"
      pattern: "mempalace_mined:"
---

<objective>
Close the Phase 4 loop: assert MEM-03's machine-readable stdout contract with tests, then wire the SKILL.md orchestrator to call `mine` after the last `write` (with the D-05 zero-write skip living in the SKILL per RESEARCH.md §"Integration Map"). Ends with a human checkpoint: you run `/sync-chats` manually on a session and verify the summary shows `mempalace_mined: true`.

Purpose: Fulfill MEM-03 ("Sync summary includes `mempalace_mined: true|false|skipped` line") and lock the SKILL-side integration that CONTEXT D-02 and D-05 describe. `cmd_mine` itself is already feature-complete after Plans 01–02; this plan verifies the stdout contract formally and updates the skill file.

Output:

- `TestCmdMineSummary` (2 tests) green — MEM-03 stdout format asserted on success + skipped paths
- `TestSkillMineStep` (1 test) green or `@skipUnless` passthrough — verifies SKILL.md Step 4 exists
- `~/.claude/skills/sync-chats/SKILL.md` Step 4 added, zero-write skip implemented
- Human checkpoint: real-world sync run shows correct `mempalace_mined` line
  </objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/04-mempalace-bulk-mine-integration/04-CONTEXT.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-RESEARCH.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-VALIDATION.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-01-SUMMARY.md
@.planning/phases/04-mempalace-bulk-mine-integration/04-02-SUMMARY.md
@sync_chats.py
@tests/test_mine.py

<interfaces>
<!-- cmd_mine stdout contract (from Plans 01-02, now frozen by MEM-03) -->

Exact stdout strings cmd_mine prints (one and only one line per invocation):

| Condition                                              | stdout line                                    |
| ------------------------------------------------------ | ---------------------------------------------- |
| mempalace binary present AND mine succeeded (rc=0)     | `mempalace_mined: true`                        |
| mempalace binary present, non-zero exit code N         | `mempalace_mined: false (exit N)`              |
| mempalace binary present, subprocess timed out at 300s | `mempalace_mined: false (timeout after 300s)`  |
| `shutil.which("mempalace")` returned None              | `mempalace_mined: skipped (command not found)` |

Zero-write skip (D-05) lives in the SKILL, not in `cmd_mine`:

| Condition                                             | stdout line (printed by SKILL)            |
| ----------------------------------------------------- | ----------------------------------------- |
| SKILL's write count (M + K) == 0 → skips calling mine | `mempalace_mined: skipped (no new files)` |

SKILL.md path (per-user, not in repo — CONTEXT.md "Integration Points"):
`~/.claude/skills/sync-chats/SKILL.md`
Test access: `_SKILL_PATH = Path.home() / ".claude" / "skills" / "sync-chats" / "SKILL.md"` with class-level `@unittest.skipUnless(_SKILL_PATH.exists(), ...)` per project memory `reference_skill_md_tests_ci.md`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 4-03-01: MEM-03 stdout contract — success prints exactly `mempalace_mined: true`</name>
  <files>tests/test_mine.py</files>
  <behavior>
    - Test 4-03-01 (`TestCmdMineSummary.test_true_on_success`): On a fully-mocked successful run (`shutil.which` returns a path, `subprocess.run` returns rc=0), `cmd_mine` prints exactly one line — `mempalace_mined: true` — and no other stdout (no diagnostics, no stderr tail, no extra whitespace).
  </behavior>
  <action>
Un-skip `TestCmdMineSummary::test_true_on_success` and implement:

```python
def test_true_on_success(self):
    """MEM-03: stdout is exactly `mempalace_mined: true` on rc=0 (sole output line)."""
    fake_args = argparse.Namespace()

    with patch("sync_chats.shutil.which", return_value="/fake/mempalace"), \
         patch("sync_chats._require_config", return_value={
             "vault_path": "/tmp/fake-vault", "machine_label": "t", "schema_version": 1,
         }), \
         patch("sync_chats.subprocess.run") as mock_run, \
         patch("sync_chats._log_sync") as mock_log, \
         patch("builtins.print") as mock_print:
        mock_run.return_value = MagicMock(returncode=0, stdout="ignored stdout",
                                          stderr="ignored stderr")
        sync_chats.cmd_mine(fake_args)

    # Exactly one print call — no diagnostics leak to stdout (Pitfall 3 in RESEARCH).
    mock_print.assert_called_once_with("mempalace_mined: true")
    # Success is silent in sync.log per D-11 (no logging on rc=0)
    mock_log.assert_not_called()
```

Rationale (Python beginner note): `mock_print.assert_called_once_with(...)` is stricter than `assert_called_with` — it fails if `print` was called 0 times OR 2+ times. This catches the Pitfall 3 failure mode where `cmd_mine` accidentally prints diagnostics alongside the outcome line.

No production code changes expected. If this test fails, it means Plan 01/02 introduced a stray `print(...)` somewhere in the success path — fix by removing it.
</action>
<verify>
<automated>pipx run pytest tests/test_mine.py::TestCmdMineSummary::test_true_on_success -xvs</automated>
</verify>
<done>Test green. Stdout contract for success formally verified.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4-03-02: MEM-03 stdout contract — skipped outcome includes inline reason</name>
  <files>tests/test_mine.py</files>
  <behavior>
    - Test 4-03-02 (`TestCmdMineSummary.test_skipped_with_reason`): When `shutil.which` returns None, stdout is exactly `mempalace_mined: skipped (command not found)` — proving D-15's inline-reason format is honored.
  </behavior>
  <action>
Un-skip `TestCmdMineSummary::test_skipped_with_reason`:

```python
def test_skipped_with_reason(self):
    """MEM-03 / D-15: skipped outcome carries inline reason `(command not found)`."""
    fake_args = argparse.Namespace()

    with patch("sync_chats.shutil.which", return_value=None), \
         patch("sync_chats._require_config", return_value={
             "vault_path": "/tmp/fake-vault", "machine_label": "t", "schema_version": 1,
         }), \
         patch("sync_chats._log_sync"), \
         patch("builtins.print") as mock_print:
        sync_chats.cmd_mine(fake_args)

    mock_print.assert_called_once_with("mempalace_mined: skipped (command not found)")
```

This test is a narrower assertion than 4-02-01's, focused on the D-15 inline-reason contract specifically (not sync.log, not subprocess mock — just the exact stdout format).
</action>
<verify>
<automated>pipx run pytest tests/test_mine.py::TestCmdMineSummary -xvs</automated>
</verify>
<done>Both `TestCmdMineSummary` tests green. MEM-03 stdout format locked.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 4-03-03: Wire SKILL.md Step 4 + zero-write skip + summary append</name>
  <files>~/.claude/skills/sync-chats/SKILL.md, tests/test_mine.py</files>
  <behavior>
    - Test 4-03-03 (`TestSkillMineStep.test_skill_step4_calls_mine`, class-decorated with `@unittest.skipUnless(_SKILL_PATH.exists(), ...)`): The installed SKILL.md file contains (a) a Step 4 heading/section that mentions `mine`, (b) an invocation of `sync_chats.py mine`, (c) a zero-write conditional that short-circuits to `mempalace_mined: skipped (no new files)` when write-count is 0, and (d) an instruction to append the `mempalace_mined:` line to the Step 3 summary. On hosts where the SKILL file does not exist (CI), the whole class skips per `reference_skill_md_tests_ci.md`.
  </behavior>
  <action>
**Part A — Update `~/.claude/skills/sync-chats/SKILL.md`:**

Add a new Step 4 after the existing Step 3 (summary). Preserve the existing frontmatter and Steps 1–3. The new Step 4 content:

````markdown
## Step 4: Mine vault into MemPalace (post-run)

After all `write` calls in Step 2 complete, shell out **once** to the MemPalace bulk-mine CLI so every new chat gets ingested.

**Zero-write skip (D-05):** If Step 2 wrote zero files (M + K counters both 0), skip calling `mine` entirely and append `mempalace_mined: skipped (no new files)` to the summary. Rationale: a full-directory scan of an unchanged vault is wasted work.

**Otherwise:**

```bash
python3 $HOME/.claude-chat/sync_chats.py mine
```
````

Capture the single stdout line this prints — one of:

- `mempalace_mined: true`
- `mempalace_mined: false (<reason>)`
- `mempalace_mined: skipped (<reason>)`

Append it verbatim as the **last line** of the Step 3 summary block so the full summary reads:

```
Processed N sessions: M labeled, K stubbed, J skipped (ultra-short).
mempalace_mined: <status>
```

**Do not** raise or abort if `mine` reports `false` or `skipped`. Phase 4's contract (MEM-02) is fail-soft: vault writes are already committed by Step 2; the mine outcome is reportable state, not a blocker.

````

**Part B — Un-skip and implement test 4-03-03:**

```python
_SKILL_PATH = Path.home() / ".claude" / "skills" / "sync-chats" / "SKILL.md"

@unittest.skipUnless(_SKILL_PATH.exists(),
                     "SKILL.md not installed on this host (per-user file, not in repo)")
class TestSkillMineStep(unittest.TestCase):
    """MEM-03: SKILL.md Step 4 wires cmd_mine into the sync pipeline."""

    def test_skill_step4_calls_mine(self):
        content = _SKILL_PATH.read_text(encoding="utf-8")

        # (a) Step 4 section exists and mentions mine
        self.assertRegex(content, r"(?mi)^##\s*Step\s*4.*mine")

        # (b) Invocation of sync_chats.py mine
        self.assertIn("sync_chats.py mine", content)

        # (c) Zero-write skip (D-05) with the exact "no new files" reason string
        self.assertIn("mempalace_mined: skipped (no new files)", content)

        # (d) Summary append instruction — SKILL must mention appending to the
        # Step 3 summary (Claude's discretion on exact wording, but "summary" + "append"
        # should both appear near the Step 4 content).
        self.assertRegex(content, r"(?is)Step\s*4.{0,2000}?summary")
````

Python beginner notes:

- `(?mi)` at the start of a regex enables multiline + case-insensitive mode.
- `(?is)` enables dotall (`.` matches newlines) + case-insensitive — needed because the "append to summary" check spans multiple lines.
- `{0,2000}?` is a bounded non-greedy match so the regex can't wander into later sections of the SKILL.

**Part C — Human checkpoint follows in Task 4-03-04 below** (split out so this automated task can be verified independently).
</action>
<verify>
<automated>pipx run pytest tests/test_mine.py::TestSkillMineStep -v</automated>
</verify>
<done>On host with SKILL.md installed: test green. On CI (no SKILL.md): test skipped. Full suite `python3 -m unittest discover tests -v` zero failures.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 4-03-04: Human verify — real-world sync run end-to-end</name>
  <what-built>
End-to-end Phase 4 pipeline:
- `cmd_mine` subcommand with graceful degradation on missing binary / non-zero exit / timeout
- `sync.log` warnings on every non-success path (last 20 lines of stderr on failure only)
- SKILL.md Step 4 invokes `mine` after last `write`, zero-write skips print `mempalace_mined: skipped (no new files)`
- Summary's last line is `mempalace_mined: <true|false|skipped (reason)>`
  </what-built>
  <how-to-verify>
1. **Happy path** (requires ≥1 new Claude Code session that has not yet been synced):
   ```bash
   cd ~
   # From a Claude Code session, invoke the skill:
   /sync-chats
   ```
   Expected: summary ends with `mempalace_mined: true`. Confirm with:
   ```bash
   mempalace search "some phrase from that chat"
   # Should return the synced chat in results.
   ```

2. **Zero-write path** (re-run immediately, with nothing new to sync):

   ```bash
   /sync-chats
   ```

   Expected: summary ends with `mempalace_mined: skipped (no new files)`. `sync_chats.py mine` is NOT invoked (verify by tailing `~/.claude-chat/sync.log` — no new mempalace line).

3. **Missing-binary path** (optional, requires a shell with PATH scrubbed):

   ```bash
   PATH="/usr/bin:/bin" python3 ~/.claude-chat/sync_chats.py mine
   ```

   Expected:
   - stdout: `mempalace_mined: skipped (command not found)`
   - exit code: `echo $?` → 0
   - `tail -1 ~/.claude-chat/sync.log` contains `mempalace: command not found — skipping mine`

4. **Failure path** (optional, simulate non-zero exit):
   ```bash
   # Temporarily point mempalace at a broken target
   python3 ~/.claude-chat/sync_chats.py mine  # run with a deliberately-invalid vault_path in config
   ```
   Expected: summary line `mempalace_mined: false (exit N)`, `sync.log` contains last ~20 lines of stderr, exit 0. Restore config after.

Verify `~/.claude-chat/sync.log` is sane:

```bash
tail -20 ~/.claude-chat/sync.log
```

No raw chat content should appear — only pattern names, exit codes, and mempalace's own error text.
</how-to-verify>
<resume-signal>Type "approved" if all four paths behave as described, or describe any deviation (e.g., "timeout message missing from sync.log", "summary line appears before Step 3 output").</resume-signal>
</task>

</tasks>

<threat_model>

## Trust Boundaries

| Boundary                         | Description                                                                                                                                                                          |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| SKILL.md → subprocess invocation | SKILL shells out to `sync_chats.py mine` via `python3 $HOME/.claude-chat/sync_chats.py mine` — list-form implicit via bash argv, no shell variables expanded into the mempalace argv |
| cmd_mine stdout → SKILL summary  | Machine-readable single-line outcome parsed by the SKILL and appended to human-facing summary                                                                                        |

## STRIDE Threat Register

| Threat ID | Category               | Component                     | Disposition | Mitigation Plan                                                                                                                                                                                                                                |
| --------- | ---------------------- | ----------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-4-01    | Tampering              | SKILL.md → python3 invocation | mitigate    | The SKILL calls `python3 $HOME/.claude-chat/sync_chats.py mine` — `$HOME` expansion is shell-safe (no user input). `cmd_mine` itself re-asserts list-form subprocess.run (covered in Plan 01, T-4-01).                                         |
| T-4-05    | Information disclosure | Summary line                  | accept      | `mempalace_mined: true/false/skipped (<reason>)` contains no config, path, or chat content. Reason strings are fixed (`command not found`, `exit N`, `timeout after 300s`, `no new files`).                                                    |
| T-4-06    | Repudiation            | Zero-write skip               | accept      | SKILL-side skip (D-05) is logged to the summary as `skipped (no new files)` — user sees the outcome; `sync.log` does not record skip because `cmd_mine` was never invoked. Acceptable: the write-count in the same summary line disambiguates. |

</threat_model>

<verification>
```bash
pipx run pytest tests/test_mine.py -v          # 8 tests: 7 green + 1 SKILL test (green on dev host, skipped on CI)
python3 -m unittest discover tests -v          # full suite green
```

Smoke (human-verify task above covers the manual end-to-end).
</verification>

<success_criteria>

- [ ] `TestCmdMineSummary` (2 tests) green — MEM-03 stdout contract formally verified
- [ ] `TestSkillMineStep` green on dev host OR cleanly skipped on CI (per `reference_skill_md_tests_ci.md`)
- [ ] SKILL.md Step 4 exists with: (a) `mine` invocation, (b) zero-write skip with `mempalace_mined: skipped (no new files)` message, (c) summary-append instruction
- [ ] Full suite `python3 -m unittest discover tests -v` zero failures
- [ ] Human checkpoint 4-03-04 returns "approved" — real sync shows `mempalace_mined: true` on happy path and `skipped (no new files)` on zero-write re-run
- [ ] All three MEM-03 outcome states (`true | false | skipped`) visible in the summary output on the appropriate invocation
- [ ] No regressions in prior phases
      </success_criteria>

<output>
After completion, create `.planning/phases/04-mempalace-bulk-mine-integration/04-03-SUMMARY.md` documenting the final SKILL.md Step 4 content, the exact wording chosen for each outcome line, and the human-verify outcome.
</output>
