# 专属声音克隆接入（CosyVoice 3.5 Flash）

更新：2026-11-05，Asia/Shanghai。本节描述代码与配置现状，不代表已经完成真人录音克隆或听感验收。

## 当前结论

- **首次真实试听已完成**：用户认可最新样式并授权生成短试听。已在真实账号页面对原 ready 声音“测试”点击一次“生成试听”，结果 ready；MP3 位于隔离验收媒体 `voice-clones/cv-voice-403c0d19b5e24878b26476fa0739e0bf/preview.mp3`，页面已播放。证据 `outputs/video-studio/clone-preview-20261105/verification.json` 与截图。此段覆盖后面旧 not_created 说明。后续复用缓存，不能再合成同一短句；真人相似度听评待用户反馈，克隆视频仍未验收，实际账单未核对。
- **视觉修正**：用户认为上一版预览底部原生灰色测试按钮、重复提示不好看；已移除演示按钮，统一使用正式弹窗与黑色按钮。正式上传表单和处理页同步精简：白底、淡紫上传区域、细进度条、单句提示；列表紧凑显示。预估曲线及完成判断逻辑保留。桌面/390×844 窄屏与 typecheck、相关 ESLint 已验证；本轮无付费调用。证据 `outputs/video-studio/clone-ui-polish-20261105/`。
- **最新客户界面要求**：供应商、模型和采购成本只留后端，不作为客户价格展示。克隆配置/列表不再返回 model、preview_billing；音色目录不返回 provider；任务响应只保留配音名称，成本回执仍在数据库；新剪辑清单仅保留音色名称、语速、情绪及语言。旧 generation-prices 路径仅返回 pricing_available=false，前端不再调用。
- **进度反馈**：运行时认证 XHR 上报真实上传字节，保留 SDK 刷新/CSRF 拦截及 API 最终 401 处理。上传占整体前 25%，随后使用标注“预计”的平滑进度，快速接近 90% 后放缓，最多 98%，仅 ready 为 100%。有阶段、等待时长、慢处理提示；异常停止推进并提供查询原任务。后台只自动查询 processing 原音色，不自动重新创建或生成试听。上传中禁止关闭弹窗，提交后可关闭并在列表继续查看。
- **本轮真实现状**：用户在操作页面时自行创建了 1 条 ready 声音，preview_status=not_created；只读核查后保留了原记录和录音。本轮没有由代理创建声音、生成试听或视频，尚未听感验收。以下“尚无录音”属于较早接入阶段。
- 用户已选定先接 CosyVoice 3.5 Flash；Tao/MiniMax 系统音色、327 条缓存试听及泉语链路保留。没有重复生成试听、推送或部署，也没有改主库身份。
- 用户已在新版千问 AI 平台完成注册、实名和 API Key 创建。该平台的 API Keys 页面没有旧版百炼的地域菜单，不能继续要求用户查找“华北 2”。
- 使用官方新版地址 `https://maas.qianwenaiapi.com/api/v1/services/audio/tts/`，创建/查询为 `customization`，配音为 `SpeechSynthesizer`。密钥只写入 Git 忽略的 `backend/.env`，不要输出、复制到源码/前端/文档。
- 已真实成功执行一次只读 `list_voice`（前缀 polaris），返回空列表。没有创建任何供应商音色，没有合成音频。证据 `outputs/video-studio/cosyvoice-20261105/connection-check.json`。
- 用户截图显示 Flash、Plus 各有 10K chars 未用额度，2027-02-04 到期。“免费额度用尽即停”在截图中关闭；已建议用户自行开启，没有替用户修改云端计费设置。不能将估算费用写成实际扣费，也不能声称已经启用额度用尽即停。
- 真实账号会话自动恢复成功，现成项目仍为 `b3430e7c-99e8-4b99-a938-f5f0c368abb4`。本机已打开声音克隆表单，尚无本人录音，真实克隆、试听、克隆配音到成片仍待验收。

## 服务端

`video_cosyvoice.py` 为 HTTP 适配器。只允许官方地址、固定模型；创建使用 Base64 WAV，无需公开录音 URL。配音固定请求 MP3，再下载并解析音频；OSS 下载不转发 API Authorization、不跟随重定向，HTTP OSS 地址升级为 HTTPS。未知 POST 结果不自动重试。

`video_voice_models.py` / `video_voice_cloning.py` 保存账号和工作区私有的音色、授权版本和时间、源录音哈希、模型与渠道绑定、供应商 voice_id、克隆状态、试听状态和估算回执。用户 API 不暴露源录音路径、供应商 voice_id 或密钥。没有公开原始录音下载路由。`queued → submitting → processing → ready/failed/unknown`；未知创建按唯一前缀查询原音色，绝不因查询没有结果而重新创建。

接口均为 `/api/v1/video-studio/workspaces/{workspace_id}` 下的原灰度、真实登录和用户所有权检查：

