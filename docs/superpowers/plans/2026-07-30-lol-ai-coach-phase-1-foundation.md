# LoL AI Coach Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable, bilingual LoL AI Coach monorepo foundation with a tested FastAPI health service, a tested Next.js search homepage, Docker Compose, CI, and complete developer documentation.

**Architecture:** The monorepo contains an independently runnable Next.js frontend and FastAPI backend. The backend owns configuration, CORS, PostgreSQL connectivity, and health/readiness probes; the frontend owns locale negotiation and the non-functional Phase 1 Riot ID form. Docker Compose provides the authoritative PostgreSQL-backed integration environment while isolated backend tests use an injected fake database.

**Tech Stack:** Next.js 16 App Router, React, TypeScript 5, Tailwind CSS 4, pnpm, Vitest, Testing Library, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 17, Pytest, Ruff, MyPy, Docker Compose, GitHub Actions.

## Global Constraints

- Support Node.js 20.9 or newer; Docker images use Node.js 22.
- Support Python 3.11 or newer; Docker images use Python 3.11.
- Use `pnpm` for frontend dependencies and commit `pnpm-lock.yaml`.
- Use a Python virtual environment and `pip`; commit no virtual-environment files.
- Use Next.js App Router, TypeScript strict mode, Tailwind CSS, and ESLint.
- Use FastAPI, Pydantic schemas, SQLAlchemy async database access, Ruff, MyPy, and Pytest.
- Supported locales are exactly `zh-CN` and `en-US`.
- The language switch changes the whole UI; Phase 1 does not call Riot or OpenAI.
- Do not add authentication, match fixtures, fake match data, Riot calls, OpenAI calls, Redis, task workers, video support, or unused domain models.
- Never hardcode API keys; document empty key variables in `.env.example`.
- Public Python functions have type annotations; frontend production code contains no `any`.
- Every task follows red-green-refactor, runs focused tests, then commits one coherent change.
- The approved design remains authoritative: `docs/superpowers/specs/2026-07-30-lol-ai-coach-mvp-design.md`.

## Planned File Map

```text
lol-ai-coach/
├── .env.example                         documented local environment
├── .gitignore                           generated/local file exclusions
├── Makefile                             uniform developer commands
├── README.md                            setup, run, test, and limitations
├── docker-compose.yml                   frontend, backend, and PostgreSQL
├── .github/workflows/ci.yml             backend and frontend quality gates
├── scripts/verify.sh                    one-command local verification
├── backend/
│   ├── Dockerfile                       Python service image
│   ├── pyproject.toml                   dependencies and quality configuration
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                      FastAPI application factory/lifespan
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── health.py                live and ready routes
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py                environment settings
│   │   │   └── database.py              async engine, ping, and disposal
│   │   └── schemas/
│   │       ├── __init__.py
│   │       └── health.py                health response schema
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                  app client and fake database
│       ├── test_config.py               environment parsing contract
│       └── test_health.py               health endpoint behavior
└── frontend/
    ├── Dockerfile                       Next.js standalone image
    ├── package.json                     scripts and dependencies
    ├── pnpm-lock.yaml                   exact frontend dependency lock
    ├── next.config.ts                   standalone output
    ├── tsconfig.json                    strict TypeScript settings
    ├── eslint.config.mjs                ESLint configuration
    ├── postcss.config.mjs               Tailwind PostCSS plugin
    ├── vitest.config.ts                 jsdom and test setup
    ├── src/
    │   ├── proxy.ts                     root locale negotiation and redirect
    │   ├── app/
    │   │   ├── globals.css              dark visual tokens and responsive base
    │   │   └── [locale]/
    │   │       ├── layout.tsx            localized root HTML shell
    │   │       └── page.tsx              localized homepage composition
    │   ├── components/
    │   │   ├── language-switcher.tsx     explicit locale links
    │   │   └── riot-search-form.tsx      Phase 1 non-functional search form
    │   ├── i18n/
    │   │   ├── locales.ts                locale type and negotiation
    │   │   ├── messages.ts               typed catalog lookup
    │   │   ├── en-US.ts                  English messages
    │   │   └── zh-CN.ts                  Simplified Chinese messages
    │   └── test/
    │       └── setup.ts                  Testing Library cleanup/matchers
    └── tests/
        ├── i18n.test.ts                  locale and catalog parity
        └── riot-search-form.test.tsx      accessible bilingual form behavior
```

