#!/bin/bash
# Fleet Hive gateway launcher — reads keys from your shell env (source ~/.env
# first, per the repo's root .env.example convention), then execs LiteLLM.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG="${HIVE_GATEWAY_CONFIG:-$SCRIPT_DIR/gateway-config.yaml}"
PORT="${HIVE_GATEWAY_PORT:-4101}"

if [ ! -f "$CONFIG" ]; then
  echo "launch-gateway: $CONFIG not found — copy gateway-config.example.yaml to" \
       "gateway-config.yaml and fill in your machine hostnames first." >&2
  exit 1
fi

: "${HIVE_MASTER_KEY:?Set HIVE_MASTER_KEY before starting the gateway to any secret string; hive.py callers set the matching HIVE_KEY.}"
export HIVE_MASTER_KEY

if ! command -v litellm >/dev/null 2>&1; then
  echo "launch-gateway: 'litellm' not found — pip install 'litellm[proxy]'" >&2
  exit 1
fi

exec litellm --config "$CONFIG" --port "$PORT" --num_workers 2
