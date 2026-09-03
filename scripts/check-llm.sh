#!/usr/bin/env bash
set -euo pipefail

model_name="${COMPANY_SEARCH_OLLAMA_MODEL:-qwen3:8b}"
base_url="${COMPANY_SEARCH_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Download it from https://ollama.com/download/mac" >&2
  exit 1
fi

if ! curl --fail --silent "$base_url/api/tags" >/dev/null 2>&1; then
  echo "Ollama is not responding at $base_url. Open the Ollama macOS application first." >&2
  exit 1
fi

if ! ollama list | awk 'NR > 1 {print $1}' | grep -Fxq "$model_name"; then
  echo "Local model $model_name is not installed. Run: ollama pull $model_name" >&2
  exit 1
fi

echo "Local RAG model is ready: $model_name"
