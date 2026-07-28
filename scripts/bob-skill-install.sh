#!/usr/bin/env bash
# Copy the portfolio skill wholesale to ~/.bob/skills/portfolio/.
# Self-contained after copy - no dependency on this repo's location surviving.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [bob 2/2] Installing the portfolio skill globally for IBM Bob"
rm -rf "$HOME/.bob/skills/portfolio"
mkdir -p "$HOME/.bob/skills/portfolio"
cp -r "$REPO_DIR/skills/portfolio/." "$HOME/.bob/skills/portfolio/"
echo "    installed to $HOME/.bob/skills/portfolio/"