---

### Task 1: Tested FastAPI Health and Readiness Service

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/health.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/database.py`
- Create: `backend/app/core/errors.py`
- Create: `backend/app/core/request_id.py`
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/errors.py`
- Create: `backend/app/schemas/health.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_config.py`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: Environment variables `APP_ENV`, `DATABASE_URL`, and `BACKEND_CORS_ORIGINS`.
- Produces: `Settings`, `Database`, `create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI`, `GET /health/live`, and `GET /health/ready`.
- Produces response shape: `{"status": "ok", "service": "lol-ai-coach-backend"}` for healthy probes.
- Produces failure shape: HTTP 503 with `{"error": {"code": "SERVICE_NOT_READY", "message": "Service is temporarily unavailable.", "params": {}, "retryable": true, "request_id": "request-correlation-id"}}` when the database ping fails.

- [ ] **Step 1: Create the Python package configuration**

Create `backend/pyproject.toml` with these runtime and development dependencies and tool settings:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "lol-ai-coach-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.116,<1.0",
  "pydantic>=2.11,<3.0",
  "pydantic-settings>=2.10,<3.0",
  "sqlalchemy[asyncio]>=2.0.41,<3.0",
  "asyncpg>=0.30,<1.0",
  "uvicorn[standard]>=0.35,<1.0",
]

[project.optional-dependencies]
dev = [
  "httpx2>=2.7,<3.0",
  "mypy>=1.16,<2.0",
  "pytest>=8.4,<9.0",
  "pytest-asyncio>=1.0,<2.0",
  "ruff>=0.12,<1.0",
]

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "ASYNC"]

[tool.mypy]
python_version = "3.11"
strict = true
plugins = ["pydantic.mypy"]
packages = ["app"]
```

Install the editable development package:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

- [ ] **Step 2: Write failing settings and health tests**

Create `backend/tests/test_config.py`:

```python
from app.core.config import Settings


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000,https://coach.example.com",
    )

    assert settings.cors_origins == [
        "http://localhost:3000",
        "https://coach.example.com",
    ]
```

Create `backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient


def test_liveness_returns_service_identity(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "lol-ai-coach-backend",
    }


def test_readiness_pings_database(client: TestClient, fake_database: object) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert getattr(fake_database, "ping_count") == 1


def test_readiness_returns_safe_503_when_database_fails(
    unavailable_client: TestClient,
) -> None:
    response = unavailable_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == "SERVICE_NOT_READY"
    assert payload["error"]["params"] == {}
    assert payload["error"]["retryable"] is True
    assert payload["error"]["message"]
    assert payload["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "database unavailable" not in response.text
```

Create `backend/tests/conftest.py` with a typed fake and fixtures:

```python
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


class FakeDatabase:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.ping_count = 0
        self.close_count = 0

    async def ping(self) -> None:
        self.ping_count += 1
        if self.should_fail:
            raise ConnectionError("database unavailable")

    async def close(self) -> None:
        self.close_count += 1


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000",
    )


@pytest.fixture
def fake_database() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def client(settings: Settings, fake_database: FakeDatabase) -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=settings, database=fake_database)) as test_client:
        yield test_client


