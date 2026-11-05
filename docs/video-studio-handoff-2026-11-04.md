# 视频空间实施与灰度交接

下一 AI 窗口请先读 [视频空间 AI 接手交接](video-studio-ai-handoff-2026-11-05.md)。该文件整理了截至 2026 年 11 月 5 日的当前状态、验收边界、运行方式与下一步，本文件保留历史实施记录。

更新日期：2026-11-05。当前阶段：本地界面、灰度门禁、第一阶段持久化，以及用户另行授权的公共数字人 / H3 原创模板 / TTS 对口型均已接入并实测，未发布上线。下方早期阶段“不接付费 API”记录为历史边界，以本节最新授权为准。

## 最新交接：真实数字人接入（更新至 2026-11-05）

2026-11-05 用户指定视频的原文链路纠正验收：此前在提取后手工校对 ASR 再提交生成，插入了站外人工步骤，该版只算对照，不能算网站自动链路验收。原控制记录在 `outputs/video-studio/user-douyin-7679330733021859091/`，已明确标记排除，原任务及扣费回执保留。此后通过 CUA 在独立本地页面 3001 操作，实际 HTTP 代理至隔离 API 8011/SQLite；只有外部登录身份使用测试夹具，业务供应商均真实调用，没有浏览器业务请求拦截、没有手工填入或修订稿件。原 3000/8000 灰度规则与用户数据没有改动，仍未实测真实 SuperTokens 登录。

本次从界面粘贴用户给出的抖音搜索链接（`modal_id=7679330733021859091`），网站自动标准化到选中的 `/video/7679330733021859091`，真实 EveryInfra 提取后点击新补充的“使用原文”，选择清禾及温柔女声，点击确认生成。原文框、编辑器只读检查，272 字原文的错别字与空格保持原样。供应商提取结果、网站提取 API、原文框、编辑器、服务端保存稿、不可变确认版本、生成快照、实际 TTS 请求 8 个检查点逐字一致，UTF-8 SHA256 均为 `9dcf0588b62d728942a07c6d8a75f5ba5aaee4a8a71575e0b4e53303907b86c0`。刷新页面恢复同一项目、原文与任务，没有追加付费提交。没有新 H3/改写调用；复用已验收的正向 60 秒模板 934，本次音频实测 48.4755 秒，无需再次延长。TTS 回执扣费 ¥0.136，对口型 ¥0.50，提取回执约 ¥0.004；不同服务币种换算以回执为准。

有效成片 `outputs/video-studio/website-user-douyin-raw.mp4`：48.48 秒、768×1366、24fps，视频及音轨完整解码通过，网站显示“已完成”并实际打开成片预览。证据 `outputs/video-studio/website-user-douyin-raw/acceptance-report.json`、`ui-text-evidence.json`、`media-check.json`、`website-preview.png`。这证明原文生成链路可走通，不代表提取准确率已通过，原文中的品牌等 ASR 错误仍可复现；下一步应先处理站内可追溯的原文核对，保留原始提取结果及明确修改记录，不能在站外悄悄纠正后声称自动成功。

本次增量：二创弹窗增加“使用原文”，存在旧改写候选时仍能明确采用原文；采用时保持原字符串，超过草稿 3000 字上限明确拒绝，不静默截断。提取结果上限与引用存储 6000 字契约一致。后端相关 94 项回归、原文采用浏览器回归（假供应商、0 付费）、typecheck、相关 ESLint/Ruff、生产构建均通过。构建/测试日志在上述验收目录；界面布局未调整，未部署。

2026-11-05 规划服务与参考语音转写已接通：用户另行激活目标，提供 `api.tengliapi.xyz` 规划服务并要求尽可能接通现有流程。已真实 GET 模型目录并验证 `gpt-5.6-sol` 的结构化中文文案调用；使用隔离的 `video_script_*` 配置，没有替换图片业务全局规划线路。EveryInfra Key 也已验证，读取实时目录/OpenAPI，并接入 douyin/transcript 异步能力，不把发布标题当语音全文。

新增 `video_assistance.py`、`video_assistance_provider.py`、`video_assistance_models.py` 和迁移 `20261105_0037`（接 0036，仅追加文案任务表，拒绝删除历史）。新接口 assistance-tasks 的 POST/GET/resume 全部继承可信邮箱灰度、工作区权限和 owner/project 隔离。每次任务保存产品事实/创作要求/参考原文/项目版本快照、模型输出、来源 URL/真实分句时间、usage/billing 和请求状态；request_id 持久幂等。规划 POST 不自动重试，结果未知禁止重投；提取已知 job_id 后仅免费 GET 轮询，超时可继续原任务，不重新付费采集。规划内容是候选稿，不自动修改项目；用户点采用后进入原保存/确认稿/生成流程。

前端沿用现有文案助手与二创弹窗，只替换“本地示例/待接入”逻辑为真实任务、结果恢复和采用操作，展示待核对事实提醒。支持当前公开抖音链接；暂不声称其他平台已验收。参考价格/规格仅作为原文保存，系统提示要求不得继承，另有数字单位事实检查；事实本身与语义质量仍须用户审核。输入/输出由 React 作为文本展示，不执行参考文案指令。原文与改写结果的 textarea 补充了明确可访问名称，未改变布局。

