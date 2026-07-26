#!/usr/bin/env bash
# Interactive environment setup - prompts for secrets and writes .env
set -euo pipefail

ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mcp_servers/portfolio_tools/.env"
ENV_EXAMPLE="$(dirname "$ENV_FILE")/.env.example"

echo "==> Portfolio environment setup"
echo "    This will write secrets to: $ENV_FILE"
echo "    Press Enter to skip any value and leave it blank."
echo ""

# Read existing value (if any) to show as default
existing_key=""
if [ -f "$ENV_FILE" ]; then
  existing_key="$(grep -E '^FINNHUB_API_KEY=' "$ENV_FILE" | cut -d= -f2- || true)"
fi

if [ -n "$existing_key" ]; then
  echo "    Finnhub API key (free at https://finnhub.io/register)"
  printf "    Current value: %.4s****  Leave blank to keep it: " "$existing_key"
else
  echo "    Finnhub API key (free at https://finnhub.io/register)"
  printf "    Leave blank to skip (pipeline still works via yfinance): "
fi

read -r input_key

# Resolve final value
if [ -n "$input_key" ]; then
  final_key="$input_key"
elif [ -n "$existing_key" ]; then
  final_key="$existing_key"
else
  final_key=""
fi

# Write .env
{
  echo "FINNHUB_API_KEY=${final_key}"
} > "$ENV_FILE"

echo ""
if [ -n "$final_key" ]; then
  printf "    Written: FINNHUB_API_KEY=%.4s****\n" "$final_key"
else
  echo "    Written: FINNHUB_API_KEY= (blank - yfinance fallback will be used)"
fi
echo ""
echo "Done. Re-run 'make bootstrap' if the server is already running to pick up the new key."