@pytest.fixture
def unavailable_client(settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(
        create_app(settings=settings, database=FakeDatabase(should_fail=True))
    ) as test_client:
        yield test_client
```

- [ ] **Step 3: Run the focused tests and verify red state**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_config.py tests/test_health.py -v
```

Expected: collection fails because `app.core.config`, `app.main`, and their contracts do not exist.

- [ ] **Step 4: Implement settings, database lifecycle, schemas, and routes**

Create `backend/app/core/config.py`:

```python
from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach"
    backend_cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @cached_property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]
```

Create `backend/app/core/database.py`:

```python
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class DatabaseProtocol(Protocol):
    async def ping(self) -> None: ...
    async def close(self) -> None: ...


class Database:
    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)

    async def ping(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self._engine.dispose()
```

Create `backend/app/schemas/health.py`:

```python
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["lol-ai-coach-backend"] = "lol-ai-coach-backend"
```

Create `backend/app/api/health.py`:

```python
from fastapi import APIRouter, Request, status

from app.core.database import DatabaseProtocol
from app.core.errors import ApiError
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse()


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse:
    database: DatabaseProtocol = request.app.state.database
    try:
        await database.ping()
    except Exception as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="SERVICE_NOT_READY",
            message="Service is temporarily unavailable.",
            retryable=True,
        ) from exc
    return HealthResponse()
```

Create `backend/app/main.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.core.config import Settings
from app.core.database import Database, DatabaseProtocol
from app.core.errors import ApiError, api_error_handler
from app.core.request_id import RequestIdMiddleware


def create_app(
    settings: Settings | None = None,
    database: DatabaseProtocol | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_database = database or Database(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.database = resolved_database
        yield
        await resolved_database.close()

    application = FastAPI(title="LoL AI Coach API", version="0.1.0", lifespan=lifespan)
    application.add_middleware(RequestIdMiddleware)
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(health_router)
    return application


app = create_app()
```

Create empty package marker files at each listed `__init__.py` path.

- [ ] **Step 5: Run backend tests, lint, formatting check, and type checking**

Run:

```bash
cd backend
.venv/bin/pytest -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
```

Expected: all commands exit 0; three health tests and the settings test pass.

- [ ] **Step 6: Commit the backend foundation**

```bash
git add backend
git commit -m "feat: add FastAPI health foundation"
```

---

### Task 2: Tested Bilingual Next.js Search Homepage

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/pnpm-lock.yaml`
- Create: `frontend/next.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/eslint.config.mjs`
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/proxy.ts`
- Create: `frontend/src/app/globals.css`
- Delete after scaffolding: `frontend/src/app/layout.tsx`
- Delete after scaffolding: `frontend/src/app/page.tsx`
- Create: `frontend/src/app/[locale]/layout.tsx`
- Create: `frontend/src/app/[locale]/page.tsx`
- Create: `frontend/src/components/language-switcher.tsx`
- Create: `frontend/src/components/riot-search-form.tsx`
- Create: `frontend/src/i18n/locales.ts`
- Create: `frontend/src/i18n/messages.ts`
- Create: `frontend/src/i18n/en-US.ts`
- Create: `frontend/src/i18n/zh-CN.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/tests/i18n.test.ts`
- Create: `frontend/tests/riot-search-form.test.tsx`

**Interfaces:**
- Consumes: URL locale segment `zh-CN` or `en-US`; browser `Accept-Language` at `/`.
- Produces: `type Locale = "zh-CN" | "en-US"`, `resolveLocale(value: string | null) -> Locale`, `getMessages(locale: Locale) -> Messages`, `RiotSearchForm({messages}: Props)`, and localized routes `/zh-CN` and `/en-US`.
- Produces form fields named `gameName`, `tagLine`, and `platform`; Phase 1 submit prevents network access.

- [ ] **Step 1: Scaffold the frontend with current recommended defaults**

From the repository root, run:

```bash
pnpm create next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --use-pnpm --import-alias '@/*' --yes
cd frontend
pnpm add -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

Retain the generated Next.js, React, TypeScript, Tailwind, ESLint, and PostCSS versions in `pnpm-lock.yaml`. Add these scripts to `frontend/package.json`:

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint .",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

- [ ] **Step 2: Configure Vitest and write failing locale tests**

Create `frontend/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

Create `frontend/src/test/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

Create `frontend/tests/i18n.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { getMessages } from "@/i18n/messages";
import { resolveLocale } from "@/i18n/locales";

describe("locale resolution", () => {
  it("selects Simplified Chinese when it is preferred", () => {
    expect(resolveLocale("zh-CN,zh;q=0.9,en;q=0.8")).toBe("zh-CN");
  });

  it("falls back to English for unsupported languages", () => {
    expect(resolveLocale("fr-FR,fr;q=0.9")).toBe("en-US");
  });
});

describe("message catalogs", () => {
  it("contain exactly the same required keys", () => {
    expect(Object.keys(getMessages("zh-CN")).sort()).toEqual(
      Object.keys(getMessages("en-US")).sort(),
    );
  });
});
```

- [ ] **Step 3: Write the failing accessible form test**

Create `frontend/tests/riot-search-form.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RiotSearchForm } from "@/components/riot-search-form";
import { getMessages } from "@/i18n/messages";