真实全链路已完成：公开口播样本 `https://www.douyin.com/video/7665385569308003647` → 166 字语音原文、21 个原视频分句时间 → 规划首稿 → 产品事实约束二创 → 测试中明确采用 → 正式 TTS → 实测 40.123438 秒音频 → 主流程自动正向铺满至 40.125 秒 → 口型 → 授权下载。成片 `outputs/video-studio/authoring-to-lipsync-live.mp4` 容器显示 40.12 秒、768×1366、24fps，完整解码通过，动态采样正向匹配率 1.0，音轨相似度 0.99953。此链路没有新 H3 调用；原 60 秒音频的自动铺满测试也已完成。规划“约一分钟”是篇幅目标，不是配音保证，实际音频时长决定模板长度，不用重复音频或强行加速凑时长。原视频的分句时间不能当成二创后新配音的字幕时间；新 TTS 未返回字幕时间，仍明确缺失。

实测身份、项目与记录位于隔离认证夹具数据库，供应商调用真实，未改主库用户；不是指定邮箱的真实登录验收。全链路回执/质量报告在 `outputs/video-studio/authoring-live/`，先前正式生成回执在 `formal-forward-live/`。新增文案后端 14 项（含 0037 SQLite 迁移与 PostgreSQL DDL 编译、幂等、未知结果不重投、提取恢复不重扣、事实检查、隔离和空转写）；连同既有视频/认证测试合计 89 项分批通过。浏览器 `tools/verify_video_assistance.py` 验证结果未采用不覆盖草稿、刷新恢复、二创与产品事实分离、提取入库、提交响应丢失恢复原任务；都是假供应商，0 次付费，0 浏览器错误。原持久化浏览器和灰度回归保留。OpenAPI/TypeScript 已同步。

本地网站已在应用浏览器打开并看到首页。当前开发账号按既定灰度规则无法进入视频工作台，仍返回 404/“页面暂不可用”，没有伪造或放开真实身份。编辑器本轮验收截图为 `outputs/video-studio/assistance-editor-fixture.png`，可用于查看当前布局，不能当真实登录证明。所有新服务密钥仍只在忽略的 backend/.env，示例只有空占位，未上线/推送。

接下来的优先顺序：① 用真实指定邮箱完成一次登录、跨设备、任务失败恢复和实际费用核对的灰度验收；② 用多篇短/中/长口播稿校准文案目标时长、声音节奏和几套稳定动作模板，收集小范围反馈；③ 与剪辑同事确认交接包和接口（确认稿版本、最终音频、口播原片、产品事实/来源），再补新音频的真实字幕时间和剪辑回传。声音克隆、上传真人样本克隆与同事负责的智能剪辑仍为后续阶段，不把本次主链路接通说成所有未来功能已完成。继续保持未上线状态。

2026-11-05 主流程自动铺满已接入：不再仅依赖手动制作的 60 秒模板。`video_generation_media.py` 在每次口型提交前解码测量最终音频长度（文字 TTS 和上传音频共用；不信供应商返回的 duration=0/估值，不做固定一分钟加速），并使用提交时快照的原片。原片足够长直接复用原模型；不足时调用 `video_template_media.py` 制作正向周期（尾部向头部 0.25 秒叠化），再流式循环到向上取整至整帧的音频长度，上传登记派生私有模型后才提交口型。长音频不再需要每次重复增加一份 FFmpeg 输入，取消旧工具 300 秒限制；当前 FFmpeg 单步骤超时 600 秒，仍受已有 50 MB 音频和 200 MB 下载等资源限制，不宣称无限时长。

音频实测时长、原片快照、铺满配方/路径、上传地址、派生 model_id、计费回执与阶段均在原 owner/workspace 任务 JSON 持久保存，无新迁移。公共数字人也可延长但不调用 H3；原创优先使用本用户/工作区已验收的 H3 原片。派生登记和口型 POST 分别记阶段，结果未知禁止自动重试；安全失败可继续原任务，前端原作品卡出现“继续处理”。上传 WAV 的音频下载保持原内容和 MIME。原布局及唯一邮箱灰度未改，确认弹窗原费用文字补充了可能的延长登记费。

主流程验收：后端 75 项、前端 33 项、类型检查、ESLint/Ruff、构建，以及灰度 31 次/七路由和持久化浏览器回归通过。新增覆盖小数时长、321 秒铺满、TTS 虚假估值忽略、上传驱动、原片快照不被库更新替换、已验收 H3 延长不重复 H3、上传恢复不重复 TTS/登记、未知登记不重试、原片够长免登记。最后安全恢复按钮补充后已复跑生成相关 29 项。

另以真实供应商跑过网站 API → 上传原 60 秒 WAV → 已验收 15 秒 V2 → 自动铺满 → 登记 935 → 口型 → 授权下载 → 同请求重放。结果 `outputs/video-studio/formal-forward-generation-60s.mp4` 完成；动态采样顺序全部符合正向。没有新 H3/TTS 调用，口型实扣 ¥0.50；身份/项目/任务为隔离数据库的认证夹具，不是真实指定邮箱登录，不写主库身份。完整回执位于 `outputs/video-studio/formal-forward-live/`。

下一步执行顺序（保持本地灰度）：先完成真实指定邮箱的端到端登录验收；再把当前示例文案创作/二创接到规划服务，保留产品事实、参考原文、模型输出与用户确认版本；再接链接采集，核对 EveryInfra 实际能返回的内容后补齐视频原文提取；最后与剪辑同事约定文案版本、音频、口播原片、产品事实/来源及真实字幕时间戳交接包。字幕缺失必须明确，不编造时间。当前新增规划模型目标已由用户激活，密钥仅存忽略环境，服务能力正在核对，不把已接通生成描述成全部流程完成。

2026-11-05 稳定版 V2：用户明确授权修改提示词、用 913 重生成并复用原一分钟音频测试。已更新后端 `H3_PROMPT` 及版本化资产提示词，去掉中性姿态“自然呼吸”的强调，约束胸肩/头部/躯干稳定、低幅度前臂手势和首尾中性停顿；模型仍严格为 `Minimax-H3-768p-913`。新底片 15 秒，人物/服装/背景与内置生成参考图一致。4fps 中央胸部相邻帧平均灰度变化由 V1 的 5.928 降至 V2 的 4.120，约下降 30.5%；这只是动作代理指标，不是呼吸频率，也不能替代用户连续观看验收。

