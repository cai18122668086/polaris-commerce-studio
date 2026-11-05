# 视频空间 AI 接手交接

更新时间：2026 年 11 月 5 日，Asia/Shanghai。

## 新对话接手快照（最高优先级）

**2026-11-05 首次真人克隆试听：** 用户认可最新克隆弹窗样式，并明确要求用刚创建的声音生成短试听。已通过真实账号页面，对现有 ready 声音“测试”点击一次“生成试听”，preview_status 已 ready、MP3 缓存落盘且页面已播放。试听文案为“你好，这是我的专属声音。用自然的表达，讲好每一个故事。”后续复用这份缓存，不重复合成；相似度和听感仍由用户评价，未生成克隆视频。证据 `outputs/video-studio/clone-preview-20261105/`，此段覆盖下文旧的 not_created/未试听结论。

**2026-11-05 克隆弹窗视觉修正：** 用户指出上一张预览底部的“重新演示 / 模拟完成 / 模拟结果待确认”原生灰按钮及重复长提示难看。已移除预览演示控件，预览直接复用正式 Dialog、按钮和进度组件。正式克隆弹窗也统一为紧凑白底、淡紫上传区、细进度条与黑色操作按钮，移除渐变框、四步圆点和重复说明；列表使用紧凑进度。用户确认本次仅针对新增进度与克隆弹窗，不扩展调整数字人选择或整体编辑器。桌面及 390×844 窄屏检查通过，无页面横向溢出，临时 viewport 已恢复；typecheck、相关 ESLint 通过。本轮只调整前端，不创建声音/试听/视频。证据 `outputs/video-studio/clone-ui-polish-20261105/`；进度截图仍是界面模拟，不能当作实际任务进度。

**2026-11-05 客户界面与进度反馈增量：** 用户要求收起供应商和成本信息，已移除克隆/视频确认/作品预览中的上游名称及成本，停止前端查询供应商报价；客户响应和新导出清单不再包含成本回执、渠道和配音模型，完整记录保留后端。上传采用实际字节进度，创建/试听按用户要求使用预估曲线：快速接近 90% 后放缓，最高 98%，仅真实 ready 才到 100%；有阶段、等待时长、慢处理提示、失败/未知结果恢复。processing 自动查询原声音，不自动重建。60 项后端、21 项前端测试及类型/ESLint/Ruff/构建通过，证据 `outputs/video-studio/voice-progress-20261105/`。用户本轮自行上传后，本机已有 1 条 ready 专属声音，试听仍 not_created；未听评，也没有克隆成片验收。保留该记录及录音，不重复创建或生成。

**2026-11-05 页面反复“暂不可用”修复：** 原访问 Hook 在 focus/pageshow/可见性切换时先清空授权，Gate 把请求等待误作拒绝并卸载编辑器。现已区分初次等待、后台复核、临时连接错误和明确拒绝；同一页面复核保留已验证身份及编辑器，合并在途请求，退出/账号切换/路由变化清除旧身份并忽略迟到响应。未缓存跨会话权限，业务接口继续逐请求鉴权。新增 9 项访问状态回归，与原持久化 7 项共 16 项通过；typecheck、相关 ESLint、生产构建通过。本机 3003 已重启并确认系统声音、我的声音及克隆表单可打开。证据 `outputs/video-studio/access-stability-20261105/`。未触发配音、试听合成或视频生成。

**2026-11-05 声音克隆接入增量：** 用户已授权实施 CosyVoice 3.5 Flash。后端私有音色/上传/授权/状态/试听缓存及克隆配音接入、前端真实流程已实现，66 项后端回归及前端检查/构建通过；新版千问平台凭据已安全配置，只读查询成功。接入时尚无录音；此后用户已自行创建声音，现状以上一段为准。详见 [CosyVoice 最新交接](video-studio-cosyvoice-handoff-2026-11-05.md)。本段优先于下文历史占位说明。

用户本次只要求总结并移交到新的对话窗口，没有要求继续实施、付费测试、提交或上线。本节与下面两轮最新增量一起作为当前事实；更下方正文包含历史状态，不要把其中“未接 TTS”“未完成真实登录”“没有交接接口”等旧结论当作现状。

### 已完成、可复用

- 核心口播链路：公开抖音语音原文提取 / 需求创作文案 → 规划与二创 → 明确采用、原文校对、确认版本 → Tao 或泉语配音 / 上传音频 → 实测音频时长与正向动作模板铺满 → 泉语对口型 → 成片预览、下载及剪辑材料 ZIP。提取、AI 文案、TTS 与视频各有真实供应商成功证据；不声称任意平台链接都支持。
- 327 个官方 MiniMax 系统音色（24 个语言分组），各生成一次对应语言固定短句并缓存。用户已明确同意此方案；样片不是官方现成样片。保留 6 个旧泉语音色，共 333 个；旧 6 条尚无固定试听。327 份缓存全部可复用，不要再次批量生成。
- 自然及 7 种指定情绪、语速、语言自动识别/手动指定，生成时冻结精确稿件和配音设置。自动识别表示按稿件发音，不包含翻译或自动更换音色。
- 草稿、文案版本、任务、失败阶段和未知付费结果保护、原任务恢复、费用回执及阶段耗时；同一次请求幂等。Tao 单任务当前只显示估算，不能把聚合用量或估算当成每条实际账单。
- 唯一灰度邮箱已完成真实登录、保存、刷新恢复、缓存试听、真实口播生成、ZIP 导出、退出访问拦截、再次登录恢复。使用原有线上认证和本机独立业务验收库，没有伪造身份或改写主库用户。
- 前端用户已认可当前方向：数字人/音色弹窗组件布局尽量参考必火，配色/动效参考 PiccoPilot；数字人四列分页、完整人物与柔焦背景，音色三列、组合筛选和缓存试听，共用来源标签与底部操作区。模板前景不裁剪，窄屏和键盘交互已检查。
- 剪辑材料和服务接口已实现：不可变确认稿、原配音、无字幕口播、哈希、限时 Bearer 下载、撤销和幂等状态回调。文档与客户端已准备；外部剪辑本身尚未联调。

### 明确未完成

