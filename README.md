# LoL AI Coach

[English](#english) | [中文](#中文)

<a id="english"></a>

## English

LoL AI Coach is a bilingual League of Legends match-data browser. Phase 2 resolves a Riot ID, displays a player profile and up to ten recent matches, and opens a localized standard-match detail page. It presents normalized Riot data; it does not judge play.

### Phase 2 status and boundary

- Available: single-field Riot ID search with optional automatic platform detection (feature-flagged), the compatibility resolve route with explicit platform, canonical player profile, recent-match rail, and English/Chinese localized match details with ten participants for supported standard games.
- Automatic detection covers Riot's sixteen League platforms from a closed routing catalog. Candidate server labels always come from the backend response.
- The tag line is independent of platform. For example, a numeric tag such as `#1234` is valid and is not inferred from any platform code.
- Queue `400` (Normal Draft) and `420` (Ranked Solo/Duo) are marked as data-supported. Other returned queues remain visible but do not offer a detail view when their team structure is unsupported.
- Static data comes from a match-compatible Data Dragon version. `en-US` maps to `en_US`; `zh-CN` maps to `zh_CN`. If names or assets cannot be resolved, numeric data still appears with a localized degraded-data warning; the app never substitutes current-patch names silently.
- Phase 2 / Replay R1 still does not score or judge play. Deterministic Analysis V1 is a separate, on-demand data-coaching layer described below; it does not add AI calls, replay interpretation, behavioral judgment, positioning, mechanics, awareness, intent, causality, OP.GG integration, or raw upstream JSON storage. Match Timeline evidence is Joint Evidence J1 and stays dark until `JOINT_EVIDENCE_ENABLED=true`.

### Platform detection rollout

`RIOT_PLATFORM_DETECTION_ENABLED` defaults to `false`. Roll out in this order:

1. Migrate the database to Alembic head (`0003_player_platform_detection` or later).
2. Deploy the backend with `RIOT_PLATFORM_DETECTION_ENABLED=false` so routes exist but stay dark.
3. Deploy the compatible frontend (single Riot ID field + detection client).
4. Set `RIOT_ACCOUNT_PRIMARY_REGION` and the detection/confirmation TTLs.
5. Enable detection with `RIOT_PLATFORM_DETECTION_ENABLED=true`.
6. Monitor `riot_platform_detection_*` and `riot_platform_confirmation_total` metrics.
7. To roll back, set the flag back to `false`. The compatibility `GET /api/v1/players/resolve` route remains available.

### Joint Evidence J1 rollout

`JOINT_EVIDENCE_ENABLED` defaults to `false`. Roll out in this order:

1. Apply Alembic migration `0004_match_timelines` (`cd backend && .venv/bin/alembic upgrade head`).
2. Deploy the backend with `JOINT_EVIDENCE_ENABLED=false` so the evidence route exists but stays dark.
3. Deploy the compatible frontend (explicit Prepare timeline evidence action).
4. Confirm Timeline cache TTLs (`TIMELINE_CACHE_TTL_SECONDS`, `TIMELINE_NOT_FOUND_TTL_SECONDS`).
5. Enable the flag with `JOINT_EVIDENCE_ENABLED=true`.
6. Monitor closed-label metrics: `joint_evidence_api_requests_total` (`outcome=ready|error`, `error_code` allowlist), `joint_evidence_timeline_cache_total`, `joint_evidence_windows_total{result="planned"}`, `joint_evidence_window_truncations_total`, `joint_evidence_replay_coverage_total{coverage="full|partial|unavailable"}`, and `joint_evidence_singleflight_total`.
7. To roll back, set only `JOINT_EVIDENCE_ENABLED=false`. Do not downgrade migration `0004`.

J1 does not call OpenAI and does not create new media; local extra external-service cost is approximately zero beyond existing Riot and local compute. Only user-owned or explicitly authorized recordings may enter Replay.

Timeline-only smoke: `make smoke-riot` against a running backend with the flag on. It posts evidence twice and prints only `outcome`, fact/window counts, cache consistency, elapsed time, and a safe request ID.

Authorized Replay-linked smoke: `make smoke-replay` or `make e2e-replay-compose` with the flag on. After Replay is ready and before delete, it posts evidence with the in-memory possession token, checks artifact references against the authorized manifest, then finishes delete and zero-residue checks.

Production API keys require normal rotation and must never be pasted into source files, fixtures, logs, or chat.

### Deterministic Analysis V1 rollout

Deterministic Analysis V1 computes an on-demand single-match score, five role-weighted dimensions, up to three structured data findings, and up to three next-match goals from normalized Match-V5 and Timeline data. It uses fixed versioned formulas and rules only: no model, prompt, OpenAI call, replay vision, media inspection, behavioral inference, or causal claim. Joint Evidence J1 remains a separate neutral evidence route; analysis may reference exact J1 fact IDs but never changes J1 facts or opens Replay automatically.

At the Riot boundary, `UTILITY -> Support`; the internal role is `support`, and user-facing English is always `Support`. This is a single-match LoL AI Coach score, not a Riot score, rank, MMR, or ELO.

`DETERMINISTIC_ANALYSIS_ENABLED` defaults to `false` and requires `JOINT_EVIDENCE_ENABLED=true`. Roll out in this order:

1. Apply Alembic migration `0005_deterministic_analyses` (`cd backend && .venv/bin/alembic upgrade head`).
2. Deploy the backend and compatible frontend with `JOINT_EVIDENCE_ENABLED=false` and `DETERMINISTIC_ANALYSIS_ENABLED=false`; the analysis routes stay dark.
3. Confirm `ANALYSIS_RETENTION_DAYS` (default `30`) and the J1 Timeline cache settings.
4. Enable J1 first, then set `DETERMINISTIC_ANALYSIS_ENABLED=true`.
5. Run `make smoke-riot`, then run `make smoke-analysis` twice. Both analysis runs must report `repeat=ok`, `locales=2`, and `versions=ok` without identifiers or payloads.
6. Monitor the closed-label `analysis_api_requests_total`, `analysis_duration_seconds`, `analysis_cache_total`, `analysis_results_total`, `analysis_coverage_total`, `analysis_unavailable_signals_total`, and `analysis_idempotency_total` metrics.
7. Roll back by setting only `DETERMINISTIC_ANALYSIS_ENABLED=false`. Do not disable J1, downgrade migration `0005`, or delete retained rows as part of flag rollback.

`make smoke-analysis` reuses ignored `RIOT_SMOKE_GAME_NAME`, `RIOT_SMOKE_TAG_LINE`, and `RIOT_SMOKE_PLATFORM`, requires a configured Riot key plus both feature prerequisites, and targets an already-running backend. Its only success line has this safe shape:

```text
analysis=completed|partial metrics=<n> dimensions=5 findings=<0..3> goals=<0..3> coverage=<bucket> repeat=ok locales=2 request_id=<safe-or-none> versions=ok
```

The smoke resolves the configured account, selects the newest match that supports both detail and analysis, creates in `zh-CN` and `en-US`, loads both locales, and verifies one persisted locale-neutral result. Live Riot smoke, browser acceptance, isolated Compose acceptance, and GitHub CI for Deterministic Analysis V1 are not recorded as passed until the verification phase completes them.

### Requirements

- Node.js 20.9+ (CI uses Node.js 22)
- pnpm 11+ (CI uses pnpm 11.9.0)
- Python 3.11+
- PostgreSQL 17 for repository integration verification
- FFmpeg and ffprobe on `PATH` for local replay processing (`brew install ffmpeg` on macOS)
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

For Replay R1, also set `REPLAY_ENABLED=true` and a local-only `REPLAY_TOKEN_SECRET` of at least 32 bytes (never commit the secret):

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
make dev-replay-worker
```

Local replay files default to `<repo>/var/replays` unless `REPLAY_LOCAL_ROOT` overrides that path. Compose mounts a private `replay_data` volume at `/var/lib/lol-ai-coach/replays` for both the API and `replay-worker`.

Open `http://localhost:3000/zh-CN` or `http://localhost:3000/en-US`.

### Verification and live smoke

```bash
make verify
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test make verify-postgres
make verify-replay
make verify-replay-ffmpeg
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test make verify-replay-postgres
make smoke-riot
make smoke-analysis
make smoke-analysis
make smoke-replay
```

- `make verify` runs non-integration backend/frontend tests (excluding real FFmpeg), lint, formatting, type checks, production build, and a whitespace check. It does not require a database.
- `make verify-postgres` requires a dedicated, reachable `TEST_DATABASE_URL`, applies Alembic, and runs the PostgreSQL repository integration suite. It fails rather than silently skipping when the variable or database is absent.
- `make verify-replay` runs Replay unit/API/frontend tests only (`not integration and not replay_ffmpeg`). Frontend portion uses `pnpm test` for the replay Vitest files.
- `make verify-replay-ffmpeg` requires real `ffmpeg`/`ffprobe` binaries and runs the marked media integration test.
- `make verify-replay-postgres` requires `TEST_DATABASE_URL`, upgrades migrations, and runs PostgreSQL integration tests excluding the FFmpeg media suite.
- `make smoke-riot` calls an already-running local backend. It also requires non-empty ignored `RIOT_SMOKE_GAME_NAME`, `RIOT_SMOKE_TAG_LINE`, and `RIOT_SMOKE_PLATFORM` settings plus `RIOT_API_KEY`. When `RIOT_PLATFORM_DETECTION_ENABLED=true` on both the smoke runner and the running API, it also posts `/api/v1/players/detect` twice and prints only safe detection fields (`status`, candidate count, elapsed time, request ID). Optional `RIOT_SMOKE_AMBIGUOUS_RIOT_ID` exercises confirm when set. When `JOINT_EVIDENCE_ENABLED=true`, it posts Timeline-only evidence twice for a `detail_supported` + `analysis_supported` match and prints only outcome, counts, cache consistency, elapsed time, and a safe request ID; when the flag is false it prints a safe skip line. The command never prints the Riot ID, PUUID, match ID, key, full URL, or raw response body.
- `make smoke-analysis` reuses the same ignored Riot identity, requires `JOINT_EVIDENCE_ENABLED=true` and `DETERMINISTIC_ANALYSIS_ENABLED=true`, exercises both analysis locales and persisted reuse, and prints only the safe contract documented above. Run it twice during rollout.
- `make smoke-replay` requires a running API + replay worker, FFmpeg, and ignored `REPLAY_SMOKE_MATCH_ID` / `REPLAY_SMOKE_PUUID`. It generates a 600s 320×180 lavfi fixture at runtime, exercises create/upload/complete/poll/artifacts, optional linked evidence (when `JOINT_EVIDENCE_ENABLED=true`), and delete, and prints only generic lines such as `replay=ready artifacts=3 delete=ok`.

CI runs non-integration backend checks, the PostgreSQL integration gate, and all frontend checks. It intentionally does not run a live Riot smoke flow because development keys and smoke identities are local secrets.

Observed acceptance on this workstation: the final automated gate passed 945 backend tests and 252 frontend tests together with Ruff, formatting, ESLint, mypy, TypeScript, and the production build. The PostgreSQL gates passed 78 general integration tests and 55 integration-directory tests, and the real FFmpeg gate passed its probe/normalize/frame-extraction test. Live Riot/J1 smoke completed with the safe generic results `matches=10 locales=2 repeat=ok` and `outcome=ready facts=1125 windows=25 cache=consistent`. Two consecutive Deterministic Analysis V1 smoke runs each completed with `metrics=8 dimensions=5 findings=3 goals=0 coverage=100 repeat=ok locales=2 versions=ok`. On the real Chinese desktop match page, the cached five-dimension analysis and exact J1 fact focus were observed while Replay remained separate; that inspection exposed a raw upstream role code, and bilingual component tests now cover localized product labels for all five roles. A final real-page English and 320px browser recheck could not be completed because the in-app browser blocked the identifier-bearing route under its URL safety policy, so that manual boundary remains unverified rather than inferred from tests. Isolated Compose returned 200 for both locale routes, produced 21 Replay artifacts, linked 25 J1 windows, completed the authorized lifecycle through delete, confirmed zero files in `replay_data`, and removed its isolated containers and volumes. GitHub CI remains separate and unverified until the branch is pushed and the resulting workflow finishes.

### Configuration

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Host-local SQLAlchemy async PostgreSQL URL. |
| `COMPOSE_DATABASE_URL` | Container-internal PostgreSQL URL (`db` host). |
| `TEST_DATABASE_URL` | Dedicated disposable PostgreSQL database for `make verify-postgres`. |
| `RIOT_API_KEY` | Server-only Riot key; leave empty in `.env.example`. |
| `RIOT_SMOKE_GAME_NAME` / `RIOT_SMOKE_TAG_LINE` | Ignored local smoke identity; never commit a real player identifier. |
| `RIOT_SMOKE_PLATFORM` | Compatibility resolve smoke platform (closed catalog value). |
| `RIOT_SMOKE_AMBIGUOUS_RIOT_ID` | Optional ignored Riot ID for multi-platform confirm smoke; leave empty to skip. |
| `RIOT_PLATFORM_DETECTION_ENABLED` | Enables automatic platform detection APIs. Default `false`. |
| `RIOT_PLATFORM_DETECTION_TTL_SECONDS` / `RIOT_PLATFORM_DETECTION_NOT_FOUND_TTL_SECONDS` / `RIOT_PLATFORM_CONFIRMATION_TTL_SECONDS` | Detection cache and confirmation TTLs. |
| `RIOT_ACCOUNT_PRIMARY_REGION` | Primary Account-V1 region before stable regional fallback. |
| `JOINT_EVIDENCE_ENABLED` | Enables Joint Evidence J1 (`POST /api/v1/matches/{match_id}/evidence`). Default `false`. |
| `DETERMINISTIC_ANALYSIS_ENABLED` | Enables deterministic single-match analysis. Default `false`; requires `JOINT_EVIDENCE_ENABLED=true`. Server-only and never a `NEXT_PUBLIC_*` value. |
| `ANALYSIS_RETENTION_DAYS` | Retention window for persisted deterministic analyses. Default `30`; allowed range `1..365`. |
| `TIMELINE_CACHE_TTL_SECONDS` / `TIMELINE_NOT_FOUND_TTL_SECONDS` | Positive and negative Timeline cache TTLs. |
| `SMOKE_API_BASE_URL` | Already-running local backend base URL, default `http://localhost:8000`. |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-visible backend base URL; contains no secret. |
| `REPLAY_ENABLED` | Enables Replay APIs/worker. Default `false`. |
| `REPLAY_TOKEN_SECRET` | Server-only HMAC secret (≥32 bytes) when replay is enabled. Leave empty in `.env.example`; generate locally. |
| `REPLAY_STORAGE_BACKEND` | `local` (default) or `s3`. |
| `REPLAY_LOCAL_ROOT` | Private local storage root. Defaults to `<repo>/var/replays`. Compose uses `/var/lib/lol-ai-coach/replays`. |
| `REPLAY_S3_*` | S3-compatible endpoint/region/bucket/credentials/prefix. Never expose to the frontend. |
| `REPLAY_GATEWAY_RATE_LIMITS_ENFORCED` | Production gate. Must be `true` when `APP_ENV=production` and replay is enabled. When `true`, the API enforces (per client IP, in-memory): 5 creates/hour, 2 concurrent local uploads, 60 ordinary requests/minute. Rejections return `429 REPLAY_RATE_LIMITED` with a `Retry-After` header. |
| `REPLAY_GATEWAY_CREATE_LIMIT_PER_HOUR` / `REPLAY_GATEWAY_UPLOAD_CONCURRENCY_LIMIT` / `REPLAY_GATEWAY_REQUEST_LIMIT_PER_MINUTE` | Override the default gateway rate limits above. |
| `REPLAY_TRUSTED_PROXY_CIDRS` | Comma-separated CIDRs. `X-Forwarded-For` is only trusted for rate-limit client-IP resolution when the direct peer is inside one of these networks; otherwise the direct socket IP is used. Empty (default) means never trust `X-Forwarded-For`. Raw client IPs are never logged, only a truncated SHA-256 reference. |
| `REPLAY_SMOKE_MATCH_ID` / `REPLAY_SMOKE_PUUID` | Ignored local smoke binding identity; leave empty in `.env.example`. |

### API

- `GET /health/live`: process liveness without database access.
- `GET /health/ready`: database/configuration readiness without calling Riot.
- `POST /api/v1/players/detect`: single-field Riot ID platform detection (`resolved` or `confirmation_required`). Returns `404 NOT_FOUND` while the feature flag is off.
- `POST /api/v1/players/detect/{detection_id}/confirm`: confirms one returned candidate platform.
- `GET /api/v1/players/resolve`: compatibility resolve for a valid `platform`, `game_name`, and `tag_line`.
- `GET /api/v1/players/{puuid}/matches`: returns up to ten newest-to-oldest normalized matches.
- `GET /api/v1/matches/{match_id}`: returns a localized supported match detail for the selected player.
- `POST /api/v1/matches/{match_id}/evidence`: on-demand Joint Evidence J1 (404 `NOT_FOUND` while `JOINT_EVIDENCE_ENABLED=false`).
- `POST /api/v1/analyses`: create or reuse one deterministic analysis for `platform`, `match_id`, and `puuid` (404 `NOT_FOUND` while `DETERMINISTIC_ANALYSIS_ENABLED=false`).
- `GET /api/v1/analyses/{analysis_id}`: load the persisted locale-neutral analysis with localized response selection.

### Replay R1

Replay R1 adds authorized upload of an uploader-owned recording bound to a supported match, worker-side probe/normalize/frame extraction, status polling, artifact access, retry, and deletion. It does **not** call OpenAI, score play, or emit coaching conclusions. UI copy states that replay evidence is ready without an AI coaching conclusion.

Rights limits: only uploader-owned or explicitly authorized recordings may be uploaded. Public, purchased, or third-party teaching video is never ingested without the rights holder’s permission. Rights attestation version `2026-08-01` is required on create.

Retention: upload URLs expire after 30 minutes; source media is retained 24 hours after processing; derived artifacts are retained 7 days after `ready`; user delete and retention jobs scrub media and sensitive metadata.

S3 bucket CORS (when `REPLAY_STORAGE_BACKEND=s3`): allow the frontend origin for `PUT`/`GET` of presigned object URLs, expose `ETag`/`Content-Length`, and do not put bucket credentials in browser code.

Seven Replay APIs:

- `POST /api/v1/replays`
- `PUT /api/v1/replays/{replay_id}/content` (local backend upload)
- `POST /api/v1/replays/{replay_id}/complete`
- `GET /api/v1/replays/{replay_id}`
- `GET /api/v1/replays/{replay_id}/artifacts`
- `POST /api/v1/replays/{replay_id}/retry`
- `DELETE /api/v1/replays/{replay_id}`

Artifact bytes are served at `GET /api/v1/replays/{replay_id}/artifacts/{artifact_id}/content` with the possession token (or via short-lived presigned URLs in S3 mode).

Gateway rate limits (`REPLAY_GATEWAY_RATE_LIMITS_ENFORCED`) are enforced in-process per client IP and return `429 REPLAY_RATE_LIMITED`; see the Configuration table. Raw client IPs are never logged.

Production hardening: the backend/worker container runs as a non-root user; the `replay-worker` Compose service runs with a read-only root filesystem, `tmpfs` scratch space at `/tmp` and `/var/tmp`, and a `stop_grace_period` so an in-flight job can finish draining after `SIGTERM` before being force-killed. Processing duration, failures (by error code), job retries, and cleanup lag are recorded in an in-memory metrics registry exposed as Prometheus text at `GET /internal/metrics` (an internal-only endpoint, not for public/browser use; worker-recorded metrics are process-local, so this endpoint reflects the API process's own view unless worker and API share a process).

Run `make e2e-replay-compose` (or `./scripts/e2e_replay_compose.sh`) to exercise the full Docker Compose flow end to end: locale routes, upload/complete/refresh/frames, Replay-linked evidence, delete, and a post-delete check that the `replay_data` volume contains zero files. It requires Docker, Compose, and configured `REPLAY_SMOKE_MATCH_ID`/`REPLAY_SMOKE_PUUID`. If Docker, Compose, or those smoke identities are missing, the script prints `FAILED` and exits non-zero; it does not print `SKIPPED`.

### Riot disclaimer

LoL AI Coach is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

<a id="中文"></a>

## 中文

LoL AI Coach 是一个中英双语的《英雄联盟》对局数据浏览工具。Phase 2 可以查询 Riot ID、展示玩家资料与最多十场近期对局，并打开本地化的标准对局详情。它只呈现规范化的 Riot 数据，不对玩家表现做判断。

### Phase 2 状态与边界

- 已提供：单字段 Riot ID 查询与可选自动服务器识别（功能开关控制）、兼容期显式平台 resolve 路由、规范玩家资料、近期对局列表，以及中英文标准对局详情（支持时展示十名参与者）。
- 自动识别覆盖 Riot 官方十六个英雄联盟平台，候选服务器名称以后端响应为准。
- 标签与平台相互独立。例如 `#1234` 这类数字标签有效，绝不会由任何平台代码自动推断。
- 队列 `400`（自选模式）和 `420`（单排/双排）标记为数据支持。其他返回队列仍会展示；若队伍结构不支持，则不会提供详情页。
- 静态资料使用与对局版本兼容的 Data Dragon：`en-US` 映射到 `en_US`，`zh-CN` 映射到 `zh_CN`。若名称或资源无法解析，数值数据仍会展示并给出本地化降级提示；不会偷偷用当前版本名称替代。
- Phase 2 / Replay R1 本身仍不评分、不判断玩家表现。确定性分析 V1 是下文说明的独立按需数据复盘层；它不增加 AI 调用、回放解读、行为判断、走位、操作、意识、意图、因果推断、OP.GG 集成或原始上游 JSON 存储。Match Timeline 证据属于 Joint Evidence J1，在 `JOINT_EVIDENCE_ENABLED=true` 之前保持关闭。

### 自动识别上线顺序

`RIOT_PLATFORM_DETECTION_ENABLED` 默认 `false`。按以下顺序上线：

1. 将数据库迁移到 Alembic head（含 `0003_player_platform_detection`）。
2. 先部署后端并保持 `RIOT_PLATFORM_DETECTION_ENABLED=false`。
3. 部署兼容前端（单 Riot ID 输入与识别客户端）。
4. 配置主区域与检测/确认 TTL。
5. 将 `RIOT_PLATFORM_DETECTION_ENABLED=true` 开启识别。
6. 监控 `riot_platform_detection_*` 与 `riot_platform_confirmation_total` 指标。
7. 回滚时把开关设回 `false`；兼容 `GET /api/v1/players/resolve` 仍可用。

### Joint Evidence J1 上线顺序

`JOINT_EVIDENCE_ENABLED` 默认 `false`。按以下顺序上线：

1. 先执行 Alembic 迁移 `0004_match_timelines`（`cd backend && .venv/bin/alembic upgrade head`）。
2. 先部署后端并保持 `JOINT_EVIDENCE_ENABLED=false`。
3. 部署兼容前端（显式的「准备时间线证据」操作）。
4. 确认 Timeline 缓存 TTL（`TIMELINE_CACHE_TTL_SECONDS`、`TIMELINE_NOT_FOUND_TTL_SECONDS`）。
5. 将 `JOINT_EVIDENCE_ENABLED=true` 开启证据。
6. 监控闭合标签指标：`joint_evidence_api_requests_total`（`outcome=ready|error` 与允许的 `error_code`）、`joint_evidence_timeline_cache_total`、`joint_evidence_windows_total{result="planned"}`、`joint_evidence_window_truncations_total`、`joint_evidence_replay_coverage_total{coverage="full|partial|unavailable"}`、`joint_evidence_singleflight_total`。
7. 回滚时只把 `JOINT_EVIDENCE_ENABLED` 设回 `false`，不要降级迁移 `0004`。

J1 不调用 OpenAI、不创建新媒体；本地新增外部服务成本约为零（仍只有既有 Riot 与本地计算）。进入 Replay 的录像必须由用户拥有或获得明确授权。

仅时间线冒烟：对已运行后端执行 `make smoke-riot`（flag 开启时）。脚本会把 evidence 请求发两次，只打印 outcome、facts/windows 数量、cache 一致性、耗时和安全 request ID。

已授权 Replay 关联冒烟：`make smoke-replay` 或 `make e2e-replay-compose`（flag 开启时）。Replay ready 之后、delete 之前会带 possession token 调用 evidence，校验 artifact 引用是独立授权 manifest 的子集，然后继续完成删除与零残留检查。

生产 API Key 需按常规轮换，绝不能粘贴进源码、夹具、日志或聊天。

### 确定性分析 V1 上线顺序

确定性分析 V1 根据规范化 Match-V5 与 Timeline 数据，按需计算单局综合评分、五个按位置加权的维度、最多三条结构化数据发现和最多三个下一局目标。它只使用固定且带版本的公式与规则：不使用模型、Prompt、OpenAI、回放视觉、媒体检查、行为推断或因果结论。Joint Evidence J1 仍是独立的中立证据路由；分析可以引用精确的 J1 fact ID，但不会改写 J1 事实，也不会自动打开 Replay。

在 Riot 边界执行 `UTILITY -> 辅助`：内部位置固定为 `support`，中文界面始终显示“辅助”。这是 LoL AI Coach 的单局评分，不是 Riot 评分、段位、MMR 或 ELO。

`DETERMINISTIC_ANALYSIS_ENABLED` 默认 `false`，并要求 `JOINT_EVIDENCE_ENABLED=true`。按以下顺序上线：

1. 应用 Alembic 迁移 `0005_deterministic_analyses`（`cd backend && .venv/bin/alembic upgrade head`）。
2. 先部署后端和兼容前端，同时保持 `JOINT_EVIDENCE_ENABLED=false` 与 `DETERMINISTIC_ANALYSIS_ENABLED=false`，使分析路由保持关闭。
3. 确认 `ANALYSIS_RETENTION_DAYS`（默认 `30`）与 J1 Timeline 缓存配置。
4. 先开启 J1，再设置 `DETERMINISTIC_ANALYSIS_ENABLED=true`。
5. 先运行 `make smoke-riot`，再连续运行两次 `make smoke-analysis`；两次分析都必须显示 `repeat=ok`、`locales=2`、`versions=ok`，且不输出任何标识符或响应载荷。
6. 监控闭合标签指标：`analysis_api_requests_total`、`analysis_duration_seconds`、`analysis_cache_total`、`analysis_results_total`、`analysis_coverage_total`、`analysis_unavailable_signals_total`、`analysis_idempotency_total`。
7. 回滚时只设置 `DETERMINISTIC_ANALYSIS_ENABLED=false`；不要关闭 J1、降级迁移 `0005`，也不要在 flag 回滚时删除保留数据。

`make smoke-analysis` 复用被忽略的 `RIOT_SMOKE_GAME_NAME`、`RIOT_SMOKE_TAG_LINE`、`RIOT_SMOKE_PLATFORM`，要求 Riot 密钥和两个功能前置条件均已配置，并连接已运行的后端。成功时只允许输出以下安全格式：

```text
analysis=completed|partial metrics=<n> dimensions=5 findings=<0..3> goals=<0..3> coverage=<bucket> repeat=ok locales=2 request_id=<safe-or-none> versions=ok
```

该冒烟会查询配置账号，选择同时支持详情和分析的最新对局，以 `zh-CN` 和 `en-US` 创建并读取同一份分析，验证持久化结果不依赖语言。确定性分析 V1 的在线 Riot 冒烟、浏览器验收、隔离 Compose 验收和 GitHub CI 在验证阶段真正完成前，均不记录为通过。

### 环境要求

- Node.js 20.9+（CI 使用 Node.js 22）
- pnpm 11+（CI 使用 pnpm 11.9.0）
- Python 3.11+
- PostgreSQL 17（仓库集成验证需要）
- 本地回放处理需要 `PATH` 上的 FFmpeg 与 ffprobe（macOS 可用 `brew install ffmpeg`）
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

启用 Replay R1 时，在本地 `.env` 设置 `REPLAY_ENABLED=true`，并生成至少 32 字节、仅本地使用的 `REPLAY_TOKEN_SECRET`（切勿提交）：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
make dev-replay-worker
```

本地回放文件默认写入 `<repo>/var/replays`，可用 `REPLAY_LOCAL_ROOT` 覆盖。Compose 会为 API 与 `replay-worker` 挂载私有卷 `replay_data` 到 `/var/lib/lol-ai-coach/replays`。

打开 `http://localhost:3000/zh-CN` 或 `http://localhost:3000/en-US`。

### 验证与在线冒烟

```bash
make verify
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test make verify-postgres
make verify-replay
make verify-replay-ffmpeg
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test make verify-replay-postgres
make smoke-riot
make smoke-analysis
make smoke-analysis
make smoke-replay
```

- `make verify` 运行非集成后端/前端测试（排除真实 FFmpeg）、静态检查、格式检查、类型检查、前端生产构建和空白检查，不需要数据库。
- `make verify-postgres` 需要专用且可连接的 `TEST_DATABASE_URL`，会执行 Alembic 并运行 PostgreSQL 仓库集成测试；变量或数据库缺失时会失败，不会静默跳过。
- `make verify-replay` 仅运行 Replay 单元/API/前端测试（`not integration and not replay_ffmpeg`）；前端部分用 `pnpm test` 跑 replay Vitest 文件。
- `make verify-replay-ffmpeg` 需要真实 `ffmpeg`/`ffprobe`，运行标记的媒体集成测试。
- `make verify-replay-postgres` 需要 `TEST_DATABASE_URL`，升级迁移并运行排除 FFmpeg 媒体套件的 PostgreSQL 集成测试。
- `make smoke-riot` 调用已经运行的本地后端，同时要求忽略的 `RIOT_SMOKE_GAME_NAME`、`RIOT_SMOKE_TAG_LINE`、`RIOT_SMOKE_PLATFORM` 非空，以及已配置的 `RIOT_API_KEY`。成功时仅输出通用计数；`JOINT_EVIDENCE_ENABLED=true` 时会额外做两次 Timeline-only evidence 请求并只打印 outcome、计数、cache 一致性和安全 request ID，flag 关闭时只打印安全 skip 行。不会输出 Riot ID、PUUID、对局 ID、密钥、完整 URL 或原始响应体。
- `make smoke-analysis` 复用同一套被忽略的 Riot 身份，要求 `JOINT_EVIDENCE_ENABLED=true` 与 `DETERMINISTIC_ANALYSIS_ENABLED=true`，验证双语分析和持久化复用，并只输出上文定义的安全格式；上线时连续运行两次。
- `make smoke-replay` 需要已运行的 API 与 replay worker、FFmpeg，以及忽略的 `REPLAY_SMOKE_MATCH_ID` / `REPLAY_SMOKE_PUUID`。脚本会在运行时生成 600 秒 320×180 lavfi 测试视频，完成 create/upload/complete/poll/artifacts、可选的关联 evidence（`JOINT_EVIDENCE_ENABLED=true` 时）和 delete，并只打印类似 `replay=ready artifacts=3 delete=ok` 的通用结果。

CI 会运行非集成后端检查、PostgreSQL 集成门和所有前端检查。由于开发密钥和冒烟账号属于本地机密，CI 有意不运行在线 Riot 冒烟流程。

本机已实际观察到以下验收结果：最终自动化门禁通过 945 个后端测试、252 个前端测试，以及 Ruff、格式检查、ESLint、mypy、TypeScript 和生产构建。PostgreSQL 通用集成门通过 78 个测试，integration 目录专项门通过 55 个测试，真实 FFmpeg 探测、标准化与抽帧门通过 1 个测试。在线 Riot/J1 冒烟以安全通用结果 `matches=10 locales=2 repeat=ok` 和 `outcome=ready facts=1125 windows=25 cache=consistent` 完成；连续两次确定性分析 V1 冒烟均得到 `metrics=8 dimensions=5 findings=3 goals=0 coverage=100 repeat=ok locales=2 versions=ok`。真实中文桌面比赛页已观察到缓存的五维分析与精确 J1 fact 聚焦，且 Replay 始终独立；该检查曾暴露一个上游位置代码，现已有中英文组件测试覆盖全部五个位置的产品化标签。由于应用内浏览器对含标识符路由执行 URL 安全拦截，最终真实页面的英文与 320px 复验无法完成，因此这项人工边界仍记为未验证，不用自动化测试结果代替。隔离 Compose 的中英文路由均返回 200，生成 21 个 Replay artifacts、关联 25 个 J1 窗口，已授权生命周期完成到删除，`replay_data` 文件数为 0，专用容器与卷也已清理。GitHub CI 与本地结果分开记录；在分支推送且对应工作流结束前仍为未验证。

### 配置

| 变量 | 用途 |
| --- | --- |
| `DATABASE_URL` | 本机 SQLAlchemy 异步 PostgreSQL 地址。 |
| `COMPOSE_DATABASE_URL` | 容器内部 PostgreSQL 地址（`db` 主机）。 |
| `TEST_DATABASE_URL` | `make verify-postgres` 使用的独立可清理 PostgreSQL 数据库。 |
| `RIOT_API_KEY` | 仅后端使用的 Riot 密钥；`.env.example` 必须为空。 |
| `RIOT_SMOKE_GAME_NAME` / `RIOT_SMOKE_TAG_LINE` | 被忽略的本地冒烟身份；不要提交真实玩家标识。 |
| `RIOT_SMOKE_PLATFORM` | 兼容 resolve 冒烟平台（封闭目录中的平台代码，如 `NA1` / `EUW1` / `KR`）。 |
| `RIOT_ACCOUNT_PRIMARY_REGION` | Account-V1 主区域，随后回退到稳定区域。 |
| `JOINT_EVIDENCE_ENABLED` | 启用 Joint Evidence J1（`POST /api/v1/matches/{match_id}/evidence`）；默认 `false`。 |
| `DETERMINISTIC_ANALYSIS_ENABLED` | 启用确定性单局分析；默认 `false`，且要求 `JOINT_EVIDENCE_ENABLED=true`。仅后端使用，不得设置为 `NEXT_PUBLIC_*`。 |
| `ANALYSIS_RETENTION_DAYS` | 已持久化确定性分析的保留天数；默认 `30`，允许范围 `1..365`。 |
| `TIMELINE_CACHE_TTL_SECONDS` / `TIMELINE_NOT_FOUND_TTL_SECONDS` | Timeline 正/负缓存 TTL。 |
| `SMOKE_API_BASE_URL` | 已运行本地后端的基础地址，默认 `http://localhost:8000`。 |
| `NEXT_PUBLIC_API_BASE_URL` | 浏览器可见的后端基础地址；不包含密钥。 |
| `REPLAY_ENABLED` | 启用 Replay API/worker；默认 `false`。 |
| `REPLAY_TOKEN_SECRET` | 启用回放时使用的服务端 HMAC 密钥（≥32 字节）。`.env.example` 必须留空，仅在本地生成。 |
| `REPLAY_STORAGE_BACKEND` | `local`（默认）或 `s3`。 |
| `REPLAY_LOCAL_ROOT` | 私有本地存储根目录；默认 `<repo>/var/replays`。Compose 使用 `/var/lib/lol-ai-coach/replays`。 |
| `REPLAY_S3_*` | S3 兼容 endpoint/region/bucket/凭证/前缀；绝不能暴露给前端。 |
| `REPLAY_GATEWAY_RATE_LIMITS_ENFORCED` | 生产上线门。`APP_ENV=production` 且启用回放时必须为 `true`。为 `true` 时后端按客户端 IP 在进程内强制执行：每小时 5 次 create、2 个并发本地上传、每分钟 60 次普通请求；超限返回 `429 REPLAY_RATE_LIMITED` 并带 `Retry-After`。 |
| `REPLAY_GATEWAY_CREATE_LIMIT_PER_HOUR` / `REPLAY_GATEWAY_UPLOAD_CONCURRENCY_LIMIT` / `REPLAY_GATEWAY_REQUEST_LIMIT_PER_MINUTE` | 覆盖上述默认网关限流值。 |
| `REPLAY_TRUSTED_PROXY_CIDRS` | 逗号分隔的 CIDR 列表。仅当直连 socket 位于配置网段内时才信任 `X-Forwarded-For` 做限流用客户端 IP 解析；默认留空，即从不信任该请求头。原始客户端 IP 从不写入日志，仅记录截断后的 SHA-256 引用。 |
| `REPLAY_SMOKE_MATCH_ID` / `REPLAY_SMOKE_PUUID` | 被忽略的本地冒烟绑定身份；`.env.example` 必须留空。 |

### API

- `GET /health/live`：进程存活检查，不访问数据库。
- `GET /health/ready`：数据库/配置就绪检查，不调用 Riot。
- `GET /api/v1/players/resolve`：根据有效 `platform`、`game_name`、`tag_line` 查询玩家。
- `GET /api/v1/players/{puuid}/matches`：返回最多十场按新到旧排序的规范化对局。
- `GET /api/v1/matches/{match_id}`：返回所选玩家的本地化、受支持对局详情。
- `POST /api/v1/matches/{match_id}/evidence`：按需 Joint Evidence J1（`JOINT_EVIDENCE_ENABLED=false` 时返回 404 `NOT_FOUND`）。
- `POST /api/v1/analyses`：按 `platform`、`match_id`、`puuid` 创建或复用确定性分析（`DETERMINISTIC_ANALYSIS_ENABLED=false` 时返回 404 `NOT_FOUND`）。
- `GET /api/v1/analyses/{analysis_id}`：按语言读取同一份不依赖语言的持久化分析结果。

### Replay R1

Replay R1 支持将上传者自有/已授权录像绑定到受支持对局，由独立 worker 探测、标准化并抽取证据帧，提供状态轮询、产物访问、重试与删除。本阶段**不**调用 OpenAI、不评分、不输出教练结论；界面明确说明录像证据已准备但尚未产生 AI 教练结论。

权利限制：仅允许上传者自有或获得明确授权的录像。未获权利人许可时，不得接入公开、购买或第三方教学视频。创建时必须提交权利声明版本 `2026-08-01`。

保留期：上传地址 30 分钟过期；处理成功或失败后源文件保留 24 小时；`ready` 产物保留 7 天；用户删除与定期清理会清除媒体并擦除敏感元数据。

S3 bucket CORS（`REPLAY_STORAGE_BACKEND=s3` 时）：允许前端源站对预签名对象 URL 做 `PUT`/`GET`，暴露 `ETag`/`Content-Length`，且不得把桶凭证放进浏览器代码。

七个 Replay API：

- `POST /api/v1/replays`
- `PUT /api/v1/replays/{replay_id}/content`（本地后端上传）
- `POST /api/v1/replays/{replay_id}/complete`
- `GET /api/v1/replays/{replay_id}`
- `GET /api/v1/replays/{replay_id}/artifacts`
- `POST /api/v1/replays/{replay_id}/retry`
- `DELETE /api/v1/replays/{replay_id}`

产物字节通过带 possession token 的 `GET /api/v1/replays/{replay_id}/artifacts/{artifact_id}/content` 提供（S3 模式也可使用短时预签名 URL）。

网关限流（`REPLAY_GATEWAY_RATE_LIMITS_ENFORCED`）按客户端 IP 在进程内强制执行，超限返回 `429 REPLAY_RATE_LIMITED`；详见配置表。原始客户端 IP 从不写入日志。

生产加固：后端/worker 容器以非 root 用户运行；`replay-worker` Compose 服务使用只读根文件系统，通过 `/tmp`、`/var/tmp` 的 `tmpfs` 提供可写临时空间，并设置 `stop_grace_period`，使正在处理中的任务在收到 `SIGTERM` 后仍有时间跑完再被强制终止。处理耗时、按错误码统计的失败数、任务重试次数与清理延迟都记录在内存指标注册表中，以 Prometheus 文本格式通过 `GET /internal/metrics` 暴露（仅限内部使用，不面向浏览器/公网；worker 记录的指标是进程本地的，除非 worker 与 API 共用进程，否则该端点只反映 API 进程自身的视角）。

运行 `make e2e-replay-compose`（或 `./scripts/e2e_replay_compose.sh`）可端到端跑通完整 Docker Compose 流程：本地化路由、上传/完成/刷新/取帧、Replay 关联 evidence、删除，以及删除后确认 `replay_data` volume 文件数为 0。需要 Docker、Compose，以及配置好的 `REPLAY_SMOKE_MATCH_ID`/`REPLAY_SMOKE_PUUID`。若 Docker、Compose 或这些冒烟身份缺失，脚本会打印 `FAILED` 并以非零状态退出，不会打印 `SKIPPED`。

### Riot 声明

LoL AI Coach 未获得 Riot Games 认可，也不代表 Riot Games 或任何正式参与 Riot Games 产品制作与管理人员的观点或意见。Riot Games 及其相关资产均为 Riot Games, Inc. 的商标或注册商标。
