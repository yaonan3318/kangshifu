#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd -P)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This setup script is intended for macOS." >&2
  exit 1
fi

for command_name in node npm docker; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
done

python_command=""
for candidate in python python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    candidate_version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [[ "$candidate_version" == "3.12" || "$candidate_version" == "3.13" ]]; then
      python_command="$(command -v "$candidate")"
      python_version="$candidate_version"
      break
    fi
  fi
done
if [[ -z "$python_command" ]]; then
  echo "Python 3.12 or 3.13 is required in the active environment." >&2
  echo "Create and activate an isolated environment, for example: conda create -n company-search python=3.13" >&2
  exit 1
fi
echo "Using Python $python_version from $python_command"

if ! "$python_command" -c 'import shutil; from pathlib import Path; raise SystemExit(0 if shutil.disk_usage(Path.home()).free >= 10 * 1024**3 else 1)'; then
  echo "At least 10 GB of free disk space is required for the local embedding model." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install libmagic: https://brew.sh" >&2
  exit 1
fi
for formula in libmagic tesseract tesseract-lang; do
  brew list "$formula" >/dev/null 2>&1 || brew install "$formula"
done

venv_python="$project_dir/backend/.venv/bin/python"
if [[ -x "$venv_python" ]]; then
  venv_version="$("$venv_python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "$venv_version" != "3.12" && "$venv_version" != "3.13" ]]; then
    echo "Existing backend/.venv uses Python $venv_version." >&2
    echo "Move backend/.venv aside, then run setup again; other project environments are not affected." >&2
    exit 1
  fi
  echo "Reusing backend/.venv with Python $venv_version"
else
  "$python_command" -m venv "$project_dir/backend/.venv"
fi
"$project_dir/backend/.venv/bin/python" -m pip install --upgrade pip
"$project_dir/backend/.venv/bin/python" -m pip install -e "$project_dir/backend"

if [[ ! -f "$project_dir/backend/.env" ]]; then
  cp "$project_dir/.env.example" "$project_dir/backend/.env"
  sed -i '' "s|/Users/your-name|$HOME|" "$project_dir/backend/.env"
fi

npm --prefix "$project_dir/frontend" install
docker compose -f "$project_dir/docker-compose.yml" up -d db

for _ in {1..30}; do
  if docker compose -f "$project_dir/docker-compose.yml" exec -T db pg_isready -U company_search -d company_search >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose -f "$project_dir/docker-compose.yml" exec -T db pg_isready -U company_search -d company_search >/dev/null

(cd "$project_dir/backend" && .venv/bin/alembic upgrade head)
(cd "$project_dir/backend" && .venv/bin/python -m app.download_models)
if ! tesseract --list-langs 2>/dev/null | grep -qx "chi_sim"; then
  echo "Simplified Chinese OCR language chi_sim is unavailable after installing tesseract-lang." >&2
  exit 1
fi
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed; document search works, but local RAG answers require https://ollama.com/download/mac"
else
  echo "Run ./scripts/check-llm.sh to verify the local Qwen model."
fi
echo "Setup complete. Run ./scripts/start.sh"