1. **声音克隆真实验收**：CosyVoice 3.5 Flash 业务接口与前端已实现，已配置新版千问凭据。用户自行上传后已有 1 条 ready 声音，短试听已生成、缓存并播放；相似度听评及克隆声音到成片待做，不要重复创建或合成试听。假供应商自动化不能代替真人听评。旧 Tao 克隆路径 404 不再是本次方案的接入依据。
2. **真人视频形象克隆**：`avatar-clone` 同样只有本地流程，未上传也未创建用户专属数字人。公共数字人和预置原创形象的 H3 动作制作/审核/登记已接通，不等于“用户上传自己的视频克隆自己”已接通。
3. **智能剪辑和字幕**：剪辑由另一位同事负责。实际音文对齐、字幕渲染、外部剪辑任务创建、最终成片回收/验证/入作品仍待双方联调。当前 `result_ready` 只是登记外部引用，不是已回收和验证的最终成片。
4. **用户侧视频计费**：现有代码记录供应商用量和费用，视频生成与文案辅助尚未接入用户积分预扣、成功结算、失败释放及完整对账；Tao 单条任务的最终实扣也未取得。供应商扣费保护不等于站内商业计费已完成。
5. **生产上线与剩余真实验收**：没有部署。正式认证配置、生产数据库迁移、任务执行与存储检查仍待做；本机为 BackgroundTasks 加持久阶段，不是已验收的生产分布式任务系统。真实跨设备、会话自然到期刷新、生产域 Cookie/代理及真实 PostgreSQL 未验收。正常页面刷新恢复已经验收，不能混称 token 到期刷新。
6. **小项**：原文逐字差异高亮、旧 6 条泉语固定试听，以及后续声音/情绪听感人工评估。公开音色名称中性别不明确者继续标为未知，不能凭外观或猜测补造官方元数据。

以上是剩余范围说明，优先顺序由用户在新窗口指定；不要擅自扩展实现同事负责的剪辑。

### 新窗口入口与运行状态

- 工作区 `C:/Users/a1726/Desktop/cyh/tengli/polaris-commerce-studio`，当前 PowerShell；实际路径可能映射到 D:。大量 modified / untracked 是本项目的现有成果，不能 reset、clean、覆盖或丢弃。当前未提交、未推送。
- 本次交接核查监听：前端 3003（PID 23028），后端 8013（PID 18652）；进程号会变化，接手时重新确认，只处理自己启动的验收进程。原主站 3000/8000 及先前验收端口不要混用或停止。
- 当前预览 `http://localhost:3003/video-studio`；真实账号项目 `b3430e7c-99e8-4b99-a938-f5f0c368abb4`，已完成任务 `3eb3216d-a088-42cc-b352-dd2c1c5d42a3`（约 4.98 秒、1080×1920）。优先查看现成成片，不要再点付费生成。
- 后端启动：仓库根目录设进程级 `PYTHONPATH=backend`，运行 `.venv/Scripts/python.exe tools/video_account_gateway.py`。前端启动：`node outputs/video-studio/real-account-20261105/frontend.mjs`。该 launcher 用进程环境将 API 设为同源代理到 8013，保持 external 认证，不改主站 `.env.local`。
- 网关 `tools/video_account_gateway.py` 只作本机验收：固定 HTTPS 上游认证，每个受保护请求核查真实已验证用户；绑定 127.0.0.1。不是生产认证替代方案。用户密码/验证码只在正常登录页面输入，缺会话时通知用户，不读取或导出浏览器 Cookie。
- 唯一允许的已验证邮箱仍为 `1474953130@qq.com`；保留灰度，不改开发账号为白名单、不伪造用户 Header，不修改主库身份。密钥只在忽略的 backend/.env 安全配置中，禁止打印、复制进聊天、前端或交接包。
- 迁移增量 0035–0038、OpenAPI 与生成类型均在工作区；0038 已实际执行 SQLite 迁移和生成 PostgreSQL 离线 SQL，未执行生产迁移。构建会影响共用 Vinext 开发缓存；如开发预览异常，完成构建后只重启自己的验收前端并重新检查，别改认证来绕过。

### 证据与阅读顺序

1. 本文件最高优先级快照及后面最新增量。
2. `docs/video-studio-tts-api-handoff-2026-11-05.md`：音色、固定试听、配音参数与计费历史。
3. `docs/video-studio-editing-api-v1.md`：剪辑端完整协议；客户端 `tools/fetch_video_editing_handoff.py`。
4. `outputs/video-studio/real-account-20261105/`：真实账号、原任务、确认稿、ZIP 哈希、登录/退出等证据。
5. `outputs/video-studio/frontend-polish-20261105/`：最新两类弹窗桌面/窄屏截图、构建、类型检查、ESLint、7 项持久化测试和 verification.json。
6. `outputs/video-studio/tts-catalog-20261105/` 与 `backend/.data/video-studio/voice-previews/speech-2.8-turbo/`：前次 TTS 真实链路与 327 条缓存。媒体与 outputs 都被 Git 忽略，迁机需单独复制；密钥另行安全配置。

已通过的视频/网关后端 94 项、剪辑下载客户端另 3 项、原认证配置另 17 项；更新后的交接模块已针对性复验。最新前端持久化 7 项、typecheck、相关 ESLint、生产构建通过。假供应商自动化与真实账号任务的验收范围分开记录；不重复重跑没有改动的昂贵链路。

给新窗口的启动说明：

> 请在 `C:/Users/a1726/Desktop/cyh/tengli/polaris-commerce-studio` 继续视频空间任务。先读 `docs/video-studio-ai-handoff-2026-11-05.md` 顶部“新对话接手快照”，再读配音交接和剪辑接口文档，保留所有未提交成果及本地媒体。核心口播、327 条缓存试听和真实账号本机验收已完成，最新界面方向已认可。剩余重点是声音克隆、真人形象克隆、视频用户积分计费、剪辑同事联调及生产验收。克隆目前只是界面，剪辑回调只登记引用。保持现有灰度和界面方向，不上线、不推送、不改主库身份、不自动重跑付费样片；需要登录时让我在页面操作。先核对当前状态，再按我指定的下一项推进，不自动创建目标或新对话。

## 前端细节第二轮（最新）

用户要求继续对齐必火组件布局与 PiccoPilot 配色/动效。本轮仅改前端组件及样式，没有再次付费生成、变更认证、数据库结构或部署。

