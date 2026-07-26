#!/usr/bin/env bash
# Step 4: Copy the portfolio skill wholesale to ~/.claude/skills/portfolio/.
# Self-contained after copy - no dependency on this repo's location surviving.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [4/4] Installing the portfolio skill globally"
rm -rf "$HOME/.claude/skills/portfolio"
mkdir -p "$HOME/.claude/skills/portfolio"
cp -r "$REPO_DIR/skills/portfolio/." "$HOME/.claude/skills/portfolio/"
echo "    installed to $HOME/.claude/skills/portfolio/"
