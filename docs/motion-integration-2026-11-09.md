# 口播与 Motion 接入实施记录

状态：阶段 0 和阶段 1 的首条真实基础字幕链路已实现并在本机验证；不是全库可运行或视觉验收结论。后续语义规划、跨引擎逐组验证和文稿流程仍在实施。

## 阶段 0：基线与原库

- 重新通过 `git ls-remote`、`git fetch` 核对远端 `main`：`106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`；GitHub REST 查询开放 PR 数为 0。
- 主目录仍为 `22fc356` 且有大量既存未提交改动，未重置、覆盖或纳入本次开发。
- 桌面实际映射 D 盘，启动时 D 盘可用空间为 0。原工作树创建失败，改为 C 盘隔离开发副本：`C:/Users/a1726/codex-workspaces/tengli-motion-20261109`，分支 `codex/motion-integration-20261109`。该副本独立 Git 元数据、共享只读对象；未发布或部署。
- 已完整阅读 00、01、02 交接文档；完整原 ZIP SHA256 分别为 `c10429057a862cd8bd9e24280e5dd3f04448a3829b8b10646dd5d341ca0969bc`、`3b4d100ebf6ce41a233f4c994c1f779502ef568a206e7fc9c26cc9507c0baf17`，与交接基线相同。
- 安装器核对 ZIP 摘要、安全路径、原始 integrity 的 1426 项文件、全部 132 组入口/schema/模板/声明合同及 197 条随包资产摘要。全部原包文件保留为只读，实例、绑定、输出在包外。
- 完整 Motion 版本目录：`C:/tl/l/c10429057a86/motion`；原写稿包在 `C:/tl/l/3b4d100ebf6c/writing`。注册索引保留原目录、aliases、附加组件、197 条资产原记录、699 条外部引用、全部方法文件及独立网站状态。外部引用未被宣称为已经拥有的文件。
- 首次原生 `doctor`：132 组，无缺入口，197 条资产无摘要错误；当时 Hypit CLI 缺失。后续补装精确 0.2.12 并完成 HY-A3 本机技术编码，详见下面证据；其余 6 组未实测，未删除。浏览器家族的 CX-G01 仍因精确字体缺失而失败，不能以安装 Playwright 代替验证。
- 独立本地环境实际版本：Python 3.12.10、Node 24.13.0、Pillow 12.3.0、numpy 2.5.4、OpenCV headless 5.0.0.93、jsonschema 4.26.0、fonttools 4.68.0、Playwright 1.64.1、onnxruntime 1.31.1、faster-whisper 1.2.1、CTranslate2 4.8.5。与原包测试环境的差别保留在运行记录，未推断全库兼容。
- 实际 pip 解析遇到 kombu 5.7 的 packaging 26.3 与既存 SuperTokens `<26` 冲突。`backend/editing-constraints.txt` 固定本机验证组合 Celery 5.6.3 / kombu 5.6.2 / packaging 25.0，不修改主目录环境。
- 只读模型列表查询确认网关含 `gpt-6.1-sol`。原文稿模型配置仍为 `gpt-5.6-sol`。未发起付费规划请求，未输出密钥。

## 阶段 1：代码与合同

- `motion_library.py` 和安装脚本：完整原 ZIP 安装与校验，原库只读，注册状态与历史认可状态分开。
- 新迁移 `20261109_0042` 新增 `video_editing_sources`、`video_editing_tasks`、`video_editing_attempts`、`video_editing_artifacts`。复用既有 workspace、用户、项目、确认稿、generation 外键，不伪造数字人任务来支持上传视频。
- 新接口 `/api/v1/video-studio/workspaces/{workspace_id}/editing-sources`、`editing-tasks`、查询/取消/重试、任务产物和分页 `editing-library`，另有单组原始 schema/contract 与随包/外部资源分页查询。沿用既有灰度身份及工作区权限；结果路径不会出现在公开任务响应；完成前无下载产物。
- `video_editing_contracts.py`：实际词句 ID/毫秒/置信度/稿音差异、严格任务响应、无时间和代码字段的语义规划合同。OpenAPI 与 TypeScript 已同步生成。
- 独立 `editing` Celery 队列和 worker 入口；`run_editing_worker.py --once ID` 为本地独立进程入口，`--recover` 重投数据库内 queued 或过期运行任务。API 只持久入库，不连接 broker 或执行媒体工具；独立 `app.video_editing_maintenance` 扫描投递，有 5 分钟 DB 投递预留防止积压期间反复入队。任务有租约、执行 token、尝试历史、取消意图、旧进程回写隔离与转录 checkpoint。
- worker 原声提取到 16 kHz PCM，再实际识别词点；不均分字速，不用模型猜时间。生成原 `episode/selection/bindings`，调用原 adapter 的 `check/export`，原视频音轨贯穿整片。
- 原统一引擎单页上限 15 秒：按该限制分视觉段，语音仍取同一原视频连续音轨。首版画幅、旋转和起点偏移超出已核验范围时明确失败，不擅自裁成竖屏或拉伸人声。
- 原 exporter 两次复制字体、Hypit 复制组件目录时，会把只读模式带进任务副本，导致 Windows 后续写入失败。`video_editing_native.py` 与固定 Python 启动适配只让“原库→当前任务目录”的副本可写，覆盖原生子进程的 `copy2/copytree`；仍执行原 adapter、原检查、原渲染函数，没有修改引擎、字体或源码字节。每个进程记录实际兼容操作。
- 新页面接入已有视频或上传原片，基础字幕任务、状态、取消/重试、真实成片播放和下载；没有让用户填写底层 JSON，也没有宣称智能动效已经全面完成。

## 真实结果与验证边界

- 输入：主目录此前真实口播 `outputs/video-studio/website-user-douyin-raw.mp4`，原始 SHA256 `6e90abf677e2f83f84935806faa40a4b6d519a980ee0ec32119109fed6fd53d5`。旧原片只是本次输入，未用旧成片冒充新剪辑结果。
- 新任务 `d9abbc1b-4960-4f51-9692-f8bcf214e815`：48.475 秒原声，212 个实际 ASR token，原库 Z-M00＋libass 主字幕，新导出 720×1280 / 30 fps / H.264 / AAC。
- 新结果 `C:/tl/acceptance/first/website-download.mp4`；SHA256 `bc2f6e28b28a2bdd8e900435b6fd834b5af3f398ad8f928337738fbb6679d53b`。原声轨保留，整片解码通过，结果时长 48.475 秒。
- 原片经过新 API 实际上传入库；独立 worker 把新产物及校验记录登记数据库，经新 API 取回，下载摘要一致，Range 请求为 HTTP 206。当前使用共享本地任务卷，尚未实现远程 worker 的结果上传协议。
- 已打开本地 React 页面，浏览器视频 `readyState=4`，时长 48.475 秒，实际播放超过 2 秒，`video.error=null`；点击下载得到相同 SHA256。浏览器证据 `C:/tl/acceptance/first/browser-evidence.json`。
- 本地网页 `http://localhost:4311/video-studio/editing?project=40a798a3-4e9c-4ac2-8bcb-72a9f255b431`；API 仅监听 127.0.0.1:8311。这不是线上部署。由于本地未启用付费数字人供应商，既有形象库读取提示不作为剪辑结果失败或线上状态判断。
- 失败尝试保留：租约时区比较、PyAV 解码参数兼容和字体任务副本权限。最终成功不是用退出码代替文件/归属/解码/下载验证。
- **语义未通过**：当前中文识别有“洗洁精”等同音错字、繁简混用、部分断句不佳。第一条仅为真实工程链路样片，不能作为最终内容成品验收。尚未证明 150 ms 词点、300 ms 句边界目标。
- **视觉与听感未验收**：检查了少量输出帧和浏览器播放；未连续人工听看全片，未获得用户认可。没有音乐和音效是基础字幕模式的显式范围，不能继承为后续动效成片默认。
- 相关测试已覆盖旧 handoff/文稿回归、剪辑归属、幂等、取消重试、租约、无时间代码语义合同、重复中文锚点、否定/虚构素材保护、新迁移往返、中文时间戳拒绝错配、原生证据拒绝字节变化、broker 故障恢复及只读原包副本兼容。完整结果见本机测试日志；全 backend Ruff、Windows/Linux mypy、前端类型和新增组件 ESLint 已通过。历史全链 SQLite Alembic 在既存 PostgreSQL 专用迁移失败；新 0042 的 SQLite 往返和 PostgreSQL 离线 DDL 通过，真实 PostgreSQL 升级尚未执行。

## 运行与接续

在独立环境安装 `pip install -c editing-constraints.txt -e '.[dev,editing]'`。Motion 原 ZIP 不进前端 public，也不复制进 Git；使用 `scripts/install_motion_library.py --motion-zip ... --writing-zip ... --root ...` 安装。

API 与 worker 需配置相同数据库、Redis 和绝对媒体路径，完整原库以只读挂载共享，任务卷可写。启动 `celery -A app.celery_app.celery_app worker -Q editing --concurrency=1`；Windows 本地联调用 `--pool=solo`。恢复入口为 `python scripts/run_editing_worker.py --recover`。

已另启本机 127.0.0.1:6387 Redis 与独立 Celery worker，真实第二任务 `7dbf1581-204c-43a4-bdc5-15c8a8709d5a` 经 HTTP API 持久排队、`--recover` 投递、`editing` 队列消费，在 1 次尝试内完成。输入与第一任务相同，新输出摘要相同；这证明调度与渲染可复现，不能算作两条不同创意成品。证据 `C:/tl/acceptance/first/redis-evidence.json`。独立镜像构建及生产卷配置仍待验证。

### 中文识别与第二版真实链路

已接入可选本地 FunASR 1.4.24，使用官方 Paraformer、FSMN VAD、CT 标点模型。`app/data/editing_funasr_models.json` 固定官方仓库、文件 revision、SHA256 和字节数，安装器按固定清单下载，运行前逐文件核对，禁止 remote code。实际测试组合为 Torch/Torchaudio 2.5.1+cpu、Transformers 4.51.3、huggingface-hub 0.36.2、tokenizers 0.21.4；先安装 CPU Torch，再安装 `.[editing,editing-zh]`。原 faster-whisper 路径仍可显式选择，两条识别记录保留。

同一段原声新识别出 243 个词点、25 个标点分句；只在 raw_text 与 surface text 词序及数量一致时附加标点，不均分文字时间。尾词模型量化超出实际音频 24 ms，按音频终点裁齐并明确记录原值与调整值；超出 30 ms 或其他不一致直接失败。缓存依据 provider、实际模型文件、识别版本、语言、设备和参考稿摘要，不能因模型同名而复用旧结果。

真实 HTTP 任务 `e46ac572-b7df-442b-9f32-2382da7a6658` 由维护进程投递、独立 Celery worker 在 1 次尝试内完成。网站视频仍为 48.475 秒，SHA256 `73d70069b6ed4f7330b1a73e59c003403647ffd122aff1f22d32076f1bce03d5`，浏览器 readyState=4、播放超过 2 秒、无 video.error，下载摘要一致。证据 `C:/tl/acceptance/first/funasr-browser-evidence.json`，文件 `funasr-browser-download.mp4`。这是一条改进后的基础字幕工程试片；“关点/关键、真话事/真划算、刷的/刷到”等错字和断句仍未解决，不能声称语义通过，也没有达到用户最终验收。

新增 `backend/Dockerfile.editing-worker` 和显式选择的 `compose.editing.yaml`，共享任务卷、只读原库及只读 ASR 模型、独立恢复进程，原视频目录必须明确指向已有目录，禁止自动创建空目录掩盖缺失。Compose 合并配置检查通过；本机 Docker Linux daemon 未启动，镜像尚未构建，未启动该 Compose、未部署，生产迁移与文件归属仍需实际验证。

### 全量核查与原生证据

`audit_motion_library.py` 已对全部 132 组原入口、模板及 schema 留下逐项摘要。35 个 unified 原始模板的 `output.path` 仍为 `input://...`，直接 schema 检查不满足 `.mp4` 文件名约束；这是未绑定原模板的状态，不能自动归为 35 组引擎故障，更不能把它们剔除。实际实例编译后由原 adapter 再检查。核查文件 `C:/tl/preflight/all-132-schema-audit.json`。

运行证据独立保存于任务卷 `_library-validation/<release>/`，以原生规范化输入摘要、库摘要、输出摘要、完整解码与帧数核对后登记。网站全目录和单组接口返回这些具体证据；成功仅叫 `sample_rendered`，失败叫 `sample_failed`，有成功和失败记录时叫 `mixed_samples`，均保持语义、视觉与听感未验收。未测的组仍注册为 unverified。

YYP01 已用当前口播原片、新的几何与事件时点渲染 120 帧 1080×1920 原生画面组件，完整解码，SHA256 `4e8ff9c776c3db104c67d403658bd90601527691c0a7e584a12159c28f036a00`。该组字幕层显式关闭，由整片独立主字幕承载；不是缺字体时偷偷替换字形，也不是一条独立创意成片。BG-S06/YYP01 成功及 CX-G01/LYO01 失败证据均已导入网站目录状态。

