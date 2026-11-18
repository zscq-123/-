#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
(cd apps/api && .venv/bin/python -m pytest -q)
apps/api/.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
(cd apps/web && npm run typecheck && npm run build)
