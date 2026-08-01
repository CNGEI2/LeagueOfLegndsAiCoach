# LoL AI Coach Replay R1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有对局详情页加入已授权录像的上传、校验、标准化、时间同步、证据帧、状态查询和自动删除能力，但不调用 AI、不生成任何教练结论。

**Architecture:** FastAPI 只处理短时 API 请求和授权；独立 PostgreSQL Worker 通过 `FOR UPDATE SKIP LOCKED` 领取任务，用 `ffprobe`/`ffmpeg` 处理视频。存储通过统一接口支持开发环境本地目录和生产环境 S3-compatible 对象存储，Next.js 使用 possession token 完成上传、轮询和受保护的产物访问。

**Tech Stack:** Python 3.11、FastAPI、Pydantic 2、SQLAlchemy 2 async、Alembic、PostgreSQL 17、FFmpeg/ffprobe、boto3、Next.js 16、React 19、TypeScript、Zod 4、Vitest、Testing Library、Docker Compose。

## Global Constraints

- 只在 `/Users/pf/lol-ai-coach/.worktrees/phase2-riot-integration` 的 `a0d5c01` 之后开发；不要从仍停留在 Phase 1 的 `main` 开始。
- 开始执行时在该 worktree 中从当前 HEAD 创建 `feature/replay-r1`；如果该分支已存在则继续使用，禁止重复创建或覆盖用户修改。
- Python 版本保持 `>=3.11`；Node.js 保持 `>=20.9.0`；PostgreSQL 集成目标保持 17。
- 接受 `.mp4`、`.mkv`、`.mov`、`.webm`，最大 4 GiB，探测时长 600–5400 秒，仅一个视频流，分辨率 320×180–3840×2160，帧率 `(0, 120]`。
- 规范输出为 MP4/H.264/`yuv420p`/不放大的最大 1280×720/恒定 30 fps/`faststart`；兼容音频输出 AAC 双声道 128 kbps。
- 上传地址 30 分钟过期；成功或失败后源文件保留 24 小时；`ready` 产物保留 7 天。
- possession token 只通过 `Authorization: Bearer` 发送，数据库只保存 `HMAC-SHA256` 摘要；token、摘要、PUUID、对象 Key、预签名 URL、本地路径和 FFmpeg 原始输出不得进入响应或日志。
- 未知 replay ID、缺少 token、错误 token 统一公开为 `404 REPLAY_NOT_FOUND`。
- UI 必须完整支持 `zh-CN` 和 `en-US`，必须明确显示“录像证据已准备，但尚未产生 AI 教练结论”。
- 本阶段禁止 OpenAI 调用、评分、错误标签、意识/操作/走位判断、OCR、Riot Timeline 和第三方 URL 下载。
- 所有实现遵循 TDD：先写失败测试，确认失败原因正确，再写最小实现；每个任务单独提交。
- 规格来源：`docs/superpowers/specs/2026-08-01-lol-ai-coach-replay-r1-design.md`。

## Execution Prerequisite

在 Cursor 中打开 `/Users/pf/lol-ai-coach/.worktrees/phase2-riot-integration`，然后运行：

```bash
git status --short --branch
git log -3 --oneline
git switch -c feature/replay-r1
```

预期基线包含 `a0d5c01` 及规格提交 `8f0fbcb`。如果已经在 `feature/replay-r1`，只核对状态后继续。若存在未知未提交修改，先停止并让用户确认归属。

本机当前没有 FFmpeg。单元测试先使用 fake runner；执行 Task 7 的真实集成测试前运行：

```bash
brew install ffmpeg
ffmpeg -version
ffprobe -version
```

## File Structure

后端新增或修改文件职责：

- `backend/app/services/replays/domain.py`：状态、错误码、时间映射、覆盖范围等无 I/O 领域逻辑。
- `backend/app/services/replays/security.py`：possession token 生成、HMAC 摘要和常量时间验证。
- `backend/app/models/replay.py`：`ReplayUploadRow`、`ReplayJobRow`、`ReplayArtifactRow`。
- `backend/app/repositories/replays.py`：回放状态、任务领取、产物幂等和清理查询。
- `backend/app/services/replays/storage/base.py`：存储协议和安全数据类型。
- `backend/app/services/replays/storage/local.py`：非公开本地目录的流式读写、Range 和删除。
- `backend/app/services/replays/storage/s3.py`：S3-compatible 预签名 PUT/GET、stat、下载、上传和删除。
- `backend/app/services/replays/media.py`：受控 `ffprobe`/`ffmpeg` 参数、探测解析、转码和抽帧。
- `backend/app/services/replays/service.py`：创建、授权、完成、查询、重试、删除的应用服务。
- `backend/app/services/replays/processor.py`：单个处理/清理任务的幂等编排。
- `backend/app/workers/replay.py`：Worker 主循环、信号处理、心跳和退避。
- `backend/app/schemas/replays.py`、`backend/app/api/replays.py`：公开 API 契约与路由。
- `backend/alembic/versions/0002_replay_r1.py`：三张表、约束、索引和降级。

前端新增或修改文件职责：

- `frontend/src/api/schemas.ts`：Replay JSON 的严格 Zod 契约。
- `frontend/src/api/client.ts`：Replay JSON 请求、XHR 上传和 bearer token。
- `frontend/src/replays/storage.ts`：允许字段白名单的 `localStorage` capability 存储。
- `frontend/src/components/replay-upload-form.tsx`：本地预览、`00:00` 锚点、授权和上传。
- `frontend/src/components/replay-status-panel.tsx`：轮询、阶段、失败、重试、保留期和删除。
- `frontend/src/components/replay-artifact-gallery.tsx`：验证帧与部分覆盖警告。
- `frontend/src/components/replay-section.tsx`：组合上述组件并恢复本地 capability。
- `frontend/src/components/match-detail-client.tsx`：在成功的比赛详情下挂载 Replay 区域。
- `frontend/src/i18n/en-US.ts`、`frontend/src/i18n/zh-CN.ts`：全部用户文案。

---

### Task 1: Replay 配置、领域状态、token 与时间映射

**Files:**
- Create: `backend/app/services/replays/__init__.py`
- Create: `backend/app/services/replays/domain.py`
- Create: `backend/app/services/replays/security.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/test_config.py`
- Test: `backend/tests/test_replay_domain.py`
- Test: `backend/tests/test_replay_security.py`

**Interfaces:**
- Produces: `ReplayStatus`、`ReplayJobStatus`、`ReplayJobKind`、`ReplayArtifactKind`、`ReplayCoverage`。
- Produces: `game_to_video_time(game_time_ms: int, game_time_zero_ms: int) -> int`。
- Produces: `video_to_game_time(video_time_ms: int, game_time_zero_ms: int) -> int`。
- Produces: `calculate_coverage(video_duration_ms: int, game_time_zero_ms: int, match_duration_ms: int) -> ReplayCoverage`。
- Produces: `issue_replay_token(secret: bytes) -> tuple[str, str]` 和 `verify_replay_token(secret: bytes, token: str, expected_digest: str) -> bool`。

