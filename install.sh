#!/usr/bin/env bash
# Install scientific-deep-research as an agent skill.
# Usage: ./install.sh [target-skills-dir]
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME/.agents/skills}/scientific-deep-research"

mkdir -p "$(dirname "$TARGET")"
if [ -e "$TARGET" ] && [ "$TARGET" != "$SRC" ]; then
  echo "Target $TARGET exists — updating."
  rm -rf "$TARGET"
fi
if [ "$TARGET" != "$SRC" ]; then
  cp -r "$SRC" "$TARGET"
  rm -rf "$TARGET/.git"
fi
echo "Installed to $TARGET"

# Claude Code: symlink into ~/.claude/skills if that convention exists
if [ -d "$HOME/.claude" ]; then
  mkdir -p "$HOME/.claude/skills"
  ln -sfn "$TARGET" "$HOME/.claude/skills/scientific-deep-research"
  echo "Symlinked for Claude Code: ~/.claude/skills/scientific-deep-research"
fi

cat <<'EOF'

For CLIs without native skill support (Codex, Antigravity, ...), add this
to your project's AGENTS.md (or equivalent rules file):

  ## /sdr — Scientific Deep Research
  When the user types /sdr <topic> or asks for a deep research with
  downloaded papers: read and follow
  ~/.agents/skills/scientific-deep-research/SKILL.md

Done. Try: /sdr <your topic>
EOF