已再次读取官方实时 OpenAPI：对口型提交只公开 model_id/audio_url，没有 loop/reverse 参数。为避免短视频被服务端正倒放扩展，使用 `tools/prepare_video_forward_loop.py` 把 V2 原片按正向复制、0.25 秒叠化连接，裁到 60 秒，再登记为供应商模型 **934**（本地库当前版本，替代 933）。没有声称提示词能控制后续供应商的倒放策略；这个规避方法通过给足 60 秒输入视频实现。已复用原 `narration-60s.wav`/公网音频地址，SHA256 与上轮一致，0 次新 TTS 调用。新对口型任务完成并实扣 ¥0.50，新 H3 标价仍为 ¥0.90/次，登记响应没有返回 billing，不推断隐藏收费。

新成片 `outputs/video-studio/owned-913-stable-v2-one-minute.mp4`：60.00 秒、768×1366、24fps。完整解码通过；音轨与同一输入音频相似度 0.99914、0ms 偏移；排除脸部后的手势/躯干区域按 4fps 与原片匹配，116 个动作采样全部对应正向预期时序，没有上版 15～30/45～60 秒的持续倒序。静止姿态和叠化附近的单帧匹配仍可能歧义，不能据此保证每帧完全无瑕或自然度完美。已抽查各段人物和手部图像。只验证到 60 秒；音频超过这个已登记模板的时长，供应商仍可能自行扩展，需按音频时长预铺视频再验证。当前网站新建个人 H3 任务的默认流程仍登记原始 15 秒片；本轮证明了本地 V2/一分钟方案，没有把任意时长自动预铺接入全部后台任务。

本地库仍为 46 公共 + 1 原创，原创 ID 沿用 reference asset 的 `self-presenter-female-v1`，provider_model_id 切换为 934，默认预览源为新的 60 秒正向 V2；933 和源/结果文件保留，旧 manifest 备份到 `registered-template-v1-backup.json`。已清除此形象的旧派生预览缓存；其余公共素材不变。本地后端重启载入新提示词，灰度和布局不变，没有上线/推送。后端生成相关 19 项、TypeScript 类型检查、Ruff、OpenAPI 导出/生成同步通过；正向工具先用旧片完成 60 秒验证，再用于真实 V2。脚本 `tools/check_video_motion_order.py` 可重复核对时序。实测完整回执/分析在忽略目录 `outputs/video-studio/live-tests/stable-v2/`。

2026-11-05 动作质量复核：用户反馈一分钟片中“呼吸急促”，已澄清指画面胸肩起伏。对 H3 原片和一分钟成片的胸肩区域（避开口型和手部）按 4fps 做逐帧匹配：前 15 秒对应原片同时间点；15～30 秒对应原片倒序；30～45 秒再次正序；45～60 秒再次倒序。平均最佳匹配灰度绝对差约 1.69/255，身体动作基本来自 H3，未见身体播放加速。倒放扩展是这份供应商成片的实际行为，不能未经验证推及其全部配置/模型。音频 atempo 没有加速画面。原先文件/身份/接缝静帧检查通过，不能当作连续动作自然度已验收；此模板目前存在用户指出的胸肩动态质量问题。后续应优先重做低幅度、胸肩稳定的 H3 底片（替换“自然呼吸”这一容易被夸大的强调），并另行验证正向循环能否替代倒放；不要只靠更换音色或降低语速处理视觉问题。分析和半速并排对照在 `outputs/video-studio/live-tests/one-minute-v1/motion-comparison.json` 和 `motion-source-left-result-right-slow.mp4`。本次诊断未调用新的付费生成。

补充一分钟实测（同日晚间）：用户认可样片后授权用一篇完整的一分钟口播稿测试。已复用 913 原创模板 933，没有新增 H3 提交。主题《产品短视频，如何把卖点说清楚》，313 个汉字、含标点/换行共 368 字符；全文和测试回执保存在 `outputs/video-studio/live-tests/one-minute-v1/`。新 TTS 实扣 ¥0.184，原音频 67.248 秒，以 atempo=1.1208 保持音调加速至严格 60 秒，没有循环/拼接文案或用长静音凑时长；新对口型实扣 ¥0.50，本次合计 ¥0.684。输出 `outputs/video-studio/owned-913-one-minute-v1.mp4`，60.00 秒、768×1366、24fps。完整解码通过，输出音轨与输入 60 秒音频对照相似度 0.99914、最佳偏移 0ms（仅证明音轨完整与对齐，不代表逐音素口型准确）。已对照 15/30/45 秒前后及结尾帧，人物/服装/背景保持一致，手部在中性位附近；动作仍按 15 秒模板重复，不承诺完全不可见的接缝。当前最长实测已从约 35 秒扩展到 60 秒；“无限时长”仍未验证。本次没有改业务代码、权限、界面或部署状态。

用户明确选择“先接公共数字人、H3 模板和对口型”，授权真实付费测试；随后指定 H3 必须使用 `Minimax-H3-768p-913`。EveryInfra 采集和文案二创暂不在本轮范围。仍须保留现有布局和唯一已验证邮箱灰度，不部署、不推送。

两类形象的固定流程：