- [ ] **Step 1: 写配置和领域逻辑的失败测试**

```python
def test_replay_settings_are_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.replay_enabled is False
    assert settings.replay_max_bytes == 4 * 1024**3
    assert settings.replay_min_duration_seconds == 600
    assert settings.replay_max_duration_seconds == 5400

def test_time_mapping_and_partial_coverage() -> None:
    assert game_to_video_time(60_000, 48_231) == 108_231
    assert video_to_game_time(108_231, 48_231) == 60_000
    assert calculate_coverage(1_000_000, 50_000, 1_800_000) == ReplayCoverage(
        start_ms=0, end_ms=950_000, partial=True
    )
```

- [ ] **Step 2: 运行测试并确认因缺少字段和函数而失败**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_config.py tests/test_replay_domain.py -v
```

Expected: FAIL，明确指向 replay 配置或领域符号尚不存在。

- [ ] **Step 3: 增加精确配置和枚举**

在 `Settings` 中增加：

```python
replay_enabled: bool = False
replay_storage_backend: Literal["local", "s3"] = "local"
replay_local_root: Path = ROOT_ENV_FILE.parent / "var" / "replays"
replay_token_secret: SecretStr = SecretStr("")
replay_max_bytes: int = 4 * 1024**3
replay_min_duration_seconds: int = 600
replay_max_duration_seconds: int = 5400
replay_upload_expiry_seconds: int = 1800
replay_source_retention_hours: int = 24
replay_derived_retention_days: int = 7
replay_worker_concurrency: int = 1
replay_ffmpeg_path: str = "ffmpeg"
replay_ffprobe_path: str = "ffprobe"
replay_process_timeout_seconds: int = 7200
replay_s3_endpoint_url: str = ""
replay_s3_region: str = ""
replay_s3_bucket: str = ""
replay_s3_access_key_id: SecretStr = SecretStr("")
replay_s3_secret_access_key: SecretStr = SecretStr("")
replay_s3_prefix: str = "replays"
replay_gateway_rate_limits_enforced: bool = False
```

`domain.py` 使用 `StrEnum` 定义规格中的状态；`ReplayJobKind` 固定为 `process/delete_source/delete_all`。`ReplayCoverage` 使用 `@dataclass(frozen=True)`，并拒绝负时间、锚点超出视频、`start_ms > end_ms`。Settings validator 必须在 Replay 启用时要求至少 32 字节 token secret；`APP_ENV=production` 还要求 `replay_gateway_rate_limits_enforced=true`，否则拒绝启动公开 Replay。

- [ ] **Step 4: 写 token 失败测试**

```python
def test_token_is_returned_once_as_plaintext_and_verified_by_digest() -> None:
    token, digest = issue_replay_token(b"x" * 32)
    assert token != digest
    assert len(bytes.fromhex(digest)) == 32
    assert verify_replay_token(b"x" * 32, token, digest)
    assert not verify_replay_token(b"x" * 32, token + "x", digest)
```

- [ ] **Step 5: 实现 token 工具**

核心实现必须等价于：

```python
def issue_replay_token(secret: bytes) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _digest(secret, token)

def verify_replay_token(secret: bytes, token: str, expected_digest: str) -> bool:
    return hmac.compare_digest(_digest(secret, token), expected_digest)

def _digest(secret: bytes, token: str) -> str:
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()
```

- [ ] **Step 6: 运行任务测试和静态检查**

```bash
cd backend && .venv/bin/pytest tests/test_config.py tests/test_replay_domain.py tests/test_replay_security.py -v
cd backend && .venv/bin/ruff check app/services/replays app/core/config.py tests/test_replay_domain.py tests/test_replay_security.py
cd backend && .venv/bin/mypy
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add backend/app/core/config.py backend/app/services/replays backend/tests/test_config.py backend/tests/test_replay_domain.py backend/tests/test_replay_security.py
git commit -m "feat: define replay domain and capability security"
```

### Task 2: PostgreSQL 迁移与 ORM 模型

**Files:**
- Create: `backend/alembic/versions/0002_replay_r1.py`
- Create: `backend/app/models/replay.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Modify: `backend/tests/integration/conftest.py`
- Test: `backend/tests/test_replay_models.py`

**Interfaces:**
- Consumes: Task 1 的状态字符串。
- Produces: `ReplayUploadRow`、`ReplayJobRow`、`ReplayArtifactRow`。
- Produces constraints: `uq_replay_active_job` 和 `uq_replay_artifact_timestamp`。

- [ ] **Step 1: 扩展迁移失败测试**

```python
assert {"replay_uploads", "replay_jobs", "replay_artifacts"}.issubset(tables)
assert "selected_puuid" in replay_upload_columns
assert "token_digest" in replay_upload_columns
```

再增加一次 `upgrade head -> downgrade 0001_phase_2_riot_cache -> upgrade head` 往返测试，确认三张 Replay 表可移除并重建，原三张 Riot 缓存表仍存在。

- [ ] **Step 2: 运行迁移测试并确认失败**

```bash
TEST_DATABASE_URL="$TEST_DATABASE_URL" make verify-postgres
```

Expected: FAIL，因为三张 Replay 表尚不存在。

- [ ] **Step 3: 创建迁移和模型**

迁移必须创建：

```text
replay_uploads(id UUID PK, match_id, platform, selected_puuid, match_duration_ms,
status, processing_stage, progress_percent, token_digest, original_filename,
declared_content_type, declared_size_bytes, actual_container, actual_size_bytes,
source_sha256, source_duration_ms, normalized_duration_ms, width, height,
frame_rate_numerator, frame_rate_denominator, game_time_zero_ms,
available_game_time_start_ms, available_game_time_end_ms, source_object_key,
normalized_object_key, rights_statement_version, rights_attested_at,
upload_expires_at, source_delete_after, derived_delete_after, warning_codes JSONB,
error_code, error_retryable, created_at, updated_at, processing_started_at,
processing_finished_at, deleted_at, version)

replay_jobs(id UUID PK, replay_id UUID FK ON DELETE CASCADE, kind, status,
attempt_count, max_attempts, available_at, claimed_at, heartbeat_at, finished_at,
worker_id, last_error_code, created_at, updated_at)

replay_artifacts(id UUID PK, replay_id UUID FK ON DELETE CASCADE, kind,
game_time_ms, video_time_ms, object_key, sha256, media_type, size_bytes,
width, height, duration_ms, created_at, delete_after)
```

约束必须包含 `progress_percent BETWEEN 0 AND 100`、非负时间/大小、同一回放同一产物类型和时间戳唯一，以及仅 `pending/running/retry_scheduled` 状态参与的 active-job 部分唯一索引。为支持 tombstone，`selected_puuid/token_digest/original_filename/declared_content_type` 在物理列上允许 null，但增加状态相关 CHECK：非 `deleted` 记录必须非 null；ORM 也将这些字段标为 `str | None`，服务创建活动记录时仍强制提供。

