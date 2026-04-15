#!/usr/bin/env bash
#
# install.sh — Interactive installer for claude-chat + sync_chats onboarding.
#
# Walks through every prerequisite from README Section 2 and every install
# step from Sections 3–5, detecting what's already in place and only
# prompting for action where something is missing or outdated.
#
# Usage:
#   ./install.sh              Interactive install (default)
#   ./install.sh --dry-run    Detect only; make no changes
#   ./install.sh -y           Auto-approve every prompt (use carefully)
#   ./install.sh --help       Show this usage
#
# Exit codes:
#   0  — everything green, ready to go
#   1  — user declined one or more required steps (or hit a blocker)
#   2  — bug in the installer itself (please report)

set -euo pipefail

# ─── Globals ─────────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
CLAUDE_CHAT_HOME="${CLAUDE_CHAT_HOME:-$HOME/.claude-chat}"
SETTINGS_JSON="$HOME/.claude/settings.json"
HOOK_COMMAND="python3 ~/.claude-chat/sync_chats.py --once"

DRY_RUN=0
AUTO_YES=0

# Counters for the final report
STEPS_OK=0
STEPS_INSTALLED=0
STEPS_SKIPPED=0
STEPS_BLOCKED=0

# ─── Arg parsing ─────────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -y|--yes) AUTO_YES=1; shift ;;
    --help|-h)
      sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

# ─── Output helpers (color when attached to a TTY) ───────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
  C_OK="$(tput setaf 2)"; C_WARN="$(tput setaf 3)"; C_ERR="$(tput setaf 1)"
  C_BOLD="$(tput bold)"; C_DIM="$(tput dim)"; C_RESET="$(tput sgr0)"
else
  C_OK=""; C_WARN=""; C_ERR=""; C_BOLD=""; C_DIM=""; C_RESET=""
fi

ok()   { echo "${C_OK}✓${C_RESET} $*"; STEPS_OK=$((STEPS_OK+1)); }
warn() { echo "${C_WARN}⚠${C_RESET} $*"; }
err()  { echo "${C_ERR}✗${C_RESET} $*" >&2; }
step() { echo ""; echo "${C_BOLD}── $* ──${C_RESET}"; }
dim()  { echo "${C_DIM}$*${C_RESET}"; }

# ─── Interaction ─────────────────────────────────────────────────────────────

# ask_yn PROMPT [default_no|default_yes] → returns 0 for yes, 1 for no
ask_yn() {
  local prompt="$1" default="${2:-default_no}"
  if [[ $AUTO_YES -eq 1 ]]; then
    echo "  ${C_DIM}auto-yes: ${prompt}${C_RESET}"
    return 0
  fi
  if [[ $DRY_RUN -eq 1 ]]; then
    # Honor the passed default so dry-run previews the "just hit Enter" flow.
    # default_yes → dry-run assumes YES (what a user would get from Enter-key).
    # default_no  → dry-run assumes NO.
    if [[ "$default" == "default_yes" ]]; then
      echo "  ${C_DIM}dry-run: would ask: ${prompt} → assuming YES (default)${C_RESET}"
      return 0
    else
      echo "  ${C_DIM}dry-run: would ask: ${prompt} → assuming NO (default)${C_RESET}"
      return 1
    fi
  fi
  local hint="[y/N]"
  [[ "$default" == "default_yes" ]] && hint="[Y/n]"
  local ans
  read -r -p "  ${prompt} ${hint} " ans
  ans="${ans:-}"
  if [[ -z "$ans" ]]; then
    [[ "$default" == "default_yes" ]] && return 0 || return 1
  fi
  [[ "$ans" =~ ^[Yy] ]] && return 0 || return 1
}

# run_cmd CMD — prints the command, then runs it unless DRY_RUN.
run_cmd() {
  echo "  ${C_DIM}$ $*${C_RESET}"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "  ${C_DIM}(dry-run: not executed)${C_RESET}"
    return 0
  fi
  eval "$@"
}