- QuanYu 公共数字人直接入库、直接对口型，不经过 H3。已同步 46 个 active/public/video 模型，2 个图片模型及供应商账号的全部私有模型被排除；复用现有公共模型 ID，没有批量付费复制公共库。封面从对应视频提取，不使用无关图库照片。完整公共大目录不等于已同步的 46 个视频模型，未声称已导入整个数千项目录。
- 自有数字人先用内置 `image_gen.imagegen` 生成人物参考图，再用指定 `913` 生成动作底片；用户预览确认人物一致后才登记。当前本地平台库已有 1 位原创形象“清禾”，参考图及来源说明保存在 `assets/video-studio/owned/`。真实验收后的供应商模型为 933；manifest 位于忽略目录 `backend/.data/video-studio/self-owned/registered-template.json`。720p 早期诊断输出人物不一致，登记得到的 932 已排除，不能作为清禾模板使用；803 仅保留历史诊断任务，不用于新生成。
- `913` 请求固定 15 秒 / 768p / 9:16，JSON `referenceImages` 使用实际生成图片的 OSS 公网地址；密钥与 OSS 临时签名只在服务端。官网当前标价 ¥0.90/次，不能把状态内上游 `charge` 字段当本账户最终扣费证明。

新增后端：`video_providers.py`（HTTP/上传/下载）、`video_generation_models.py`、`video_generation.py`；新增迁移 `20261104_0036`（接 0035，仅追加三表，拒绝破坏性回滚）。接口均在原工作区视频前缀下，复用可信灰度与 owner/workspace 隔离，写操作检查角色：`avatars`、`voices`、`generation-prices`、`audio-files`、`generation-tasks`、模板 approve/reject、任务 resume 和受保护媒体下载。

任务的 request_id/摘要、确认稿、供应商 task_id、已合成音频、费用响应与阶段持久保存。付费 POST 不自动重试；结果未知标为 unknown，禁止 resume 自动重扣；已完成生成的下载失败可以继续原任务，不重新 TTS/生成。底片进入 awaiting_review 后不登记，确认入库才执行登记；验收/恢复使用条件更新防止并发重复。浏览器按用户及工作区保留待确认请求 ID，响应丢失后刷新仍查询同一请求。服务器使用本地 BackgroundTasks 和 15 分钟无心跳恢复窗口，不等于生产分布式任务队列；重启后可继续已知 task_id，未知付费提交须人工核对。

声音使用官方公共 preset，提交字段为 `cloud_voice_id`（例如字符串 `"1"`，不是 `voice_id`）；支持真实 TTS 和上传 MP3/WAV/M4A，服务端检查实际音频内容，最大 50 MB。音频与结果只经授权路由交付。浏览器文案试听仍是本机声音，已明确标注；正式生成才调用所选官方音色。情绪与分辨率没有独立供应商调节能力，界面保留控件位置并禁用，成片按原模板分辨率交付，不能宣称原创片为 1080p。

真实测试结果（输出全在忽略目录 `outputs/video-studio/`，不是登录夹具结果）：

- 公共形象 + 正式 TTS + 对口型：完成，`public-lipsync-live-v1.mp4`，11.68 秒、1080×1920、25fps。一次公共目录导入响应扣费 ¥0.05，TTS 响应扣费 ¥0.0335，对口型单次扣费 ¥0.50。
- 内置生成参考图 → `913` 底片：完成，15.00 秒、768×1366、24fps。对照参考图和首中尾帧，人物/服装/背景一致，手势归位；首尾表情有差异，不宣称严格无缝。
- 验收底片登记为 933 → 约 35 秒音频对口型：完成，`owned-913-lipsync-live-v1.mp4`，35.15 秒、768×1366、24fps，对口型响应扣费 ¥0.50。已抽查 15 秒衔接前后及中段人物和口周画面。仅验证约 35 秒，不能由此证明“任意时长”或精确的音素级同步。
- 早期不一致模板的两次对口型仅作诊断，均未进入正式库。API 返回的 subtitle_data 为空，没有编造字幕时间戳。

验证：

- 后端 65 项通过（video_generation / video_projects / video_studio_access / auth_external / auth_config），含付费幂等、下载恢复、公共形象不得 H3、验收拒绝、默认关闭、SQLite 0036 迁移及 PostgreSQL DDL 编译；未实际连接 PostgreSQL。
- 原前端 33 项通过；typecheck、相关 ESLint、Ruff、生产构建通过，日志 `providers-pytest.log`、`providers-build.log`。OpenAPI 与生成的 TypeScript 已同步。
- `tools/verify_video_project_persistence.py`：真实 FastAPI + 临时 SQLite + 假供应商，独立浏览器恢复、冲突另存、已成功任务响应丢失后刷新重查不重复、音频保存恢复等通过。
- `tools/verify_video_library.py`：临时外部认证身份 + 真实供应商 GET/媒体；页面 12 张公共封面全部加载，46 个公共模型可用、原创参考图展示通过，0 次付费提交、0 浏览器错误。截图 `public-library-real-media-fixture.png`、`owned-library-real-media-fixture.png`。
- 灰度浏览器 31 次 access 请求、七路由、跨标签撤销/错误/超时回归通过；所有浏览器允许身份均为临时夹具，未真实登录指定邮箱。
- 本地后端已重启载入新代码与 server-only `.env` 配置；仅新建目录数据 46 公共 + 1 原创，真实库项目/生成任务/音频表仍为空（实测任务输出单独保存）。对照 `before-provider-integration.sqlite3`，users/workspaces 没变；未模拟认证的本地开发身份 access、业务及封面均 404。

运行仍使用仓库根 `.venv`。供应商密钥只在忽略的 `backend/.env`，示例环境文件只有空占位，默认 `POLARIS_VIDEO_PROVIDERS_ENABLED=false`；非忽略源码的密钥扫描为零。同步目录可运行 `.venv/Scripts/python.exe backend/scripts/sync_video_library.py`，只对本地目录写入、供应商侧只有 GET，不会把其他账号私有模型导入本地。原图 provenance 与动作提示词随源码保留。