- [ ] **Step 4: 写并运行 ORM 默认值测试**

```python
def test_replay_model_maps_security_sensitive_fields_explicitly() -> None:
    row = ReplayUploadRow(
        match_id="NA1_1", platform="NA1", selected_puuid="private",
        match_duration_ms=1_800_000, token_digest="a" * 64,
        original_filename="owned.mp4", declared_content_type="video/mp4",
        declared_size_bytes=100, game_time_zero_ms=1_000,
        rights_statement_version="2026-08-01",
        rights_attested_at=datetime.now(UTC), upload_expires_at=datetime.now(UTC),
        status=ReplayStatus.CREATED.value, progress_percent=0, warning_codes=[], version=1,
    )
    assert row.status == ReplayStatus.CREATED.value
    assert row.progress_percent == 0
```

- [ ] **Step 5: 运行迁移、模型、格式和类型检查**

先把 integration fixture 的清理语句改为：

```sql
TRUNCATE TABLE replay_artifacts, replay_jobs, replay_uploads,
matches, recent_match_caches, players CASCADE
```

然后运行：

```bash
cd backend && .venv/bin/pytest tests/test_replay_models.py -v
TEST_DATABASE_URL="$TEST_DATABASE_URL" make verify-postgres
cd backend && .venv/bin/ruff check app/models/replay.py alembic/versions/0002_replay_r1.py
cd backend && .venv/bin/mypy
```

- [ ] **Step 6: 提交**

```bash
git add backend/alembic/versions/0002_replay_r1.py backend/app/models backend/tests/test_replay_models.py backend/tests/integration/test_migrations.py backend/tests/integration/conftest.py
git commit -m "feat: add replay persistence schema"
```

### Task 3: Repository、状态转换与 PostgreSQL 任务队列

**Files:**
- Create: `backend/app/repositories/replays.py`
- Modify: `backend/app/repositories/matches.py`
- Test: `backend/tests/test_replay_repository_contract.py`
- Modify: `backend/tests/integration/test_repositories.py`

**Interfaces:**
- Produces: `ReplayRepository.create/get/transition/scrub_deleted`。
- Produces: `ReplayJobRepository.enqueue/claim_next/heartbeat/succeed/fail/recover_stale/enqueue_due_retention`。
- Produces: `ReplayArtifactRepository.upsert/list_for_replay/delete_rows`。
- Produces: `MatchRepository.get_for_replay_binding(platform: Platform, match_id: str) -> MatchSnapshot | None`，不受 Riot 缓存 TTL 影响。

- [ ] **Step 1: 写 repository protocol 和状态转换失败测试**

```python
@pytest.mark.asyncio
async def test_transition_requires_expected_version(repository, created_replay) -> None:
    updated = await repository.transition(
        replay_id=created_replay.id,
        expected_statuses={ReplayStatus.CREATED},
        expected_version=1,
        status=ReplayStatus.UPLOADED,
        values={},
    )
    assert updated.version == 2
    with pytest.raises(ReplayStateConflict):
        await repository.transition(
            replay_id=created_replay.id,
            expected_statuses={ReplayStatus.CREATED},
            expected_version=1,
            status=ReplayStatus.UPLOADED,
            values={},
        )
```

- [ ] **Step 2: 写 PostgreSQL 并发领取失败测试**

并行运行两个 `claim_next()`；插入两个 pending jobs 时，两名 worker 必须得到不同 job。只插入一个 job 时，第二名 worker 得到 `None`。重复 `enqueue()` 必须由部分唯一索引阻止第二个 active job。

- [ ] **Step 3: 运行测试并确认 repository 尚不存在**

```bash
cd backend && .venv/bin/pytest tests/test_replay_repository_contract.py -v
cd backend && TEST_DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/pytest tests/integration/test_repositories.py -m integration -v
```

- [ ] **Step 4: 实现短事务任务领取**

SQLAlchemy 语义必须等价于：

```python
statement = (
    select(ReplayJobRow)
    .where(
        ReplayJobRow.status.in_(["pending", "retry_scheduled"]),
        ReplayJobRow.available_at <= now,
    )
    .order_by(ReplayJobRow.available_at, ReplayJobRow.created_at)
    .with_for_update(skip_locked=True)
    .limit(1)
)
```

领取事务只更新 `status="running"`、`claimed_at`、`heartbeat_at`、`worker_id` 和 `attempt_count + 1`，随后立即提交；不得在事务中运行媒体处理。

- [ ] **Step 5: 实现幂等产物和 stale job 恢复**

`upsert()` 使用 `(replay_id, kind, game_time_ms, video_time_ms)` 唯一键；相同哈希返回现有记录，不同哈希抛出 `ReplayArtifactConflict`。`recover_stale()` 只把心跳早于阈值的 running job 改为 `retry_scheduled`，清除 worker 字段并设置新的 `available_at`。

`enqueue_due_retention(now)` 在一个事务中锁定到期记录并幂等创建任务：到达 `source_delete_after` 时创建 `delete_source`；到达 `derived_delete_after`、用户删除、上传过期或失败记录满七天时创建 `delete_all`；`deleted_at` 满七天的 tombstone 直接硬删除。测试必须证明重复调度不会产生第二个 active cleanup job。

- [ ] **Step 6: 实现删除脱敏**

`scrub_deleted()` 必须在对象清理成功后清空：`selected_puuid`、`token_digest`、`original_filename`、`declared_content_type`、两个 object key、校验和和媒体尺寸；保留 replay ID、`deleted` 状态和 `deleted_at` 七天。

- [ ] **Step 7: 运行定向与 PostgreSQL 测试**

```bash
cd backend && .venv/bin/pytest tests/test_replay_repository_contract.py -v
TEST_DATABASE_URL="$TEST_DATABASE_URL" make verify-postgres
```

- [ ] **Step 8: 提交**

```bash
git add backend/app/repositories/replays.py backend/app/repositories/matches.py backend/tests/test_replay_repository_contract.py backend/tests/integration/test_repositories.py
git commit -m "feat: add replay repositories and job queue"
```

### Task 4: 存储协议与本地流式存储

**Files:**
- Create: `backend/app/services/replays/storage/__init__.py`
- Create: `backend/app/services/replays/storage/base.py`
- Create: `backend/app/services/replays/storage/local.py`
- Test: `backend/tests/test_replay_local_storage.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `StoredObject(key: str, size_bytes: int, sha256: str | None)`。
- Produces: `UploadTarget(method: str, url: str, headers: Mapping[str, str], expires_at: datetime)`。
- Produces protocol methods `create_upload_target`、`write_stream`、`stat`、`download_to_path`、`upload_from_path`、`iter_range`、`delete`。

- [ ] **Step 1: 写路径逃逸、大小限制和部分文件清理测试**

```python
@pytest.mark.asyncio
async def test_local_storage_never_uses_user_filename(tmp_path: Path) -> None:
    storage = LocalReplayStorage(tmp_path)
    result = await storage.write_stream(
        key="source/abc/input", chunks=aiter([b"video"]), max_bytes=10
    )
    assert result.size_bytes == 5
    assert ".." not in result.key
    assert not list(tmp_path.rglob("owned recording.mp4"))

