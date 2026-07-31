# LoL AI Coach

[English](#english) | [中文](#中文)

<a id="english"></a>

## English

LoL AI Coach is a bilingual League of Legends match-data browser. Phase 2 resolves a Riot ID, displays a player profile and up to ten recent matches, and opens a localized standard-match detail page. It presents normalized Riot data; it does not judge play.

### Phase 2 status and boundary

- Available: `NA1` Riot ID search, separate game name/tag line/platform inputs, canonical player profile, recent-match rail, and English/Chinese localized match details with ten participants for supported standard games.
- The tag line is independent of platform. For example, a numeric tag such as `#1234` is valid and is not inferred from `NA1`.
- Queue `400` (Normal Draft) and `420` (Ranked Solo/Duo) are marked as data-supported. Other returned queues remain visible but do not offer a detail view when their team structure is unsupported.
- Static data comes from a match-compatible Data Dragon version. `en-US` maps to `en_US`; `zh-CN` maps to `zh_CN`. If names or assets cannot be resolved, numeric data still appears with a localized degraded-data warning; the app never substitutes current-patch names silently.
- Not in Phase 2: Match Timeline, scores, coaching findings, AI calls, behavioral judgment, positioning, mechanics, awareness, intent, causality, OP.GG integration, replay processing, video uploads, or raw upstream JSON storage.

### Requirements

- Node.js 20.9+ (CI uses Node.js 22)
- pnpm 11+ (CI uses pnpm 11.9.0)
- Python 3.11+
- PostgreSQL 17 for repository integration verification
- Docker Desktop with Docker Compose only for the optional container workflow

### Local setup

```bash
cp .env.example .env
make install
```

Set `RIOT_API_KEY` only in ignored `.env`. Riot development keys expire after about 24 hours, so renew the local key when Riot rejects it. The key is read by the backend only; never put it in `NEXT_PUBLIC_*`, browser code, committed files, fixtures, logs, or screenshots.

Use a host-local database URL for the backend and a container hostname for Compose:

```dotenv
DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach
COMPOSE_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@db:5432/lol_ai_coach
```

Apply the normalized-cache schema before running the backend against a new local database:

```bash
cd backend
.venv/bin/alembic upgrade head
```

Run backend and frontend in separate terminals:

```bash
make dev-backend
make dev-frontend
```

Open `http://localhost:3000/zh-CN` or `http://localhost:3000/en-US`.

### Verification and live smoke

```bash
make verify
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test make verify-postgres
make smoke-riot
```

- `make verify` runs non-integration backend/frontend tests, lint, formatting, type checks, production build, and a whitespace check. It does not require a database.
- `make verify-postgres` requires a dedicated, reachable `TEST_DATABASE_URL`, applies Alembic, and runs the PostgreSQL repository integration suite. It fails rather than silently skipping when the variable or database is absent.
- `make smoke-riot` calls an already-running local backend. It also requires non-empty ignored `RIOT_SMOKE_GAME_NAME`, `RIOT_SMOKE_TAG_LINE`, and `RIOT_SMOKE_PLATFORM` settings plus `RIOT_API_KEY`. The command prints only generic counts on success; it never prints the Riot ID, PUUID, match ID, key, full URL, or raw response body.

CI runs non-integration backend checks, the PostgreSQL integration gate, and all frontend checks. It intentionally does not run a live Riot smoke flow because development keys and smoke identities are local secrets.

Observed acceptance on this workstation: automated unit/type/build checks and the local PostgreSQL gate passed; the live smoke completed with the safe generic result `matches=10 locales=2 repeat=ok`. Real English and Chinese browser flows displayed ten newest-to-oldest matches, localized champion/item assets, supported and visibly unsupported queues, accessible standard-match detail, responsive narrow layouts, and the permanent data-only notice without behavioral or causality claims. Controlled degraded/error checks preserved numeric statistics and showed localized safe recovery states. Docker Compose remains unverified because Docker CLI access is unavailable; it is not recorded as passed.

### Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Host-local SQLAlchemy async PostgreSQL URL. |
| `COMPOSE_DATABASE_URL` | Container-internal PostgreSQL URL (`db` host). |
| `TEST_DATABASE_URL` | Dedicated disposable PostgreSQL database for `make verify-postgres`. |
| `RIOT_API_KEY` | Server-only Riot key; leave empty in `.env.example`. |
| `RIOT_SMOKE_GAME_NAME` / `RIOT_SMOKE_TAG_LINE` | Ignored local smoke identity; never commit a real player identifier. |
| `RIOT_SMOKE_PLATFORM` | Smoke platform; Phase 2 supports `NA1` only. |
| `SMOKE_API_BASE_URL` | Already-running local backend base URL, default `http://localhost:8000`. |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-visible backend base URL; contains no secret. |

### API

- `GET /health/live`: process liveness without database access.
- `GET /health/ready`: database/configuration readiness without calling Riot.
- `GET /api/v1/players/resolve`: resolves a valid `platform`, `game_name`, and `tag_line`.
- `GET /api/v1/players/{puuid}/matches`: returns up to ten newest-to-oldest normalized matches.
- `GET /api/v1/matches/{match_id}`: returns a localized supported match detail for the selected player.

### Replay roadmap

The next phase can add authorized replay upload and timestamped frame evidence to supplement data. Public, purchased, or third-party teaching video is never ingested without explicit permission from its rights holder. An AI may propose a rule from authorized evidence, but a human must approve it before any product use.

### Riot disclaimer

LoL AI Coach is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

<a id="中文"></a>

## 中文

LoL AI Coach 是一个中英双语的《英雄联盟》对局数据浏览工具。Phase 2 可以查询 Riot ID、展示玩家资料与最多十场近期对局，并打开本地化的标准对局详情。它只呈现规范化的 Riot 数据，不对玩家表现做判断。

### Phase 2 状态与边界

- 已提供：`NA1` Riot ID 查询、独立的游戏名/标签/平台输入、规范玩家资料、近期对局列表，以及中英文标准对局详情（支持时展示十名参与者）。
- 标签与平台相互独立。例如 `#1234` 这类数字标签有效，绝不会由 `NA1` 自动推断。
- 队列 `400`（自选模式）和 `420`（单排/双排）标记为数据支持。其他返回队列仍会展示；若队伍结构不支持，则不会提供详情页。
- 静态资料使用与对局版本兼容的 Data Dragon：`en-US` 映射到 `en_US`，`zh-CN` 映射到 `zh_CN`。若名称或资源无法解析，数值数据仍会展示并给出本地化降级提示；不会偷偷用当前版本名称替代。
- Phase 2 不包含：Match Timeline、评分、复盘结论、AI 调用、行为判断、走位、操作、意识、意图、因果推断、OP.GG 集成、回放处理、视频上传或原始上游 JSON 存储。

### 环境要求

- Node.js 20.9+（CI 使用 Node.js 22）
- pnpm 11+（CI 使用 pnpm 11.9.0）
- Python 3.11+
- PostgreSQL 17（仓库集成验证需要）
- Docker Desktop 与 Docker Compose（仅可选容器工作流需要）

### 本地启动

```bash
cp .env.example .env
make install
```

只在被忽略的 `.env` 中填写 `RIOT_API_KEY`。Riot 开发密钥约 24 小时过期，Riot 拒绝请求时需在本地更新。密钥只由后端读取，绝不能放进 `NEXT_PUBLIC_*`、浏览器代码、已提交文件、测试夹具、日志或截图。

后端使用本机数据库地址；Compose 使用容器主机名：

```dotenv
DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach
COMPOSE_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@db:5432/lol_ai_coach
```

新建本地数据库后，先应用规范化缓存迁移：

```bash
cd backend
.venv/bin/alembic upgrade head
```

在两个独立终端启动后端和前端：

```bash
make dev-backend
make dev-frontend
```

打开 `http://localhost:3000/zh-CN` 或 `http://localhost:3000/en-US`。

### 验证与在线冒烟

```bash
make verify
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test make verify-postgres
make smoke-riot
```

- `make verify` 运行非集成后端/前端测试、静态检查、格式检查、类型检查、前端生产构建和空白检查，不需要数据库。
- `make verify-postgres` 需要专用且可连接的 `TEST_DATABASE_URL`，会执行 Alembic 并运行 PostgreSQL 仓库集成测试；变量或数据库缺失时会失败，不会静默跳过。
- `make smoke-riot` 调用已经运行的本地后端，同时要求忽略的 `RIOT_SMOKE_GAME_NAME`、`RIOT_SMOKE_TAG_LINE`、`RIOT_SMOKE_PLATFORM` 非空，以及已配置的 `RIOT_API_KEY`。成功时仅输出通用计数；不会输出 Riot ID、PUUID、对局 ID、密钥、完整 URL 或原始响应体。

CI 会运行非集成后端检查、PostgreSQL 集成门和所有前端检查。由于开发密钥和冒烟账号属于本地机密，CI 有意不运行在线 Riot 冒烟流程。

本机已实际观察到以下验收结果：自动化单元/类型/构建检查与本地 PostgreSQL 门通过；在线冒烟以安全通用结果 `matches=10 locales=2 repeat=ok` 完成。真实中英文浏览器流程展示了十场按新到旧排列的对局、本地化英雄与装备资源、明确区分的支持/不支持队列、可访问的标准对局详情、窄屏响应式布局和永久的数据范围提示，且没有行为或因果判断。受控降级与错误检查保留了数值统计，并提供本地化的安全恢复状态。此 Mac 没有 Docker CLI，Docker Compose 仍未验证，不能标记为已通过。

### 配置

| 变量 | 用途 |
| --- | --- |
| `DATABASE_URL` | 本机 SQLAlchemy 异步 PostgreSQL 地址。 |
| `COMPOSE_DATABASE_URL` | 容器内部 PostgreSQL 地址（`db` 主机）。 |
| `TEST_DATABASE_URL` | `make verify-postgres` 使用的独立可清理 PostgreSQL 数据库。 |
| `RIOT_API_KEY` | 仅后端使用的 Riot 密钥；`.env.example` 必须为空。 |
| `RIOT_SMOKE_GAME_NAME` / `RIOT_SMOKE_TAG_LINE` | 被忽略的本地冒烟身份；不要提交真实玩家标识。 |
| `RIOT_SMOKE_PLATFORM` | 冒烟平台；Phase 2 仅支持 `NA1`。 |
| `SMOKE_API_BASE_URL` | 已运行本地后端的基础地址，默认 `http://localhost:8000`。 |
| `NEXT_PUBLIC_API_BASE_URL` | 浏览器可见的后端基础地址；不包含密钥。 |

### API

- `GET /health/live`：进程存活检查，不访问数据库。
- `GET /health/ready`：数据库/配置就绪检查，不调用 Riot。
- `GET /api/v1/players/resolve`：根据有效 `platform`、`game_name`、`tag_line` 查询玩家。
- `GET /api/v1/players/{puuid}/matches`：返回最多十场按新到旧排序的规范化对局。
- `GET /api/v1/matches/{match_id}`：返回所选玩家的本地化、受支持对局详情。

### 回放路线图

下一阶段可以加入已授权的回放上传和带时间戳的画面证据，补充数据来源。未获权利人明确许可时，不会接入公开、购买或第三方教学视频。AI 可以根据获授权证据提出规则，但在产品使用前必须由人工批准。

### Riot 声明

LoL AI Coach 未获得 Riot Games 认可，也不代表 Riot Games 或任何正式参与 Riot Games 产品制作与管理人员的观点或意见。Riot Games 及其相关资产均为 Riot Games, Inc. 的商标或注册商标。
