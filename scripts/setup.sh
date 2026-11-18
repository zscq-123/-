#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf '%s\n' '请安装 Python 3.12，或设置 PYTHON_BIN 指向兼容解释器。' >&2
  exit 1
fi
"$PYTHON_BIN" -c 'import sys; assert (3, 12) <= sys.version_info < (3, 14), "请使用 Python 3.12 或 3.13；3.14 尚未验证依赖兼容性"'
"$PYTHON_BIN" -m venv apps/api/.venv
apps/api/.venv/bin/python -m pip install -r apps/api/requirements.txt
(cd apps/web && npm ci)
printf '%s\n' '依赖已安装。可复制 .env.example 为 .env 后运行 ./scripts/dev.sh。'
