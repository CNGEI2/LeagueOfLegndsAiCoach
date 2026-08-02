# LoL AI Coach Riot 服务器自动识别设计

- 状态：规格已确认通过，可进入实施
- 日期：2026-08-01
- 依赖：Phase 2 Riot Integration、现有玩家与比赛缓存
- 产品语言：`zh-CN`、`en-US`
- 用户输入：仅 Riot ID，格式为 `游戏名#标签`

## 1. 目的

当前玩家查询要求用户同时提供 Riot ID 与服务器代码。普通玩家不应理解 `NA1`、`EUW1` 或区域路由的技术含义。本功能将服务器识别移入后端：玩家只输入 Riot ID，系统自动检查 Riot 官方支持的 League of Legends 平台。

如果该 Riot ID 只存在于一个平台，系统直接进入玩家页面；如果同一个 Riot ID 在多个平台都存在，系统只展示实际检测到的候选服务器，让用户确认。用户不能自由填写服务器代码。

本功能只改变玩家身份解析入口，不改变比赛、回放和后续分析数据继续以 `PUUID + platform` 为边界的原则。

## 2. 目标结果

本功能必须实现：

1. 首页只保留一个 Riot ID 输入框。
2. 后端解析 `游戏名#标签` 并取得全局 PUUID。
3. 后端检测 Riot 官方支持的所有 LoL 平台。
4. 唯一平台时自动返回玩家资料。
5. 多平台时返回候选服务器，并要求用户从候选项中确认。
6. 未找到、部分检测失败、限流和上游不可用必须彼此区分。
7. 检测结果使用 PostgreSQL 缓存，减少 Riot API 请求。
8. 相同 Riot ID 的同进程并发检测合并为一次。
9. 前后端覆盖中英文状态、错误和服务器显示名称。
10. 不记录 Riot API Key、完整 PUUID 或完整 Riot ID。

## 3. 非目标

本功能不包括：

- 中国大陆腾讯服务器；Riot 官方 API 当前没有对应平台路由。
- 根据 IP、时区、浏览器语言或 Riot ID 标签猜测服务器。
- 把用户对多服务器候选项的选择保存为全局默认。
- Riot Sign On 或用户账号系统。
- OP.GG 或其他第三方网站抓取。
- 修改比赛、回放或分析记录的 `platform` 绑定方式。
- 修复 Replay R1 的 FFmpeg 30 FPS 和删除烟测问题；它们是合并前独立阻塞项。
- 分布式 single-flight；首版只保证单进程请求合并，多副本重复探测由共享限流器控制。

## 4. 已确认决策

| 项目 | 决策 |
| --- | --- |
| 用户输入 | 单字段 Riot ID：`游戏名#标签` |
| 唯一平台 | 自动进入玩家页面 |
| 多个平台 | 用户从系统候选列表确认 |
| 服务器输入 | 不允许自由填写服务器代码 |
| 检测方式 | Account-V1 取得 PUUID，Summoner-V4 检查平台存在性 |
| 并发 | 共享最大并发 `4` |
| 正向缓存 | 24 小时 |
| 未找到缓存 | 5 分钟 |
| 部分失败 | fail closed，不得误判为唯一平台 |
| 用户选择 | 不保存为全局偏好 |
| 旧接口 | 暂时保留，供内部工具和兼容期使用 |
| 数据边界 | 玩家、比赛、回放继续按 `PUUID + platform` 区分 |

## 5. Riot 路由目录

平台目录是闭合、类型化并有测试覆盖的配置，不允许从用户输入拼接主机名。

### 5.1 区域路由

- `AMERICAS` -> `americas.api.riotgames.com`
- `ASIA` -> `asia.api.riotgames.com`
- `EUROPE` -> `europe.api.riotgames.com`
- `SEA` -> `sea.api.riotgames.com`

### 5.2 平台路由

- `BR1`
- `EUN1`
- `EUW1`
- `JP1`
- `KR`
- `LA1`
- `LA2`
- `NA1`
- `OC1`
- `TR1`
- `RU`
- `PH2`
- `SG2`
- `TH2`
- `TW2`
- `VN2`

每个平台条目同时声明：平台 API 主机、Match-V5 所属区域、中英文显示名称和稳定排序值。新增或移除 Riot 平台必须修改该目录并更新契约测试。