后续提升：可以在固定首尾中性姿态的前提下，分别替换中段为单手解释、双手小幅强调、轻点头三类动作，建立多套模板；不能依靠“随机多做手势”保证协调。需要严格循环时应逐帧验收并处理衔接；本轮未声称已解决所有接缝。每个新底片仍须单独验收身份与手部质量。

## 已完成的灰度范围

用户要求：功能尚未上线，不要让普通前台用户看到；只允许已登录账号 `1474953130@qq.com` 参与灰度。入口、直接访问地址及未来业务 API 应使用同一授权规则。不要仅靠隐藏按钮、前端邮箱字符串或 localStorage 判断权限。

本轮交付：交接文档、统一后端灰度门禁、桌面/移动入口、全部视频子路由门禁、契约与测试均已完成，已有本地原型保留。允许场景使用临时数据库中的外部身份夹具验证；未真实登录指定邮箱，未改动真实用户资料。当前本地开发账号不在灰度范围，打开视频地址会显示“页面暂不可用”。

本次已在新对话读取 goal 技能并调用 create_goal 恰好一次，不设预算。灰度目标已经完成。本次用户另行授权第一阶段持久化，已创建不设预算的新目标并完成实现与验收；后续对话不要重复创建已完成目标。

## 项目与运行

- 仓库：`D:/Desktop/cyh/tengli/polaris-commerce-studio`，GitHub `https://github.com/cai18122668086/polaris-commerce-studio`。
- 当前分支 `main`，基线提交 `22fc3560fff2d68adfb943dc139afcec7a4ff948`。
- 本地未提交的导航修改及未跟踪的视频空间文件均为本任务成果，必须保留；不要重置或覆盖。
- 前端 `http://127.0.0.1:3000`，Vinext + React + TypeScript；后端 FastAPI `http://127.0.0.1:8000`。
- 本地已安装 node_modules、`.venv`，前后端以隐藏进程运行；先检查端口，避免重复启动。当前后端不是 reload 模式，代码变更后需重启任务所属后端进程。
- `.env.local` 与 `backend/.env` 为忽略文件，包含本地开发认证、SQLite 和 mock 配置。不要输出其中密钥，不要把开发认证用于生产。
- 启动前端：`node node_modules/vinext/dist/cli.js dev --hostname 127.0.0.1 --port 3000`。
- 启动后端：工作目录 backend，使用仓库 `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。

## 已确认的产品方向

原始方案文档：`D:/Desktop/cyh/剪辑/交付文档/网站产品介绍视频自动化流水线实施方案_v1.0_20261103.docx`。分工已调整：本项目负责参考视频采集/提取、基于产品事实的文案二创、声音和数字人 API 接入；另一个同事负责剪辑，后续接入。

用户认可必火的界面结构，要求尽可能沿用它的布局、模块顺序和操作习惯，替换为极光商绘配色/品牌。不要再次自行设计复杂的流水线看板或多个配置大面板。

参考页面：`https://www.bihuoai.com/workspace/welcome` 和 `/workspace/digital-human/create-digital`。用户已认可本地版本的整体界面。视频空间独立外壳，原极光商绘只放入口，打开新标签页；未来可独立子域名。本轮不配置域名、不发布、不接付费生成。

## 现有原型

入口路由：`app/video-studio/[[...screen]]/page.tsx`。

核心：`components/video-studio/video-studio.tsx`、`video-studio.module.css`、同目录 README。

页面包括 `/video-studio` 首页以及 create、avatars、voices、library、works、editing 子页。首页有侧栏、四张快捷功能卡、公共数字人列表。编辑器为形象、文案、右侧作品/文案库/助手布局；支持文本/音频驱动、形象/声音弹窗、二创弹窗、克隆素材填写流程。

草稿、产品事实、参考来源、文案版本和演示任务已改为服务端持久化，按当前用户及工作区隔离。localStorage 仅用于按身份/工作区隔离的未保存内容恢复，以及旧演示记录的显式导入；旧 `polaris-video-studio-demo-v1` 保留为只读备份。音频仍仅当前会话 Object URL，服务端只保存本地媒体关联元数据，换设备需重新选择原文件；声音试听仍是浏览器 speechSynthesis；二创/助手是本地示例；生成只保存“演示任务”及确认稿，没有真实视频。智能剪辑后置。

原站入口：`components/top-navigation.tsx` 的桌面入口和动态追加的移动入口均由 `useVideoStudioAccess` 控制；静态 `MOBILE_PRIMARY_NAVIGATION_LINKS` 不含视频链接。`components/primary-navigation-link.tsx` 保留视频链接新标签页行为；对应样式在 top-navigation.module.css。

此前原型验证：形象/声音选择应用、文案保存/改写、演示任务、刷新恢复；截图 `outputs/video-studio/editor.jpg`（忽略目录）。第一阶段只调整保存、恢复、版本与项目选择，未接入供应商生成；灰度和持久化验证见下文。

## 权限实现调查结果

