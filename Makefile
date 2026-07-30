.PHONY: install dev-backend dev-frontend test lint typecheck verify docker-up docker-down

install:
	python3 -m venv backend/.venv
	backend/.venv/bin/python -m pip install --upgrade pip
	backend/.venv/bin/python -m pip install -e 'backend[dev]'
	cd frontend && pnpm install --frozen-lockfile

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && pnpm dev

test:
	cd backend && .venv/bin/pytest -v
	cd frontend && pnpm test

lint:
	cd backend && .venv/bin/ruff check .
	cd backend && .venv/bin/ruff format --check .
	cd frontend && pnpm lint

typecheck:
	cd backend && .venv/bin/mypy
	cd frontend && pnpm typecheck

verify: test lint typecheck
	cd frontend && pnpm build

docker-up:
	docker compose up --build

docker-down:
	docker compose down