- 新增 `components/video-studio/avatar-picker.tsx`，选择弹窗桌面四列、每页 12 项；即时搜索与分页切换重置列表滚动位置。卡片采用必火式横向柔焦背景，中间用 contain 展示完整原图；背景裁剪仅用于装饰，不裁剪前景人物。首页原有竖版卡片和编辑器完整适配保持。展示名称移除技术性 sit_body/whole_body 后缀，真实 ID/名称未改。
- 音色弹窗桌面三列紧凑布局，性别、关键词搜索、语言同排；窄屏调整为单列。试听点击区扩大，支持播放状态提示；来源切换停止试听；空结果可重置筛选，搜索可清空。
- 复用 `PickerTabs`、`PickerFooter`，新增独立 `selection-controls.module.css`；浅紫白底、黄绿色选中提示、黑色确认按钮、轻抬升/切换动效，并支持 reduced-motion。移除上轮主 CSS 中被替代的音色选择样式。
- 数字人动作预览在原选择弹窗上打开，关闭或 Escape 仅返回原筛选列表；已修正嵌套 dialog 的事件传播。来源标签支持左右方向键、Home/End，保留原生弹窗焦点约束。
- 桌面与 390px、320px 窄屏已检查；两类弹窗底部操作栏均可见，无内部水平溢出。已验证数字人分页/搜索/预览返回、音色语言性别组合筛选/搜索/空结果/缓存试听/取消不修改原音色。证据在 `outputs/video-studio/frontend-polish-20261105/`。
- typecheck、相关 ESLint、前端持久化 7 项通过；生产构建通过，记录在该目录的 `build.log`。未重复跑未受影响的后端与付费链路。

## 最新增量：真实账号验收、参考站界面与剪辑 API

此节优先于下方历史记录。用户已授权继续开发和真实账号验收，并在必火参考站、极光商绘验收站亲自完成登录。仍未提交、推送、上线、扩大灰度或修改生产数据库。

### 真实账号完成的链路

- 验收入口 `http://localhost:3003`，后端 `127.0.0.1:8013`。独立数据目录 `outputs/video-studio/real-account-20261105/`，主站 3000/8000 与先前 3002/8012 未替换。
- 本机缺少 SuperTokens Core 连接配置，因此新增本机专用 `tools/video_account_gateway.py`。正常登录请求通过固定 HTTPS 上游 `https://www.tengliapi.xyz` 的认证接口；每条本地受保护请求都用原 Cookie/Authorization 访问上游 `/api/v1/me` 核验真实且邮箱已验证的身份。没有使用测试认证或伪造白名单 Principal。Cookie 保留 Secure/HttpOnly/SameSite，仅收窄为本机 host；登录 POST 限制同源。该工具仅作本机验收，不是生产部署认证方案。
- 正常登录后账户页显示指定邮箱已验证；经本地 JIT 创建隔离库用户，其本地 user_id 与上游业务 user_id 不同。保存、刷新恢复、音色缓存试听、确认稿生成、真实 Tao 配音 → 泉语口型、成片预览和 ZIP 导出均通过。
- 新项目 `b3430e7c-99e8-4b99-a938-f5f0c368abb4`，唯一新生成任务 `3eb3216d-a088-42cc-b352-dd2c1c5d42a3`，已完成。确认稿为“你好，欢迎来到视频空间。用自然的声音，讲好每一个故事。”；温暖闺蜜、平静、语速 1.0、语言自动识别；成片 1080×1920、约 4.98 秒。不要重复提交付费生成。
- 已正常退出（上游 signout 200），再次直接访问原视频项目会返回登录页；用户再次亲自登录，原项目、设置和成片恢复。保留登录后的验收页面。
- 配音记录是 27 字、估算 0.00324 元，未取得本任务独立 Tao 最终账单；口型实扣回执 0.50 元。不将估算当作实扣。
- 证据：`real-generation-evidence.json`、`zip-verified.json`、`auth-audit.jsonl`、`verified-account.png`、`completed-result.png`、`logout-guard.png`。审计不保存密码、Cookie 或 token。下载 ZIP 位于本机 Downloads，同名任务归档含视频、配音、确认稿、manifest、阶段记录；确认稿逐字及哈希校验通过。

真实会话跨设备、自动 access-token 到期刷新、生产直连 Core/部署域 Cookie 和生产 PostgreSQL 尚未实测。页面刷新恢复已实测，不能将其写成“自动 token 刷新已验收”。

### 界面与模板裁剪

- 已查看登录后的必火数字人编辑器与声音弹窗；编辑器采用形象 / 文案配音 / 右侧工具区，声音弹窗采用我的声音/系统声音、性别分段、语言筛选、关键词搜索、可试听双列音色行和固定底部取消/应用。
- 已拆出 `studio-primitives.tsx`、`voice-picker.tsx`、`studio-intro.tsx`。保留真实持久化和试听逻辑；沿用缓存，未重新生成 327 份试听。6 条旧泉语音色没有固定样片时按钮禁用，不冒充已有试听。
- 视觉参考 PiccoPilot 的浅紫/粉到黄绿色渐变、网格、黑色按钮、强调色和卡片轻动效，支持 reduced-motion。没有复制参考站商标或私有图片。
- 用户指出模板裁剪过多，已把卡片从 4:4.7 的 cover 改为 9:16、contain；编辑器、作品缩略图、生成确认缩略图也完整适配。移除图片 hover 放大；不改变供应商原片。横向素材可有留边，避免人为截去身体。
- 模板弹窗的素材列表独立滚动，应用按钮保留在下方；右侧真实作品区修正为两列与独立刷新按钮。桌面 1440×960、窄屏 390×844 已检查，窄屏无水平页面溢出；临时 viewport 已恢复。
- `voice_gender` 只按官方音色名称/ID 中明确的性别词生成筛选标签；不明确者仍为未知，不声称官方接口提供了独立 gender 字段。
- UI 证据：`voice-picker.png`、`voice-picker-mobile.png`、`avatar-full-frame.png`、`editor-full-frame.png`、`studio-home.png`。

### 剪辑交接

