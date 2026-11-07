# 极光商绘：剪辑模块 AI 接手说明

日期：2026-11-07，北京时间。用途：交给同事的 AI，继续实现已有口播视频的后置剪辑和网站接入。本文描述当前架构、接口与开发范围。

## 1. 接手目标和当前状态

主站已提供文案、配音、形象、动作模板、数字人口播生成、预览下载与剪辑素材交接。接手任务从**已完成的口播原片**开始：对齐字幕、编排素材、渲染成片、回报状态，并与主站完成最终成片入库及作品展示。

**剪辑模块目前尚未开发，没有现成的剪辑仓库、剪辑引擎或渲染服务。** 网站的“智能剪辑”目前是待开发入口。主站已有素材交接 API，可以下载素材并接收未来剪辑服务的进度回调；这些接口不执行字幕对齐、剪辑或渲染。`result_ready` 当前只保存外部结果引用，尚不负责取回或验证外部成片，也不会自动把它加入“我的作品”。接手方需要从头实现剪辑模块，再与主站接通完整交付链路。

## 2. 代码仓库和开发起点

- 主站：`https://github.com/cai18122668086/polaris-commerce-studio`，取最新 `main`。此次改动以视频模块为范围。
- 剪辑模块：尚未开发，当前没有可交接的剪辑仓库或既定技术栈。由接手方确定实现方案和代码组织方式。

开发输入是主站已生成的口播原片、实际配音、确认稿和素材清单。第一步以这些输入制作基础字幕成片，再逐步实现自动编排、渲染和在线任务服务。

## 3. 主站架构

- 网站业务入口：`https://www.tengliapi.xyz`。视频页面在 `/video-studio`，业务 API 在同一 origin 的 `/api/v1/video-studio/...`。
- 前端：React 19、TypeScript、Next App Router 目录结构，由 Vinext/Vite 构建运行。视频页面组件在 `components/video-studio/`，状态、接口和数据处理在 `features/video-studio/`。
- 后端：Python 3.13、FastAPI、SQLAlchemy、Alembic。视频 API 使用独立 `video-api` 服务；图像、采集和复刻业务使用各自现有 API/worker。
- 持久化：PostgreSQL 保存用户、工作区、项目、确认稿、任务和交接记录；Redis 用于现有异步业务；MinIO/S3 用于现有图像资产。视频原片、实际音频和交接包保存在视频服务的持久卷中，由后端鉴权后提供下载。
- 网关：Caddy 按业务路径分流。视频 API 的认证和用户体系与主站共用。
- `https://api.tengliapi.xyz` 是模型中转入口；剪辑端的业务 API 请求应使用上面的 `www` 站点。支付入口为独立支付服务。
- 视频空间目前保留灰度权限。联调账号和素材授权由主站负责人提供，接口仍按用户、workspace 和任务做权限隔离。

## 4. 已有视频能力

1. 项目草稿、文案库、文案版本和生成确认稿持久化；每条视频绑定自己的不可变确认稿快照。
2. 文案提取与二创助手；公共音色、试听、语速、情绪、语言选项和克隆音色。
3. 公共形象及私人照片/视频形象；原创动作底片预览确认后进入后续生成。
4. 文本配音驱动和上传音频驱动；按实际音频时长准备完整正向动作，再生成对口型原片。
5. 原片预览、下载、作品记录、阶段进度与素材交接 ZIP。
6. 对口型原渠道和备用路由。慢任务继续查原任务；明确失败且备用形象已配置时，按既有规则切换。
7. 后台恢复：每 15 秒扫描；数据库运行锁默认 120 秒，每 40 秒续租；每实例最多两个恢复工作线程。登记请求等待上限 180 秒，单轮找回窗口 90 秒；仍未找到时按 15、30、60、120、240、300 秒退避继续查询。
8. 重启后自动接管失去有效租约的可恢复任务，复用已确认的模型、音频和供应商任务编号。等待人工预览确认的形象不会被自动批准；已明确失败的生成不会被当成新任务重新付费提交。

具体可选音色、形象及功能开关以当前账号和服务端配置为准。后台恢复优先保持付费请求只提交一次；缺少任何可查询编号且没有可靠完成凭据的付费提交，会保留待核对状态。

## 5. 主站代码入口