@pytest.mark.asyncio
async def test_oversized_stream_removes_partial_file(tmp_path: Path) -> None:
    storage = LocalReplayStorage(tmp_path)
    with pytest.raises(ReplayObjectTooLarge):
        await storage.write_stream("source/abc/input", aiter([b"123", b"456"]), 5)
    assert not list(tmp_path.rglob("*.part"))
```

- [ ] **Step 2: 运行测试并确认失败**

```bash
cd backend && .venv/bin/pytest tests/test_replay_local_storage.py -v
```

- [ ] **Step 3: 实现严格 object-key 校验和原子写入**

object key 仅接受 `^[a-z0-9][a-z0-9/_-]{0,255}$`，拒绝空段、`.`、`..` 和绝对路径。本地写入目标是 `<root>/<key>.part`，写完后以原子 rename 提升为 `<root>/<key>`；异常和取消都删除 `.part`。

- [ ] **Step 4: 实现 Range 与安全删除**

`iter_range(key, start, end)` 验证 `0 <= start <= end < size`，按 1 MiB 块迭代；`delete()` 仅删除已解析且确认位于 `REPLAY_LOCAL_ROOT` 内的文件，缺失文件视为成功。不得把 root 注册成 FastAPI 静态目录。

- [ ] **Step 5: 忽略所有本地媒体**

在 `.gitignore` 加入：

```gitignore
var/replays/
*.replay-upload.part
```

- [ ] **Step 6: 运行测试、类型和格式检查**

```bash
cd backend && .venv/bin/pytest tests/test_replay_local_storage.py -v
cd backend && .venv/bin/ruff check app/services/replays/storage tests/test_replay_local_storage.py
cd backend && .venv/bin/mypy
git check-ignore var/replays/example.mp4
```

- [ ] **Step 7: 提交**

```bash
git add .gitignore backend/app/services/replays/storage backend/tests/test_replay_local_storage.py
git commit -m "feat: add safe local replay storage"
```

### Task 5: Replay 应用服务、API schema 和 token 授权

**Files:**
- Create: `backend/app/schemas/replays.py`
- Create: `backend/app/services/replays/service.py`
- Modify: `backend/app/core/dependencies.py`
- Test: `backend/tests/test_replay_service.py`
- Test: `backend/tests/test_replay_schemas.py`

**Interfaces:**
- Produces: `ReplayCreateRequest`、`ReplayCreateResponse`、`ReplayStatusResponse`、`ReplayArtifactResponse`。
- Produces: `ReplayService.create/authorize/mark_local_uploaded/complete/get_status/list_artifacts/retry/request_delete`。
- Consumes: Tasks 1–4 的安全、领域、repository、match binding 和 storage 接口。

- [ ] **Step 1: 写创建绑定与授权失败测试**

测试必须覆盖：比赛不存在、PUUID 不属于比赛、`rights_attested=false`、未知 statement version、声明大小超过 4 GiB、错误扩展名、Replay 未启用，以及成功时只在响应中返回一次明文 token。

成功断言至少包括：

```python
created = await service.create(valid_request, now=now)
assert created.status == ReplayStatus.CREATED
assert created.access_token
stored = await repository.get(created.replay_id)
assert stored.token_digest != created.access_token
assert stored.match_duration_ms == 1_800_000
```

- [ ] **Step 2: 写授权不可枚举测试**

```python
@pytest.mark.parametrize("replay_id,token", [(uuid4(), "valid"), (known_id, "wrong")])
async def test_missing_and_wrong_token_have_same_public_error(replay_id, token) -> None:
    with pytest.raises(ApiError) as raised:
        await service.get_status(replay_id, token)
    assert raised.value.status_code == 404
    assert raised.value.code == "REPLAY_NOT_FOUND"
```

- [ ] **Step 3: 运行并确认测试失败**

```bash
cd backend && .venv/bin/pytest tests/test_replay_service.py tests/test_replay_schemas.py -v
```

- [ ] **Step 4: 实现严格公开 schema**

`ReplayStatusResponse` 只允许：`replay_id/status/processing_stage/progress_percent/normalized_duration_ms/width/height/available_game_time_start_ms/available_game_time_end_ms/warning_codes/error_code/error_retryable/source_delete_after/derived_delete_after/request_id`。`ReplayArtifactResponse` 只返回 ID、kind、两个时间戳、媒体类型、尺寸、大小和 `{mode,url,expires_at}` access 对象。不要定义 PUUID、token digest、filename 或 object key 字段。

- [ ] **Step 5: 实现服务状态规则**

`complete()` 的顺序固定为：验证 token → 验证未过期 → `storage.stat()` → 校验实际大小。S3 的 `created` 在 stat 成功后转 `uploaded`；本地 PUT 已经处于 `uploaded`。随后在数据库事务中 enqueue 并转 `queued`。重复调用从 `uploaded/queued/processing/ready` 返回当前状态，不创建新 job。

`retry()` 只接受 `failed + error_retryable=true + source_delete_after > now + source object exists`；`request_delete()` 先转 `deleting` 使 API 不再提供内容，再 enqueue cleanup。

- [ ] **Step 6: 注入服务但保持测试可替换**

扩展 `AppServices`：

```python
@dataclass(frozen=True)
class AppServices:
    player_service: PlayerResolver
    match_service: MatchResolver
    replay_service: ReplayServiceProtocol
    closers: tuple[AsyncCloser, ...]
```

同步更新全部现有 fake fixtures，使用拒绝意外调用的 `FakeReplayService`，防止健康检查或 Riot API 测试无意访问 Replay。

- [ ] **Step 7: 运行定向测试和现有后端测试**

```bash
cd backend && .venv/bin/pytest tests/test_replay_service.py tests/test_replay_schemas.py -v
cd backend && .venv/bin/pytest -m "not integration" -v
cd backend && .venv/bin/mypy
```

- [ ] **Step 8: 提交**

```bash
git add backend/app/schemas/replays.py backend/app/services/replays/service.py backend/app/core/dependencies.py backend/tests
git commit -m "feat: add replay application service"
```

### Task 6: Replay HTTP API、本地上传、Range、重试与删除

**Files:**
- Create: `backend/app/api/replays.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/core/errors.py`
- Test: `backend/tests/test_replay_api.py`
- Test: `backend/tests/test_replay_runtime_privacy.py`

**Interfaces:**
- Produces规格中的七类路由：create、local content PUT、complete、status、artifact manifest/content、retry、delete。
- Consumes: `ReplayServiceProtocol` 和 `ReplayStorage`。

- [ ] **Step 1: 写 API 契约失败测试**

使用 FakeReplayService 覆盖：

```python
response = replay_client.post("/api/v1/replays", json=valid_payload)
assert response.status_code == 201
assert response.json()["access_token"] == "returned-once"
assert response.json()["request_id"] == response.headers["X-Request-ID"]