describe("RiotSearchForm", () => {
  it("renders the English fields and keeps Phase 1 submission local", async () => {
    const user = userEvent.setup();
    render(<RiotSearchForm messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Game Name"), "PlayerName");
    await user.type(screen.getByLabelText("Tag Line"), "NA1");
    expect(screen.getByLabelText("Region")).toHaveValue("NA1");

    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByText("Riot API search will be added in Phase 2.")).toBeVisible();
  });

  it("renders Simplified Chinese labels", () => {
    render(<RiotSearchForm messages={getMessages("zh-CN")} />);

    expect(screen.getByLabelText("游戏名称")).toBeVisible();
    expect(screen.getByRole("button", { name: "查询" })).toBeVisible();
  });
});
```

- [ ] **Step 4: Run frontend tests and verify red state**

Run:

```bash
cd frontend
pnpm test
```

Expected: tests fail because the i18n modules and `RiotSearchForm` do not exist.

- [ ] **Step 5: Implement typed locale negotiation and message catalogs**

Create `frontend/src/i18n/locales.ts`:

```typescript
export const locales = ["zh-CN", "en-US"] as const;
export type Locale = (typeof locales)[number];

export function isLocale(value: string): value is Locale {
  return locales.includes(value as Locale);
}

export function resolveLocale(acceptLanguage: string | null): Locale {
  if (!acceptLanguage) return "en-US";
  const normalized = acceptLanguage.toLowerCase();
  return normalized.includes("zh-cn") || normalized.startsWith("zh")
    ? "zh-CN"
    : "en-US";
}
```

Create `frontend/src/i18n/en-US.ts`:

```typescript
export const enUS = {
  productName: "LoL AI Coach",
  headline: "Understand the match. Improve the next one.",
  description: "Enter a Riot ID to prepare a data-based post-game review.",
  gameName: "Game Name",
  tagLine: "Tag Line",
  region: "Region",
  northAmerica: "North America",
  search: "Search",
  example: "Example: PlayerName # NA1",
  phaseNotice: "Riot API search will be added in Phase 2.",
  language: "Language",
  disclaimer: "LoL AI Coach is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.",
} as const;
```

Create `frontend/src/i18n/zh-CN.ts` with the same keys:

```typescript
import type { Messages } from "./messages";

export const zhCN: Messages = {
  productName: "LoL AI Coach",
  headline: "看懂这一局，打好下一局。",
  description: "输入 Riot ID，准备生成基于赛后数据的复盘。",
  gameName: "游戏名称",
  tagLine: "标签",
  region: "服务器",
  northAmerica: "北美",
  search: "查询",
  example: "示例：PlayerName # NA1",
  phaseNotice: "Riot API 查询将在第二阶段接入。",
  language: "语言",
  disclaimer: "LoL AI Coach 未获得 Riot Games 认可，也不代表 Riot Games 或任何正式参与 Riot Games 产品制作与管理人员的观点或意见。Riot Games 及其相关资产均为 Riot Games, Inc. 的商标或注册商标。",
};
```

Create `frontend/src/i18n/messages.ts`:

```typescript
import { enUS } from "./en-US";
import { zhCN } from "./zh-CN";
import type { Locale } from "./locales";

export type Messages = { [Key in keyof typeof enUS]: string };

export function getMessages(locale: Locale): Messages {
  return locale === "zh-CN" ? zhCN : enUS;
}
```

- [ ] **Step 6: Implement the localized form and language switch**

Create `frontend/src/components/riot-search-form.tsx`:

```tsx
"use client";

import { type FormEvent, useState } from "react";

import type { Messages } from "@/i18n/messages";