- `backend/app/video_studio_routes.py`、`video_studio_models.py`：项目、文案版本和工作区范围。
- `backend/app/video_generation.py`、`video_generation_models.py`：生成任务、原片与音频下载。
- `backend/app/video_generation_media.py`：音频测量、动作准备和登记结果找回。
- `backend/app/video_generation_runtime.py`、`video_generation_recovery.py`：跨实例运行锁、续租、后台重试与重启恢复。
- `backend/app/video_providers.py`、`video_lipsync.py`：上游调用及既有对口型路由。
- `backend/app/video_tts.py`、`video_voice_cloning.py`、`video_avatar_uploads.py`：配音、克隆和私人形象。
- `backend/app/video_editing_handoff.py`：素材 manifest 和 ZIP。
- `backend/app/video_editing_routes.py`、`video_editing_models.py`：限时授权、素材下载、进度回调。
- `tools/fetch_video_editing_handoff.py`：剪辑端下载与 SHA-256 校验参考客户端。
- `docs/video-studio-editing-api-v1.md`、`docs/openapi-v1.json`：现有 API 协议与字段。
- `components/video-studio/generation-preview.tsx`：现有“剪辑材料”下载入口。
- `backend/tests/test_video_editing.py`、`test_video_editing_client.py`：接口行为与幂等合同测试。

## 6. 剪辑端接收什么

每条输入包括口播 MP4、该次实际配音、确认稿（文本驱动时）和 `manifest.json`。

- `schema_version` 当前为 `1.0`。
- `generation_task_id` / `idempotency_key` 标识原口播任务；`project_id`、`confirmed_version_id` 绑定原项目与确认稿版本。
- `files.video/audio/script` 给出文件名，纯音频驱动的 `script` 可为 null。
- `audio_format`、`video_format` 包含 MIME、字节数、SHA-256；视频还包含实测尺寸、fps、时长。
- `script_sha256` 是确认稿原始 UTF-8 字节哈希；无稿时为 null。
- `subtitles.status` 为 `pending_alignment` 或 `transcription_required`。
- `reference_timestamps_reusable=false`：字幕时钟应根据当前实际配音重新对齐。纯音频任务先转写。
- TTS 导出仅含用于剪辑的音色名称、语速、情绪和语言快照；内部渠道、密钥和计费凭据留在主站后端。

先校验所有文件哈希，再生成剪辑输入。原稿作为不可变输入保留；字幕换行、标点与显示样式另存，不能用编辑器后续草稿覆盖原稿。

## 7. 现有在线接口

业务 API base：`https://www.tengliapi.xyz`。

用户通过正常登录会话创建授权：

```http
POST /api/v1/video-studio/workspaces/{workspace_id}/generation-tasks/{job_id}/editing-handoffs
Content-Type: application/json

{"request_id":"<UUID>","expires_in_seconds":3600}
```

仅已完成的 `lipsync` 任务可交接。返回 `id`、`access_token`、`manifest_url`、`events_url` 与过期时间；默认一小时，允许 60 秒到 24 小时。同一 request_id 与相同参数重放返回原授权，不延长有效期。

剪辑端使用单任务的 `Authorization: Bearer <access_token>`：

```http
GET  /api/v1/video-studio/editing-handoffs/{handoff_id}/manifest
GET  /api/v1/video-studio/editing-handoffs/{handoff_id}/assets/video
GET  /api/v1/video-studio/editing-handoffs/{handoff_id}/assets/audio
GET  /api/v1/video-studio/editing-handoffs/{handoff_id}/assets/script
POST /api/v1/video-studio/editing-handoffs/{handoff_id}/events
```

Token 通过安全配置提供；只在请求 Header 使用。素材路径使用 manifest 返回的同 origin 路径。客户端不跟随重定向、不向其他域发送该 Token。

也可以由用户在作品中下载“剪辑材料”ZIP，用于第一轮离线接入；该下载使用用户会话。

参考客户端运行方式：先在隔离 Python 环境安装 `httpx`，通过安全配置设置 `VIDEO_EDITING_BASE_URL` 与 `VIDEO_EDITING_ACCESS_TOKEN`，然后从主站仓库运行：

```powershell
python tools/fetch_video_editing_handoff.py --handoff-id <UUID> --output editing-inputs
```

下载结果位于 `editing-inputs/<handoff_id>/`，包含已校验素材和 manifest，不保存 Token。

## 8. 剪辑状态回调

状态依次为 `accepted`、`aligning`、`editing`、`result_ready`；中间可报告 `failed`。允许跳过中间状态，不能倒退；`failed` 与 `result_ready` 为终态。