正式协议见同目录 [video-studio-editing-api-v1.md](video-studio-editing-api-v1.md)，可直接给剪辑端同事。实现有用户端创建/状态/撤销交接，剪辑端 Bearer 限时 manifest/素材下载/幂等事件回调；精确绑定确认稿与音视频 SHA-256，过期、撤销和原成员失效都会拒绝访问。新增迁移 `20261105_0038_video_editing_handoffs`。服务端环境项 `POLARIS_VIDEO_EDITING_HANDOFF_SECRET` 已仅配置于忽略的本机 backend/.env，示例文件留空。

下载校验参考客户端为 `tools/fetch_video_editing_handoff.py`。不将用户 Cookie、供应商密钥或服务端签名密钥交给剪辑端；token 不放 URL/日志。

目前 `result_ready` 仅登记外部结果引用，并不拉取或验证剪辑成片。外部任务创建适配、字幕对齐、实际剪辑、最终视频回收仍待双方联调；前端继续显示即将上线。

### 本轮检查与继续运行

相关视频与网关后端 94 个测试通过，另新增剪辑下载客户端 3 个测试通过；最后对更新的交接模块复验 3 项通过。原外部认证与配置 17 项另行通过。前端持久化 7 项、typecheck、相关 ESLint、Ruff 和生产构建通过；日志位于本轮证据目录。0038 迁移在内存 SQLite 实际执行通过，另生成 PostgreSQL 离线 SQL，未连接生产 PostgreSQL。当前后端 readiness 200，匿名和伪造用户 Header 访问均为 401；ZIP 内音视频与最新 manifest 的哈希一致。不要把自动化假供应商样本与上面的真实账号任务混称。

启动本机验收后端：根目录设置进程级 `PYTHONPATH=backend` 后运行 `.venv/Scripts/python.exe tools/video_account_gateway.py`；前端运行 `node outputs/video-studio/real-account-20261105/frontend.mjs`。前端 launcher 使用实际空字符串覆盖 API base，保证 `/api` 同源代理到 8013，认证模式 external。主站 `.env.local` 不变。必要媒体和 launcher 在忽略目录，移交机器时单独复制，密钥另行安全配置。

## 2026-11-05 续接开发与验收（优先于下方历史记录）

用户本轮已明确要求继续完成链路，并确认所有音色各生成一次固定短句、缓存后反复试听；随后补充 Tao 密钥额度。已完成本地开发与下列验证，没有提交、推送、部署、扩大灰度或改写主库身份。

- 已从 MiniMax 官方中文公开表导入 327 个系统音色、24 个语言分组，源地址和获取日期保存在 `backend/app/data/minimax-system-voices.json`。全部 327 条固定试听使用 Speech 2.8 Turbo 成功生成并实际解码；音频哈希均不同。样片由我们生成，不是官方预制音频。中文短句为“你好，欢迎试听我的声音。用自然的表达，讲好每一个故事。”，其他音色采用所属语言的同义短句。
- `video_voice_catalog.py` 维护音色、情绪和语言；`video_tts.py` 是独立 Tao 适配器。保留原 QuanYu 音色，供应商音色 ID 不混用。服务端新增 `POLARIS_VIDEO_TAO_TTS_ENABLED`、`POLARIS_TAO_API_KEY`、`POLARIS_VIDEO_TAO_TTS_MODEL`；本机忽略的 `.env` 已配置并启用 Tao，示例仍为空密钥、默认关闭。不要打印或复制实际密钥。
- 页面已接通音色搜索、语言筛选、固定样片试听、情绪及语言选择。情绪为自然（自动）及平静、愉快、悲伤、愤怒、害怕、厌恶、惊讶。7 种指定情绪均完成真实短配音请求和解码；这不等于人工逐项听感评分。默认 `language_boost=auto`；模型按文案语言发音，翻译与自动更换音色不属于此选项。未引入 whisper/fluent。官方表不提供统一性别字段，未确定的声音不伪造性别。
- 新任务冻结供应商、模型、音色、情绪、语言和语速。Tao 音频先落盘，再上传到现有对口型链路；上传失败后复用成功音频。付费响应未知仍禁止自动重新提交。`backend/scripts/prepare_voice_previews.py` 默认仅显示计划，`--generate` 才付费；每个音色提交前独占写入 intent，未知结果不自动重试。327 条缓存全部就绪后再次执行，新增用量为 0。
- 站内新增“原文校对”：参考原文只读保留、当前配音稿独立修改、保存留版本，生成确认可展开精确稿件。当前提供是否不同的提示，尚无逐字差异高亮。原文提取质量仍需用户校对，不自动悄悄改 ASR 错字。
- 新增提取/规划及生成阶段的持久开始结束记录和耗时；失败保留对应阶段与原因，恢复保留历史尝试。旧任务不补造历史计时。作品预览可查确认稿、配音设置、生成耗时和费用。QuanYu 返回的金额是回执；Tao 任务暂标估算、实际金额待核对，不把字数估算当成实扣。
- 新增鉴权 GET `/generation-tasks/{job_id}/handoff` 导出 ZIP，包含精确确认稿、最终音频、无字幕口播原片、manifest 和阶段历史。manifest 含项目/任务/确认版本、稿件哈希、实测时长、媒体尺寸/帧率/MIME、去重键和 `pending_alignment` 字幕状态；纯上传音频没有确认稿时为 `transcription_required`。不复用参考视频时间戳。下载仍经原灰度和用户/工作区鉴权，临时 ZIP 响应后清理。剪辑服务提交、回调、服务间授权和成片回传仍待双方联调，未自动向同事发送任何材料或密钥。

### 本轮真实证据与费用

证据目录 `outputs/video-studio/tts-catalog-20261105/`，受 Git 忽略。主缓存位于 `backend/.data/video-studio/voice-previews/speech-2.8-turbo/`，迁机时需另行复制。

通过 CUA 在独立验收网站完成：打开受控短稿、在校对框把“固事”明确改为“故事”、保存、试听温暖闺蜜、选择愉快情绪与语言自动、核对确认稿、确认生成、预览并下载剪辑包。没有拦截业务请求或站外改写提交稿。身份和数据库为隔离夹具，Tao 与 QuanYu 业务供应商均真实。

