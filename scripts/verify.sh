#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$repo_dir/backend"
.venv/bin/pytest -m "not integration" -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy

cd "$repo_dir/frontend"
pnpm test
pnpm lint
pnpm typecheck
pnpm build