```json
{
  "event_id": "<本次事件固定 UUID>",
  "sequence": 1,
  "status": "accepted",
  "service_task_id": "<剪辑端固定任务 ID>"
}
```

sequence 从 1 开始严格递增，最大 100；service_task_id 从第一次事件起固定。网络超时重放**原 event_id、原 sequence 和原内容**。相同事件重复提交不会新增记录；修改内容、错序或绑定不同剪辑任务会返回 409。

完成事件使用下一序号，增加 `script_sha256` 与 `result_reference`。文本驱动必须原样回传 manifest 的稿件哈希；无稿任务传 null。result_reference 是外部存储或任务引用，最长 1000 字符。

当前 events 请求只接受现有 schema 字段，不能把 MP4、字幕文件或自定义结果 manifest 当作新字段直接提交。401 表示授权失效，需要主站重新授权；409 先核对状态和 revision；422 检查字段及稿件哈希。

## 9. 待开发的剪辑模块

以下能力需要接手方实现；技术选型、目录和运行命令在方案确定后补充：

- 素材输入与校验：读取主站 manifest，核验原片、配音及确认稿哈希。
- 字幕处理：文本任务按实际配音对齐；无稿音频先转写，再生成字幕时间轴。
- 编排与渲染：实现标题、产品图、补充镜头、音乐、样式配置和成片输出。
- 剪辑任务服务：实现任务创建、进度查询、幂等、失败处理及重启恢复。
- 成片交付：与主站约定文件上传或可信存储回收、结果校验和作品展示。

新模块的输入应绑定原片/配音/稿件哈希、音文对齐结果、产品素材和剪辑配置。尺寸、帧率与音频格式读取实测字段；输出规格由双方明确约定，不把原片硬编码为 1080p 或固定 fps。

## 10. 建议接手顺序和分工

1. **第一条离线成片**：用一个已完成任务的 ZIP，校验素材，生成字词/句子对齐、SRT 和基础字幕 MP4。输入 MP4 与配音由主站提供。
2. **开发编排与渲染**：确定技术方案，实现 manifest 输入适配和一种基础版式，逐步加入标题、产品图、补充镜头和背景音乐，保留可重复执行的任务目录与输入哈希。
3. **在线任务适配器**：消费单任务授权；以 generation_task_id + 素材/剪辑配置哈希做幂等，保存 service_task_id、事件 UUID/序号和运行状态。重启后继续已有剪辑任务，不创建重复任务。
4. **最终成片交付协议**：双方约定 MP4、SRT/ASS、字词时间轴、输入/输出哈希、时长/尺寸/fps、存储引用及错误码。当前 result_reference 只登记引用，文件上传或可信存储回收、验证和入库需要新增接口或适配器。
5. **网站闭环**：主站开发方接入创建剪辑任务、进度显示、结果校验入库和作品预览下载；剪辑开发方提供稳定的任务创建/查询/结果契约以及实际成片。
6. **验收后开放入口**：以一条真实任务走通“主站原片 → 剪辑 → 主站成片”，再扩展母版、批量任务和更多画幅。

首轮验收：所有输入/输出可校验；字幕按当前配音对齐；全片可解码且有正确音轨；开头、中段、结尾播放正常；重试和重启不会重复创建任务；用户只可查看本工作区授权的内容；主站展示的是实际取回并校验的成片。

## 11. 运行和协作边界

- 视频恢复功能只在独立 video-api 开启，迁移版本包含 `20261107_0041`。后台运行锁和退避位于 `video_generation_runs`；业务任务材料位于原 `video_generations`。
- 恢复逻辑沿用既有用户请求、确认稿、素材、模型和供应商任务编号。对已发出但无法确认结果的付费 POST，保留核对状态，不重新提交。
- 主站登录、灰度权限、上游配音和口型密钥保持服务端管理。剪辑端通过单任务授权接入素材和回调；生产发布由主站维护流程执行。
- 私有素材、模型缓存、Token、SSH/数据库凭据和运行输出保存在仓库外。交接文档本身不包含这些凭据。

给接手 AI 的首个任务：先阅读本文与主站仓库的相关入口，核对现有 API schema，明确剪辑模块尚未开发，然后制定实现方案，完成离线素材适配与第一条字幕基础成片。随后提出可落地的最终成片交付接口，并完成在线任务和作品展示闭环。