# ─── Detection checks ────────────────────────────────────────────────────────

check_python() {
  step "Python 3.9+"
  if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found on PATH."
    echo "  On macOS: install Xcode Command Line Tools via 'xcode-select --install'"
    echo "  Then re-run this installer."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
  local ver
  ver="$(python3 -c 'import sys; print("{}.{}".format(sys.version_info[0], sys.version_info[1]))')"
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)'; then
    ok "python3 ${ver} (>= 3.9 required)"
  else
    err "python3 ${ver} is too old (>= 3.9 required)."
    echo "  Upgrade via Xcode CLT or a modern Python installer."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
}

check_obsidian() {
  step "Obsidian"
  if [[ -d /Applications/Obsidian.app ]]; then
    ok "Obsidian.app found in /Applications/"
    return 0
  fi
  if command -v obsidian >/dev/null 2>&1; then
    ok "obsidian found on PATH (non-macOS install)"
    return 0
  fi
  warn "Obsidian not detected."
  echo "  Download: https://obsidian.md"
  echo "  Install it, open any vault, then re-run this installer."
  STEPS_BLOCKED=$((STEPS_BLOCKED+1))
  return 1
}

check_claude_code() {
  step "Claude Code"
  if command -v claude >/dev/null 2>&1; then
    ok "claude CLI found at $(command -v claude)"
    return 0
  fi
  warn "Claude Code CLI not found on PATH."
  echo "  Install instructions: https://docs.claude.com/claude-code"
  echo "  You must install + authenticate Claude Code before the SessionEnd hook can fire."
  echo "  (This installer can still continue — the hook will sit dormant until Claude Code is in place.)"
  STEPS_BLOCKED=$((STEPS_BLOCKED+1))
  return 1
}

check_jq() {
  step "jq (required for safe settings.json edits)"
  if command -v jq >/dev/null 2>&1; then
    ok "jq found at $(command -v jq)"
    return 0
  fi
  warn "jq not found — needed to install the SessionEnd hook safely."
  if ask_yn "Install jq via 'brew install jq'?" default_yes; then
    if ! command -v brew >/dev/null 2>&1; then
      err "Homebrew not installed. Install from https://brew.sh then re-run."
      STEPS_BLOCKED=$((STEPS_BLOCKED+1))
      return 1
    fi
    run_cmd "brew install jq"
    STEPS_INSTALLED=$((STEPS_INSTALLED+1))
  else
    STEPS_SKIPPED=$((STEPS_SKIPPED+1))
    return 1
  fi
}

check_pipx() {
  step "pipx (optional — only needed if you want MemPalace)"
  if command -v pipx >/dev/null 2>&1; then
    ok "pipx found at $(command -v pipx)"
    return 0
  fi
  warn "pipx not found."
  if ask_yn "Install pipx via 'brew install pipx'?"; then
    if ! command -v brew >/dev/null 2>&1; then
      err "Homebrew not installed. Skipping pipx."
      STEPS_SKIPPED=$((STEPS_SKIPPED+1))
      return 1
    fi
    run_cmd "brew install pipx && pipx ensurepath"
    STEPS_INSTALLED=$((STEPS_INSTALLED+1))
  else
    dim "  Skipping pipx. MemPalace integration will be unavailable."
    STEPS_SKIPPED=$((STEPS_SKIPPED+1))
  fi
}

check_mempalace() {
  step "mempalace (optional — semantic memory palace for your chats)"
  if command -v mempalace >/dev/null 2>&1; then
    ok "mempalace found at $(command -v mempalace)"
    return 0
  fi
  if ! command -v pipx >/dev/null 2>&1; then
    dim "  Skipping mempalace check — pipx is not installed (see earlier step)."
    STEPS_SKIPPED=$((STEPS_SKIPPED+1))
    return 0
  fi
  warn "mempalace not found."
  if ask_yn "Install via 'pipx install mempalace'?"; then
    run_cmd "pipx install mempalace"
    STEPS_INSTALLED=$((STEPS_INSTALLED+1))
  else
    STEPS_SKIPPED=$((STEPS_SKIPPED+1))
  fi
}