- 项目 `a3367cfd-c7f3-4f69-8644-e595c05c2d1b`，任务 `617a2e6a-34d1-4e55-9ba3-efed0c0f1bac`。
- 最终音频实测 5.584438 秒，成片约 5.58 秒、1080×1920、25 fps，视频音轨完整解码通过。使用已有公共数字人，未调用 H3、未重新生成原创模板。
- 编辑器、确认快照和导出稿逐字一致；原始错字稿独立保留。重启验收后端后仍是同一条 completed 任务、无额外生成；新导出包的媒体格式也已检查。
- 可查 `acceptance-report.json`、`preview-summary.json`、`completed-job.json`、`project-after.json`、`editing-manifest.json`、`editing-handoff.zip`、`talking-head.mp4`、`narration.mp3`，以及 `proofread.png`、`voice-selection.png`、`confirmation.png`、`completed-preview.png`。
- Tao 此轮用量由 7425 增至 1148745，以每元 500000 配额换算，实际 **2.28264 元**，包含 327 份音色试听、7 份情绪短测和 1 份站内配音。对口型另有 **0.50 元**实际回执。本次 Tao 单任务仍显示估算，聚合实扣证据不能冒充每条任务独立账单。
- 相关后端检查本轮共覆盖 75 个不同测试：前次 65 项通过，新增 10 项通过；最后对受影响模块复验 58 项通过。前端持久化 7 项、typecheck、相关 ESLint、Ruff 通过；生产构建日志为 `build-final.log`。

### 仍未完成的外部验收

主站本地 3000/8000 仍为开发认证，实际打开视频空间被灰度门禁拦截；本机未提供外部认证配置，未改成白名单身份。指定邮箱的真实正常登录、跨设备真实会话与生产环境仍未验收。剪辑端字幕音文对齐、提交回调和成片回传也未联调。不得将本轮隔离身份测试称为这些事项完成。

当前新增验收前端为 `http://localhost:3002`，后端 8012，均只用于隔离验收。启动文件位于证据目录，前端 launcher 用独立进程环境覆盖 API 地址，不改主站 `.env.local`。该服务器的 lipsync intent 已存在，勿删除或再点新生成；已有项目和成片可直接预览。原 3000/8000、3001/8011 保留。以下正文为本轮前的历史交接，涉及“尚未接入”“尚未生成试听”“无交接包”时以上述增量为准。

接收方是下一个 AI 对话窗口。用户要继续推进现有网站的口播生成工作，并保持原界面与灰度限制。剪辑由另一位同事负责，我们负责采集与文案、声音、数字人生成及后续交接。当前主链路已接入并真实跑通，仍未上线。本轮仅整理交接文档，没有新增开发、付费调用或部署。

## 接手先做什么

1. 阅读本文，再检查工作区变更与监听端口。保留所有已有未提交代码、测试证据和媒体文件。
2. 向用户简述当前状态与下一步。如果用户要求继续，优先做真实灰度账号验收和站内原文校对，不要重新开始 H3 或重复付费生成样片。
3. 明确区分已完成、尚未验收和拟议功能。本文优先于旧交接文件中的历史状态。

用户最近只要求写一份供下一窗口接手的交接文档，没有要求本轮实施剩余开发。目标模式曾在前序工作中使用并结束；本轮查询目标工具返回 `goal: null`，没有活动目标。除非用户明确要求，不要自动新建目标。

## 工作区与不可改变的约束

仓库绝对路径：`C:/Users/a1726/Desktop/cyh/tengli/polaris-commerce-studio`。Windows 实际解析路径也可能显示为 `D:/Desktop/cyh/tengli/polaris-commerce-studio`，是当前工作区的映射。环境为 PowerShell，仓库根目录有 `.venv/Scripts/python.exe`，不要寻找不存在的 `backend/.venv`。

当前分支为 `main`，核查时 HEAD 为 `22fc356`。代码有大量未提交的 modified 和 untracked 文件，包含此前已授权的全部视频功能；不能 reset、clean 或丢弃。未经后续明确要求，不提交、推送或部署。

- 保持目前页面布局、导航和灰度限制。唯一允许的已验证邮箱为 `1474953130@qq.com`，后端以可信认证主体为准。
- 不要把开发用户邮箱改成白名单，不要通过前端参数、伪造请求头或主库身份修改绕过灰度。
- 主库用户和工作区没有为测试改写。真实生成测试使用隔离数据库和测试认证身份。
- 用户最初限制付费调用，后续已明确授权公共数字人、H3 模板、TTS、对口型及提取和规划的真实接入与测试；不要只依据旧文档误判为从未授权。授权不等于接手后应自动重跑付费测试，先复用现有证据并核对任务状态。
- H3 必须使用 `Minimax-H3-768p-913`。公共数字人直接入库使用，不经过 H3。
- 密钥已在忽略的 `backend/.env` 中配置。不要在文档、聊天、前端、日志或提交里复制密钥；也不要整份打印该文件。
- 用户指出过站外手工改稿破坏验收链路。验收必须通过产品流程，不得悄悄修正系统输出后声称自动成功。
- 剪辑由同事负责。不要擅自实现智能剪辑、分镜编排或字幕渲染；我们应约定交接材料与接口。

## 已完成的业务流程

项目持久化已接入后端：项目草稿、产品事实、参考来源、文案版本、确认版本、媒体关联和任务均按用户与工作区隔离。版本冲突不覆盖，变更和任务有持久 request_id 及摘要，同一提交重放避免重复任务。换设备恢复与异常场景有测试，但真实指定邮箱的交互登录验收尚未完成。

文案流程已接通：公开抖音链接提取语音原文，或直接输入需求；规划服务生成首稿、依据产品事实二创；用户明确采用后进入编辑器，确认生成时冻结本次稿件。提取保存真实分句时间，发布标题不冒充语音全文。当前仅公开抖音链路有验收，不声称所有平台均支持。

生成流程已接通：文本驱动先 TTS，也可上传 MP3、WAV、M4A；后端测量最终音频实际时长，准备足够长的动作模板，提交对口型，轮询并下载结果。用户可从作品预览与下载。TTS 返回过 `duration: 0`，业务以实际解码测量为准。

数字人库当前为 46 个 active/public/video 公共数字人和 1 位原创形象清禾。公共封面由对应视频提取，不使用无关图库照片。原创图来自内置图像生成功能，再通过 913 制作动作底片，预览验收后登记。

