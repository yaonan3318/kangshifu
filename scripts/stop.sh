#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd -P)"
run_dir="$project_dir/.run"

stop_pid() {
  local pid_file="$1"
  local expected="$2"
  [[ -f "$pid_file" ]] || return 0
  local pid
  pid="$(<"$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    local command_line
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$command_line" == *"$expected"* ]]; then
      kill "$pid"
    else
      echo "Refusing to stop PID $pid because it is not $expected." >&2
    fi
  fi
  rm -f "$pid_file"
}

stop_pid "$run_dir/backend.pid" "uvicorn"
stop_pid "$run_dir/frontend.pid" "vite"
docker compose -f "$project_dir/docker-compose.yml" stop db
echo "Company Search stopped."