- 前端真实当前用户查询：`features/auth/api/me.ts` 的 `useCurrentAuthUser`，调用 `/api/v1/me`。查询键 `['auth','me']`。
- API 客户端：`lib/api/client.ts`，默认同源，开发配置可指向 localhost:8000；已集成 SuperTokens refresh、最终 401 处理。复用现有认证机制。
- 前端全局认证：`app/providers.tsx` → `components/auth/auth-boundary.tsx`。视频路由仍受原登录/工作区门禁，并额外经过 VideoStudioGate。
- 后端可信身份：`backend/app/auth.py` 的 `get_principal` / `Principal`。生产 external 模式由 SuperTokens 验证会话与邮箱，忽略伪造 X-User-Id；开发模式允许 X-User-Id，不能当作生产验证证据。
- 后端当前用户响应：`backend/app/routes_v1.py` 的 `/me`，`backend/app/schemas_v1.py` 的 CurrentUserResponse。
- 配置：`backend/app/config.py` 的 Settings。开发默认邮箱为 admin@example.com，不应自动授权。
- 外部认证测试参考 `backend/tests/test_auth_external.py`，已有 FakeExternalAuthBackend、external_settings、verified_identity，可验证可信会话、未验证邮箱、伪造请求头等。
- API 文档生成：`.venv/Scripts/python.exe backend/scripts/export_openapi.py docs/openapi-v1.json`；TypeScript 生成使用 package.json 的 api:generate。若变更响应或新增接口，同步契约。

已实现 `GET /api/v1/video-studio/access`，使用 `backend/app/video_studio_access.py` 的 `require_video_studio_access` / `VideoStudioDependency`。规则只在后端：可信 principal 的账号状态为 active、邮箱已验证、邮箱 trim + casefold 后精确匹配指定邮箱。开发身份仍遵守同一规则，没有开发账号自动放行分支。

允许响应为 `{ "allowed": true, "user_id": "当前用户ID" }`，不返回邮箱或名单；普通账号返回通用 404；缺失会话 401、未验证/停用 403、认证服务不可用 503。视频 API 的成功与错误响应均禁止缓存。OpenAPI 与 `lib/api/generated/openapi.d.ts` 已同步。

`features/video-studio/access.ts` 使用现有 apiClient 和 SuperTokens 拦截器，不依赖 `/me` 的五分钟缓存；不读浏览器邮箱、能力值或 localStorage。初始/换路由/重新聚焦/页面恢复时均收回旧结果重新查询；只接受 2xx、严格布尔 true 和非空 user_id，8 秒超时或任何错误均拒绝。取消请求并丢弃迟到响应。`VideoStudioGate` 在明确允许前不挂载工作台，统一覆盖七个页面；不可用页面不显示灰度信息。页面外壳本身可以是 HTTP 200，受保护 API 返回实际拒绝状态，未实现基于 Cookie 转发的 SSR 鉴权。

`lib/auth/session-events.ts` 通过内存撤销标记与 BroadcastChannel 同步退出/最终 401/新会话事件；退出发起时先撤销，SDK SIGN_OUT/UNAUTHORISED 同样撤销，SESSION_CREATED 触发重新查询。撤销标记跨组件重挂载保留；聚焦也不能重新使用已撤销会话的旧允许结果。

**后续视频业务 API 必须声明 `principal: VideoStudioDependency`（或同一 Depends 作为路由级依赖），再执行工作区/资源归属与额度校验。** 前端门禁不是 API 鉴权凭据，不得接收浏览器传来的 allowed 或邮箱作为授权依据。`test_future_api_can_reuse_same_dependency` 用测试业务路由证明复用依赖时的允许/拒绝行为；目前没有真实视频生成接口。

## 灰度验收

1. 普通账号、未登录、邮箱为空、邮箱未验证时：桌面/移动入口都不展示。
2. 已验证账号 1474953130@qq.com：入口可见，新标签页进入视频空间，所有已知子路由正常。
3. 普通账号粘贴首页/create/avatars/voices/library/works/editing 地址仍不能进入；没有先闪出工作台再隐藏的情况。
4. 查询参数、localStorage、伪造邮箱/用户请求头不能绕过生产 external 模式的服务端校验。
5. 权限接口故障、慢请求、异常响应均默认拒绝；退出登录或切换账号不得沿用上个账号的允许状态。
6. 不向普通用户返回完整灰度名单；新增业务 API 不能绕过同一鉴权依赖。
7. 使用真实后端授权逻辑和外部身份测试夹具验证允许与拒绝；开发身份测试明确标注，不声称已经在真实邮箱账号登录验证。
8. 类型检查、适当的后端权限测试、导航/认证回归及构建通过。浏览器验证可达条件，并在文档记录证据及未能验证的部分。
9. 本轮默认只修改本地仓库。不得声称已上线；没有用户进一步指令，不部署或推送。

## 灰度验收证据与复现

以下命令均从**仓库根目录**运行，2026-11-04 已通过：

- `.venv/Scripts/python.exe -m pytest backend/tests/test_video_studio_access.py backend/tests/test_auth_external.py backend/tests/test_auth_config.py`：29 项通过，覆盖归一化邮箱、普通/空/未验证邮箱、无会话、停用账号、外部认证故障、伪造头与查询参数、账号切换、默认开发账号拒绝、未来业务依赖复用。均为临时 SQLite 身份夹具，不是真实邮箱登录。
- `node --experimental-strip-types --test tests/homepage-navigation-regression.test.mjs tests/workspace-header.test.mjs tests/auth-route-policy.test.mjs tests/auth-diagnostics.test.mjs`：26 项通过。
- `npm run typecheck`、`npm run build` 通过；构建保留现有 Vinext 源映射/配置加载提示，无构建错误。
- 后端本轮文件 Ruff、前端本轮文件 ESLint、`git diff --check` 通过。OpenAPI 再次导出后与文档 SHA256 一致，TypeScript 契约已生成。
- `tools/verify_video_studio_access.py`：Chrome 无头浏览器测试，拦截 API 后将 access 请求交给真实 FastAPI TestClient + FakeExternalAuthBackend；其他页面数据是只读夹具。验证普通账号全部七路由无工作台挂载闪现、伪造 localStorage/查询参数无效、指定已验证身份七路由可达、桌面/移动入口可见且新标签页可进入、503/断网/异常响应/9 秒迟到成功均拒绝、跨标签页退出与切换账号、撤销后迟到响应无效。最近运行 31 次 access 请求、0 次业务写入；未登录、空邮箱和未验证邮箱的路由及桌面/移动入口也分别验证拒绝。
- 同一浏览器脚本另开**无拦截**上下文访问本地 3000/8000：开发身份七个视频路由不可用、原站入口隐藏；实际本地 access 返回通用 404，未给开发用户添加白名单身份。