## 6. 架构

```text
Localized Search UI
  -> POST /api/v1/players/detect
      -> RiotIdParser
      -> PlatformDetectionService
          -> PlatformDetectionRepository
          -> RiotGateway
              -> Account-V1 regional route
              -> Summoner-V4 platform routes (bounded concurrency)
          -> PlayerService for the selected platform
  -> resolved player
     OR confirmation_required + detected candidates
  -> POST /api/v1/players/detect/{detection_id}/confirm
      -> validate candidate
      -> PlayerService
```

`PlatformDetectionService` 是独立边界，负责检测、缓存、并发合并和候选验证。它不负责比赛抓取、静态资料解析或页面文案。

现有 `PlayerService` 继续负责在已知平台下获取并缓存玩家资料。检测服务选出唯一平台或验证用户确认后，才调用 `PlayerService`。

## 7. 后端组件

建议新增或扩展以下模块：

```text
backend/app/
  api/players.py
  core/routing.py
  models/player.py
  models/platform_detection.py
  repositories/players.py
  repositories/platform_detections.py
  schemas/platform_detection.py
  services/platform_detection.py
  services/riot/gateway.py
```

职责：

- `core/routing.py`：区域、平台、显示键和 Match 路由映射。
- `RiotIdParser`：从最后一个 `#` 分隔游戏名和标签，执行长度与空值校验。
- `PlatformDetectionService`：缓存查询、Account 查询、平台探测、结果分类和 single-flight。
- `PlatformDetectionRepository`：PostgreSQL 正向、歧义和未找到缓存。
- `RiotGateway`：提供按区域查询 Account、按平台查询 Summoner 的窄接口。
- `api/players.py`：只做请求验证、服务调用和公共响应映射。

## 8. Riot ID 解析

输入是一个字符串，例如：

```text
CNGEI#1115
```

解析规则：

1. 去除输入两端空白。
2. 使用最后一个 `#` 作为分隔符。
3. 分隔符两侧都必须非空。
4. `game_name` 长度为 1 到 32 个 Unicode 码点。
5. `tag_line` 长度为 1 到 16 个 Unicode 码点。
6. 缓存键使用现有 NFKC 与大小写标准化方法。
7. 页面显示 Riot 返回的规范名称，不显示本地标准化值。

解析失败返回 `INVALID_RIOT_ID`，且不调用 Riot API。

## 9. 检测数据流

### 9.1 缓存优先

1. 根据标准化的 `game_name + tag_line` 查询检测缓存。
2. 有效正向缓存直接返回唯一平台或候选平台。
3. 有效未找到缓存直接返回 `PLAYER_NOT_FOUND`。
4. 缓存不存在或过期时进入 Riot 检测。

### 9.2 获取 PUUID

1. 首先使用部署配置的首选区域调用 Account-V1。
2. 首选区域返回 `404` 时，按固定顺序尝试其余区域。
3. 任一区域返回有效 Account DTO 后停止继续请求。
4. 区域返回的关键身份字段冲突时返回 `RIOT_INVALID_RESPONSE`。
5. 所有区域均明确返回 `404` 才判定玩家不存在。
6. 任一区域出现未恢复的 `429`、超时或 `5xx` 时，不能把结果缓存为不存在。

### 9.3 检查平台

1. 使用取得的 PUUID 调用每个平台的 Summoner-V4 `by-puuid`。
2. 共享信号量将并发限制为 `RIOT_MAX_CONCURRENCY`，默认 `4`。
3. `200` 且 DTO 合法：加入候选平台。
4. `404`：该平台不存在该玩家。
5. `401` / `403`：立即停止并返回认证错误。
6. `429`、超时或 `5xx` 在既有重试策略耗尽后：整次检测返回暂时不可用。
7. 只要存在未确定的平台结果，就禁止自动判定唯一平台。

### 9.4 分类结果

- 候选数为 `0`：保存 5 分钟未找到缓存，返回 `PLAYER_NOT_FOUND`。
- 候选数为 `1`：保存 24 小时正向缓存，调用 `PlayerService` 并返回 `resolved`。
- 候选数大于 `1`：保存 24 小时候选缓存，返回 `confirmation_required`。