export function RiotSearchForm({ messages }: { messages: Messages }) {
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
  }

  return (
    <form onSubmit={handleSubmit} className="search-card">
      <label>
        <span>{messages.gameName}</span>
        <input name="gameName" autoComplete="off" required maxLength={16} />
      </label>
      <label>
        <span>{messages.tagLine}</span>
        <input name="tagLine" autoComplete="off" required maxLength={5} />
      </label>
      <label>
        <span>{messages.region}</span>
        <select name="platform" defaultValue="NA1">
          <option value="NA1">{messages.northAmerica}</option>
        </select>
      </label>
      <button type="submit">{messages.search}</button>
      <p className="example">{messages.example}</p>
      {submitted ? <p role="status">{messages.phaseNotice}</p> : null}
    </form>
  );
}
```

Create `frontend/src/components/language-switcher.tsx`:

```tsx
import Link from "next/link";

import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages";

export function LanguageSwitcher({ locale, messages }: { locale: Locale; messages: Messages }) {
  const target = locale === "zh-CN" ? "en-US" : "zh-CN";
  return (
    <nav aria-label={messages.language}>
      <Link href={`/${target}`} hrefLang={target}>
        {target === "zh-CN" ? "中文" : "English"}
      </Link>
    </nav>
  );
}
```

- [ ] **Step 7: Implement localized routes and the dark responsive shell**

Delete the generated `frontend/src/app/layout.tsx` and `frontend/src/app/page.tsx`. Create `frontend/src/proxy.ts` so `/` redirects before route resolution:

```tsx
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { resolveLocale } from "@/i18n/locales";

export function proxy(request: NextRequest) {
  const locale = resolveLocale(request.headers.get("accept-language"));
  return NextResponse.redirect(new URL(`/${locale}`, request.url));
}

export const config = { matcher: ["/"] };
```

Create `frontend/src/app/[locale]/layout.tsx`:

```tsx
import { notFound } from "next/navigation";

import "../globals.css";
import { isLocale, locales } from "@/i18n/locales";

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: Readonly<{ children: React.ReactNode; params: Promise<{ locale: string }> }>) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return (
    <html lang={locale}>
      <body>{children}</body>
    </html>
  );
}
```

Create `frontend/src/app/[locale]/page.tsx`:

```tsx
import { notFound } from "next/navigation";

import { LanguageSwitcher } from "@/components/language-switcher";
import { RiotSearchForm } from "@/components/riot-search-form";
import { getMessages } from "@/i18n/messages";
import { isLocale } from "@/i18n/locales";

export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const messages = getMessages(locale);

  return (
    <main>
      <header>
        <span className="brand">{messages.productName}</span>
        <LanguageSwitcher locale={locale} messages={messages} />
      </header>
      <section className="hero">
        <p className="eyebrow">POST-GAME REVIEW</p>
        <h1>{messages.headline}</h1>
        <p>{messages.description}</p>
        <RiotSearchForm messages={messages} />
      </section>
      <footer>{messages.disclaimer}</footer>
    </main>
  );
}
```

Replace `frontend/src/app/globals.css` with:

```css
@import "tailwindcss";

:root {
  color-scheme: dark;
  --background: #070b14;
  --surface: #101827;
  --surface-raised: #172235;
  --border: #2a3850;
  --text: #f4f7fb;
  --muted: #9aa9bd;
  --accent: #56d68b;
  --accent-strong: #31b86c;
  --focus: #8ee8b1;
}

* {
  box-sizing: border-box;
}

body {
  min-height: 100vh;
  margin: 0;
  background:
    radial-gradient(circle at 15% 0%, rgb(42 72 94 / 35%), transparent 38%),
    var(--background);
  color: var(--text);
  font-family: Arial, Helvetica, sans-serif;
}

a {
  color: var(--accent);
  text-underline-offset: 0.25rem;
}

main {
  width: min(1120px, calc(100% - 2rem));
  min-height: 100vh;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem 0;
}

.brand {
  font-weight: 800;
  letter-spacing: 0.04em;
}

.hero {
  flex: 1;
  display: grid;
  align-content: center;
  gap: 1rem;
  padding: 3rem 0;
}

.eyebrow {
  margin: 0;
  color: var(--accent);
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.18em;
}

h1 {
  max-width: 760px;
  margin: 0;
  font-size: clamp(2.5rem, 7vw, 5.4rem);
  line-height: 0.98;
  letter-spacing: -0.04em;
}