规划 API 已配置并启用：`https://api.tengliapi.xyz`，模型 `gpt-5.6-sol`。网站的文案助手和文案二创都已连接真实任务接口。首稿和二创有真实供应商成功回执与 usage，随后接 TTS、对口型生成过约 40 秒视频。规划配置与图片业务隔离。当前规划用于文案层，未包含剪辑分镜或素材编排。

## 关键代码与数据位置

前端主要文件：

- `components/video-studio/video-studio.tsx` 和相邻 CSS：现有视频界面、真实任务、文案采用、生成确认和预览。
- `features/video-studio/library.ts`：资产库、生成任务、价格、上传、恢复及模板验收。
- `features/video-studio/assistance.ts`：文案与提取任务、轮询、未知响应恢复。
- `features/video-studio/projects.ts`、`project-session.ts`、`use-project-session.ts`：服务端持久化、串行保存、待重试请求、冲突和身份隔离。
- `app/video-studio/`：各页面和灰度入口；导航及认证还有相关既有变更，不能只保留新目录。

后端主要文件：

- `video_studio_access.py`：统一可信邮箱门禁。
- `video_studio_models.py`、`video_studio_schemas.py`、`video_studio_routes.py`：项目、版本、参考内容和权限。
- `video_assistance.py`、`video_assistance_models.py`、`video_assistance_provider.py`：规划、二创、EveryInfra 异步提取、幂等和来源快照。
- `video_generation.py`、`video_generation_models.py`：资产、TTS、模板审核、对口型、阶段和回执。
- `video_generation_media.py`：口型提交前的音频测量与模板准备，支持中断后复用已成功步骤。
- `video_template_media.py`：实际解码计时、正向循环与整帧长度准备。
- `video_providers.py`：服务器端供应商调用、上传、受限媒体下载；付费 POST 不自动重试。
- `config.py`、`main.py`、`routes_v1.py`、`schemas_v1.py` 以及迁移注册有集成改动。

迁移依次为 `20261104_0035_video_projects.py`、`20261104_0036_video_generation.py`、`20261105_0037_video_assistance.py`，接原 0034，仅追加表，拒绝破坏性回滚。SQLite 已运行验证，PostgreSQL 仅离线 DDL 编译验证，不能称已在真实 PostgreSQL 执行。

契约文件为 `docs/openapi-v1.json`、`lib/api/generated/openapi.d.ts`。历史长文为 `docs/video-studio-handoff-2026-11-04.md`，其中混有早期状态；以本文和源代码为准。

## 接口与配置

业务基础路径为 `/api/v1/video-studio/workspaces/{workspace_id}`，需通过原认证、可信灰度及工作区权限，不是匿名外链接口。

- 项目：GET `/projects`、GET/PUT `/projects/{project_id}`。
- 版本：GET `/versions?project_id=...&kind=confirmed`，实际生成的确认版本应以任务的 `confirmed_version_id` 精确匹配，不能随手取最新草稿。
- 文案与提取：POST/GET `/assistance-tasks`，POST `/assistance-tasks/{task_id}/resume`。
- 资产与生成：GET `/avatars`、`/voices`、`/generation-prices`，POST `/audio-files`，POST/GET `/generation-tasks`。
- 任务恢复：POST `/generation-tasks/{job_id}/resume`；H3 另有 approve-template 和 reject-template。
- 已完成媒体：GET `/generation-tasks/{job_id}/video`、`/audio`，必须使用后端实际返回 URL 并经过授权。

当前任务详情通过列表获取。没有独立的剪辑提交、剪辑回调、字幕导出或交接包导出接口；不要在下一步方案里把拟议接口当成已经实现。

任务响应包含 `status`、`stage`、`error_code`、`can_resume`、确认版本 ID、快照、billing、音频实测时长和模板准备信息。`snapshot.draft.text` 是本次实际生成稿；后续编辑当前项目不会改写已确认快照。

当前本地真实配置启用视频供应商、规划和提取，具体服务器变量包括 `POLARIS_VIDEO_PROVIDERS_ENABLED`、`POLARIS_VIDEO_SCRIPT_PLANNING_ENABLED`、`POLARIS_VIDEO_SCRIPT_API_KEY`、`POLARIS_VIDEO_SCRIPT_BASE_URL`、`POLARIS_VIDEO_SCRIPT_MODEL`、`POLARIS_VIDEO_EXTRACT_ENABLED`、`POLARIS_VIDEO_EXTRACT_API_KEY`，以及 QuanYu、Wuye 对应 key。示例环境文件保留空 key 和默认关闭，不要把示例当成当前运行配置。

供应商约定：QuanYu 使用 `X-API-Key`，TTS 声音字段为 `cloud_voice_id`，例如字符串 `"1"`；H3 使用 Bearer 和指定 913；EveryInfra 使用 Bearer，`https://api.everyinfra.com/api/v1/social` 异步提交 douyin/transcript，再 GET jobs 查询；规划使用单独的 OpenAI 兼容 `/v1/chat/completions` 路线。完整实现以适配器为准，后续服务契约有变化需查官方资料。

## 原创模板与倒放问题

用户曾看到胸肩快速起伏。此前定位到 H3 源动作较急促，以及短模板被后续供应商正倒放延长。不能单靠提示词宣称解决供应商倒放。

V2 提示词约束胸肩、头部和躯干稳定，手势集中于前臂，低幅度、缓慢回位，开头结尾保持中性姿态。正式默认提示词在 `video_generation.py` 的 `H3_PROMPT`。

正式流程先根据最终音频测量时长：原片够长则直接复用；不足则制作全程正向周期，尾头约 0.25 秒叠化，流式循环至向上取整的整帧长度，上传并登记派生模型，再提交口型。不能把此步骤改回让供应商自行扩展短片。

原始 V2 底片 15 秒在 `backend/.data/video-studio/self-owned/presenter-female-template-913-v2-stable.mp4`。当前库默认已登记 60 秒正向 V2，model_id 为 **934**，本地 avatar_id 仍是 `self-presenter-female-v1`。manifest 为同目录 `registered-template.json`。933 为历史 V1 备份；932 人物不一致已排除；803 仅诊断，不得拿来生成清禾。

