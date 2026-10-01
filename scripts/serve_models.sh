#!/usr/bin/env bash
# Serve the local LLMs: llama-server in router mode on 127.0.0.1 with the
# presets in models.ini. It starts with no model loaded. The first request that
# names a model loads it, and with --models-max 1 a request naming the other
# model unloads the current one first.
#
# Usage: scripts/serve_models.sh   (reads .env; copy .env.example first)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
    echo "No .env: copy .env.example to .env first." >&2
    exit 1
fi
set -a
# shellcheck source=/dev/null
source .env
set +a

exec "$LLAMA_SERVER" --models-preset models.ini --models-max 1 \
    --host 127.0.0.1 --port "$LLAMA_PORT"
