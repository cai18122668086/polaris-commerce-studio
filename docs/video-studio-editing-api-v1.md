# 视频空间 → 剪辑端接口 v1

更新：2026-11-05。实现已加入本地仓库；尚未部署，也未与外部剪辑服务联调。对接代码以 `backend/app/video_editing_routes.py` 与 `docs/openapi-v1.json` 为准。

## 交付范围

口播生成完成后，提供原口播 MP4、实际配音音频、不可变确认稿和 manifest。剪辑端下载并校验文件后，自行完成音文对齐、字幕、剪辑与成片存储，通过 events 接口回报进度和结果引用。

`result_ready` 只表示剪辑端登记了结果引用。当前服务器不拉取该引用、不验证外部成片、不自动把它加入作品列表。外部剪辑服务地址、任务创建适配器、最终成片回收和字幕文件上传仍需双方后续接入；前端因此保留“智能剪辑即将上线”。

## 认证和部署

- 用户端创建、查询、撤销交接：正常登录会话，已验证邮箱和视频灰度权限，且有 workspace 写权限；仅可操作自己的生成任务。
- 剪辑端：只使用单个交接的限时 `Authorization: Bearer <access_token>`。不接收用户 Cookie、登录密码、Tao/泉语密钥。
- 服务配置 `POLARIS_VIDEO_EDITING_HANDOFF_SECRET`，至少 32 字符；未配置返回 503。密钥仅留在服务端安全配置中，轮换会使已有交接凭据全部失效。
- 部署前执行新增迁移 `20261105_0038_video_editing_handoffs`（接在 0037 后）；目前仅在隔离验收库自动建表，不曾迁移生产库。
- 生产对接使用 HTTPS；当前本地验收 API 为 `http://localhost:8013`，前端同源入口 `http://localhost:3003`。它们是本机入口，外部剪辑服务器不能直接访问。

## 用户端创建与查询

下文 `OWNER_ROOT` 为：

```text
/api/v1/video-studio/workspaces/{workspace_id}/generation-tasks/{job_id}/editing-handoffs
```

1. `POST OWNER_ROOT`：只接受 `kind=lipsync` 且 `status=completed` 的任务。

```json
{"request_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","expires_in_seconds":3600}
```

`request_id` 是调用方生成的 UUID。同一用户/workspace 中，相同标识和相同请求返回同一交接与凭据，不延长有效期；变更任务或参数却复用标识返回 409。有效期 60–86400 秒，默认 3600 秒。过期或撤销后如需重新授权，使用新 request_id。

响应 HTTP 200，包含：

```json
{
  "id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  "generation_task_id":"cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  "expires_at":"2026-11-05T08:00:00+00:00",
  "revoked":false,
  "status":"created",
  "revision":0,
  "events":[],
  "result_reference":null,
  "access_token":"<仅通过安全配置通道交给指定剪辑端>",
  "manifest_url":"/api/v1/video-studio/editing-handoffs/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/manifest",
  "events_url":"/api/v1/video-studio/editing-handoffs/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/events"
}
```

2. `GET OWNER_ROOT/{handoff_id}`：返回状态、revision、events、result_reference，无 access_token。
3. `POST OWNER_ROOT/{handoff_id}/revoke`：立即撤销交接，重复调用仍为已撤销。不会取消外部剪辑任务，也不能收回已下载文件。

创建交接本身不生成或重新计费配音/口型。凭据不要写入 URL、日志、仓库或前端持久化存储。

## 剪辑端下载

`SERVICE_ROOT=/api/v1/video-studio/editing-handoffs/{handoff_id}`。

所有调用都带相同 Bearer Header，不依赖用户登录会话：

1. `GET SERVICE_ROOT/manifest`：读取不可变任务材料描述。
2. `GET SERVICE_ROOT/assets/video`：MP4。
3. `GET SERVICE_ROOT/assets/audio`：实际配音音频，MIME 和文件名以 manifest 为准。
4. `GET SERVICE_ROOT/assets/script`：UTF-8 原文，没有 BOM 或额外换行；仅文本驱动任务提供。纯音频驱动返回 404，不能虚构确认稿。

manifest 关键字段：