不使用最近比赛时间自动决定多平台账号；用户已明确要求在多个服务器存在完全相同 Riot ID 时自行确认。

## 10. 公共 API

### 10.1 自动检测

```http
POST /api/v1/players/detect
Content-Type: application/json
```

请求：

```json
{
  "riot_id": "CNGEI#1115",
  "locale": "zh-CN"
}
```

唯一平台响应：

```json
{
  "status": "resolved",
  "player": {
    "puuid": "public-player-identifier",
    "game_name": "CNGEI",
    "tag_line": "1115",
    "platform": "NA1",
    "summoner_level": 100,
    "profile_icon_id": 1
  },
  "request_id": "request-correlation-id"
}
```

多平台响应：

```json
{
  "status": "confirmation_required",
  "detection_id": "uuid",
  "expires_at": "2026-08-01T12:15:00Z",
  "candidates": [
    {
      "platform": "NA1",
      "display_name": "北美服"
    },
    {
      "platform": "EUW1",
      "display_name": "欧西服"
    }
  ],
  "request_id": "request-correlation-id"
}
```

`display_name` 根据请求 locale 返回；前端不得自己猜测平台名称。

### 10.2 候选确认

```http
POST /api/v1/players/detect/{detection_id}/confirm
Content-Type: application/json
```

请求：

```json
{
  "platform": "NA1",
  "locale": "zh-CN"
}
```

后端必须验证：

1. `detection_id` 存在且确认期限未过。
2. 缓存的候选结果未过期。
3. 所选平台属于候选列表。
4. 所选平台的玩家资料仍可解析。

确认成功返回与唯一平台相同的 `resolved` 响应。确认不会改变候选缓存，也不会保存为所有用户共享的默认服务器。

### 10.3 兼容接口

现有接口暂时保留：

```http
GET /api/v1/players/resolve?platform=NA1&game_name=CNGEI&tag_line=1115
```

它只供内部烟测、旧前端兼容和运维诊断使用。新首页不得调用或展示它的 `platform` 输入。一个完整发布周期后再单独决定是否弃用，不在本功能中删除。

## 11. 数据库设计

新增 `player_platform_detections`：

