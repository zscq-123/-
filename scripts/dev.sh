#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
if [[ ! -x apps/api/.venv/bin/python || ! -d apps/web/node_modules ]]; then
  printf '%s\n' '请先运行 ./scripts/setup.sh。' >&2
  exit 1
fi
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
export APP_MODE="${APP_MODE:-demo}"
export DEMO_PASSWORD="${DEMO_PASSWORD:-local-demo-change-me}"
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$BACKEND_PID" ]] || kill "$BACKEND_PID" 2>/dev/null || true
  [[ -z "$FRONTEND_PID" ]] || kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM
(cd apps/api && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!
(cd apps/web && exec node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3000) &
FRONTEND_PID=$!
printf '%s\n' '触屏接待：http://127.0.0.1:3000' '工作人员后台：http://127.0.0.1:3000/staff' 'API：http://127.0.0.1:8000/docs' '按 Ctrl+C 停止本脚本启动的服务。'
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done
printf '%s\n' '一个服务已退出，停止另一个服务；请检查上方错误。' >&2
exit 1