check_claude_chat_home() {
  step "~/.claude-chat/ state directory"
  if [[ -d "$CLAUDE_CHAT_HOME" ]]; then
    ok "$CLAUDE_CHAT_HOME exists"
  else
    warn "$CLAUDE_CHAT_HOME does not exist."
    if ask_yn "Create it now?" default_yes; then
      run_cmd "mkdir -p '$CLAUDE_CHAT_HOME'"
      STEPS_INSTALLED=$((STEPS_INSTALLED+1))
    else
      err "This directory is required. Re-run installer when ready."
      STEPS_BLOCKED=$((STEPS_BLOCKED+1))
      return 1
    fi
  fi

  # Cloud-sync sanity check (matches _assert_not_icloud in sync_chats.py).
  # Skip if the dir doesn't exist yet (dry-run case where mkdir was previewed
  # but not executed) — we can't realpath something that isn't there.
  if [[ ! -d "$CLAUDE_CHAT_HOME" ]]; then
    dim "  Skipping cloud-sync scan — directory not yet on disk (dry-run)."
    return 0
  fi
  local real
  real="$(cd "$CLAUDE_CHAT_HOME" && pwd -P)"
  if [[ "$real" == *"Mobile Documents"* || "$real" == *"/iCloud"* ]]; then
    err "$CLAUDE_CHAT_HOME resolves to an iCloud path ($real)."
    echo "  sync_chats.py will refuse to run from there."
    echo "  Relocate via: export CLAUDE_CHAT_HOME=/some/local/path (add to ~/.zshrc)."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
  # Soft warning for other common cloud-sync roots.
  case "$real" in
    *"/CloudStorage/Dropbox"*|*"/Dropbox/"*|*"/CloudStorage/GoogleDrive-"*|*"/CloudStorage/OneDrive-"*)
      warn "$CLAUDE_CHAT_HOME appears to be inside a cloud-synced folder ($real)."
      echo "  The assertion doesn't block this, but state.json races across machines will corrupt."
      echo "  Relocate via CLAUDE_CHAT_HOME env var before proceeding if possible."
      ;;
  esac
}

check_symlink() {
  step "~/.claude-chat/sync_chats.py symlink"
  local link="$CLAUDE_CHAT_HOME/sync_chats.py"
  local target="$REPO_ROOT/sync_chats.py"

  if [[ ! -f "$target" ]]; then
    err "Expected sync_chats.py at $target — is this script being run from inside the repo?"
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi

  if [[ -L "$link" ]]; then
    local current_target
    current_target="$(readlink "$link")"
    if [[ "$current_target" == "$target" ]]; then
      ok "symlink correctly points to $target"
      return 0
    fi
    warn "symlink points to $current_target (expected $target)."
    if ask_yn "Replace it with a link to $target?" default_yes; then
      run_cmd "ln -sf '$target' '$link'"
      STEPS_INSTALLED=$((STEPS_INSTALLED+1))
    else
      STEPS_SKIPPED=$((STEPS_SKIPPED+1))
    fi
    return 0
  fi

  if [[ -e "$link" ]]; then
    warn "$link exists but is not a symlink — won't overwrite. Inspect manually."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi

  warn "symlink missing."
  if ask_yn "Create symlink $link → $target?" default_yes; then
    run_cmd "ln -sf '$target' '$link'"
    STEPS_INSTALLED=$((STEPS_INSTALLED+1))
  else
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
}

