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

# --- Data directory -----------------------------------------------------------
# Where the pipeline keeps everything it reads and writes. Kept out of the package
# on purpose, so the data can live on a synced/encrypted/backed-up volume without
# touching code. Blank = the in-repo default.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DATA_DIR="$REPO_DIR/data"

existing_data_dir=""
if [ -f "$ENV_FILE" ]; then
  existing_data_dir="$(grep -E '^PORTFOLIO_DATA_DIR=' "$ENV_FILE" | cut -d= -f2- || true)"
fi

echo ""
echo "    Data directory - where your portfolio data is stored"
echo "      personal/    your transactions, positions, price history, news, reports"
echo "      impersonal/  shared ticker lookup tables"
if [ -n "$existing_data_dir" ]; then
  printf "    Current value: %s\n    Leave blank to keep it: " "$existing_data_dir"
else
  printf "    Leave blank to use the default (%s): " "$DEFAULT_DATA_DIR"
fi
read -r input_data_dir

if [ -n "$input_data_dir" ]; then
  final_data_dir="$input_data_dir"
elif [ -n "$existing_data_dir" ]; then
  final_data_dir="$existing_data_dir"
else
  final_data_dir=""
fi

# Expand a leading ~ so the Python side gets an absolute path either way
case "$final_data_dir" in
  "~"|"~/"*) final_data_dir="${HOME}${final_data_dir#\~}" ;;
esac

# Write .env
{
  echo "FINNHUB_API_KEY=${final_key}"
  echo "PORTFOLIO_DATA_DIR=${final_data_dir}"
} > "$ENV_FILE"

echo ""
if [ -n "$final_key" ]; then
  printf "    Written: FINNHUB_API_KEY=%.4s****\n" "$final_key"
else
  echo "    Written: FINNHUB_API_KEY= (blank - yfinance fallback will be used)"
fi
if [ -n "$final_data_dir" ]; then
  echo "    Written: PORTFOLIO_DATA_DIR=$final_data_dir"
  if [ ! -d "$final_data_dir" ]; then
    mkdir -p "$final_data_dir/personal" "$final_data_dir/impersonal"
    echo "             (created, with personal/ and impersonal/)"
  fi
else
  echo "    Written: PORTFOLIO_DATA_DIR= (blank - using default $DEFAULT_DATA_DIR)"
fi
echo ""
echo "Existing data is NOT moved - if you changed the directory, move its contents"
echo "yourself, keeping the personal/ and impersonal/ subdirectories intact."
echo ""
echo "Done. Restart the server to pick up changes:"
echo "  kill \$(cat $REPO_DIR/mcp_servers/portfolio_tools/.server.pid) && make server-start"
