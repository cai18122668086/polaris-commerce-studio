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