Hypit 原组件依赖声明为 `@hypit/hypit ^0.2.12`；本机单独安装精确 0.2.12，核对 npm tarball SHA512，保留完整 LICENSE，未改原包依赖。该版本许可要求第三方多租户服务取得厂商书面授权；允许本组织在自己基础设施上使用和内部制作。当前只做本组织本机测试，7 组保留，未开放为第三方网站能力，也未购买授权。完整许可在 `C:/tl/hypit/LICENSE-0.2.12.txt`，来源为官方 [0.2.12 发布包](https://registry.npmjs.org/@hypit/hypit/-/hypit-0.2.12.tgz)。

HY-A3 第三个新实例已通过原生 Build/get 编码：`bld_20261108T183222077Z_1B2533A11A`，输出 `C:/tl/native-validation/HY-A3-v3/renders/component.mp4`，SHA256 `1037619b4e991869e3ac8ccc167838ec8f9f631433bf48f1f63d21a7fc341963`。独立 FFprobe 计数及 FFmpeg 全解码验证 120 帧、360×640、30 fps。使用当前口播原片和该原片三张新截图，仅为技术输入，不声称“三张截图”构成商品语义素材。执行前 plan 确认 5 个本地请求、0 个供应商请求，Runtime 安装 7 个本地依赖包、2 个 Programs 就绪；没有付费模型调用。Windows 安装版 Chrome 的 `--version` 探测不兼容，改为显式使用官方 Playwright Chrome Headless Shell 156.0.8078.4，未改原引擎。失败的只读副本和环境尝试保留，成功后已停止该实例的 Hypit Runtime worker。

截至此处，网站 API 遍历仍为全部 132 组：4 组有具体样本渲染证据（Z-M00、BG-S06、YYP01、HY-A3），2 组有失败证据（CX-G01、LYO01），126 组未实测；全体视觉、听感与语义验收均未通过。证据 `C:/tl/acceptance/first/full-catalog-runtime-evidence.json`。这覆盖四类引擎的具体路径，不能替代剩余逐组和浏览器家族验证。

只读副本兼容 V2 变更后再跑完整 48.475 秒链路，任务 `005a8845-f3b4-4a7a-b667-fa9e36857743` 成功，下载仍为 `73d70069b6ed4f7330b1a73e59c003403647ffd122aff1f22d32076f1bce03d5`；新 API 实测提交仅 0.015 秒，随即取消排队任务成功。当前 46 项相关测试通过，日志 `C:/tl/phase1-all-final-tests.log`。新增静态检查在最后代码变更后继续执行，以实际日志为准。

阶段 2 准备：新增完整 132 组检索索引、按原方法摘要及逐文件哈希版本化的规则包、严格词 ID 规划和不可重复付费提交标记。`prepare_motion_plan.py` 默认仅写 dry-run 请求；`--execute` 会发起一次付费调用，需要用户对新增费用的授权后才执行。该准备不能当作已经完成模型规划或原生参数编译。

新增原生技术验证（不能当作语义正确或全库通过）：BG-S06 已用新文字/新事件时点渲染 120 帧透明字幕，完整解码，SHA256 `1742fc55c44e8c75bc35535dd0dd85b5df2c81b8bd721decd8aef9848747b3eb`。CX-G01 遇到原 `title.ttf` 对应的 YouSheBiaoTiHei 字体 `font-dab883d69fb71323` 缺失，未替换为别的字形。LYO01 发现真实合同冲突：该组 schema 禁止 `style`，原 `render.py.validate` 却无条件要求 LYO02 的 background/geometry，尚未变更原库或绕过检查。分别保留输入、日志和状态于 `C:/tl/native-validation`；这些具体问题说明“文件齐全”不能替代全库运行验证。

阶段 1 结束时的后续项：改善中文 ASR/对齐和校对版本，再跑受约束的语义规划，扩展原生参数编译、跨五类引擎代表试片及逐组 132 项验证。恢复过程还需完善渲染片段/回传阶段的复用；目前只复用通过摘要检查的转录。页面风格/重点/音乐编辑、文稿分对象流程、资源绑定版本和 Hypit 条件继续实施，下面记录了后续进展。部署、外部发布、真正新增的付费调用继续按用户要求单独说明后授权。

## 文稿分对象流程的实施进展

阶段 0/1 的可复查代码已保存本地提交 `113b6773b7d6f74944a05dbfc01acef59c6efe1f`，未推送。后续文稿改动在同一隔离分支上推进；没有改动主目录的未提交内容。

已读取同事包的拆解、客观分析、影子写稿与端到端方法及原 `shadow_check.py`。新增固定清单验证全部 33 个原文件摘要；原始包、源码与方法未替换或裁减。网站适配区分方法里的历史样例数值与当前证据，文字参考缺画面、互动和跨号样本时明确标“未提供”，不照搬旧样本相关系数、语速或所谓平台门槛作为新结论。

新增 `video_writing_documents` 保存独立、不可覆盖的 reference / analysis / facts / draft 对象；`video_writing_adoptions` 记录采用后生成的既有草稿版本。新增迁移 0043，原 `video_script_versions` 与 handoff 协议保留。参考原文带来源与稳定句 ID，事实卡区分用户声明与未知，含禁词与禁价格/净含量/疗效；拆解覆盖所有原句，引用必须能在对应原句中找到。新稿逐句映射已知事实，拒绝虚构事实 ID、参考价格残留、禁词和未映射数字。采用通过项目 revision 做并发保护，原子写入新草稿版本与血缘，不自动生成确认稿。

复用已有 assistance 任务与单次提交服务，新增 `ref_analysis` / `fact_draft` 两种任务。源资料与方法版本快照落库，失败或结果未知时不自动重发。实际调用的 `shadow_check.py` 来自只读原包，参数固定，不执行模型生成代码。可选目标片长与出镜/手部形式用于原方法字数预算；没有明确时长就不宣称预算检查通过。结构 PASS 仍不等于意思或事实正确。

页面在文案助手中新增“拆解与事实写稿”，支持原文版本、事实卡版本、原文拆解、逐句新旧对照、事实映射和采用为草稿；未保存的事实编辑不能悄悄用旧事实卡生成。当前本机开启资料保存和浏览，文稿模型调用显式禁用；没有用模拟模型响应在真实项目生成样稿。

浏览器已真实保存参考原文与“产品名称：未知”的事实卡，刷新后两个独立对象仍在，未知值保持 null，模型按钮禁用且未发送 writing-tasks。证据 `C:/tl/writing-validation/browser-evidence.json`；该原文来自前面真实口播的未校对识别稿，明确不是客户事实。真实界面 `http://localhost:4311/video-studio/create?project=aaa4ca7e-6512-4ef2-b418-3fa510d48f57`，仅本地联调。

3 项新增测试覆盖事实/证据拒绝、保存→模拟任务→保存结果→采用→旧确认稿隔离、幂等与迁移往返；与旧 assistance 和项目测试合跑通过。另以 httpx.MockTransport 在零网络请求下执行两个 provider 合同与真正原包 checker，原 checker 返回 PASS，33 文件完整性通过；这是合成单元输入的技术检查，不能当成真实模型写稿或语义验收。证据 `C:/tl/writing-validation/original-checker-evidence.json`。新流程默认关闭，配置项 `POLARIS_VIDEO_WRITING_WORKFLOW_ENABLED` / `POLARIS_VIDEO_WRITING_LIBRARY_DIR`；真正模型拆解、写稿质量及实际 PostgreSQL 迁移仍未验证。

截至本次文稿改动，68 项相关新旧测试合跑通过（`C:/tl/writing-editing-regression-tests.log`），342 个 app 源文件 Windows/Linux mypy、后端 Ruff、前端类型检查、新组件 ESLint 通过；0043 SQLite 往返及 PostgreSQL 离线 DDL 通过，未在实际 PostgreSQL 执行。编辑器底部旧“智能剪辑即将上线”占位已替换为可打开基础字幕面板的真实入口。

`compose.writing.yaml` 是独立选择的本地文稿挂载配置，原方法只读、检查产物在独立任务卷；它复用现有文稿供应商配置，不自动启用模型。该配置仅做 Compose 合并检查，没有启动或部署。

随后补完浏览器家族 CX-G07 的原生技术样本：120 帧、720×1280、30 fps，完整解码，SHA256 `6cb9e3c8d3f94c1d82c5a849a9e1940e07413c6d34122669a4be3194ed699ebb`。使用原暴露的 font 字段显式绑定原包 Noto，保留原 keyframe 轨迹形状，仅更换当前时间/平移/配色及当前原片截图；没有解决或替换 CX-G01 的硬编码 title.ttf。该样本仅测浏览器载体：截图是说话人，不是假装“洗碗”等用途的实拍证据，未接入网站成片、未获得语义验收。

最新目录 API 实测仍为 132 组：5 组有样本编码、2 组有失败、125 组未实测，0 组用户视觉验收。五类引擎现在各有具体技术样本；此结论不能替代全 132 组的逐项参数编译、素材/字体依赖和本期成片验证。受约束规划请求已更新到包含容量、限制与 ASR 未校对信息的 dry-run，尚无付费模型响应，未宣称规划→全库编译已完成。

## 词锚点与原生参数编译的后续进展

新增全部 132 组的原生字段合同提取器，记录原 schema/模板摘要、具体文字 JSON 指针、真实事件单位、素材槽、原生时间长度/偏移/速率与容量范围。`audit_motion_parameters.py` 重新验证原库完整性后产生 `C:/tl/preflight/native-input-contract-audit-all-132.json`。目录和规划请求包含全部组，单组接口返回字段合同；这只是模板字段覆盖，不是 132 组配方或运行通过。

已按原源码区分时间语义：浏览器 `at` 是时刻、`enter` 是入场持续时间；scene 的 `shift_frames` 是整体偏移；逐字间隔、stagger、cell_duration 与 hand_speeds 不能冒充词点时刻。模型只给允许的字段指针、词 ID、start/end 边界与现有素材 ID。编译器从真实词点取时间，记录帧量化误差，保留小数、数量单位及否定，不依据字速均分。转录合同新增稳定词 ID、顺序、实际时长上限和分句范围一致性校验。

新增原生配方编译器：配方是网站适配层/操作者明确编写的数据，不是模型代码。当前要求与原模板相同字段和数组拓扑；文字、时刻、媒体必须先清空为待绑定槽，不能默用历史文字/旧时点/旧素材。字体、位置、颜色和其他参数需记录当前设计理由；外部字体/模型只接受原身份 SHA256 一致的显式绑定，输出强制写入任务实例。原 schema 再检查。不同数组容量/分支、数值图表的事实映射和 Hypit 原生复合属性作者协议仍需专用配方，当前明确拒绝，未以替代渲染器绕过。

真实新验证 `C:/tl/native-validation/BG-S06-word-compiled-v2` 使用当前原声词 `t000004..t000023`：上层“十四块九”、下层“到手两大瓶”，时段为原 ASR 的 1070–4670 ms。原生组帧数 108，四个事件编译为 0/22/22/52 帧，原引擎实际输出 576×320、30 fps，108 帧完整解码通过，SHA256 `614925f744534d05e4060c66d12f8352c7ca0e00c508f7fcae5971ca1a380a7d`。配方、词绑定、schema 编译记录、原生 receipt 与目录证据均保留。这是操作者选组的组件工程验证，不是模型语义规划，不是整片，也未确认商品价格事实、听感或视觉验收。初次直接启动缺 FFmpeg PATH 的失败日志保留，使用显式工具目录后才完成真实编码。

规划提交现已支持以任务稳定目录复用已保存响应；在响应保存后、校验保存前崩溃，可重做合同校验而不再次请求模型。输入摘要变化、结果未知或响应不合合同均不能自动重付费。请求、响应、校验结果以摘要关联；校验仅标为 contract_only，语义与视觉仍 unreviewed。后续 worker 接入必须使用任务级目录，不能用每次 attempt 的目录规避提交标记。新增计费仍等待用户授权，实际模型调用为零。

该轮新增与既有流程合计 76 项测试通过，日志 `C:/tl/native-compiler-regression.log`；345 个 app 文件 Windows/Linux mypy 及后端 Ruff 通过。dry-run `C:/tl/planning/dry-native-bindings-v1` 包含全部 132 组及词绑定字段，235415 字节，最大输出 5000 tokens，未提交模型。前端未在此轮变更；编译器尚未作为网站语义模式接入 worker，基础字幕链路继续运行。

上述词锚点编译工作保存于本地提交 `677166c`，未推送。

## 校对文字重新对齐的实施进展

新增独立、可选的 `fa-zh` 本机强制对齐路径，使用官方 `iic/speech_timestamp_prediction-v1-16k-offline`。官方模型文档的 [Timestamp Prediction](https://huggingface.co/funasr/fa-zh/blob/main/README.md#timestamp-prediction) 与 [维护者说明](https://github.com/modelscope/FunASR/discussions/2971) 明确使用实际音频和已有文字，专用于中文，不等同于多语言识别。新 `editing_alignment_models.json` 固定 10 个官方文件的 revision、SHA256 和字节数，共 167025765 字节；其中 `model.pt` 的 SHA256 为 `f34ede558af831fb504206b25f1c2f27ca2f77753c26c4dd38d03323153b6f73`。本机逐文件校验安装在 `C:/tl/asr/alignment/fa_zh`，模型包清单摘要 `48072d77a20fa3f3e244a598b6af1485ffbb939e9e11d8df370b23c6d0d70116`。未更换现有三模型 ASR 包，默认安装仍为 recognition，alignment 需显式选择。

`align_editing_transcript.py` 读取原任务音频、prepared 和原转录，保存独立文字、原始对齐结果、新转录和 receipt；UTF-8、音频摘要、原转录 source/audio/duration 一致性和模型摘要在执行中检查，禁止 remote code，禁止覆盖已有对齐实例。新转录记 parent 摘要、文字 revision、独立词 ID 和处理版本，原 ASR 文件不改。用户校对与操作者候选有不同状态；命令行只能产生 operator_candidate，不能冒充用户校对。新时间轴始终 timing_review=unreviewed，强制对齐不能证明文字确实被说出，也不核验商品事实。

真实音频验证保存在 `C:/tl/alignment-validation`：same-text-v1 与 candidate-v1 均产生 243 个词点；numeric-candidate-v1 使用“14块9、1000克、4斤、A类”等写法，产生 240 个单位，3 处把原生数字子词以真实首尾边界合并，原区间和下标保留在 timing_adjustments，未均分或猜测字符时间。首词起点 410 ms、尾词结束 48050 ms，原音频仍长 48475 ms。操作者对“关点/关键、真话事/真划算、刷的/刷到”的候选更改和未核验的品牌名登记在 operator-candidate-provenance.json，尚未逐词听验，更不是用户确认稿。原数据库中已有确认稿也包含识别式错字，不能直接替代当前实际音频。数字写法与实际读法的对齐精度仍需专项听验，未证明 150 ms/300 ms 目标。

新增测试拒绝缺词、字词不匹配、缺时间戳、重叠时间、越界与跨源对齐，验证原文与原时间轴不变、新时间点与新词 ID、大小写/标点保留及数字子词的真实边界合并。29 项相关回归、346 个 app 文件 mypy 与后端 Ruff 通过。这一轮完成对齐模块和运行脚本；校对版本数据库、网站校对界面、独立 worker 消费校对稿及据此重新出片仍待继续接入。没有付费模型调用或部署。

上述本机对齐模块保存于本地提交 `b1d2355`，未推送。下列后续工作已经把校对版本接入网站和独立 worker。

## 网站校对版本与重新出片的真实链路

新增迁移 0044 和不可覆盖的 `video_editing_transcript_revisions`：区分原转录产物、文字版本、父文字版本、修改前后差异、原声身份和用户声明。保存候选不推断用户已校对；`user_corrected` 必须另有明确勾选，仍不意味着时间或成片验收。源、项目、工作区和用户归属都要匹配。相同请求幂等返回已有版本；跨任务产物、其他原片或其他用户的版本被拒绝。新版本只新增记录，不改原 ASR、已完成任务、原确认稿或已完成视频。

网页新增“校对字幕”：按分句定位试听、编辑文字、保存/选择版本、显示待核对或用户校对状态，重新出片只能用已保存版本。编辑未保存时不能悄悄使用旧版本。继续编辑所选版本会记录父子关系和相对该版本的差异；同文同状态不重复保存。原画面有硬字幕时不提供此处重生成，明确提示需要无硬字幕原片。

独立 editing worker 读取校对版本与原转录摘要，在可取消的独立子进程中完成真实 `fa-zh` 对齐，仍由原库 Z-M00 与原生主字幕出口成片。校对路径默认关闭，开启需 API 与 worker 配置 `POLARIS_VIDEO_EDITING_ALIGNMENT_ENABLED=true`，worker 指向独立固定模型目录。新增 `compose.alignment.yaml` 作为显式叠加项，模型只读挂载且禁止自动创建空目录；Compose 合并配置检查通过，未启动 Compose 或部署。

真实网页操作保存候选版本 `b22b1604-4227-429b-8a43-84a8c88ff00f`，刷新后读取相同文字，未勾选人工校对；网页创建新任务 `eb26dcbb-e8b0-4476-8aef-33cbb4effcc8`，由 Redis/独立 Celery 在 1 次尝试完成。新任务使用 240 个 `funasr-fa-zh` 对齐单位，而非旧 ASR 时间数组；字幕文字与保存版本一致。输出 48.475 秒，SHA256 `83b40c10ebf6fd91112ecff024949eb319dd302f20b356d3d1807c3f1a2ad5a4`。浏览器 readyState=4，实际播放到 2.247 秒、无错误，点击下载摘要与服务端一致，且不同于原基础字幕视频。文件 `C:/tl/correction-validation/browser-download.mp4`，证据 `submission-evidence.json` / `browser-playback-evidence.json`；界面截图已查看 `C:/tl/preflight/website-transcript-correction-editor.png`。这仍是候选字幕工程试片，不是不同创意方案的多条成品，更不是全库动效验收。

进一步在网页保存子版本 `fb9f0f95-0f4b-4a22-8668-a64529ddd8c2`，只改一处逗号为冒号，父版本正确记录为上述候选，刷新后文字与父子关系保留，未触发重新出片，未勾选人工校对。证据 `C:/tl/correction-validation/lineage-browser-evidence.json`。

真实恢复试验任务 `990f59d0-3a12-49a4-abd9-027b77079580`：首次完成对齐并进入原生渲染后取消，再重试。第二次尝试复用摘要一致的转录和 alignment-input / alignment-raw / alignment-receipt / parent-transcript 四份证据，没有再次运行对齐，完成后产物仍能下载且 SHA256 与上述视频相同。检查中补上了原先只复用转录却没有携带对齐 receipt 的缺口；缺失或摘要变化的证据不会被当作有效缓存。证据 `C:/tl/correction-validation/recovery-evidence.json`。相同输出只证明恢复可复现，不能算作第二个创意成品。

44 项相关测试通过（`C:/tl/correction-validation/regression-tests.log`）；父子版本补充后 3 项归属/幂等/血缘/迁移测试再次通过。347 个 app 文件 mypy、后端 Ruff、前端类型及两个组件 ESLint 通过，OpenAPI 与生成类型同步。0044 SQLite 往返与 PostgreSQL 离线 DDL 通过，尚未在真实 PostgreSQL 升级。再次 fetch GitHub main 仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，未推送、未部署，主目录未提交改动未纳入本分支。

仍未完成：逐词听验和 150 ms/300 ms 目标、商品事实核验、获准后的腾力规划模型实测、语义模式到原 episode 的完整编译、全 132 组专用配方及逐组验证、音效/音乐编排与不同创意整片。CX-G01 缺原指定字体、LYO01 原合同冲突和 Hypit 多租户授权条件继续保留。当前目录仍为 5 个组有具体技术样本、2 个组失败、125 个组未实测；这些字幕进展不能提高全库运行或用户验收计数。所有新增付费模型调用仍为零。

上述网站校对与恢复接入保存于本地提交 `befae02`，未推送。

## 完整原库网页目录、试听与项目选组备忘

新增真实网页目录入口“原库目录与项目选组备忘”，完整加载 132 组并支持组 ID / 名称 / 用途搜索、画面与字幕筛选、原组详情和模板引用依赖。失败和未验证组均保留可查。编码样本、实际失败与未测状态单独展示，不使用原目录中的历史 playable 数字冒充本机运行数量。模板依赖清单明确只覆盖模板引用，原入口的硬编码或其他隐含依赖仍需原生 preflight，不能据此宣称依赖全部齐全。

197 项内置资源全部进入目录：16 字体、126 原音效、16 处理音效、14 背景音乐、14 插画、11 几何轮廓；699 外部引用全部分页保留：28 字体、670 历史素材、1 模型。外部引用显示为待本任务显式绑定；不将历史商品或人物素材当作本片证据。插画与几何轮廓也不标为商品实拍。源文件和字节没有裁减或替换。

新增仅对原包内置音频开放的鉴权试听端点，按清单 ID 定位，检查路径范围与 SHA256 后返回原始音频，支持 Range/206 和 private,no-store。字体、外部文件和任意路径不能经此端点读取。播放不会自动写“已试听”或听感通过；本轮没有把试听音乐混进工程试片。

新增迁移 0045 与不可覆盖的 `video_editing_library_notes`，按用户/工作区/项目/原库版本隔离动效和资源倾向。consider / avoid / clear 均记录理由、序号和父版本，使用唯一序号与父版本检查拒绝过期写入；请求幂等，清除倾向保留历史。列表的最新版本按每个条目选择后再分页，历史可单独读取。备忘不会修改原库或自动改变基础字幕视频，页面明确说明这一点。

规划快照接口在单次 SQL 查询中读取当前项目所有最新条目，冻结版本 ID、选择、理由与 SHA256。规划请求可以显式携带快照，原目录仍包含全部 132 组。合同检查会拒绝选中本项目 avoid 的组；consider 不变成强制数量配额，clear 不再限制选择；资源备忘也不能冒充本期事实素材。模型输出中的 locked_by_user 现在只能为 false，不能让模型自己宣称用户锁定或认可。此处是合同验证，不是已经取得模型规划响应或完成语义验收。

实际 API 遍历验证全部 132 / 197 / 699 条目及类型数量，原音频下载摘要与清单一致，Range 请求返回 206。证据 `C:/tl/catalog-validation/full-catalog-api-evidence.json`。网页在独立、空文稿/空事实/无视频的联调项目 `c092510f-c08a-4c7b-a1a5-8c996ded7c01` 中验证 132 张动效卡、43 组字幕筛选、CX-G01 失败状态保留、HY-A3 备忘连续 3 版（最后 clear）、刷新与历史；未把测试倾向写入真实口播项目。14 条原背景音乐可查，首条实际播放到 0.867 秒、readyState=4、时长 185.92 秒、无媒体错误；28 外部字体可筛选，缺少绑定的优设标题黑条目可搜索。未触发写稿、生成视频或剪辑出片 POST。证据 `C:/tl/catalog-validation/browser-evidence.json`，三张对应页面截图已检查。

真实口播项目的规划快照为 0 条备忘，摘要 `a0d158b92cf7f5c747b4f1808c0ad2e80f00f6b1bb5963cc09effd8431715793`。用本项目实际校对转录和此快照产生 `C:/tl/planning/dry-project-choices-v1`：仍含 132 组，242076 字节，最大输出 5000 tokens，没有 --execute，没有模型费用。该准备没有完成语义 worker 或全库 episode 编译。

新增 6 项目录/音频/备忘/快照/迁移测试与相关旧测试合计 50 项通过，日志 `C:/tl/catalog-validation/regression-tests.log`；349 个 app 文件 Windows/Linux mypy、后端 Ruff、前端类型和目录/剪辑组件 ESLint 通过。0045 SQLite 往返及 PostgreSQL 离线 DDL 通过，未在实际 PostgreSQL 升级。本机 API 已重载至目录版本；Compose、部署和公开发布均未执行。目录仍为 5 组样本编码、2 组失败、125 组未实测、0 组用户画面验收，没有因为网页展示和试听而提高运行或验收计数。

## 逐词语义编排到原生 episode 与网站动效试片

本轮新增 `video_editing_episode_compiler.py`，把严格 `SemanticPlan`、当前逐词转录和操作者明确制作的原生配方编译为原库的 episode / selection / bindings，不修改原引擎。语言模型只能提供词 ID、重点、关系和已存在素材 ID；配方、原生设计参数、工具路径和摆位来自可信适配端。缺配方、关系条目未绑定、原生字段不支持、字幕放错图层、来源或摘要不符均失败，不自动退回普通字幕。关系条目需明确映射实际文字或媒体槽位，多条关系不能共用一个槽位假装已表达。已知关系容量也要匹配。原 schema 不支持的关系仅保留适配层元数据，不能偷偷改成因果或宣称原审计已覆盖。

编译器校验完整 132 组目录和原 `params.schema.json`，时间只由实际词点转秒或帧。Z-M00 原景段按实际区间拆为不超过 15 秒的原生片段；整片仍连续保留原始 48.475 秒音频和原景，不压缩口播、不删除静音、不伪造单词时间。当前 sound_mode 仅为 original_voice_only，未混音。原始库的 1426 项完整性检查仍在 worker 执行；失败实例和原始文件都保留。

新增迁移 0046 `video_editing_native_plans`，编排绑定用户/工作区/项目/原片/原任务/原转录产物与摘要、原库版本、项目选组快照及配方摘要。操作者 CLI 只能导入 operator_candidate，不能声明腾力网关来源。网站只能读自己的候选、选择已有候选出片，不能上传任意配方或可执行代码。新 `native_plan` 任务沿用独立 Celery 队列、DB 领取与租约、取消和重试；复用冻结转录的精确原字节，不再识别、对齐或调模型。编排摘要损坏即失败，不走基础字幕替代路径。项目备忘变化时新任务要求先核对并保存新编排；已经提交的任务按其冻结输入执行。动效成片保存字幕文字新版本后，也不能直接复用旧词点编排出片。

候选渲染需 API 和 worker 同时显式开启 `POLARIS_VIDEO_EDITING_NATIVE_PLAN_ENABLED=true`；默认 false，Compose 仅增加开关，未启动、构建或部署。普通字幕任务保持原流程；抽出共享转录读取与选组快照存储函数，保留归属、路径、摘要、单次 SQL 快照规则。网站明确显示“人工工程候选”“语义及视觉待验收”。读取候选只是合同验证状态，不能当作已渲染或用户认可。

真实新工程实例在 `C:/tl/episode-validation`：用现有 240 单位 fa-zh 候选转录，将开头和正文保留 Z-M00，价格句按实际词点选择原 BG-S06，白字“14块9”、金字“到手两大瓶”。本期配方明确字体、几何、阅读区和静态脸部保护矩形；该矩形由当前抽帧选择，不是自动跟踪，也未完成连续听验。第一次编译使用的保护区字段 basis 不符合原合同，失败保留于 native-v1。native-v2 已运行原渲染，但原生 alpha/字角色检查发现上下行入场碰撞 26 帧；没有增加豁免或改库。仅把当前下行几何改为 lower_top=134、mask_top=124 后，native-v3 在全部 111 帧原生字幕层检查中为 0 碰撞，原生检查、原生导出及完整解码成功。静态检查通过不替代用户的视觉/听感验收。

已将 v3 编排导入为 `2089f8af-504c-43ab-9454-84ba168b8d41`，父转录任务 `eb26dcbb-e8b0-4476-8aef-33cbb4effcc8`，原片摘要 `6e90abf677e2f83f84935806faa40a4b6d519a980ee0ec32119109fed6fd53d5`，转录摘要 `ba0c92807edb79686353bb236bd780f568ad896f4118b59ffb3cc819207d1c22`。真实网页点击出片创建任务 `f24966ea-6a0c-4280-afe0-f5ff48ce4a41`，Redis / 独立 worker 1 次尝试完成。原生布局 review=passed、errors=[]、无过渡豁免；48.475 秒、720×1280、H.264/AAC，完整解码通过。最终 SHA256 `954b06e7c84670d9016fca085caa2f8927da8ed1fc2454999142427eac477119`，与 CLI v3 相同，且不同于先前纯字幕视频。网站实际播放 readyState=4、currentTime=3.946、无媒体错误；按钮下载摘要匹配。

可查看 `C:/tl/episode-validation/website-native-download.mp4`；证据为同目录 website-submission.json、website-task-result.json、website-playback-evidence.json，任务目录内 native-plan-lineage.json 记录识别/对齐/规划调用均为 0。已查看网页结果截图 `C:/tl/preflight/website-native-episode-result.png`。这是一条新动效工程试片，重复 CLI / 网页渲染不算两个创意成品；品牌“火力/活力”、商品数量价格及 A 类等事实与实际读法仍未核验，文字仍是 operator_candidate。

本轮相关回归 61 项通过，另补充的“损坏冻结编排不得重识别或退回纯字幕”与原生编排服务合计 5 项通过；354 个 app 文件 Windows/Linux mypy、后端 Ruff、前端类型和三个剪辑组件 ESLint 通过。0046 SQLite 升降级保留原行，PostgreSQL 仅离线 DDL，未做真实 PG 升级。两个历史普通/校对任务重新提交原请求仍返回原 ID，0 新任务；证据 legacy-replay.json。再次 fetch GitHub main 仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`；首次 Windows Schannel 握手失败后使用本次命令级 OpenSSL 后端重试成功，未关 TLS 校验或改全局 Git 配置。主目录 HEAD 仍 22fc356，81 项既存未提交条目未归入本分支。

尚未完成：获准后的实际腾力模型语义规划与任务衔接、全 132 组专用配方与逐组运行证据、Hypit 复合编排、原生视频素材的源时钟绑定、商品事实和逐词听验、音乐音效混入、数条不同创意成品及用户验收。本轮只增加 Z-M00 + BG-S06 的整片级证据，目录计数仍为 5 样本成功 / 2 失败 / 125 未实测 / 0 用户验收。付费调用、推送、部署和发布均为零，不能称为全库已经在网站运行。

上述冻结编排网站链路保存于本地提交 `c9db37d`。以下继续补齐原生视频源时钟。

## 人物原生画面与实际原片区间绑定

新增 `video_editing_media_clocks.py` 和字节固定的 `editing_media_clock_profiles.json`。本轮逐一核对原生 `commercial_runtime/native.py`、`unified/core/media.py` 和对应人物引擎：YYP01–07 / LYO01–04 的 presenter 使用镜头内 frame/30 秒，原 `inspect_asset` / `asset_frame` 只加一次 offset。LYO02 的入口及其导入的 base render.py 同时固定摘要。11 项是已核对的源取帧表达式，不是 11 组已经完成运行或视觉验收；LYO01 的已知原合同冲突继续存在。

原生配方新增 `media_clocks` 明确选中媒体槽和 `transcript_source_window` 策略；不得填写任意数字时间。编译器校验当前素材 ID、实际文件摘要、original_video 身份与转录原片摘要，按当前 beat 的实际首尾词点生成 offset_seconds / duration_seconds。两个原生时间字段必须留空，由编译器填入，历史数字即使附有说明也不能通过。每个选中的视频及每个原生媒体时间字段都需要具体绑定；别的素材、未知接口、改变的引擎字节、未绑定字段均失败。原生取帧仍按原库算法量化并限制末帧，没有改取帧、变速或音频。原输入合同继续保留全部 132 组，只在已核对组上显示时钟适配信息。

YYP01 / YYP02 的 style.geometry.start_frame 和 end_frame 实际是事件时间，已纳入逐词锚定字段，不再作为普通几何数值。其他几何与原生固定编舞保持当前操作者明确设计，不能把各家 start_seconds、source_start_frame 或 shift_frames 一概相加。CXBR、其他未核对接口、独立 B-roll 片段与 Hypit 媒体时钟仍需专用适配，不猜测或静默使用 0 秒。

真实新候选 `8e342ab2-5f0c-4a84-b8b8-5e70bdf9fe97` 沿用同一原片和转录，保留价格 BG-S06，在实际单瓶购买经历段（词 23–44）增加原 YYP01 人物轻推近；后段保持 Z-M00 原景。实际源区间 4870–8250 ms，原生 offset=4.87、duration=3.38、102 帧，景别事件由“花”和“的”的实际词点编译为 25 / 67 帧；未从视频开头重播。当前几何和摆位由适配端明确给出，不是模型生成代码。人物层不再重复画字幕，主字幕继续走原 episode 出口。

CLI 首次检查因没有注册本片 source asset ID 失败，原实例保留。为验证脚本新增 `--source-asset-id`，只能把当前实例里摘要一致的 input/source.mp4 注册为原片说话人卡，不当作商品实拍；新实例编译及原 schema admission 通过。网站使用数据库里原片归属和已有素材卡，不接收任意本地路径。

真实网页创建新任务 `19b7c8a0-dd49-49f9-bc15-9a5f744f01ba`，独立 Redis / Celery 一次成功，原生布局 passed、0 errors，原生导出和全量解码通过。整片仍 48.475 秒、720×1280、H.264/AAC，SHA256 `266c2566cad725f11bbe352f1e0a9e1f8330e09abff615bb329fcced31e85f67`，不同于上一条只加价格字效的整片。网页从 5 秒实际播放到 6.556 秒、readyState=4、无媒体错误，下载文件摘要一致。可查看 `C:/tl/episode-validation/website-presenter-clock-download.mp4`，证据同目录 presenter-clock-website-submission.json / presenter-clock-task-result.json / presenter-clock-website-playback-evidence.json / presenter-clock-runtime-evidence.json。已查看 6.5 秒网站截图 `C:/tl/preflight/website-presenter-clock-result.png`；连续观看、听验及文字事实依然未验收。

运行后再次核验原包 1426 项完整性，未改变原引擎或字体。新任务复用转录原字节，识别、对齐和规划调用均为 0。69 项相关测试、355 个 app 文件 Windows/Linux mypy 和后端 Ruff 通过，包含旧偏移、错源、错种类、数字时间注入、改变引擎字节等拒绝路径；单元测试使用明确不渲染的协议字节，真实视频证据来自上述网站任务，二者分开。

同时针对 CX-G01 缺失的原指定优设标题黑检查可获取文件。[优设官方公开页面](https://www.uisdc.com/uisdc-first-free-font)的搜索索引可见免费商用说明，但直接抓取返回 403，未取得官方下载包和包内许可，不据此推断 SaaS 嵌入或再分发授权。从 [FontsForWeb](https://github.com/callmeyyzx/FontsForWeb) 与 [scale-new-heights-generator](https://github.com/zhousiru/scale-new-heights-generator) 取到的两份同名文件分别为 1398644 字节 / SHA256 `32290ca978add7fe0e5281d2faba19563a43f4f2ff405a4e083fdc69553803c1`、1414784 字节 / SHA256 `e9463117dd453471fbc38cc7ed2cd90aa197db3d36ae609e3e6a294f51b124a1`，均不等于原清单要求的 `dab883d69fb713233ea5d9aff8d1f27ccc2b71e249143edf6ea08367784c5dba`。只留本地候选和检索 receipt，未绑定、未嵌入、未放入仓库，CX-G01 状态仍失败，未静默换字体。

新增发现：当前基础字幕按 20 字硬切，可能把中文数字或品牌切成“二十 / 八”等片段，已在真实画面看到。这是字幕分页规则的实际质量问题，下一步需按标点、实际 token 边界和中文数字/单位整体改善，不能把当前试片当作已完成审美验收。全库运行数量仍 5 样本成功 / 2 失败 / 125 未实测 / 0 用户验收，11 项时钟资料不提高此计数。获准后的实际腾力模型调用、剩余原生配方、音乐音效和多条正式验收片继续待实施；没有付费调用、推送或部署。

上述源时钟接入保存于本地提交 `768098e`。以下继续修正实际成片中的字幕断句和页内换行。

## 实际词点分页与原生字体换行的修复

新增 `video_editing_captioning.py`：使用固定 jieba 0.42.1 词典、HMM=False、明确的数字/金额/单位/ASCII 标记保护规则，优先标点和实际停顿，再在已有 token 与词边界之间平衡长句。顿号并列项在同一候选段内，较长列表优先在顿号后换页，避免“刷锅、”的短暂单项或“洗 / 水果”的断口。重复文字继续使用原词 ID；不增加文字、修正品牌、均分识别 token 或生成新时间。页边界仍取实际首尾 token，过长且无法合法分段的识别单位或数字标签会明确拒绝，不能截字或拆造子词时间。

新词典的 5071852 字节 SHA256 为 `7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8`，版本和字典摘要在运行时核验。词典只给文字边界，不判定事实或时间准确性。[原作者文档](https://github.com/fxsjy/jieba/blob/v0.42.1/README.md)和 [MIT 许可](https://github.com/fxsjy/jieba/blob/v0.42.1/LICENSE)已核对，原许可 1075 字节保存于 backend/third_party/jieba-LICENSE.txt，editing-worker Dockerfile 携带许可。jieba 只加入 editing 与 dev 可选依赖，API 生产二进制锁不变；再次用阻止 jieba 导入的独立进程验证当前 API/OpenAPI 可加载。未构建或部署 Docker 镜像。

试读词典时默认在 D:/Temp/a1726 新建了 9254935 字节缓存；通过精确绝对路径、字节数与本次创建时间 2026-11-08T21:47:40.1643183Z 核验后，仅移除此任务生成的文件，没有递归删除或清理用户其他临时文件。编辑分词器改用专有缓存 C:/Users/a1726/AppData/Local/TengliEditing/text-cache，并以字典摘要命名，不再使用全局 jieba.cache。原主目录仍为 HEAD 22fc356、81 项既存未提交条目，没有纳入本分支。

真实迭代 `fe4957b2-6e4c-4399-9dac-ef9833f475c6` 先解决分页，但实际清单仍把“洗水果”切成两页；该已完成工程输出保留，不当作修复完成。随后 `025b26b3-2543-4ed9-964a-43e5d3ff3e49` 分页保持 240 个单位、26 页和最短 0.58 秒，但从原生 plans/caption-layout.json 发现同页仍自动折成“14块 / 9”、末行单独逗号等问题。没有用截图缺失、退出码或分页测试替代这个实际换行问题。

新增 `video_editing_caption_layout.py`，使用本期原包内 Noto Sans SC Bold 的实际字节、字号和 Pillow 字形宽度，在允许的文字边界插入显式换行，再交给未修改的原 commercial_runtime/captions.py / libass 出口。Pillow 在此只用于原生主字幕同一字体与测量方法，不外推浏览器或 Hypit 字体。原 raw caption-anchors 保留原文字与词 ID；显示行只新增换行，不改配音、词点、字号或字体。当前字体 SHA256 `d1961be1161ea1be08496c920862d06ea5c23a757628f4fd69368de1d9f51bed`。字体缺失/改变、原子标签无法容纳、错误编排字段均失败，不自动换字体或缩字号。原画面已有硬字幕时仍关闭额外主字幕。

每个新任务增加 caption-segmentation.json 与 caption-adapter-layout.json，记录算法版本、加载代码摘要、字典摘要、字体摘要、原文、显示行、实际行宽和真实时间。worker 返回归属受控的 caption_receipt / caption_layout 产物。最终校验把适配层的每条显示行、行宽、起止点、字体摘要与原生引擎实际生成的 plans/caption-layout.json 逐项比较；不一致为 EDITING_CAPTION_LAYOUT_MISMATCH，不能作为成功成片。网页补充容量、依赖、字体与换行失败的可读提示。

最终真实网页任务 `2b511873-062d-4b1f-8ba4-61d3f9bca625` 使用原编排候选 `8e342ab2-5f0c-4a84-b8b8-5e70bdf9fe97`，独立 Redis / Celery 1 次完成，转录仍为原 fa-zh 240 个单位和同一摘要 `ba0c92807edb79686353bb236bd780f568ad896f4118b59ffb3cc819207d1c22`。26 页、240 单位依次完整覆盖；原生行宽比对 verified_against_original_caption_engine；原生布局 passed、0 errors，整片全量解码通过。48.475 秒成片 SHA256 `09e3c71276ee28e7f5e08d7643fb2dfef84a426d6c9438b192fd1b59abc7ceea`。网页实际从 8.8 秒播放到 10.364 秒、readyState=4、无媒体错误，按钮下载与最终摘要一致。

可查看 `C:/tl/episode-validation/website-caption-layout-v3-download.mp4`。证据同目录 caption-layout-v3-website-submission.json / caption-layout-v3-task-result.json / caption-layout-v3-website-playback-evidence.json / caption-layout-v3-runtime-evidence.json。已检查网页价格截图及 3.2 / 15.0 / 18.0 / 32.8 / 41.4 秒对应局部截图中的主要价格、数量、等级和并列句；“14块9”“1000克”“4斤”“A类”保持在各自同一行，“火力二十八”不再拆页。该抽样不等于连续观看或听验，不确认品牌“火力/活力”或商品标准事实。原包 1426 项再次完整性通过，新任务识别/对齐/规划调用均为 0，旧任务与视频保留。

89 项相关回归（82 项 Motion/剪辑、7 项生产锁检查）通过，357 个 app 文件 Windows/Linux mypy、后端 Ruff、前端类型和剪辑组件 ESLint 通过。协议测试使用明确的模拟转录与 Pillow 小字体字节，只验证输入/边界/容量和拒绝逻辑；真实字体、原生出口及实际视频证据来自上述网站任务，不能混作同一类证据。仍有 jsonschema.RefResolver 与 jieba/pkg_resources 的依赖弃用提示；没有因此更换原库或解除版本检查。

这一轮是同一工程候选的字幕质量修复，不算多条不同创意成品。全库依旧 5 样本成功 / 2 失败 / 125 未实测 / 0 用户验收。获准后的实际腾力模型语义任务、其余原生组配方和依赖、音乐音效、文稿事实核验及正式验收片继续待实施。未调用付费模型、推送、部署或发布。

上述字幕分页与原生换行修复保存于本地提交 `8ece88e`。以下把语义规划从 CLI 准备接入持久化网站任务。

## 独立语义任务队列、冻结输入与计费恢复边界

新增迁移 0047：`video_editing_planning_tasks` / `video_editing_planning_attempts`，与成片任务分表。prepare 只准备请求，generate 必须引用已准备记录；同一准备记录只能创建一个执行任务，由数据库唯一约束处理并发双击或不同请求编号的重复提交。任务有独立状态、尝试、租约、取消、幂等、来源转录产物与 SHA、模型名、原库版本、项目选组快照、当前素材卡和产物目录。准备完成是 prepared，不伪装 completed 的成片或模型结果。

新增 `/editing-tasks/{id}/planning-tasks`、项目规划列表、规划状态、取消、重试和鉴权产物下载，共 6 条路径。API 只持久化任务，HTTP 请求线程不连接 broker 或模型。editing-maintenance 为两个队列派送；新 `editing-planning` Celery 队列和独立 worker 负责完整性检查、实际转录读取、请求构建及获准后的生成。API/worker/下载均校验用户、工作区、项目、原片与转录归属；下载还校验规划目录范围、文件大小与摘要。响应不暴露服务器文件路径。

准备会核对原片物理文件摘要和已完成父任务的不可变转录，复制精确转录字节并保存 input-lineage。模型素材卡目前只有同一项目的实际原片说话人，标明不是商品实拍证据；卡中没有本地路径或凭据。完整 132 组、原方法规则、当前项目选组快照及实际词 ID 进入请求，词和分句的结构化时间字段不发给模型，模型仍只输出词 ID、关系与原生字段锚点。返回候选的文字和定位区间由服务器依实际词点还原，不用模型猜时间。

输入合同冻结请求摘要、转录字节摘要、原库、选组版本、模型和网关身份。网关记录只含主机和标准地址指纹，不含密钥；不接收用户信息、查询参数或片段形式的网关地址。准备后模型/选组/网关变化，以及排队期间网关或源文件变化，都会在付费提交前拒绝，要求重新准备。构建请求的代码或 schema 变化导致摘要不符也不会悄悄按新输入收费。已有执行任务的幂等查询仍返回原任务。

generate 沿用原腾力脚本服务配置，新增 feature flag 仍默认 false。任务稳定 provider 目录保存唯一的 semantic-submit-intent，尝试目录只放该尝试的转录和血缘。模型响应先保存，再解析合同；空 choices 等不合规成功响应也留存受控响应封套，不能因为解析失败重复付费。旧 worker 丢失租约后的迟到响应仍可保存，但失去租约便不能发布语义结果；新尝试可重新校验已有响应，付费开关随后关闭也不妨碍这种只读恢复。intent 已存在但响应未确认时，API 不允许自动重发；取消只能停止后续处理，不能承诺撤销已提交请求的费用。状态机的 SQLite 租约同步比较问题在单元测试中发现并以 synchronize_session=False 修正后才进行真实网页测试。

新网页“语义规划任务”可选择某条成片的实际转录、准备请求、读取固定输入、下载 JSON、查看任务、取消或恢复。界面区别“请求已准备 · 未调用模型”与“规划候选已返回 · 待核对”，生成按钮说明最大输出 5000 tokens、输入另计与网关计费。当前真实执行按钮 disabled，后端也以 EDITING_PLANNING_DISABLED / 503 拒绝 generate，不是仅靠前端隐藏。语义结果类型使用严格 SemanticPlan，locked_by_user 仍只能 false；模型候选即使通过合同，也明确为 semantic_review=unreviewed、native_render_state=not_compiled，不自动成为原生编排或确认稿。

真实网页初次联调发现嵌套 label 的可访问名称混入选项文字，已为转录下拉框明确 aria-label。实际准备任务初版 `c798f299-12a9-4f80-baaf-91b7bf270e81` 保留；网关身份冻结补齐后又从网页创建 `3253ba8e-a7fc-4136-9273-e94e999f72fd`，父任务为字幕修正版 `2b511873-062d-4b1f-8ba4-61d3f9bca625`。两次都是实际 Redis / 独立 worker 1 次处理，prepared 后刷新仍可读取，没有模拟模型结果写入真实库。

最新请求含完整 132 组、240 个实际转录单位和 1 张当前原片素材卡，243866 字节，模型 gpt-6.1-sol，网关 api.tengliapi.xyz；请求规范化 SHA256 `8b224ea988c00f920dd3aa4286b13ad9816c29d6042ea95abdbb26c6c7572027`，网页下载原始 JSON SHA256 `b4c764460a1daa65b3c22319bc07f0e2de8e3be534619bca4ca298ce0f652132`，两种序列化的对应关系已计算核验。下载文件 `C:/tl/planning/website-prepared-request.json`。证据同目录 website-planning-queue-evidence.json / website-prepared-task-result.json / website-paid-gate-evidence.json；首版证据另存 *-initial 文件。已查看 `C:/tl/preflight/website-planning-request-prepared.png`。直接调用 generate 也返回 503，未增加执行任务、未创建 provider intent，semantic 为 null、调用次数为 0。网页与产物准备成功不代表已完成实际模型语义测试，也没有在本阶段生成新视频。

101 项相关回归通过，JUnit 为 `C:/tl/planning/planning-current-regression.xml`（0 failures / errors / skipped），包含归属与路径、准备幂等、单一执行、无 broker 的请求线程、broker 断线持久化、选组/网关变更、响应不明、错误封套/JSON、租约失效、迟到响应和关闭付费后的只读恢复。模型部分使用明确的模拟提供方与协议转录，仅验证合同和调用边界，没有真实腾力模型调用，不能用它证明语义正确。360 个 app 文件 Windows/Linux mypy、变更后端 Ruff、前端类型与两个剪辑组件 ESLint 通过。旧 OpenAPI 路径和 schema 逐项结构比较均未改变，只增加 6 条路径；证据 openapi-backward-compatibility.json。0047 SQLite 升降级测试保留既存行，PostgreSQL 只生成离线 SQL，实际 PG 升级未执行。

Compose 增加独立规划 worker 和显式 provider 配置占位引用；渲染 worker 不接收该规划配置，密钥值未写入文件或日志。合并配置 --quiet 检查通过，没有构建、启动 Compose、部署或发布。当前本机 API / 规划 worker 的 VIDEO_EDITING_PLANNING_ENABLED 与 VIDEO_SCRIPT_PLANNING_ENABLED 都为 false。再次 fetch GitHub main 仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录 HEAD 22fc356、81 项未提交条目保持隔离。原 Motion 1426 项再次校验通过。

待继续：实际获准的腾力模型调用与语义验收、模型结果到可信当前原生配方的采用链路、剩余 132 组接口/变体/数字与 Hypit 复合参数、缺失字体和原合同问题、音乐音效、事实核验及正式多创意试片。全库运行/验收计数仍 5 样本成功 / 2 失败 / 125 未实测 / 0 用户验收，不能因为全量目录已进入请求而增加运行数量。没有付费调用、推送或部署。

上述独立语义任务保存于本地提交 `fb78f48`。以下继续建立已捕获模型结果到原生配方的采用边界。

## 服务器规划结果与原生出片的采用衔接

新增 `video_editing_planning_provenance.py`。可信适配端只能引用同用户、工作区和项目的已完成 generate 任务；prepare 请求、未完成任务、别人的任务或只有一份自称来自模型的 JSON 都不能取得网关来源。逐项校验准备记录、实际原片与转录身份、稳定 provider 目录中的请求/响应/语义/校验回执、唯一提交 intent、父准备产物、摘要与目录范围。请求必须保留全部 132 个原组、同一组实际词 ID 和文字、同一项目素材卡与选组快照；响应解析后的 SemanticPlan 必须与任务记录、semantic-plan.json 和回执摘要一致。

新增可信服务 `register_gateway_plan`，读取上述记录中的语义内容，不接受另传 semantic JSON；操作者 CLI 增加 `--planning-task`，与原 `--plan` 互斥。服务器任务自己提供 base task，不允许从命令行拼接另一条转录。原 `--plan --base-task` 仍只能导入人工候选，既存请求摘要和幂等编号保持兼容。原生配方仍是可信适配端明确制作的数据，不向网站开放任意配方、DSL 或代码上传；此轮没有自动生成全库配方。

采用时保存不可变规划血缘，包含请求摘要、准备及执行 ID、模型/网关身份、来源转录、选组版本和每项受控产物摘要。渲染 worker 在编译之前重新核对血缘、语义、素材卡与来源，只有一致时才把已验证语义摘要交给原 episode 编译器的网关来源检查。排队后产物被改也会停止，不能重调模型、重识别或退回基础字幕。出片侧的读取校验不依赖当前付费开关或当前网关地址，不会因为恢复或换配置而再计费。native-plan-lineage.json 保留此血缘，语义/画面/听感仍是 unreviewed。

114 项相关回归通过，日志及 JUnit 为 `C:/tl/planning/provenance-full-regression.log` / `provenance-full-regression.xml`，含新增 13 项采用测试。模型部分仍使用明确的协议提供方和 132 组协议目录；测试中途主动在原生渲染前停止，不制造视频，也不能据此证明腾力模型语义正确。361 个 app 文件 Windows/Linux mypy、变更后端及 CLI/test Ruff 通过；无数据表或公开响应合同变化。

真实本机库进行只读采用核验：两条 prepared 请求 `c798f299-12a9-4f80-baaf-91b7bf270e81` / `3253ba8e-a7fc-4136-9273-e94e999f72fd` 均返回 EDITING_PLANNING_RESULT_REQUIRED，不能冒充模型结果；两份已存人工候选按原输入重放仍返回 `2089f8af-504c-43ab-9454-84ba168b8d41` / `8e342ab2-5f0c-4a84-b8b8-5e70bdf9fe97`。核验前后都是 2 规划任务、0 generate、2 原生编排，未增加任务、成片或调用。原包 1426 项完整性再次通过。证据 `C:/tl/planning/actual-adoption-gate-evidence.json`；本机尚无真实模型响应，不能宣称此链路已完成真实模型到成片的验收。

另核对全部 HY-A1–07：原 materializer 支持 attributes 内容覆盖，但七个经典输入 schema 都把 attributes 的 properties 置空且 additionalProperties=false；实际非空属性探测均被原 schema 拒绝。只有 HY-A3 的同一原 schema 明确另列 picture-parallel-3 变体。原入口、schema 和 materializer 摘要及探测结果保留在 `C:/tl/planning/hypit-original-authoring-schema-conflicts.json`。这是七组经典作者接口的静态合同冲突，未修改原文件或绕过校验，未登记为七次运行失败；也不影响原 HY-A3 独立变体样本的既有编码证据。后续需按原合同支持的变体逐项适配，并保留经典冲突，不把缺少接口误称全库接通。

本机独立渲染 worker 重载本阶段代码后，从真实网站重新提交同一人工编排 `8e342ab2-5f0c-4a84-b8b8-5e70bdf9fe97`，新任务 `99cfba5f-7af4-495c-a2aa-8cefcfcb921f` 经 Redis、1 次 worker 尝试完成。原 BG-S06 / YYP01 / Z-M00 渲染与整片导出、全量解码、原生字幕行宽比对通过，成片仍为 48.475 秒，最终 SHA256 仍为 `09e3c71276ee28e7f5e08d7643fb2dfef84a426d6c9438b192fd1b59abc7ceea`。网页实际播放至 10.356787 秒、readyState=4、无媒体错误，按钮下载摘要一致。首次浏览器验证下载被取消，核对该验证进程的默认 TEMP 仍为 D:/Temp/a1726；显式改用 C:/Users/a1726/AppData/Local/Temp 后重试成功，没有清理用户临时目录。

可查看 `C:/tl/episode-validation/website-adoption-operator-regression-download.mp4`，证据同目录 adoption-operator-regression-website-submission.json / adoption-operator-regression-task-result.json / adoption-operator-regression-website-playback-evidence.json / adoption-operator-regression-runtime-evidence.json。已检查对应网站截图；新 lineage 字段 planning_provenance=null，明确是人工候选，识别/对齐/规划调用均为 0。该片是新版 worker 的兼容回归，与上一条字幕修正版的内容和最终字节相同，不计作新创意或新模型成片。

剩余工作仍包括获准后的真实腾力模型调用及语义采用实测、全 132 组的当前配方/原生变体与逐组运行、数字事实绑定、缺失字体和原合同冲突、音乐音效、连续观看听验及数条不同创意验收片。本阶段没有提高目录运行计数：仍为 5 样本成功 / 2 失败 / 125 未实测 / 0 用户验收；全部未验证条目保留。主目录仍 HEAD 22fc356、81 项既存未提交条目；没有付费调用、推送、部署或发布。

上述采用链路保存于本地提交 `a07f4a5`。以下开始按原生后端扩大逐组运行覆盖。

## 43 组字幕动效的当前录音批次

新增 `app.motion_native_batch`，供可信本机操作者执行原字幕组件。输入清单必须恰好列出原包全部 43 个字幕组；重复、遗漏、组与配方身份不一致、未尝试却没有阻塞说明，均拒绝。可显式选少量组复跑，余组标 not_requested，不补计为已运行。每组采用新的实例目录，沿用相同当前词点编译器、原始 job schema、原适配入口 check / render-group 及原渲染。原失败诊断保留；若只是适配校验失败，也不会编造原生失败记录。

成功登记前需要真实原生编码产物，独立 ffprobe 计数、FFmpeg 全解码与原生 RGBA 帧的逐项摘要、顺序、尺寸、alpha 非空和像素变化检查。组件样本可以是静音中性底预览，其透明帧为实际组合材料。此检查不判定表达合适、字角色碰撞、观看或听感，更不把组件预览当作整片。保存真实原生失败与只完成静态 schema 检查的区别。登记进入现有网站目录的仅为组 ID、输入和产物摘要及技术证据，私有转录/视频/组件目录没有加入公开目录或提交。

当前配方由人工按 240 单位、SHA256 `ba0c92807edb79686353bb236bd780f568ad896f4118b59ffb3cc819207d1c22` 的冻结转录逐组选词，价格、规格、表达顺序和两种用途分别采用实际出现的词 ID；事件为词起止点量化，逐字间隔及固定原生动作保留。37 组有明确的当前输入，原组字体及容量继续检查，未把旧示例句或旧秒数带入。本期清单 `C:/tl/subtitle-batch/subtitle-current-manifest-v1.json`，摘要 `5a090ea2e16fbee2598179cb010deb3323a38aff3a2271de60848e3f7610c83c`，作者脚本 `author_current_subtitle_cohort.py` 保存在同目录。6 组 AH-S03、AH-S06、AH-S07、SG-S05、BG-S10、BG-S11 未绑定指定原字体 SHA，登记 not_attempted，不替换或假装失败运行；AH-S07 原引擎还严格需要四位数字加“年”，这条录音不提供所需语义内容。

相关 11 项协议、原编译与证据测试通过，日志 `C:/tl/subtitle-batch/native-batch-tests.log`；362 个 app 文件 Windows/Linux mypy、变更模块与测试 Ruff 通过。初次 mypy 发现 pydantic-settings 的 `_env_file` 专用运行参数未出现在生成签名，已按单条 call-arg 修正静态标注；CLI 实际仍显式禁用付费规划，执行环境不传入模型凭据。

全批次原生执行已结束：37 组均完成各自当前 job 的原 schema admission、原生 check、实际 render-group、视频全解码与 RGBA 核验；6 组明确未尝试，没有适配失败或假报。累计独立核对 3455 个编码帧和对应透明帧，分别保留 job、word-bindings、compile-receipt、native-render-group、independent-validation 及原编码文件。总回执 `C:/tl/subtitle-batch/native-v1/batch-receipt.json`，结束后原包 1426 项完整性通过。BG-S06 以前已有样本，本次给它加一份新输入证据；其余 36 组首次获得实际编码记录。

真实本机 API 枚举 132 组，所有 37 条本批记录逐项按证据 ID、视频摘要和实际帧格式匹配；6 个未尝试组仍未验证，未暴露私有源、配方或视频路径。真实浏览器筛到全部 43 张字幕卡，37 张显示“有编码样本 · 未验收”，6 张显示“待实际验证”；SG-S09 原组详情显示 1 份运行记录，AH-S07 原依赖仍可查。证据 `C:/tl/subtitle-batch/website-subtitle-cohort-evidence.json`、同目录 website-SG-S09-evidence.png / website-AH-S07-dependency.png。已抽看 SG-S09 的“每瓶两斤”和“到手4斤”两个原生组件画面，未将其记为连续观看或事实认可。

本批完成时，全库为 41 组有编码样本、2 组有失败样本、89 组待实测、0 组用户画面验收；132 组 / 197 项内置资源 / 699 个外部引用仍完整。35 组统一引擎、37 组 scene、10 组浏览器、7 组 Hypit 的其余未验证输入不能由字幕批次替代。GitHub main 再次 fetch 为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录 HEAD 22fc356、81 项未提交条目保持隔离。实际识别、对齐和模型调用均为 0；未推送、部署或发布。

上述字幕批次代码与证据说明保存于本地提交 `2892097`。

## 统一引擎两种真实视频取帧路径

在既有 11 项媒体时钟配置之外，新增 Z-M01 与 W-R05 两项原生取帧配置，分别固定原入口、取帧、计划、分支和绘制代码摘要。Z-M01 使用原生页内帧 / 30 加页起点，原 asset_frame 只加一次实录源偏移；W-R05 的原 LiveFrames 直接用 actual_t = 当前帧 / 30 取画面，动作时钟的虚拟帧不用于重定时口播背景。编译回执新增原采样表达式，任一被固定的源文件变化会拒绝；没有更换原引擎、改变原声或泛化到其余多素材时钟。

Z-M01 首次输入把 overflow 误填为 fit，被原 schema 拒绝，未产生样本或运行计数。新实例 `C:/tl/subtitle-batch/unified-z-m01-v2` 改用原允许的 reject，以实录第 55–67 个 token 的 10010–13650 ms 窗口，明确使用原 B 主题和本期上部／胸前摆位，编译“14块9”和“两大瓶”两个实际短语。原生 check 与 render-group、109 帧独立解码通过，SHA256 `94384d6cb62a1029ba9c1347a71ce4c48badb0ded3d42f1b72e56a96c4a8bd6d`。在不覆盖文字的相同像素区域，抽样 f15 / f70 的实际源窗平均误差 2.2089 / 2.1477，明显低于从片头重放的 9.3549 / 14.7250 和重复偏移的 8.9493 / 21.5395。

W-R05 `C:/tl/subtitle-batch/unified-w-r05-v1` 使用 26510–31050 ms 的本片窗口，实际“旗舰店”和“正品有保障”词点分别触发原生两条字，不背书录音中的商家或商品事实。本期绑定原视频完整画幅。原生 check、136 帧实际渲染及独立全量解码通过，SHA256 `06dd475afbc68c9e7a4f3e866f45dbebc0f38d90bfa7af9e367d250478bb013e`。f20 / f95 的实测窗像素误差 2.1318 / 2.0946，低于片头错窗的 14.6151 / 9.9308，也低于 41.010 秒错窗的 9.3956 / 6.5302。两份实际组件及各自 presenter-clock-evidence.json 均保留，不作为整片或人审通过。

网站 API 确认 Z-M01、W-R05 的证据 ID、输出摘要、格式与实际产物一致，证据 `C:/tl/subtitle-batch/unified-clock-catalog-evidence.json`。全库更新为 43 组有编码样本、2 组有失败样本、87 组待实测、0 组用户验收；仍为全部 132 组。12 项媒体时钟、原生编译及批次证据回归和变更 Ruff 通过，原包 1426 项完整性复验通过，未调用模型。

## 价格标注与规格对比工程试片

新人工编排 `d222c2d6-38ce-47e7-9a23-ee719883e8a8` 从本批已实际渲染的 AHG-S02 / SG-S09 选组。开场用 AHG-S02 的黄色原生标记强调实录报价；在后续规格段把实际“每瓶两斤”和“到手4斤”分别绑定到 SG-S09 四格的前后角色，用原逐字替换区分单瓶和到手总量。此用法保留原关系审计“能力未索引”的提示，不冒充已有通用关系能力。其他区段保持 Z-M00 和完整原主字幕，尤其不为两槽模板裁掉并列用途或购买条件。该片是不同剪法，未使用旧成片或另加配音、音效、背景音乐。

真实网页提交任务 `e16fd5a2-c26c-4872-ab36-91ed2ac3e17c`，Redis / 独立 worker 1 次完成，复用同一冻结转录字节，0 新识别、对齐及规划调用。原生布局分别核验 AHG-S02 96 帧、SG-S09 201 帧，0 画面碰撞、0 过渡豁免；原生导出、字幕行宽比对、全量解码通过。该次尝试约 11 分钟，原 SG-S09 字角色逐帧检查占主要时间，尚未作并发/性能验收。整片 48.475 秒、720×1280、H.264/AAC，最终 SHA256 `552a0426018a3ff0794525300a115d62ac9b911ac22300e2cba8abcd0b83a840`，与既有报价和人物推近试片不同。

网站实际从 14.9 秒播放到 16.450597 秒、readyState=4、无媒体错误；Range 为 206，下载与校验摘要一致。成片 `C:/tl/subtitle-batch/website-price-weight-v1-download.mp4`，证据同目录 price-weight-website-submission-v1.json、price-weight-task-result-v1.json、price-weight-website-evidence-v1.json。已查看 1.6 / 15.8 / 18.9 / 41.4 秒画面，能看到报价、单瓶与到手两种文字状态和后段主字幕。本次为工程抽样，品牌、价格、重量、执行标准等事实、完整视觉和听感均待验收。

后续继续覆盖仍未实测的画面组、6 个字幕组的精确字体/内容输入、Hypit 原生变体与原合同冲突、现有原音效及 BGM 编排、获准后的真实腾力语义规划与文稿/事实验收。未推送、部署、发布或发起付费调用。

## 原库音效和背景音乐的本地网站出片

可信原生配方增加 `native_mix`，既存原声配方保留序列化和摘要。音效须指定原库资源 ID、本次用途、阶段和已编译画面事件。编译器校验资源类型、原路径与摘要、项目避用标记、取段时长，以及实际词点到原生配置事件的帧量化。音乐起止、音量变化取实测词边界或片头片尾，循环须显式允许。网站适配层写入原 episode 的 `fx`、`music`、`mix`，原生引擎负责有效起音测量、分轨、混音与编码。worker 核对原渲染回执的资源、落点、处理后文件与成片摘要、分轨与编码信号。校验通过后才发布成片和可下载的声音校验记录，页面单独标记听感待验收。此轮从可信操作者配方配置声音，尚未开放网页调音功能。

原包全部 156 个音频资源逐项校验 SHA256，并以 FFmpeg 全量解码为非空有限的 48 kHz PCM。涵盖 126 个原音效、16 个处理音效和 14 个音乐文件，142 个音效的原运行索引与资产清单路径、摘要逐项一致。证据 `C:/tl/native-audio/bundled-audio-decode-v1.json`，含独立解码采样数、峰值和原音效起音元数据。此项验证覆盖文件可用性，逐项选用和听感仍需随场景验证。

工程 A/B 采用已验证的 BG-S06、YYP01、Z-M00 画面。人工选择原短按钮声 `sfx-caca4bd9dd717c9f`，取前 0.14 秒并由原生引擎移除 20 ms 前导，绑定报价 BG-S06 `/events/upper_end`。对应词尾 1.730 秒、原生帧事件 1.723333 秒、混合音效分轨实测首个有效样本约 1.724 秒。音乐候选 `bgm-b5035a43098ee293` 从片头到片尾，基础 -36 dB、两端 0.8 秒淡化，报价及数量段按词点再降低 5 dB，随后恢复。口播维持 0 dB。此取舍用于验收声音效果，画面沿用原声对照片。

实际网页提交任务 `956c076a-8c19-4999-bd17-6bc4adb21ea7`，配方 `dfeea6dc-6e56-440b-8633-3f406852b73e`，经 Redis 与独立 worker 一次完成。整片 48.475 秒，2,326,800 个音频采样帧，编码峰值 -22.08 dBFS、无过载；原生布局通过。与原声任务 `99cfba5f-7af4-495c-a2aa-8cefcfcb921f` 的视频码流和口播分轨逐样本一致。独立解码对比，成片 AAC 与三个原生分轨叠加的误差信号相对为 -35.29 dB，实测有词区间音乐 RMS 比口播低约 13.63 dB。浏览器实播至 2.754487 秒、readyState=4、无媒体错误，Range 206。下载成片 `C:/tl/native-audio/website-sound-mix-v1.mp4` 的 SHA256 为 `9e06036b6d41d5887329f025fc82676ba2d7a95f6ec23a0b91ee4193a2fed437`，声音回执 `C:/tl/native-audio/website-sound-receipt-v1.json` 摘要为 `46a927a469a4f0b2cc6bb8985b8a0619c60373ef0ad9aba6c49a7a0ffc1a1d55`，均与网站产物登记一致。独立证据见同目录 `website-sound-evidence-v1.json`。听感、完整视觉与商品事实仍待验收，本片记作声音 A/B 版本。

30 项相关回归、变更后端 Ruff、363 个 app 文件 Windows/Linux mypy、前端类型检查和剪辑组件 ESLint 通过。无数据库迁移，原包 1426 项完整性通过。全库仍为 43 组有编码样本、2 组有失败样本、87 组待实测、0 组用户验收。本次沿用冻结的实录转录和人工画面编排，新增识别、对齐和模型调用均为 0。主目录仍为 `22fc356`、保留 81 项既存未提交改动。未推送、部署或发布。

## 实景动效批次与人物镜头整片

扩展可信批次工具支持全部 37 个实景组的名册。运行只登记与冻结转录摘要一致的本期说话人素材。通过原 schema、原生 `check` 和 `render-group` 后，再独立核对编码尺寸、时钟、全解码、逐帧像素摘要及画面变化。原生组件不另画示例字幕，整片仍由原 episode 输出完整主字幕。YYP06 的运镜和出框四个时点、LYO02 的圆蒙版时点加入实测词点字段合同，`/content/theme` 标记为 LYO02 的可绑定文字。原几何函数按 `local_frame - shift_frames` 运行，明确绑定这些几何词点时要求 shift 为 0，避免再次偏移。固定编舞留在原引擎。

本机从公开发行源恢复 `u2net_human_seg.onnx`，175,997,641 字节，SHA256 `01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c`，均与原包外部资源登记完全一致。以原来的资源 ID 显式绑定到原生进程，使用本机 ONNX Runtime CPU。YYP04 与 YYP06 分别检查 30 张和 22 张实际有效且各不相同的人像 alpha 蒙版。权重与私有本机素材只在实例中使用。[发行源代码与下载地址](https://github.com/danielgatis/rembg/blob/main/rembg/sessions/u2net_human_seg.py)

全名册 `C:/tl/scene-batch/scene-current-manifest-v1.json`，摘要 `281dabde070c8f7f0383ce7be1d2c9947f67c2beeecfbf3197c36b45b689775e`。YYP01、YYP02、YYP03、YYP04、YYP06、YYP07 实际通过，6 份 1080×1920/30 fps 组件累计独立验证 657 帧。YYP01 增一份已有组的记录，其余 5 组首次登记。YYP02 前段 f20 / f68 的实际源窗像素误差为 1.5563 / 1.5573，片头错窗为 7.8939 / 7.4466，重复偏移错窗为 6.9328 / 10.7390。批次回执 `C:/tl/scene-batch/native-v1/batch-receipt.json`，证据 `website-scene-cohort-evidence.json`。浏览器 YYP06 详情显示已有一份编码记录且未验收，更新后的本机 API 显示四个新绑定时点。原包 1426 项完整性复验通过。

31 组本轮未运行，按实际入口与素材槽保留阻塞。YYP05 等缺本期独立画面素材，CXBR / AZL 多素材槽仍需按原始采样式适配。YYO、YY6O 及 LYO02 原生文字需精确原字体，当前主机同名黑体或微软雅黑粗体与原摘要不符。LYO01、LYO03、LYO04 的原 schema 禁止 style，三者共用的原入口校验却要求 style.background 和 style.geometry。LYO01 已有早期实测失败，LYO03、LYO04 只登记静态冲突。本轮全库为 48 组有编码样本、2 组有失败记录、82 组待实测、0 组用户验收，目录仍含 132 组、197 项内置资源及 699 个外部引用。

人工整片候选 `d7ac1a99-eeb0-4203-a9d9-d6909a78b035` 保留 BG-S06 报价与既有原声、按钮声及低位背景乐。实际数量从单瓶转到两瓶时使用 YYP02（13.890–19.050 秒，缩景 89→119 帧），实际列举用途时使用 YYP06（39.110–43.110 秒，运镜 20→50 帧、出框 93→106 帧）。二者是人物视觉强调，逐项用途和数量关系由原主字幕承载。已查看浏览器四处抽帧，缩景留出背景、前景人物确实越过圆角窗底，主字幕在两个实际动作后的抽查帧可读。商品事实、语义、连续视觉与听感仍待验收。

从网站提交 `de259dbb-282e-4b2b-998a-4097205710cd`，Redis 与独立 worker 1 次完成。两段组件与批次成片字节一致，原生布局 0 错误、0 过渡豁免，原字幕宽度复核、原生混音与整片解码通过，编码峰值 -22.08 dBFS、无过载。浏览器在 16.5 秒与 41.3 秒分别开始播放，两次到 17.863847 与 42.663857 秒，readyState=4，无媒体错误；Range 206，48.475 秒的下载成片 `C:/tl/scene-batch/website-scene-trial-v1.mp4`，SHA256 `fbc5877f1046b9cede699c28dcdafb5d3961d1eb00fae424e39f0e5078d8472b`。同目录 `website-scene-trial-evidence-v1.json` 记录验证，`website-scene-*.png` 保留抽帧。

20 项相关回归、变更后端 Ruff、363 个文件 Windows/Linux mypy 通过。GitHub main 本轮 fetch 仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录 81 项既存改动保持隔离。本轮新增识别、对齐和远端规划调用均为 0。本机 API 与 worker 已更新到当前分支，无数据库迁移、推送或正式部署。

## 本期项目素材与 YYP05 双素材接力

迁移 0048 新增 `video_editing_materials`。沿用剪辑任务目录保留原始上传字节，项目、工作区和所有者三重隔离。新增项目素材分页、上传和原件预览接口。相同请求编号和相同文件及说明返回原版本，冲突输入拒绝，补充或替换通过新的素材 ID。图片复用现有校验器，视频采用既有 FFprobe 安全参数检查容器、方向、起点、分辨率和长度。初次真实视频上传暴露本机 API 缺少 FFprobe，已补本机路径及仅剪辑 Compose 启用的构建参数，缺工具有独立错误。生产容器未构建或部署。

网页“本期补充素材”可保存图片与视频、查看原件、最多勾选 24 项。准备请求冻结 ID、类型、摘要和用户填写的画面说明，模型输入无素材原件、预览地址或服务器路径。生成任务继承已准备的素材版本，首次提交前核对实际文件。可信编排只解析本项目的素材，模型来源进一步核对捕获请求中的素材卡。剪辑 worker 在尝试目录分块复制、校验文件长度和 SHA256，核对失败时不出片；血缘保留 ID 与摘要。旧无素材的请求默认值和已冻结的版本继续兼容，旧 OpenAPI 路径逐项结构一致，仅有两个新路径以及准备请求的可选 `material_ids`。

真实浏览器上传三项。A 为同一实际口播 39.11 秒起的手势取段，4.000 秒，摘要 `e4829600d05c15fb3a57dc6a27c1715c89dbd71ef2c7344ad9663b3898affd29`。B 为同片 14.69 秒起的人物近景，4.267 秒，摘要 `b16e8d16807e2a6e88d503c615b2ba7f5b33a31f73ad27a7183dc2d7cf171f7d`。另上传一张实际静帧作未勾选对照。三项鉴权读取的字节分别与上传原件一致。准备任务 `c269a7e4-7c98-49dd-b68f-3f38e72e6817` 经独立规划 worker 一次完成，保留完整 132 组、240 个实测词、口播及两张选中素材卡；未选的静帧不进入请求。网页下载的请求 SHA256 `e593e7431e06588830af5a49adb5cc884bd2ad4fd570293d0568caf508800d04`，生成入口关闭，调用为 0。

原生 YYP05 保留当前说话人 8.650–13.650 秒窗口。两个独立素材槽按原入口从镜头局部第 32、40 帧各自从头读取，持续区间按原动作计算为 3.934、3.667 秒，短于所需区间的补充视频拒绝。二者原件取段与本片说话人时钟独立。150 帧原生组件全量解码和变化检查通过，两个槽各比对 f70、f115 的实际画面，正确取帧的像素误差 1.60–1.81，片头重放或错用镜头时钟的最小误差 5.65。独立原生样本和网站任务的 YYP05 组件字节一致，SHA256 `2942e07be2946666ca265dc0f0250a97e47f08a949362a54d495f2e73de49c8a`。证据 `C:/tl/project-materials/native-yyp05-v1/independent-validation.json`，网站登记 ID `be20e6080e0a499f98668c64da600a78`。

人工整片编排 `6c803203-fee1-49be-89f7-d30e39413962` 保留 BG-S06、YYP01、完整主字幕、口播及既有混音，在第二次报价前加入 YYP05 的两个取段。两段画面均来自本期实录，可用于对照三个取帧时钟，商品实拍和链接证据仍缺。网站任务 `4c022834-905a-40e9-8407-027b3217a9cd` 经 Redis 和剪辑 worker 一次完成，原布局无错误或过渡豁免，字幕宽度、混音和整片解码通过。浏览器实播从 9.05 到 11.305231 秒、readyState=4、Range 206，下载与原产物摘要一致。成片 `C:/tl/project-materials/website-yyp05-trial-v1.mp4`，48.475 秒，SHA256 `cc2cbe29f82f287a7812ec01f691b14d3ceb312b0e77fe11600b4d2d4380f285`，证据 `website-yyp05-evidence-v1.json`。抽看三个画面状态，完整视觉、语义、商品事实及听感仍待验收。

57 项相关回归含跨项目、跨用户、幂等冲突、同尺寸文件改写与素材过短，全部通过。后端 Ruff、Windows/Linux mypy、前端类型和目标 ESLint 通过；0048 在实际 SQLite 库备份上升降级保留既存 15 项成片任务，PostgreSQL 离线 SQL 已生成，合并 Compose 配置验证通过。原包复验 1426 项，全库当前 49 组有编码样本、2 组有失败记录、81 组待实测、0 组用户验收，仍完整登记 132 组、197 项内置资源和 699 项外部引用。GitHub main 仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录保留 81 项既存改动。本轮无新增识别、对齐或付费规划调用，无推送或部署。

## 35 组统一引擎名册与原生切点

批次工具增加 unified 名册和本期项目素材解析。名册仍须覆盖全部原组，每个缺项单独记录。传入的项目素材为已注册 ID，数据库以当前原片归属查找，素材摘要逐项复核。另从同一真实口播提取 10 张可追溯静帧和 1 张原权重生成的透明前景，并用本机项目素材接口保存原件。静帧展示本期讲述者，涉及商品或使用效果的陈述仍是实录待核对内容。Z-M07、Z-M08 的原图板键是固定媒体槽，编译器保留槽名并填入本期素材，模型文字绑定合同移除这些键。

八个统一引擎视频槽增加原始源时钟配置，分别固定 Runtime11 及 Build12 原入口、取帧与调度字节。Z-M06、W-R10、W-R16 增加按切点编译独立素材区间的专用配置，所用起止必须有实测秒制事件绑定。原代码以 `local_time - cut` 采样，网站编译器只设置该原切点对应的原片起点一次。Z-M06 使用 8.650–10.010 秒、实录静帧和 11.110–13.650 秒三段；W-R10 首视频窗口为 10.010–11.110 秒，后续两段为同句静帧；W-R16 两段源视频为 39.110–39.770 与 42.210–43.110 秒，中间三张为同段静帧。Z-M06 和 W-R16 各抽两帧独立对照，实测窗口的像素平均绝对误差为 2.17–5.64，错窗最小误差为 9.01。逐帧比较由本地程序执行。

名册一 `C:/tl/unified-batch/unified-current-manifest-v1.json` SHA256 `785a1aa945044084b1326be8f5ca4ff2b579113e7c5e2777970b9e35e526cf2e` 实际运行 20 组，18 成功、2 失败、15 未试。切点名册 `unified-current-manifest-cuts-v1.json` SHA256 `dad0ec193036d366b5f568237938a52e46a0a0a6d1d7c5ab1fc73e95b54eb55e` 补跑 3 组并全部成功。合计 21 份 540×960/30 fps 新组件，独立验证 3269 帧。Z-M00、Z-M01、W-R05 原先已有记录，其余 18 组首次有编码样本。两个批次回执位于 `native-v1` 和 `native-cuts-v1`，实际网站目录逐组匹配摘要、格式和技术状态，证据 `C:/tl/unified-batch/website-unified-cohort-evidence.json`。

W-R09 在原生入口缺少 `silhouette-0.png`，原登记 `media-fbca4ecbc2aead9960b3`。W-R18 烟雾入口缺少 `smoke-00.png`，原登记 `media-f771ec9d4f387028c4c8`。两项均保留原诊断、输入与资源身份，原位没有替换文件。剩余 12 个统一组分别登记需要的本期产品素材、外部证据、双语或章次依据、数字容量和原关系。全库 API 当前为 67 组有编码样本、4 组有失败记录、61 组待实测、0 组用户验收，132 组 / 197 个内置资源 / 699 个外部引用完整保留。原包 1426 项完整性复核通过。

35 项相关回归包含当前照片槽映射与错切点回归，变更 Ruff、365 个文件 Windows/Linux mypy 通过。GitHub main 本轮重新核对仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`。本机 API 与两个 worker 已重新加载当前代码，付费开关仍关闭。无新增识别、对齐或远端规划调用，无数据库迁移、推送或部署。

### 统一引擎整片与主字幕避让

人工整片保留 BG-S06 报价和 YYP01 先前经历，在 13.890–21.350 秒使用 Z-M11 方格纸与本期透明讲述者，用两行实录词分开“每瓶”和“到手”规格。在 39.110–43.110 秒使用 Z-M14 实录圆窗及用途短词，主字幕仍保留四项及完整原话。原声与已验证按钮声、低位背景乐继续由原生引擎合成。

初版任务 `b953ca07-3684-4b6b-8f44-d4b7db4ec510` 原生布局检查通过，成片抽帧仍发现 Z-M14 场景内的大字和主字幕重叠。原检查可量字幕组 RGBA 与主字幕，场景内已合成字还需单独核对。新编排 `c8d8c530-d3c1-41e4-993c-738b8eb768ba` 使用原生 `typography.caption.layout_overrides`，只将起于 39.11 和 40.77 秒的两条主字幕基线从 1024 移至 1200，给本期本机试看留出底部读区。字幕文字、切点、其余字幕位置均逐条比对一致。对 Z-M14 的 120 帧实码进行画面区域及主字幕墨迹核对，原有 70 个重叠帧在修订后取得最小 16 px 竖向间距；两条新统一引擎组件与首版及批次的字节一致，编码音轨也与首版相同。图 `C:/tl/unified-batch/website-unified-v1-overlap.png` 和 `website-unified-v2-42.8.png` 可核对具体改动。社交平台叠加控件区域、连续画面和听感仍待验收。

修订任务 `99964c5d-a05a-4db8-934b-79b9da7a9644` 由真实本机网页提交，Redis 与独立剪辑 worker 1 次完成，原字幕行宽、原生布局、混音和整片解码通过。实际浏览器分段播放到 19.415505 和 42.505227 秒，readyState=4、Range 206、无媒体错误。网站下载成片 `C:/tl/unified-batch/website-unified-trial-v2.mp4`，48.475 秒，SHA256 `b517ccf943f95a60093a58f53b46457b3b591b9f4b6785c5a62647da900f58f5`，证据 `website-unified-v2-evidence.json`。实录中的商品规格、表达与听感均待人工核对，本次没有模型生成。主目录的既存 81 项改动保持隔离。

## 浏览器原生三卡与运行依赖

新增 browser 批次入口，读取原 10 组完整名册，记录实际使用的 Chrome 摘要。组详情分别显示本期素材槽、原入口登记的字体引用和可选的原包字体。原组的入口、模板和历史引用全部保留。原档 1426 项完整性复核通过。

CX-G07 逐字绑定“洗碗”“刷锅”“洗水果”。三个原入场关键姿态由实测词点 39.770、40.190、40.770 秒驱动，末卡收定使用 41.990 秒词尾。三条轨迹按同一分段时钟插值，原刻度 `[0, 3, 24, 42, 54, 61]` 对应本期局部帧 `[0, 20, 32, 50, 86, 119]`。87 个原姿态的坐标、卡片尺寸和原画幅保留。适配层按组检查入口与模板摘要，拒绝丢失、乱序或量化后同帧的锚点。原接口允许选字体，本期明确选用原包 Noto Sans SC Medium，并在网站 worker 核对原包摘要及标签的 6 个不同字符。实际渲染走原 `city` 分支，原 `food` 槽也用本期素材绑定，单独渲染仍待实测。卡图与背景均为本期人物静帧。

名册 `C:/tl/browser-batch/browser-current-manifest-v1.json`，SHA256 `9a7fd4c6ae1b5c230aacef75a7985001f7b4700fc6fd6ec707b3aec103b23c82`。一组完成原生渲染，720×1280、30 fps、120 帧全量解码并取得 120 种解码帧摘要，组件 SHA256 `e036a21af7e26513240bf8ba8cb336135bf73dfa1699074dbf5a38ee9f7b3fed`。另九组本次逐项登记为未运行，具体依赖见 `native-v1/batch-receipt.json`。

- CX-G01–03 共用入口缺原优设标题字体 `font-dab883d69fb71323`。
- CX-G04–06 共用入口缺原宋体 `font-346c3d9c8c827faa`，G05 另需原活动背景序列。
- CX-G08–10 共用入口缺 `font-db575410c0444da5` 和 `font-500d96e599576ffb` 两套励字字体，G09、G10 另需原活动背景和素材。

CX-G07 此前已有单组编码记录，本次新增实录词轴证据。41 项相关回归全部通过，涵盖共享时钟、重复落点和原坐标修改拒绝。变更 Ruff、Windows/Linux mypy、前端类型和目标 ESLint 均通过。GitHub main 复核仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录既存改动与本轮隔离。本机 API 与两个独立 worker 已重新加载代码，两项付费规划开关关闭。

人工编排 `6e5d036e-aabf-4b98-8a2f-5a66363d11bc` 保留原实录、BG-S06 报价、YYP01 旧购买经历、按钮声和低位背景乐。39.110–43.110 秒加入原浏览器三卡，只把此段两条主字幕移到卡片上方，完整保留第四项“蔬菜”。对 120 帧组件核对原姿态、三张卡片实际画面和两条原生主字幕墨迹。111 帧有主字幕，最小竖向间距 46 px，中间 0.3 秒实录停顿无字幕。抽看首卡入场与末卡落定，原轨迹按左、右、中接续，最终画面按左、中、右排列。整片仍待连续视觉、听感及商品事实验收。

本机网页实际提交任务 `4d5efd9e-1e57-49d2-af8a-b8cd20cba0ea`，Redis 与独立剪辑 worker 一次完成。整片解码、原字幕与混音技术检查通过，三卡组件与独立原生样本字节一致，编码音轨与原生混音试片一致。网页从 40.0 秒实播到 42.265 秒，readyState=4、Range 206、无媒体错误。网页下载 `C:/tl/browser-batch/website-browser-trial-v1.mp4`，48.475 秒，720×1280/30 fps，SHA256 `cfc61c8bde0b86801b006f7b0ad28f81cacdce15eef29a1d207a979531f16a27`。证据 `website-browser-evidence-v1.json`，含网页实际详情、字幕间距和无新增识别、对齐或模型调用。全库 API 当前 132 组，67 组有编码样本，4 组有失败记录，61 组待实测，0 组用户验收。无推送、部署或迁移。

## HY-A3 原生三图变体与本机整片

七个 Hypit 经典入口的原 schema 都将 `attributes` 定义为封闭空对象。网站和完整模型目录登记该冲突，六组未试，HY-A3 的经典变体也保留该状态。本轮只编译 HY-A3 同一原 schema 已定义的 `picture-parallel-3`，从原 schema 读取可绑定字段，继续执行原校验、原 `stagger` 组件和 Hypit Build/get。原包 1426 项完整性检查通过。模型收到的本期参数范围包含三张图及三个入场锚点。

本机三图变体默认关闭。API 和剪辑 worker 分别限制到配置的单个内部工作区、开发鉴权及 development/test 环境。CLI 与 Chrome 路径由服务器配置，worker 核对 Hypit 0.2.12 及入口摘要，计划与素材不能提供 Hypit CLI。原安装包许可涉及第三方托管与多租户授权。`POLARIS_VIDEO_EDITING_HYPIT_INTERNAL_WORKSPACE`、`POLARIS_VIDEO_EDITING_HYPIT_LOCAL_MODULE` 和 `POLARIS_VIDEO_EDITING_HYPIT_LOCAL_CHROME` 只配在本机联调。原 Build 结束后，外层适配调用原 CLI 停止本任务自己的 Runtime worker。许可依据见 [Hypit 0.2.12 原发布包](https://registry.npmjs.org/@hypit/hypit/-/hypit-0.2.12.tgz)。

三图分别取同一实录讲述者静帧，对应“洗碗”“刷锅”“洗水果”的词首 39.770、40.190、40.770 秒，计算局部第 20、32、50 帧。源背景与可选实时人物在本次均取 39.110–43.110 秒。编译检查三项与图槽、词首的一一对应，三张图的字节互异，末卡落定后有读取区间；运行时保持原三图从上方落下。主字幕仍保留包含“蔬菜”的原句。本期用途画面为人工工程编排，三图展示本期讲述者，商品实证仍待核对。

独立名册 `C:/tl/hypit-batch/hypit-current-manifest-v1.json`，SHA256 `777dfd7297fece0eebb89369d6e4f1145e744afe2c13feef66bc7d6ce01f2164`，7 组全部登记，1 组运行成功，6 组保留经典合同阻碍。HY-A3 原 Build `bld_20261109T011610134Z_F62FC21D89` 得到 360×640、30 fps、120 帧，完整解码有 120 个不同帧摘要，组件 SHA256 `db35391ca2358381389918b3cd38f96caa5ec2bbb7e1801c9b334eaf7098a506`。初版网页任务 `9b2ec936-e27f-45a6-b604-bbef28deb90a` 与独立组件字节相同。初版字幕基线 1210，原生墨迹距卡片 26 px，网页暂停时控件盖住字幕，因此保留初版作为布局对照。

修订版编排 `5059c1ac-89aa-405e-a386-4e121bd5072e` 抬高并缩短本期三卡和人物框，保留原入场机制及词点。39.11 和 40.77 秒起的两条主字幕基线移到 1060。对原字幕墨迹与卡片范围复核，最小竖向间距 32 px。网页暂停实拍截图 `website-hypit-v2-first-entry.png` 和 `website-hypit-v2-three-cards.png` 均可完整读取主字幕。对 f12、f62、f96 分别独立比对实际源帧，正确窗口的像素平均误差 1.35–1.45，错窗最小误差 5.16。成片三槽中各自正确静帧的误差 5.38–5.58，错槽最小 8.35。抽查范围是布局和素材时钟，连续视觉、听感及商品事实仍待人工验收。

修订网页任务 `93250b75-44cf-4ffc-8f00-c80fec703b6a` 经独立 worker 一次完成，原 Build `bld_20261109T012403512Z_5A8AA295AC`，独立解码 120 帧。实际原计划报告 7 项本地请求、0 项远程供应商请求，任务结束后 Runtime worker 状态为 `stopped`。原字幕和混音检查通过，编码音轨与混音试片一致。Chrome 实播到 42.048 秒、readyState=4、Range 206，实际网页下载 `C:/tl/hypit-batch/website-hypit-trial-v2.mp4`，48.475 秒，SHA256 `a7dd9517ca8618b336bab2bdd94d03d1a390243d40a4c1c918b5acbe16d02918`。证据 `website-hypit-evidence-v2.json`。全库保持 132 组，67 组有编码样本、4 组有失败记录、61 组待实测、0 组用户验收。本轮新增 HY-A3 的本期网站出片证据，组数按首次样本统计。

48 项相关回归通过，覆盖三图词首与素材槽绑定、重复素材拒绝、阅读区间、内部工作区范围、生产及外部鉴权拒绝。变更 Ruff、367 个文件的 Windows/Linux mypy、前端类型和目标 ESLint 通过。GitHub main 仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录既存 81 项改动隔离。无新增识别、对齐、远端规划调用、推送、部署或迁移。

## 网站出片前调整音乐与指定段落

候选卡新增“调整本次出片”。有背景音乐的候选可沿用、降低 6 dB 或关闭。降低只改原轨总增益，保留时间窗、淡入淡出和原包络；关闭时原生计划不加入背景音乐。已具备原生配方的段落可按稳定 ID 选择保留原景。编译器在该段实测起止内使用原 Z-M00 和本期人物画面，保留主字幕与源音频，移除只绑定到该段动作的音效。若本项目备忘明确排除 Z-M00，段落入口关闭。

调整作为本次任务的类型化选项入库，幂等摘要包含规范化段落 ID 和音乐模式，重试从同一任务取值。API 和 worker 分别核对所选音乐、段落及候选版本。冻结的语义、配方和转录保留原身份，编译记录另列所选段落的前后组 ID、词 ID、原时间与本次用户锁；声音记录列出移除的原音效及音乐决定。网页保留任务选择并提供调整记录下载。关闭的段落不会触发只为该段准备的素材读取，其他使用中的项目素材继续检查原件摘要。新增 OpenAPI 合同兼容旧请求与任务；沿用既有选项 JSON 字段。

在独立本机联调库通过网页实际提交同一人工候选 `6e5d036e-aabf-4b98-8a2f-5a66363d11bc` 的两份调整。关闭音乐版任务 `0dae13d8-f784-4ef2-9bd0-d7a8b08e25b3` 在 1.090–4.790 秒将 BG-S06 切回原 Z-M00，保留原句主字幕。声音分轨验证 BGM 轨无输出，移除该段原按钮音，音效轨解码为全零。独立抽帧对比报价区域，改后与原片误差 3.59，原花字版与原片误差 9.70。实播与网页下载 `C:/tl/render-edits/website-edits-off.mp4`，SHA256 `9a89a5bcfe256ab17e397bfaeb200a4d50a507eeb9b14d5ed4f3d12964dd65a6`。

降音乐版任务 `1016397e-0f04-4f3e-a18f-207aef95dc7c` 保留原编排画面、主字幕和音效。原生 BGM 轨实测降低 6.0000 dB，编码视频流和音效分轨摘要与原版一致。实播与网页下载 `C:/tl/render-edits/website-edits-lower.mp4`，SHA256 `f18aae8185f8c659fa449e4b2c163c30e7cb5ed56bf3666998aee03006331d73`。两版各 48.475 秒，分别由 Redis 和独立 worker 一次完成，均保持原声分轨、冻结文档与字幕行，分段读取 206、播放无媒体错误，下载与任务摘要匹配。同一请求重发返回原任务，改变选项后使用同一请求号返回 409。证据 `website-edits-evidence.json`，浏览器暂停截图 `website-edits-off.png` 与 `website-edits-lower.png`。听感、完整画面和商品事实仍待验收。

34 项相关回归通过，Windows/Linux mypy、Ruff、前端类型与目标 ESLint 通过。OpenAPI 原路由内容保持一致，变化限于剪辑选项和候选数据合同。验证用网页 `http://localhost:4312`、API `127.0.0.1:8312` 与独立 SQLite 库、Redis 逻辑库。GitHub main 复核 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录既存 81 项改动隔离。无新增识别、对齐、模型调用、迁移、推送或部署。阶段 3 的代理预览、确认高清，以及换素材或重点等更细操作仍待继续。

## 连续人物底片、可重复的动效组合与代理确认

按用户追加的画面要求，网站模板预览在同一原片画布上从 0 秒连续合成，保留原音。编译只接受原库能输出透明层的字幕动效，原景段直接使用原生 exporter 的连续底片。初始规则经用户调整为至少五种不同原生动效，优先十种以上。重复用组以不同段落 ID 和词点记录，出现次数与种类分开。整屏演示候选留作原引擎验证，网站新模板入口对这类候选显示适配状态。用户提供的模板截图用于选择交互，必火工作台链接无法直接读取，参考范围为截图和公开说明。 [必火 AI 官方说明](https://avatar.bihuoai.com/)

网站新增“价签与规格对照”和“滚动报价与规格对照”两套可选动效组合。选择随规划任务冻结，生成请求保留 132 组目录、实际词 ID、选中的模板与可用原素材身份，模型只在模板槽内选组。适配器校验捕获模板与导入原生编排一致。网页实测两套准备请求 `7a9f2dca-de79-446a-9cba-1d8da4f57b77`、`38dc1f6b-0278-4be5-9026-85513f51ff2b` 使用同一份 240 词转录，模板不同则请求摘要不同。两份均为 `prepared`、0 模型请求。证据 `C:/tl/preview-delivery/template-prepare-evidence.json`。模型结果的模板配方目前由可信适配流程提供，自动构造本期配方与逐套画廊样片仍待继续。

代理从原生渲染并完整校验后的文件生成，缩放长边至最多 640 px，复核帧数、帧率、音视频起止与 AAC 字节。待用户确认时只公开代理和相关回执，高清文件的 ID 与地址留在内部。网页提交代理 ID 和摘要；API 检查归属、两份文件与摘要绑定，在同一事务开放已经校验的高清。重复确认同一代理返回同一结果。确认只开放交付，语义、视觉与听感状态仍为待验收。此实现预先渲染高清来保持原生版式与代理画面一致，确认阶段不重新渲染。历史 API 成片继续按原模式可读。

实录编排的第二次报价改绑完整短句“给你发两大瓶”，按本期实际六字配置原容量检查。适配器在 Windows 子进程复用只读原字体实例，避免规格对照反复打开 Unicode 字体时耗尽内存。三个可对照原片段的编码字节与修复前一致。重试后 11 处原生片段均完成，整片版式门禁拒绝了 SG-S03、AH-S05、JJ-S01、SG-S10 的 131 帧内部文字重叠。人物保护区和主字幕碰撞为零，该轮没有交付可播放成片。

第三版保留同一实录词轴。SG-S03、AH-S05、JJ-S01 沿用原字体和机制，按现有角色调整字号或阴影。滚动报价模板更新到 `roll-compare-v2`，用原 AH-S09 的分区标题和说明表达下单前提。已冻结的 `roll-compare-v1` 仍按原内容读取，SG-S10 保留在原库。四段原生角色预检分别检查 48、138、137、144 帧，均无重叠。组合候选仍为 10 种动效、11 次出现，两次报价独立绑定实际词点。预检结果保存在 `C:/tl/preview-delivery/refinement-v3`。

修订后的两套模板经 Chrome 实际选择和提交准备。价签 `3dbf44d9-200c-42cc-9da5-74e87d0a13a6`、滚动报价 `3af5bae2-c07d-4f39-9dd5-3a6dec29d12c` 均冻结了各自的版本和 132 组目录，复用相同的 240 个实测词 ID，无新增模型请求。证据 `C:/tl/preview-delivery/template-prepare-evidence-v3.json`。

实录第三版候选 `7ead8812-ee5c-4160-9b1d-158778abd1e1` 由网页提交任务 `06f9017f-ff64-4a5c-b0aa-239c5b62c393`。独立 worker 一次完成，使用连续人物原片、原声与 11 处原生透明层，覆盖 10 个不同组。BG-S06 在 0.410–4.790 秒和 8.650–12.430 秒的实录片段各使用一次。完整原生版式检查 11 处可见，0 项碰撞，0 项过渡豁免。另从实际高清编码画面抽样复核每处叠加，22 个同位人脸样本的像素绝对误差均值最高 6.55/255，11 个动效段均检测到与原片相应的人脸运动。独立解码 11 个动效段及整片，对比原音的最低波形相关度为 0.999983，16 kHz 下最佳样本偏移均为零。末尾沿用原生约 0.4 秒画面淡出，本期未启用配乐或音效。

代理 360×640 和高清 720×1280 均为 48.475 秒、30 fps、1454 帧，编码 AAC 音轨摘要相同。Chrome 代理实播至 2.925 秒、高清实播至 41.367 秒，无媒体错误，分段读取返回 206。确认前以实际高清 ID 读取返回 404，错代理摘要返回 409。网页确认后下载同一份已校验高清，重复确认无新 worker 尝试。下载 `C:/tl/preview-delivery/website-continuous-hd-v3.mp4`，SHA256 `73979247975de6b7c27dbf26f7300436fc05d3283e918bb2e2ac6f29669ab76d`。代理 `C:/tl/preview-delivery/website-continuous-proxy-v3.mp4`，SHA256 `4444045c61de4aa04688e377f2fc42403349f110f7ce8cb820e60b9dfe18b7ce`。核对记录 `continuous-delivery-evidence-v3.json`、`continuous-speech-evidence-v3.json`，人工检查 4 张暂停画面。整片观感、听感和商品事实仍待用户验收。

最终 51 项相关回归通过，Windows/Linux mypy、Ruff、前端类型与目标 ESLint 通过。GitHub main 仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录既存 81 项改动隔离。原 132 组和资源未修改，无数据库迁移、付费调用、推送或部署。当前试片为按实录词点人工配置的滚动报价模板，其他风格成片、模型到模板配方的自动生成、全库视觉验收仍待继续。

## 手机画幅的字效尺寸与原生前后叠字

用户反馈部分字效过小，也提示叠字可能属于设计。核对原 `BG-S04` 入口发现，它按 576×860 的原生画布布局左右竖排。第三版将整个透明画布缩进胸前的横框。第四版给左右竖排独立的高画幅区域，普通字效扩大胸前投影。沿用原生帧预检显示，BG-S04 的有效字层联合宽度由 190 增至 440 像素，SG-S09 由 138 增至 184，SG-S03 由 289 增至 385。预检逐帧检查可见墨迹未超字幕安全区或进入本片抽帧确定的人脸区域，证据 `C:/tl/preview-delivery/projection-preflight-v4.json`。

原 `SG-S10` 的渲染源码明确将红色横句叠到灰色背衬字前。第四版按本期真实词点恢复该组。网站适配层只处理受信编排显式指定的 SG-S10 字幕层，核对固定原渲染器和原检查源码摘要，先完整执行原版式检查。仅当所有失败项均来自指定镜头的 `lead/accent` 角色对，且发生在前景开始之后，适配层才将它们单列为设计叠字。原 `layout/review.json` 保留，独立版式记录提供原报告摘要与每帧叠字。出现人物保护区、主字幕、其他透明层或其他角色碰撞时，原失败继续阻止出片。无全片例外，无原库源码改写。

第四版网页任务 `2d71f335-8625-45de-b761-f7930547fa85` 经 Redis 与独立 worker 一次完成。实际原生 BG-S04 有效墨迹联合宽度 419 像素，为第三版的 2.21 倍，SG-S09、SG-S03 实测为 184、385 像素。11 处原生层均可见，10 个不同组，BG-S06 继续在两处词点复用。原检查的 55 帧角色交叠均为 SG-S10 前景与背衬，适配后其余撞字为 0，原生过渡豁免为 0。布局原报告 SHA256 `1ad0b65ad7f2647902d439558a2173dd7d76086a524f1349b020a595def721e4`。实录用途段 8 张原片抽帧、22 个高清同位面部样本及全部 11 处编码叠加核对通过。各动效段和全片独立解码对比原声音频，最低相关度 0.999983，最佳样本偏移均为零。

Chrome 实际播放 360×640 代理、确认后播放 720×1280 高清并下载。两版 48.475 秒、30 fps、1454 帧。确认前隐藏高清、错摘要拒绝、分段读取 206、重复确认无新渲染。高清 `C:/tl/preview-delivery/website-continuous-hd-v4.mp4`，SHA256 `9c11b040229592d7fbdf0849e4e41604140f6995e1c62433b6385eebe7e4f9eb`。代理 `C:/tl/preview-delivery/website-continuous-proxy-v4.mp4`，SHA256 `2f423ea0902dbaaf335dad543568e00c57b2581799da13b4a8099aa8ae8dfd72`。实看 42 秒两侧竖排与 47.2 秒前后叠字，记录 `continuous-delivery-evidence-v4.json`、`continuous-speech-evidence-v4.json`。字号与整片观感待用户验收。

57 项相关回归通过，Windows/Linux mypy、Ruff、前端类型及目标 ESLint 通过。原库 1426 项完整性复验通过，132 组、197 项内置资源、699 个外部引用完整。主目录 81 项既有修改隔离，GitHub main 复核 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`。无新增付费调用、迁移、推送或部署。另用原目录与该实录词轴离线重建 11 份配置，除各实例的输出路径外与本次实际编译配置逐项相同，证据 `C:/tl/preview-delivery/template-reconstruction-v4.json`。这项结果验证配方重建，网站仍未启用模型结果自动采用。

## 从保存的语义规划生成模板配方

语义规划任务卡新增“生成原生编排”，调用 `POST /editing-planning-tasks/{task_id}/native-candidate`。服务重新验证工作区归属、已完成的请求和响应、实录转录、原片身份、模板版本与选组备忘，从原库输入结构及合同生成透明字幕层配方。浏览器只提交既有规划 ID，无配方或脚本字段。每处的文案和绝对动作事件继续由现有词点编译器计算，原生时钟间距、字体等保留原组或使用已复验的网站模板参数。模型生成结束后由用户触发此步骤，生成候选本身无模型请求，也不直接触发渲染。以同一规划和配方版本确定候选请求编号，重复点击回到同一候选。

模板编排须保留至少五种不同原组。可在多个段落复用同一组，独立保存各段输入。缺少原生文字或动作词点、关系项、角色容量不合适、选择了需要其他适配的字段时，返回明确错误。纯文本模板保留连续人物原片和原声，主字幕字号按实际输出尺寸计算。当前用居中竖屏的静态保护区，偏离居中构图的影片需通过预览核对。对 SG-S10 继续使用已验证的原生叠字分类。冻结模板和旧人工配方沿用原来源合同，无数据库迁移。

在 `C:/tl/auto-overlay/acceptance.db` 复制的独立联调库回放本期 240 词实录。价签模板前两处报价分别用 AH-S09 的标题加黑条说明与 JJ-S03 的原生句内放大，和其余 9 组组成 11 种动效。全 11 项输入通过原入口检查，两项新选组的独立角色检查通过。用确定的本地协议响应经真实规划 worker 保存，准备及执行请求包含 132 组目录，真实外部模型调用为零。规划 `3d9d0e65-ff6c-416a-9521-b55286ae33d6` 经浏览器提交自动编排 `f0f5aee1-52a2-40f7-92cf-34931c75e83f`，重复提交返回同一 ID。通过浏览器提交剪辑任务 `b197ef5c-6aba-475b-8177-31d4486b55e7`。协议回放用于验证数据链路，真实模型对内容的判断仍待另行验证。

独立渲染 worker 重新核验了保存的规划响应摘要和同一实际转录，一次完成。11 处原生层与 11 种不同组均在编码画面逐处验证，版式检查记录片尾 SG-S10 的 55 帧设计叠字，其他碰撞和原生豁免均为 0。22 个同位人脸样本的最大像素误差均值为 6.575/255，11 个动效段均保留了原人物运动。11 个动效段及全片独立解码音频，最低波形相关度 0.999983，16 kHz 下最佳样本偏移均为零。已抽看开头价签、链接句内放大和片尾叠字，整片观感、听感与商品事实待用户验收。

Chrome 实测播放 360×640 代理、确认后播放并下载 720×1280 高清。两版各 48.475 秒、30 fps、1454 帧。确认前隐藏高清、错误摘要拒绝、Range 206、重复确认无新 worker 尝试。高清 `C:/tl/auto-overlay/website-label-hd.mp4` SHA256 `310390cae4c3262b4de3bc8c633d49c1568d49cc003d38675fa11768b0c2ec69`。代理 `C:/tl/auto-overlay/website-label-proxy.mp4` SHA256 `3925335b8cee5a5f2596a2f15239d674a74f367efe9a1aa95e1572c2a57ac178`。证据 `capture.json`、`submitted.json`、`website-label-evidence.json` 和 `website-label-speech.json`。

59 项相关回归通过，Windows/Linux mypy、Ruff、前端类型与目标 ESLint 通过。OpenAPI 只新增编排入口，旧路径和组件逐项保持一致。GitHub main 仍为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录 81 项既有修改隔离。无外部付费调用、迁移、推送或部署。当前自动配方覆盖这两套模板的原生文字组，其他原组继续完整登记，模型语义与全库视觉验收仍待推进。

## 晨曦素材排版原生双时钟

补齐 CXBR02–05 的网站适配。适配器固定每组原入口、媒体取帧及其原生辅助代码摘要。说话人使用实录词点绑定的绝对区间，补充视频为本项目独立登记素材，源时钟从 0 开始，时长须覆盖原生剩余帧。CXBR02、CXBR03、CXBR05 的补充画面分别由已绑定的原生入场事件触发，写入原 `start_seconds` 字段。CXBR04 原入口从局部首帧开始，保持原配置结构。素材过短、缺真实入场词点、使用尾帧保持或循环、原采样实现摘要变化时拒绝编译。没有修改原素材槽、原入场曲线或原库文件。

本期使用已登记的两段实录近景与手势视频。在独立联调库新增一份本期 40 秒原画面左上方的墙面取样，作为 CXBR03、CXBR05 原纸纹图像槽的本期素材。素材内容和摘要从实际网站接口复核，无商品或使用证据。选用原包字体，CXBR02 继续用摘要与原登记一致的抠像模型。全 37 个实景组保留在名册，按本批范围执行 CXBR02–05。CXBR01 缺原入口固定读取的 Times New Roman 文件，AZL01–07 缺原入口固定读取的精确黑体，网站组详情增加这些依赖引用，AZL 同时列出原抠像模型。未绑定条目保持原运行状态。

批次 `C:/tl/cxbr-batch/native-v1/batch-receipt.json` 记录 4 组各一次原生 `check` 与 `render-group`。720×1280、30 fps，共 526 帧，独立全量解码、画面变化与证据摘要通过。说话人样本采用四个不同非零源偏移，补充视频分别从局部第 40、89、0、7 帧进入，源时间起点均为 0。独立比较 4 个说话人画面和 18 个补充画面样本。正确说话人窗口像素平均绝对误差为 1.883–2.217，错用原片起点为 8.634–17.760。正确补充窗口为 1.454–1.755，各组平均误差均低于错用镜头时钟的对照。证据 `C:/tl/cxbr-batch/clock-and-catalog-evidence.json`。人工抽看实际编码画面确认圆窗、分区、前景和纸条存在。这批静音原生组件使用实录取段作为时钟对照，仍待以本期实际配套素材核对完整画面。连续人物模板沿用已经实测的出片流程。

真实 API 对照四组的证据 ID 和输出摘要。Chrome 实测四张组卡显示“有编码样本 · 未验收”，CXBR01 显示待实测与原字体依赖，CXBR03 详情显示一份具体记录。CXBR02 的原模型缓存检出 73 张各不相同的有效 alpha 蒙版。网站证据 `C:/tl/cxbr-batch/browser-catalog-evidence.json`。原库仍完整登记 132 组、197 项内置资源、699 项外部引用，现有 71 组带编码样本、4 组有失败记录、57 组待实测、0 组获用户画面验收。批次结束时原包 1426 项完整性复核通过。50 项相关回归、Windows/Linux mypy、Ruff、前端类型与目标 ESLint 通过。GitHub main 复核 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，主目录的 81 项既存改动隔离。无数据库迁移、付费调用、推送或部署。

## 本机原字体和模型依赖

API 与 worker 可通过 `POLARIS_VIDEO_EDITING_NATIVE_BINDINGS_FILE` 读取同一份原包绑定工具生成的本机清单。网站按文件身份显示未登记、已登记文件缺失、摘要不符或原件已核验。只返回核验状态，文件路径保留在本机私有清单。可信配方用 `dependency_ids` 明确指定本次依赖，原有 `dependency_bindings` 继续兼容。每次编译核对字节数与 SHA256，历史视频和其他项目素材继续按原流程独立绑定。

原包绑定工具在本机已安装字体及既存本机素材中核验了 Georgia Bold、Georgia Italic、Impact、Segoe Print、Segoe Script、Consolas 和 u2net 抠像模型。28 项外部字体有 6 项本机已核验、22 项待登记。CXBR01 的 Times New Roman 和 AZL01–07 的黑体已找到本机同名字体，但其字节数与摘要不同。优设标题黑官方发布页需要登录下载，已有两份公开候选摘要均不同。此轮保持这些依赖待登记，库内原件身份不变。

以清单 ID 重编并实际渲染 CXBR02、YYP04、YYP06，三份编码样本与原路径绑定的样本 SHA256 逐一相等。Chrome 核对 AZL01 的模型已核验与黑体未登记，以及外部字体页的 6 项已核验和 22 项未登记。真实 API 与独立比较证据见 `C:/tl/dependency-binding/website-dependency-registry-evidence.json`。原包完整性通过，运行覆盖统计沿用上一阶段，未据此增加视觉验收。

扩大本机字体检索后，找到符合原摘要的黑体 `font-aa4560dd8fe56457`，以本机文件明确绑定，系统同名字体保留。下载并核对江西拙楷 2.0、优设标题黑、庞门正道标题体和庞门正道粗书体的字节数与 SHA256，再安装到当前 Windows 用户。江西拙楷取自公开 npm 包 `@fontpkg/jiangxizhuokai@1.0.0`，其余三份取自公开字体库 `dxinef/freefonts`。所有下载文件均与原包登记逐字节身份相符，二进制文件保留在本机。Chrome 与 API 实测外部字体 11 项已核验、17 项待登记。AZL01 同时列出已核验的黑体与原抠像模型，实景素材和采样时钟仍需单独验证。Times New Roman 仍待精确原件。最终证据 `C:/tl/dependency-binding/website-dependency-registry-fonts-v3-evidence.json`。

BG-S10 与 BG-S11 使用已恢复的原庞门正道粗书体和同一实际口播词点，分别渲染“终于／等到／两大瓶”与“柠檬精华／冷水去污”原生透明组件。原生入口检查、全量解码、90 与 104 帧以及透明像素变化均通过，网站各登记 1 份样本。它们是当前实录组件，仍待带人物的组合版式与语义验收。AH-S07 的字体依赖已具备，本期实录缺少该组要求的四位年份词。批次见 `C:/tl/dependency-binding/brush-native-v1/batch-receipt.json`。

## 组合模板入场音效与背景乐

自动原生编排升级为 `tengli-overlay-recipe-v2`，以原组入场事件为锚。价签和滚动模板的每处实际动效生成一条原库短音效，同组重复出现时保留各自的词点和音效。使用原声源片的电平，背景乐以 −33 dB 增益低位铺底，首尾淡入淡出。避用备忘参与候选选择，保留现有背景乐降低、关闭及段落恢复原景的功能。原生引擎测量音效起声并去除前导留白。旧候选按冻结配方重放，新候选按版本去重。

同一价签实录以已保存的本地协议规划生成候选 `f7899057-ad05-455e-8756-a034997d5cb9`。Chrome 经网站提交任务 `51f1c780-a059-4162-a33c-57c482b64f1f`，独立 worker 一次完成，真实付费规划、转录和对齐调用均为零。48.475 秒视频保留 11 种、11 次原生叠加动效与片尾 SG-S10 的 55 帧设计叠字。新增 11 个原生入场声点，使用 5 份原库音效与一条原库背景乐。独立解码 11 处音效的首个有效 1 ms 窗均与原生事件同位。原口播声轨样本与旧版逐样本相等，画面编码流 SHA256 与旧版一致。背景乐在有词区间平均比口播低 10.435 dB，编码混音峰值 −20.106 dBFS，未过载。

Chrome 已验证网站代理与高清实际播放并解码声音，代理与高清的 AAC 流相同。确认前隐藏高清，错误代理摘要被拒绝，确认后发布同一高清文件，重放确认仍只有一次 worker 尝试。高清 `C:/tl/auto-overlay/website-label-with-sound-hd.mp4` SHA256 `3ce6da668fc1c46cff267ecdba1685f2084e27fb2756c1b3dfc6799305d79d1d`。代理 `C:/tl/auto-overlay/website-label-with-sound-proxy.mp4` SHA256 `8663ac0a6db2fe03c3d292772a1f2434e36a26f0ba7211866cd0fa33667898d4`。声音分轨和浏览器证据见 `C:/tl/auto-overlay/website-label-with-sound-evidence.json`。实际听感、语义及画面继续待用户验收。

本轮剪辑回归 126 项全部通过。恢复测试的本地请求替身已接收模板参数，覆盖中断后避免重复调用的原断言。Windows mypy、Ruff、前端类型检查与目标 ESLint 通过。主目录 81 项既存改动隔离，无迁移、付费调用、推送或部署。

## AZL01–07 实景组件取帧与蒙版

补齐原阿哲 AZL01–07 的网站取帧适配。逐组固定原生入口、共享取帧代码、原抠像实现和原工作进程的摘要。说话人使用实录词点确定起点与长度，补充视频从自己的首帧开始，已登记的静态素材沿用原静态输入规则。编译仅写入原组已开放的字段。原组没有独立时长字段的补充素材，校验当前登记视频覆盖整个窗口。源身份、素材长度和尾帧策略均在编译阶段检查。每组原构图、素材槽、字幕事件、黑体与抠像模型按原包使用。

原生 AZL 的蒙版键包含局部帧号与固定偏移字符串。网站在调用原 worker 时按实际准备任务隔离蒙版缓存。用同一个原视频、同一个实例目录和同一 AZL01 局部第 0 帧跑两次，使用实录 0.410 秒与 4.870 秒的偏移。两份蒙版分别与原视频第 10 帧和第 117 帧的 RGB 裁切逐像素一致，错配时平均绝对误差为 8.869/255。证据 `C:/tl/azl-batch/repeated-native-cache/actual-repeated-cache-evidence.json`。

本批使用当前项目已登记的口播和素材做原生组件验证。两份补充视频是同一原片的人物和手势取段，第三路静态图是原片灰墙局部。这些取段的工程验证范围限于原生采样和遮罩。项目配套素材、组合模板里的完整观感、字号与语义待验收。

七组经原生 `check` 与 `render-group` 各一次，全部为 360×540、30 fps，共 735 帧。独立全量解码与画面变化通过。14 个口播帧的蒙版 RGB 与实录取帧逐像素一致。22 个补充素材区域的像素平均绝对误差为 0.764–2.460/255，20 个视频区域全部比错误固定首帧更接近正确取帧。抽看每组一帧，确认原人物窗、出框描边和独立素材布局在编码画面中出现。批次记录 `C:/tl/azl-batch/native-v1/batch-receipt.json`，独立比较 `C:/tl/azl-batch/scene-clock-and-catalog-evidence.json`。

真实 API 核对七个组的样本摘要和证据 ID，Chrome 验证七张运行卡及 AZL04 的三处补充素材槽、已核验的黑体与模型。网站现有 132 组全量登记、80 组有实际编码样本、4 组有失败记录、48 组待实测。原包完整性复核通过。剪辑回归 128 项通过，最终相关回归 14 项、mypy、Ruff、前端类型与目标 ESLint 通过。GitHub main 为 `106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a`，本次修改在隔离工作树，无迁移或外部付费调用。

## 浏览器分屏和 W-R09 剪影恢复

CX-G01–03 以本机摘要核验通过的原优设标题黑启动共用浏览器入口。网站编译提前校验原引擎及辅助代码身份、三项标题、入场顺序和末项落稳时间，并把历史参考帧注记更新为本次本地帧范围。实际画面使用项目里登记的人物取帧。三个入场分别在用途段的 0.660、1.080、1.660 秒，对应实录“洗碗”“刷锅”“洗水果”。CX-G01 的英文标签按本期中文实录留空。三组各独立渲染 120 帧、720×1280、30 fps，经过编译预检重跑的输出摘要与初次修复逐一相同。

抽看编码帧后发现 G02 与 G03 的第三项长标签被原构图局部遮住。两组以实录中的“水果”重渲染，口播字段仍为“洗水果”，入场时点、原布局和其他编译输入逐项相同。抽看新编码帧时两字完整。两组各 120 帧，网站已登记新的输出摘要。首批与独立复验证据分别在 `C:/tl/failure-recovery/browser-native-v1/batch-receipt.json`、`C:/tl/failure-recovery/recovered-evidence.json`。标签调整的证据在 `C:/tl/failure-recovery/readable-labels-evidence.json`。

W-R09 原合同允许七张透明剪影和前一张画面。网站为该组明确暴露七个透明图片槽，校验本期项目素材身份，并传入原生 alpha 声明。用同一实录的七帧及原抠像模型结果生成七份本期轮廓，保留原剪影入场序列、位置和绘制方式。第一遍漏写原入口要求的 alpha 声明，记录了具体失败。补齐声明后，原生检查验证了文件实际透明度，随后编码 540×960、30 fps、138 帧，独立解码得到 137 个不同画面状态。检查最终已落稳帧，七处剪影各自对应的主体像素比例为 76.9% 至 100%。组件输出 SHA256 为 `80477388c17a3ede1314182e52bec1c508bde62d159b8a779bf731485517de18`。原剪影素材引用仍登记在原库，本次轮廓明确绑定在当前项目实例。证据在 `C:/tl/failure-recovery/unified-native-v3/batch-receipt.json`。

网站统计区单列同时有成功与失败记录的组。Chrome 核对了 CX-G01、W-R09 的混合状态以及 LYO01 的精确字体缺失提示。132 组中，82 组仅有编码成功记录，2 组已有编码样本且保留失败历史，2 组仅有失败记录，46 组待实测。W-R18 仍缺原透明烟雾素材。LYO01 的原 schema 与共享入口校验仍有冲突，且缺精确的微软雅黑粗体。全库逐组、组合成片观感、听感与语义仍待推进。原包完整性复核通过。剪辑回归 130 项、最终相关回归 16 项、mypy、Ruff、前端类型与目标 ESLint 通过。本轮无迁移或外部付费调用。

## 实录章次和数量字形

在可信配方中为 Z-M05、Z-M15 增加实录章起点。网站按有序词 ID 计算英语序词，要求章单从实录首词开始、本镜头与章起点一致、镜头范围不跨下一章。当前适配的序词范围为 First 到 Tenth。章次来自人工划分的本期实录段落，章名和引用仍来自本镜头的实际词点。Z-M05 的原静态透明人物槽使用本期实录的人物前景。Z-M15 的原人物取帧窗口由实录绑定并核对原生取帧代码摘要。初次批次用原组的 `chapter` 值填入了网站语义枚举，适配验证返回不匹配。重跑使用网站的 `explanation` 并保留原组 `chapter` 意图。Z-M05 与 Z-M15 最终实际编码 205 帧和 120 帧，抽看显示 Third、Fourth 及本期章名。

W-R07 在原字形容量内绑定本期明确说出的“每瓶两斤”和“到手四斤”。网站保留两段原词和对应词 ID，把“两斤”和“4斤”编译为原生可用字形 `2`、`4`，原标签显示“斤”。规则校验两端同单位、数字原词在各自字幕中连续出现、入场与各自的实录金额或数量词点一致。目前支持原生 1–3 位 ASCII 整数及有限的中文个位数和“十”写法。该组保留原黑场、数字镂空与轮转。实际编码 150 帧，镂空处的两个帧样本分别对应原片第 404 帧和第 454 帧，像素平均绝对误差为 2.612、2.550/255，固定首帧对照为 5.408、5.900/255。

三份样本共 475 帧，均由原生引擎实际编码并独立完整解码。网站 API 逐一核对样本摘要和证据 ID。全库 132 组中 87 组有实际编码样本，其中 2 组还保留失败历史，另有 2 组仅有失败记录和 43 组待实测。本批素材、文字和章划分用于组件工程验证，组合成片观感、事实与听感待验收。证据在 `C:/tl/chapter-quantity/source-grounding-evidence.json`、`C:/tl/chapter-quantity/native-v1/batch-receipt.json` 和 `C:/tl/chapter-quantity/native-v2/batch-receipt.json`。原包完整性复核通过，132 项剪辑回归、Ruff 和 mypy 通过。本轮无迁移、外部付费调用或部署。

## 月云川两批开场的原黑体与人物窗口

按原文件摘要绑定黑体 `font-aa4560dd8fe56457` 及 U2Net `model-01eb6a29a5c4d8edb30b`。YYO01–08、YY6O03–06 的适配表逐组锁定原生入口、共享取帧和抠像代码。原生调用按每帧的局部秒数取样，编译器按实录区间设置偏移及长度并要求越界报错。网站适配将 YYO02、YYO07 和 YY6O03–06 的人物蒙版缓存按实际原生任务隔离，因为原缓存键没有随当前取帧偏移改变。现有 AZL 隔离范围保留，原包文件不写入。

本期同一实录提供“到手两大瓶”“买一瓶”及“每瓶 1000 克”“4 斤”等词点。YY6O03、YY6O05、YY6O06 绑定本期已登记的灰墙静帧作为独立背景，人物始终取本期原视频。先前黑体缺失记录已更新。YY6O01 还需要网站允许将原问号作为固定图形保留，目前纯文本绑定要求实录对应字。YY6O02 的撕纸需要与背景图不同的室内素材，本次批次只有一个已登记的室内静帧。首次 YYO01、YY6O04 的配方未声明原模型 ID，原检查失败并留下诊断。显式声明精确的字体和模型后重跑，两组实际编码成功。

原生取景、闪现、人物窗、蒙版、字体、动画及其固有重叠均保留。开场组件可能改变人物构图或在过渡中遮挡画面，当前可选连续口播模板继续使用经过核对的透明层。抽看了圆形蒙版、聚光灯、大小字排版及各自时点的人物嘴部和手势变化。全库视觉及语义状态仍为待验收。

抽看发现 YYO08 的价格字采用原生固定动画时点。用对应时点附近真实说出的“14块9”重新绑定，YYO01 和 YYO06 的提前说明也换成同期报价。三组重跑并抽看，原生位置和字号没有改变。YY6O06 保留原电视纹理和人物虚焦，本期仅核验组件。12 组最新样本合计 2736 帧，逐组实际编码、独立解码、核对词点时间、项目素材、原字体及模型摘要，并核对目录 API 的证据 ID 和编码摘要。全库 132 组中 99 组已有实际编码样本，其中 4 组同时保留失败记录，另有 2 组仅有失败记录、31 组待实测。原包 1426 项完整性复核通过。记录在 `C:/tl/opening-batch/opening-evidence.json` 和同目录 `smoke-v2`、`native-v1`、`native-v2` 的批次回执。剪辑回归 133 项、Ruff、mypy 通过。

## 第二条带入场音效和背景乐的网页试片

滚动报价与规格对照模板 `roll-compare-v2` 通过实际规划任务保存本地协议回放的实录词点，再从网页触发原生编排 `41d09455-51b9-4488-aa46-849443e191bb` 及剪辑任务 `29e57aeb-7ee2-48bf-a489-a2242022855a`。独立 worker 一次完成。影片为 48.475 秒、30 fps、1454 帧，10 种透明动效共出现 11 次。BG-S06 在约 1.08 秒与 10.02 秒各出现一次并有独立声音锚。真实规划模型对内容的判断仍待验证，本次外部调用为零。

22 个实录同位人脸取样的最大像素平均误差为 6.575/255，11 处动效均核对了编码叠加。分轨核对 11 个原库入场音效，音效在各原生动作入场的首个毫秒达到检测阈值，原声轨的采样值与先前同源试片一致。原库背景乐铺满全片，按实录词覆盖区间测量的均方根电平比原声低 10.435 dB。代理与高清使用相同的编码声音流，Chrome 播放两版均实际解码声音，并核对确认、下载和 206 分段读取。高清 `C:/tl/opening-batch/website-rolling-with-sound-hd.mp4`，SHA256 `172992ed4f942a230b56289df5a95de04f6ce5b473f8c936ce9326bbb4f7101c`。声音和画面证据在同目录 `website-rolling-with-sound-evidence.json` 与 `rolling-visual-continuity.json`。字号、画面、语义与实际听感待用户验收。本轮无迁移、外部付费调用或部署。

## 问号开场、双层撕纸与中英换字

补齐 YY6O01 和 YY6O02 的原生人物时钟与实例蒙版隔离。YY6O01 保留原模板问号字形，由实录“谁”的 5190 ms 词点触发，回执区分原设计装饰和本期可说出的内容。YY6O02 的两个静态槽分别绑定本期原片左上及右上墙面裁片。右上裁片经本期网站补充素材接口登记和下载摘要核对。它们来自同一房间的两个画面区域，组件验证覆盖撕纸边缘和独立图层。使用原黑体、原 U2Net、原生模板和渲染源码。

W-R02 保留原两字逐字换色、背景虚化与动态人物窗。以实录“每瓶”“到手”分别绑定原文及各自字幕，两个换字动作来自“到”和“手”的词点。英语 `PER BOTTLE` 与 `TOTAL` 是本期可信配方提供的说明标签，来源和相应中文词 ID 单独保存，语义待验收。编译器限制这项能力到原双语换字组和两个固定槽，校验译文对应各自的实录及字幕并防止与直接转录绑定冲突。人物窗抽取的两帧分别对应原片第 363、447 帧，像素平均绝对误差为 3.585、2.644/255，低于未偏移和固定首帧对照。

三个组分别实际编码并完整解码 227、224、196 帧。抽看保留原撕纸末段的黑色衬底及大字跨人物躯干的设计，三个组此次仅核验原生组件。目录 API 核对样本证据 ID 与摘要，并用当前 FastAPI 源码核对问号装饰字段及三个取帧合同。全库 132 组中 102 组有实际编码样本，其中 4 组保留失败历史，另有 2 组仅有失败记录、28 组待实测。证据 `C:/tl/opening-finish/component-evidence.json` 与 `current-route-contract.json`。原包 1426 项完整性、135 项剪辑回归、Ruff 和 mypy 通过。本轮无迁移、外部付费调用或部署。

## Hypit 人物标签与斜切条的本期参数

HY-A4 和 HY-A5 保留原 SVML、思源宋体、stagger 组件与 Hypit Build。原 schema 继续验证原生 config，原有封闭的 attributes 字段保留。网站侧为三条短标签及各自的实录词点生成独立的任务参数文件。原属性读取器遇到 item 方向符号时会提前截断，适配层因此只在原入口生成的任务实例文件写入两项已审核的条幅参数，保留原坐标、宽高、方向、入场曲线和字号。任务参数绑定原生 config 摘要、组 ID、输出身份及受审计的原入口。每次使用独立工作目录，结束后关闭本机 Hypit worker。现行运行范围为内部联调工作区。

用本期已登记的说话人静帧和“洗碗、刷锅、洗水果”词点分别运行两组。编译的标签帧为 20、32、50。两组各原生编码 120 帧，独立解码均得到 120 个不同帧。抽看确认人物标签保留原底板与文字关系，蓝色斜切条在原构图会与人物眼部重叠。本批样本用于组件检查。网站目录核对两份原生证据 ID、输出摘要及专用参数合同。其余 HY-A1、HY-A2、HY-A6、HY-A7 的经典参数适配仍待完成，HY-A3 保留已有三图变体。

在本地原 episode 工程试片中将 HY-A5 用于链接段及用途段。两段分别编译“看看／下面／链接”和“洗碗／刷锅／洗水果”，产生两份不同的原 Build ID 和参数摘要。影片 48.475 秒，原生导出并完整解码，四个叠加时点的同位人脸像素平均误差最高 1.904/255，原声相关度 0.999987。此工程试片只有两处叠加和原声，组合模板还需核对适配这两组的摆位与声音时点。技术证据在 `C:/tl/hypit-strips/component-evidence.json` 与 `C:/tl/hypit-strips/repeat-episode-evidence.json`。全库 132 组中 104 组有实际编码样本，其中 4 组保留失败历史，另有 2 组仅有失败记录、26 组待实测。原包 1426 项完整性复核、136 项剪辑回归、Ruff 与 mypy 通过。本轮无迁移、外部付费调用或部署。

## Hypit 价格卡与入场混音

HY-A6 的三张卡沿用原生思源宋体 Heavy 与 Bold、卡片几何、右对齐标题、绕锚点缩放及不同入场长度。网站适配保留原 schema 的封闭字段，在隔离任务实例填入三组两行文字和实际入场帧。报价“14块9”、每瓶“1000克”、两瓶“4斤”来自本期实录，原素材槽逐一绑定四份互不相同的登记图片。抽看首版发现黑字与深色头发重叠。第二版用本期三处实录的手势和墙面分别裁出卡面，右侧给原黑字留浅色读区。两版均通过原生 Build 与全解码，第二版为 1080×1920、30 fps、312 帧。素材为本期实录取景样本，商品画面仍待相应素材。

Hypit 的标签与卡片入场音效沿用原混音器。原 schema 保持封闭，适配层以已编译的原生入场帧转换到绝对声轴，渲染后逐项核对任务参数摘要、实际生成的原生 SVML 及其中的帧值，再核对原库音效的编码起声。现有普通原生事件继续用原 config 引用校验。多个不同入场可以绑定同一原库音效，每条独立保存实录词 ID、原生帧、音效 ID 和校验回执。

本地网站内部剪辑接口实际提交 10 种动效及 14 条入场提示，独立 worker 一次完成。首版像素核对发现价格卡和斜切条在原生标记帧仍透明。修订版把这两组的声音对齐到下一可见帧，并按原生合成器的输出帧时钟处理镜头起点取整。任务 `1271c356-2e66-4a8f-8248-a4b8de23a41d` 实际导出 48.475 秒、720×1280、30 fps。六处音效起声分别与第 301、441、546、1194、1206、1224 个零基编码帧的入场变化一致。原声持续播放，原库背景乐在实录词覆盖区间比人声低 10.435 dB。五个取样点的同位人脸像素平均误差最高 6.405/255。Chrome 已播放并实际解码声音，确认 206 分段读取和浏览器下载摘要一致。

高清试片 `C:/tl/hypit-cards/website-price-cards-with-sound-v2.mp4`，SHA256 `2f3b01826879ad3ea7721cb15ef7bf990101f330a50643a72bb3d5e1bf3a1def`。证据在同目录 `website-price-card-evidence-v2.json` 及 `component-evidence.json`。组合预览按钮当前仍限定为透明字幕层，带 Hypit 小窗的试片经内部接口出片。小窗价格字与主字幕的视觉关系、听感与语义均待验收。全库 132 组中 105 组有实际编码样本，其中 4 组保留失败历史，另有 2 组仅有失败记录、25 组待实测。原包 1426 项完整性、138 项剪辑回归、Ruff 与 mypy 通过。本轮无数据库迁移、外部付费调用或部署。

## 手机字号与带 Hypit 小窗的预览确认

HY-A6 新增可选的任务字号配置。适配层仅在本次原生实例中放大卡片文字并调整基线。原思源宋体、卡片尺寸、右对齐、缩放锚点与错峰入场均沿用原组。此配置仅接受原组的三组短行文字，常规字号路径保留。独立解码 312 帧后按像素量测，三张卡的原字形高度为 57–58 像素，改后为 89–93 像素，卡片上下各仍有至少 29 像素留白。量测记录在 `C:/tl/hypit-insets/native-font-evidence.json`。

内部联调工作区的组合预览可在无内嵌字幕的连续原口播上使用 HY-A5、HY-A6 小窗。已审核的下方画带与声明的人物保留区分开，价格卡需使用放大字号配置。导出时以原生 libass 量出的主字幕笔画框及对应时间检查小窗，校验通过后才生成可确认的预览。原组内部文字压条、卡面等原有叠放保留。本期方案由内部人员按同一份实录词点配制，人物保留区和卡面取景亦由本期配方提供。

Chrome 以 390 像素宽视口从网站提交任务 `332f2cc5-1336-4582-b5ba-c8add5f2dace`，一次渲染生成 360×640 代理与 720×1280 高清。两者均在实际页面以 320 像素播放器宽度播放并解码声音，AAC 流摘要一致。确认前高清不可读，错误摘要返回 409。点击确认后下载文件摘要与原生输出一致，重放确认仍只有一次任务尝试。高清 48.475 秒、30 fps，含 10 种动效、14 条入场音效及原库背景音乐。价格卡和斜切条的六处声音分别与第 301、441、546、1194、1206、1224 个零基编码帧的实际可见变化同步。两组小窗与对应主字幕笔画至少相隔 36 个高清像素。五个同位人脸取样点像素平均绝对误差最高 6.447/255。抽看入场结束后的斜切条，三条标签均完整可读。

下载文件 `C:/tl/hypit-insets/website-price-cards-mobile-hd.mp4`，SHA256 `f8e88c52127947db3544545f24ba50d68eedef4673fd31faede1f7dde2604302`。网站、逐帧音效和字幕核验回执在同目录 `website-mobile-evidence.json`。本期沿用原录音与已登记的实录对齐，无新增识别、对齐或规划调用。语义、整片画面及听感仍待用户验收。全库 132 组中 105 组有实际编码样本，其中 4 组保留失败历史，另有 2 组仅有失败记录、25 组待实测。原包 1426 项完整性、140 项剪辑回归、Ruff 与目标 mypy 通过。本轮无数据库迁移、外部付费调用或部署。

## Hypit 流式标签的原生组件验证

HY-A7 现可按本期实录编译原生组件。原组的倾角、虚实双边框、三套渐变、文字压缩、入场方向、位移和持续帧数均保留。适配层以“洗碗、刷锅、洗水果”的实录词起点量化为本地第 20、32、50 帧，把原来跟随新标签入场的七段重排绑定到对应词点。保留原动作前后相对帧数，时间不足时拒绝把移动挤在同一段。中文标签使用原包思源宋体 Heavy，英文槽本期留空，原配置的 Georgia Italic 从 Windows 现有原件核验并绑定，摘要为 `d3e4bad27651d120ac8f2cea42cf4b4f077264fb243f66b3caffcfd35465f49b`。

口播底板以已登记源视频和实际词点裁出 39.110–43.110 秒，转成 30 fps 的任务本地片段供原生入口从首帧读取。编译与运行分别核对源摘要和窗口，实际解码验证底板完整覆盖 120 帧。六个输出人脸区和原片同位时点的平均绝对像素误差为 4.595–4.851/255，全部优于未偏移取帧，后五处也全部优于固定首帧。原 Hypit Build 独立完整解码 1080×1920、30 fps 的 120 个不同帧，抽看七段重排后的三条标签完整可读。原饼图随同组件保留，本期没有与该饼图对应的经过核对的数值，因此整片出片入口明确拒绝这一组的未绑定数据版本。组件样本仅用于技术核验。

网站目录 API 与 Chrome 实测显示该组的编码样本、字体原件状态及饼图出片条件。规划目录保留全部 132 组及该组的组件验证范围。全库 106 组有实际编码样本，其中 4 组保留失败记录，另有 2 组仅有失败记录、24 组待实测。首轮配方使用了错误的依赖字段名，编译前置检查拒绝；修正字段后完成原生渲染。网站按同一证据 ID `dfafb0a84d444d49b722bed8c5784358` 登记，组件 SHA256 `f8cdc0d5606930843df83de14580ee53056dfc9573d451dbfdd38635815d8a10`。证据在 `C:/tl/hypit-flow/native-v2/batch-receipt.json`、`C:/tl/hypit-flow/source-frame-evidence.json` 和 `C:/tl/hypit-flow/website-flow-evidence.json`。原包 1426 项完整性、151 项剪辑与原库回归、Ruff、mypy、前端类型检查与目标 ESLint 通过。无迁移、外部付费调用或部署。

## W-R18 竖排追问和烟雾收尾分开验证

W-R18 保留原有竖排追问和烟雾收尾。网站合同分别列出两套原生内容字段、时点与依赖，拒绝同一个词点方案混用两个分支的字段。竖排追问使用原思源宋体和原运行时指定的庞门正道粗书体，人物按实录窗口连续取帧。共用原入口会在追问初始化时读取只供烟雾收尾绘制的 18 张原图。网站兼容层仅在原入口和绘制源码摘要核对通过、且该任务明确选择追问分支时，将这 18 个精确文件的读取延迟到像素访问。访问仍由原加载器读取原件。原包文件及原绘制路径保留。烟雾收尾独立重跑原生检查，仍明确缺少原 `smoke-00.png`，没有生成烟雾输出。

本期竖排使用实录“你们谁”，原片 4.870 秒起，6.410 秒的“买”触发溶解。第二版把恢复清晰时的字幕缩为实录“那真是亏大发了呀”，在实录 7.090 秒进入，并通过原生布局设置最小字号 38 像素。对同一编码时点测量，实际字幕字形从 29 增至 36 像素。保留首帧的放大取景、文字压在虚化人物上、颗粒溶解和人物恢复清晰。实际编码 540×960、30 fps，共 101 帧，独立解码得到 94 个不同帧。溶解后 3 个同位人脸取样与实录的像素平均绝对误差为 2.197–2.360/255，优于固定首帧和未偏移对照。

网站 API 与 Chrome 已核对最新追问证据 `723d6ee9ad074bafa608001aa6b00cb9`、其独立分支标记和烟雾原件状态。输出摘要 `08990096c548e6a740b917c1c882631d83d24a973c0eca48f69bb02361ed8c21`。证据在 `C:/tl/vertical-question/native-v2/batch-receipt.json`、`C:/tl/vertical-question/question-component-evidence.json` 和 `C:/tl/vertical-question/website-question-evidence.json`。本轮范围为原生组件和目录验证，带完整口播声音的组合版仍待独立验证。全库 132 组中 107 组有实际编码样本，其中 5 组保留失败记录，另有 1 组仅有失败记录、24 组待实测。原包 1426 项完整性、152 项剪辑与原库回归、Ruff、mypy、前端类型检查和目标 ESLint 通过。本轮无数据库迁移、外部付费调用或部署。

## 十一种原生动效的带声网站预览

连续口播预览新增 W-R18 原生追问小窗。仅在原片无内嵌字幕、明确选用追问分支、主字幕由网站排版、且小窗避开声明的人物区域时启用。原生烟雾分支与带内置字幕的组件仍保留独立合同。小窗沿用原竖排、颗粒溶解与内部人物画面，底板全程使用同一实录，不切走人物。网站逐条比对原生 libass 主字幕笔画和三个小窗的实际时间范围。W-R18 与主字幕最少相隔 84 个高清像素，两个 Hypit 小窗分别为 36 个像素。

从实录 4.870 秒起安排追问。原合成器在第一个达到该时点的输出帧启用不透明小窗，适配层用这个编码帧绑定原库悬疑音，保留词点和原事件的对应关系。实际高清第 145、146、147 个零基帧内的深红字形像素分别为 0、0、17465，独立音效分轨在第 147 帧对应的 4.900 秒起声。原 Hypit 价格卡与斜切条的六处声音也再次核对到各自可见帧。AAC 解码与原声、音效、背景乐三轨叠加的相对误差为 −32.48 dB，口播词覆盖区间内的原库背景乐比原声低 10.43 dB。

本地网站任务 `2bcf21b4-998e-4f45-9018-76d82ded573a` 从实际页面生成代理与高清，一次 worker 尝试完成。48.475 秒的成片经抽帧与原片、原生字形区域或小窗区域逐组对照，确认 11 种动效均实际出现在编码画面，含 15 条入场音效及原库背景乐。手机宽度浏览器实播代理和高清并解码声音，确认前高清不可读，错误代理摘要被拒绝，点击确认后下载与原生输出摘要一致。下载 `C:/tl/question-film/website-question-11-effects-hd.mp4`，SHA256 `12966ab58dc478dcba491bd0b31f46c33e0b5be87cf41c32e07c3196b96ff9a4`。证据见同目录 `website-mobile-evidence.json` 与 `all-eleven-motion-evidence.json`。

当前组合由内部人员按本期实录词点配制，原片、实际录音和词点均沿用已冻结产物。产品事实、整片观感和听感仍待用户验收。全库 132 组中 107 组有实际编码样本，其中 5 组保留失败历史，另有 1 组仅有失败记录、24 组待实测。153 项剪辑与原库回归、Ruff 和目标 mypy 通过。本轮无数据库迁移、外部付费调用或部署。

## 整帧场景与连续口播分开编排

原 HY-A5、HY-A6 使用 1080×1920 画布。HY-A6 的原样式有三个独立卡图、背景槽和原生文字。前版灰底小窗和截取原片衣服作为卡图来自网站试片的绑定。当前全幅版本让原生画布覆盖完整成片，用实录同期画面填充 Hypit 背景，用单独登记的三张演示图承载“两大瓶、每瓶、下单”三条说明。图中价格、重量和件数来自本期实录，瓶形为示意。第一版卡图首尾对应反了，取消该任务并重新绑定。W-R18 的整帧追问使用同一实录同步生成清晰人物和实时虚化底板，保留原入场和颗粒溶解。以上适配写入任务实例，原包文件保持原样。

新版组合模板 `question-story-v1` 可同时安排透明叠加和整帧场景。人物是否露出由模板的原生构图决定，整帧场景可以改变背景或遮盖人物，实录声音继续，主字幕由网站独立编译。模板快照冻结槽位和资源规则，语义模型只引用真实词 ID、组 ID 和本期素材 ID。编译器依据实际录音换算时点，检查整帧范围、源素材、同位取帧、场景分支、主字幕及音效锚点。W-R18 要求真实追问、段首入场、溶解词点及两路同源素材。没有满足条件的场景可留白或选择适用的模板槽，无法编译的输入返回具体校验错误。正式剪辑过程无需逐帧视觉模型或人工移动素材。人工复核样片用于发现应补入模板合同的规则。

本地网站修正版任务 `a8f05e53-59de-42df-b02e-120f0a777d0d` 已实际播放代理、确认并下载 48.475 秒高清。它包含 11 种动效和 15 条原库音效，W-R18 在第 147 帧即 4.900 秒入画起声，六个 Hypit 入场与对应音效均核对到实际输出帧。原库背景乐在口播词覆盖区间比原声低 10.43 dB。文件 `C:/tl/full-native-film/website-full-canvas-hd.mp4`，SHA256 `667ad55008112da40aaf1019f8a09f5e2ba1199c4b31b7acfddad4a51b8683d0`，证据见同目录 `website-full-canvas-evidence.json`。这条用于追溯三个截图和对应原生构图，使用内部已配置编排。

Chrome 选择整帧追问模板并保存准备任务 `8da835e8-9867-4aa7-901e-27e5362d0264`。下载的真实规划请求含全库 132 组、整帧槽及本期原片素材 ID。一次受控离线响应经过真实规划校验，原生编排由网站自动生成，无人工编排改动。相同实录编译出 10 种动效共 11 次，BG-S06 在不同词点重复，W-R18 与其他组使用同一原声时钟。原引擎静态检查通过，回执 `C:/tl/full-native-film/template-contract-replay/native-check.json`。原包 1426 项完整性复核、156 项剪辑与原库回归、Ruff、目标 mypy、前端类型检查与目标 ESLint 通过。本轮无数据库迁移、外部付费调用或部署。真实模型对新文稿的语义选择及其他整帧场景需要分别实测。

独立剪辑 worker 在一次尝试中完成任务 `d579e980-0d6d-42a9-910c-fed727f7867b`，原生布局回执通过。手机宽度 Chrome 实播代理和高清，均实际解码声音。确认前高清不可取，确认后下载与原生输出摘要相同，并支持 HTTP 206。48.475 秒高清含 11 条原库入场音效及背景乐。W-R18 在第 147 帧入画和起声。整片口播分轨与同一实录的前一任务逐样本相同。实录词覆盖区间的背景乐比口播低 10.43 dB，AAC 解码与三轨总和的相对误差为 −33.65 dB。高清文件 `C:/tl/full-native-film/website-auto-scene-hd.mp4`，SHA256 `29e4246da841334d2888482a311225481f89ec1899528cbb5d173d1b9c2d5fed`，回执见同目录 `website-auto-scene-evidence.json`。语义、观感和听感仍待验收。

## AH-S07 年份字幕的实录词点与原生字形

原引擎的年份槽要求四个阿拉伯数字加“年”。网站编译器从同一连续实录词组投影显示字形，允许四位阿拉伯数字、全角数字或逐位中文数字，要求原生年份入场锚定首个数字词点。原文字、词 ID、显示字形同时写入回执，主字幕和原转录保留原文。三种原字体及字号、背衬字、数字错帧和透明通道按原组保留。庞门正道粗书体使用已按原 SHA256 核验的依赖 `font-06b2048c592b1dae`。

当前产品原片没有口播年份。本轮使用 Windows 本机合成语音作为组件输入，FunASR 识别后用 fa-zh 在实际音频上重新对齐。“二零二六年”起点为 450 ms，镜头起点为 230 ms，原生年份入场为本地第 7 帧，输入仍保留五个实测词 ID。原生 check 和 render-group 均实际运行。组件独立完整解码 139 帧，576×330、30 fps，原生 RGBA 自第 7 帧出现红色年份像素，H.264 抽帧自第 8 帧出现少量过阈值红色像素，第 9 帧明显增加。抽看确认年份、前后短字和灰色“测试”背衬均实际编码。此输出范围是透明字幕组件，配音用于对齐，尚未纳入组合模板出片或用户验收。

组件 `C:/tl/year-caption/native-v1/AH-S07/renders/component.mp4`，SHA256 `9e267dd8fd9e3620e1950a62a359032654643ce7141ba193cc5f54f6e9bc8fc4`。网站目录证据 ID `a96cc64339d943089dae1a11aeb442fd` 与编码摘要一致，核对记录 `C:/tl/year-caption/year-website-evidence.json`。全库 132 组中 108 组有编码样本，其中 5 组同时保留失败记录，另有 1 组仅有失败记录和 23 组待实测。原包 1426 项完整性、157 项剪辑与原库回归、Ruff 和目标 mypy 通过。本轮识别及对齐在本机运行，无数据库迁移、外部付费调用或部署。

## W-R06 评论框的实录时钟与两路底板

W-R06 增加独立的原生时钟配置，固定原引擎、原采样函数和两套原入口的文件摘要。提交前底板必须绑定本次原片，使用词点窗口并禁止循环或尾帧停留。提交后由原入口切换到独立登记的项目静帧。占位词、提交词和动作时点均取同一实测转录，框的原构图和上移曲线保留。

由于产品口播只邀请点击链接，本轮另建联调项目，用本机合成测试语音表达评论区留言和输入“示例”。底板为原片实拍手部取段，提交后静帧经网站素材接口上传并核对下载原字节。FunASR 与 fa-zh 在这条测试音轨上实际识别和对齐，原生组件保留“请在评论区留言”和“示例”。词点分别是原测试源的 2.290 秒、4.890 秒，编译后的场景本地时点为 2.020 秒、4.620 秒。

原生 check 和 render-group 实际运行，完整解码得到 209 帧、540×960、30 fps，其中 173 帧画面不同。第 138 帧仍匹配同期视频，第 139 帧切到独立静帧，评论框内的关键词同步替换。网站目录核对证据 `5b89f67f46334965937f975106b3b7be`。组件 `C:/tl/comment-cta/native-v1/W-R06/renders/component.mp4` 的 SHA256 为 `b55cb4e25ec55fb723bd020f5f534b9b74f6569eebcd12700adfcb519ed90ea2`，逐帧核对记录在 `C:/tl/comment-cta/website-cta-evidence.json`。本轮是独立场景验证，尚待组合出片和听感验收。132 组中 109 组有编码证据，其中 5 组仍保留失败历史，另外 1 组仅有失败记录和 22 组待实测。原包 1426 项完整性、22 项时钟、编译与批次回归通过。

## 三图卡自动编排与口播字幕

新增组合模板 `picture-compare-v1`，允许规划将口播中三个并列项目交给原 CX-G07 整帧图卡。准备任务冻结本项目勾选的图片 ID 和摘要。网站检查背景和三张图卡的素材身份、两套原生图卡槽对应的词组和图片、三张图片摘要的差异及入场词点。缺图、重复图片和同卡两套槽不一致均在编排阶段返回明确错误。原引擎使用原优设标题黑、原画幅、原卡片尺寸及姿态。主字幕在图卡时间内自动移到卡片上方，口播原声连续。

首轮图卡组件测得第一张卡从第 15 帧开始露出，原实测入场点是第 20 帧。取消该轮整片任务 `580aedb4-567e-43f8-a296-af1378778826` 后，自动模板将离屏的上一关键帧保持到入场前一帧，原姿态和进入画幅后的运动轨迹保留。沿用早期配方的任务继续采用原有时钟。三次入场各绑定一条原库短音，背景乐继续低位混合。

Chrome 选择三图卡模板和四张本项目已登记的图片，网页保存准备任务 `694cc478-7bb3-4843-b1aa-9f8cd520f88c`。使用受控离线规划响应验证真实接口、编排和渲染。自动编排 `660980ca-268c-4587-9da4-4d094a4556c7` 包含 10 种动效共 11 次，保留整帧追问及滚动报价复用。三张卡图为本期口播取帧，用于核对素材通路，商品实物和使用事实另待核对。编排校验见 `C:/tl/picture-template/card-contract-verification.json`。157 项剪辑与原库回归、Ruff 和目标 mypy 通过。

独立 worker 一次完成整片任务 `d132d6f9-e424-4771-b4a4-7590e4b165fa`。三张卡首次出现在整片第 1193、1205、1223 帧，三处提示音均在相应帧开始后约 10 ms 起声。111 个图卡与主字幕同屏帧的最小竖向间距为 46 px。48.475 秒整片含 13 条原库音效及低位背景乐，原声分轨与同一实录的先前任务逐样本一致。手机宽度 Chrome 实播代理和高清，确认后下载与原生输出摘要相同。高清 `C:/tl/picture-template/website-picture-template-hd.mp4` 的 SHA256 为 `fb5c71fb7897d7e678708c2a8d199f218610e2c3df97c493b004116d30712247`，核对记录见同目录 `website-picture-evidence.json`。实际外部规划调用为零，真实模型选组、商品语义、整片观感和听感待验收。

## W-R04 拼贴与 W-R14 判断场景

W-R04 的七个透明人物槽沿用原轮廓布局，当前原片按实录窗口连续取帧。W-R14 的判断、否定和结论使用实际词点，原动态背景与大字叠放保留。原引擎依赖的庞门正道粗书体以原文件摘要登记，缺少该字体时编译拒绝继续。早期因缺少字体而失败的记录保留。

原生组件分别完整解码 279 帧和 331 帧。W-R04 组件证据为 0e5fa1e6aaa44e2ab30b4b075b27c495，W-R14 最终证据为 98f986d58cce436aacb17f6fb47e7996。运行和抽帧文件见 C:/tl/evidence-scenes。组件使用本地测试语音和现有登记素材，检验编译、识别对齐及原生编码，组合出片和语义验收待验证。132 组中 111 组有编码证据，其中 6 组保留失败历史，另有 1 组仅有失败记录、20 组待实测。本轮无外部付费调用或部署。

## 三图卡保留同期人物和用途图片

网站将三图卡切到 picture-compare-v2。原 CX-G07 的文字、圆形裁切、画布、卡片姿态及轨迹仍由原浏览器引擎绘制。原生子进程仅在这版配方上导出透明卡片，原合成器把卡片叠到连续原视频轨上，口播原声继续使用同一条实录音轨。旧版三图卡保留已冻结的静态背景配方，其他整帧场景继续各自选择是否覆盖人物。

该槽要求本期原片、三个实际口播词组和三张不同的项目图片。每张图片在原 food 和 city 槽共用同一文件，入场由相应首词触发。规划从项目素材描述判断用途匹配，缺少适用的图时可以跳过这组。编译校验项目归属、摘要、类型、原片身份及词点，语义与商品事实仍需验收。联调上传的洗碗、刷锅、洗水果三图为本地用途示意。

现有电商创意图 API 支持用商品参考图生成场景图。剪辑素材 API 已实测可登记和读取三份 PNG。本地联调环境的生图运行模式为 mock，图像任务的产物尚未自动转入剪辑项目。后续若需要补图，可将生成与原生渲染分开，在核对图片用途后登记到当前项目，由规划引用其素材 ID。明确用途的实拍或示意图都可用，涉及包装及实际使用效果时以相应实拍为依据。

原包完整性复核 1426 项通过，161 项剪辑与原库回归、Ruff、目标 mypy、前端类型检查通过。独立 CX-G07 组件实际导出 120 帧，开场透明，图卡首入帧为第 20、32、50 帧，稳定后人物所在区域保持透明。合同拒绝静态底板、原片摘要不符、缺图、重复图及同卡槽不一致。本轮未调用付费图片或规划服务。

本地网站任务 bac7756c-a4c6-489a-915e-67f304cc0291 一次完成。Chrome 实播代理和高清，确认后下载摘要与原生输出一致，支持 HTTP 206。48.475 秒成片含 10 种动效共 11 次、13 条原库音效和低位背景乐。三卡在 39.11 至 43.11 秒间出现，三个入场音效与各自首帧同帧。人物区域的 120 帧均核对到同期原片，原声分轨与同一实录的基准输出逐样本相同。高清文件 C:/tl/picture-template/live-v2/website-picture-template-hd.mp4 的 SHA256 为 056850af6de8180c2e9de939a537d20c9ebeebcb0cd3232fcf247474fc22559a，证据见同目录 website-picture-evidence.json。语义候选使用受控离线响应，真实模型选图、付费生图回流和用户视觉验收待验证。

## W-R15 多角色论证链

编译器核验 16 个原生场景图片槽、从本段首词起严格递增的 16 个动作切点，以及关门、交接、禁行三处共享词点。回执分别记录素材和动作时钟。原入口还在部分切点内交叉淡化、留屏和连续换图。网站目录和规划请求提供原生素材角色顺序及原角色字占位。profile 和 doctor 两处保留原三块角色字区域，配图避免在同层叠印标题。

联调使用 Windows 本机测试语音，实际经过 FunASR 识别和 fa-zh 对齐。16 张自制流程示意图通过本项目素材接口登记，下载原字节与登记摘要一致。首轮配方添加了原模板未声明的说明字段，在编译阶段被拒绝。后续编码抽查发现按数组序号配图会错置后段素材，因此按原生实际出画顺序重绑本期插画，并保留早期样本记录。没有修改原引擎和原包。

最终独立组件 C:/tl/role-scenes/native-v4/W-R15/renders/component.mp4 完整解码 646 帧，540×960、30 fps，412 帧像素状态不同。禁行锚点为本段 18.640 秒，输出第 561 帧达到红色禁行标记检测阈值。九处抽帧与相应登记素材对照。网站证据 b7c3840d55bc476f9402dc6285c96e15，组件 SHA256 c5aa71cb42e844b2c1597188810a428bb5da80b10bdb8fd6be72d0ad5958509e。核对记录和抽帧图见 C:/tl/role-scenes/website-role-evidence.json 和 role-chain-proof.png。范围为原生组件和规划请求，组合出片、真实模型选组、听感与用户视觉验收待完成。

网站仍登记原库全部 132 组。其中 112 组有成功编码证据，6 组同时保留失败历史，另有 19 组待实测、1 组仅有失败记录。本轮无外部付费调用或部署。

162 项剪辑、文稿及原库回归通过，目标 mypy 与 Ruff 通过。原生批次运行前复核原包 1426 项。GitHub main 仍为 106d1e3eb17a87b89576d3f97c7ec8c9edf05e5a，本轮改动在隔离分支。

## Z-M12 纸面包装与同期圆窗

网站适配层支持原 Z-M12 四项纸面包装配置的同期人物圆窗。原引擎按镜头局部时钟取帧，原片偏移只应用一次。编译核验原片摘要、实录窗口、禁止循环及尾帧停留、四张项目图的素材身份和各标签的实测首词。原纸面、圆形裁切、卡片位置、旋转、进场曲线与字体保留。包装颜色按样式参数处理，价格和数量仍从实录文字绑定。

初版组件中的“1000克”被原自适应排版换行。初版网站任务 15bf9368-11a5-4434-9d5e-a7b0e0a3bc78 已取消交付。组件试跑中的单行自适应宽度不足和 native 搭配 auto 的合同冲突均保留失败记录。最终使用原生单行排版和 reject 模式。本期单瓶规格标签取实录中紧接着出现的“两斤”，主字幕仍保留“1000克”。四张图为同一商品的参数示意，不提供商品外观证据。

最终组件 C:/tl/package-window/v2/native-v3/Z-M12/renders/component.mp4 完整解码 278 帧，每帧像素状态不同。圆窗与原片 9.770 至 19.050 秒的同期区域逐帧比对，四处原生标签均出画。网站目录证据 ID 63af75ca1f9c42d296afec4389c0ea90，SHA256 94c11adadce11ebdf1e5f6c133db7a6b7b4f35792d3e85173836b439cd683053。原包仍登记 132 组，113 组有成功编码证据，其中 7 组保留失败历史，另有 18 组待实测、1 组仅有失败记录。164 项相关回归、目标 mypy 和 Ruff 通过。

组合片任务 e9adeb15-869c-42da-8a6e-dce4525b0e59 一次完成。网站在手机宽度 Chrome 实播代理与高清，确认前高清不可取，确认后下载与原生输出摘要一致且支持 HTTP 206。48.475 秒成片含 11 种动效、16 条原库音效和低位背景乐。四处包装音效实测在第 300、357、469、546 帧起声，与原生开始进场的帧一致。按颜色阈值检测到明显图形的首帧分别晚 3、2、3、3 帧，符合原进场曲线由浅到深。核对原声分轨与同一实录基准逐样本一致，下载片六处圆窗抽帧与同期原片对应。组合片的可选“囤一次”由主字幕承载。成片 C:/tl/package-window/v2/website-package-hd.mp4，SHA256 373c872882a7a2ea9693b984e94ca1337907a8bc0125e1e9a1f2e09905b0def0。证据见同目录 website-package-evidence.json。

本轮候选为内部配方，沿用已冻结的实录转录与对齐。无外部付费调用、迁移或部署。真实规划模型的选组、商品事实、整片观感和听感仍待验收。

## W-R01 胶片作品带与互动证据

网站编译器区分原评论框的样式参数和可核对的点赞数。当前三项配方的每条点赞数必须绑定项目内同位置的证据图、来源、带时区的采集时间以及实录标签。记录按对应标签首词驱动原评论进场。零次点赞可明确记录。规划请求只开放文字词点和素材 ID，目录同时列出需要可信配方提供的三处点赞数字段。缺记录或证据图、标签与词点对不上时拒绝编译。

联调以本机合成的技术说明作为实际识别和强制对齐的输入。三个胶片图由公开问题的当时记录制成，原始快照保存在 C:/tl/film-feedback/feedback-source.json，GitHub +1 分别为 0、1、0。通过项目素材接口登记并核对原字节。前景是本地透明插画，用于核验原生前景层。原引擎和原包字节保持原样。来源为 [FunASR #2784](https://github.com/modelscope/FunASR/issues/2784)、[FunASR #3702](https://github.com/modelscope/FunASR/issues/3702)、[FunASR #3457](https://github.com/modelscope/FunASR/issues/3457)。

原生 check 和 render-group 实际运行。组件完整解码 389 帧，540×960、30 fps，389 帧像素状态不同。三个相对词点为 6.560、8.420、10.160 秒，原胶片路径、原评论动效及文字叠放保留。入场前后在对应评论徽记区域测得红心像素变化。抽看确认数字与采集快照一致。网站证据 ID 3f07d96d4d0f44de898093aa43d43a3a，组件 C:/tl/film-feedback/native-v1/W-R01/renders/component.mp4 的 SHA256 为 102a22459c16847c3aef2e6d2bb23c063a97adbb3d79c9b9148c89df9aa35f8b。网站和无付费规划请求核对见 C:/tl/film-feedback/website-feedback-evidence.json。本轮范围为独立组件验证，组合成片、动态人物版本和用户视觉验收待完成。

网站仍登记全部 132 组。114 组有成功编码证据，其中 7 组同时保留失败历史。另有 17 组待实测、1 组仅有失败记录。原包 1426 项完整性复核、165 项相关回归、Ruff、目标 mypy 通过。本轮无外部付费调用、数据库迁移或部署。

## W-R11 线描手势与同期人物回切

新增本期透明线描分支。网站选用已登记的线描前景、上一景实录取帧，以及一张六列四行、每格 540×960 的透明 PNG。编译按顺序拆出 24 帧，检查透明区、非空画面、帧变化和每帧摘要。无效素材不会发布半套派生帧。原整片的素材登记仍指向已上传并校验的原图，原生子进程根据任务内摘要核对派生帧。原笔刷、纸面遮罩、入场和人物缩放回切继续由原引擎执行，历史手势原件的引用与缺失状态保留。

本期实录窗口为 5.370 至 8.250 秒。用实录「之前」「一瓶」「十几块钱」驱动线描标签和纸面文字。人物窗口用同期原片，不循环、不停留尾帧。新线描和手部素材是本期示意，上一景静帧取同一原片的 5.3 秒。组件实际运行原生 check 和 render-group，完整解码 86 帧，其中 84 帧不同。两次编码摘要一致，最终目录证据 ID 8188386d2997474f84895fe8ff7c48ad。组件 C:/tl/line-branch/native-v2/W-R11/renders/component.mp4 的 SHA256 为 b22d8e5ea0c7c7a5e45ab7367f16e896739efa34eb6b75fc905af2b163065037。

首个整片任务 03b29092-64f6-4aed-9e7f-1018a0faa518 因派生帧目录不能作为原整片登记文件而在原生检查失败。修正后保留原图引用，再由原生子进程打开已核验的任务帧目录，原素材校验仍执行。原包目录仍完整登记 132 组，115 组有成功编码证据，其中 7 组保留失败历史。另有 16 组待实测、1 组仅有失败记录。

修正后的本地网站任务 6a33d76b-a650-45e6-bb65-fe58c62abcf5 一次完成。Chrome 在手机宽度实播代理和高清，确认后下载通过摘要校验并支持 HTTP 206。48.475 秒成片含 11 种动效、16 条原库音效和低位背景乐。W-R11 手势提示音的起点为实录词点 5.870 秒。按从零开始的帧序号核对，第 175 帧的手势检测仍为空，第 176 帧已出现明显线描。回切后四处人物抽帧与同期原片对应，独立原声轨与同一实录的基准逐样本一致。高清文件 C:/tl/line-branch/website-line-hd.mp4，SHA256 027183f8746bf84cc0f17007be791aa3f61bb34b5de1ccdd70835b0e5bf52783。回执见同目录 website-line-evidence.json。

原包 1426 项完整性复核、166 项相关回归、Ruff、目标 mypy 通过。本期使用内部候选和已冻结的实录转录与对齐。未调用外部付费 API，未迁移或部署。真实规划模型选组与用户视觉、听感验收待验证。

## 已交付创意图回流剪辑项目

「本期补充素材」增加「已有创意图」来源。可浏览近期有交付产物的创意图任务，预览选中的原图，填写名称与用途后导入。剪辑项目仍按原有方式勾选素材，三图卡仍以实际口播词点绑定三张独立图。新接口只读同工作区已交付的可用图片，校验任务产物关联、文件格式、尺寸、字节数和摘要，再登记项目内原件。重复提交同一请求返回原登记，源任务后续过期时仍可复用已经导入的项目原件。

迁移 20261109_0049 增加可空来源任务和来源素材字段。旧素材无需回填。导入图片在规划请求中标记为示意，W-R01 的互动计数证据入口拒绝把这类图当作原始观察记录。测试确认输入图片、无权项目和被替换原件无法导入，保存后的项目素材能继续核对摘要后读取。167 项剪辑、文稿及原库回归、Ruff、目标 mypy、前端类型和目标 ESLint 通过。已在独立 SQLite 副本验证迁移，并生成 PostgreSQL 的增量 SQL。

浏览器联调使用三张本地绘制的用途图，在测试工作区以创意图交付记录登记。Chrome 实际预览并逐张导入「洗碗」「刷锅」「洗水果」。项目原件逐一与交付摘要匹配，规划请求收到同样的三个素材 ID 与示意标记。使用受控离线规划响应验证编译，无新生图请求、外部付费调用或部署。真实生图供应商的交付回流和用户视觉、听感验收仍待验证。

新网站任务 aa103449-b7c7-47e7-8f0e-0fb445c20270 首轮因联调 worker 未挂载原字体登记文件，在 W-R18 与 CX-G07 编译处停止。挂载原件后重试同一任务，11 次原生动效均完成。手机宽度 Chrome 实播代理与高清，确认后下载支持 HTTP 206。48.475 秒成片含 10 种动效、11 次使用、13 条原库音效和低位背景乐。39.11 至 43.11 秒三图卡以实录词点进入，三个入场音效与各自首帧同帧。三图卡期间 120 帧人物区域均核对到同期原片，原声分轨与基准逐样本一致。

本次使用与上次相同的示意图原字节，通过新素材 ID、规划和原生任务重新编码，下载摘要与上次一致。高清文件 C:/tl/image-result-import/website-picture-template-hd.mp4，SHA256 056850af6de8180c2e9de939a537d20c9ebeebcb0cd3232fcf247474fc22559a。原包 1426 项完整性复核通过。三张导入回执与整片证据见同目录 imported-materials.json 和 website-picture-evidence.json。原库仍登记 132 组，115 组有成功编码证据，16 组待实测，1 组仅有失败记录。

## 原字体恢复与四组原生验证

在本机 Windows 字体和组件库内按原摘要逐一核对，找到两个不同版本的同名宋体，但均不符合原登记。随后从微软下载服务器取得 Windows 11 22H2 Build 22621.1 的 Desktop Required ESD 和简体中文补充字体 CAB，在任务目录提取六份字体。宋体、楷体、微软雅黑常规、Arial、Times New Roman 常规和粗体的大小与 SHA256 全部匹配原目录。使用私有绑定清单登记这些文件。微软组件及字体保留在本机。[微软 Windows 11 22H2 发布说明](https://blogs.windows.com/windows-insider/2022/06/07/releasing-windows-11-version-22h2-to-the-release-preview-channel/)

SG-S05 用实际口播的「终于等到14块9」「到手两大瓶」验证原三字体轮换和金色前景，共完整解码 96 帧。AH-S06 用实录「A类」分别绑定中心、两侧和英文字母层，共完整解码 32 帧。两组同时保留原生 RGBA 序列，网站证据 ID 分别为 5c50d9f921f84f2e87e1b0dbb1eb97ca 和 d7d5d0553e504b068ad8812fcaebbcec。字幕内容是实录的表达，商品事实待验。

W-R17 的适配把「谁」映射为原四字形弧排可容纳的 `Who?`。两个独立问号均为本期登记的透明示意道具，原 3D 道具仍保留外部资源引用。两道具、英文和虚化分别锚定本期实录 4.870、5.030、5.190、7.210 秒。首轮用交接记录摘要核对时识别到归档入口差异，按原包完整性记录复核并固定实际入口。随后原生检查拒绝首事件与镜头起点同钟，编译增加相同约束，并按实测上一词的边界保留 0.200 秒入场前区间。最终 107 帧全解码且逐帧不同。两问号从局部第 7、11 帧明显出画，虚化前七处嘴部抽帧与同期原片对应。样本证据 4af9fb8ee7984d7bb3b30300f47fa7df，核对记录在 C:/tl/exact-windows-fonts/question/question-motion-evidence.json。

CX-G06 保留原固定「水果介绍」标题、圆图、三条说明和入场轨迹。规划请求明确标注适用主题，编译核验四张独立项目图片、原裁切区和三组各自的词点。联调用本机合成语音实际完成 FunASR 转录及强制对齐，三张水果插画在「荔枝」「榴莲」「香蕉」对应的 0.210、3.650、7.090 秒进入。首轮透明底板让浏览器留下旧描边，任务适配改为调用原引擎已有的纯色背景分支。重跑得到 269 帧，末段一处边缘扫描从 5 道旧描边减为 1 道当前描边。最终证据 93e90db631a9482095cffc70dd47961f，核对记录在 C:/tl/exact-windows-fonts/fruit/fruit-motion-evidence.json。此组联调头部圆图为水果拼盘插画。

网站目录 API 对照四组最新证据、各组原字体身份及 W-R17 的道具槽。原包 1426 项完整性和 168 项相关回归、Ruff、目标 mypy 通过。132 组中 119 组有成功编码证据，其中 8 组同时保留失败历史。另有 12 组待实测，1 组仅有失败记录。四组范围为组件验证，整片合成、听感与用户画面验收待完成。无外部付费调用或部署。

## 用途图回流与实景圆窗时钟

三图卡已支持从本期素材或已交付创意图中选择三张用途图。编排冻结素材身份、摘要及口播词点，原引擎裁切圆图，人物原画和原声保持同期。补图可以沿用创意图 API 的商品参考图流程，生成任务交付后导入剪辑项目。现有实测覆盖了测试交付记录至网站出片。外部供应商实时生图回流及按缺口自动发起生图待验证。示意图用于解释用途，商品包装及实际使用效果由对应实拍支持。

CXBR01 使用原 Times New Roman、原画幅、上方素材扩张、下方人物取景和缩圆及三段字幕。适配核验原生入口及取帧实现的字节摘要，公开合同注明顶层参考与人物槽共用本期原片。人物读取 13.890 至 20.730 秒，上方独立手势片段从第 89 帧起读自己的 0 秒。手势画面来自本期另一段实录，用于核对第二路时钟。首轮编译因缺少原参考源帧号的显式决定而停止，补齐决定后原生输出 720×1280、30 fps、206 帧，全部独立解码且帧摘要不同。抽验上方片段七帧和人物圆窗六帧，两路各自对应预期时点，平均像素绝对误差分别不超过 1.926 和 2.205。该组件沿用原视觉入口，音频由整片合成链路负责。

网站证据 ID 为 `e46a7df995e849ffb02ef76c34fcd32c`。帧核对、原生批次及目录回执保存在 `C:/tl/cxbr01-live`。原包 1426 项完整性复核、169 项相关回归、Ruff 和目标 mypy 通过。132 组中 120 组有成功编码证据，其中 8 组保留失败历史。另有 11 组待实测、1 组仅有失败记录。CXBR01 的整片语义和用户视觉验收待完成，本次未调用付费服务或部署。

## G04 原生焦点轮换与同期人物

CX-G04 保留原暖色全画布、卡片形状、叠放关系和焦点轨迹。首张卡从镜头第一帧展开，另外两张卡的焦点以实录首词触发。网站编译器要求同一期口播原片及三张不同的项目图，验证卡片标题、顺序、词点与切换区间。渲染端用原 U2Net 人物抠像和原视频取帧函数采样，将 RGBA 人物送入原浏览器人物槽。网站规划合同显示原人物、图片和词点要求。原库文件保持原摘要。

用本期实录 39.770 至 43.110 秒及已登记的「洗碗」「刷锅」「洗水果」三张示意图，实际渲染 720×1280、30 fps、100 帧。原生焦点切换的画面变化从组件第 13、31 帧可见。抽取 15 帧嘴部，与同期源帧和冻结首帧分别比较，除首帧本身外全部更接近同期源帧。组件证据 ID 为 `510ad8ebffbe4281b9fa009368756f04`，帧核对及目录回执在 `C:/tl/browser-rotation`。原包 1426 项完整性、170 项相关回归、Ruff 和目标 mypy 通过。132 组中 121 组有成功编码证据，另有 10 组待实测、1 组仅有失败记录。

本机网站接口通过独立 SQLite 副本接收试片任务 `391a9ef5-ddfd-4b9f-b320-fac37c26a69d`，联调调度在 HTTP 受理后调用真实剪辑 worker。经代理预览确认后下载的高清片长 48.475 秒，含 11 种动效、16 条原库音效和一条背景乐。G04 首次出画与两次焦点切换分别落在成片第 1194、1206、1224 帧，三个原音效实际起音与相应帧一致。口播分轨与同源基准逐样本一致，背景乐在发声区间较口播低 10.43 dB。代理与高清都返回 HTTP 206，下载摘要为 `019da6739751a9dffdbfe0ca284f222a7560995169d1def4e2ec1a376a77423f`。成片及核对记录为 `C:/tl/browser-rotation/website-rotation-film-hd.mp4` 和 `website-rotation-evidence.json`。抽看 41.4 秒时，双行主字幕的上行与卡片下沿局部重叠。本次用工程候选验证，实际规划服务选组及用户语义、视觉和听感验收待验证。

同入口 G05 活动帧每帧绘制原 `g05-assets/base-000.jpg` 至 `base-068.jpg`。核对原 ZIP 和资源映射，这组序列无原件及可用映射，仍登记为运行缺口。相同 ZIP 中 G09 的 `g09-bg/` 和 G10 的 `G10-background-clean.jpg` 也无原件，G10 的背景另有原摘要引用。

从微软 Windows 11 22H2 Build 22621.1 Client Features ESD 提取原 `msyhbd.ttc`，16,829,116 字节及 SHA256 `06e1a30f687ab7d39f533447b21e84d51e0cecdaa6bfa060c87136b168811bdc` 与 LYO 原登记完全一致，已登记在本机私有依赖清单。[微软字体目录](https://learn.microsoft.com/en-us/typography/fonts/windows_11_font_list)

LYO02 使用本期口播 0.410 至 3.590 秒，沿用原圆窗、虚线边、前景抠像与原字体。第 20 帧为完整原片，第 21 帧开始显示原圆窗机制，第 48 帧达到目标几何，第 55 帧随「两大瓶」首词出现弧形字。原生组件为 576×1024、30 fps，96 帧全部解码且画面摘要不同，已抽看人物嘴部及手势变化。网站证据 ID 为 `909fa4b12bb44eda861aad6ad408a82d`，核对记录在 `C:/tl/lyo-openings`。目录 132 组中 122 组有成功编码证据，其中 8 组也有失败历史，另有 9 组待实测、1 组仅有失败记录。

对 LYO01、LYO03、LYO04 的静态核查发现，三组原 schema 均禁止 `style`，共用原 `validate` 入口却要求 LYO02 的 `style`。三组的绘制分支只读各自的正文和事件。其原生验证边界待适配并实际重跑。

## LYO01、LYO03、LYO04 原生验证

先用当前实录复现三次原生检查失败，诊断均为原共用入口要求 LYO02 背景及几何。适配核对原加载器、渲染器和 LYO02 模板摘要，仅在这三个组的原校验函数调用中提供原模板样式。原 schema 继续校验提交配置，渲染继续读取各自的原配置。回归验证了错误的正文角色仍被原校验拒绝，绘制收到的配置没有新增字段。

- LYO01 保留原放大和暗角，使用 4.870 至 8.250 秒实录。「十几块钱」在局部第 30 帧出现，共解码 102 帧。证据 `2aeedd3500bf4233b2b340e375fce918`。
- LYO03 保留身后标题及前景抠像，使用 8.650 至 12.430 秒实录。主标题「14块9」于第 41 帧开始滑入，副标题「直接给你发两大瓶」于第 74 帧出现，共解码 114 帧。证据 `061a44cd6e47499d92c7123a9c124831`。
- LYO04 保留原窗口变形轨迹，使用 12.230 至 16.550 秒实录。「1000克两斤的大瓶装」在第 74 帧出现，共解码 130 帧。证据 `21103c67aaf04f0aa0e66765e493d101`。

三个输出均为 576×1024、30 fps，各自全部帧摘要不同。每组选六帧比较同期原片与冻结人物，除比较基准帧外均更接近同期原片。抽帧、像素比对和目录回执在 `C:/tl/lyo-openings`。原包 1426 项完整性复核、171 项相关回归、Ruff 和目标 mypy 通过。网站目录 132 组中 125 组有成功编码证据，其中 11 组保留失败历史。余下 CX-G05、CX-G08–10、HY-A1、HY-A2、AH-S03 待实测。本批验证原生组件，语义和用户画面、听感验收仍待完成。

## HY-A2 原斜卡与同期前景

网站编译器要求三张本期用途图、同一期背景图和同期口播原片，分别绑定原三张卡、背景和前景的槽位。三项图、标题和事件首词逐一核对。英文小字通过可信配方登记所对应的原话，沿用原 Arial；中文沿用原优设标题黑。经典 schema 的 `attributes` 仍为空，由已绑定的任务配方在原生材料化之后写入本期卡名与实测入场帧。原斜卡位置、角度、滑入方向、12 帧入场及画布均保留。

前景使用原抠像模型和原视频取帧，把本期 39.110 至 43.110 秒生成带透明通道的任务内 WebM。原 Hypit 以同一时间轴播放该轨，前景保持原 483、1014、597、906 像素区域和卡片上方层级。原生 Build `bld_20261109T104835064Z_889E852923` 输出 1080×1920、30 fps、120 帧，完整解码且各帧摘要不同。首尾 alpha 均同时含有效透明区与不透明人物，所抽十帧的人物区域除比较基准帧外均更接近同期原片。三卡首个可见帧分别为 21、33、51，运行结束后本任务 Hypit Runtime 状态为 stopped。证据 ID `f708aaf9cc3b4b1aac79f9dc36a3ea22`，核对文件在 `C:/tl/hypit-slant`。洗碗卡白字与图案的浅色区域局部对比不足，用户画面验收待完成。

本机网站接口在独立数据库接受工程候选，联调调度在 HTTP 受理后调用真实剪辑 worker。任务 `a7652318-fb0d-4492-a0c0-a8ce246f3768` 通过代理预览、确认及高清下载，代理和高清范围请求均为 HTTP 206。48.475 秒成片有 11 种原生动效、16 条原库音效及一条背景乐。HY-A2 三张斜卡分别在成片第 1194、1206、1224 帧开始可见，实测起音分别为 39.800、40.200、40.800 秒，和可见帧一致。原声分轨与基准逐样本一致，发声期间背景乐低于原声 10.43 dB。成片 `C:/tl/hypit-slant/website-slant-film-hd.mp4` 的 SHA256 为 `29ef71386222566996590b0238ccdacf8d3f417255ca6c74474ed560487bbc84`，证据见同目录 `website-slant-evidence.json`。本机工程候选验证覆盖整片链路，真实模型选组、用户画面及听感仍待验收。

原包 1426 项完整性复核、172 项相关回归、Ruff 和目标 mypy 通过。网站目录核对原抠像模型、前景素材类型及原生输出，132 组中 126 组有成功编码证据。余下六组中，CX-G05 仍缺 69 张活动背景帧。CX-G08–10 仍缺共用入口两款原励字字体，CX-G09 另缺 66 张原活动底板及原图，CX-G10 另缺原活动底板和人物图。HY-A1 原俊雅体资源标注为非商用，AH-S03 原 Aa 研宋未登记，后者所需 Times New Roman Bold 和 Impact 已核验。字库官网分别公布商用授权要求，尚待核对实际项目授权及交付字体字节。[励字超粗黑简繁](https://www.dreamfont.cn/font/lizichaocuheijianfan.html) · [Aa 字库授权](https://www.aafont.com.cn/license/font/)

## 网站模板接入 G04 原生轮换

网站模板「三图轮换与口播重点」把 CX-G04 和原文字、报价及追问动效列入同一模板。规划可按口播选择多组动效，同一组可在不同语段复用。G04 要求三个并列事项各自绑定实录短词、短标签和不同的项目图片，同期人物由原视频时钟驱动。三张卡按实测词点触发原焦点轨迹，并各自配一次原库提示音。主字幕在 G04 窗口进入下方通道，原卡片的叠放关系和入场构图保留。既有模板 ID 和旧任务继续按已冻结的配方读取。

用途图优先复用本期已核对的实拍或已交付的创意图。产品图接口支持上传商品参考图，创意图交付后可导入剪辑项目，由各原生组按自有形状裁切。此路径已用测试交付记录验证。供应商实时出图和按缺口自动发起生图待验证。

本机网站接口在独立数据库接受了受控离线模型响应。实际规划 worker 校验语义合同并自动编译，后续通过网站任务接口提交原生候选，执行真实剪辑 worker。整个测试无需人工改配方。任务 `f0b634e2-1590-4d52-8db7-758fc51da345` 通过代理预览、确认及高清下载，代理和高清范围请求均为 HTTP 206。

本次成片长 48.475 秒，10 种动效、11 次使用，BG-S06 出现两次。混入 13 条原库音效和一条背景乐。三次图卡出画分别在第 1194、1206、1224 帧，对应实测起音 39.800、40.200、40.800 秒。十张成片抽帧的嘴部区域均更接近同期人物帧。原声分轨与同源基准逐样本一致，背景乐在发声区比原声低 10.43 dB。原生版式检查通过，卡片底部和主字幕实际像素的最小间距为 8 像素，抽看 41.4 秒确认两者分离。

高清下载文件为 `C:/tl/rotation-template/website-rotation-template-hd.mp4`，SHA256 为 `621172bd4716c683d87cdb5bbf108f32dc148ba6bb1aa7005f980e8c123190af`，证据见同目录 `website-rotation-template-evidence.json`。本次规划由一条受控响应验证，三张用途图采用已登记的本期插画。真实规划服务选组、生成供应商实时交付及用户视觉、听感验收待完成。

原包 1426 项完整性复核、173 项相关回归、Ruff 与目标 mypy 通过。目录仍登记 132 组，其中 126 组有成功编码证据。再次核对本机剪辑资料、交接目录和运行目录，六组的缺件及字体授权状态仍按上节记录。

## 文稿双模式与确认快照

文稿页默认选择「借鉴结构创作」。新稿按已保存拆解的段落功能组织，允许拆句和合句，正文逐行引用对应的事实卡条目。编排必须按顺序覆盖各段，拒绝未知事实、未经映射的数字和标为不可照搬的原文。目标时长只提供口播字数估算，实际时长由录音决定。

「按原结构改编」保留原逐句映射和原 `shadow_check.py`。现有省略写稿模式的 API 请求继续按原模式处理，历史请求摘要和已保存草稿可继续使用。新请求冻结显式模式，保存结果及采用草稿时按各自的数据结构读取。页面可切换已保存草稿，逐项显示该版引用的原句或段落功能，以及该版使用的事实卡。

在独立数据库中用 Chrome 保存参考原文和分析，选取本期事实卡，分别提交两种模式。受控响应中，借鉴结构产出三行，逐句改编保持原两句并通过原包检查。页面切回三行版本后明确采用，编辑器此前保存的口播稿直到采用时才更新。再经原确认接口生成独立快照，核对新旧两份确认稿各自保留原文。浏览器联调证据为 `C:/tl/writing-modes/browser-evidence.json`，任务与回执均存于本机联调目录。使用封闭 HTTP 测试传输和原写稿 checker，真实供应商写稿、生成配音与数字人以及用户语义验收待完成。

357 项视频和文稿回归、目标 Ruff、mypy、前端类型及 ESLint 通过。OpenAPI 仅增加可选写稿模式字段，无数据库迁移。原写稿包 33 项和 Motion 原包 1426 项摘要复核通过。本轮 Motion 目录仍登记 132 组，126 组有成功编码证据。

## PostgreSQL 迁移与剪辑 worker 依赖

在本机独立测试数据库使用与项目 Compose 同版本的 PostgreSQL 18.4。运行从空库到 `20261107_0041`、升级到 `20261109_0049`、回到 `0048` 再升级、回到 `0041` 再升到最新。升级前先通过原项目 API 保存确认稿。每次迁移后核对该项目、确认稿快照和旧任务的版本关联。另在 `0048` 保存一条旧上传素材，升至 `0049` 后旧标签和摘要仍可读取，新增来源字段均为 null。数据库验收覆盖剪辑、规划及写稿的 12 张新增表。运行记录 `C:/tl/pg18-motion/migration-evidence.json`。[PostgreSQL Windows 发行页](https://www.postgresql.org/download/windows/)

原生剪辑子进程保留 worker 的 `PLAYWRIGHT_BROWSERS_PATH`，继续使用固定环境白名单。实际通过 worker 子进程入口从指定目录启动 Chromium 156.0.8078.4 并读取本地测试页。回归覆盖浏览器路径传入和文稿服务凭据隔离。

额外需要原字体或原模型的本地 Compose 可合并 `compose.editing-dependencies.yaml`。将已校验且可供当前项目使用的原件和 `bindings.json` 放进同一私有目录，令 `POLARIS_MOTION_DEPENDENCIES_HOST` 指向该目录。清单的 `resources` 对象仍以原资源 ID 为键，值填写容器内绝对路径，例如 `/motion-dependencies/fonts/original.ttf`。用 `docker compose -f compose.yaml -f compose.editing.yaml -f compose.editing-dependencies.yaml config` 查看合并配置。API 和剪辑 worker 共用只读依赖目录和原有可写任务卷。文件进入运行时仍按原包登记核验字节数及 SHA256。Compose 合并实测通过，Linux 镜像构建和容器实跑待验证。

18 项相关回归、Ruff 和目标 mypy 通过。原 Motion 1426 项及原写稿 33 项完整性复核通过。

已迁移的 PostgreSQL 由实际 FastAPI 和独立 Celery worker 共用。通过 HTTP 上传本期原口播、重复提交同一请求并核对相同任务 ID，维护入口把持久任务交给独立的本机 Redis。任务 `12ca31bb-1886-4c1a-aceb-9fc9f1c182c3` 一次完成，FunASR 本次重识别得到 243 个词点，原引擎渲染 48.475 秒基础字幕成片。成片音视频全量解码通过，HTTP 范围读取返回 206，Chrome 从 API 实播超过两秒，readyState 为 4。下载摘要 `027037390749881fbe56e9f09280f9d9729df4835306cd138504d8e4ca6a6f18` 与登记相符。文件 `C:/tl/pg18-motion/website-postgres-oral.mp4`，证据同目录 `website-postgres-worker-evidence.json`。这条任务复用实录，覆盖 PostgreSQL 上的运行和基础字幕，语义组合与用户视觉验收另行核对。Motion 目录仍为 132 组，其中 126 组有成功编码证据。

## 人物开场与口播重点模板

新增组合模板 `presenter-openings-v1`，把老于的 LYO01 至 LYO04 和已有原生透明字效放入同一套可选组合。四组分别保留放大暗角、圆窗、人物身后标题和变形窗口。本期人物素材须匹配实录原片摘要，人物源窗口由真实语音词点编译，片段结尾采用原 `error` 策略。标题与说明锚定各自首词，按原字号容量和网站阅读时间规则预检。圆窗的两个变形词点须先于主题，身后标题的原 10 帧入场须先完成。使用原微软雅黑粗体以及需要时的原抠像模型。原包和旧模板版本保持独立。

Chrome 已从网站选择模板并保存语义准备任务 `6d446a3f-dc4b-4a1f-9a72-0614e2b48e01`。准备请求保留原库 132 组和 240 个实录词 ID，本模板有 14 个候选槽。四组各用现有实录输入通过网站配方和原生 check，编译帧数分别为 102、96、114、130。浏览器和原生检查记录在 `C:/tl/presenter-template`。176 项剪辑、写稿和原库相关回归及原包 1426 项完整性复核通过。

首次整片 `49e76435-d11c-4847-8c75-682b11c96e29` 在 LYO01 段发现主字幕与原生强调词挤在一起。为本模板的 LYO01、LYO04 窗口单独设定 1280 高画布上的 1110 像素字幕基线，按输出高度缩放。原生强调词的字号、颜色和位置保持原样，LYO03 的身后叠字沿用原层级。修订编排的两段 LYO01 主字幕由实际 libass 生成墨迹，字幕上缘在 1070 像素，原生强调词实测底缘为 990 像素。

修订任务 `7e0bd10f-c123-402d-aa7d-e7b265011ddd` 用受控规划响应从网站自动编译，真实剪辑 worker 完成出片。48.475 秒包含 11 种原生动效、11 条原库音效和一条背景乐。11 段原生组件重新编码后摘要与首轮一致。成片两段共十处人物采样均对应同期运动，独立口播分轨逐样本与同源基准相同。两次强调字出画在第 176、333 帧，实测音效起点 5.870、11.117 秒，与出画相差 3.33、16.67 毫秒。发声期间背景乐比口播低 10.43 dB。原生版式检查通过，LYO01 与 LYO03 的主字幕距原生下部文字最小间距分别为 80、39 像素。抽看修订版 6.4 秒确认两层分开。

代理预览和确认后的高清下载均支持 HTTP 206。高清为 `C:/tl/presenter-template/revision-2/website-presenter-template-hd.mp4`，SHA256 `c0fc89dab44a57b74dc9640213a13a48225327d3fadd0f5a05c0ee818f74e1ea`，同目录保存核对记录。真实规划服务选组、用户语义、听感和画面验收待完成。原库 132 组仍完整登记，126 组有成功编码证据，余下六组待补原件或授权。修订后 176 项相关回归、目标 Ruff 和 mypy 通过。

## 语义规划读取全库实测状态和原件校验

准备任务保存版本化的原库状态，覆盖原有 132 组。规划请求逐组带入已有编码样本状态，并在已识别的外部字体或模型上列出原资源 ID、依赖范围和当前核验状态。历史样片状态与当前模板可用性分开，历史素材及原件仍按原目录保留。请求仅传入可公开的资源 ID 和状态，实际原片词仍只有词 ID 与文字。

自动模板的已知必需原件由配方与准备任务共享同一份映射。准备时缺少必需原件的组仍在目录和模板中登记，当前规划候选须避开这些槽。开始提交前复核准备时可用的槽，如果原件不再能核验，模型请求停在未提交状态。存在提交标记时保持原请求用于恢复。已保存的旧准备请求保留原协议和摘要。API 和剪辑、规划两个 worker 在可选 Compose 里共用只读原件注册目录，实际 Linux 镜像运行仍待验证。

本机实际准备请求带出 115 组成功样本、11 组同时有成功与失败记录、6 组未实测。用已登记的本期 240 个实录词和一次受控响应生成新候选 `03d480b8-8164-400d-a076-c220a6e21e5f`，其配方与此前完成原生出片的人物开场试片相同。另在隔离清单中移除原微软雅黑粗体，准备后发生变化的请求在供应商入口前停止。重新准备时浏览器列出 LYO01 至 LYO04，完整目录仍为 132 组。受控响应如果强选这些槽，合同校验拒绝。已有准备请求 `6d446a3f-dc4b-4a1f-9a72-0614e2b48e01` 也用受控响应验证了原请求摘要可继续使用。证据见 `C:/tl/runtime-planning/runtime-planning-api-evidence.json` 和 `browser-runtime-planning.json`。

177 项剪辑、写稿及原库回归、目标 Ruff、mypy、前端类型及 ESLint 通过。原包 1426 项完整性复核通过。OpenAPI 仅增加可选缺件组列表，无数据库迁移。此轮覆盖准备、候选及原件校验边界，真实规划模型和最终用户验收待继续。