hidden = replay_client.get(
    f"/api/v1/replays/{replay_id}", headers={"Authorization": "Bearer wrong"}
)
assert hidden.status_code == 404
assert hidden.json()["error"]["code"] == "REPLAY_NOT_FOUND"
```

再覆盖重复 complete、非法 bearer 格式、PUT 超限、Range `206`/`416`、retry、delete 幂等和所有响应隐私字段。

- [ ] **Step 2: 运行测试并确认 404 或路由缺失**

```bash
cd backend && .venv/bin/pytest tests/test_replay_api.py tests/test_replay_runtime_privacy.py -v
```

- [ ] **Step 3: 实现路由和 bearer 解析**

路由前缀固定为 `/api/v1/replays`。使用一个私有 dependency 解析 `Authorization`；任何缺失、非 `Bearer`、空 token 或 token 过长都调用同一 `REPLAY_NOT_FOUND` 工厂。不要把 token 放进 dependency 参数日志。

- [ ] **Step 4: 实现本地 PUT 流式上传**

使用 `request.stream()` 直接传给 `LocalReplayStorage.write_stream()`；先检查 `Content-Length`，但即使缺失或伪造也必须在流式写入中再次限制。成功后调用 `mark_local_uploaded()`，返回 `204`。

- [ ] **Step 5: 实现受保护的 Range 内容响应**

只允许 status 为 `ready` 的产物。解析单一 `Range: bytes=start-end`，合法范围返回 `206`、`Accept-Ranges: bytes` 和正确 `Content-Range`；多段 Range 或越界返回 `416`。内容类型取数据库中已验证值，不取请求参数；`Content-Disposition` 只使用生成的 artifact UUID 文件名。源录像没有任何下载路由。

- [ ] **Step 6: 更新 CORS**

在 `create_app()` 中设置：

```python
allow_methods=["GET", "POST", "PUT", "DELETE"]
allow_headers=["Accept", "Authorization", "Content-Type", "Range"]
expose_headers=["Accept-Ranges", "Content-Length", "Content-Range", "X-Request-ID"]
```

- [ ] **Step 7: 运行 API、隐私、CORS 和全后端测试**

```bash
cd backend && .venv/bin/pytest tests/test_replay_api.py tests/test_replay_runtime_privacy.py tests/test_errors.py -v
cd backend && .venv/bin/pytest -m "not integration" -v
```

- [ ] **Step 8: 提交**

```bash
git add backend/app/api/replays.py backend/app/main.py backend/app/core/errors.py backend/tests/test_replay_api.py backend/tests/test_replay_runtime_privacy.py
git commit -m "feat: expose authorized replay API"
```

### Task 7: FFprobe、FFmpeg 和真实媒体集成测试

**Files:**
- Create: `backend/app/services/replays/media.py`
- Test: `backend/tests/test_replay_media.py`
- Test: `backend/tests/integration/test_replay_ffmpeg.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `MediaProbe`、`VideoStreamProbe`、`AudioStreamProbe`。
- Produces: `ReplayMediaRunner.probe(input_path)`、`normalize(input_path, output_path, probe, progress)`、`extract_frame(input_path, video_time_ms, output_path)`。
- Produces: `validate_probe(probe, limits) -> ValidatedMedia`。

- [ ] **Step 1: 注册 marker 并写命令构造失败测试**

在 pytest 配置增加：

```toml
"replay_ffmpeg: requires ffmpeg and ffprobe binaries",
```

测试必须断言命令是 list，第一项来自配置路径，且没有 `shell=True`：

```python
assert command[:4] == ["ffprobe", "-v", "error", "-print_format"]
assert "-show_streams" in command
assert "-show_format" in command
assert "libx264" in normalize_command
assert "yuv420p" in normalize_command
assert "+faststart" in normalize_command
```

- [ ] **Step 2: 写验证边界失败测试**

参数化覆盖 599/600/5400/5401 秒、0/1/2 个视频流、319×180、3840×2160、121 fps、subtitle/data stream、非有限 duration、无音频和多音频。

- [ ] **Step 3: 运行 fake runner 测试并确认失败**

```bash
cd backend && .venv/bin/pytest tests/test_replay_media.py -v
```

- [ ] **Step 4: 实现受控子进程**

只使用：

```python
process = await asyncio.create_subprocess_exec(
    *args,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
```

限制捕获输出长度；超时先 terminate，短暂等待后 kill。公开异常只包含稳定错误码。原始 stderr 只进入受保护、截断且去路径的诊断对象，不进入普通结构化日志。

- [ ] **Step 5: 实现规范化命令**

参数至少包括：

```text
-map 0:v:0 -map 0:a:0? -c:v libx264 -pix_fmt yuv420p
-vf scale(不放大且最大1280x720),fps=30,setpts=PTS-STARTPTS
-fps_mode cfr -movflags +faststart
-c:a aac -ac 2 -b:a 128k -af asetpts=PTS-STARTPTS
```

加入 `-progress pipe:1 -nostats`，只解析 `out_time_ms` 更新 15–80 的阶段进度。输出先写 scratch 临时路径，完成后再次 probe 验证 H.264、MP4、`yuv420p`、30 fps、尺寸和时长容差。

- [ ] **Step 6: 实现确定性抽帧**

使用输入定位到 `video_time_ms / 1000`，输出单张 JPEG，最大 1280×720；输出参数必须包含 `-frames:v 1`、`-map_metadata -1`。同一输入和时间重复调用产生可接受的固定元数据和内容哈希。

- [ ] **Step 7: 写真实 FFmpeg 集成测试**

测试运行时用 lavfi 生成 12 秒、640×360、30 fps 的测试视频和正弦音频，不保存 fixture；然后以测试专用 `MediaLimits(min_duration_seconds=1, max_duration_seconds=30)` 完成 probe、validate、normalize，抽取 0/5/11 秒帧并验证。生产默认 600–5400 秒不得因测试而改变。使用：

```python
pytestmark = pytest.mark.replay_ffmpeg
if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
    pytest.skip("ffmpeg and ffprobe are not installed", allow_module_level=True)
```

只在 `shutil.which()` 缺失时跳过。

- [ ] **Step 8: 运行 fake 和真实媒体测试**

```bash
cd backend && .venv/bin/pytest tests/test_replay_media.py -v
cd backend && .venv/bin/pytest tests/integration/test_replay_ffmpeg.py -m replay_ffmpeg -v
```

- [ ] **Step 9: 提交**

```bash
git add backend/app/services/replays/media.py backend/tests/test_replay_media.py backend/tests/integration/test_replay_ffmpeg.py backend/pyproject.toml
git commit -m "feat: normalize replay media with ffmpeg"
```