浏览器脚本标准命令：`.venv/Scripts/python.exe tools/verify_video_studio_access.py`，需要安装 backend 的 dev/browser 可选依赖和本机 Chrome。当前机器 Playwright 已装在用户级 Python312，实际复现命令为 `.venv/Scripts/python.exe -c "import sys,site,runpy; sys.path.append(site.getusersitepackages()); runpy.run_path('tools/verify_video_studio_access.py',run_name='__main__')"`；仅借用浏览器测试库，不修改业务配置。

证据位于忽略目录 `outputs/video-studio/`：`gray-browser-report.json`、`gray-denied.png`、`gray-allowed-fixture.png`、`gray-live-denied.png`。允许截图明确为夹具。前端复用原 3000 进程；任务所属 8000 后端已重启加载门禁。

测试注意：从 backend 目录运行旧 `test_auth_config.py` 会加载本地 `backend/.env` 的开发配置，导致 8 个生产配置测试在 task_dispatcher 校验提前失败；改从仓库根运行后 29 项全部通过，没有修改配置或弱化生产安全规则。

未覆盖真实 SuperTokens Core/指定邮箱的交互登录，以及线上反向代理、生产 Cookie/跨子域名会话；本轮没有部署，因此不宣称这些已实测。上线前应使用真实账号做最终冒烟并核对代理认证配置。本地允许身份仅是可丢弃夹具，未修改真实用户资料；无推送、无域名变更、无付费 API 调用。

## 后续阶段与验收

### 第一阶段 项目持久化（已完成，本地验证通过）

服务端保存项目、产品事实、参考来源、文案版本、确认版本、媒体关联和任务记录，按用户/工作区隔离。验收“换设备也能继续编辑”已用两个不共享 localStorage 的独立浏览器上下文完成：同一已验证外部身份夹具从服务端恢复草稿、声音选择、产品事实、参考链接，并继续编辑。未真实登录指定邮箱，未进行线上验证。

实现与契约：

- `backend/app/video_studio_models.py` 定义 `video_projects`、`video_script_versions`、`video_tasks`、`video_mutations` 四张表；主记录同时绑定 workspace_id 与 owner_user_id，历史通过所属项目归属隔离。版本和任务不提供修改/删除接口。
- `backend/app/video_studio_routes.py` 的整个路由组复用灰度依赖，每个接口再检查活跃工作区成员；写入还限制成员角色。普通账号、未登录、未验证邮箱不能读写；同一工作区其他用户也不能读写此用户项目。
- 基础路径 `/api/v1/video-studio/workspaces/{workspace_id}`：GET `/projects`、GET/PUT `/projects/{project_id}`、GET `/versions`、GET `/tasks`、POST `/imports/legacy`。列表支持 limit/offset，默认及最大单页 100；当前界面显示最近 100 项，旧记录不在服务端截断，指定项目 ID 可以直接恢复。
- `backend/app/video_studio_schemas.py` 严格限制字段、文本长度、引用数量与本地媒体元数据，不接受客户端 owner/status、存储路径、blob URL 等字段。参考链接只保存，不在服务端抓取；只允许无账号密码的 http(s) 引用。
- PUT 使用 expected_revision 做原子版本比较；冲突返回 409，不覆盖其他设备内容。request_id 与请求摘要持久保存，同请求重复/并发重试不会重复确认或创建任务；同 key 不同内容被拒绝。项目、历史、确认稿、任务与重试结果在同一事务提交。
- 普通保存保留完整内容快照的 draft 版本；“存入文案库”追加 library 版本；“创建演示任务”是用户明确确认当前内容，追加 confirmed 版本并绑定 demo 任务。后续改稿不会改变确认稿。任务状态仅允许 demo，未声称生成成功、未提供伪造视频文件。
- 迁移 `backend/migrations/versions/20261104_0035_video_projects.py` 接在 `20261030_0034` 后，只追加视频表与索引；不回填或改动用户、工作区、账务数据。回滚拒绝删除历史。迁移已在临时 SQLite 运行，并验证迁移后真实 API 可写；PostgreSQL DDL 已离线编译验证，未在真实 PostgreSQL 运行。
- OpenAPI 与 `lib/api/generated/openapi.d.ts` 已重新生成并核对导出一致；新 API 继承视频路径 no-store 缓存策略。

前端行为：

