#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd -P)"
run_dir="$project_dir/.run"
mkdir -p "$run_dir"

if [[ ! -x "$project_dir/backend/.venv/bin/uvicorn" || ! -d "$project_dir/frontend/node_modules" ]]; then
  echo "Run ./scripts/setup.sh first." >&2
  exit 1
fi

for pid_file in "$run_dir/backend.pid" "$run_dir/frontend.pid" "$run_dir/worker.pid"; do
  if [[ -f "$pid_file" ]] && kill -0 "$(<"$pid_file")" 2>/dev/null; then
    echo "Company Search is already running. Use ./scripts/stop.sh first." >&2
    exit 1
  fi
done

docker compose -f "$project_dir/docker-compose.yml" up -d db
(
  cd "$project_dir/backend"
  nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$run_dir/backend.log" 2>&1 &
  echo $! >"$run_dir/backend.pid"
)
(
  cd "$project_dir/backend"
  nohup .venv/bin/python -m app.worker >"$run_dir/worker.log" 2>&1 &
  echo $! >"$run_dir/worker.pid"
)
(
  cd "$project_dir/frontend"
  nohup ./node_modules/.bin/vite --host 127.0.0.1 >"$run_dir/frontend.log" 2>&1 &
  echo $! >"$run_dir/frontend.pid"
)

for _ in {1..30}; do
  worker_pid="$(<"$run_dir/worker.pid")"
  if ! kill -0 "$worker_pid" 2>/dev/null; then
    echo "Worker exited during startup. Check $run_dir/worker.log" >&2
    exit 1
  fi
  if curl --fail --silent http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "Company Search is running at http://127.0.0.1:5173"
    exit 0
  fi
  sleep 1
done

echo "Backend did not become healthy. Check $run_dir/backend.log" >&2
exit 1