### Task 8: S3-compatible 存储适配器

**Files:**
- Create: `backend/app/services/replays/storage/s3.py`
- Create: `backend/app/services/replays/storage/factory.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_replay_s3_storage.py`
- Modify: `backend/tests/test_config.py`

**Interfaces:**
- Implements Task 4 的 `ReplayStorage` protocol。
- Produces: `build_replay_storage(settings: Settings) -> ReplayStorage`。

- [ ] **Step 1: 添加明确依赖**

运行：

```bash
cd backend && .venv/bin/pip install "boto3>=1.40,<2.0" "boto3-stubs[s3]>=1.40,<2.0"
```

把 `boto3` 放入正式依赖，把 `boto3-stubs[s3]` 放入 dev 依赖；不要依赖本机全局包。

- [ ] **Step 2: 写 Stubber 失败测试**

使用 botocore `Stubber` 覆盖：presigned PUT 30 分钟、presigned GET 5 分钟、`head_object` 大小、download/upload、删除缺失对象幂等、非本 bucket key 拒绝，以及响应中永不返回对象 Key。

- [ ] **Step 3: 运行测试并确认失败**

```bash
cd backend && .venv/bin/pytest tests/test_replay_s3_storage.py -v
```

- [ ] **Step 4: 实现 S3 适配器**

所有 key 都以配置的私有前缀开头；bucket 禁止 public ACL。预签名 PUT 固定目标 key 和最大允许期限，完成时仍调用 `head_object` 校验大小。同步 boto3 调用使用 `asyncio.to_thread()`，不得阻塞事件循环。

- [ ] **Step 5: 实现 fail-closed factory**

`replay_enabled=false` 时不得初始化 S3 客户端。`local` 要求可创建且不位于仓库静态目录；`s3` 要求 endpoint/region/bucket/credentials 非空。未知 backend 由 Pydantic 拒绝。

- [ ] **Step 6: 运行测试和类型检查**

```bash
cd backend && .venv/bin/pytest tests/test_replay_s3_storage.py tests/test_config.py -v
cd backend && .venv/bin/mypy
```

- [ ] **Step 7: 提交**

```bash
git add backend/app/services/replays/storage backend/pyproject.toml backend/tests/test_replay_s3_storage.py backend/tests/test_config.py
git commit -m "feat: add s3-compatible replay storage"
```

### Task 9: 幂等 Worker、处理流水线和保留清理

**Files:**
- Create: `backend/app/services/replays/processor.py`
- Create: `backend/app/workers/__init__.py`
- Create: `backend/app/workers/replay.py`
- Test: `backend/tests/test_replay_processor.py`
- Test: `backend/tests/test_replay_worker.py`
- Modify: `backend/app/core/dependencies.py`

**Interfaces:**
- Produces: `ReplayProcessor.process(job)`、`ReplayProcessor.delete_source(job)` 和 `ReplayProcessor.delete_all(job)`。
- Produces: `run_worker(settings: Settings, stop_event: asyncio.Event) -> None`。
- Consumes: repositories、storage、media runner、Task 1 时间映射。

- [ ] **Step 1: 写正常流水线失败测试**

Fake storage/media/repositories 记录调用顺序，断言：

```text
download source -> hash -> probe -> probing state -> normalize -> transcode state
-> probe normalized -> upload normalized -> extracting state -> frames
-> artifact upserts -> ready(100) -> retention deadlines
```

必须生成 game time 0 和每 30 秒一帧，末尾不足 30 秒补一帧，总数不超过 181。

- [ ] **Step 2: 写重启幂等、部分覆盖和错误分类测试**

覆盖：规范文件已存在且哈希一致时跳过转码；已有同哈希 frame 时复用；转码中断后清理临时文件；短覆盖写入 `partial_coverage`；非法媒体不可重试；临时存储失败可重试；第三次失败后终止；用户在处理中删除时，processor 在下一个阶段边界发现 `deleting`、停止提升产物并把处理 job 标记为 `cancelled`。

- [ ] **Step 3: 写 Worker 领取、心跳和停止测试**

使用短 poll interval，断言没有 job 时退避；领取后每 15 秒心跳；SIGTERM/stop event 停止领取新任务并等待当前安全点；stale job 启动时恢复。

- [ ] **Step 4: 运行测试并确认失败**

```bash
cd backend && .venv/bin/pytest tests/test_replay_processor.py tests/test_replay_worker.py -v
```

- [ ] **Step 5: 实现处理流水线**

Worker 为每个 job 创建独立 `tempfile.TemporaryDirectory()`；仅把随机 scratch 路径传给 FFmpeg。每个阶段完成后写状态和进度。准备 `ready` 前必须确认规范视频和全部 artifact rows 已持久化。

- [ ] **Step 6: 实现源文件清理和完整清理**

`delete_source` 只删除 source 和遗留 `.part`，随后清空 `source_object_key/source_sha256/actual_size_bytes`，不得删除 normalized 或 frames。`delete_all` 的顺序为：确认内容不可访问 → 删除 source/normalized/artifact/temp 对象 → 删除 artifact rows → 调用 `scrub_deleted()`。对象缺失成功；存储暂时失败按 job 重试；绝不能因为一项缺失跳过其他对象。

- [ ] **Step 7: 实现 Worker 入口**

`python -m app.workers.replay` 必须：加载 Settings、验证 Replay 启用与 FFmpeg/storage、创建独立 Database/Repositories、启动 concurrency 个消费者、注册 SIGINT/SIGTERM、退出时关闭数据库和客户端。调度协程每 60 秒调用 `enqueue_due_retention()`，因此源文件 24 小时、产物 7 天、过期上传和七天 tombstone 都会真正处理。

CLI 同时支持 `python -m app.workers.replay --check`：只验证数据库、storage、scratch、ffmpeg 和 ffprobe 后退出 0，不领取任务，供容器 readiness 使用。

- [ ] **Step 8: 运行任务测试和全后端单元测试**

```bash
cd backend && .venv/bin/pytest tests/test_replay_processor.py tests/test_replay_worker.py -v
cd backend && .venv/bin/pytest -m "not integration and not replay_ffmpeg" -v
```

- [ ] **Step 9: 提交**

```bash
git add backend/app/services/replays/processor.py backend/app/workers backend/app/core/dependencies.py backend/tests/test_replay_processor.py backend/tests/test_replay_worker.py
git commit -m "feat: process replay jobs asynchronously"
```

### Task 10: 前端 Replay API、严格 schema 和本地 capability

**Files:**
- Modify: `frontend/src/api/schemas.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/replays/storage.ts`
- Test: `frontend/tests/replay-api-client.test.ts`
- Test: `frontend/tests/replay-storage.test.ts`

**Interfaces:**
- Produces: `createReplay`、`uploadReplayContent`、`completeReplay`、`getReplayStatus`、`getReplayArtifacts`、`getReplayArtifactBlob`、`retryReplay`、`deleteReplay`。
- Produces: `saveReplayCapability/loadReplayCapability/removeReplayCapability`。