check_claude_chat_export() {
  # sync_chats.py shells out to `claude-chat.py export --stdout` to render each
  # session's markdown body. If the flag is missing (e.g. user has an old fork
  # without Phase-1 additions), writes will fail silently. Verify up front.
  step "claude-chat.py export --stdout compatibility"
  local engine="$REPO_ROOT/claude-chat.py"
  if [[ ! -f "$engine" ]]; then
    err "claude-chat.py not found at $engine"
    echo "  The repo clone appears incomplete — re-clone from github.com/digitaljavelina/claude-chat."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
  # Run --help and confirm it parses without error.
  if ! python3 "$engine" --help >/dev/null 2>&1; then
    err "python3 $engine --help failed to run."
    echo "  Check the file isn't corrupted; if recent, try 'git pull'."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
  # Confirm the `export` subcommand offers --stdout.
  # Use `export -h` (not --help at top level) so we see the subcommand's own flags.
  if python3 "$engine" export -h 2>&1 | grep -q -- "--stdout"; then
    ok "claude-chat.py export --stdout flag available"
  else
    err "claude-chat.py's 'export' subcommand does not expose --stdout."
    echo "  sync_chats.py depends on this flag for body rendering; writes will fail."
    echo "  If you have a fork of claude-chat.py, pull upstream or re-clone."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
}

check_config() {
  step "~/.claude-chat/config.json"
  local cfg="$CLAUDE_CHAT_HOME/config.json"
  if [[ -f "$cfg" ]]; then
    ok "config.json exists"
    dim "  $(python3 -c "
import json
c = json.load(open('$cfg'))
print('  machine_label:', c.get('machine_label','?'))
print('  vault_path:   ', c.get('vault_path','?'))
" 2>/dev/null || echo '  (could not parse)')"
    return 0
  fi
  warn "config.json missing — need to run sync_chats.py init."
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "  ${C_DIM}dry-run: would prompt for --label and --vault${C_RESET}"
    STEPS_SKIPPED=$((STEPS_SKIPPED+1))
    return 0
  fi
  local label vault
  read -r -p "  Machine label (short, e.g. mbp, studio): " label
  if [[ -z "$label" ]]; then
    err "Label cannot be empty."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
  read -r -p "  Absolute path to your Obsidian vault: " vault
  if [[ -z "$vault" || ! -d "$vault" ]]; then
    err "Vault path must exist and be absolute. Got: '$vault'"
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
  run_cmd "python3 '$CLAUDE_CHAT_HOME/sync_chats.py' init --label '$label' --vault '$vault'"
  STEPS_INSTALLED=$((STEPS_INSTALLED+1))
}

check_session_end_hook() {
  step "~/.claude/settings.json SessionEnd hook"

  if [[ ! -f "$SETTINGS_JSON" ]]; then
    warn "$SETTINGS_JSON does not exist yet (Claude Code may not have been run)."
    echo "  Skip for now and re-run this installer after launching Claude Code once."
    STEPS_SKIPPED=$((STEPS_SKIPPED+1))
    return 0
  fi

  if ! command -v jq >/dev/null 2>&1; then
    err "jq required for this step but not installed. See earlier step."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi

  # Does our hook already exist?
  if jq -e --arg cmd "$HOOK_COMMAND" \
       '.hooks.SessionEnd // [] | map(.hooks // []) | flatten | any(.command == $cmd)' \
       "$SETTINGS_JSON" >/dev/null 2>&1; then
    ok "sync-chats SessionEnd hook already installed"
    return 0
  fi

  warn "sync-chats SessionEnd hook not installed."
  local existing
  existing="$(jq '.hooks.SessionEnd // [] | length' "$SETTINGS_JSON")"
  dim "  Existing SessionEnd array has ${existing} entry/entries — will APPEND (not replace)."

  if ask_yn "Install the hook now?" default_yes; then
    local backup="${SETTINGS_JSON}.bak-preInstall-${TIMESTAMP}"
    run_cmd "cp '$SETTINGS_JSON' '$backup'"
    # Atomic jq-append pattern (see reference memory).
    local payload='{"hooks":[{"type":"command","command":"'"$HOOK_COMMAND"'","timeout":60}]}'
    run_cmd "jq '.hooks.SessionEnd = (.hooks.SessionEnd // []) + [${payload}]' '$SETTINGS_JSON' > '${SETTINGS_JSON}.tmp'"
    if [[ $DRY_RUN -eq 0 ]]; then
      if python3 -m json.tool <"${SETTINGS_JSON}.tmp" >/dev/null 2>&1; then
        run_cmd "mv '${SETTINGS_JSON}.tmp' '$SETTINGS_JSON'"
        ok "hook installed; backup at $backup"
        STEPS_INSTALLED=$((STEPS_INSTALLED+1))
      else
        err "Generated settings.json did not parse. Left original untouched."
        rm -f "${SETTINGS_JSON}.tmp"
        STEPS_BLOCKED=$((STEPS_BLOCKED+1))
        return 1
      fi
    else
      STEPS_SKIPPED=$((STEPS_SKIPPED+1))
    fi
  else
    STEPS_SKIPPED=$((STEPS_SKIPPED+1))
  fi
}