生产准备代码与 CLI 共用 `video_template_media.py`；`tools/prepare_video_forward_loop.py` 是包装，`tools/check_video_motion_order.py` 用于时序证据。动态采样支持正向顺序结论，不保证每帧完美或完全不可见接缝。长时长只有有限样本验证，不得承诺无限时长；仍有 50 MB 音频、200 MB 下载和单媒体处理 600 秒等限制。

## 最重要的有效验收证据

### 用户洗洁精视频的原文链路

用户提供的原始地址是带 `modal_id=7679330733021859091` 的抖音搜索链接。代码从该参数标准化到 `https://www.douyin.com/video/7679330733021859091`。用户明确要求直接用原口播稿，不做二创。

最初提取后在站外手工校对了 ASR 错字并提交生成，用户指出这破坏验证链路。那份 `outputs/video-studio/user-douyin-7679330733021859091/` 和 `user-douyin-original-script.mp4` 仅作人工校对对照，已标记排除，不能再作为自动链路验收成功证据，也不要删除历史任务或回执。

随后补了网站内“使用原文”，真正通过 CUA 界面完成：粘贴原始链接、自动提取、点击使用原文、选择清禾与温柔女声、点击确认生成；中间没有编辑原文或拦截业务请求。

- 有效成片：`outputs/video-studio/website-user-douyin-raw.mp4`，48.48 秒、768×1366、24fps，完整视频与音轨解码通过。
- 证据目录：`outputs/video-studio/website-user-douyin-raw/`，含 acceptance-report、ui-text-evidence、extraction-job、confirmed-version、generation-job、media-check、website-preview 和请求回执。
- 项目 ID：`2f910636-babb-43bf-b281-32e72aa8ca59`；生成任务 ID：`5845ae14-bf0f-4e80-a2ac-577284fecf56`。
- 272 字原文在供应商结果、网站提取 API、原文框、编辑器、保存稿、确认版本、生成快照、实际 TTS 请求 8 个检查点逐字一致。
- UTF-8 SHA256：`9dcf0588b62d728942a07c6d8a75f5ba5aaee4a8a71575e0b4e53303907b86c0`。
- 刷新后恢复同一项目与任务，原文未变，没有额外重复生成。业务供应商真实调用；仅认证身份、数据库为隔离测试，不能称真实指定邮箱登录已验收。
- 实测音频 48.4755 秒，复用 60 秒 934，无需再次延长。没有新 H3 或规划改写调用。
- 回执：TTS ¥0.136，对口型 ¥0.50，提取约 ¥0.004。H3 ¥0.90 是该模型此前官网标价，不属于本条新增费用。

本条只证明原文生成链路通畅，不代表原文质量通过。提取中仍有“火力28”“旗舰链”“去无”等错误。不能在验收前偷偷修正；日常产品使用应增加明确的站内校对与确认。

本次耗时由回执与文件落盘时间估算：提取 39 秒，TTS 8.3 秒，音频与模板下载测量约 2.3 秒，对口型排队生成轮询约 1 分 46 秒，成片下载保存约 7.1 秒。确认生成到成片约 2 分 04 秒；系统处理合计约 2 分 43 秒，含界面核对操作整轮约 3 分 47 秒。尚无逐阶段持久计时历史，不能把这些近似值当成产品已具备完整计时功能。

### 其他已完成的真实验证

- `outputs/video-studio/authoring-live/`：真实提取、规划首稿、二创、采用、TTS、自动延长和口型的 API/worker 验收。首稿和二创 response 均返回 `gpt-5.6-sol`，usage 分别 559、818 tokens。成片 `authoring-to-lipsync-live.mp4` 约 40.12 秒。不是整套业务都经 CUA 操作，不能与上面的界面原文验收混称。
- `outputs/video-studio/formal-forward-live/`：上传真实 60 秒 WAV，15 秒 V2 底片按实际音频长度自动铺满、登记 935、口型和同请求重放。成片 `formal-forward-generation-60s.mp4`，无新 H3/TTS，口型扣费 ¥0.50。
- `outputs/video-studio/live-tests/stable-v2/`：913 胸肩稳定底片，复用此前严格 60 秒音频进行前后对照；成片 `owned-913-stable-v2-one-minute.mp4`。运动采样支持正向循环，没有 V1 持续倒序段。
- 还有 `public-lipsync-live-v1.mp4` 等公共模型测试。旧首轮一分钟测试使用过 atempo 加速到 60 秒，仅是历史对照；正式流程不加速音频凑一分钟，按实际音频时长铺模板。

## 字幕和剪辑的最新约定

剪辑由另一位同事负责。用户认为应直接把口播稿提交给剪辑，避免再次转录；已认可按此方向交接。

我们应交出实际用于 TTS 的确认稿、最终音频、无字幕口播原片，以及项目 ID、生成任务 ID、确认版本 ID、实际时长和媒体格式。当前还没有统一交接包导出或剪辑提交回调的实现，需要与同事约定并由相应责任方落地。

最近三次 TTS 回执均为 `subtitle_data: null`、`subtitle_file: ""`，即使请求设置了 `subtitle_enable: true`、`subtitle_type: "sentence"`。最终配音目前没有可交付的真实字幕时间戳。

提取参考视频的时间戳真实存在，洗洁精样本有 29 段，另一验收样本有 21 段，但属于参考视频音轨。新配音的速度与停顿不同，不能把这些直接作为新成片字幕时间。

剪辑端应以确认稿确定字幕文字，以最终音频做音文对齐，获得本次音频的起止时间；不必重新识别整篇文稿。仅上传音频且没有稿件的场景才需先识别。交接包应把字幕状态明确标记为待对齐；具体字段名、字幕格式、素材访问方式和回调地址尚未约定。

涉及改稿时应区分字幕显示修订与实际配音内容变更。字幕样式和排版可独立导出；实际配音稿变化应产生新的版本及音频、对应视频任务，不能篡改旧确认稿。不要承诺任意字幕改字都与已生成声音一致。

## 后续工作优先级

以下是向用户提出的下一步建议，不是已完成能力。用户本轮只要求交接，下一窗口按用户新的继续指令推进。