- [ ] **Step 1: 写严格 Zod schema 失败测试**

覆盖 create/status/artifact manifest，额外字段必须失败；`request_id` 继续走现有安全转换。Artifact access 明确定义为 `{ mode: "bearer" | "presigned", url: string, expires_at: string }`。明确断言以下字段不在公开类型中：`selected_puuid`、`token_digest`、`object_key`、`original_filename`。

- [ ] **Step 2: 写 JSON bearer 请求和 XHR 上传失败测试**

```typescript
expect(fetchMock).toHaveBeenCalledWith(
  expect.stringContaining(`/api/v1/replays/${replayId}/complete`),
  expect.objectContaining({
    method: "POST",
    headers: expect.objectContaining({ Authorization: `Bearer ${token}` }),
  }),
);
```

XHR 测试触发 `upload.onprogress({ loaded: 50, total: 100 })`，断言回调收到 50；abort signal 必须调用 `xhr.abort()` 并抛出 `AbortError`。`getReplayArtifactBlob()` 必须以 bearer header 获取本地 artifact，并拒绝非 `image/jpeg` 的 frame 响应。

- [ ] **Step 3: 写 localStorage 白名单失败测试**

保存后 JSON 只能包含 `replayId/accessToken/matchId/updatedAt`。传入包含 `puuid/fileName/uploadUrl` 的对象时，这些字段不得落盘。损坏、过期或 schema 不符的 JSON 返回 `null` 并删除。

- [ ] **Step 4: 运行测试并确认失败**

```bash
cd frontend && pnpm test -- replay-api-client.test.ts replay-storage.test.ts
```

- [ ] **Step 5: 扩展通用请求函数**

保持现有 GET 行为不变，加入 `method/body/token` 参数；错误仍统一解析 `errorResponseSchema`。token 只能作为 header 值，任何错误对象、调试文本或 URL 都不含 token。

- [ ] **Step 6: 实现 XHR 和 capability 存储**

本地 adapter 返回 `/api/v1/replays/{id}/content` 相对 URL，S3 adapter 返回绝对预签名 URL。XHR 使用 `new URL(upload.url, apiBaseUrl).toString()`；只有 `upload.url.startsWith("/")` 才添加 bearer token，S3 只使用返回的 `upload.headers`。上传成功仅接受 2xx。Artifact 的 `access.mode="bearer"` 使用带 Authorization 的 fetch 转为 Blob；`presigned` 才能直接交给浏览器。每个 replay 使用固定前缀 key，例如 `lol-ai-coach:replay:<replayId>`。

- [ ] **Step 7: 运行测试、lint 和类型检查**

```bash
cd frontend && pnpm test -- replay-api-client.test.ts replay-storage.test.ts api-client.test.ts
cd frontend && pnpm lint
cd frontend && pnpm typecheck
```

- [ ] **Step 8: 提交**

```bash
git add frontend/src/api frontend/src/replays frontend/tests/replay-api-client.test.ts frontend/tests/replay-storage.test.ts
git commit -m "feat: add replay browser client"
```

### Task 11: 双语上传、锚点选择、状态、产物和删除 UI

**Files:**
- Create: `frontend/src/components/replay-upload-form.tsx`
- Create: `frontend/src/components/replay-status-panel.tsx`
- Create: `frontend/src/components/replay-artifact-gallery.tsx`
- Create: `frontend/src/components/replay-section.tsx`
- Modify: `frontend/src/components/match-detail-client.tsx`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/src/app/globals.css`
- Test: `frontend/tests/replay-section.test.tsx`
- Modify: `frontend/tests/match-detail-page.test.tsx`
- Modify: `frontend/tests/i18n.test.ts`

**Interfaces:**
- Consumes Task 10 的 API 和 capability 函数。
- Produces: `ReplaySection({ matchId, puuid, platform, locale, matchDurationSeconds })`。

- [ ] **Step 1: 写本地选择和授权失败测试**

测试上传按钮初始禁用；选择合法 `File` 后出现 `<video>` 本地预览；未点击锚点或未勾选授权仍禁用。模拟 `video.currentTime = 48.231` 后点击“Set as game 00:00”，创建请求必须发送 `game_time_zero_ms: 48231`。

- [ ] **Step 2: 写上传、轮询和刷新恢复失败测试**

模拟 create → XHR progress → complete → queued → processing → ready；断言 progressbar 和 stage 文本正确。预先写入 capability 后重新 render，必须直接调用 status 而不重复创建或读取视频文件。

- [ ] **Step 3: 写状态与删除失败测试**

覆盖：`partial_coverage`、retryable failed 显示重试、terminal failed 不显示重试、expired 清 capability、delete 确认后调用 API 并清 capability、错误 token 统一显示“回放不存在或访问已失效”。

- [ ] **Step 4: 写无障碍和双语失败测试**

断言授权 checkbox 默认未选、label 可点击、阶段更新在 polite live region、错误为 alert、进度有 `aria-valuenow`、缩略图 alt 包含格式化游戏时间、中英文 key 完整，并始终显示无 AI 结论提示。

- [ ] **Step 5: 运行测试并确认失败**

```bash
cd frontend && pnpm test -- replay-section.test.tsx match-detail-page.test.tsx i18n.test.ts
```

- [ ] **Step 6: 实现上传表单**

使用 `URL.createObjectURL(file)`，更换文件和 unmount 时必须 `URL.revokeObjectURL()`。前端只做后缀、声明 MIME 和 4 GiB 早期提示；最终校验由后端完成。发送固定 `rights_statement_version: "2026-08-01"`。

- [ ] **Step 7: 实现轮询与页面可见性退避**

活动状态每 2 秒轮询；`document.hidden=true` 时改为 10 秒；`ready/failed/deleted/expired` 停止。每个 effect 使用 AbortController，切换 match 或卸载后旧响应不得覆盖新状态。

- [ ] **Step 8: 实现产物与安全下载**

artifact gallery 按 `game_time_ms` 排序。`access.mode="bearer"` 时调用 `getReplayArtifactBlob()` 并用 `URL.createObjectURL(blob)` 展示，替换或卸载时 revoke；`presigned` 才直接作为 `src`。图片 URL 仅在内存中使用，不写入 localStorage。S3 URL 过期导致加载失败时刷新 manifest，不在错误文本显示 URL。验证帧标签只能是“验证帧 / Verification frame”。

- [ ] **Step 9: 接入比赛详情并完成响应式样式**

只在 match detail 成功且所选玩家存在时渲染：

```tsx
<ReplaySection
  locale={locale}
  matchId={data.match_id}
  puuid={data.selected_puuid}
  platform={data.platform}
  matchDurationSeconds={data.duration_seconds}
