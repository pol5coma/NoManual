#!/usr/bin/env bash
# Start the full local stack.
#
#   Postgres + Redis  -> Docker, in the background
#   API + Celery      -> foreground, logs interleaved in this terminal
#
# Ctrl+C stops everything.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

set -euo pipefail
cd "$(dirname "$0")"

echo "==> Postgres and Redis"
docker compose up -d --wait

echo "==> API on http://localhost:8000"
uv run uvicorn nomanual.main:app --reload &
API_PID=$!

# watchmedo restarts the worker on code changes: celery has no --reload of its
# own, and a stale worker silently runs the previous version of a task.
echo "==> Celery worker"
uv run watchmedo auto-restart --directory=backend --pattern='*.py' --recursive -- \
    celery -A nomanual.worker.celery_app worker --pool=solo --loglevel=info &

WORKER_PID=$!

# Without this, Ctrl+C kills the script and leaves both children orphaned,
# still holding their ports.
trap 'echo; echo "==> Stopping"; kill $API_PID $WORKER_PID 2>/dev/null' EXIT INT TERM

wait