sanity_smoke_test() {
  step "Smoke test — scan + status"
  if [[ ! -f "$CLAUDE_CHAT_HOME/config.json" ]]; then
    dim "  Skipping — config.json not present (see earlier step)."
    return 0
  fi
  if python3 "$CLAUDE_CHAT_HOME/sync_chats.py" scan >/dev/null 2>&1; then
    ok "scan command works"
  else
    err "scan command failed."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
  if python3 "$CLAUDE_CHAT_HOME/sync_chats.py" status >/dev/null 2>&1; then
    ok "status command works"
  else
    err "status command failed."
    STEPS_BLOCKED=$((STEPS_BLOCKED+1))
    return 1
  fi
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
  echo "${C_BOLD}claude-chat + sync_chats installer${C_RESET}"
  echo "${C_DIM}repo root: $REPO_ROOT${C_RESET}"
  echo "${C_DIM}state dir: $CLAUDE_CHAT_HOME${C_RESET}"
  [[ $DRY_RUN -eq 1 ]] && echo "${C_WARN}[dry-run — no changes will be made]${C_RESET}"
  [[ $AUTO_YES -eq 1 ]] && echo "${C_WARN}[auto-yes — every prompt answered YES]${C_RESET}"

  # Run checks. Each returns non-zero on hard block; we continue through the
  # list regardless so the final report shows everything.
  check_python        || true
  check_obsidian      || true
  check_claude_code   || true
  check_jq            || true
  check_pipx          || true
  check_mempalace     || true
  check_claude_chat_home || true
  check_symlink       || true
  check_claude_chat_export || true
  check_config        || true
  check_session_end_hook || true
  sanity_smoke_test   || true

  # ─── Report ────────────────────────────────────────────────────────────────
  echo ""
  echo "${C_BOLD}── Summary ──${C_RESET}"
  local installed_label="installed this run"
  local skipped_label="skipped"
  if [[ $DRY_RUN -eq 1 ]]; then
    installed_label="would install"
    skipped_label="would skip"
  fi
  echo "  ${C_OK}${STEPS_OK} already in place${C_RESET}"
  echo "  ${C_OK}${STEPS_INSTALLED} ${installed_label}${C_RESET}"
  echo "  ${C_WARN}${STEPS_SKIPPED} ${skipped_label}${C_RESET}"
  echo "  ${C_ERR}${STEPS_BLOCKED} blocked${C_RESET}"
  echo ""

  if [[ $STEPS_BLOCKED -gt 0 ]]; then
    warn "Some steps are blocked — address the items above and re-run ./install.sh."
    exit 1
  elif [[ $STEPS_SKIPPED -gt 0 ]]; then
    warn "Optional steps skipped — setup is functional but some features disabled."
    echo "  Re-run ./install.sh any time to revisit skipped items."
    exit 0
  else
    ok "All steps complete. End a Claude Code session to trigger your first hook fire."
    echo "  Verify via:  cat ~/.claude-chat/last_run.json | python3 -m json.tool"
    exit 0
  fi
}

main "$@"
