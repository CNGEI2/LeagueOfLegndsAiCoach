# Task 4 Report: CI, Verification Script, and Complete README

## Status

Task 4 adds the canonical non-Docker verification script, GitHub Actions quality gates, and a bilingual root README. The obsolete `frontend/README.md` scaffold has been removed so the root README is the single authoritative setup guide.

## Delivered Files

- Added `.github/workflows/ci.yml`.
  - Separate `backend` and `frontend` jobs.
  - Backend: Python 3.11, editable `backend[dev]` install, pytest, Ruff check, Ruff format check, and MyPy.
  - Frontend: pnpm 11.9.0, Node.js 22, frozen lockfile install, Vitest, ESLint, TypeScript, and production build.
- Added executable `scripts/verify.sh` as the canonical non-Docker quality gate.
- Added bilingual `README.md` covering setup, Docker, verification, environment variables, health endpoints, repository structure, MVP limits, Riot disclaimer, and Phase 2.
- Removed `frontend/README.md`, the obsolete generated Next.js scaffold documentation.
- Added this acceptance-evidence report.

## Commands Run and Results

| Command | Result |
| --- | --- |
| `git diff --check` before verification | Passed; no whitespace errors. |
| `bash -n scripts/verify.sh` | Passed. |
| `stat -f '%Sp %N' scripts/verify.sh` | Passed; script mode is `-rwxr-xr-x`. |
| `./scripts/verify.sh` in the restricted sandbox | Backend and frontend checks passed through TypeScript, but Next.js production build was blocked by the sandbox's `Operation not permitted` error while binding a local process port. |
| `./scripts/verify.sh` outside the restricted sandbox | Passed: backend pytest 5/5, Ruff check, Ruff format check (16 files), MyPy (12 source files), frontend Vitest 6/6 across 3 files, ESLint, TypeScript, and Next.js production build. |
| `make verify` outside the restricted sandbox | Passed with the same gates and counts: backend 5/5 tests; frontend 6/6 tests across 3 files; no Ruff, MyPy, ESLint, TypeScript, or build failures. |
| `git diff --check` after documentation/CI review | Passed; no whitespace errors. |
| `git diff --cached --check` | Passed; no staged whitespace errors. |
| `git status --short` before commit | Listed only the five Task 4 paths: workflow, report, root README, deleted scaffold README, and verification script. |
| `git status --short --branch` after commit | Passed; `feature/phase-1-foundation` is clean. |
| `git log --oneline -5` after commit | Passed; shows the Task 4 commit followed by the Task 3 and Task 2 commits. |
| `command -v docker` | Docker CLI unavailable on this Mac. |

The first restricted build failure was investigated before rerun. Its panic log identifies the environment-level cause as process creation and port binding denied by the sandbox; the identical command passes outside that sandbox. No application change was made for that host restriction.

## Docker Verification Status

Docker Compose build, service startup, and endpoint probes were **not verified** on this Mac because no Docker CLI is available. The README deliberately presents the Compose commands as documented instructions rather than a completed local verification. No Docker success claim is made.

## Local Start and Endpoint Commands

```bash
cp .env.example .env
make install
make dev-backend
make dev-frontend
```

Open `http://localhost:3000`, `http://localhost:3000/zh-CN`, or `http://localhost:3000/en-US`. The documented backend probes are `GET /health/live` and `GET /health/ready`.

## Phase 1 File Inventory by Task

### Task 1: FastAPI health foundation

- `.gitignore`
- `backend/app/__init__.py`
- `backend/app/api/__init__.py`
- `backend/app/api/health.py`
- `backend/app/core/__init__.py`
- `backend/app/core/config.py`
- `backend/app/core/database.py`
- `backend/app/core/errors.py`
- `backend/app/core/request_id.py`
- `backend/app/main.py`
- `backend/app/schemas/__init__.py`
- `backend/app/schemas/errors.py`
- `backend/app/schemas/health.py`
- `backend/pyproject.toml`
- `backend/tests/__init__.py`
- `backend/tests/conftest.py`
- `backend/tests/test_config.py`
- `backend/tests/test_health.py`
- `docs/superpowers/plans/2026-07-30-lol-ai-coach-phase-1-foundation.md`

### Task 2: Bilingual frontend foundation

- `.superpowers/sdd/2026-07-30-lol-ai-coach-phase-1-foundation/task-2-brief.md`
- `.superpowers/sdd/2026-07-30-lol-ai-coach-phase-1-foundation/task-2-report.md`
- `frontend/.gitignore`
- `frontend/eslint.config.mjs`
- `frontend/next.config.ts`
- `frontend/package.json`
- `frontend/pnpm-lock.yaml`
- `frontend/pnpm-workspace.yaml`
- `frontend/postcss.config.mjs`
- `frontend/public/file.svg`
- `frontend/public/globe.svg`
- `frontend/public/next.svg`
- `frontend/public/vercel.svg`
- `frontend/public/window.svg`
- `frontend/src/app/[locale]/layout.tsx`
- `frontend/src/app/[locale]/page.tsx`
- `frontend/src/app/favicon.ico`
- `frontend/src/app/globals.css`
- `frontend/src/components/language-switcher.tsx`
- `frontend/src/components/riot-search-form.tsx`
- `frontend/src/i18n/en-US.ts`
- `frontend/src/i18n/locales.ts`
- `frontend/src/i18n/messages.ts`
- `frontend/src/i18n/zh-CN.ts`
- `frontend/src/proxy.ts`
- `frontend/src/test/setup.ts`
- `frontend/tests/home-page.test.tsx`
- `frontend/tests/i18n.test.ts`
- `frontend/tests/riot-search-form.test.tsx`
- `frontend/tsconfig.json`
- `frontend/vitest.config.ts`

### Task 3: Containerized local environment

- `.env.example`
- `.gitignore`
- `Makefile`
- `backend/Dockerfile`
- `backend/tests/test_config.py`
- `docker-compose.yml`
- `frontend/.dockerignore`
- `frontend/Dockerfile`
- `docs/superpowers/plans/2026-07-30-lol-ai-coach-phase-1-foundation.md`

### Task 4: CI, verification, and documentation

- `.github/workflows/ci.yml`
- `scripts/verify.sh`
- `README.md`
- `frontend/README.md` (deleted)
- `.superpowers/sdd/2026-07-30-lol-ai-coach-phase-1-foundation/task-4-report.md`

## Current Product Limitations

- No Riot player lookup, account data, Match V5 data, Data Dragon content, scoring, accounts, trends, or AI review is implemented.
- Phase 1 uses no fake match data.
- Data-only analysis can report recorded statistics and event sequence; it cannot establish claims about positioning, mechanics, or player intent.
- Replay analysis is a later, separate evidence source.
- Docker Compose remains unverified on this Mac because Docker CLI is absent.

## Next Recommendation

Proceed to Phase 2 only after retaining this non-Docker verification evidence. Phase 2 should integrate Riot Account, Summoner, Match V5, and localized Data Dragon behind mocked external-service tests; keep all credentials server-only and empty in committed examples.
