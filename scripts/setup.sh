#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd -P)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This setup script is intended for macOS." >&2
  exit 1
fi

for command_name in python3 node npm docker; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
done

python_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$python_version" != "3.12" && "$python_version" != "3.13" ]]; then
  echo "Python 3.12 or 3.13 is required; found $python_version." >&2
  exit 1
fi

if ! python3 -c 'import shutil; from pathlib import Path; raise SystemExit(0 if shutil.disk_usage(Path.home()).free >= 5 * 1024**3 else 1)'; then
  echo "At least 5 GB of free disk space is required." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install libmagic: https://brew.sh" >&2
  exit 1
fi
for formula in libmagic tesseract tesseract-lang; do
  brew list "$formula" >/dev/null 2>&1 || brew install "$formula"
done

python3 -m venv "$project_dir/backend/.venv"
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
if ! tesseract --list-langs 2>/dev/null | grep -qx "chi_sim"; then
  echo "Simplified Chinese OCR language chi_sim is unavailable after installing tesseract-lang." >&2
  exit 1
fi
echo "Setup complete. Run ./scripts/start.sh"