- `id UUID PRIMARY KEY`
- `game_name_key VARCHAR`
- `tag_line_key VARCHAR`
- `canonical_game_name VARCHAR NULL`
- `canonical_tag_line VARCHAR NULL`
- `puuid VARCHAR NULL`
- `result_status VARCHAR`：`resolved`、`ambiguous`、`not_found`
- `candidate_platforms JSONB`
- `fetched_at TIMESTAMPTZ`
- `expires_at TIMESTAMPTZ`
- `confirmation_expires_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

约束：

- 标准化游戏名与标签组成唯一键。
- `resolved` 必须恰好有一个候选平台和非空 PUUID。
- `ambiguous` 必须至少有两个候选平台和非空 PUUID。
- `not_found` 必须没有候选平台且 PUUID 为空。
- 候选平台只能来自闭合路由目录。
- `confirmation_expires_at` 只用于歧义结果。

候选确认窗口为 15 分钟。检测缓存仍可保留 24 小时；确认窗口过期后，前端重新发起检测即可得到新的确认窗口，不需要重新探测未过期的平台缓存。

原始 Riot 响应不落库。

### 11.1 现有 `players` 表兼容迁移

当前 `players.puuid` 是全局唯一，并且 upsert 只以 PUUID 为冲突键。多服务器候选要求同一个 PUUID 可以同时保存多个平台的 Summoner 资料，因此本功能必须：

1. 删除 `players.puuid` 的单列唯一约束。
2. 新增 `UNIQUE (platform, puuid)`。
3. 将玩家 upsert 的冲突目标改为 `(platform, puuid)`。
4. 保留 PUUID 普通索引和平台索引。
5. 迁移既有数据时原样保留所有行，不重写 PUUID、平台或玩家显示信息。
6. 为同一 PUUID 在两个平台的写入、读取和更新增加 PostgreSQL 集成测试。

`recent_match_caches` 已使用 `(platform, puuid)` 作为边界；比赛 ID 自带平台前缀；Replay R1 也显式保存平台，因此这些表不需要改变身份边界。

## 12. 缓存与并发

- `resolved`、`ambiguous`：默认缓存 24 小时。
- `not_found`：默认缓存 5 分钟。
- 缓存时间通过设置项配置，并设安全上下限。
- 同一进程内，同一标准化 Riot ID 的并发检测共享同一个异步任务。
- 共享 Riot HTTP 信号量继续限制所有上游请求，不为检测服务创建无上限线程池。
- 多副本可能同时探测同一过期键；数据库 upsert 收敛为相同缓存结果，API 正确性不受影响。
- 用户确认的平台若返回 `404`，删除对应检测缓存并允许一次重新检测；不得无限循环。

建议设置：

```text
RIOT_PLATFORM_DETECTION_ENABLED=true
RIOT_PLATFORM_DETECTION_TTL_SECONDS=86400
RIOT_PLATFORM_DETECTION_NOT_FOUND_TTL_SECONDS=300
RIOT_PLATFORM_CONFIRMATION_TTL_SECONDS=900
RIOT_ACCOUNT_PRIMARY_REGION=AMERICAS
```

## 13. 错误合同

沿用现有错误 envelope。新增稳定错误码：

- `INVALID_RIOT_ID`：格式或长度非法，不重试。
- `PLAYER_NOT_FOUND`：所有区域与平台均明确不存在，不重试。
- `RIOT_PLATFORM_DETECTION_UNAVAILABLE`：部分平台结果未知，可重试。
- `PLATFORM_CONFIRMATION_EXPIRED`：确认窗口过期，可重新检测。
- `PLATFORM_NOT_IN_CANDIDATES`：提交了非候选平台，不重试。

沿用：

- `RIOT_NOT_CONFIGURED`
- `RIOT_AUTH_FAILED`
- `RIOT_RATE_LIMITED`
- `RIOT_UNAVAILABLE`
- `RIOT_INVALID_RESPONSE`

错误判定必须 fail closed：只要有一个平台因限流、超时或服务错误而无法确定，就不能把其余单一成功结果当作唯一平台。

## 14. 前端体验

首页搜索区只显示：

- 一个 Riot ID 文本框。
- 一个提交按钮。
- 输入示例 `CNGEI#1115`。
- 说明文字：标签不代表服务器，服务器由系统识别。

状态：

1. `idle`：等待输入。
2. `detecting`：显示“正在识别账号和服务器”。
3. `resolved`：自动进入玩家页面。
4. `confirmation_required`：显示候选服务器按钮。
5. `not_found`：显示未找到提示和输入检查建议。
6. `temporarily_unavailable`：显示重试按钮，不暗示玩家不存在。

候选服务器必须：

- 只来自后端候选响应。
- 使用本地化全名，例如“北美服 / North America”。
- 支持键盘操作和可见焦点。
- 不依赖颜色区分。
- 提交期间禁用重复点击。

确认后导航仍携带内部平台：

```text
/{locale}/players/{puuid}?platform=NA1
```

平台参数是系统状态，不是首页用户输入。

## 15. 安全、隐私与可观测性

- Riot API Key 只保存在后端环境变量。
- API Key、Authorization header、完整 PUUID 和完整 Riot ID 不进入日志、指标标签、错误文本或测试快照。
- 日志允许记录请求 ID、结果类型、候选数量、缓存状态、探测数量、重试次数和耗时。
- Riot ID 只以不可逆摘要或既有安全引用形式进入结构化日志。
- `detection_id` 使用不可预测 UUID，不包含 Riot ID、PUUID 或平台列表。
- 指标标签使用闭合集合，禁止把玩家标识放入高基数标签。

建议指标：

- `riot_platform_detection_requests_total{outcome}`
- `riot_platform_detection_duration_seconds`
- `riot_platform_detection_cache_total{status}`
- `riot_platform_detection_probes_total{result}`
- `riot_platform_confirmation_total{outcome}`

## 16. 测试策略

### 16.1 后端单元与合同测试

- 单字段 Riot ID 解析，包括 Unicode、空白、缺少 `#` 和长度边界。
- 16 个平台与四个区域映射。
- 平台主机只能来自闭合目录。
- 唯一平台自动解析。
- 多平台返回候选而不自动选择。
- 零平台返回 `PLAYER_NOT_FOUND`。
- 一个或多个平台超时、`429` 或 `5xx` 时 fail closed。
- `401` / `403` 立即停止。
- 正向、歧义和未找到缓存命中与过期。
- 同 Riot ID 并发请求只触发一组探测。
- 非候选确认和过期确认被拒绝。
- 确认不写入全局平台偏好。
- 响应和日志脱敏。