.hero > p:not(.eyebrow) {
  max-width: 640px;
  color: var(--muted);
  font-size: 1.08rem;
}

.search-card {
  display: grid;
  grid-template-columns: 1.4fr 0.8fr 1fr auto;
  gap: 0.9rem;
  margin-top: 1.5rem;
  padding: 1.2rem;
  border: 1px solid var(--border);
  border-radius: 1rem;
  background: rgb(16 24 39 / 88%);
  box-shadow: 0 1.5rem 4rem rgb(0 0 0 / 24%);
}

label {
  display: grid;
  gap: 0.45rem;
  color: var(--muted);
  font-size: 0.8rem;
  font-weight: 700;
}

input,
select,
button {
  min-height: 3rem;
  border-radius: 0.7rem;
  font: inherit;
}

input,
select {
  width: 100%;
  border: 1px solid var(--border);
  background: var(--surface-raised);
  color: var(--text);
  padding: 0 0.85rem;
}

input:focus-visible,
select:focus-visible,
button:focus-visible,
a:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 2px;
}

button {
  align-self: end;
  border: 0;
  padding: 0 1.4rem;
  background: var(--accent);
  color: #041109;
  font-weight: 800;
  cursor: pointer;
  transition: background-color 140ms ease;
}

button:hover {
  background: var(--accent-strong);
}

.example,
[role="status"] {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
}

footer {
  padding: 1.5rem 0 2rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.75rem;
  line-height: 1.6;
}

@media (max-width: 720px) {
  .search-card {
    grid-template-columns: 1fr;
  }

  button {
    width: 100%;
  }
}
```

Set `output: "standalone"` in `frontend/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
```

- [ ] **Step 8: Run the frontend quality gates**

Run:

```bash
cd frontend
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

Expected: locale/form tests pass, lint/typecheck exit 0, and Next.js builds `/`, `/zh-CN`, and `/en-US` successfully.

- [ ] **Step 9: Commit the bilingual frontend foundation**

```bash
git add frontend
git commit -m "feat: add bilingual Next.js search homepage"
```

---

### Task 3: Docker Compose and Uniform Local Commands

**Files:**
- Create: `.env.example`
- Create: `.gitignore`
- Create: `Makefile`
- Create: `docker-compose.yml`
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`

**Interfaces:**
- Consumes: `.env` values documented by `.env.example`.
- Produces: `make install`, `make dev-backend`, `make dev-frontend`, `make test`, `make lint`, `make typecheck`, `make verify`, `make docker-up`, and `make docker-down`.
- Produces local services: frontend `http://localhost:3000`, backend `http://localhost:8000`, PostgreSQL `localhost:5432`.

- [ ] **Step 1: Write a configuration test for required environment names**

Extend `backend/tests/test_config.py`:

```python
def test_settings_have_safe_local_defaults() -> None:
    settings = Settings()

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.cors_origins == ["http://localhost:3000"]
```

Run:

```bash
cd backend
.venv/bin/pytest tests/test_config.py -v
```

Expected: PASS, establishing the environment contract used by containers.

- [ ] **Step 2: Create root environment and ignore files**

Create `.env.example`:

```dotenv
APP_ENV=development
POSTGRES_DB=lol_ai_coach
POSTGRES_USER=lol_ai_coach
POSTGRES_PASSWORD=lol_ai_coach
DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@db:5432/lol_ai_coach
BACKEND_CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
DEFAULT_LOCALE=en-US
RIOT_API_KEY=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-terra
```

Create `.gitignore` with these entries:

```gitignore
.DS_Store
.env
.env.*
!.env.example
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.pyc
node_modules/
.next/
coverage/
dist/
*.log
```

- [ ] **Step 3: Create production-shaped service images**

Create `backend/Dockerfile`:

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN python -m pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `frontend/Dockerfile`:

```dockerfile
FROM node:22-alpine AS dependencies
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
```

If `public/` does not exist after scaffolding, create the empty `frontend/public/.gitkeep` before building so the Docker copy is deterministic.

- [ ] **Step 4: Create Docker Compose with health dependencies**