/>
```

窄屏不得产生页面横向滚动；缩略图使用响应式 grid；尊重 `prefers-reduced-motion`。

- [ ] **Step 10: 运行前端全门禁**

```bash
cd frontend && pnpm test
cd frontend && pnpm lint
cd frontend && pnpm typecheck
cd frontend && pnpm build
```

- [ ] **Step 11: 提交**

```bash
git add frontend/src/components frontend/src/i18n frontend/src/app/globals.css frontend/tests
git commit -m "feat: add bilingual replay upload experience"
```

### Task 12: 容器、运行命令、清理调度、文档和完整验收

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `Makefile`
- Modify: `README.md`
- Create: `scripts/smoke_replay.py`
- Test: `backend/tests/test_replay_container_contract.py`
- Test: `backend/tests/test_replay_smoke_script.py`

**Interfaces:**
- Produces: `make dev-replay-worker`、`make verify-replay`、`make verify-replay-ffmpeg`、`make verify-replay-postgres`、`make smoke-replay`。
- Produces: Compose `replay-worker` 和共享私有 `replay_data` volume。

- [ ] **Step 1: 写容器契约失败测试**

断言 Backend image 安装 `ffmpeg`，Compose 有独立 `replay-worker`，API 和 worker 共享 `/var/lib/lol-ai-coach/replays`，worker 命令为 `python -m app.workers.replay`，healthcheck 使用 `python -m app.workers.replay --check`，frontend 不收到 `REPLAY_TOKEN_SECRET`、S3 credentials、Riot 或 OpenAI key。

- [ ] **Step 2: 写 Make target 与 smoke 隐私测试**

smoke 输出只允许类似：

```text
replay=ready artifacts=3 delete=ok
```

脚本从忽略的环境变量读取 `REPLAY_SMOKE_MATCH_ID` 和 `REPLAY_SMOKE_PUUID`，用 FFmpeg 在临时目录生成恰好 600 秒、320×180 的低码率授权测试图案，完成 create/upload/complete/poll/artifacts/delete 后删除临时文件。测试必须拒绝输出 match ID、PUUID、token、文件名、object key、URL 或原始响应体。

- [ ] **Step 3: 运行测试并确认失败**

```bash
cd backend && .venv/bin/pytest tests/test_replay_container_contract.py tests/test_replay_smoke_script.py -v
```

- [ ] **Step 4: 更新 Backend image 和 Compose**

Dockerfile 安装后清理 apt metadata：

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
```

Compose 增加 `replay-worker`，复用 backend image/environment/database dependency；API 和 worker 挂载 `replay_data:/var/lib/lol-ai-coach/replays`。Worker healthcheck 调用 `--check`，不得通过“进程存在”冒充依赖可用。`REPLAY_ENABLED` 默认 false，示例本地启用时显式提供至少 32 字节随机 `REPLAY_TOKEN_SECRET`，不得提交真实 secret。

- [ ] **Step 5: 更新 Makefile**

目标固定为：

```makefile
dev-replay-worker:
	cd backend && .venv/bin/python -m app.workers.replay

verify-replay:
	cd backend && .venv/bin/pytest tests/test_replay_*.py -m "not integration and not replay_ffmpeg" -v
	cd frontend && pnpm test -- replay-api-client.test.ts replay-storage.test.ts replay-section.test.tsx

verify-replay-ffmpeg:
	cd backend && .venv/bin/pytest tests/integration/test_replay_ffmpeg.py -m replay_ffmpeg -v

verify-replay-postgres:
	test -n "$$TEST_DATABASE_URL"
	cd backend; DATABASE_URL=$$TEST_DATABASE_URL .venv/bin/alembic upgrade head
	cd backend; .venv/bin/pytest tests/integration -m "integration and not replay_ffmpeg" -v
```

同时把现有 `test` 目标的 marker 改为 `-m "not integration and not replay_ffmpeg"`，保证真实媒体测试只由 `verify-replay-ffmpeg` 运行。

- [ ] **Step 6: 更新 `.env.example` 与中英文 README**

示例 secret 必须留空；`REPLAY_SMOKE_MATCH_ID` 和 `REPLAY_SMOKE_PUUID` 也留空且只允许出现在被忽略的本地 `.env`。文档包含：FFmpeg 安装、Replay 环境变量、本地目录、worker 启动、S3 bucket CORS、生产网关的 `5 create/hour/IP`、`2 local uploads/IP`、`60 API requests/minute/IP` 限制、`REPLAY_GATEWAY_RATE_LIMITS_ENFORCED` 上线门、保留期、权利限制、七个 API、无 AI 结论边界和每个验证命令的真实依赖。

- [ ] **Step 7: 运行全部自动门禁**

```bash
make verify-replay
make verify-replay-ffmpeg
TEST_DATABASE_URL="$TEST_DATABASE_URL" make verify-replay-postgres
make verify
git diff --check
```

Expected: 全部 PASS；若 Docker CLI 仍不可用，只能把 Docker 记录为“未执行”，不能写成通过。

- [ ] **Step 8: 运行 Docker 和浏览器验收（环境可用时）**

```bash
docker compose config
docker compose up --build
make smoke-replay
```

在 `zh-CN` 和 `en-US` 各完成一次：选择生成的测试视频、设置 `00:00`、确认授权、上传、等待 ready、查看验证帧、刷新恢复、删除并确认存储对象消失。不得使用真实玩家或未授权视频进行自动化 fixture。

- [ ] **Step 9: 最终隐私和范围扫描**

```bash
rg -n "OPENAI_API_KEY|openai|mistake|错误操作|意识评分|object_key|token_digest|selected_puuid" backend/app/services/replays backend/app/api/replays.py frontend/src/components/replay-*.tsx
git status --short
```

人工确认 OpenAI/语义判断不存在；`object_key/token_digest/selected_puuid` 只存在于后端内部模型或服务，不存在于公开 schema、前端代码、日志格式。

- [ ] **Step 10: 提交**

```bash
git add backend/Dockerfile docker-compose.yml .env.example Makefile README.md scripts/smoke_replay.py backend/tests/test_replay_container_contract.py backend/tests/test_replay_smoke_script.py
git commit -m "chore: complete replay r1 runtime and verification"
```

## Final Review Checklist

Cursor 完成 Task 12 后，不要只报告“测试通过”，必须逐项给出实际证据：

- 当前分支与最终 commit 列表；
- `make verify` 结果；
- Replay 定向单元/前端结果；
- 真实 FFmpeg 集成结果；
- PostgreSQL 迁移、并发领取和 repository 结果；
- Docker 是否实际执行；
- 中英文浏览器流程是否实际执行；
- 使用的测试视频是否为运行时生成或明确授权；
- 是否确认没有 OpenAI 调用和教练结论；
- 是否确认 `.env`、媒体、token、PUUID、对象 Key 和预签名 URL 未提交。

如果任何依赖环境不可用，明确写“未执行”和原因，不得用 mock 测试代替真实 FFmpeg、PostgreSQL、S3-compatible 或 Docker 验证结论。