1. **真实灰度账号验收**：使用指定已验证账号检查登录、跨设备、刷新、失败恢复、权限撤销与用户隔离。测试夹具结果不能代替真实登录；若缺少会话需让用户完成正常登录，不能改主库身份绕过。
2. **站内原文校对**：原始转写、修改稿、确认稿分开留存，品牌、价格、规格等可核对；生成明确绑定确认版本，保留可追溯修改记录。现有版本保存不等于已完成完整的校对与差异审核界面。
3. **任务可观测性与费用**：补逐阶段开始结束时间、实际费用和失败原因的可查记录。已有 billing/阶段/恢复不等于已有完整耗时历史。付费结果未知必须核对，不盲目重新提交；已成功音频与供应商任务复用。
4. **与剪辑的交接约定**：输出字段、素材格式、授权下载/服务访问方式、过期策略、字幕待对齐标记、剪辑状态与成片回传、去重键。现有灰度用户接口不能直接当作服务间授权；不要扩大灰度或向同事发送供应商 key。
5. **固定样本质量与稳定性回归**：短中长稿、文字与上传驱动、公共与原创，关注胸肩稳定、正向循环、接缝、音画同步、断网/重启恢复和实际费用；优先利用已有样本，只对必要变化做受控真实调用。

上线前另需生产任务执行与存储检查。当前本地 BackgroundTasks 加持久阶段，不是生产分布式队列；15 分钟无心跳恢复与未知付费状态保护已做，但进程重启不等于自动完成所有任务。真实 PostgreSQL、生产代理、Cookie/跨域会话也未验收。声音克隆、真人样本克隆和更大的原创库不是当前收尾优先项。

## 当前本地运行状态

本轮核查时监听如下，接手时再次核实，PID 可能变化：

- 3000，PID 40460：原 Vinext 开发站点。
- 8000，PID 43808：原 `uvicorn app.main:app` 后端，从 backend 工作目录运行。开发身份没有视频灰度权限，access 返回 404 是正常限制，不是应绕过的故障。
- 3001，PID 50276：独立验收前端，同一代码，代理到 8011。
- 8011，PID 29212：`outputs/video-studio/website-user-douyin-raw/server.py`，隔离认证和 SQLite，业务供应商真实。付费 POST 有一次性 intent 文件保护。

应用浏览器此前保留了 3001 的该项目成片预览。此页面是测试身份预览，不能误认成主站真实用户会话。3001/8011 进程可能随环境结束退出，需要时先查端口，不要同时启动第二份。

不要为了继续查看视频直接重跑 `run.py generate`、`server.py` 的测试流程或真实 POST。若一次性 intent 已存在但状态不明，应查已有回执与 job_id；不能删除 intent 以绕过重复付费保护。

当前阶段仅为本地验证，没有部署、推送、域名修改。文档整理不应触发这些动作。

## 测试与复现

最近相关后端 94 项通过，日志 `outputs/video-studio/website-user-douyin-raw/pytest.log`；生产构建通过，日志同目录 `build.log`。typecheck、相关 ESLint、Ruff 和 `git diff --check` 通过。前序前端 33 项通过；灰度浏览器、持久化浏览器和文案浏览器回归均有报告，认证允许身份是夹具。

从仓库根运行后端回归：

```powershell
.venv/Scripts/python.exe -m pytest backend/tests/test_video_assistance.py backend/tests/test_video_forward_generation.py backend/tests/test_video_generation.py backend/tests/test_video_projects.py backend/tests/test_video_studio_access.py backend/tests/test_auth_external.py backend/tests/test_auth_config.py -q
npm run typecheck
npm exec eslint -- components/video-studio/video-studio.tsx
```

不要从 backend 目录运行旧 auth_config 测试：会读本地 `.env` 开发配置，曾导致生产配置测试提前失败；根目录运行已通过，不能为此弱化安全校验。

浏览器测试库在用户级 Python312；仓库 .venv 未直接安装 Playwright，已验证的命令如下，只借用用户级测试库：

```powershell
.venv/Scripts/python.exe -c "import sys,site,runpy; sys.path.append(site.getusersitepackages()); runpy.run_path('tools/verify_video_assistance.py',run_name='__main__')"
```

`verify_video_assistance.py` 使用真实 FastAPI/临时 SQLite、测试认证和假业务供应商，包含“使用原文”逐字保存、旧改写候选存在时仍采用原文、响应丢失恢复同一任务等回归，不是付费真实供应商验收。

其他脚本有 `verify_video_studio_access.py`、`verify_video_project_persistence.py`、`verify_video_library.py`。最后一个会访问供应商 GET/媒体，运行前读限制与费用，不要把 GET 一概视为供应商永远不收费。

真实测试目录和媒体均在 git 忽略范围 `outputs/`、`backend/.data/`。若交给其他机器的 AI，单独复制这些证据与必要本地媒体；仅复制 Markdown 或 Git 已跟踪文件不会包含它们。密钥另行安全配置，不随交接包发送。

## 接手验收纪律

- 不用手工干预隐藏流程断点，原文错字应如实暴露，产品校对需明确操作和留痕。
- 不把 API 测试、假供应商浏览器测试、真实供应商测试和真实账号界面测试混称。
- 不把当前草稿当成本条视频的实际确认稿，精确绑定任务确认版本。
- 不复用参考视频时间戳冒充新配音时间戳，不凭字数平均切出伪时间。
- 不把恢复按钮可点等同于可重跑所有付费步骤，以后端 can_resume 和已知供应商任务为准。
- 既有 94 项检查已过，下一轮只针对改动运行必要测试；没有新问题不反复重跑昂贵或耗时验证。
- 无需重做 Word/PDF。用户已明确交接对象为下一 AI 对话窗口，本文 Markdown 就是接手入口。

## 给下一窗口的启动提示

可以让下一窗口执行：

> 请先阅读仓库 `docs/video-studio-ai-handoff-2026-11-05.md`，核对当前未提交变更与运行状态，继续视频空间收尾工作。保持现有界面与唯一邮箱灰度，不上线，不自动重跑付费样片。剪辑由另一位同事负责；先按交接文档确认真实账号验收、站内原文校对、任务费用与阶段耗时、剪辑交接材料这几项的实际状态，再推进我指定的下一步。
