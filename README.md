# LoL AI Coach

[English](#english) | [中文](#中文)

<a id="english"></a>

## English

LoL AI Coach is a bilingual, data-based League of Legends post-game review assistant. Phase 1 provides a tested project foundation and search interface; it does not yet call Riot Games or OpenAI services.

### Current Status

- Available: Chinese and English homepages, a Riot ID form, FastAPI live/ready health endpoints, a PostgreSQL-backed Docker configuration, tests, lint, type checks, and CI.
- Not available: player lookup, match data, scoring, AI review, accounts, trends, or replay analysis.
- Verification note: the non-Docker quality gate is the canonical local check. Docker Compose build, startup, and endpoint probes have not been verified on this Mac because the Docker CLI is unavailable.

### Requirements

- Node.js 20.9+ (CI uses Node.js 22)
- pnpm 11+ (CI uses pnpm 11.9.0)
- Python 3.11+
- Docker Desktop with Docker Compose for the container workflow

### Local Setup

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

### Docker Setup

```bash
cp .env.example .env
make docker-up
```

Stop services with:

```bash
make docker-down
```

The Compose workflow builds PostgreSQL, backend, and frontend services. On this Mac it is documented but unverified: Docker Compose build, startup, and endpoint probes require Docker CLI access.

### Verification

```bash
make verify
```

`make verify` runs backend/frontend tests, lint, formatting checks, type checks, and the production frontend build. The underlying canonical non-Docker command is `./scripts/verify.sh`.

### Environment Variables

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Backend environment name. |
| `POSTGRES_DB` | Local Compose database name. |
| `POSTGRES_USER` | Local Compose database user. |
| `POSTGRES_PASSWORD` | Local Compose database password; replace the development default outside local use. |
| `DATABASE_URL` | SQLAlchemy async PostgreSQL URL. |
| `BACKEND_CORS_ORIGINS` | Comma-separated allowed frontend origins. |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-visible backend base URL; it contains no secret and is supplied to the frontend image at build time. |
| `DEFAULT_LOCALE` | Default product locale, `zh-CN` or `en-US`. |
| `RIOT_API_KEY` | Empty and unused in Phase 1; server-only in Phase 2. |
| `OPENAI_API_KEY` | Empty and unused in Phase 1; server-only in Phase 4. |
| `OPENAI_MODEL` | Future configurable coaching model; defaults to `gpt-5.6-terra`. |

Copy `.env.example` to `.env`. Never commit `.env` or populated API keys.

### API

- `GET /health/live`: process liveness; it does not query the database.
- `GET /health/ready`: database readiness; it succeeds only after a database ping.

### Project Structure

- `frontend`: Next.js interface, localization, and frontend tests.
- `backend`: FastAPI service, configuration, database readiness, and backend tests.
- `docs/superpowers/specs`: approved product and technical designs.
- `docs/superpowers/plans`: phase-by-phase implementation plans.
- `scripts`: repository verification commands.

### MVP Boundary

Phase 1 contains no fake match data. Future data-only reviews may describe recorded statistics and event order, but cannot claim to observe positioning, mechanics, or player intent. Replay analysis is a separate future evidence source and is not part of the current product.

### Riot Disclaimer

LoL AI Coach is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

### Next Phase

Phase 2 adds real Riot Account, Summoner, Match V5, and localized Data Dragon integration with mocked external-service tests.

<a id="中文"></a>

## 中文

LoL AI Coach 是一款中英双语、基于数据的《英雄联盟》赛后复盘助手。Phase 1 提供经过测试的项目基础和搜索界面；目前尚未调用 Riot Games 或 OpenAI 服务。

### 当前状态

- 已提供：中文和英文首页、Riot ID 表单、FastAPI 存活/就绪健康检查端点、带 PostgreSQL 的 Docker 配置、测试、静态检查、类型检查与 CI。
- 尚未提供：玩家查询、对局数据、评分、AI 复盘、账户、趋势或回放分析。
- 验证说明：非 Docker 质量门是本地的权威检查。由于此 Mac 没有 Docker CLI，尚未验证 Docker Compose 的构建、启动和端点探测。

### 环境要求

- Node.js 20.9+（CI 使用 Node.js 22）
- pnpm 11+（CI 使用 pnpm 11.9.0）
- Python 3.11+
- 容器工作流需要带 Docker Compose 的 Docker Desktop

### 本地启动

```bash
cp .env.example .env
make install
```

在两个独立终端分别启动后端和前端：

```bash
make dev-backend
make dev-frontend
```

打开 `http://localhost:3000`、`http://localhost:3000/zh-CN` 或 `http://localhost:3000/en-US`。

### Docker 启动

```bash
cp .env.example .env
make docker-up
```

停止服务：

```bash
make docker-down
```

Compose 会构建 PostgreSQL、后端和前端服务。此 Mac 上这些步骤仅提供说明，尚未进行 Compose 构建、启动及端点探测验证；需要 Docker CLI 才能完成验证。

### 验证

```bash
make verify
```

`make verify` 会运行前后端测试、静态检查、格式检查、类型检查和前端生产构建。底层的权威非 Docker 命令为 `./scripts/verify.sh`。

### 环境变量

| 变量 | 用途 |
| --- | --- |
| `APP_ENV` | 后端环境名称。 |
| `POSTGRES_DB` | 本地 Compose 数据库名称。 |
| `POSTGRES_USER` | 本地 Compose 数据库用户。 |
| `POSTGRES_PASSWORD` | 本地 Compose 数据库密码；在本地开发以外的环境应替换默认值。 |
| `DATABASE_URL` | SQLAlchemy 异步 PostgreSQL URL。 |
| `BACKEND_CORS_ORIGINS` | 以逗号分隔的允许前端来源。 |
| `NEXT_PUBLIC_API_BASE_URL` | 浏览器可见的后端基础 URL；不含密钥，并在构建前端镜像时传入。 |
| `DEFAULT_LOCALE` | 默认产品语言，`zh-CN` 或 `en-US`。 |
| `RIOT_API_KEY` | Phase 1 为空且未使用；Phase 2 起仅在服务端使用。 |
| `OPENAI_API_KEY` | Phase 1 为空且未使用；Phase 4 起仅在服务端使用。 |
| `OPENAI_MODEL` | 未来可配置的教练模型；默认值为 `gpt-5.6-terra`。 |

将 `.env.example` 复制为 `.env`。不要提交 `.env` 或已填入的 API 密钥。

### API

- `GET /health/live`：进程存活检查；不会查询数据库。
- `GET /health/ready`：数据库就绪检查；仅在数据库 ping 成功后返回成功。

### 项目结构

- `frontend`：Next.js 用户界面、本地化与前端测试。
- `backend`：FastAPI 服务、配置、数据库就绪检查与后端测试。
- `docs/superpowers/specs`：已批准的产品与技术设计。
- `docs/superpowers/plans`：按阶段组织的实施计划。
- `scripts`：仓库验证命令。

### MVP 边界

Phase 1 不包含伪造的对局数据。未来仅基于数据的复盘可以描述已记录的统计指标和事件顺序，但不能声称能够观察走位、操作或玩家意图。回放分析是未来独立的证据来源，不属于当前产品。

### Riot 声明

LoL AI Coach 未获得 Riot Games 认可，也不代表 Riot Games 或任何正式参与 Riot Games 产品制作与管理人员的观点或意见。Riot Games 及其相关资产均为 Riot Games, Inc. 的商标或注册商标。

### 下一阶段

Phase 2 将接入真实的 Riot Account、Summoner、Match V5 和本地化 Data Dragon，并为外部服务加入 mock 测试。