- `GET /voice-clone-config`：启用状态、模型、录音要求、授权版本和固定试听文案。
- `GET /voice-clones` / `GET /voice-clones/{voice_id}`：本人列表和状态，不触发供应商创建或配音。
- `POST /voice-clones`：multipart `file`、UUID `request_id`、`name`、`consent=own-voice-2026-11-05`。MP3/WAV/M4A ≤10MB，实际解码后 5～60 秒；本地转为 24kHz 单声道 PCM WAV，推荐 10～20 秒清晰独白。需要用户在页面明确确认是本人声音并同意传阿里云。
- `POST /voice-clones/{voice_id}/refresh`：查询原音色。若任务仍在 queued（从未取得提交锁），可安全地原任务恢复；取得锁后不再次创建。
- `POST /voice-clones/{voice_id}/preview`：用户明确点击后，仅第一次合成固定短句；后续复用缓存，未知结果不重发。
- `GET /voice-clones/{voice_id}/preview`：本人会话下载缓存试听。

原 `/voices` 合并本人已就绪音色并标注 `source=own`；创建视频时服务端核查音色归属与状态，冻结准确的模型、音色、语速、情绪指令和语言。克隆音频保存后复用现有上传、实测时长、动作铺满、对口型、成片及剪辑交接链路。供应商渠道变化不能默默替换冻结任务。

迁移 `20261105_0039_video_cloned_voices` 接在 0038 后。已执行隔离 SQLite 迁移测试、输出 PostgreSQL 离线 SQL；未执行生产迁移。本机 8013 隔离验收库由现有 `auto_create_schema` 创建新表，先备份至本轮证据目录。原媒体未清理。

## 前端与配置

`features/video-studio/voice-clones.ts`、`components/video-studio/voice-cloning.tsx` 新增真实提交、进度、手动状态查询、试听缓存与“用于视频”。选择声音弹窗的“我的声音”可选本人已就绪音色，“系统声音”保持原目录。形象克隆仍是原本地流程，不声称已实现。

配置：

```dotenv
POLARIS_VIDEO_COSYVOICE_ENABLED=true
POLARIS_VIDEO_COSYVOICE_PLATFORM=qianwen
POLARIS_VIDEO_COSYVOICE_API_KEY=<仅后端安全配置>
POLARIS_VIDEO_COSYVOICE_MODEL=cosyvoice-v3.5-flash
```

旧版百炼北京账号可将 platform 设置为 `bailian_beijing` 并配置 `POLARIS_VIDEO_COSYVOICE_WORKSPACE_ID`；当前真实账号使用新版平台，不需要此项。示例文件默认关闭、密钥留空，不能把本机已配置当成生产已配置。

## 验证和下一步

- 客户信息收口/进度本轮：60 项后端、21 项前端测试、typecheck、相关 ESLint、Ruff 与构建通过；证据 `outputs/video-studio/voice-progress-20261105/`。本地模拟页面只验证进度组件，不上传录音或调用供应商，不能当作真实任务进度证据。下一步可由用户对现有 ready 声音明确点击一次试听并听评，不要重新创建音色。
- 后续已修复页面焦点复核导致的“页面暂不可用”闪退：等待不再当作拒绝，同页复核保留编辑器与录音选择；退出、账号切换及明确拒绝仍清除旧访问状态。访问状态新增 9 项回归，与持久化共 16 项通过，typecheck、相关 ESLint、构建通过。本机恢复后已打开克隆表单，没有提交任何录音。证据 `outputs/video-studio/access-stability-20261105/`。
- 新增克隆测试 17 项通过；包含原配音、视频生成、剪辑和项目持久化的本轮后端回归共 66 项通过，全部使用假业务供应商，不计作真实克隆验收。
- 前端持久化 7 项、typecheck、相关 ESLint、Ruff 和生产构建通过。构建之后只重启了本机 3003/8013 验收服务，保留 3000/8000。
- 真实只读凭据验证成功；真实账号页面能恢复并显示 333 个原系统/旧音色，克隆表单和明确授权/首次试听计费说明可见。
- 下一步由用户提供本人清晰录音，并在本机页面勾选授权后创建；查询 ready 后只生成一份短试听，用户听感确认，再使用短稿生成一次克隆声音视频。不要扫描本机任意录音冒充用户授权样本。
- `outputs/video-studio/cosyvoice-20261105/` 为本轮证据目录，含日志、只读连通报告、迁移 SQL、隔离库备份和表单截图。该目录被忽略，迁机需单独保存媒体和证据。

官方参考：[新版声音复刻](https://platform.qianwenai.com/docs/developer-guides/speech/voice-cloning)、[新版非实时配音](https://platform.qianwenai.com/docs/developer-guides/speech/tts)、[声音复刻 HTTP 协议](https://help.aliyun.com/zh/model-studio/voice-clone-design-http-api)、[CosyVoice HTTP 配音协议](https://help.aliyun.com/zh/model-studio/cosyvoice-tts-http-api)。