- `schema_version="1.0"`；`idempotency_key` 与 `generation_task_id` 是原口播任务 UUID；`project_id`、`confirmed_version_id` 绑定本次原始项目与确认稿版本。
- `files.video/audio/script`：安全本地文件名，script 可为 null。服务端额外给出 `assets` 相对路径；从同一个 API origin 下载，禁止把 Bearer 凭据转发到任意外部链接。
- `script_sha256`：确认稿 UTF-8 字节 SHA-256；无稿则 null。只允许围绕该稿对齐字幕，不能使用编辑器后续草稿覆盖本次确认稿。
- `audio_format.mime_type/bytes/sha256`、`audio_duration_seconds`：真实音频信息。
- `video_format.mime_type/bytes/sha256/dimensions/fps/duration_seconds`：真实视频信息，dimensions 为 `[宽,高]`。
- `tts`：本次配音音色、情绪、语速与语言快照；音频驱动可不含 TTS 信息。
- `subtitles.status`：文本驱动为 `pending_alignment`，音频驱动为 `transcription_required`；`reference_timestamps_reusable=false`。原参考视频时间戳不可直接当作新配音字幕时间戳。
- 2026-11-05 客户信息收口：新清单不再导出 `billing`；`tts` 只保留音色名称、情绪、语速和语言，供应商渠道、模型、远端音色 ID 及成本回执保留后端核账。
- `handoff`：交接状态和有效期。服务端每次下载/回调都检查有效期、撤销和原用户/workspace 权限。

仓库附有可运行的下载与哈希校验客户端：`tools/fetch_video_editing_handoff.py`。安装本项目 backend 依赖后，通过安全方式注入 `VIDEO_EDITING_BASE_URL`、`VIDEO_EDITING_ACCESS_TOKEN`，再运行：

```powershell
.venv/Scripts/python.exe tools/fetch_video_editing_handoff.py --handoff-id bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb --output editing-inputs
```

客户端拒绝跨站素材路径、重定向、危险文件名和校验不符素材；每个文件最多 200 MiB。输出按 handoff_id 分目录，不保存访问凭据。

用户也可在作品中使用已有 `GET .../generation-tasks/{job_id}/handoff` 下载 ZIP，里面有同一份视频、音频、确认稿、manifest 和处理阶段记录；ZIP 下载需要用户会话，不要把用户 Cookie 交给剪辑端。

## 剪辑端状态回调

`POST SERVICE_ROOT/events`。所有时间使用 UTC；每条事件生成新的 UUID，`sequence` 从 1 开始严格递增，最大 100。`service_task_id` 从第一条事件起固定。

```json
{
  "event_id":"dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  "sequence":1,
  "status":"accepted",
  "service_task_id":"editor-task-123"
}
```

可用状态：`accepted` → `aligning` → `editing` → `result_ready`，任一非终态也可转 `failed`。允许跳过中间状态或连续报告同一状态，但不能倒退。`failed` 和 `result_ready` 为终态。响应为最新 metadata。

完成事件示例（sequence 按实际事件数填写）：

```json
{
  "event_id":"eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
  "sequence":2,
  "status":"result_ready",
  "service_task_id":"editor-task-123",
  "script_sha256":"<manifest.script_sha256，音频无稿任务传 null>",
  "result_reference":"editor-storage/object-456"
}
```

`result_reference` 是最长 1000 字符的外部存储/任务引用，仅登记元数据，不接受上传；文本任务完成必须原样回传确认稿哈希。失败事件可带 `error_code`（最多 80 字符），不能把密钥或完整内部异常写入。

相同 event_id 与相同请求内容重放不会新增事件。相同 event_id 改内容、错序、并发 revision 冲突、变更 service_task_id 返回 409。网络超时应重放原事件，不生成新 event_id；遇到并发冲突由用户端状态接口核对 revision，再由对接调度方协调后续事件。

## 错误和验收边界

- 401 `VIDEO_EDITING_UNAUTHORIZED`：凭据缺失/无效/过期/撤销，或原授权成员失效；停止访问，联系用户重新授权。
- 403：用户或灰度权限不满足。
- 404：用户看不到该交接，或纯音频任务没有确认稿。
- 409 `VIDEO_HANDOFF_NOT_READY` / `VIDEO_HANDOFF_MEDIA_MISSING`：口播未完成或本地素材缺失，不应触发重新付费生成。
- 409 `VIDEO_REQUEST_REUSED` / `VIDEO_EDITING_EVENT_REUSED` / `VIDEO_EDITING_EVENT_ORDER` / `VIDEO_EDITING_TASK_CHANGED`：幂等或顺序冲突。
- 422 `VIDEO_EDITING_RESULT_INVALID`：结果引用为空或确认稿哈希不符；其他参数越界同样为 422。
- 503 `VIDEO_EDITING_NOT_CONFIGURED`：服务端交接密钥未配置。

已覆盖自动化验收：材料 SHA-256、无会话服务访问、跨交接凭据隔离、失效/撤销/成员失效、创建与事件幂等、错序、服务任务绑定、确认稿哈希和终态保护。真实账号已完成口播生成与 ZIP 导出；外部剪辑完成、字幕准确率、最终成片回收和生产 PostgreSQL 部署未验收。
