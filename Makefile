.PHONY: install dev-backend dev-frontend dev-replay-worker test lint typecheck verify verify-postgres verify-replay verify-replay-ffmpeg verify-replay-postgres smoke-riot smoke-replay docker-up docker-down e2e-replay-compose

install:
	python3 -m venv backend/.venv
	backend/.venv/bin/python -m pip install --upgrade pip
	backend/.venv/bin/python -m pip install -e 'backend[dev]'
	cd frontend && pnpm install --frozen-lockfile

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000 --no-access-log

dev-frontend:
	cd frontend && pnpm dev

dev-replay-worker:
	cd backend && .venv/bin/python -m app.workers.replay

test:
	cd backend && .venv/bin/pytest -m "not integration and not replay_ffmpeg" -v
	cd frontend && pnpm test

lint:
	cd backend && .venv/bin/ruff check .
	cd backend && .venv/bin/ruff format --check .
	cd frontend && pnpm lint

typecheck:
	cd backend && .venv/bin/mypy
	cd frontend && pnpm typecheck

verify: test lint typecheck
	git diff --check
	cd frontend && pnpm build

verify-postgres:
	test -n "$$TEST_DATABASE_URL"
	cd backend; DATABASE_URL=$$TEST_DATABASE_URL .venv/bin/alembic upgrade head
	cd backend; .venv/bin/pytest -m integration -v

verify-replay:
	cd backend && .venv/bin/pytest tests/test_replay_*.py -m "not integration and not replay_ffmpeg" -v
	cd frontend && pnpm test -- replay-api-client.test.ts replay-storage.test.ts replay-section.test.tsx

verify-replay-ffmpeg:
	cd backend && .venv/bin/pytest tests/integration/test_replay_ffmpeg.py -m replay_ffmpeg -v

verify-replay-postgres:
	test -n "$$TEST_DATABASE_URL"
	cd backend; DATABASE_URL=$$TEST_DATABASE_URL .venv/bin/alembic upgrade head
	cd backend; .venv/bin/pytest tests/integration -m "integration and not replay_ffmpeg" -v

smoke-riot:
	PYTHONPATH=backend backend/.venv/bin/python scripts/smoke_riot.py

smoke-replay:
	PYTHONPATH=backend backend/.venv/bin/python scripts/smoke_replay.py

docker-up:
	docker compose up --build

docker-down:
	docker compose down

e2e-replay-compose:
	./scripts/e2e_replay_compose.sh
