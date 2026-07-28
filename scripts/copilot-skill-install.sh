#!/usr/bin/env bash
# Copy the portfolio skill wholesale to GitHub Copilot's global (personal,
# cross-repo) skills directory. Mirrors scripts/skill-install.sh /
# scripts/codex-skill-install.sh, but for Copilot - see
# https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
# for Copilot's Agent Skills format (same SKILL.md name+description
# frontmatter as Claude/Codex). Unlike Claude Code, Copilot needs no separate
# registration step for skills - it detects the files directly.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COPILOT_SKILLS_DIR="$HOME/.copilot/skills/portfolio"

echo "==> Installing the portfolio skill globally for Copilot"
rm -rf "$COPILOT_SKILLS_DIR"
mkdir -p "$COPILOT_SKILLS_DIR"
cp -r "$REPO_DIR/skills/portfolio/." "$COPILOT_SKILLS_DIR/"
echo "    installed to $COPILOT_SKILLS_DIR/"