### 16.2 PostgreSQL 集成测试

- Alembic 从空库创建检测表。
- 旧数据库升级保留玩家、比赛和回放数据。
- `players` 唯一约束从 PUUID 改为 `(platform, puuid)`，同一 PUUID 可保存多个平台资料。
- 唯一键、状态约束、候选约束和过期查询。
- 并发 upsert 收敛。
- 过期确认窗口刷新但复用有效检测结果。

### 16.3 前端测试

- 首页只有一个 Riot ID 输入框，没有服务器自由输入。
- 中文和英文识别中、未找到、不可用和确认状态。
- 唯一平台自动导航。
- 多平台候选按钮及确认请求。
- 候选项仅使用后端返回值。
- 键盘、焦点、重复提交和移动端布局。
- 无效后端 union 响应被运行时 schema 拒绝。

### 16.4 真实烟测

新增自动检测烟测，使用忽略提交的真实 Riot ID：

1. 不传 platform 调用检测接口。
2. 验证北美账号自动识别为 `NA1`。
3. 验证玩家资料和最近比赛可读取。
4. 重复查询验证缓存命中。
5. 输出只包含安全计数和结果类型。

多平台真实账号不是自动化验收前提；该分支使用确定性假响应和 PostgreSQL 集成测试覆盖。

## 17. 发布与兼容

1. 先添加路由目录、数据库迁移、检测服务和 API，默认功能开关关闭。
2. 在测试和真实北美烟测通过后启用本地开发开关。
3. 更新前端为单字段输入并保留旧解析接口。
4. 观察限流、检测时延、错误率和候选数量。
5. 功能稳定后默认开启。

如果检测功能关闭，旧接口仍可工作；新前端应显示暂时不可用，而不是恢复服务器自由输入。

## 18. 验收标准

本功能完成必须同时满足：

1. 玩家只输入 `游戏名#标签`。
2. 北美真实账号无需服务器输入即可解析为 `NA1`。
3. 唯一平台自动进入玩家页。
4. 多平台账号只能从后端候选列表确认。
5. 部分上游失败不会产生错误的唯一平台判断。
6. 未找到与暂时不可用在两种语言中明确区分。
7. 24 小时正向缓存、5 分钟未找到缓存和并发合并符合规格。
8. 确认选择经过后端候选验证且不保存为全局默认。
9. 现有玩家、比赛和回放绑定继续使用 `PUUID + platform`。
10. `players` 表允许同一 PUUID 保存多个平台资料，且不会相互覆盖。
11. 单元、前端、静态检查、生产构建和 PostgreSQL 集成测试全部通过。
12. 真实北美自动检测烟测通过。
13. 日志、错误、指标和测试产物不泄露密钥或完整玩家标识。

## 19. 与 Replay R1 的关系

Replay R1 的内部烟测继续显式传入：

```text
REPLAY_SMOKE_PLATFORM
REPLAY_SMOKE_MATCH_ID
REPLAY_SMOKE_PUUID
```

这些是确定性运维配置，不是普通用户界面。服务器自动识别不会删除它们。

当前真实 Replay R1 烟测已确认两个独立阻塞项：

1. Docker 内 FFmpeg 需要明确输出 `-r 30`，否则当前命令可能把 30 FPS 源转为 25 FPS。
2. `DELETE_ALL` 清除访问令牌后，删除烟测应把受保护状态接口的 `REPLAY_NOT_FOUND` 视为删除完成，再断言对象卷为零。

这两个问题必须先修复并重新运行完整 create -> upload -> process -> delete -> zero-residue 烟测，但不扩大本设计的实现范围。

## 20. 权威参考

- Riot League of Legends API、Riot ID、平台与区域路由：<https://developer.riotgames.com/docs/lol>
- Riot API 参考：<https://developer.riotgames.com/apis/>
- Riot Developer Portal、Key 类型和限流：<https://developer.riotgames.com/docs/portal>
- Riot 一般政策与密钥安全：<https://developer.riotgames.com/policies/general>