Create `docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-lol_ai_coach}
      POSTGRES_USER: ${POSTGRES_USER:-lol_ai_coach}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-lol_ai_coach}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10

  backend:
    build: ./backend
    environment:
      APP_ENV: ${APP_ENV:-development}
      DATABASE_URL: ${DATABASE_URL:-postgresql+asyncpg://lol_ai_coach:lol_ai_coach@db:5432/lol_ai_coach}
      BACKEND_CORS_ORIGINS: ${BACKEND_CORS_ORIGINS:-http://localhost:3000}
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')"]
      interval: 5s
      timeout: 3s
      retries: 10

  frontend:
    build: ./frontend
    environment:
      NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}
    ports:
      - "3000:3000"
    depends_on:
      backend:
        condition: service_healthy

volumes:
  postgres_data:
```

- [ ] **Step 5: Create uniform Make targets**

Create `Makefile`:

```makefile
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
```

- [ ] **Step 6: Validate configuration and local commands**

Run:

```bash
make verify
docker compose config
docker compose build
docker compose up -d
curl --fail http://localhost:8000/health/live
curl --fail http://localhost:8000/health/ready
curl --fail http://localhost:3000/en-US
curl --fail http://localhost:3000/zh-CN
docker compose down
```

Expected: verification exits 0; Compose configuration and images succeed; both health routes and both locale pages return HTTP 200. If Docker is not installed on the execution machine, record the missing-runtime limitation and still run `make verify`; do not claim Docker verification passed.

- [ ] **Step 7: Commit the local environment**

```bash
git add .env.example .gitignore Makefile docker-compose.yml backend/Dockerfile frontend/Dockerfile frontend/public/.gitkeep
git commit -m "build: add containerized local environment"
```

---

### Task 4: CI, Verification Script, and Complete README

**Files:**
- Create: `scripts/verify.sh`
- Create: `.github/workflows/ci.yml`
- Create: `README.md`

**Interfaces:**
- Consumes: Task 1–3 commands and committed lock/configuration files.
- Produces: `./scripts/verify.sh` as the canonical non-Docker quality gate and a GitHub Actions workflow with separate backend/frontend jobs.
- Produces: README instructions for local, Docker, testing, environment variables, bilingual routes, current limitations, and next phase.

- [ ] **Step 1: Create and run the canonical verification script**

Create `scripts/verify.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$repo_dir/backend"
.venv/bin/pytest -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy

cd "$repo_dir/frontend"
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

Make it executable and run it:

```bash
chmod +x scripts/verify.sh
./scripts/verify.sh
```

Expected: every backend and frontend gate exits 0.

- [ ] **Step 2: Create GitHub Actions quality gates**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: backend/pyproject.toml
      - run: python -m pip install -e 'backend[dev]'
      - run: pytest -v
        working-directory: backend
      - run: ruff check .
        working-directory: backend
      - run: ruff format --check .
        working-directory: backend
      - run: mypy
        working-directory: backend

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 11.9.0
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
        working-directory: frontend
      - run: pnpm test
        working-directory: frontend
      - run: pnpm lint
        working-directory: frontend
      - run: pnpm typecheck
        working-directory: frontend
      - run: pnpm build
        working-directory: frontend
```

- [ ] **Step 3: Write the complete Phase 1 README**

Create `README.md` with these exact top-level sections and commands:

```markdown
# LoL AI Coach

LoL AI Coach is a bilingual, data-based League of Legends post-game review assistant. Phase 1 provides the tested project foundation and search interface; it does not yet call Riot or OpenAI.

## Current Status

- Available: Chinese/English homepage, Riot ID form, FastAPI live/ready health endpoints, PostgreSQL-backed Docker environment, tests, lint, type checks, and CI.
- Not available: player lookup, match data, scoring, AI review, accounts, trends, or replay analysis.

## Requirements

- Node.js 20.9+
- pnpm 11+
- Python 3.11+
- Docker Desktop with Docker Compose for the container workflow

## Local Setup

```bash
cp .env.example .env
make install
```

Run the backend and frontend in separate terminals:

```bash
make dev-backend
make dev-frontend
```

Open `http://localhost:3000`, `http://localhost:3000/zh-CN`, or `http://localhost:3000/en-US`.

## Docker Setup

```bash
cp .env.example .env
make docker-up
```

