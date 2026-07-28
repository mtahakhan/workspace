#!/usr/bin/env bash
# Copy the portfolio skill wholesale to Codex's global skills directory.
# Mirrors scripts/skill-install.sh, but for Codex instead of Claude Code -
# Codex's global (cross-repo) skills directory is $HOME/.agents/skills/, per
# https://developers.openai.com/codex/skills. Unlike Claude Code, Codex needs
# no separate registration step for skills - it detects the files directly;
# restart Codex if a change doesn't show up.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_SKILLS_DIR="$HOME/.agents/skills/portfolio"

echo "==> Installing the portfolio skill globally for Codex"
rm -rf "$CODEX_SKILLS_DIR"
mkdir -p "$CODEX_SKILLS_DIR"
cp -r "$REPO_DIR/skills/portfolio/." "$CODEX_SKILLS_DIR/"
echo "    installed to $CODEX_SKILLS_DIR/"