- `features/video-studio/projects.ts` 使用原 apiClient 与有界超时；`project-session.ts` 串行提交、保留确切的待重试请求，迟到响应不覆盖正在输入的新内容。`use-project-session.ts` 连接界面与身份/工作区隔离的恢复缓存。
- `VideoStudioGate` 在服务端授权后，把可信返回的 user_id 与当前工作区传入工作台；恢复缓存不能授权，也不会为其他账号显示上个账号内容。
- 原侧栏、功能卡和三栏编辑布局保留；编辑头部加入项目选择/新建，原保存提示改为真实保存状态，文案工具栏加入历史版本。原二创弹窗补充产品事实，重新打开可查看已有参考来源。恢复历史版本会产生新的草稿保存，保留原历史。
- 文本修改约 650ms 后自动保存；切换内部页面/项目先完成保存。服务端读取失败不会自动创建空项目覆盖已有数据。未保存时刷新有离开提示；本机恢复数据需用户明确选择恢复或使用服务端版本，冲突可“另存项目”。
- 本地存储不可用时仍可保存到服务端；失败/结果未知不显示保存成功。网络失败保留待提交内容和 request_id；重试先查明原提交结果，避免重复任务。账号撤销/工作台卸载不会再发起后续写请求，旧请求结果不能恢复授权。
- 旧演示记录必须点击“导入本机旧记录”，一次事务导入草稿、文案库与演示任务。基于原备份内容生成稳定请求 ID，刷新或响应丢失后重试不会重复导入，原 key 不删除。服务端历史时间使用导入时间，原始日期仍在浏览器只读备份中。
- 本地文件保存名称、类型、大小与 local_only 关联；形象/声音选择 ID 随草稿保存。音频和克隆样本未上传，重开页面会提示重新选择原文件，不持久化 Object URL，不绕开现有上传校验。文件上传、真实声音/数字人资产及其生命周期仍归后续阶段。

本阶段测试与本地证据（2026-11-04）：

- 仓库根运行 `.venv/Scripts/python.exe -m pytest backend/tests/test_video_projects.py backend/tests/test_video_studio_access.py backend/tests/test_auth_external.py backend/tests/test_auth_config.py`：46 项通过。覆盖跨应用重启恢复、产品事实/来源/媒体元数据、确认稿不可变、正常及并发幂等、不同设备原子冲突、用户/工作区隔离、viewer 写入拒绝、成员撤销、全部新接口灰度门禁、防伪造、输入限制、旧记录导入、迁移与 PostgreSQL DDL 编译。时间统一按 UTC 返回，SQLite 重新读取不会发生时区偏移。
- 根目录运行 `node --experimental-strip-types --test tests/video-project-session.test.mjs tests/homepage-navigation-regression.test.mjs tests/workspace-header.test.mjs tests/auth-route-policy.test.mjs tests/auth-diagnostics.test.mjs`：33 项通过。包括慢请求期间继续输入、未知提交重试、双击确认去重、冲突另存、显式恢复、退出期间不追加写入、本地存储不可用仍可保存。
- `npm run typecheck`、相关前端 ESLint、后端 Ruff、`npm run build`、`git diff --check` 均通过。构建日志在 `outputs/video-studio/persistence-build.log`，沿用现有 Vinext 配置/源映射提示。
- `tools/verify_video_project_persistence.py` 把视频业务请求送到真实 FastAPI TestClient 与临时 SQLite，外部身份用 FakeExternalAuthBackend；两套浏览器上下文互不共享 localStorage。通过：首页进入空项目、保存与独立浏览器恢复、事实与引用/声音恢复、文案库与确认稿任务、并发冲突另存、成功响应丢失后不重复任务、断网刷新显式恢复、版本历史、音频关联重选、旧记录导入与刷新防重。
- 浏览器报告 `outputs/video-studio/persistence-browser-report.json`；截图 `persistence-editor-fixture.png`，均明确为临时身份夹具，0 次付费/上传调用。运行方式同上节 Playwright 用户级库命令，把脚本名替换为 `tools/verify_video_project_persistence.py`。
- 已再次运行原灰度浏览器脚本：31 次 access 请求，普通/未登录/空/未验证邮箱、七个子路由、防伪造、故障/超时、跨标签页切换仍全部通过；该只读回归 0 次业务写入。
- 本地 3000 前端复用，8000 仅重启本任务后端。重启前通过 SQLite backup 保存 `outputs/video-studio/before-persistence.sqlite3`；本地 auto_create_schema 追加四张表。对照备份，真实 users/workspaces 身份与状态没有改变，四张视频表仍为空，临时夹具没有写入本地真实数据库。开发账号对 access 与 projects API 的实际请求均返回 404。

当前边界：真实 SuperTokens Core/指定邮箱登录、真实 PostgreSQL 执行与生产代理/Cookie 尚未实测；不应把夹具结果描述为真实账号验收。未部署、未推送、未改域名、未接供应商或付费 API。本阶段完成后下一步为第二阶段采集与二创，供应商契约需另行核对；不要自行开始真实付费生成。

### 第二阶段 采集和二创

粘贴视频链接 → 异步采集/提取 → 保留原文和来源 → 结合用户产品事实改写 → 用户编辑确认。不要继承同行价格、规格或承诺。验收：链接得到属于自己产品的确认稿。

### 第三阶段 真实生成闭环

先使用现成声音/数字人：确认文案 → TTS 试听/正式音频 → 数字人口播任务 → 进度恢复 → 预览下载。供应商调用仅在后端，任务有幂等键；提交结果未知先查询，避免重复付费。不要因失败丢弃已成功音频。

### 第四阶段 克隆资产

形象与声音分别管理样本、授权、异步状态、失败原因和可用资产；成功进入我的资产供创作页选择。

### 第五阶段 任务和使用体验

费用预估、任务重试/取消、历史记录、素材管理、配额与生命周期。音视频存储需扩展现有仅图片/归档等验证，不应直接绕开验证上传。

### 第六阶段 剪辑对接

先与同事约定交接包：项目/文案版本、确认文案、最终音频、数字人口播原片、产品事实和素材、真实字幕时间信息。缺少时间信息明确标为缺失，不伪造词级时间戳。后续智能剪辑消费此包，原片保留可追溯。

候选供应商源自原方案，接入前以官方契约重新核对：EveryInfra 视频提取、QuanYu 声音/数字人 API；H3 原片能力作为后续候选，非本轮必要。不要在浏览器暴露密钥，不调用真实付费 API 来验收本轮权限任务。