Stop services with `make docker-down`.

## Verification

```bash
make verify
```

The command runs backend/frontend tests, lint, formatting checks, type checks, and the production frontend build.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Backend environment name. |
| `POSTGRES_DB` | Local Compose database name. |
| `POSTGRES_USER` | Local Compose database user. |
| `POSTGRES_PASSWORD` | Local Compose database password; replace the development default outside local use. |
| `DATABASE_URL` | SQLAlchemy async PostgreSQL URL. |
| `BACKEND_CORS_ORIGINS` | Comma-separated allowed frontend origins. |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-visible backend base URL; it contains no secret. |
| `DEFAULT_LOCALE` | Default product locale, `zh-CN` or `en-US`. |
| `RIOT_API_KEY` | Empty and unused in Phase 1; server-only in Phase 2. |
| `OPENAI_API_KEY` | Empty and unused in Phase 1; server-only in Phase 4. |
| `OPENAI_MODEL` | Future configurable coaching model; defaults to `gpt-5.6-terra`. |

Copy `.env.example` to `.env`. Never commit `.env` or populated API keys.

## API

- `GET /health/live`: process liveness.
- `GET /health/ready`: database readiness.

## Project Structure

- `frontend`: Next.js user interface, localization, and frontend tests.
- `backend`: FastAPI service, configuration, database readiness, and backend tests.
- `docs/superpowers/specs`: approved product and technical designs.
- `docs/superpowers/plans`: phase-by-phase implementation plans.
- `scripts`: repository verification commands.

## Product Scope Notice

Phase 1 contains no fake match data. Future data-only reviews may describe recorded statistics and event order, but they cannot claim to observe positioning, mechanics, or player intent. Replay analysis is a separate future phase.

## Riot Disclaimer

LoL AI Coach is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

LoL AI Coach 未获得 Riot Games 认可，也不代表 Riot Games 或任何正式参与 Riot Games 产品制作与管理人员的观点或意见。Riot Games 及其相关资产均为 Riot Games, Inc. 的商标或注册商标。

## Next Phase

Phase 2 adds real Riot Account, Summoner, Match V5, and localized Data Dragon integration with mocked external-service tests.
```

- [ ] **Step 4: Run final Phase 1 verification and inspect repository state**

Run:

```bash
./scripts/verify.sh
git diff --check
git status --short
```

Expected: verification and whitespace check exit 0; status lists only the Task 4 files before commit.

- [ ] **Step 5: Commit CI and documentation**

```bash
git add scripts/verify.sh .github/workflows/ci.yml README.md
git commit -m "docs: add foundation verification and setup guide"
```

- [ ] **Step 6: Record the Phase 1 acceptance evidence**

After the commit, run:

```bash
git status --short --branch
git log --oneline -5
```

Expected: branch `main` is clean and the four Phase 1 commits are visible. In the completion report, list the exact commands run, pass/fail counts, Docker verification status, local start commands, all modified files grouped by task, current limitations, and Phase 2 as the next recommendation.

## Phase 1 Completion Gate

Do not begin the Riot integration plan until all non-Docker verification commands pass. Docker verification must either pass on a machine with Docker or be reported explicitly as unverified because Docker is absent; it must never be silently marked successful.

The following independently verifiable deliverables must exist:

1. `/health/live` succeeds without a database query.
2. `/health/ready` succeeds only after a database ping.
3. `/zh-CN` and `/en-US` render localized accessible search forms.
4. Search submission makes no external request and states that Riot integration is Phase 2.
5. Backend tests, Ruff, MyPy, frontend tests, ESLint, TypeScript, and Next.js build all pass.
6. `.env.example` contains empty Riot/OpenAI credentials.
7. README contains local and Docker instructions plus current limitations.
8. CI runs the same non-Docker quality gates as local verification.

## References

- Approved product design: `docs/superpowers/specs/2026-07-30-lol-ai-coach-mvp-design.md`
- Next.js installation and requirements: <https://nextjs.org/docs/app/getting-started/installation>
- Tailwind CSS with Next.js: <https://tailwindcss.com/docs/installation/framework-guides/nextjs>
- FastAPI documentation: <https://fastapi.tiangolo.com/>
