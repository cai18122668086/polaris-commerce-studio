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


## 按方向找抖音对标

视频编辑器和文案助手增加独立「找对标」入口。用户输入关键词，选排序和发布时间，每次点击明确提交一页。同一请求或同一页的重放返回已有任务。原请求结果不明时保留原任务，禁止续提。每次搜索最多十页，旧页有效期在网站显示。接入沿用现有 EveryInfra 适配器与文案任务记录，功能默认关闭，启用需要现有提取配置和服务端开关，无数据库迁移。供应商按页计一次调用。[EveryInfra 关键词搜索合同](https://everyinfra.com/douyin-api/search)

每页保存抓取时间、关键词、来源作品 ID、规范链接、有限的原始字段、归一化字段及供应商回执。以作品 ID 跨页去重，跳过非视频、不一致来源及已知超过 300 秒的视频。公开结果显示逐条媒体待核验状态、有效样本的作者数、同作者最高作品数、作者缺失数、藏赞比和转赞比。互动缺失保留空值，零点赞时比值为空，供应商示例中的播放数不用于播放转化。播放签名不落库，翻页令牌只保存在服务端。选中候选只填入规范来源链接并带上搜索任务引用，语音提取由另一次点击启动，提取文本单独保存为原文版本。

Chrome 在独立 SQLite 项目实测从两页结果选择候选、重放第二页、切换到提取并保存独立原文版本。第二页跨页去重一条，重放同一页保持相同任务 ID，选择链接前后均只有两次受控搜索调用，用户点击提取后增加一次受控转录调用。浏览器的待提取输入保持空白，作品描述未进入原文，现有项目稿件保持原样。证据见 C:/tl/benchmark-writing/browser-evidence.json 与同目录截图。216 项视频、文稿及原库回归通过，Ruff、目标 mypy、前端类型及 ESLint 通过。供应商接口使用本地受控响应。真实搜索回执、媒体可用性与落地、跨账号语义分析和付费账单仍待验证。本轮无付费调用或部署。


## 三图卡的本期素材预检

「三图卡与口播重点」和「三图轮换与口播重点」在准备规划请求时统计已选且原件核对通过的本期图片，按 SHA256 去重。同期人物原片与其他视频不计入图卡配图。准备结果分别列出缺少原库依赖的组和本期图片数量，完整的 132 组目录继续保留。图片不足时，当前图卡槽退出候选，模型可选同模板里语义适合的文字动效或留白。图卡仍须为三个实录并列项各绑定一张不同图片。已有准备版本保留原请求摘要，新准备版本才写入图片条件。自动生图调用独立于此次预检。

浏览器从已有实录转录准备三图轮换模板，显示 CX-G04 已选 0 张、需要 3 张。下载请求含全部 132 组、12 个模板槽和 240 个实录词 ID。另用本项目已登记的三张用途图重新准备，规划回执记录三张，受控响应通过原生图卡编译。测试覆盖 0 张、三次上传中两份不同原件、三份不同原件、重复配图以及用原片冒充图卡素材。219 项相关回归、Ruff、目标 mypy、前端类型和 ESLint 通过，原库字节和目录完整性复核通过。浏览器记录在 C:/tl/template-image-preflight/browser-image-preflight.json。


缺图时用同一条真实口播执行网站规划、原生编排、独立 worker 出片、预览确认和高清下载。网站任务 4b0cfc24-5224-4175-ab49-1cb262bb7ee5 生成 48.475 秒新成片，含 10 种动效共 11 次，BG-S06 出现两次。11 条原库提示音分别与编译的入场时点一致，混入一条原库背景乐，发声期间低于口播约 10.43 dB。原声分轨与同源基准逐样本相同，三图卡原定时段抽验 98 帧嘴部区域与同期原片，最大平均像素绝对误差低于 1.91。原生版面检查通过，代理和高清范围请求均为 HTTP 206，下载摘要与产物记录一致。

高清样片为 C:/tl/template-image-preflight/website-no-illustrations-hd.mp4，SHA256 为 172992ed4f942a230b56289df5a95de04f6ce5b473f8c936ce9326bbb4f7101c。同目录 website-no-illustrations-evidence.json 记录验证范围。两种素材状态的规划均通过受控离线响应验证，真实规划模型的选组、配图语义及用户观感和听感仍待验收。本轮无外部付费调用、迁移或部署。


## W-R14 证据判断组合模板

网站增加「证据判断与口播重点」，可用原 W-R14 以及十种透明字效。W-R14 需要实际口播比较、两份不同项目图片和同期视频底片。依据原出画机制，第一个词组对应右上透明图和勾，第二个词组对应左下图和叉，后续实录结论驱动竖排文字。准备任务核对两张图的原件摘要及透明像素，透明位按素材 ID 冻结。模型只提交已有词 ID、素材 ID 和原生字段路径。两份图不足或没有透明图时可用模板的其他动效。原引擎继续执行布景、勾叉、原包登记的可编辑字体及遮罩退出。主字幕保留完整内容，判断期间走底部通道。

在本机 Chrome 选择模板和真实实录，准备请求仍含原库 132 组和 240 个词 ID。无配图时回执列出需要两份不同图及零份透明图。浏览器核对见 C:/tl/judgment-template/browser-judgment-preflight.json。另用两张根据实录内容制成的口播引用图，核对「到手两大瓶」与「先前买一瓶」。引用图作为画面说明，商品和成交事实待独立核验。

首轮新组件完整解码 235 帧，540×960、30 fps。原勾首个清晰可见帧为局部第 25 帧，叉为第 164 帧。直接使用实际词点作为声音起点会使勾声提前，适配层改为按 Build12 原分段时钟与整片帧时基定位可见帧。首轮整片主动取消，保留组件与取消回执。修订同时把原生版面检查的字幕安全区扩展到底部通道。初轮留存 C:/tl/judgment-template/initial-film-submission.json 与 initial-film-status.json。

第二轮整片完成原生编码后，网站声音验证因尚未识别 W-R14 的显式出画回执而阻止交付。验证器现在会从原生镜头和词点重新计算出画帧，并核对动作路径、原音效身份及导出起声。用该轮实际编码和声音分轨单独重验，原生混音与主字幕校验通过。按从零开始的成片帧号，勾和叉分别在第 37 和第 176 帧首次出现，检测的提示音起声与其同帧。网站旧失败回执保存在 C:/tl/judgment-template/pre-retry-film-status.json。

同一网站任务 445ae07c-f710-4d7d-9bd3-351968bfc5fd 通过原重试入口第二次执行，沿用原规划和候选。重试完成代理预览、确认和高清下载，两种产物范围请求均为 HTTP 206。48.475 秒新成片含 10 种动效、14 条原库提示音和一条原库背景乐，发声期间背景乐低于口播约 10.43 dB。原声分轨与同源基准逐样本一致。最终下载件中勾和叉分别与提示音同在第 37、176 帧，画面和音效分轨独立复核通过。九帧底片样本均更接近同期原片，原生版面检查通过。

高清 C:/tl/judgment-template/website-evidence-judgment-hd.mp4，SHA256 04f6978d4eacd4266219b2ad4fa6c37bfcfd0b852ebac4b90a454bca00596785，输出核对记录为同目录 website-evidence-judgment-evidence.json。221 项视频和文稿相关回归、Ruff、目标 mypy、前端类型和 ESLint 通过，原库 1426 项摘要复核通过。本轮规划使用受控离线响应，无外部付费调用、迁移或部署。真实模型语义、完整画面与听感待用户验收。

430 像素宽 Chrome 从项目成片卡实播 720×1280 下载件，在判断段从 5.50 秒播放到 6.61 秒，并通过页面「下载成片」取得同一摘要。浏览器收到了两次 HTTP 206 媒体响应。回执为 C:/tl/judgment-template/browser-judgment-playback.json。


## 局部调整原生动效强调词

「调整本次出片」增加「改动效强调词」。首批开放原 BG-S04 两处竖排词和 AH-S05 跳字强调词。候选短语来自编排绑定的实录，使用同一段内连续的词 ID。并列项有独立词范围时沿用其范围，邻近词槽保留各自边界。含数值或否定的短语保留已有编排，原生字数、句界和剩余阅读时间参与候选检查。前端优先呈现边界完整的短语，保存及重试按词 ID 读取。

调整沿用现有任务选项 JSON，随本次代理预览持久化。编译只重绑选中原生字段的文字和对应入场事件，复用原生模板、音效策略和真实词点。编译回执记录原词、新词、字段、入场词点和用户锁。旧编排、旧成片及原始模型回执保留原摘要。旧请求省略新增字段，幂等标识沿用既有规则。用户新建另一份规划时仍可核对自己的调整，当前锁绑定到具体出片任务。

Chrome 从原编排选中「洗水果」并提交预览，接口按对应词 ID 保存这项调整。重放同一请求返回原任务，跨段或其他转录词 ID 被拒绝。浏览器提交校验和另行运行真实剪辑 worker 的试片独立记录，浏览器联调用任务在核对后取消。浏览器证据 C:/tl/highlight-edits/browser-highlight-selection.json。

网站剪辑任务 d1ff969d-6924-42d6-a3df-263af330ff57 使用已有真实口播，通过独立 worker 重新编码 48.475 秒整片。仍含 10 种动效和 11 次使用。对比前后原生配置，BG-S04 的右侧词由「刷锅」改成「洗水果」，局部入场由第 32 帧改为第 50 帧，对应实录 40.770 秒。剔除任务输出路径后，其他镜头配置、主字幕、混音计划及原候选摘要一致。两个高清文件的解码音轨逐样本一致。抽看 41.4 秒确认右侧新词，人物区域和段外画面另有像素核对。Chrome 在 430 像素宽窗口实播并从网站下载，摘要与最终产物记录一致，代理和高清均支持 HTTP 206。

另以实录「真划算」改成「划算」运行 AH-S05 原生组件，跳字由局部第 127 帧移到第 130 帧，完整解码 138 帧。组件证据为 C:/tl/highlight-edits/ah-s05-edit-evidence.json。高清试片为 C:/tl/highlight-edits/website-highlight-edit-hd.mp4，SHA256 bc677fa51224baf9f0a5e611668095bbce4fbb6cf16b159a43b2eb3cd0fb87b1，证据同目录 film-api-evidence.json 与 browser-highlight-playback.json。223 项相关回归、Ruff、目标 mypy、前端类型和 ESLint 通过，原库 1426 项摘要复核通过。本轮复用已有受控规划，局部修改与出片阶段没有模型调用或外部付费，未迁移或部署。用户的整片画面与听感验收仍待完成。


## 按实录卡片局部替换配图

「调整本次出片」增加「替换配图」，按真实口播词组列出原生图槽。首批开放 CX-G07 三图卡、CX-G04 三图轮换及 W-R14 判断图。素材来自本期已登记的上传原件或已完成的创意图。API 按用户、工作区、项目核对素材 ID 与原件 SHA256，拒绝原片路径、重复配图和不符合透明图槽的图片。W-R14 右上图必须有实际透明像素。现有生图工作流仍由用户另行发起，剪辑出片不自动提交生图任务。

替换随本次出片冻结。CX-G07 同一张卡的两个原生图字段同步更新，原引擎负责圆形裁切，并可按图片色彩重算卡片配色。保留原编排、词点、卡片轨迹、背景和音效绑定。回执记录原图、新图及双方摘要。网页提交、任务重放和 worker 均复用现有版本及幂等约束，无数据库迁移。缺少合适图片时继续沿用模板预检与文字动效方案。

Chrome 实测显示三张用途卡，可查看新图原件及提交替换。独立网站任务 516d4ad1-bc9a-4b37-86d4-798964eee513 将「洗水果」换成本地登记的红色水果示意图，重新编码 48.475 秒整片。10 种原生动效共 11 次，含 13 条原库提示音和 1 条背景音乐。旧编排及编译配置比对只显示 CX-G07 的同一卡两处图片绑定变化，字幕、动画时点和声音计划一致。两个高清件解码混音逐样本一致，原声分轨摘要也一致。120 帧原生透明组件的遮罩逐帧一致，画面差异从该卡原入场第 50 帧起，限于卡片范围。W-R14 和 CX-G04 已核对历史真实编排的可编辑字段及针对性回归，这次整片使用 CX-G07。

代理与高清范围请求均为 HTTP 206。430 像素宽 Chrome 在 41.55 至 42.66 秒实播高清，并从页面下载同一摘要。高清试片 C:/tl/image-edits/website-image-edit-hd.mp4，SHA256 2a21a6dbf9c3178a949e154362a7819577ed7864779a12f2bc952eb2fb1050f3。验证记录为同目录 film-api-evidence.json、browser-image-selection.json、browser-image-playback.json 和 component-evidence.json。226 项视频、文稿与原库回归通过，Ruff、目标 mypy、前端类型和 ESLint 通过，原库完整性复核通过。本轮使用已有示意图和已冻结的受控规划，无模型调用或部署。真实按需生图、配图语义和用户观感仍待后续验收。


## AH-S03 原 A 版与原入口缺件

原 ZIP 的 AH-S03 目录交付了两份同引擎输入。归档目录默认指向 B 版，保留 Aa 研宋、Times New Roman Bold 和 Impact 原角色。A 版按原文件摘要显式选用，三处字形分别绑定原包思源宋 Heavy、本机已核对的 Arial 和优设标题黑。A/B 字体身份、模板摘要及本期样本状态分别显示，B 版 Aa 研宋仍待补合规原件。没有修改原输入、原默认入口、绘制源码或字体。A 版编排把本期两段相邻实录词绑定到左右文字，英文释义单独记录来源和词 ID，问号沿用原图形。

原生组件采用本期实录「你们」「谁」及人工核对释义 WHO AMONG YOU。独立解码 36 帧，画幅 576×330、30 fps。原生透明帧抽验，红字、英文和问号分别在局部第 7、12、17 帧出现，都是各自原事件之后的第一帧。整片提示音采用原入场透明度机制算出的首个可见帧，交付检查从镜头配置重新计算。原生组件证据 a7a5328a0fa54d57a68379d004e172b8，详见 C:/tl/ah-s03-original/native-a。

复核了两份原 ZIP 的 SHA256 和 Motion 原包 1426 项摘要。网站目录按原档案索引核对启动文件。CX-G05 的背景 69 张、人物透明序列 69 张及原照片 3 张均未进入原 ZIP。CX-G08、G09、G10 使用同一启动入口，该入口先加载两款励字字体、三张原素材、66 张 G09 背景和 G10 背景与人物图，再接收当前任务输入。两张 G10 原件已有外部资源 ID，其余列明文件模式和数量。HY-A1 继续显示原俊雅体非商用标记。档案计数不等同于任务绑定或实际运行，证据见 C:/tl/ah-s03-original/archive-evidence.json。

第一次及声音校准后的整片尝试均被原通用版面检查拒绝。原检查记录 12 帧同一对原生角色重叠，英文位于原引擎指定的问号前景之下。编译器给 A 版镜头写入明确的原角色校验意图，运行时在固定原 AH-S03 渲染器及原校验入口摘要后，只分类问号已开始、画面未清除区间中的英文和问号角色重叠。保留原失败报告摘要及每帧坐标。主字幕、人物保护区和其他角色冲突仍阻止交付。回归用实际首轮报告及故意注入的保护区冲突核对了边界。

网站任务 ff083401-efe3-4acc-a489-a540a514bcc3 由实际剪辑 worker 完成。48.475 秒成片有 10 种原生动效、11 次使用、13 条提示音和 1 条原背景乐。A 版黄色问号和对应提示音在成片第 157 帧同时出现，约 5.233 秒。对比 155 至 167 帧的八帧人物区域，最大平均像素绝对误差为 1.597，人物与同期原片一致。原声 WAV 摘要与基准一致。原校验报告和单独适配报告均保留，后者仅确认所记录的 12 帧原生角色叠放。

Chrome 430 像素宽窗口实际播放高清追问段，代理和高清均支持 HTTP 206，从网页下载摘要一致。试片 C:/tl/ah-s03-original/website-question-card-a-hd-final.mp4，SHA256 37d6fd550f24cd263969f073b1631f68b17a65eb7fbbdf330744e21f3816087a。网站目录、音画抽验和播放证据在同目录 catalog-evidence.json、film-verified-evidence.json 和 browser-question-a-playback.json。230 项相关回归、Ruff、目标 mypy、前端类型及 ESLint 通过。

全库 132 组中 127 组有本期编码证据，其中 11 组也保留失败历史。其余 5 组为 CX-G05、CX-G08–10、HY-A1。AH-S03 B 版单独保留未验证状态。整片采用可信工程候选与实录，真实规划模型选组、用户完整画面及听感验收仍待完成。本轮无外部付费调用、数据库迁移或部署。


## 透明问号自动组合模板

网站新增「透明问号与口播重点」，包含原 AH-S03 A 版和十个原生文字槽。旧模板 ID 和各自的请求内容保留。新模板的请求只给模型实录词 ID 和文字，接受两个相邻短语的首尾词、五个原生动作的实录边界以及最多 24 字符的英文释义。服务器核对原片词点、两处短语顺序、原生放大和淡出的剩余帧，再编译 A 版原字体、字形、画布及事件。英文释义附来源词 ID，网站候选显示待核对状态。原 A 版前景叠放和逐帧音效定位沿用既有规则。旧编排没有新增字段时保持原序列化与摘要。

Chrome 实测从本期实录选择新模板并准备请求，准备记录保留 132 组及 240 个实录词 ID。候选卡显示 WHO AMONG YOU 并标明待核对。测试移除本机字体绑定，预检只将 AH-S03 列为本模板缺件，校验拒绝选用该槽。另重算已归档「证据判断与口播重点」的准备请求，SHA256 仍为 7fd010f05666088fc8f93ccf2cdacd46dec3d90fd2debec36b03f5b0feed959c。浏览器与依赖证据为 C:/tl/ah-s03-automatic/browser-template-evidence.json 和 dependency-evidence.json。原库 1426 项摘要复核通过。

受控规划响应经实际网站准备、生成任务、血缘校验及候选保存。重复保存返回同一候选，原生配方由服务器直接编译，人工配方修改次数为零。剪辑任务 ef87379d-d740-465e-a326-6801f25c41a5 完成独立 worker 出片、代理预览、确认及高清下载。48.475 秒成片有 10 种动效、11 次出现、11 条提示音和 1 条原背景乐。A 版问号和提示音仍在成片第 157 帧出现，八帧人物抽样与同期原片一致，口播分轨和同源基准逐样本一致。原版面报告和仅分类原英文与问号叠放的适配报告均保留。

Chrome 在 430 像素宽窗口实播追问段，代理与高清范围请求均返回 HTTP 206，页面下载摘要相同。高清为 C:/tl/ah-s03-automatic/website-transparent-question-hd.mp4，SHA256 3267c33b46a4b3dca58c612fd9dcdba58be46a533ff7a522649de748c4007043。音画核对在同目录 film-verified-evidence.json，浏览器记录为 browser-question-a-playback.json。本次本机整片任务约 18 分钟，包含原生逐组版面校验。

231 项相关回归、Ruff、目标 mypy、前端类型及 ESLint 通过。132 组仍完整登记，127 组已有本期编码证据。本轮没有外部付费调用、部署或数据库迁移。真实模型选组与释义质量、用户画面和听感仍待验收。

## 原生成口播与确认稿来源核对

已有口播生成结果进入剪辑时，保存生成任务、原确认稿版本、入选视频摘要及独立配音摘要。在同一项目中核对口播任务记录的文稿与原确认稿，发现不一致时停止接入。已发布的编辑任务仍能读取。音频驱动的旧草稿文字不参与新来源的识别参考。选片控件和剪辑任务卡显示原确认稿编号，可下载不含磁盘路径的来源回执。数据使用已有 EditingSource 记录，无迁移；handoff v1 保持原行为。

worker 用实际探测值核对独立配音和视频内音轨的起点与时长。回执分别报告容差内、时钟不同、文件变化、缺失或无法核对，容差为 50 毫秒起点和 100 毫秒时长。该结果只描述时间，剪辑和识别继续使用冻结视频的原音轨。独立配音不参与混音，不会触发配音或口型重做。

在独立 SQLite 项目保存口播稿，从现有配音及口型入口完成两次受控供应商协议响应，返回真实录音 MP3 和真实录制视频。随后推进项目草稿，再从已完成的原生成任务创建剪辑。确认稿、原视频和配音摘要与旧 ZIP handoff 一致，重复提交沿用同一剪辑任务。实际 FunASR 生成 243 个词点，并保存与参考稿的差异。独立 MP3 相对视频音轨起点晚 35 毫秒、时长短 19 毫秒。本机原生基础剪辑重新编码完整视频，接口 Range 206，下载摘要与产物一致。浏览器选片和任务卡均显示原确认稿编号，并验证来源回执摘要。原生成服务使用本地受控响应，本次没有实际商用配音、数字人生成或付费调用。

实际另编码带 218 毫秒起点偏移的 M4A，适配器将其归为时钟不同。回执在 C:/tl/generation-motion-source/clock-negative-evidence.json。用已保存的本期工程校对稿在同一真实音频上执行 fa-zh，对齐为 240 个词点，原 FunASR 记录及确认稿分别保留。对齐状态为 operator_candidate，等待用户核对。之后用受控规划响应经实际网站保存原生候选，独立剪辑 worker 重新生成组合试片。

剪辑任务 d221f263-80a6-4f50-80c7-f2b6f1c48839 的基础、校对、组合三个阶段共用同一视频源 ID，三份来源回执逐字节一致。48.475 秒组合试片有 10 种动效、11 次使用、11 条原库提示音和一条原背景乐。原口播分轨逐样本一致，黄色问号与提示音在第 157 帧出现。高清重新编码后的 SHA256 与上一轮同音频和编排的试片一致。代理与高清请求均为 HTTP 206，430 像素宽 Chrome 实播并下载同一摘要。

高清 C:/tl/generation-motion-source/website-generation-motion-hd.mp4，SHA256 3267c33b46a4b3dca58c612fd9dcdba58be46a533ff7a522649de748c4007043。证据见同目录 film-verified-evidence.json、browser-generation-motion-playback.json、browser-source-evidence.json 和 website-evidence.json。268 项相关回归通过，目标 Ruff、mypy、前端类型与 ESLint 通过。原 132 组和原包字节保持原样。本次供应商生成和规划使用受控响应，真实生成服务的口型、模型语义及用户画面与听感验收仍待完成。

## SG-S09 原生字体检查耗时

用上一轮整片的 SG-S09 输入定位瓶颈。8 帧性能采样中，200 次字符映射查询累计耗时 36.65 秒，整段采样为 39.47 秒。适配层核对原加载器、组入口和两个共享实现文件的摘要。在 SG-S09 的原生渲染和版面子进程内，按原包字体文件版本和集合内字体索引复用字符映射。缓存最多 12 份，随进程退出清除。外部字体与其他组沿用原路径，源文件摘要不匹配时沿用原检查。原缺字和尺寸校验、帧采样、布局阈值、绘制和编码仍由原引擎执行。

本期 197 帧 RGBA 序列及原生组件 MP4 与同输入的基准逐字节一致，组件 SHA256 为 cc13a9d0c1a3e3d3e9e5a191bfe2028f79afa9ed1f33fbd797749d17d0dd42da。由实际任务文件时间计，组件渲染从约 194 秒降到约 21 秒。独立运行同一份 197 帧原生角色请求，两份完整报告逐字段一致。该对照与其他验证并发时，原路径和优化路径的墙钟时间分别约为 774 秒和 69 秒，见 role-ab-evidence.json。故意加大字体造成三帧真实重叠，优化前后都报告每帧 11258 个碰撞像素。注入缺字时，原生错误相同。回归另核对同一字体集合的不同字体索引、文件更换及外部字体。组件和对照记录位于 C:/tl/motion-layout-performance。

网站任务 d65ed073-6181-4bd7-baed-557b77159814 复用上一轮已冻结的真实口播和编排。新任务的 SG-S09 角色检查区段为 45.10 秒，同机上一轮整片中为 563.94 秒，均按相邻角色检查请求落盘时间计。新 worker 约 11 分 58 秒完成代理和高清。本次整片使用 10 种原生动效、11 次出现、11 条提示音和一条背景乐。统一实例路径后，整份原生版面报告与上一轮一致。原声 WAV 与高清 MP4 摘要相同，代理和高清均返回 HTTP 206。430 像素宽 Chrome 实播并下载同一摘要。高清为 C:/tl/motion-layout-performance/website-layout-optimized-hd.mp4，SHA256 为 3267c33b46a4b3dca58c612fd9dcdba58be46a533ff7a522649de748c4007043。整片和浏览器核对见同目录 film-verified-evidence.json、browser-layout-optimized-playback.json。

269 项相关回归、Ruff 和目标 mypy 通过。复核原库 1426 项摘要及 132 组目录。全库本期组件编码覆盖仍为 127 组。本轮复用了已保存的规划，实际供应商模型选组、画面与听感仍待验收。

## 讲解步骤模板与桌面收纳口播

网站新增「讲解步骤与口播重点」模板版本 explainer-steps-v1。11 个原生文字槽按场景、动作、分类、使用地点和行动提示标明用途，复用已经接入的原生角色和动作合同。模板允许使用不同槽组合及在不同实录位置重复使用同一组。语言模型仍只选择原组与词 ID，网站编译原生字段、音效和背景乐。

取历史已经交付的 authoring-to-lipsync-live.mp4 作为另一段有实际配音与口型的输入，主题为桌面收纳，片长 40.123 秒。将原件上传隔离项目后，实际 FunASR 得到 17 个分句和 201 个词点。历史二创交付稿与本期 ASR 比对，忽略标点后的汉字顺序一致。本期保留实际转录和原词点。受控规划按当前讲解内容选用十种不同动效，办公用品与日常小配件分别绑定实录词组，「不用在桌面上反复翻找」由主字幕与同期原声完整表达。准备和候选保存走网站接口，供应商规划使用受控响应。

独立剪辑 worker 一次完成网站任务 40a2ed35-00b5-4954-981f-aea3e61ccbd1。十种原生动效各出现一次，均抽样核对了实际编码帧及其同期原片。十处人物保护区平均像素绝对误差最大为 1.64/255。原版面报告记载 SG-S10 的 24 帧前景字与背衬叠放，按已登记的原生设计意图分类后，适配报告零未解释碰撞。两份报告均保留。独立解码核对了 1925904 个 48 kHz 立体声采样帧，原片重采样后与口播分轨逐样本相同。十条原库提示音实际起音与各自原生事件一致，背景乐在实录发声区间的均方根电平低于口播 10.65 dB。

Chrome 在 430 像素宽窗口选中模板及本期转录，实播 720×1280 高清，并从网页下载同一摘要。代理和高清均返回 HTTP 206。新试片 C:/tl/second-motion-source/website-desk-explainer-hd.mp4，SHA256 为 1f3e318aed55982d162072e539f5ca1bbd8346d9637f8bf32fa269f9e7fc59cd。证据见同目录 film-verified-evidence.json、sound-levels-evidence.json、browser-explainer-template.json 和 browser-desk-explainer-playback.json。269 项相关回归、Ruff 和目标 mypy 通过，原包 1426 项摘要复核通过。真实供应商选组、用户完整观感及听感仍待验收。此次没有新付费调用。

## 已交付成片进入「我的作品」

「我的作品」新增跨项目的剪辑成片区，可按当前项目名搜索、翻页、播放、下载和返回项目剪辑。生成作品继续在同页单独展示。接口从现有任务与已校验的 final 产物读取当前用户、工作区和项目内的记录。需要代理确认的任务沿用确认记录与最终摘要检查。列表只返回作品信息和现有鉴权媒体地址。分页以任务时间及 ID 排序，兼容同一时间创建的记录，无数据库迁移。

在隔离 SQLite 副本用两条真实试片联调。将桌面收纳原任务回到代理待确认状态，原成片与原数据库仍用于摘要对照。待确认时作品页只有已交付记录，直接读取待确认高清返回 404。Chrome 实播 360×640 代理并点击确认，作品页随后能按项目名找到并播放 40.123 秒桌面收纳高清和 48.475 秒原口播高清。下载桌面收纳文件摘要与原任务一致，Range 返回 206。另在既有独立 PostgreSQL 18.4 测试库对真实剪辑产物核对了项目搜索、游标边界、通配符转义和 64 KiB 范围读取。证据位于 C:/tl/motion-works-delivery 下的 browser-works-delivery.json 和 postgres-works-evidence.json。本轮核对的是成片入库后的交付与播放，复用了已经编码的真实试片。

270 项剪辑、文稿及原库回归、目标 Ruff、mypy、前端类型与 ESLint 通过。测试验证暂存高清不可见、同时间分页稳定以及不同所有者无法读取作品或借用游标。OpenAPI 新增作品列表查询，当前未部署。

另在本机六个相关目录中按原清单字节数及摘要查找四份字体和两份 G10 原图，未得到匹配。检查较早交接 ZIP 的 23 个条目，未发现该批启动素材。记录见 C:/tl/motion-works-delivery/original-resource-search.json。现有 132 组目录与 127 组本期编码覆盖仍保留，缺件组及 B 版原 Aa 研宋保持待补状态。

## 高清校验后的剪辑交付续跑

worker 在高清校验通过后、生成代理之前保存检查点，代理校验后再保存完整交付检查点。检查点绑定本次请求和实际编译的原生 episode、selection、bindings、实录词点及适用的声音和版面意图。重试仍核对原片、原包、编排与素材，再按任务内原路径、角色、字节数、摘要及已保存的技术回执验证已完成产物。代理损坏或缺失时复用有效高清并重建代理。高清或必需回执不一致时重新走原生渲染。未完成高清校验的中断仍走正常渲染，片段级续跑继续待验证。

已完成产物保留在各自尝试的目录，领取重试时仍使用新尝试目录。任务状态与产物行继续在有租约保护的同一事务提交。作品页沿用代理确认边界。检查点使用已有任务 JSON，无数据库迁移。在独立数据库中将既有真实高清及代理置于已过期租约下，实际 worker 约 4.8 秒完成重领及登记，旧尝试标记 superseded。两种媒体重编码调用均为零，代理与确认后高清的范围请求均为 206。该项对照复用历史真实媒体，证据为 C:/tl/motion-delivery-recovery/expired-lease-evidence.json。

另创建新任务 1cc9d8b1-3b31-40ec-a099-6420ec6f582f，按冻结的 40.123 秒桌面收纳口播实际重新编码，使用十种原生动效。首次用时 524.80 秒并完成高清校验，在进入代理编码时注入中断。第二次用时 7.03 秒，读取首轮高清并实际生成、校验代理，随后在写入产物事务时注入失败。数据库未保留半完成的产物行。第三次用时 3.98 秒，沿用首轮高清和第二轮代理完成登记。整次运行只调用一次原生渲染，代理进入编码成功一次。确认前高清仍暂存，确认后作品页恰有一条该任务记录。两版均支持 HTTP 206。

430 像素宽 Chrome 实播恢复后的高清并下载相同摘要。C:/tl/motion-delivery-recovery/website-recovered-desk-explainer-hd.mp4 的 SHA256 为 1f3e318aed55982d162072e539f5ca1bbd8346d9637f8bf32fa269f9e7fc59cd。此试片用于同一编排的续跑验证。两次中断检查点、恢复与浏览器记录在同目录。272 项相关回归、Ruff 和目标 mypy 通过。整体语义、视觉和听感仍待用户验收。

## 原生渲染中断后的片段续跑

网站适配层复用原 exporter 的片段缓存接口。每次尝试仍有独立目录。原入口确认片段编码并完整解码后，额外封存实际请求、原回执、MP4 和透明帧清单的摘要。重试只读同一任务、同一编排及相同原生适配版本的早期尝试，核对原始请求与当前片段请求，逐帧校验透明序列。合格片段复制到本次目录，更新原回执的实例路径和本次请求摘要，交回原入口再次核对。原库源码及早期尝试不参与写入。

当片段缺失、未封存或任一摘要不符时，原入口重新编码该片段。主字幕、原生版面检查、声音合成和整片校验照常运行。此轮覆盖原 episode shots 中带标准解码回执的片段。独立整帧场景流水线、仅提供专用 Build 回执的 Hypit 以及版面中断的逐组续跑仍待扩展。状态记录和封存文件都在尝试目录，无数据库迁移。

基础字幕任务 005b5371-0446-4ae7-bc09-26de64a17867 使用真实桌面收纳口播。在第一段 Z-M00 编码后通过网站取消，再重试。原片片段无透明序列，首段视频摘要匹配并被复用，后两段重新编码，最终成片 Range 206。运行证据在 C:/tl/motion-shot-recovery/base-control/recovery-evidence.json。另有单元对照验证不同片段请求和损坏帧均不能进入复用路径。

动效任务 c855e75a-ecc7-4253-905d-d08105d824e9 使用已冻结的桌面收纳口播及十种原生动效。六段封存后通过网站取消，在隔离测试目录故意改动 BG-S04 一帧。重试复用五段，重做损坏片段和四个未完成片段。复用片段的 MP4 和透明序列清单摘要一致，原回执中的输出路径与新尝试对应。对十段实际编码回执另核验了新加入的整片时钟容差。

版面检查与原库混音重新执行，整片通过解码和原声、字幕、时钟及交付检查。代理与高清均返回 206。430 像素宽 Chrome 实播 40.123 秒试片并下载同一摘要。试片 C:/tl/motion-shot-recovery/website-shot-resumed-hd.mp4，SHA256 为 1f3e318aed55982d162072e539f5ca1bbd8346d9637f8bf32fa269f9e7fc59cd。记录在同目录 recovery-evidence.json、relocated-native-receipts.json、native-shot-clock-check.json 和 browser-shot-resumed-playback.json。本次为续跑验证，使用受控规划并复用该编排，整体观感和听感仍待验收。

加入片段时长检查后，再用真实基础字幕任务 9a3549f6-8a6b-48c5-bcd8-e7d44bf0350d 验证一次取消和重试。新 worker 复用首段 Z-M00，最终三段均封存，输出与此前基础字幕对照摘要相同。证据为 C:/tl/motion-shot-recovery/final-clock-control/recovery-evidence.json。274 项相关回归、Ruff、目标 mypy 及原包 1426 项摘要复核通过。

## 剪辑 worker 运行依赖自检

`python scripts/run_editing_worker.py --check-runtime` 使用当前配置验证任务目录写入、口播媒体目录、原包字节、原生 Python 依赖、FFmpeg 滤镜与交付编码器、无头浏览器画布、离线转录模型及启用时的对齐模型。命令输出独立的 JSON 回执，失败返回 1。它不领取队列任务，不进行转录或原生成片渲染。启用剪辑探测的 API 镜像与 worker 镜像均在切换到 UID 10001 前建立共享任务挂载点。

在 Windows 本机使用原包、实际 FunASR 和 fa-zh 模型、原媒体目录执行自检，七项均通过，原包核验 1426 项并注册 132 组。将口播媒体和 ASR 分别指向不存在的路径后，两项明确失败并返回 1。其他检查仍各自完成。回执位于 C:/tl/motion-container-runtime/windows-runtime-check.json 与同目录 windows-runtime-negative.json。

274 项相关回归、目标 Ruff、mypy 及 Compose 四层配置校验通过。本机 Docker Desktop 初次启动在两个旧通信端点处遇到 Windows 错误 1920。保留两个端点目录的备份后，启动进入 WSL 阶段，仍在创建其内部发行版目录时失败。Docker 数据盘留在原位，Linux 镜像构建与容器内真实出片均待验证。

## 从两份原 ZIP 重建运行目录

两份原 ZIP 的字节数与 SHA256 均匹配交接基线。使用正式安装命令在 C:/tl/clean-motion-install-20261110 从空目录重建。Motion 解包 1428 份文件。作者清单覆盖 1426 份，剩余两份为清单本身与分享说明。运行校验现在也把这两份文件绑定到批准 ZIP 中的实际字节，拒绝自行替换的清单与内容。写稿原包 33 份文件在首次安装及重复安装时均通过原方法身份校验。

重新运行安装和全部 132 组静态审计成功。登记仍有 197 个原包资产和 699 个外部资源引用。安装回执和 all-132-schema-audit.json 位于新目录。针对原包校验与原生批次的四项回归及目标 Ruff、mypy 通过。这些结果只证明原件和入口清单可从原 ZIP 恢复。

## 隔离 Linux 容器联调

Docker Desktop 的 WSL 目录为指向现有 D 盘数据的 junction。用独立 Ubuntu WSL 2 发行版和单独 Unix socket 的 Docker Engine 构建测试镜像，原 Desktop 目录和数据盘留在原位。独立 PostgreSQL 18.4 从空库迁移到 `20261109_0049`，Redis 8.6.4 可用。应用测试网络为内部网络，仅使用本地测试配置。

首次 API 镜像成功构建但无法启动。图卡字形校验提前在 API 路由导入 `fontTools`，该依赖由剪辑 worker 提供。把导入移动到字形校验调用中，保留原校验逻辑。重建后，API 容器实测在没有 `fontTools` 的环境启动，UID 10001 可初始化并读写共享任务卷。容器 API 可读取完整 132 组目录，并接受实际桌面收纳口播，持久任务初始状态为 queued。原生图卡时钟与编译器的 11 项针对性回归通过。原包变更后的整组回归为 275 项通过，回执在 C:/tl/clean-motion-install-20261110/regression.xml。

测试系统使用核对官方 SHA256 的 Ubuntu Base 24.04.5。独立 worker 镜像实际构建完成，容器以 UID 10001 断网自检七项均通过。原 Motion、视频媒体、FunASR、fa-zh 与私有依赖目录均为只读挂载，共享任务卷可写。容器运行的 Python 为 3.12.10，FFmpeg 为 5.1.9，Chromium 为 156.0.8078.4。API 容器另以只读挂载校验写稿原包全部 33 个文件。Compose 合并剪辑、对齐、外部依赖和文稿覆盖文件的静态校验通过。 [Ubuntu Base 发行文件](https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/) [Microsoft WSL 导入文档](https://learn.microsoft.com/en-us/windows/wsl/use-custom-distro)

真实口播由 HTTP API 写入 PostgreSQL，由维护容器经 Redis 投递，独立 Celery worker 领取。基础任务 735b5059-6adc-4b5f-8326-1be1cda1c606 实际 FunASR 识别 201 个词点，177 秒完成。基础字幕片长 40.123 秒，容器 Chromium 实播，范围下载返回 206，高清摘要为 edab712079b91604c04f4ec08f70ba51271c7eafbd6cdffe39c79a77b39f87be。独立对齐任务 b008c28e-0219-4e1b-a766-4537a5e198b9 实际执行 fa-zh，153 秒完成，核对了原声音频、转录版本和 201 个对齐词点。三个成片任务各仅领取一次实际执行；队列长等候期间的重投消息由任务状态拒绝重复执行。

独立规划 worker 以实录词 ID 和完整 132 组目录生成请求，向内部 HTTPS 测试端点提交一次。受控响应沿用同条口播的已核对编排，覆盖十种原生动效。网站将候选冻结并提交渲染，新任务 7fb98bd7-c030-43de-9cc1-3bec5fa17b64 实际重新编译和编码，耗时 1064 秒，主要耗时在原生逐角色版面检查。先交付代理，再通过 API 确认导出。代理与高清均返回 206，确认后的作品接口仅登记一条同摘要成片。高清以 720×1280 在容器 Chromium 实播，片长 40.123 秒。

整片通过完整解码和原生版面检查。十个动效各抽样一帧核对同期人物，包含原生末尾 0.4 秒淡出，人物区像素绝对平均差最大 1.56。口播分轨与独立解码的原音 1,925,904 个单声道样本逐样本一致。十条原库音效均有实际信号，起音与锚点同帧。实际口播区间内，背景乐均方根电平比人声低约 11.35 dB。高清为 D:/codex-motion-runtime-20261110/linux-native-hd.mp4，SHA256 为 4658fd5ce2b75e3937caefbea2f464be030e11c9bd3d2fe42f620db6f2c2cc60。自检、浏览器、编排、声音、作品和对齐回执均在同目录。供应商真实规划、全库缺件组与用户视觉听感仍待验收。

## Linux 原生逐角色版面检查加速

复用 SG-S09 的进程内字体映射缓存，扩展到使用同一原生字体检查代码并经过本次实测的 BG-S06、SG-S02、SG-S03、SG-S06、SG-S10。适配器核对各组原入口、共享代码与原加载器的 SHA256，再给原字体检查安装受限缓存。缓存只复用原包字体映射，按打开的实际文件版本和集合索引区分。原生逐帧缺字、墨迹、透明度、角色碰撞、字幕及保护区检查照常执行。外部字体沿用原检查路径。

用上一轮 Linux 实际版面输入取前八帧对照。SG-S02 的底层字符映射查询从 60 次降到 2 次，整个角色检查从 20.75 秒降至 10.21 秒。BG-S06 从 54 次降到 2 次，检查从 12.69 秒降至 4.78 秒。五组实际完整输入共 468 帧，优化后的原生角色报告与上一轮逐字段一致。SG-S10 原先报告的 24 帧角色叠放仍在原报告中。相关 11 项回归、Ruff 和目标 mypy 通过。对照回执位于 C:/tl/motion-font-optimization-20261110/linux-role-ab.jsonl。

沿用上一轮 40.123 秒口播和已冻结的十动效编排，通过网站创建新任务 ce733eb2-776e-49de-a33c-1cac4caaac71。现有 Linux worker 镜像以只读方式挂载本次两个适配源码文件，Redis 投递并由 worker 一次领取。十段原生检查点均为本次重新编码。PostgreSQL 实际执行时长从 1064 秒降至 548 秒，约缩短 48.5%。以首个角色检查请求至原版面报告落盘计，版面检查从 713.55 秒降至 330.14 秒。计时是两次本机真实运行，现场硬件和存储负载会影响结果。

两次整片的 1053 张透明帧摘要、三条声音分轨和高清文件逐字节一致。统一尝试目录后，原生版面报告逐字段一致。代理和高清范围请求均返回 206，确认后 Chromium 在 430 像素宽窗口实播高清。新下载件 C:/tl/motion-font-optimization-20261110/linux-font-optimized-hd.mp4 的 SHA256 为 4658fd5ce2b75e3937caefbea2f464be030e11c9bd3d2fe42f620db6f2c2cc60。回执为同目录 linux-optimized-delivery.json。这次复渲使用既有受控编排，用于验证同一成片的性能和保真。真实模型选组与用户视觉听感验收仍待完成。

## 纸面规格场景进入网站自动编排

新增组合模板 `package-specs-v1`「纸面规格与口播重点」。12 个可选原生动效包括全幅纸面场景 Z-M12、整帧追问、口播标题、数字与行动提示。沿用至少五种、优先十种、同组可重复的编排合同。Z-M12 用于四项相连且各有对应图片的实录说明。缺图预检按原件 SHA256 去重，排除口播视频。模板要求规划在缺图或实录缺少四项合适说明时跳过该场景，并保留其他可用槽。

自动编译验证四个标签、四个媒体槽、四个入场词点逐项对应，并校验当前口播原片的摘要。圆窗按原生视频字段读取同期原片，源时窗越界时报错。原背景、画幅、包装造型与入场曲线保留，统一主字幕在该场景期间移至底部。沿用原生场景编译和已验证的逐项入场音效。此次调整仅在网站适配层，未修改原 ZIP 或数据库模式。

使用实际洗洁精口播、已验证的 240 个词点和四张已登记的规格示意图。准备请求包含原库 132 组，三张不同图片显示还缺一张，四张符合数量要求。本地受控规划响应进入真实校验和网站候选生成。独立 worker 一次领取并完成新整片任务 `3fb777c7-5e9f-468a-964d-0d93229491d8`，耗时约 161 秒。预览先交付，再由本地验证流程确认高清导出。两个 API 均返回范围请求 206。实片为 48.475 秒，720×1280，H.264 和双声道 AAC，包含 11 种原生动效、14 条原库音效和一条背景音乐。

原生版面、原始时钟、混音及完整解码均通过。抽样六帧的圆窗像素对照与同期源画面匹配。四张用途图按各自实录标签入场，原音效分别在第 300、357、469、546 帧起音。图像保留原动画的渐进显现，2 至 3 帧后清晰可见。独立解码的原声和口播分轨比对误差约为 −143.34 dBFS。实录发声区间内，背景乐均方根电平比口播低约 10.43 dB。

Chrome 实测模板可选，零张图时准备页显示还缺四张。430 像素宽窗口将高清从 15.6 秒播放至 16.77 秒，并通过页面下载同一摘要。高清试片在 C:/tl/package-automatic-20261110/website-automatic-package-hd.mp4，SHA256 为 e991c523f42bbd110f77ab5457dd06a445578ae0b66ab9faf291facdafab4414。准备、交付、媒体和浏览器验证分别记录在同目录的 prepared-request.json、delivery-evidence.json、media-evidence.json 和 browser-package-evidence.json。277 项相关回归、目标 Ruff、mypy 和差异检查通过。未提交外部模型或生图任务。真实模型对新口播的选组和配图语义，以及用户对成片的整体观感、听感仍待验收。

## 线描经历与纸面规格自动组合

新增 `line-story-v1`「线描经历与纸面规格」。13 个可选动效沿用纸面规格模板的原生槽，并增加 W-R11。准备页按角色列出可选的本期过渡图、透明线描和六列四行的 RGBA 手势帧图。帧图的 24 格须各有透明区域和可见画面，序列须有可见变化。只有透明区的 RGB 值变化无法通过预检。帧预检与 worker 拆帧共用同一验证，实际渲染仍逐项绑定任务内 PNG 的摘要。原件和合法派生帧复核一致。

规划使用实录文字、三份素材 ID 和实际词点。编译校验同期人物原片摘要、三个互异的图片、线描标签与手势入场的实录首词、四个有序回切点。保留原线描纸面、原笔刷、原人物缩放回切。主字幕由网站统一绘制，在线描及规格场景使用底部通道。手势入场接入原库短音效，原声和背景音乐贯穿场景切换。已存组合模板版本及原包未改动，无数据库迁移。

用真实洗洁精口播的 240 个实录词点和七张本期项目素材重新准备。刻意少选手势帧图时，准备回执将该角色列为空。选齐后使用一次本地受控规划响应生成网站原生候选。独立 worker 一次完成新任务 `3ca482be-2e1e-48ff-9fa1-6e93c3b15279`，耗时约 186 秒。高清 48.475 秒，720×1280，H.264 和双声道 AAC，含 11 种原生动效、14 条原库音效和一条背景音乐。预览和高清的范围请求均返回 HTTP 206。

原生版面和完整解码通过。线描手势在第 175 帧未出画，第 176 帧出现，提示音从 5.870 秒起声，落在同一帧。回切后抽样四帧对照同期人物。纸面规格圆窗另抽样六帧，四张图及各自音效继续按实录词点进入。口播分轨与独立解码原音的误差约为 −143.34 dBFS，发声期间背景乐均方根电平比口播低约 10.43 dB。Chrome 选择新模板并看到缺素材提示，430 像素宽实播高清 5.6 至 6.76 秒，从页面下载的 SHA256 与交付文件一致。

高清试片 C:/tl/line-auto-20261110/website-automatic-line-hd.mp4，SHA256 为 4fb3f75ddee4fc5beda996db4edf2c85f017f315b451374b8485fa1bdbbf4635。准备、交付、媒体及浏览器回执均在同目录。278 项相关回归、Ruff、目标 mypy、前端类型检查、目标 ESLint、差异检查及原包完整性复核通过。外部模型选组和生图供应商均未调用，整片观感和听感仍待用户验收。

## 原生字效叙事模板

新模板 `subtitle-story-v1` 增加 AH-S02、AH-S08、AHG-S04、AHG-S05、BG-S02、BG-S03、BG-S05、JJ-S02、JJ-S04、JJ-S05 十个可自动编排的原字幕组，与已接入的十二组组成 22 个候选槽。继续使用原组模板、原生字号和轨迹、实录文字字段和事件时钟。编译器按各组入场事件绑定原库短音效，保留连续原片、主字幕、低位背景乐和同组重复规则。原有模板版本、数据库模式和原包均保持原样。

对原有 37 组本期组件送入原生分角色字层检查。旧组件本批有 36 组返回，20 组未报告字层交叠，16 组保留交叠记录。旧 SG-S09 输入在 480 秒限时内未返回，后续以本次实际整片的新 SG-S09 输入通过版面检查。十个新增槽的原组件样本均通过这项检查。组件能编码只记录技术证据，实际文字、时钟与画面仍随本期出片核验。本批逐组回执在 C:/tl/subtitle-auto-20261110/original-role-screen-v2.jsonl。

首轮整片 `75b9cc44-b76d-40a2-870f-18fc1ee3152d` 完成十二个组件编码，原生整片版面检查拦下 20 个字层碰撞。JJ-S02 在前后景交接中有 3 帧相碰。编译器要求后景退定的词点不晚于前景起点，验证用的新词点取同一句中靠前的实录。BG-S03 有 17 帧的小面积交叠，来自两层字的阴影。在自动模板中关闭这一组的阴影，保留原字形、字号和轨迹。两组修正后分别通过 137 帧和 120 帧的原生分层检查，未增加版面豁免。首轮失败的任务和原始报告保留。

使用相同的实际洗洁精口播和 240 个实录词点重新准备。网站冻结含 132 组目录的请求，通过本地受控响应采用本期候选。独立 worker 一次完成新任务 `91d5eaf0-d01a-4c0e-9899-1e62ea7686f5`，约 201 秒。本轮出片实际包含十个新增组以及 SG-S09、AH-S09。原生版面核对了 1315 帧，零碰撞。完整解码通过，48.475 秒、720×1280，H.264 和双声道 AAC。Chrome 实际选择模板，确认该请求可独立准备，430 像素宽窗口实播并下载同一摘要。代理与高清支持范围请求 206。

十二个动效段各抽一帧核对同期人物，脸部区域像素绝对平均差最大 2.59。音效共十二条，均有实测信号，绑定各组入场词点。对 30 fps 的原生透明帧以 alpha 大于 96 且像素数大于 100 检测明显字效，提示音领先约 0.1 至 2.7 帧，含原生渐进显现。口播分轨与独立解码原声误差约 −143.34 dBFS，发声区间背景乐比人声低约 10.43 dB。40.5 秒抽帧中的白、金字在浅色衣服上的对比偏低，像素碰撞检查无法覆盖此项观感。

高清文件 C:/tl/subtitle-auto-20261110/website-automatic-subtitle-hd.mp4，SHA256 为 823c1431a2287fbbfc8c34fd487ff7d91f407c356bdaee30efa262b5a67ced44。准备、交付、媒体及浏览器回执在同目录。278 项相关回归通过，修订后针对性回归 94 项通过，Ruff、目标 mypy、差异检查及原包完整性复核通过。未调用外部付费服务，供应商真实模型选组、用户整体观感和听感仍待验收。

## 原生透明字效入场的混音校准

为 `subtitle-story-v1` 的透明字幕入场音效增加 `rgba-threshold-v1` 时钟。保存的词点和原编译 episode 仍是可核对的输入。原生版面通过后，适配器验证原合成、布局、混音入口摘要及镜头 RGBA 序列。按 30 fps 的原合成时间基准和画面启用条件读取首个有效帧，阈值沿用本期验收用的 alpha 大于 96 且可见像素数大于 100。最多向词点后检查六帧，缺失或变更的原生证据阻止交付。原生 FX 渲染仍负责测量有效起音和混音。

已经出画的文字若有后续强调音，仍按原生强调事件播放。已用实片的 AHG-S02 核对，文字在本地第 1 帧可见，原强调词点是第 33 帧，提示音应留在后者。交付验证重新读取同一透明帧并核对音效起音，声音回执记录词点、实际入场帧及该帧摘要。该策略只绑定本模板的常规透明字幕入场，独立图卡、整帧场景和其他模板沿用各自既有时钟。

用原 48.475 秒真实口播、240 个冻结词点及同一份本地受控编排创建新任务 `f0b5749f-1ecf-4b8c-abb1-d11fc7afb16b`。独立 worker 约 185 秒内实际重新渲染并交付。12 个透明字效及 1315 帧原生版面检查通过。十二条提示音的有效起音均落在首个达到阈值的视频帧，原生声音回执及独立 PCM 对照都测得 0 样本差。上一版领先最多 90 毫秒的 JJ-S02 和 AHG-S05 分别校准到第 829 帧和第 1064 帧。对照验证两版视频流、口播分轨和背景乐摘要一致。

Chrome 选取模板并准备请求，430 像素宽窗口实播高清，下载摘要一致。代理与高清均返回 HTTP 206。试片 C:/tl/subtitle-sound-20261110/website-synced-subtitle-hd.mp4，SHA256 为 3b6f540382455fc5d55d78b2051e8731992a0280caef9110ce4f0cfa01fb1e45。同目录保留交付、声音对齐和浏览器回执。280 项相关回归、目标 Ruff、mypy 及差异检查通过。本次无外部付费调用或迁移，画面观感和实际听感仍待用户验收。

## BG-S03 薄描边及原生排版预检

「原生字效叙事」模板为 BG-S03 保留原字号、白金字色、位置和动作。编译 worker 用本期文字和实际词点调用经摘要确认的原生分角色检查，依次检查双行 1 像素深描边、仅对白字描边、无描边。选择第一项零碰撞配置写入正式编译回执。候选与正式 job 放在各自实例目录，整片仍执行原生版面检查和可见帧音效校准。原生检查仅处理文字图层，不需要视觉模型或上传口播画面。探测样本中，双行 2–4 像素描边引入字层接触，未采用。

第一轮桌面收纳尝试在选出单行描边后触发原编译器的实例不可覆写保护。修正为独立试排目录后重新提交，初轮失败任务及预检回执保留。洗洁精实际口播的试排 120 帧无碰撞，选择双行描边。桌面收纳实际口播的长标签试排 141 帧，双行描边 67 帧碰撞，仅对白字描边零碰撞，自动采用后者。桌面试片仍保留原 SG-S10 已登记的 24 帧设计叠字，BG-S03 无该类豁免。

本地受控规划生成两条新整片。洗洁精任务 `caba73ce-1c39-4882-a038-5c95fb5d8163` 为 48.475 秒，含 12 种动效。桌面收纳任务 `5c761c24-de99-4de3-ade9-da0f479a0962` 为 40.123 秒，含 10 种动效。两个任务的代理及高清均支持 HTTP 206，430 像素宽 Chrome 实播分别至约 40.96 秒、9.37 秒，两次浏览器下载都与网站交付摘要一致。两段 BG-S03 的音效在可见阈值帧起音，分别为第 1195 帧、第 215 帧。洗洁精口播分轨和背景音乐与上一版摘要一致。

按 360 像素宽手机画幅，对洗洁精片约 40.5 秒的三个抽样帧测量。新深色字边与同期底片的局部明度对比中位数从约 1.07–1.09 提至约 1.93–2.01，测量范围为实际发生改变的字边区域。该检测不判定主观可读性。成片及数据在 C:/tl/subtitle-contrast-final-20261110 和 C:/tl/subtitle-contrast-desk-20261110。两条高清摘要分别为 3854e91fcb2e8d0101f86eb170250128e068986d08129fb1e6ed0b05f1304cc1 和 e05e17fbceeed0e582e761d72d8460ec4813d1aaaa98fed7496434872b675955。280 项相关回归、Ruff、目标 mypy、差异检查及原包完整性复核通过。真实模型的选组和用户观感、听感仍待验收。

## 已校验规划直达代理预览

「语义规划任务」中已完成合同校验的组合模板新增「按本次规划生成代理预览」。API 同一次请求复用保存的语义结果、模板、原片和逐词版本，通过既有来源验证和原生任务准入保存编排与剪辑任务。按规划 ID 生成稳定请求标识，双击、重复提交或页面刷新后仍关联同一预览。规划关联与剪辑任务同事务提交，独立 worker 按既有队列消费。用户仍可选择先保存编排，再调整重点、素材和音乐。高清继续由同一代理预览确认后开放。

新入口读取已经保存并校验的模型响应，不发起配音、识别、对齐或模型请求。付费语义规划仍需使用原有带费用提示的单独操作。未完成的规划、不同项目的原片和不满足原生组合合同的候选不能通过。已有规划及任务使用原有数据库列，无迁移。

同步复核原 ZIP 安装和累计原生运行台账。132 组完整登记，116 组有成功样本，11 组同时有成功与失败样本，5 组暂无实际编码。现有 12 个网站组合模板共覆盖 33 个不同原生槽，其他有编码证据的组仍按其实际组件能力登记。CX-G05、CX-G08–10、HY-A1 保留原件或授权待补记录。本轮当前清单为 C:/tl/preview-handoff-20261110/current-original-coverage.json。

本机用洗洁精原口播、240 个实录词点及一个已保存的受控规划响应走网站入口。Chrome 一次点击创建任务 `fef9eb5b-fc40-451c-9b65-294822d71d71`，重放请求返回同一任务。独立 worker 重新渲染了 12 个原生字效镜头，完整解码通过，含 12 条入场提示音和一条低位背景乐。编排沿用冻结的实录和规划，出片 worker 的识别、对齐及模型调用计数均为 0。

430 像素宽 Chrome 实播 360×640 代理，确认前 API 只交付代理。确认后实播并下载 720×1280 高清，片长 48.475 秒，两版范围请求均返回 HTTP 206。另在浏览器模拟列表窗口没有返回该任务，确认可以通过规划记录只读找回它，后续刷新仍能播放，未产生新任务。下载路径 C:/tl/preview-handoff-20261110/website-single-step-preview-hd.mp4，摘要为 3854e91fcb2e8d0101f86eb170250128e068986d08129fb1e6ed0b05f1304cc1。该次新渲染与相同输入的前版成片字节一致。浏览器回执为同目录的 browser-preview-evidence.json 和 browser-linked-history.json。

281 项相关回归、目标 Ruff、mypy、前端类型和 ESLint 通过。本次未发起外部付费规划或生图。真实供应商的语义选组和配图、用户视觉和听感仍待验收。

## 编号标签用三张用途图自动出片

新组合模板 `numbered-pictures-v1` 提供原 CX-G03 编号标签和 11 种可配套的原字幕动效。模板需要三个同段实录条目及三份不同的本期图片。准备规划时显示图片缺口，无图时保留同模板的其他候选。每项分别绑定原 `label`、`spoken`、`image` 和标签首词 `at`。编译拒绝使用重复字节、错位词点或静态人物代替本期原片。页面可按本次编号标签替换单张项目图片。

保持原编号、卡片配色、相对位置和进场曲线。网站导出只取原生透明编号层，原合成器用连续原视频和原声承载。首轮抽帧发现原字号与卡片图片都可能截断标签右侧。对该模板限定两个实录字，沿用原字体和高度，把字绘制在原剪裁区内。素材有越入字区时，按比例缩放到卡片右侧并保留原底边。主字幕下移至独立阅读区。原生版面检查直接读同一套 RGBA 和实际主字幕墨迹，检查与主字幕及人物保护区是否相交。该适配由新模板启用，原包字节完整性复核通过。

用已识别并对齐的桌面收纳口播和 201 个实录词点生成新试片。三张本地示意图分别表达办公用品、配件和随手小物。零张图时页面显示需补三张。补图后的受控语义响应经网站一键入口提交，独立 worker 约 181 秒完成任务 `21878bb5-9186-4e8f-bb12-427c07719160`，含 10 种原生动效、12 条提示音及一条背景乐。编号段为 6.87–11.79 秒，148 帧原生透明层通过版面检查。原 SG-S10 的 24 帧设计叠字保留单独记录。五处同期脸部抽帧误差最大 2.62，口播分轨与原声对照差约 −143 dBFS。三条编号提示音均在对应首个可见帧前 17–25 毫秒，低于一帧。背景乐在发声区间比口播低约 10.65 dB。

网页实播并下载了 40.123 秒、720×1280 的高清，代理及高清均返回 HTTP 206。浏览器核对了三个可单独更换的图槽。高清文件 C:/tl/numbered-final-20261110/website-numbered-labels-hd.mp4，SHA256 为 6f0c5160ad9f788a478eee27e8d71eee85ec96f637a9c85ce30f09c123a0844b。媒体、交付及浏览器回执在同目录。旧 CX-G07 透明三图卡用同输入重新编码 120 帧，摘要与原输出一致。网站现有 13 套组合模板、34 个不同原生槽。此轮没有新增付费规划或生图，真实模型的选组及用户观感、听感仍待验收。

237 项相关回归、目标 Ruff、mypy 和差异检查通过。本轮没有数据库迁移。

## Hypit 原斜切标签进入网站自动编排

「斜切标签与口播重点」新增 HY-A5 原生槽。每次使用必须对应三个实录短词，分别绑定首词、原生标签文字及当期原片。按原入口要求验证先后关系和末项读时。同一动效可在不同段重复，分别生成原生任务参数、活动画面取帧窗口和原库提示音。原生斜切、擦入、字形和字号由原 Hypit 引擎绘制，网站使用已存在的同期活动底板适配，主字幕独立排在下方。

准备和提交规划前均检查本机已登记的 Hypit CLI 字节、版本、浏览器及工作区权限，并要求源片无内嵌字幕。条件不足时在原模板请求中标记该槽不可选，其余已支持槽可继续参与规划。联调验证了无权限时的准备状态、准备后运行条件失效时的付费提交拦截，以及恢复配置后重试同一任务。拦截时供应商调用计数为 0，证据见 C:/tl/hypit-automatic-20261110/runtime-gate-evidence.json。

用洗洁精真实口播的 240 个已对齐词点和本地受控规划响应，经浏览器一键提交剪辑任务 `10d5d788-b9bc-491d-a0b0-fc9fc7542147`。独立 worker 一次完成。全片 48.475 秒，含 10 种动效共 11 次、15 条提示音和一条低位背景乐。HY-A5 在 8.65–12.43 秒显示「看看／下面／链接」，在 39.11–43.11 秒显示「洗碗／刷锅／洗水果」。两处使用独立的同期底板与原生渲染实例，分别完整解码 114 帧和 120 帧。两段八处人脸抽样与同期底板的平均像素差均低于 2.39。整片原生版面检查无碰撞。

六条提示音有效起声分别落在成片第 264、275、289、1194、1206、1224 帧，对应区域均在该帧出现首批蓝色标签像素。原声分轨与独立解码原声之差约 −143.34 dBFS，实录词区间背景乐比人声低约 10.43 dB。Chrome 实播 360×640 代理，点击确认后实播并下载 720×1280 高清。两版均支持 HTTP 206，下载摘要为 256df98668369cf3da67e10b47d4d718de988514f032565aebee6fe464c5e139。成片在 C:/tl/hypit-automatic-20261110/website-live-strip-hd.mp4，浏览器、声音和画面回执在同目录。

237 项相关回归和新增的运行条件专项测试通过。Ruff、目标 mypy、前端类型、ESLint、原库字节完整性及差异检查通过。网站已有 14 套组合模板，覆盖 35 个不同原生组。本轮无数据库迁移及外部付费调用。Hypit 自动编排继续限本机授权工作区，真实模型选组与用户视听验收待完成。

## 跨页批量提取对标原文

「找对标」支持跨页勾选最多 10 个作品，并显示已加载去重作品数、可识别作者数、作者缺失数及单一作者的最高样本数。明确点击付费提交后，服务端从同一项目已完成的搜索页核对作品 ID 和规范链接，再将每条作品登记为独立语音提取任务。登记按项目与作品固定请求标识，重放、跨页再选和同时提交沿用已存在的任务。每条的提交结果、已返回的供应商任务 ID、失败和可恢复状态沿用现有提取机制。

成功条目可单独保存为独立参考原文。原文正文采用该任务的语音转写，写稿文档保存提取任务关联，来源记录作品 ID、搜索页、采集时间与规范链接。刷新后仍可从文稿流程选择对应原文进行拆解。项目编辑正文和确认版本沿用既有版本机制。作品描述和公开互动只在搜索结果中显示，拆解的画面及互动证据仍标为未提供。

在本机 Chrome 和独立数据库中用封闭供应商传输跑通两页三条。第一条经原异步任务查询返回转写，第二条返回空转写并保留独立失败，第三条直接返回转写。两条成功结果均保存为不同参考文档，刷新后可在「拆解与事实写稿」分别选中。重放整批返回原任务，提取提交总数为 3，项目正文、确认版本和项目引用列表与初始状态一致。证据见 C:/tl/benchmark-batch-20261110/browser-evidence.json 及同目录截图。本轮使用本地受控响应，实际供应商搜索、语音提取、跨账号语义归纳和账单仍待验证。

279 项相关回归通过，覆盖错误来源、其他项目的作品、重复勾选、空转写、保存原文及幂等重放。Ruff、目标 mypy、前端类型、ESLint、OpenAPI 生成、原写稿包 33 项完整性及差异检查通过。本轮没有数据库迁移或外部付费请求。

## 五组原生字效进入双层字幕接力

「双层字幕接力」使用独立模板版本 `subtitle-relay-v1`，包含 AH-S04 折叠标题、AHG-S01 下划线接力、JJ-S06 同位换字、BG-S07 白金接力、BG-S08 大标题与下方说明五个新增槽。复用原生动作、绑定及透明输出，候选总数为 27。文字入场事件须锚定对应短语的首个实录词。编排读取原合同的角色长度，并继续检查原生定长字段。

第一轮实际渲染因 AHG-S01 前句超过原生四字上限被拒，回执保存在 C:/tl/subtitle-relay-20261110。网站编排现在提前拦截同一输入，修订试片使用实录中的「消耗品」。AH-S04 的红字在网站模板内采用 56 像素，AHG-S01 前句采用 80 像素，这两个适配关闭字层阴影。原字形、轨迹与色彩继续由原入口绘制，原生分层检查在本期词组上排除了碰撞。JJ-S06 保留原设计的短暂交叠，允许范围限于原版入口、两层指定文字和最多十二帧的实录交接。主字幕、保护区和其他字层的碰撞继续使用原检查。

首轮通过版面检查的成片在手机画幅抽看时，BG-S08 的说明偏小。将下排原生字体参数由 62 提至 84 像素，并加 2 像素深描边，沿用原金色字与上下位置。相同实录文字和落定帧的透明字形高度由 56 提至 76 像素，按 360 像素宽画幅换算约为 13.5 至 18.3 像素。原包的入口和字体摘要复核通过。

用 240 个实际对齐词点、洗洁精原片和本地受控规划，经浏览器一键提交任务 `7da49ed1-3045-469d-9e31-bea30bbd91b5`。独立 worker 生成 48.475 秒整片，含 12 种不同动效、12 条提示音和一条背景乐。1315 帧原生版面检查中，只记录 JJ-S06 在 11.95 秒的 1 帧原设计交叠。五个新增槽的入场提示音分别在成片第 14、303、703、840、1309 帧与对应首个可见帧对齐。与字号调整前一轮对照，口播、音效和背景乐三条分轨摘要相同。发声期间背景乐比人声低约 10.43 dB。

Chrome 实播 360×640 代理并确认高清，随后实播和下载 720×1280 成片。两版均支持 HTTP 206。高清为 C:/tl/subtitle-relay-readable-20261110/website-subtitle-relay-hd.mp4，SHA256 为 081dfe94e214c7b7d406e12b7333dfec22b8f44b70b5fe2697804681b55b24a1。浏览器、媒体、字号及回归回执均在同目录。280 项相关回归、Ruff、目标 mypy、原库完整性及差异检查通过。网站现有 15 套模板，覆盖 40 个不同原生组。本轮没有数据库迁移或新增付费调用，真实模型选组和用户视听验收待完成。

## 同项目批量剪辑预览

阶段 5 的「语义规划任务」可勾选 2 至 5 条尚未生成代理的模板规划。批量接口先核对工作区、项目、用户及全部规划 ID，再逐条走原生候选与剪辑提交。各条保留原片、实录转录、模板及编排版本。规划编号派生同一个单条预览请求标识，重复提交整批或切回单条时沿用同一剪辑任务。每条单独入库并关联规划，候选未就绪等业务错误按条显示，已经入库的条目可继续完成。剪辑 worker 仍独立领取任务，代理就绪后逐条确认高清。批量入口复用现有数据库记录与导出权限。

本机 Chrome 一次勾选并提交清洁用品与桌面收纳两段实录。两条任务 `f1dd903c-d787-418b-bb5e-3d1cfb93f504`、`565881de-aaae-4b80-8d81-1b30c0359117` 通过 Redis 和独立 Celery worker 各一次完成。整批和单条重放均返回原任务。把一条只完成准备的规划插在批次中间时，两条有效任务仍可读取，准备项单独返回未就绪。刷新后两条规划仍关联各自的代理。浏览器验证了选一条不可提交、选五条后不可再加、取消勾选后可再选。两条代理和高清均以 HTTP 206 实播，确认第一条后第二条仍待确认，两次下载分别匹配服务端摘要。

清洁用品试片 48.475 秒，12 种原生动效和 12 条入场音效。桌面收纳试片 40.123 秒，10 种原生动效和 10 条入场音效。两条各有一条原库背景乐，原声分轨与各自实录的波形差低于 -143 dBFS，音效逐项核对至各自首个可见帧。下载位于 C:/tl/batch-preview-20261110/website-batch-product-hd.mp4 与 C:/tl/batch-preview-20261110/website-batch-desk-hd.mp4。两条均是本次重新渲染的回归试片，沿用既有实录对齐与本地受控规划，成片摘要与各自之前的同配方输出相同。浏览器、选择上限、原生媒体及回归回执见同目录。

281 项相关回归、Ruff、目标 mypy、前端类型和 ESLint、OpenAPI 生成及原包 1426 项完整性通过。本轮没有数据库迁移、外部付费请求或部署。真实规划模型的语义及用户对整片画面和听感的验收仍待完成。

## 八组原生字幕进入关键词递进模板

新增「关键词递进」模板 `subtitle-progress-v1`。继承双层字幕接力的 27 个槽，并增加 AH-S01、SG-S01、SG-S04、SG-S07、JJ-S07、JJ-S08、JJ-S09、BG-S01 八个原生槽。文字取实录词段，各组入场、合并、换位或缩放的事件只接收实录词 ID 与起止边界。JJ-S08 和 JJ-S09 保留原引擎的双行同时入场，后句首词触发换位或第二段缩放。音效继续从原库取样，由实际透明帧判定入场。

首轮受控响应的留白关系值不符合合同，规划 worker 拒绝了该响应。修订后完成原生镜头编码，首轮整片 `48d7c481-a62a-4074-a17d-ae5307091782` 因内部字层碰撞被拦截，原生回执在 C:/tl/subtitle-progress-20261110。主字幕、安全区域和人物保护区未报告碰撞。根据原实现及实际分层帧，适配层只允许指定角色在原折叠、移位、换位、淡化或边缘接触的窗口叠放，主字幕和保护区继续使用原检查。同一帧发生多个角色碰撞时逐个对账，任何未列入许可的重叠仍会拒绝导出。

SG-S01、JJ-S07 和 JJ-S09 使用网站模板字号并关闭字层阴影，保留原字体、轨迹和层次。SG-S01 分身落定后，仅允许指定两层在原生坐标中至多 64 像素的字缘接触。SG-S01、SG-S04、SG-S07 复用已经按原代码摘要限制的本机字体覆盖缓存，原字体文件、字体绘制及原库入口继续由原引擎读取。

修订版用洗洁精实录、240 个词级锚点及本地受控规划，从网页提交任务 `9965864f-9a8b-4ea9-aa1a-65f3009f8010`。独立 worker 一次完成 48.475 秒整片，含 12 种原生动效、12 条入场提示音及一条原库背景乐。原生版面检查覆盖 1274 帧，保留七组的原设计叠放及经边缘限制的接触，最终回执无未通过项。抽看八个新增槽各一帧，画面均对应同期原片。原声分轨与实录的波形差为 -143.34 dBFS，背景乐在有词区间比人声低 10.43 dB。提示音逐项核对到对应首个可见帧。

Chrome 实播 360×640 代理，经确认后实播并下载 720×1280 高清，两种媒体均支持 HTTP 206。高清位于 C:/tl/subtitle-progress-layout-20261110/website-subtitle-progress-hd.mp4，SHA256 为 f8e68d93e4019c52a96113dc427f81fe84cee148652197b487237574f953185b。原生回执、八组抽帧与浏览器证据均在同目录。网站现有 16 套组合模板，合计覆盖 48 个不同原生组。本轮使用本地受控响应，无新增付费请求、数据库迁移或部署。真实模型语义和用户整片视听验收仍待完成。

283 项相关回归、Ruff、目标 mypy、差异检查及原包 1426 项完整性通过。

## 六组原生字幕进入原字形前景重点模板

新增「原字形前景重点」模板 `subtitle-foreground-v1`，在关键词递进模板上接入 AH-S06、SG-S05、SG-S08、BG-S09、BG-S10、BG-S11。AH-S06 的英文字母必须取自实录，字形溶落使用原有的中心字、英文和两侧单字槽。SG-S05 的同一句保留三款原字体，轮换和金字入场均按本期词点执行。SG-S08 与三组 BG 保留原先的前景及退灰背衬，版面检查只允许已核对原入口的指定角色在相应原生阶段叠放。

AH-S06、SG-S05、BG-S10、BG-S11 只接受与原输入对应的字体 ID。规划准备标出缺少原件的组，执行前重新核对，实际编译再次按原资源大小与摘要验证。字体路径保留在私有绑定，规划与模板只接收资源 ID。SG-S05 的已验证原字体可在当前原生子进程复用字形覆盖表。原文件、字体绘制及 renderer 入口保持原样。

当前洗洁精实录没有四位年份词。AH-S07 继续保留原库条目与既有原生组件验证，网站自动模板留待取得适配口播后验证。

用 240 个词级实录锚点及本地受控规划，经网页提交任务 `5d1db47e-8040-4031-b1b3-9dc7a270fceb`。独立 worker 一次完成 48.475 秒整片。13 种原生动效、13 条入场提示音和一条原库背景乐都经过实际编码。原生版面检查覆盖 1315 帧，指定角色的叠放按组记录。抽查六个新增槽的同期人物画面，并分别查看 SG-S05 三种字体阶段。原声分轨与实录的波形差为 -143.34 dBFS，词覆盖区间的背景乐比人声低 10.43 dB，提示音分别核对至对应首个可见帧。

Chrome 实播 360×640 代理、确认并下载 720×1280 高清，两种媒体均支持 HTTP 206。文件为 C:/tl/subtitle-foreground-20261110/website-subtitle-foreground-hd.mp4，SHA256 为 d6ae9f38ad78418e8dbdc505b1ba9138532803456dab580f3cbb211525d0b776。浏览器、原生分层、媒体及依赖回执见同目录。网站现有 17 套组合模板，覆盖 54 个不同原生组。本轮使用受控规划，无新增付费请求、数据库迁移或部署。真实模型选组及用户整片视听验收仍待完成。

原库 43 个字幕组中已有 42 个进入自动模板。最终 285 项相关回归通过，覆盖既有编排省略字体字段、原件在准备后变化、原生字层交接及字体缓存。最新编译器用冻结的实际候选重算配方，结果与成片任务一致。同步确认同词点轮换两种字体、把汉字绑定英文槽均被拒绝。Ruff、目标 mypy、差异检查及原包 1426 项完整性通过。

## 六组月云川人物开场自动编排

「月云川人物开场」模板接入 YYO01、YYO02、YYO03、YYO04、YYO05、YYO07 六组原生整帧构图，同时提供 22 个原生字幕槽。使用当前实录原片和已核对的原黑体及 U2Net，人物取帧由已有的原生时钟配置锁定。固定动画用实录首词与原生帧窗核对，原入口可调的标题、问句和收定事件沿用词级绑定。YYO07 原绘制入口只显示问号，问句槽为原生入场提供词点。YYO06、YYO08 仍保留原组件记录，其余固定文字动作待单独适配。

剪辑准备阶段为内嵌字幕或字幕状态未知的原片标记这六组不可用。对于通过准备的编排，独立 worker 使用原生整帧构图和连续原声音轨。主字幕基线在开场段移至底部，通过原引擎生成的 libass 墨迹核对每条字幕的实际位置。开场提示音使用已按摘要核对的原合成规则，锚定开场层实际启用的第一个成片帧。透明字幕槽继续使用已有的原生可见帧音效校准。

桌面收纳口播用 201 个实录词点和受控规划，由 Chrome 提交剪辑任务 `877e7a7e-4ed3-4442-8115-698068b266b9`。首轮完成六组画面、四组字幕、整片合成和媒体校验。旧交付门槛仅统计透明字幕，导致任务在交付代理前被拒绝。门槛现按原生编码和版面回执统计可见的不同组，透明字幕仍需通过可见性检查，背景底板和没有可见证据的透明层不计入。在 Chrome 中从原网页任务点击重试后，worker 按摘要复用十个原生镜头，生成代理并开放确认。Chrome 实播 360×640 代理与 720×1280 高清，确认后从页面下载，两个版本均支持 HTTP 206。

高清成片时长 40.123 秒，含 10 种动效、10 条首帧提示音及一条原库背景乐。六组原生画面的逐帧摘要均有变化，合成首帧与各自原生输出相符。六处主字幕的墨迹与原生文字区相距 22 至 70 像素。抽看六组不同构图，原生标题和小字的设计性叠放保留。原声分轨与原片的波形差为 -143.34 dBFS，实录词区间的背景乐比人声低 10.65 dB。文件为 C:/tl/yy-opening-automatic-20261110/website-yy-openings-hd.mp4，SHA256 为 a1c34ffc605e5661663c4960d943aa00407b6d36bbd12c1fa97d849f968a597b。编排、浏览器与媒体回执和六组抽帧均在同目录。

网站现有 18 套组合模板，可自动编排 60 个不同原生组。287 项相关回归、Ruff、目标 mypy、差异检查及原包 1426 项完整性复核通过。另用本期实录确认编译器拒绝错过原生固定窗口的词点。本次未发起外部付费调用或部署。真实模型对新实录的选组语义和用户整片观感、听感仍待验收。

## 月云川竖字、推近切词和数量圆窗

网站可选的月云川人物开场升级为 `yy-presenter-openings-v2`，新增 YYO06、YYO08、YY6O04 三组，冻结的 v1 继续按原槽位读取。YYO06 的主题和大字分别限定为原入口的三字和两字，校验各自的固定入场窗口。其 `title_in` 实际触发说明字，问号沿用原设计。YYO08 上方标题用实录首词，须在原生推近前进场并在第 35 帧前留出读时。下方短语只接受固定 30 至 40 帧窗内的实录首词。YY6O04 的数量和单位取相邻实录词，分开绑定单瓶规格与到手总量。矩形、圆窗、数字和说明各用实录词点，原圆窗裁切、字体及动作沿用原入口。

原片和原声继续使用同一时钟。YYO08 和 YY6O04 的原生局部第 0 帧仍从同期原画开始，提示音分别对准上方标题开始淡入和矩形开始收缩的输出帧。主字幕仍经原生 libass 墨迹检查。工程候选的第一轮因缺少数量对照关系映射被编译拒绝，第二轮在原引擎检出 YYO06 的四字主题超限。重新冻结候选时补齐两项关系及各自原词，三字容量也提前进入模板绑定与编译检查。

用 240 个实录词点及受控规划从 Chrome 提交最终任务 `4dafa617-1274-41c4-8928-55f3e08e1748`。独立 worker 完成 48.475 秒的整片。三组整帧与七组字幕共 10 种原生动效，全部实际编码和解码。原合成器将正数偏移截断到帧时基，另按起点启用画面层。独立解码发现旧算式会让两处提示音各晚一帧。校正后 YYO08、YYO06、YY6O04 的声音分别落在零基成片第 68、260、417 帧。重新出片前后的 1454 帧解码摘要相同。七组字幕中，六条提示音核对到首个可见帧，AHG-S02 延续原报价强调词点的声音时钟。共混入十条原库音效及一条原库背景乐。实录词区间的背景乐比人声低 10.43 dB，原声分轨与原片的波形差为 -143.34 dBFS。新增三处主字幕与原生文字区间距 22 至 70 像素。抽帧核对了标题切换、竖排和数量圆窗。

Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，两个版本均支持 HTTP 206。高清文件 C:/tl/yy-opening-expanded-20261110/website-yy-expanded-hd.mp4，SHA256 为 0a7c99e4083a3c195d6280554e1db38cadc741c3e988f44f53ace1158f38ae8d。浏览器、媒体、编排和旧版回放证据均在同目录。用同一实录验证了错误的说明词、错过固定入场窗的词点和分离的数量单位都会被拒绝。旧版冻结配方重算与已交付任务一致。

网站保持 18 套可选模板，可自动编排的不同原生组增至 63。290 项相关回归、Ruff、目标 mypy、差异检查和原包 1426 项完整性复核通过。原库仍登记全部 132 组。其余月云川六种开场批次的组继续保留组件状态。本轮未新增付费调用或部署，真实模型选组及用户整片画面、听感仍待验收。

## 同期人物运镜与分区

新模板 `presenter-reframing-v1` 接入原生 YYP01–07，配合已有透明字效。推近、缩景、运镜及人物出框的动作边界由实录词点编译。分区、描边、双素材接力和透视折叠继续执行原固定动画，只在实录词点符合原动作窗口时使用。原输入的字幕时钟仍绑定实录，完整字幕在整片生成。主字幕在整帧镜头内移至底部读区，人物和原声沿同一实录时钟播放。运镜和出框各有独立的原库提示音。

规划准备检查无内嵌字幕的原片，以及双素材组所需的两份不同、时长足够的本期视频。媒体卡只在该模板记录已核对的项目视频时长，已有准备版本的卡字段仍可回放。后端根据实录停顿和标点列出有限的可选词范围、已测事件词 ID 及对应视频槽。模型继续只返回词 ID 和素材 ID。重新核对编排时逐项验证本次实录区间及每个补充视频的实际取帧长度，保持两个补充画面从各自首帧开始。以 240 个实际词点重算并验证了七组共 131 项建议绑定。过短素材、错过原动作窗及调换运镜与出框顺序均被拒绝。

工程联调第一份双素材候选要求第一段补充视频覆盖 4.1 秒，已选手势取段为 4 秒，预览提交被拒绝。第二份候选缩短镜头至实录句尾后，编译器仍拦下三个缺少原生字幕时钟的运镜组。补齐对应实录首词绑定后，11 个原生配方通过编译，进入独立 worker 渲染。双素材试验使用本期已登记的手势及人物近景，画面用途为核对两个取帧时钟。

Chrome 实测选择新模板。未勾补充视频的准备请求仅停用 YYP05，并显示需要两段不同视频。勾选两段项目视频后的新请求可使用全部七组画面。最终任务 `3616151c-2a75-4c0d-8cf6-2d07670ec1d4` 由网页提交，独立 worker 一次完成。实播 360×640 代理，确认后实播和下载 720×1280 高清，两种文件均支持 HTTP 206。

48.475 秒实录成片含 11 种动效、12 条原库音效及一条原库背景乐。七个新增场景独立解码共 811 帧，各场景的帧摘要均不同。八处画面动作的音效分别对准零基成片第 33、168、286、506、992、1074、1194、1267 帧。每帧与原生组件对应动作帧的像素误差均小于相邻帧。双素材的正确取帧平均像素误差为 1.70 和 1.76，错用镜头时钟为 7.94 和 11.41，调换素材为 58.77 和 60.34。抽看人物和手势分区、双素材圆窗、人物出框和透视折叠。原声分轨与实录的波形差为 -143.34 dBFS，实录词区间背景乐比人声低 10.43 dB。

高清位于 C:/tl/presenter-reframing-20261110/website-presenter-reframing-hd.mp4，SHA256 为 8649e4f0f53d98f2d89d0e9ff34c7f078c5b2779920ca691b9e43f1c7f2fc9a9。浏览器准备与交付、媒体和编排证据在同目录。网站现有 19 套可选模板，可自动编排 70 个不同原生组。292 项相关回归、Ruff、目标 mypy、前端类型和目标 ESLint、差异检查及原包 1426 项完整性复核通过。全量 132 组继续登记。本轮使用本地受控规划，没有新增付费调用或部署。真实模型选组及用户整片视听仍待验收。

## 阿哲多素材板式进入网站自动编排

新模板 `azl-panels-v1` 接入原生 AZL01–07。原 360×540 板式保持二比三比例，放在 9:16 成片上方，独立主字幕放在板式下方。网站按各原构图选择白底或深色底，并用原 `visual_scenes` 合成器铺满整个画幅。原素材槽、裁切、字型和同期人物取帧均沿用原入口。网站将底色和板式绑定相同的成片帧区间。连续口播预览的入场校验只接受此模板的固定投影，导出后另核对底色回执及主字幕实际墨迹。提示音绑定本段首词后的首个合成帧。

规划准备按原槽位核对一至三份不同的本期图片或视频。视频从各自首帧开始且须覆盖整段，项目图片按原静态输入规则使用。AZL06 三张卡保留原共用素材槽，三项卡词独立绑定实录。规划请求提供服务端按实录计算的可用段落、字幕词点与各段可用的素材 ID。用 240 个实录词核对了 117 项板式候选绑定，拒绝重复素材、移离本段首词的字幕入口及重复的关键词卡。零份素材时停用七组，两份时只停用 AZL04，三份时七组可选。上一版运镜模板的词点建议与请求摘要重算一致。

第一轮网页候选被旧的单层全幅门槛拒绝。调整后网页创建剪辑任务，原引擎又拦下缺少底色用途的 `selection` 记录。将每处底色补为有用途的原生选择项后，从网页重试同一任务。试片的独立补充画面取自本期已登记的两段实录近景和一份灰墙取样，用于区分原素材槽的画面和取帧时钟。

第一份下载件在 AZL03、AZL04、AZL06 和 AZL07 的最后一个合成帧各露出一帧底色。原 `setpts` 在输出帧时基中截断非整数起点，可能让同一输出区间比可用板式多一帧。网站现在按原时基限制板式和底色的实际退出区间，避免跨过第一个没有原生画面的成片帧。切换后继续使用同期原视频，实录音频和已编译的原素材区间保持完整。

最终从 Chrome 重试网站任务 `df6c47c8-f736-4a31-a917-084082ae947c`，独立 worker 完成编码。浏览器实播 360×640 代理，确认后实播并下载 720×1280 高清，均支持 HTTP 206。48.475 秒成片含 11 种动效、11 条原库提示音和一条原库背景乐。七处板式提示音落在各自首个可见帧。逐帧核对七段共 690 个板式活动帧的底色覆盖，实际主字幕距板式下沿 62 至 110 像素，四个原退出闪帧均恢复为同期原画。抽帧核对三素材板式的三个槽和同期人物，两个视频槽与各自时钟的同期取帧更接近。原声分轨与实录的波形差为 -143.34 dBFS，实录词区间背景乐比人声低 10.43 dB，校正前后下载件的解码混音逐样本一致。

高清文件位于 `C:/tl/azl-panels-20261110/website-azl-panels-hd.mp4`，SHA256 为 `39da2a32493e335bbc3828073096d6c66ab8d18373a44bcda8fe197a98c60190`。浏览器、媒体和编排核对结果在同目录。296 项相关回归、Ruff、目标 mypy、前端类型和目标 ESLint、差异检查及原包 1426 项完整性复核通过。网站现有 20 套可选模板，可自动编排 77 个不同原生组，全量 132 组继续登记。本轮使用受控规划，无新增付费调用或部署。真实模型选组和本期商品配图的语义验收，以及用户整片视听仍待完成。

## 晨曦双路实景进入网站自动编排

新模板 `chenxi-broll-v1` 将 CXBR01–05 与原字幕组合一起提供给网站规划。五组保持原画幅、人物窗、抠像、裁切、纸纹底图、纸条和各自的运动曲线。同期人物使用实录源区间，独立补充视频按原槽位从自身首帧播放，长度须覆盖其原生可见窗口。部分组另要求独立的本期纸纹图片。CXBR01 的顶层原参考字段与人物槽共用同一个实录原件，原教程和水印继续关闭。CXBR01 原 Times New Roman 和 CXBR02 原抠像模型经私有登记核对，路径留在 worker。

规划准备区分独立视频和图片，排除与实录原件摘要相同的上传，按原生分段长度提供可选视频 ID。实录词点建议仅提供事件边界，不预填截断的中文字串。原生短标签由语义规划选完整实录词组，编译校验短语和入场词点、各动作顺序和读取窗口，并重新核对实际原件。主字幕放在原生标签及纸条的文字带下方，导出后按原生 libass 墨迹复核。背景和人物画面可按原构图切换，整片原声音轨保持连续。补充视频铺开、纸条出现和圆窗入场按各自首个可见帧放置原库音效。

首轮网页候选的 CXBR01 要求 4.367 秒的独立视频，所选手势取段只有 4 秒，预览提交被编排校验拒绝。第二轮将该镜头结束点放在已说完「4斤」后的实录词尾，保留三处规格短语及后续口播。试验补充画面使用本期已登记的手势、人物近景和墙面样本，目的是验证原件归属、两路视频时钟及纸纹输入。

用 240 个实录词点核对了五组共 40 项可用时间窗。编译拒绝过短的视频、用视频填纸纹槽、把标题和实际首词错开、给参考槽换用补充视频，以及颠倒素材带和圆窗的动作顺序。仅选视频时，Chrome 准备页面显示 CXBR01、CXBR03、CXBR05 停用，勾选已登记纸纹后五组均可选。上一版阿哲板式的冻结请求摘要重算一致。

网页任务 `a68c3a07-3842-4fc3-b9d9-13c69f6224ba` 由独立 worker 一次完成。Chrome 实播 360×640 代理，确认后实播及下载 720×1280 高清，两种媒体均支持 HTTP 206。48.475 秒成片含 10 种原生动效共 11 次、13 条原库提示音及一条原库背景乐。七处实景动作的提示音落在成片零基第 176、440、669、796、863、1193、1206 帧。原声分轨与实录的波形差为 -143.34 dBFS，有词区间背景乐比人声低 10.43 dB。

五组原生组件共独立解码 605 帧，各组内部帧摘要均不同。按八位像素通道平均绝对误差衡量，补充视频的同期取帧误差为 1.49 至 1.79，冻结画面对照为 6.21 至 24.71。人物的同期取帧误差为 2.02 至 4.47，冻结对照为 14.15 至 20.54。五个退出点相对同期原片的画面误差均低于 1，实际主字幕墨迹距离原生文字带至少 172 像素。抽看规格圆窗、透视纸条和素材带。规格镜头的原生短标题经过脸部区域，素材带镜头的简短并列标题省略了顿号，完整主字幕保留实录标点。

高清文件位于 `C:/tl/chenxi-broll-20261110/website-chenxi-broll-hd.mp4`，SHA256 为 `43f88d8f6fb56a4ba0cf86fabb9085ed007544fb726bc659f54ec6e241604d7c`。浏览器、媒体和编排证据在同目录。298 项相关回归、Ruff、目标 mypy、前端类型及目标 ESLint、差异检查和原包 1426 项完整性复核通过。网站现有 21 套模板、82 个可自动编排的不同原生组，完整原库仍登记 132 组。本轮使用受控规划，无新增付费调用或部署。真实模型的选组和配图、用户整片视觉及听感仍待验收。

## 月云川五组背景开场进入网站自动编排

「月云川人物开场」升级为 `yy-presenter-openings-v3`，接入 YY6O01、YY6O02、YY6O03、YY6O05、YY6O06。v1 和 v2 按冻结槽位继续读取。五组使用同一期原片及本期静态背景，撕纸组需要两份不同摘要的原件。原字体、人物蒙版、闪现、暗底圆窗、原问号图形、竖排与聚光灯继续通过原入口。背景和人物可按原设计暂时覆盖原画，口播音轨继续取完整实录。

本期 240 个实录词点中，准备接口给出八组可绑定的数量与单位。两字之间仅接受相邻实录或有连续时钟的「大」「小」修饰。规划只能引用这些词 ID；编译校验同一数量词对、实录疑问词、聚光灯短指标、动画顺序及读取窗口。未选背景时停用五组，只选一张时停用撕纸组，背景齐备后五组可选。每组的场景开头和第二个原生动作各用一条原库提示音。撕纸和闪现两组的原生数字或说明更靠下，主字幕单独选择更低的基线，导出按原生 libass 的实际墨迹检查。

首轮网页提交到独立 worker 后，问号组因缺少保留原设计图形的专用决定被拦截，两个规格对照候选也缺少两项实录和原文字槽的关系映射。适配层登记原问号并提前核对关系项，修订候选把单瓶规格与到手总量分别绑定到对应语段。双背景采用本期已登记的同一房间左右两处墙面裁片，用于验证原撕纸图层的输入与合成。

Chrome 实测新模板仅勾一张图时显示撕纸缺件，补齐第二张后恢复可选。原生编排拒绝了重复背景、错配单位、无疑问词的问号、无数值的聚光灯短指标和颠倒的闪现顺序。旧版 v2 冻结请求摘要重新计算一致。

两个修订后的网页任务均由独立 worker 一次完成。Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，两种文件均支持 HTTP 206。两条都为 48.475 秒，各含 10 种原生动效及一条原库背景乐。

- 撕纸、问号与闪现任务 `7462b195-4980-491e-bf1d-1ec9d7e1050a` 含 13 条提示音，六个新增动作提示音落在零基成片第 13、28、147、182、417、546 帧。高清位于 `C:/tl/yy-opening-all-20261110/website-yy-paper-focus-hd.mp4`，SHA256 为 `d54fe10276d9677c7b0cc7377c4be47abcb04dd8a8f89d691045dcbfe01bf5ad`。
- 电视纹理与聚光灯任务 `e84c0cf2-6d49-42c7-ad9c-951a72e5b91e` 含 12 条提示音，四个新增动作提示音落在第 260、357、417、546 帧。高清位于 `C:/tl/yy-opening-all-20261110/website-yy-light-texture-hd.mp4`，SHA256 为 `ccb485d2a160c786b2fd2d147e73aed8312794d92a46f03e00dc904cc3e29682`。

五组原生组件共解码 832 帧。抽样人物区域相对同期取帧的八位像素通道平均绝对误差为 2.69 至 3.26，冻结对照为 14.09 至 16.44。撕纸揭开后与第一张原件的误差为 1.34，回切后与第二张原件的误差为 1.38。五处退出帧相对同期原画的误差为 0.89 至 1.01。主字幕墨迹距原生文字区 14 至 70 像素。抽帧确认撕纸原数字与说明的叠放、问号圆窗和电视纹理的短时虚焦。两条原声分轨与实录的波形差均为 -143.34 dBFS，有词区间背景乐比人声低 10.43 dB。

300 项相关回归及修订后的 50 项适配复跑、Ruff、目标 mypy、前端类型和目标 ESLint、差异检查、原包 1426 项完整性复核通过。21 套模板可自动编排 87 个不同原生组，原目录 37 个实景组均已进入自动模板，完整原库仍登记 132 组。本轮使用受控规划，无新增付费调用或部署。真实模型选组及用户整片视听仍待验收。

## 统一引擎论点与数量对照进入网站自动编排

新模板 `unified-argument-v1` 加入 Z-M01、Z-M02、Z-M03、Z-M04、Z-M09、Z-M10、Z-M14 和既有原字幕组合。原景论点、暗角、矩形窗、圆窗与并列词使用原入口的当前人物视频槽，整帧不等式和数字卡沿用原底板。原静态入口仍可核对，网站适配为 Z-M02、Z-M03、Z-M04 绑定实录视频区间，并逐组固定原入口、媒体取样和布局文件摘要。原生采样从局部帧时间加页起点后读取一次实录偏移。人物视频到期按原生错误策略处理。

每项并列词和不等式前后两项按实录顺序提交关系映射。数字卡限制为实录中的一位数字，正文保留数量与单位，强调词由各自实际首词触发。暗角内部的三段原生短字幕按实际首尾词绑定，完整主字幕另行绘制。原布局以容量不足即拒绝的策略执行。声音按统一引擎的硬入场、渐变或全幅切换规则编译到成片帧轴。网站按原生输出的实际帧数限制场景退出点，主音轨连续。

首版人物窗试片在 Z-M03 的结论阶段出现网站主字幕盖住原生黄字，保留该次结果用于对照。现将网站主字幕放入人物窗下缘，原生标题、并列标签和结论保持原位。一个字幕跨越不同读区时在场景交界拆分显示区间，文字和原声连续。交付检查使用原生字幕报告的实际墨迹框，核对读区上下边界。报价对照片首轮在 AH-S02 因实录选段超过原生单行上限停止。编排现提前核对原合同声明的字幕字数，试片使用原声短语「每瓶都是」与「两斤」，主字幕保留完整规格。

编排验证确认 Z-M02 的原生短字幕错时、Z-M03 的并列顺序错置、Z-M04 的圆窗错过词点、Z-M09 的关系类型错误、Z-M10 的末段停稳时间不足和 Z-M14 的标签错时均被拒绝。AH-S02 的原失败内容现于编排预检拒绝，符合字数的实录词组通过。月云川 v3 的已冻结规划请求重新核对摘要一致。原包 1426 项完整性通过，22 套网站模板可自动编排 94 个原生组，完整目录仍登记 132 组。

两次最终本地网站任务各由独立 worker 一次完成。手机宽度 Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，支持 HTTP 206。两片均为 48.475 秒，下载摘要与原生交付文件一致。

- 人物构图任务 `c548fac9-e4c7-4a39-ba8d-9219d640daaa` 使用 11 种动效和 18 条音效。Z-M03 的五条音效落在零基成片第 1174、1193、1206、1223、1273 帧。修订后的主字幕实际墨迹距人物窗读区边界至少 17 像素，抽帧确认黄字完整可读。高清位于 `C:/tl/unified-argument-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `47fec7d043160ea11053a01babe759aaa1ac753d51b76ea6916e56711668388d`。
- 数量对照任务 `dd86e87f-bbc4-4e3f-8f62-b3859b6a6a7a` 使用 10 种动效和 14 条音效。新增组的动作音效落在第 213、300、546、554、1193、1206、1223 帧。高清位于 `C:/tl/unified-argument-20261110/website-unified-compare-hd.mp4`，SHA256 为 `5372f250d288eea1f207865232c18e780ccbbc1de8528cb9500762e5f5179d64`。

七组原生组件共解码 969 帧。五个人物组各取四帧，比同期取帧的八位像素通道平均绝对误差为 2.40 至 2.60，冻结对照为 7.69 至 19.23。各组退出帧恢复同期原画，误差为 0.93 至 1.21。两片原声分轨与实录波形差均为 -143.34 dBFS，有词区间背景乐比口播低 10.43 dB。独立核对提示音分轨的逐条素材摘要、起点及混合。回执和抽帧见 `C:/tl/unified-argument-20261110` 的 `browser-preview-*.json`、`media-evidence-*.json` 与 `Z-M*-review.png`。

301 项剪辑、文稿与原库相关回归、Ruff、目标 mypy、前端类型和差异检查通过。本轮使用真实口播和已对齐的 240 个词点，规划响应由本地受控样例提供。未新增付费调用、数据库迁移或部署。真实模型选组及用户整片观感、听感仍待验收。

## 原双论点、数字镂空及年份进入组合模板

网站可选的「论点、数量与年份」使用 `unified-argument-v2`。新增 W-R05、W-R07、AH-S07 三个槽，旧 v1 按已冻结的槽和规划请求继续回放。W-R05 的两个字层分别绑定本期并列词组，使用原景裁切及原动作。W-R07 的数值与各自短句逐项绑定，两个数值必须不同且使用同一实录单位。原遮罩、黑场渐变与数字轮转用同期原片，口播音轨贯穿原段。两组的四条音效按原动作开始的成片帧触发。

AH-S07 只在实录含连续四位年份且原生背衬字体已核对时可选。前后短词须紧邻年份，年份、前后字入场和背衬分别核对原词点。数字投影及原生透明字层保持原设计。商品口播没有年份，真实网站准备任务只将这一组列为不可选。用此前本地合成并实际识别对齐的测试音频重新编译和渲染了 AH-S07。原文为「二零二六年」，原生显示为「2026年」。完整解码 139 帧，核对透明序列中 100 个有内容的帧。摘要 `9e267dd8fd9e3620e1950a62a359032654643ce7141ba193cc5f54f6e9bc8fc4` 与此前同素材的手工配方一致。该项证据范围是组件，带真实年份口播的整片仍待验证。

清洁用品试片任务 `9f2f1af6-fe6a-40df-9715-afc3caff1c8e` 由独立 worker 一次完成，时长 48.475 秒。整片使用 11 种原生动效、19 条原库提示音及一条背景乐。手机宽度 Chrome 实播 360×640 代理，确认后实播及下载 720×1280 高清，均支持 HTTP 206。高清位于 `C:/tl/unified-timeline-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `a3d285743cdd15db36f3143b2e66a65d7ddbc7bc346e896c093e82b5f67cd613`。

数字镂空两段抽取四帧，数字内部与同期原片逐像素比对，每帧均比冻结首帧更接近同期画面。双论点的四帧人物区域同样符合实录取帧。四个新增音效位于零基成片第 469、546、827、863 帧。数字区原字幕保留本期单瓶和到手规格，网站主字幕保持独立读区。原声分轨相对独立解码实录的差值为 -143.34 dBFS，词覆盖期间背景乐低于原声 10.43 dB。原生版面、下载摘要、音轨及抽帧的核对记录位于 `C:/tl/unified-timeline-20261110`。

原包 1426 项完整性复核通过。错配计量单位、用后续字触发双论点和移动年份首词均被拒绝。旧 v1 冻结请求摘要复算一致。302 项相关回归、Ruff、目标 mypy、前端类型、目标 ESLint 及差异检查通过。原库全部 132 组继续登记，网站 22 套组合模板可自动编排 97 个组，其中原库 43 个字幕组均已进入模板。试片使用真实口播与本地受控规划。真实模型选组、年份整片及用户视听待验证。本轮无新增付费调用、数据库迁移或部署。

## 实拍与项目素材接力进入网站自动编排

新增「实拍与项目素材接力」模板 `material-cut-v1`，纳入 Z-M06、W-R08、W-R10、W-R16。沿用原生三段实拍、三张撕纸、手机画面及五段表盘。准备任务按已勾选且核对字节的本期配图去重。编排要求各切点对应实录首词，关系项、原生槽位和项目素材按同一顺序匹配。切回人物时按各自原生切点从同期原片取帧。原引擎保留手机内三个固定字幕段，网站限制文字取自相应实录区间。Z-M06 的原外语槽在纯中文试片中留空，原中文短句和网站主字幕继续播放。撕纸和手机动作绑定原库提示音，实拍切入和表盘入场各有一条提示音，口播原声保持连续。

真实网站准备接口在未选图片时将四组都列为不可选。选择已有的三张用途示意及两张新登记的实录报价和件数示意后，四组都可编排。素材通过项目接口回读摘要，错位的原生字幕、复用同一组配图、跨段换图和颠倒切点关系都被拒绝。此前 v2 冻结请求复算摘要一致。第一条试片首轮因关系画面中的同期原片缺少画面身份记录被原生检查拦截，网站补录经摘要核验的本期原片身份后，通过原任务重试。该身份用于区分讲述者画面与项目配图，商品事实和素材权属仍依照项目原有记录。

两条试片均为 48.475 秒。手机宽度 Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，两种媒体均支持 HTTP 206。

- 实拍接力与表盘任务 `6481c18f-321e-4986-bb31-6db7da2308f0` 使用 11 种动效、11 条提示音和一条原库背景乐。两个新场景的提示音在零基成片第 260、1174 帧。高清位于 `C:/tl/material-cut-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `a068cf41e346418d59ce87bb819aec204f1a1fc0a6e1ee60cca1aabfe9d96375`。
- 手机画面与撕纸任务 `ee02b403-1c8b-4dfb-9c61-b4b72f3c3661` 一次完成，使用 10 种动效、15 条提示音和一条原库背景乐。新动作的提示音在第 234、274、333、375、1194、1206、1223 帧。高清位于 `C:/tl/material-cut-20261110/website-unified-compare-hd.mp4`，SHA256 为 `495fed0ba460930a9eedb66fcaad6b72f9178aa2cf258b541c5a8e42f451de1a`。

四个原生组件共独立解码 509 帧。每个切段抽一帧对照已登记原件，五段视频抽帧与同期原片的八位像素通道平均绝对误差为 2.17 至 4.16，冻结对照为 9.41 至 25.80。四处退出帧回到同期原画，误差为 0.93 至 1.19。主字幕墨迹通过四组读区检查，原表盘刻度保持原位置。两片原声与独立解码实录的波形差均为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB。素材摘要、画面抽查和声音回执位于 `C:/tl/material-cut-20261110`。

303 项相关回归及最终 53 项适配复跑通过，Ruff、目标 mypy、前端类型、目标 ESLint、差异检查及原包 1426 项完整性复核通过。网站 23 套模板可自动编排 101 个原生组，原库全部 132 组继续登记。两片使用真实口播与本地受控规划，配图用于示意。真实模型选图、用户整片观感及听感待验收。本轮无新增付费调用、迁移或部署。

## 同期人物四图板、逐项图例及三路并置

「人物与图例并置」模板 `media-panels-v1` 纳入 Z-M07、Z-M08 和 W-R13，继承素材接力模板的 26 个槽。Z-M07 同时显示原人物窗和四图板，板内四图按实录项依次绑定。Z-M08 将四张独立用途图及中文标签依次锚定到实录词点，原图形蒙版保留。W-R13 用原生三路并置同时播放同期人物与两份本期素材。补充视频使用各自时钟且须覆盖原生可见窗口。首轮 W-R13 因将进场持续时间误用为提示音起点而编译失败。适配将提示音绑定到首个可见动作帧，保留原生进场持续时间，同一任务重试成功。全视频三路的独立原生组件另外完整解码 120 帧，逐帧摘要均不同。

网页准备任务在未选项目素材时提示七个素材槽不可用，选择已核对的本期原件后恢复。编译拒绝颠倒四图板关系项、移离第四图的实录词点及过短的三路补充视频。上一版素材接力模板的冻结请求摘要复算一致。原库 1426 项完整性通过，132 组继续登记。网站 24 套组合模板可自动编排 104 个原生组。

联调初版把素材说明画进了示意图。新版将内部说明保留在项目记录，报价卡只保留实录说出的「14块9」，四图板的数字卡只保留对应实录内容。用途图使用已登记的独立用途示意。网站补充素材入口提示使用干净原件，规划说明明确素材记录供选材，标题和字幕仍按实录编译。已写进上传图片的文字会随原件进入画面，因此本轮重新登记清理后的图片并重新出片。已有创意图可以从同工作区导入。真实生图供应商回流、真实模型选材及用户整片视听仍待验收。

新版两条网站任务由独立 worker 各一次完成。Chrome 在手机宽度实播 360×640 代理，确认后实播并下载 720×1280 高清，两种媒体均支持 HTTP 206。两片均使用 48.475 秒实录与已对齐的 240 个词，本地规划响应受控。

- 报价、四图板及三路并置任务 `cba46a84-9744-4d21-a9f3-a793b6f72f01` 含 11 种动效、12 条原库提示音及一条原库背景乐。四图板及三路并置三个新增提示音在成片零基第 376、422、1174 帧。高清位于 `C:/tl/media-panels-clean-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `07baf8a6a263281a500e412708cd1afb87e946099c69a88dfcc1bddc033cde54`。
- 手机画面及逐项图例任务 `5ee5b560-501b-435d-b164-35713ace1c7a` 含 10 种动效、16 条原库提示音及一条原库背景乐。四幅用途图的提示音在第 1193、1206、1223、1249 帧。高清位于 `C:/tl/media-panels-clean-20261110/website-unified-compare-hd.mp4`，SHA256 为 `906e6a4ee9d30c25b055ae3abb2fcb187e934ac1c87b203c1b3607780fadf7e4`。

三处新增组件共解码 436 帧。人物和补充视频抽帧与各自时钟的同期画面误差为 1.72 至 2.44，冻结首帧对照为 6.20 至 22.62。退出点均恢复同期原片。三路并置试片使用本期手势特写和水果用途示意检验两个独立输入槽。逐项图例核对四幅画面各自的出图顺序与实际词点。两片原声与独立解码实录的波形差为 -143.34 dBFS，有词区间背景乐比原声低 10.43 dB。核对六张重做图片的文字范围、网站成片的素材摘要和原生参数，内部说明只出现在项目素材记录。新版截图、浏览器与媒体证据在同一试片目录。

304 项相关回归及 W-R13 校时修正后的 78 项适配复跑通过。Ruff、目标 mypy、前端类型、目标 ESLint 和差异检查通过。本轮无新增付费调用、迁移或部署。

## 资料板及实录问答进入组合模板

「资料说明与口播问答」新增 Z-M13 和 Z-M16，沿用「论点与数量对照」的原有选项。Z-M13 保留原上方放大资料板和四行双列结构，每行的两处文字来自同一实录范围。资料板在第四行所引用的词说完后显示，原中文字幕按实录起止词绑定，纯中文试片的英文槽留空。Z-M16 保留原背景虚化、问号、人物圆窗和三项回答。问号由实际疑问词触发，圆窗随第一项入场，之后按各项首词依次显示，末段用实际口播词组收束。两个场景均使用同期原片，主字幕与原口播音轨继续走整片时钟。

准备和编译核对四行与三个回答项的顺序、阅读时间和词点。提前出资料板、交换行项、提前结束原生短字幕、把问号移离疑问词、延后人物圆窗及打乱回答顺序共六种候选均被拒绝。上版「人物与图例并置」冻结请求摘要复算一致。原包完整性通过 1426 项，132 个原生组继续登记。25 套组合模板可自动编排 106 个原生组。

首轮问答下载件的长问题触发了原生前景文字换行，后面的单行光晕在两侧被裁切。按原字号和读区将问题前景限制在四字以内，编译预检会拒绝超长问题。新版取实录「你们谁」触发原问号，完整问句继续出现在整片主字幕。原光晕、颜色和叠放构图保持原设计。

本轮使用清洁用品真实口播和此前实际对齐的 240 个词。规划由本地受控响应提供，网页提交后由独立 worker 生成代理和高清。资料板任务 `1cc890fa-5628-4320-9900-6a163cedd3f8` 使用 10 种动效、17 条原库提示音及一条原库背景乐。原生组件完整解码 265 帧。资料板动作和提示音同在零基成片第 554 帧。对比同期原片，四帧口播人物区域的平均像素误差为 1.94 至 1.97，冻结首帧对照为 12.22 至 22.21。高清位于 `C:/tl/unified-explanation-final-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `99e8b70cf24b6c1c35ea469fc52ca0050369c7f6f1dcc85be83fba0d1a809f93`，与首轮实片一致。

问答任务 `7174793e-4638-4364-95f8-aa4b2af8a34a` 使用 10 种动效、22 条原库提示音及一条原库背景乐。原生组件完整解码 425 帧。问号、圆窗、三项文字及收束的提示音位于成片第 156、301、301、357、441、522 帧。三项在各自的实录词点进入，按原生读区抽帧确认。圆窗人物四帧的同期取帧误差为 1.92 至 2.12，冻结画面对照为 9.24 至 16.80。短问词画面两侧和同期虚化原片的误差为 1.70，抽看确认光晕保持在画幅内。高清位于 `C:/tl/unified-explanation-final-20261110/website-unified-compare-hd.mp4`，SHA256 为 `23e6b7eb2e82c2c7b3fb334ead4312eb66d3ce9c6f696b66965d893bde158dcd`。

两条修订版均由独立 worker 一次完成。Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，代理和高清均支持 HTTP 206。两片时长均为 48.475 秒，完整原声分轨相对独立解码实录的波形差为 -143.34 dBFS，有词区间背景乐比原声低 10.43 dB。浏览器回执、抽帧和独立媒体核对记录在新版试片目录。304 项剪辑、原库和文稿回归通过，问句版式修正后复跑 63 项适配测试，Ruff、目标 mypy 和差异检查通过。真实模型选组及用户整片观感、听感仍待验收。本轮无新增付费调用、数据库迁移或部署。

## 闪亮转场与评论框进入组合模板

「转场与评论引导」新增 W-R03 闪亮分支和 W-R06。闪亮转场把前项实录、后项实录和后项独立项目图片按顺序绑定。前段同步取原片，后段使用本期对应配图，整片口播与主字幕连续。网站按照原引擎重定时后的首个可见帧安排提示音，校验三段动作的顺序和时长。原彩条分支仍保留在原库目录，另待自动编排。

评论框需要本段实际说出的评论邀请、明确的输入指令和关键词。提交前为同期原片，提交后使用独立配图。上移和提交分别绑定滑动声及点击声。选中一张配图后，真实商品试片的准备任务仅将评论框标为不可选。另用此前本地合成并实际对齐的评论测试口播验证原生组件。初次读取旧联调库遇到缺失素材来源列，在独立 SQLite 副本应用已有 `20261109_0049` 迁移后重跑。组件重新完整解码 209 帧，局部第 138 帧仍匹配同期视频，第 139 帧切到静帧并出现关键词。声音编译将提示音锚定到含镜头前区间的第 69 和 147 帧。组件和声音编译回执属于技术验证，含真实评论引导的整片和混音仍待验证。

编排检查拒绝闪亮峰值过晚、转场偏离后项词点、颠倒关系项、把口播原片当后项配图、把否定的评论指令当邀请，以及移动评论关键词的提交时点。上一版「资料说明与口播问答」冻结请求摘要复算一致。原包完整性通过 1426 项，132 个原生组继续登记。26 套组合模板可自动编排 108 个原生组。

首轮商品试片的 SG-S03 数字词组超出原生固定字数，网页预览提交被校验拒绝。替换为能容纳「每瓶」和「1000克」的同期双短语动效后重新提交，保留两处 Z-M01 在不同词点的重复使用。闪亮转场使用两瓶数量图例，图例只画两种无商标瓶形。无新增商品事实或内部备注。试片使用真实口播和本地受控规划。

网页任务 `af904925-25bd-47ba-8139-1c0ef4387df8` 由独立 worker 一次完成。48.475 秒整片使用 11 种动效共 12 次、20 条原库提示音及一条原库背景乐。Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，均支持 HTTP 206。W-R03 的 91 帧完整解码。闪亮动作与提示音同在零基成片第 505 帧，即 16.833 秒，距离实际后项词点 16.850 秒约 17 毫秒。转场前抽取的三个画面更接近同期原片，转场后的三个抽帧均匹配登记的两瓶图例。退出点恢复同期原片。整片原声分轨与独立解码实录的波形差为 -143.34 dBFS，有词区间背景乐比原声低 10.43 dB。

高清文件位于 `C:/tl/native-handoff-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `6d46acdfa12e1fb6add743ac2f0ded6c8ea865bede5bc708f807d80a8b44098e`。浏览器、编排、媒体和评论框组件证据位于同一目录。306 项剪辑、原库和文稿回归，以及最后调整后的 58 项适配回归通过。Ruff、目标 mypy、前端类型、目标 ESLint 和差异检查通过。真实模型选组及用户整片观感、听感仍待验收。本轮无新增付费调用、项目数据库迁移或部署。

## 原生竖向、横向分屏接入同期人物

「竖横分屏与同期人物」将 CX-G01 和 CX-G02 加入网站组合模板。两组沿用原生浏览器代码、原标题字体、三项入场动作和各自画面。每项配图、标签和完整短语从同一个实录词段绑定。竖向版保留先显示实录短标题再缩入原生方窗的流程，英文槽在纯中文试片留空。横向版使用原抠像模型逐帧产生同期人物轮廓，保留原右下位置和描边。主字幕置于前两排标签之间，口播全程使用原声音轨。网站将提示音绑定到实际词点对应的原生动作帧。

准备任务显示三张不同项目图片的要求。编排拒绝两张图、重复图、错过词点的入场和延后的竖向开场标题。上版「转场与评论引导」冻结请求摘要复算一致。原包完整性通过 1426 项，132 个原生组继续登记。27 套组合模板可自动编排 110 个原生组。

首轮原生组件配置通过独立编译，整片编译读取了另一类场景的时长结构，两个任务在渲染前被拦截。修正后使用各浏览器原生帧数计算整片中的镜头边界，并从网页重试原任务。此前 CX-G04 轮换图卡的适配调用仍接受原有入参格式。试片均使用已对齐的清洁用品真实口播和本地受控规划，分屏配图为按原生裁切区制作的用途图例。

横向草片的原生右下人物遮到了三字标签「洗水果」的末字。横向标签限制在两字内后，采用实际说出的「水果」，图片和提示音随「水」字进入，完整「洗水果」由主字幕显示。竖向版保留三字原生标签。CX-G04 用原有入参复跑，完整解码 100 帧，输出 SHA256 与旧组件逐字节一致，回执 `5558fe9440ae413795c5fdfb04884c83`。

两条定稿均由网页提交，独立 worker 各一次完成。Chrome 手机宽度实播 360×640 代理，确认后实播并下载 720×1280 高清，均支持 HTTP 206。两条各 48.475 秒，包含 11 种原生动效、16 条原库提示音及一条原库背景乐。

- 竖向任务 `c164c62a-2594-41ad-865f-15326bea0f24` 的三幅用途图与提示音分别进入零基成片第 1193、1206、1223 帧。主字幕与相邻原生文字的最小距离为 27 像素。高清位于 `C:/tl/live-browser-splits-final-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `a9bb60e8bf01ef851be6750736d95fd454596955d314ece7a0037651aa198e82`。
- 横向任务 `c3c32fbb-9416-40b2-902d-4d668dbdbf0c` 的三个对应时点为第 1193、1206、1230 帧。主字幕与相邻原生文字的最小距离为 34 像素，抽查确认人物和「水果」标签分开显示。高清位于 `C:/tl/live-browser-splits-final-20261110/website-unified-compare-hd.mp4`，SHA256 为 `7330aba4f27fa83b4ac11f0588e6576b96c662e2ad6aa6ec840d934cecadb237`。

两处组件各完整解码 120 帧。人物区域四处抽帧与同期原片的八位像素误差为 2.66 至 3.22，冻结对照为 9.46 至 14.76。退出点回到同期原画。整片原声分轨相对独立解码实录的波形差为 -143.34 dBFS，有词区间背景乐比原声低 10.43 dB。抽帧、音轨和浏览器回执在试片目录。306 项剪辑、原库和文稿回归通过，最后布局调整后复跑 70 项适配测试。Ruff、目标 mypy 和差异检查通过。真实模型编排及用户视听待验收。本轮无新增付费调用、数据库迁移或部署。

## 全部新规划统一区分素材备注与成片文案

截图里的「实录报价」和「口播内容示意」来自试片配图上已经写入像素的内部说明。此前已重做报价图并从网站重新编码，图上只保留实录「14块9」。本轮复核报价段抽帧与高清摘要。新准备的所有规划任务，包括未指定模板的任务，统一要求可见文案绑定实录，素材名称、用途说明和来源记录仅用于选材。若素材记录注明原件画面含备注、占位字或无关水印，规划应跳过并记录所需干净原件。未注明的图片内嵌文字仍需在素材入库时核对，当前流程不做像素识字。

文案规则随准备任务快照冻结。用「人物与图例并置」及「竖横分屏与同期人物」的既存请求复算，旧摘要均一致，新规则只改变规划指令，素材和转录数据保持一致。52 项规划、恢复和来源回归，以及 Ruff、目标 mypy 通过。

## 原生水果介绍进入自动编排

本节是历史联调记录。后续按用户要求下架水果专用组合模板，原组 CX-G06 仍保留在原库目录。

「水果介绍与图文清单」加入 CX-G06。原生固定中英标题、圆形头图、三行胶囊、原字体和逐帧入场轨迹保留。头图绑定本期项目独立原件，至少 1006×814，三行分别使用不同的水果配图。编排要求在第一项之前说出水果主题，各行按实录顺序绑定名称、说明及图片。说明文字保持原单行容量，主字幕继续使用整片时钟。水果清单按原生全屏构图显示，期间连续播放原声。

使用本地合成的 30.467 秒中文测试口播验证网页的音频识别与校对对齐。首轮基础字幕任务 `b7630859-3d07-403f-a196-42781b73a373` 将原片在第 15、30 秒分段，最后一段约 0.47 秒，低于原组件的 0.5 秒最短时长。网站将这类末段的起点前移半秒，从前一段借出画面时间，原片和口播时间轴连续。原任务重试成功，网站输出完整解码且与原片时长一致。补充了整 15 秒倍数、短尾和 0.5 秒临界值三类回归。

网页校对对齐任务 `2b2608d4-2246-4aa1-b3b4-1094fb124193` 返回 64 个实测词。准备请求对比三张小图与四张图两种选法，只有加入尺寸合格的水果头图后才有完整素材。拒绝的编排包括先于实际主题使用清单、重复头图、选过小头图、互换两项说明和移动入场词点。旧「竖横分屏与同期人物」冻结请求摘要复算一致。原包 1426 项完整性通过，132 组继续登记，28 套模板可自动编排 111 组。

首次本地受控规划为另一组字幕 BG-S02 指定了整句，超出原生四字槽，被网页提交预检拦截。修订候选用实录「记住名字」，完整句子继续在主字幕播放。定稿任务 `3f08c200-12dc-4eb1-aed4-e21cfbabebe2` 由独立 worker 一次完成，含 5 种动效、9 条原库提示音和一条原库背景乐。Chrome 手机宽度实播 360×640 代理，确认后实播和下载 540×960 成片，两份媒体支持 HTTP 206。高清路径为 `C:/tl/fruit-introduction-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `db07d21b403ce7b4b0a86016e919f344d45b94b84185208d0f93f70814654316`。

原生组件的 339 帧完整解码。三行首次可见及对应提示音均在零基成片第 94、187、282 帧。独立回读核对四张图片摘要及原生裁切，成片主字幕与原生文字的最小距离为 18 像素。退出点恢复当前原片。用源音轨末尾补静音至视频长度的对照，整片原声分轨波形差为 -144.91 dBFS。有词区间背景乐低于原声 22.15 dB。浏览器回执、抽帧和媒体证据在试片目录。272 项视频、文稿、原库回归通过，另有 52 项适配复跑，Ruff、目标 mypy、前端类型、目标 ESLint 及差异检查通过。本轮为本地合成口播和受控规划的链路验证，真人水果口播、真实模型选组与用户整片视听待验收。无新增付费调用、迁移或部署。

## 撤下水果专用模板

CX-G06 的原引擎将「水果介绍」与英文标题直接写在绘制入口，素材槽可以换图和文字，标题固定。按用户要求从网站模板列表下架 `fruit-introduction-v1`，避免把主题专用动效当成通用模板。原库详情仍可查到 CX-G06。新建规划、从旧准备记录提交新规划、从未出片的旧候选提交预览均返回 409。已出片的历史任务仍关联原下载文件，摘要一致且范围请求返回 206。保留冻结合同和联调记录便于核对。

## 原生同期人物与三图卡

「同期人物与原生三图卡」加入 HY-A2 和 HY-A3。HY-A2 使用原生斜卡、独立底图和原抠像模型产生的同期前景，沿用原字体与入场参数。中文标题取实录一至三字，原可选英文留空。HY-A3 使用原 schema 的三图下落变体，模糊背景与人物窗口均使用同一同期原片，图卡使用独立项目图片。三项关系、素材和动作逐项绑定实录词点。网站继续限制 Hypit 在已配置的内部开发工作区执行，并检查原素材、字体、抠像与本地运行依赖。

两条首轮在完整编码后被网站成片校验拦截。原 Hypit Build 回执提供摘要和解码状态，网站组合验证还要求帧数与帧率。适配层在保留原回执的同时实测视频帧数、分辨率和帧率，并用严格解码核对成片段。两个原任务随后重试。编排检查也拒绝了颠倒条目、错移首词、重复配图及用图片替代同期人物。原水果历史规划请求摘要复算一致，原包 1426 项完整性通过，132 组继续登记。水果模板下架并加入本轮两组后，28 套模板可自动编排 112 个不同的原生组。

规格三图任务 `4f675517-8adf-4786-a1af-76612e220d93` 验证本期「1000克」「两大瓶」「4斤」三个图槽。瓶形图用于解释数量，数值来自实录。原生组件完整解码 197 帧，三卡的首个可见帧与提示音分别在零基成片第 423、507、547 帧。同期人物的独立取帧对照误差为 1.77 至 2.62，冻结首帧对照为 7.37 至 11.64。主字幕通过原生墨迹读区检查。整片 48.475 秒，含 11 种动效、20 条原库提示音和一条背景乐。Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，均支持 HTTP 206。高清路径为 `C:/tl/hypit-picture-automatic-20261110/website-unified-compare-hd.mp4`，SHA256 为 `b659a0e8bf73f649912efd31e2dc3c0280e793eff3108c068e4a97886b17232d`。

斜卡第一版的三字标签「洗水果」部分进入人物轮廓。该版随后将第三张斜卡的标题限制为两字，从对应实录取「水果」，在所选首词触发入场，主字幕继续显示完整「洗水果」。该版采用原生右下人物位置、卡片位置及动画。

修订斜卡任务 `528812c2-6099-4e83-8281-df03e3a45a32` 一次完成。三张用途图的提示音与首个可见帧同在零基成片第 1194、1206、1230 帧，原生组件 120 帧完整解码。独立检验了首尾前景 alpha 及七处同期人物画面。第三张标题在人物左侧完整显示。48.475 秒整片含 11 种动效、16 条提示音及一条原库背景乐。Chrome 实播代理和高清、确认并下载，范围请求返回 206。高清位于 `C:/tl/hypit-picture-automatic-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `9c12738164083147e08ff2464bb01d96ccb6d9bc82834e30bc0f1628c991786e`。

两片的原声分轨相对独立解码实录的波形差为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB。原生运行分别使用 5 项和 7 项本地请求，均为 0 项远程供应商请求。修订斜卡的首次进程关停超时，针对同一任务运行环境重试后状态确认为已停止。网站对关停超时增加一次同任务重试。274 项相关回归、最终 62 项适配复跑、最后 13 项 Hypit 与关停复跑，以及 Ruff、目标 mypy、前端类型和目标 ESLint 通过。两条均为真实口播与本地受控规划，真实模型选组、用户整片观感和听感仍待验收。本轮无新增付费调用、数据库迁移或部署。

## 原生双行三卡进入网站自动编排

「三项说明与同期口播」纳入 HY-A6 的双行三卡。每张卡分别绑定本期项目图片、实录标题和说明，说明首词触发原生缩放。标题和说明各至多六字，主字幕承载完整口播。保留原生字体、右对齐、缩放锚点和不同入场长度，使用已经验证过的任务字号配置及全幅同期底板。三个原图片槽的播放顺序仍为 mka6c3、mka6c2、mka6c1。三图及说明可用于不同口播主题，槽位不预置商品名、报价或标题。

编排拒绝条目颠倒、误把标题首词当入场点、图片重复、静态图替代口播底板、标题超过原生容量。准备请求显示三张独立项目图片的要求。Hypit 仍在已配置的内部开发工作区运行，需无内嵌字幕的口播源。旧「同期人物与原生三图卡」冻结请求摘要复算一致。原包 1426 项完整性通过，132 组继续登记，29 套模板可自动编排 113 个不同的原生组。

本机网站任务 `18c5b82b-6ecf-41d1-9f51-0e7cb6adb15f` 使用受控规划。首次原生渲染在 Chrome `Page.captureScreenshot` 失败，同一任务由网页提交重试后成功。原生组件完整解码 312 帧，三张本期配图与「链接／14块9」「每瓶／1000克」「两大瓶／4斤」在任务实例逐项回读匹配。提示音与首个可见画面同在零基成片第 301、441、546 帧。五处成片面部在相同坐标比对原片和冻结首帧，结果与同期原片吻合在一帧以内。主字幕与动效文字最小距离 25 像素。

Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，范围请求为 HTTP 206。48.475 秒成片包含 10 种动效、18 条提示音和一条背景乐，原声分轨与实录的波形差为 -143.34 dBFS。高清位于 `C:/tl/hypit-detail-cards-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `effa11fff538f78849705f6e1bc3aff3f8ff396fa791ef7f5367d6e184928777`。同目录保存媒体和浏览器回执。277 项相关回归通过。本轮无新增付费调用，真实模型选组和用户视听仍待验收。

## 斜卡保持原片人物构图

用户在旧斜卡成片 39 秒处发现人物变形。旧适配先将原片等比缩放至 510×906，再拉至 598×906，导致人物比等比小窗横向宽约 17%。网站自动斜卡改用整幅同尺寸的透明人物轨，沿用原片位置、尺寸和比例，人物可以挡住原生卡片。三张卡的动画、实录首词和提示音继续使用原时间轴，主字幕保留完整口播。去掉第三张卡独有的两字限制，统一使用原有的一至三字标题容量。保留原始右下小窗布局的工程用法也改用透明边距等比适配。原库文件保持原样。

本机网站任务 `70f1f156-2887-4a42-854a-23904928ff69` 从同一条真实口播一次完成。39.110 至 43.110 秒原生段完整解码 120 帧，人物透明轨为 720×1280，原生画布定位为 `[0, 0, 1080, 1920]`。独立对照七处同期原片及冻结首帧，七处成片人物都更接近原片同期画面。三张卡入场和提示音仍在零基成片第 1194、1206、1230 帧同步出现。人物遮挡部分卡片文字，主字幕仍清楚可见。原声分轨波形相对原片差为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB。

Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，范围请求为 HTTP 206。新片 48.475 秒，含 11 种动效、16 条提示音及一条背景乐。文件为 `C:/tl/hypit-a2-natural-20261110/website-unified-presenter-hd.mp4`，SHA256 为 `52e4bbfa717d20fd75760e6e9dd9fe9ba23e4aee7a69d82bbde50576ee0d25fa`。同目录保留抽帧及媒体回执。旧下载文件摘要复算一致。127 项相关回归、Ruff、目标 mypy 及差异检查通过。此次沿用本地受控规划，用户视听验收仍待完成。

对用户指出的旧下载文件 `C:/tl/hypit-picture-automatic-20261110/website-unified-presenter-hd.mp4` 再核对。用实录人脸特征在原片、旧下载与修正版中同时间取帧。38.80 秒进场前两版均与原片尺度一致。39.43、40.40、42.00 秒旧片人物约为原片 55.3% 至 55.4% 宽、47.2% 至 47.4% 高。修正版三个时刻的宽高倍率都在 1.000 附近，坐标偏移不超过 2.1 像素。证据为修正版同目录的 `presenter-geometry-39s.json` 和 `presenter-geometry-39s.png`。

## 原生人物标签进入自动编排

「人物身上标签与口播重点」将 HY-A4 的三个原生标签按各自首词绑定到本期实录。沿用原坐标、滑入、底片、刻度和思源宋体 86 像素字号。背景替换为同尺寸的同期口播，主字幕保留在下方。与 HY-A5 的斜切条分开配置，保留已有模板的词点规则。HY-A4 只允许配置正确的全幅同期底板，已绑定的原片需无内嵌字幕，且工作区需有可用的本地 Hypit 运行环境。

受控计划在真实口播中两次选择 HY-A4，分别绑定「看看／下面／链接」和「洗碗／刷锅／洗水果」。首次网页提交由全幅动效白名单拦下。修正后任务 `754f0b0c-aaaf-4c8f-a3fd-6db4cee956b3` 成功入队，worker 第一次在编译阶段记录本机 `OSError`。同一冻结计划与原片在独立编译目录复跑成功，原任务经网页重试成功出片。原包 1426 项完整性复核通过，全部 132 组继续登记，30 套模板当前可选择 114 个不同原生组。

两次 HY-A4 原生段分别解码 114 帧和 120 帧。成片在零基第 264、275、289、1194、1206、1224 帧各出现一个新标签，六条相应提示音与首次可见帧对点。八处人物面部在相同坐标比对同期底板，平均像素误差为 2.24 至 2.42，冻结首帧对照为 9.12 至 19.89。整片有 10 种动效、11 次出现、15 条提示音和一条背景乐。原声分轨波形相对实录差为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB。

Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，范围请求为 HTTP 206。高清 48.475 秒，文件为 `C:/tl/hypit-presenter-labels-20261110/website-presenter-labels-hd.mp4`，SHA256 为 `4a462c010bd4390fe4f5e03d558ff9c0db77442c224a6bdfb1bf0491329a9155`。同目录保留浏览器及媒体证据。为保留斜卡旧规划，模板核对兼容原斜卡说明文字的精确快照，其他绑定字段仍严格核对。四份旧规划请求的 SHA256 实际重算一致。278 项相关回归及最终 5 项模板复验、Ruff、目标 mypy、前端类型和 ESLint 通过。试片使用本地受控规划，真实模型选组和用户整片视听仍待验收。

## 原生章节导航进入自动编排

「章节导航与口播重点」把 Z-M15 的序词、中文章名、原散字动画和同期原片虚化接入网站。章节模板的规划合同增加 `chapter_start_token_ids`，每章和提纲项按顺序对应，起点必须是已对齐的编排段首。没有选择章节动效的章也计入顺序。Z-M15 只在章首选用，编译器从章次生成 First 至 Tenth，中文章名取实录词段。序词和章名分别使用原生淡入与散字，序词让位的位移由另一个实录词触发。连续原声与底部主字幕沿用整片时钟。旧模板请求结构和四份已冻结的 Hypit 规划请求摘要复算一致。

在真实口播上用本地受控响应运行任务 `a8f90ec9-e049-4d82-8e7f-1317a98f1217`，一次出片。四个实录章起点推导出 Fourth，中文章名为「洗碗刷锅」。Z-M15 从 39.110 秒起输出 120 帧。五处背景在同位置与同期原片虚化对照，平均像素误差为 1.15 至 1.17，均低于冻结首帧对照。序词和中文章名首个可见帧分别为零基成片第 1174、1193 帧，两条提示音对点。主字幕距本段限制带至少 27 像素，原声分轨相对实录的波形差为 -143.34 dBFS，发声时背景乐低于口播 10.43 dB。

Chrome 实播代理及 720×1280 高清，确认和下载通过，范围请求为 HTTP 206。成片 48.475 秒，含 11 种动效、15 条提示音和一条背景乐。高清为 `C:/tl/unified-chapter-20261110/website-chapter-hd.mp4`，SHA256 为 `23a288bc4b38208683b5a2dbf56ab49773336b49ea2f990e11960dcd312ac1a4`。同目录保留浏览器回执、媒体核对及六种被拒绝的编排输入。

280 项相关回归、Ruff、目标 mypy 和原包 1426 项完整性复核通过。OpenAPI 与 TypeScript 类型按新增字段重新生成。原库 132 组继续完整登记，31 套网站模板可编排 115 个不同原生组。本轮没有新增付费调用或部署，真实模型的章节划分和用户整片视听仍待验收。

## 原生问号接力进入自动编排

「问号接力与口播重点」把 W-R17 的两个道具、原生弧排短问词和虚化退场接到网站。两个道具分别选用本期已登记的 540×960 透明 PNG，网页预检文件格式、画布、透明像素及不同摘要。问句使用同期原片及原 Arial，编译器从实际说出的短问词映射至原槽可容纳的英文。两个问号、英文与退场各使用自己的实录词点。完整问句由整片主字幕承载，保留原叠放与画面比例。原库内的道具引用和方法完整保留，试片使用两张单独登记的本期示意道具。

零张及一张合格道具时网页均明确将此槽标为不可选，两张合格原件后恢复。预检实测拒绝不透明、尺寸错误及重复字节。编排拒绝同图占两个道具位、问词错绑和提前虚化。首次网站任务 `a3f5fce4-edb7-4d83-bcc6-220aae08a39e` 把独立问号当并列内容图卡，编译被图卡关系门槛拒绝。修正载体类型后使用原口播与同一对道具重新提交，网站任务 `d82f4a7f-72d8-4715-8aff-77587eda69b8` 一次完成。旧章节模板和四份 Hypit 规划请求摘要重算一致。

原生段完整解码 107 帧。两个问号、Who? 和虚化的画面变化及提示音分别在零基成片第 147、151、156、217 帧同步出现。虚化前七处嘴部对照的同期原片误差为 1.99 至 2.24，冻结首帧误差为 14.25 至 31.73。整片 48.475 秒，含 11 种动效、21 条原库提示音和一条背景乐。原声分轨对照误差为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB，主字幕在验证读区内。

Chrome 实播 360×640 代理，确认后实播并下载 720×1280 高清，范围请求为 HTTP 206。高清为 `C:/tl/unified-question-relay-20261110/website-question-relay-hd.mp4`，SHA256 为 `945e6210f872a223e8ab26d10ce454fe07513be48b7814d8827b291a1d7a4412`。同目录保存预检、浏览器、媒体回执及抽帧。280 项相关回归、Ruff、目标 mypy、前端类型和目标 ESLint 通过。原包 1426 项完整性复核通过，全部 132 组继续登记，32 套模板可自动编排 116 个不同原生组。使用本地受控规划，真实模型选组及用户整片视听仍待验收。

## 原生双语换字进入自动编排

「双语换字与口播重点」把 W-R02 的两字替换接入自动编排。中文前后词与两条完整短句分别绑定对应实录关系，后项两个字各用实测词首触发。英文使用独立短译字段，编译核对短译与已保存规划一致，页面显示待核对。当前试片采用「每瓶／到手」和「PER BOTTLE／TOTAL」，用原生字幕分别保留「每瓶都是1000克」与「两大瓶到手足足4斤」。沿用该组的同期等比例人物窗及原生换字，主字幕放在原生释义下方。短译重复、错绑词点、短句跨项、缩短后项和编译短译与规划不符均已实测拒绝。

首轮任务 `35f1b7f5-09f6-4a13-b0eb-d8b941466b17` 因双行主字幕的墨迹进入版面限制区 5 像素被拦截。只调整 W-R02 段主字幕基线后，任务 `71e16ffe-bb37-461d-8b73-502eff8510e6` 通过原生版面校验，主字幕墨迹在该区内至少留出 4 像素。W-R02 完整解码 196 帧，所抽四处人物画面按原生等比窗口对照同期原片的平均误差为 2.64 至 3.59，冻结首帧对照为 10.67 至 14.60。字词入场和两次替换与原库提示音分别在零基成片第 422、522、530 帧同步出现。整片 48.475 秒，含 11 种动效、20 条提示音和一条背景乐。原声分轨对照误差为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB。

Chrome 实播 360×640 代理及 720×1280 高清，确认后下载，范围请求返回 HTTP 206。高清文件为 `C:/tl/unified-bilingual-swap-20261110/website-bilingual-swap-hd.mp4`，SHA256 为 `382e71aaf026ff869206207c46c038bde23f7e90ff8539b88c2e337c8edf21f5`。同目录保留浏览器回执、媒体核对、入场前后抽帧和拒绝证据。280 项相关回归、Ruff、目标 mypy、前端类型与目标 ESLint 通过，OpenAPI 与前端类型与重生成件一致。六份旧规划请求摘要复算一致，原包 1426 项完整性复核通过。132 组继续登记，33 套模板可自动编排 117 个原生组。本轮沿用本地受控规划，真实模型输出、短译及用户整片视听待验收。

## 原生方格纸逐字说明进入自动编排

「方格纸逐字说明」接入 Z-M11 的两行标签、逐字正文和原生人物描边。两行各自绑定实录词段，标签由各自首词触发，正文字符使用所属实测词点。本期「1000」的四个数字共用同一词点，「克」和「4斤」保留各自测得的时点。使用原抠像模型从同段口播制作 30 fps 透明序列，按原生 `frame_sequence` 槽逐帧播放。人物在原生纸面中等比例排版，整片原声与主字幕连续。网页会提示可用原抠像模型和无内嵌字幕的源片要求。缺模型、错用其他原片、交换两行及移离标签词点均已实测拒绝。

首次网页任务 `86c7c563-fe44-45c9-a933-86098972f3d3` 已产出完整透明序列。原出片检查的素材审计只接收文件，拒绝了渲染器支持的目录槽。适配层逐帧核对摘要后，把序列索引作为原生素材交给该审计。原生出片和绘制仍消费原序列目录。原校验代码和纸面绘制保持原样。独立原生组件完整解码 196 帧，六个抽查点的透明帧与同一时刻的原片像素匹配。

同一任务从网页重试后出片。24 fps 原片的 157 个不同源帧映射到 196 帧原生透明序列，重复位置与采样时钟一致。六处成片人物与对应序列按原生几何对照，平均像素误差为 3.01 至 3.15。两个标签与提示音分别在零基成片第 422、522 帧同步出现，正文六个实测出现时点逐一核对。主字幕与本段读区边界至少相距 25 像素。整片 48.475 秒，含 11 种动效、19 条提示音和一条背景乐。原声分轨对照误差为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB。

Chrome 实播 360×640 代理，确认后实播及下载 720×1280 高清，范围请求返回 HTTP 206。高清文件为 `C:/tl/unified-paper-typewriter-20261110/website-paper-typewriter-hd.mp4`，SHA256 为 `56074f23c973082c7764647c8820cd9987ef2353eba29165bd6cecbeb4540626`。同目录保留浏览器回执、媒体核对和原生画面。281 项相关回归、Ruff、目标 mypy、前端类型和目标 ESLint 通过。七份旧冻结规划请求摘要复算一致，原包 1426 项完整性复核通过。132 组继续登记，34 套模板可自动编排 118 个原生组。本轮使用本地受控规划，真实模型选组及用户整片视听待验收。原版式白色正文叠浅底，手机端的阅读观感仍待核对。

## 原生纸面章节与同期人物分身进入自动编排

「同期人物与原生章节」纳入 Z-M05 和 Z-M17。Z-M05 从实录章起点推导英文序词，章名和两条引用保留本期原话，并分别绑定首词。退场留足第二条原话及原生收缩动画的阅读时间。Z-M17 从同一实录帧分别提交原画与透明遮罩，原引擎保留全幅底板，再在同期人物旁绘制错位描边，两个重点短语及原生短字幕取实录。两组沿用相同的原素材审计，并固定各自取帧和绘制入口的文件摘要。旧 Z-M11 的原素材索引在新适配层复查一致。

编排实测拒绝缺失章起点、过早退场、分身与第一短语错绑、短字幕末词错绑、错用其他原片和缺少原抠像模型。旧章节模板及其余七份冻结规划请求摘要复算一致。原包 1426 项完整性通过，132 组继续登记，35 套网站模板可自动编排 120 个原生组。

真实口播任务 `9b206fb4-da8e-4776-85b6-611fbd78c89e` 一次完成。Z-M05 以章单的第三章显示 Third，并呈现「每瓶」「1000克两斤」「到手足足4斤」。本段原生组件完整解码 196 帧，六处成片人物与同期原片按原生几何对照的平均像素误差为 3.11 至 3.40。Z-M17 完整解码 138 帧，六处同坐标面部与原片对照误差为 2.68 至 3.07。描边入场首帧以原生无损画面的空间位置核对压缩后高清，确认与提示音同帧。两组七处提示音分别对应零基成片第 376、441、522、559、669、691、731 帧。两段主字幕墨迹在各自验证读区内至少留出 25 和 22 像素。

Chrome 实播 360×640 代理，确认后实播及下载 720×1280 高清，范围请求为 HTTP 206。成片 48.475 秒，含 11 种动效、22 条原库提示音和一条背景乐。原声分轨相对原片的波形误差为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB。高清文件为 `C:/tl/unified-live-chapters-20261110/website-live-chapters-hd.mp4`，SHA256 为 `2677a15b5dae7c42551325cb6dfcd6a1673072a89d9cd82efcff7ff4b288c80c`。同目录保留浏览器及媒体回执、抽帧和拒绝证据。281 项相关回归和最终 71 项专项复验、Ruff、目标 mypy、前端类型和目标 ESLint 通过。使用本地受控规划，真实模型选组与用户视听仍待验收。

## 原景剪影群像进入自动编排

「原景剪影群像」接入 W-R09 的承接画面退场、原生滑入标题和七个装饰剪影。网页按原生槽核对一张 540×960 不透明承接图及七张对应尺寸的透明 PNG。准备任务实测空选和只选七个可用素材时均停用该槽，八个槽配齐后恢复。编排拒绝把同一素材放入两个槽、错放尺寸、用不透明图片充当剪影、用同一个实录词触发两个剪影或重新启用原历史窄裁切。自动编排使用完整同期底板，保留原生短暂横向模糊、遮挡与剪影位置。

原生虚拟时钟逐段映射实测词点，视觉仍按原引擎绘制。短标题首帧可能停留在屏幕外，适配层用原字体的实际字形计算首个可见入画帧。实测「洗洁精」「省」「好物」「111」首个可见原生帧分别为 10、12、11、11。纸面退场、标题和群像入场提示音在试片零基第 661、669、674 帧与画面变化对齐。群像只配一次过程声。初始承接图取紧邻前段原景，约 0.4 秒后开始退场。七张装饰剪影取同一口播者的抠像轮廓，作为链路示例。

任务 `f659d1ad-dbb0-4dec-9ffc-2a0a10a528e8` 一次完成，W-R09 完整解码 138 帧。六处同期原片与成片同位置人脸对照平均像素误差为 2.82 至 3.05，后五处冻结首帧对照为 10.45 至 22.51。七张剪影在各自位置逐项回读，成片可见区与对应素材的像素平均误差为 2.58 至 3.04。主字幕在验证读区内至少留出 25 像素。整片 48.475 秒，含 11 种动效、19 条提示音和一条背景乐。原声分轨对照误差为 -143.34 dBFS，有词区间背景乐低于原声 10.43 dB。

Chrome 实播 360×640 代理与 720×1280 高清，确认后下载，范围请求为 HTTP 206。高清文件为 `C:/tl/unified-crowd-20261110/website-crowd-hd.mp4`，SHA256 为 `36f51aea2baa744845c04fccc44f25c94ecd87522a7bbbeacf3ce2678f49adf4`。同目录保留浏览器回执、素材预检、媒体与拒绝证据。282 项相关回归、Ruff、目标 mypy、前端类型及目标 ESLint 通过。九份冻结规划请求摘要复算一致，原包 1426 项完整性复核通过。132 组继续登记，36 套模板可自动编排 121 个原生组。本轮使用本地受控规划，真实模型选组和用户整片视听待验收。

## 原生证据拼贴进入自动编排

「同期口播与证据拼贴」纳入 W-R04。录音波形、透明人物素材、画面截图及播放回执分别绑定本期四段词点，另有七个原生装饰剪影槽。网页显示素材尺寸要求。实际预检选择零张及十张素材时停用 W-R04，十一张对应素材齐备后开放。编译逐项核对图片尺寸、透明通道、独立素材摘要、同期底板来源及各段实录。原生两对共享时点的标签分别在各对的后一个词触发时共同出现。

本期口播通过网站上传、本机 FunASR、校对和重新对齐，得到 61 个词点。第一条候选 `7980fe9e-d80d-43f6-9b5d-6ec4acd8db2d` 在编译时被拦下。独立复核确认原引擎虚拟时钟的逐帧取整会让第四图离词点过远，适配层拒绝差距超过 350 毫秒的候选。另实测拒绝关系错绑、成对标签拆分、图层尺寸错配及其他原片。新候选使用实录中「最后看成片」作为第四图入场点，沿用原生绘制与动画。

网站任务 `12ff6cf8-d820-4b5a-92bc-8e31e5b8be57` 从独立剪辑 worker 出片。W-R04 从 0.23 秒到 9.50 秒，原生段完整解码 279 帧。四图层的首个可见帧与提示音对齐在零基成片第 15、54、121、246 帧，两对标签分别在第 160、272 帧出现。六处同期底板抽帧与原片的平均像素误差为 2.70 至 3.97，冻结首帧对照误差为 51.64 至 65.29。主字幕验证读区至少留出 11 像素。局部画面可见原生标签压在图面上，整片观感待用户验收。

浏览器实播 360×640 代理，确认后实播及下载 540×960 原始分辨率成片，范围请求返回 HTTP 206。21.619 秒含 W-R04、AHG-S02、AH-S08、JJ-S04、AH-S09 五种动效、八条原库提示音及一条背景乐。原声分轨相对输入的波形误差为 -144.26 dBFS，有词区间背景乐低于原声 20.84 dB。成片为 `C:/tl/unified-evidence-collage-20261110/website-evidence-collage-hd.mp4`，SHA256 为 `9549ac9f7c73d991ad7ab85822b34460c95cc281c5df8b5d1d2f23c622b26945`。同目录保存浏览器、编排与媒体回执。

283 项相关回归、Ruff、目标 mypy、前端类型与目标 ESLint 通过。十份历史规划请求摘要复算一致，原包 1426 项完整性复核通过。132 组继续登记，37 套模板可自动编排 122 个原生组。试片使用本机合成测试口播、复用的讲述者画面及受控规划。真人口型、真实模型选组及用户整片视听待验收。

## 多角色插画与流程论证进入自动编排

「多角色插画与流程论证」纳入 W-R15。16 张本期插画分别绑定原图槽与出画时的实录范围。原生画面保留交叉淡化、留屏和连续换图，允许同一句对应数张短暂出现的插画。16 个动作切点使用实录词首，关门、交接、禁行与各自原动作共用词点。三个角色名称、禁行文字和原生短字幕均取实录。网页准备实测零张及十五张时停用 W-R15，十六张齐备后开放。编译拒绝重复素材、插画偏离对应口播、单独挪动交接时点及借用其他段落的角色名。

联调将两段本机合成测试口播合成一个输入，通过网站上传、FunASR 识别、校对和强制对齐得到 114 个词点。沿用旧流程插画的构图，在本期素材中移除「本地流程演示」和「场景素材 · 联调示意」字样，再通过网站登记并回读全部 16 张原图。编排使用受控本地响应。试片全屏插画期间保留同一口播和主字幕，结束后按原时间轴回到同期画面。输入的 22.33 至 22.50 秒拼接处少四个视频帧，原整片引擎转 30 fps 时重复最近输入帧。媒体核对用输入实际时间戳转换后比较，没有按原文件帧号硬对齐。

网站 API 受理任务 `308c9eb3-3463-4983-b1e2-243994371cc7`，独立 worker 一次完成。W-R15 的 0.17 至 21.97 秒原生段解码 654 帧，16 张素材与编译回执逐项核对，16 个成片抽帧与原生绘制的平均像素误差为 1.60 至 3.39。关门、交接、禁行选用原组对应的三条音效，首个可见变化在零基成片第 180、222、572 帧，起音与其相差不超过 1 毫秒。主字幕验证读区至少留出 11 像素。回到原片后的六处画面与输入同期的平均像素误差为 0.54 至 1.27。原声分轨相对输入的波形误差为 -144.12 dBFS，有词区间背景乐低于原声 21.05 dB。

浏览器实播 360×640 代理，确认后实播和下载 540×960 原分辨率成片，范围请求返回 HTTP 206。34.612 秒整片含 W-R15、AHG-S02、AH-S08、JJ-S04、AH-S09 五种动效、七条原库音效和一条背景乐。成片 `C:/tl/unified-role-chain-20261110/website-role-chain-master.mp4`，SHA256 为 `3cb8f28e9746e0a0a19d13693fd733f2f155fc4a0a7f6bd20a8a6fcac27a799d`。浏览器、媒体、编排拒绝证据及抽帧同目录。

251 项剪辑与原库回归、最终 83 项相关复验、Ruff、目标 mypy、前端类型和目标 ESLint 通过。原包 1426 项完整性通过，132 组继续登记，38 套模板可自动编排 123 个原生组。

用户否决上述试片，已从用户验收范围撤回。该任务保留为内部 W-R15 渲染和音画时间轴证据。合成流程说明与复用人物画面不对应，且开场近 22 秒连续使用测试插画。用户验收片从同一条真实口播的画面、原声和实录词点生成，按口播内容选组，测试插画及合成重配的链路样本单独存放。W-R15 仍在原库保留，等待与完整多角色叙事及对应素材匹配的真实样本。

## HY-A2 右下角人物窗等比合成

用户确认原模板的右下角人物位置正确，需要修正人物宽高比例。网站自动编排恢复原生右下窗口 `[483, 1014, 597, 906]`，将同期透明人物等比放入窗口，横向剩余空间透明。卡片与人物的原生层级和遮挡保留。此规则接替此前的全幅前景修订。两版旧模板快照仍能按各自冻结合同核对，已完成文件可追溯。

使用同一条清洁用品口播原画、原声、实录词点及已有三张用途图重新提交任务 `df2f9a7a-1a99-4b64-b0a5-46d88524d1e6`。人物轨从 39.110 秒读取同期原片，原生组件完整解码 120 帧。39.43、40.40、42.00 秒的宽高缩放约为原片的 47%，三次宽高倍率差均小于 1%。39 秒前和回切后均按原片全幅显示。三张斜卡的提示音与首个可见帧仍对应零基成片第 1194、1206、1230 帧。原声分轨对比原片音轨误差为 -143.34 dBFS。

独立 worker 生成 48.475 秒整片，含 11 种动效、16 条原库提示音和背景乐。Chrome 实播 360×640 代理、确认并下载 720×1280 成片，范围请求返回 HTTP 206。成片 `C:/tl/hypit-a2-template-inset-20261110/website-slant-inset-hd.mp4`，SHA256 为 `d9fd2b799b678151a4c339b2b5d0a7c08005153b8ca3c30d639aa6119f0fe107`。同目录保留 `slant-inset-comparison.png` 和 `inset-evidence.json`。75 项相关回归通过。本期沿用本地受控编排，真实模型选组及用户视听仍待验收。

## HY-A7 流式标签与实录占比进入自动编排

「同期口播与三项占比」使用已校对文字中的明确合计和连续三个分项。目前支持 1 至 999 的中文或阿拉伯整数，三项须同单位且相加等于实录总数。模型绑定现有词 ID 和原生标签、入场及同期底板，编译器读取数量并保存词点、单位、合计和校对版本。未经校对的识别稿、错误单位或合计不符时拒绝使用该组。原 Georgia Italic 的精确绑定及内部 Hypit 运行环境仍需通过预检。已有无数字绑定的经典工程候选继续保留组件范围。

实例副本只为原饼图写入三个权重，保留圆心、半径、颜色、增长时序及三条斜卡的入场、重排和遮挡。数量使用原生副行。第一条斜卡的文字在该副行模式向上移 36 个原生像素，让数量在两张卡的叠层上可读。主字幕在饼图片段使用上方读区。首轮因整片编译误读 Hypit 的时长字段被拦下。第二轮的原生组件完成，整片因上方主字幕超出通用安全区被拦下。复核同一保存任务的字幕读区和图层后重试，第三轮完成网页出片。

内部测试按原库目录复算三类条目，动画类 52、实景 37、字幕 43，共 132 组。对同一测试语音实际识别及重新对齐得到 65 个词点。本机测试项目分别走自动识别稿和开发身份显式校对流程，前者停用 HY-A7，后者可准备并通过编译。独立出片任务 `68a8a005-9591-46af-bb0c-abf1cd5269d1` 中，HY-A7 原生组件完整解码 336 帧。对原生帧和整片分别测量三个扇区边界，最大偏差 1.23 度。六处人物同期同坐标像素误差为 3.13 至 3.33，冻结首帧对照为 6.58 至 17.40。三个标签的首个可见变化及提示音对应零基成片第 101、161、220 帧。主字幕读区至少留出 86 像素。

浏览器实播 360×640 代理与 720×1280 产物，确认后下载，范围请求返回 HTTP 206。26.933 秒整片使用五种动效、七条原库提示音及背景乐。原声分轨相对同一输入的波形误差为 -144.79 dBFS，背景乐在有词区间低 22.26 dB。输入测试语音先于画面结束，片尾约 1.30 秒由原引擎补静音。内部产物、编排、浏览器和媒体证据位于 `C:/tl/hypit-flow-chart-20261110`，下载件 SHA256 为 `188e03ee5c722ad258e04118b80bc5bdda0e1a41ff0247f764f83bbbb87a413f`。该联调使用合成口播、复用画面和本地受控规划，留作内部链路证据。真实业务数据、真实模型选组与用户整片视听待验收。

274 项剪辑、文稿与原库回归、Ruff、目标 mypy、前端类型和目标 ESLint 通过。原包 1426 项完整性复核通过，全部 132 组继续登记，39 套模板可自动编排 124 个原生组。

## W-R01 互动证据登记与编译

网站「本期补充素材」新增互动证据图片入口。每张图登记短标签、实际点赞数、来源链接或记录编号、带时区的观察时间，以及项目所有者的核对确认。迁移 20261110_0050 新增可空字段，登记记录随素材原字节摘要保存。原项目素材和已有创意图继续使用原合同。

规划素材卡提供短标签与登记摘要。编译器从同一项目的三张不同图片读取登记记录，逐项核对图片摘要、短标签、实录词点和原生评论入口，写入原模板的点赞数字。每项的来源、时间、词点和图片摘要留在编译回执。旧工程候选可继续读取原显式证据。两处记录冲突时拒绝编译。

本机迁移使用独立 SQLite 副本，确认 117 条已有素材仍可读取。PostgreSQL 已验证离线 SQL 生成 JSONB 字段。本轮的接口验证覆盖 0 赞、同一请求重放、修改记录后重放、跨项目读取以及时区和核对字段。275 项剪辑、文稿和原库回归通过，Ruff、目标 mypy、前端类型检查和目标 ESLint 通过。

本机从接口重新上传三个历史公开问题摘要图，沿用已实测对齐的合成技术口播和透明人物插画。用新登记素材生成新实例并重新执行原生编译及编码。完整解码 389 帧，显示的 0、1、0 与登记记录一致。三个实录词点落在零基第 197、253、305 帧，原生评论徽记随入场动画在测量区第 200、255、307 帧可见。产物 SHA256 为 102a22459c16847c3aef2e6d2bb23c063a97adbb3d79c9b9148c89df9aa35f8b。内部回执见 `C:/tl/film-evidence-20261110/verification.json`。同期动态人物、自动组合编排和真实项目整片视听待验证。本期目录仍登记 132 组，39 套模板自动编排 124 组。

Chrome 本机实测经「语义规划任务」展开「本期补充素材」，登记 0 赞并刷新回读。更改短标签会撤销已勾选的确认，重新核对后才可保存。接口返回 HTTP 201，时区转换后保留原观察时刻，下载的图与上传文件逐字节一致。浏览器回执见 `C:/tl/film-evidence-20261110/browser-verification.json`。

## W-R01 同期人物与自动组合

「胶片作品带与实录反馈」加入网站组合模板。规划请求只给出当前项目的图、登记短标签及实录词 ID。三张不同图各绑定一项反馈的原话、图片位、评论文字和入场词点，数字由原登记读取。当前采用原统一输入的三个图位，并要求英文槽也有实录英文短词。素材不足或标签缺失时，该组停用，同模板其他动效仍可选。编译再次核对逐项对应、先后顺序、间隔和末项停留时间。

网站适配用原抠像模型读取与实录同钟的原片。逐帧前景等比放入 540×960 画布后交给原胶片引擎。原胶片轨迹、评论进场和人物前后层级沿用原包，主字幕在原生短字幕下方。三条提示音从原评论各自的首个动作帧进入，原声与背景乐沿用整片时间轴。

在独立本机项目使用拼接的合成技术口播及复用人物画面。首轮因 FunASR 尾词时点超出媒体容差被拒绝。第二轮因试验封装的画面时长小于音轨被原引擎拒绝。修正输入文件后，网站完成实际识别和校对稿对齐，得到 61 个词点。准备任务选 0 张或 2 张证据图均停用 W-R01，3 张与词点匹配时启用。记录中的数字 0、1、0 进入原配置，来源及原图摘要可逐项复核。模型协议由本地受控响应验证。

独立出片任务 `2f4aafeb-6018-42ec-a7d8-a3da39b27897` 完成 26.933 秒整片，含 W-R01、AHG-S02、AH-S08、JJ-S04 和 AH-S09。W-R01 原生组件解码 441 帧，对应输入 0.170–14.870 秒。对比七帧，除用作冻结参照的一帧外，其余六帧与同期前景的 RGB 平均误差为 1.88–2.09，与冻结参照的误差为 7.31–13.40。抽查看到人物按原图层遮挡部分评论卡。本次画面用于验证同期层、原生轨迹和顺序，业务选材与视听验收仍待真实项目验证。

三个原生评论音效对应零基成片第 215、270、325 帧，整片共七条原库音效和一条背景乐。原声分轨相对输入误差为 -144.54 dBFS，解码成片与三轨混音的相对误差为 -37.86 dB。Chrome 实播 360×640 代理和 720×1280 高清，确认并下载，范围请求返回 HTTP 206。成片 SHA256 为 `dd052f7b175769e96c941610e1a934636a6cbd6d60debd0438f734fa7604c5d8`。本机证据见 `C:/tl/film-live-20261110/media-verification.json` 和 `C:/tl/film-live-20261110/browser-verification.json`。

276 项剪辑、文稿和原库回归通过。目标 Python 类型、格式和规则检查、前端类型和目标 ESLint 通过。原包 1426 项完整性复核通过。132 组继续登记，40 套组合模板覆盖 125 个可自动编排的原生组。

## PostgreSQL 反馈迁移与冻结规划重放

在本机独立 PostgreSQL 18.4 中实跑 `0049 → 0050 → 0049 → 0050`。实际新增字段为可空 JSONB。旧确认稿和旧图片的身份、摘要、字节及 API 回读保持一致。相同请求的两次并发上传均返回 201 和同一记录。以相同请求编号并发提交两个不同点赞数，只有一条创建成功，另一条返回 409。数据库确认 0 赞保存为 JSON 数值。

实际 HTTP API、Redis 8.8.0、维护进程和两个独立 Celery worker 共用该数据库。本机首次识别、对齐和规划准备均完成。生成尝试在调用网关前报告 `EDITING_PLAN_INPUT_CHANGED`。诊断复算确认 PostgreSQL JSONB 重排嵌套键，原摘要把内部 JSON 当作字符串，故仅顺序不同也会失败。

生成前先核对冻结产物的路径、长度与摘要，再比较重建请求及冻结请求的结构化内容。仅 JSON 对象键序不同可沿用冻结请求原内容和摘要。内容变化、文件摘要变化、网关变化及已有提交记录仍按原保护规则处理。修复后在同一数据库和原规划任务通过正常重试，发送文件与原冻结件逐字节一致。本机回环 HTTPS 测试网关收到一次请求。

当前 132 组中，Z-M00 是已经运行的原生基础轨，CX-G06 按用户要求从组合模板撤下并保留目录。其余 5 组仍受原件或授权约束。CX-G05 的原引擎直接绘制 69 张缺失的背景帧，并依赖 69 张透明人物帧和三张原照片。CX-G08、CX-G09、CX-G10 的共用入口仍缺 `chaocu.ttf`、`zhixiang.ttf`、三张原素材、66 张 G09 底板及 G10 的背景和人物两张原图。HY-A1 登记字体为原俊雅体非商用版，项目使用权限及字节仍待核对。AH-S03 的 A 版可用，B 版原 Aa 研宋独立待核对。两个原 ZIP 均重新核对 SHA256。

修复后的规划任务 `2c12e7f3-031f-49cb-b2da-17bc29c98b4c` 和剪辑任务 `b049a9e2-5174-4638-b904-3fc807a804ae` 通过独立 Redis 队列完成。分别向两个队列重复投递同任务消息，两个重复消息均被消费。网关仍仅一次调用，剪辑仅一条完成尝试。新编码的 26.933 秒整片含五种原生动效、441 帧 W-R01 同期前景、七条原库提示音和一条背景乐。原生配置里的三个登记值为 0、1、0。全量音视频解码、代理及高清范围读取、确认和下载摘要核对通过。新高清 SHA256 与上一轮同输入的本机试片一致，为 `dd052f7b175769e96c941610e1a934636a6cbd6d60debd0438f734fa7604c5d8`。

278 项剪辑、文稿和原库回归及目标 Ruff、mypy 通过。迁移和运行证据分别见 `C:/tl/film-postgres-20261110/migration.json` 与 `C:/tl/film-postgres-20261110/integration-evidence.json`。本轮使用合成技术轨、复用人物画面及本地受控 HTTPS 响应。真实模型选组、实际业务素材和用户视听验收仍待完成。

## 音画尾部时钟与原声保护

网站预处理分开记录容器、实际画面和识别音频的末尾。容器尾部超出已探测画面的时间大于一帧加 1 毫秒时，最多处理 0.5 秒的短尾。逐声道解码画面截止后的样本，峰值在 PCM16 的 4 个量化单位以内时，按有画面的末尾编译整片。识别 WAV 仍从原音轨全长提取，保留原片和分析音频摘要。尾部存在有效信号或超出范围时，在准备阶段提示核对原片。无独立视频时长记录的容器沿用原时钟处理。

词点必须从有画面的时间内开始。只有已核验的静音尾部允许在完整识别音频范围内收束词尾，并记录调整原因。缓存转录同时检查片长，避免在改变渲染边界后复用旧词点。原库继续按真实图像和实录时间渲染。下载验收回执附片尾探测值。

正例使用上一轮被原引擎以素材片段越界拒绝的同一个文件。容器及识别音轨为 26.720 秒，画面为 26.633 秒，截止后的 1,919 个解码采样帧峰值为 0。负例为同画面下含反相双声道尾音的文件。单声道平均峰值约 98.5，逐声道峰值 12,233。网站任务 `730e4c00-40f8-410b-92a3-21c549ca6ba7` 在准备阶段返回 `EDITING_SOURCE_AUDIO_TAIL_REVIEW_REQUIRED`，并核对识别文件与交付产物尚未生成。

正例通过实际识别、校对稿对齐、独立剪辑 worker、原生渲染、预览、确认及高清下载。任务 `12348447-2b9e-490d-8b27-dffbdc84e608` 的成片为 26.633 秒，保留 799 个画面帧，含五种原生动效、七处提示音及一条背景乐。原声分轨与解码基准的误差为 -144.52 dBFS，识别 WAV 与上一轮失败任务逐字节一致。代理与成片的范围请求均返回 HTTP 206。成片摘要为 `7e21520af32e8085ddba5643a4cd295e9cc876cb92999b37574f91de03ff8ca2`。详细证据见 `C:/tl/source-tail-20261110/source-tail-verification.json`。283 项相关回归、目标 Python 静态检查及前端类型检查通过。正例使用合成测试音轨与受控规划回复，用于核对链路、时钟及人物前景，业务模型语义和用户视听验收仍待进行。

## Paraformer 末词超出识别音频的处理

源片准备回执从分析 WAV 的实际采样数记录结束时钟。FunASR 的固定 Paraformer 模型将六个 10 毫秒步长堆叠为一帧，尾部可能包含填充。末词结束点在音频后超过原有 30 毫秒容差、且仍在一帧 60 毫秒内时，须核对词首在真实音画范围内，随后收束到实际音频与可用画面中较早的边界。原始识别结果及词首保持原样，转录记录模型末词时间、分析音频结束点、实际采用的结束点和原因。中间词、超出一帧的末词和缺少实际采样时钟的旧输入沿用严格校验。强制对齐与 Faster Whisper 沿用各自既有边界。

使用此前失败的同一个输入重新提交网站任务。原画 791 帧，画面结束为 26.366667 秒，分析 WAV 为 26.480 秒，画面截止后的解码尾部峰值为 PCM16 的 4 个单位。任务 `0debe7a6-a7a2-487c-8396-f5fce2e1122f` 的识别 WAV 和 FunASR 原始结果均与上次失败任务逐字节一致。适配层将最后一字的结束点从 26.519 秒收束到 26.366 秒，随后完成校对稿强制对齐任务 `b570f01c-199f-42f6-83df-5b9dc8224249`。

独立剪辑任务 `a2fb5c09-6120-45bc-9e7c-1cd4c6e49acd` 完成原生渲染、校验、代理预览、确认和高清下载。下载片保留 791 帧、30 fps 和 26.366667 秒的画面，含五种原生动效、七处提示音和一条背景乐。原声分轨与独立解码原声的波形误差为 -144.45 dBFS。代理和高清范围请求均返回 HTTP 206，下载片 SHA256 为 `e9601727f33548dca043f8fbfd8af4b73089d8a28c131aaf900ef0364824c1b0`。证据见 `C:/tl/paraformer-tail-20261110/paraformer-tail-verification.json`。本次使用合成技术音轨、复用人物画面和本地受控规划回复，业务模型语义和用户整片视听仍待验收。

另取 48.475 秒清洁用品实录的历史原始识别结果，对照新预处理时钟。分析 WAV 摘要、243 个词点、25 段句界和原有的 24 毫秒末词调整均一致，见 `C:/tl/paraformer-tail-20261110/normal-clock-evidence.json`。304 项剪辑、原库、视频生成和项目访问回归通过，目标 Ruff 和 mypy 通过。mypy 跳过现有第三方库缺失类型声明告警。

## 浏览器动效画面原件校验

原浏览器入口会将缺失图片回退为透明图。使用同一原版浏览器引擎、已登记的本期配图和原片取帧复现了 CX-G05 的缺件行为。69 次活动底板请求均返回 HTTP 200 和 4×4 全透明图，原引擎仍可画出三个不同的诊断帧。这个现象说明动帧和编码回执无法证明原活动背景存在。诊断证据在 `C:/tl/missing-originals-20261110/legacy-native-observed/evidence.json`。

网站在编译和调用原生入口前核对当前分支实际画入成片的原图，按原包清单比较字节摘要。CX-G05 始终需要 69 张底板，走原人物分支时还需要 69 张透明人物帧。CX-G09 始终需要三张原纹理图，走原底板分支时还需要 66 张底板。CX-G10 使用原底板和人物分支时核对两张原图。共用入口中本分支用不到的初始化图片继续按原引擎合同加载。组详情保留全部启动依赖的清单，编译诊断单列会进入画面的缺件及数量。

复用同一组实录词点和四个本期图片输入请求编译 CX-G05，实际返回缺 69 张底板，未写出原生任务。直接提交此前能绘制透明底板的原生输入，网站适配入口在启动浏览器前拦截。用同一输入验证共用引擎的 CX-G04，重新编码并完整解码 80 个不同画面帧，摘要为 `8716e9565576fa785efab82bb8b82509d4715ff5655041bb71ed7845cdedd52a`。回执见 `C:/tl/missing-originals-20261110/guard-compiler-evidence.json` 与 `guard-native-evidence.json`。本轮证据范围为浏览器组件、原图校验和缺件拦截。

在指定本地目录和两个原 ZIP 内按文件大小及 SHA256 查找七个已登记的缺件资源。扫描 305,961 个文件及 1,461 个 ZIP 文件条目，唯一大小相同的候选摘要不同。两份 ZIP 摘要与交接基线一致，原 Motion 包 1,426 项完整性通过。HY-A1 原入口包含一路同期视频输入和三张文字卡，原俊雅字体的授权与字节仍待取得。励字原超粗黑及志向黑也待取得可核验的字体和项目授权。[造字工房俊雅](https://www.makefont.com/font-1564.html) · [励字超粗黑简繁](https://www.dreamfont.cn/font/lizichaocuheijianfan.html) · [励字志向黑简特粗](https://www.dreamfont.cn/font/lizizhixiangheijian%20tecu.html)

314 项剪辑、原库和视频工作台回归通过。加入任务诊断专项用例后复跑 23 项；目标 Ruff、mypy、前端类型和 ESLint 检查通过。四个浏览器缺件组和 HY-A1 仍保留原目录状态，待取得原件后继续运行验证。

## 单独补交浏览器原件的接入

剪辑服务使用现有 `POLARIS_VIDEO_EDITING_NATIVE_BINDINGS_FILE`，在其私有 JSON 中新增可选的 `browser_startup_originals`。保留该文件原有 `resources` 和 `tools`。新增对象的 `library_release` 填原 Motion ZIP 的完整 SHA256，`files` 以从 Motion 根目录起的原始相对路径为键。每条记录提供本机绝对 `path`、文件 `sha256` 和可追溯的 `original_source`。例如 G05 第零帧的键为 `src/engines/workspace/晨曦_接手复刻_20261104/editable-library/reuse-G04-G06/g05-assets/base-000.jpg`。同一分支实际绘制的缺失序列需逐帧补齐。

编译将本次使用的 JPEG 和 PNG 按摘要冻结到任务目录。已索引的原图同时核对原目录记录的字节数和摘要，回执记为 `catalog_sha256`。未索引的原帧核对补交文件摘要及来源登记，回执记为 `operator_attested`。任务启动和浏览器逐文件响应时再次核对冻结字节。原浏览器的本地服务只对本次原路径返回已核验的补交图，原引擎继续执行原绘制。原生回执记录实际加载的路径键、摘要与证据类型。变更后的补交文件进入新任务，续跑指纹包含已冻结的绑定。

使用一段实录的 69 张测试帧，在独立目录验证实际 CX-G05 编译、冻结、浏览器加载和编码。原生回执记录全部 69 张，输出独立解码 100 帧，其中 89 种画面摘要。首帧左上抽样区和对应输入图的 RGB 平均绝对误差为 0.76。另复制任务并改动一个冻结文件的一字节，原生入口在启动浏览器之前拦截。原库 1,426 项摘要复核一致。详情见 `C:/tl/browser-supplement-20261110/transport-verification.json`。测试验证接入传输和渲染机制。四组缺件浏览器动效和 HY-A1 的真实原件及授权状态仍待补齐。

缓存负例在独立任务中变更一项来源记录，旧原生片段被拒绝复用。317 项相关回归及最终 35 项专项复验通过，目标 Ruff、mypy 和差异检查通过。

## 数字人口播交接的识别边界与模板避用

两条已有数字人生成记录提供了新的边界实测。固定 Paraformer 以 60 毫秒为一步，时间戳预测使用 −1.5 步补偿。首词起点最多提前 90 毫秒且区间仍与实际音画重叠时，将其收束到可用媒体起点。末词的上界包含滤波帧取整最多 35 毫秒、CIF 的额外 60 毫秒及 1 毫秒时钟取整，只有最后一个词允许使用这段余量。识别适配层记录每次边界收束及原值，已测词点及原声保留。强制对齐和其他识别器仍使用其原有策略。

在独立数据库副本，通过已有数字人生成任务重新提交两个网站剪辑任务。原片、确认稿关联、识别 WAV 和原始词点均与历史源一致。首条任务 `636e522a-e5b0-4877-83c2-eaf2ca13d1c6` 识别 169 词，首词 −90 毫秒收束至 0，末词从 40.680 秒收束至 40.627 秒。第二条任务 `c31a82b2-42f4-4e79-afb3-e86b9ba89223` 识别 153 词，末词从 39.400 秒收束至 39.331 秒。两条均完成基础字幕出片和网站范围下载验证。回执见 `C:/tl/handoff-paraformer-20261110/head-evidence.json` 与 `tail-evidence.json`。

模板准备按冻结的项目备忘避用单组。运行条件未满足的组另列，两类重叠的组只扣一次。其余槽和 132 组原目录仍保留，模型与编译继续核对避用合同。可选组少于五种时，准备结果供查看，网站和语义 worker 在首次提交模型前拦截。已有提交记录继续走原恢复流程。

以首条实际口播调用准备接口。「转场与评论引导」的准备任务 `2edb561a-9d01-487f-a9a3-05bf0a09d432` 避用三组后有 26 种可选，生成请求受理后在 worker 运行前取消。另一准备任务 `dca617b8-8442-4289-a83f-8452e1347ae1` 只剩 4 种，生成接口返回 HTTP 409，错误码为 `EDITING_TEMPLATE_GROUPS_INSUFFICIENT`。两份准备请求保留 132 组原目录及实录词 ID。网关调用数为零。回执见 `C:/tl/handoff-paraformer-20261110/planning-choice-evidence.json`。

首条确认稿作为操作者候选文字走实际 FunASR 强制对齐，任务 `2c949b33-6ed6-42a0-a494-a3a97d0c2d58` 保留同一原片和分析音频摘要，得到 169 个对齐词点及基础字幕成片。高清范围下载返回 HTTP 206。回执见 `C:/tl/handoff-paraformer-20261110/alignment-evidence.json`。331 项相关回归通过，目标 Ruff、mypy、前端类型和 ESLint 检查通过。

本机 Chrome 显示两次准备分别有 26 种和 4 种可选动效，单列项目避用组，并在 4 种时禁用付费提交。浏览器实播首条 720×1280 基础字幕片，取得范围响应并下载与服务端摘要一致的文件。三次出片的原声分轨相对独立解码原片，波形误差均低于 −143 dBFS。证据见同目录 `browser-evidence.json` 与 `voice-evidence.json`。本轮验证到实际口播交接、识别、校对稿对齐、基础字幕交付及选组准备。真实业务模型选组和完整动效成片仍待验收。

## 原版斜卡人物窗口与竖屏成片分辨率复验

用户再次确认 HY-A2 保留原模板的右下人物窗。原入口 `scene-l-a2-mock.svml` 给出 `mkfg1@483,1014,597,906`。网站编译继续把同期人物透明轨等比放入这个窗口并保留原层级。原画和原声沿同一个实录时钟运行。用户指出的 `hypit-a2-natural-20261110` 文件是此前的全幅前景版本。重新核对右下窗成片的原片、交付件和原生渲染回执，进出场恢复原片尺度，39.43、40.40、42.00 秒的两轴倍率均约为 0.47。三条提示音仍对应原生可见入场的成片第 1194、1206、1230 帧。可看 `C:/tl/hypit-a2-template-inset-20261110/website-slant-inset-hd.mp4`，本期复验回执在同目录。

剪辑任务的竖屏母版上限从 720×1280 提至 1080×1920。在该范围内保留源片画幅和分辨率，超出范围时等比缩至上限并取编码所需偶数尺寸。基础主字幕的描边和阴影随较高画幅缩放。原生导出后检查实际宽高与冻结 episode 一致，预览代理按画幅适配到 360×640 以内。此项针对整片交付尺寸，原生组件仍使用原模板定义的画布。

用清洁用品实录和已经核对的斜卡编排重新登记操作者候选。独立 worker 在任务 `fc2d8c9f-2c5c-40ca-a954-2666d7f7e1f2` 原生编码 48.475 秒整片，保留原片 768×1366 分辨率，含十一种动效、十六条提示音和一条背景乐。用同时间原片和下载件测量人脸，斜卡内三处宽高倍率均约为 47%，两轴差小于 1%。进场前和回切后仍为全幅，原声分轨波形差为 −143.34 dBFS。新母版及 358×640 代理均通过网站范围请求，母版完整解码并核对下载摘要。成片为 `C:/tl/slant-native-size-20261110/website-slant-inset-source-size.mp4`，回执为同目录的 `delivery-evidence.json`。

将已保存的真实腾力网关响应与其原请求摘要、网关域名和语义编排逐项核对。原响应使用另一个工作树的 `knowledge-talk-v1`。原词段、关系和八个组选项均通过当前 `unified-explanation-v1` 合同，按操作者候选身份重新注册并由独立 worker 执行。任务 `c88bc8d1-876f-41c5-87ce-41475d788f74` 从原 1080×1920 数字人口播生成同尺寸 40.627 秒成片。实录时间轴有十处动效，含八种原生组，AH-S08 使用三次。整片有十三条提示音和一条背景乐。原声分轨与独立解码原片的波形差为 −143.46 dBFS。代理及确认后的母版均通过网站 API 范围播放请求，下载件复算摘要一致且完整解码。证据为 `C:/tl/portrait-master-20261110/delivery-evidence.json`，下载件在同目录。

302 项后端剪辑、原库及文稿回归，目标 Ruff、mypy 和差异检查通过。本轮没有新增付费调用。归档响应复验验证了当前网站从已冻结词级编排到原生高清交付，当前模板的全新模型请求、其选组语义及用户整片视听仍待验收。原库五组依赖缺件和授权的状态沿用上文。

## 浏览器原件的目录核验与照片回退预检

原库组详情复用剪辑 worker 的原件校验。四组浏览器入口分别显示原包索引、实际核验的原包文件数、已通过字节核验的补交件数和待核验的原相对路径。按原生分支标出每套文件用于当前画面、未绑定本片人物时、相应图片槽留空时或共用入口预加载。私有绑定的绝对路径和补交来源记录不下发给网页。版本或结构错误的补交清单会在目录显示核验异常。

核对 CX-G05 的原生 `state()` 后增加逐槽预检。第 i 个图片槽留空时，原引擎使用 `photo-i.jpg`。现在只增加该槽对应的原照到本次画面必需文件。整套图片均由本期素材绑定时，检查仍限于实际画入成片的原件。

用正式绑定和隔离诊断清单实际请求组详情。正式绑定的 CX-G05 报告缺 69 张活动底板和 3 张回退照片。诊断绑定核验了 69 张测试底板，保留三张原照待补。沿用同一份编译配置和 69 张测试底板，在独立任务中仅把第二个图片槽置空，原生入口在启动浏览器前报告缺一张原照。保留本期图片绑定的另一任务重新编码并完整解码 100 帧，其中 89 种画面。原生回执记录 69 张已读取的诊断图。证据在 `C:/tl/browser-original-intake-20261110/api-evidence.json` 和 `native-evidence.json`。

本机 Chrome 以 425 像素视口进入已有剪辑项目。目录显示诊断环境的 69 张核验补交件，能展开查看缺少的三张原照片和各分支的使用条件。证据在同目录 `browser-evidence.json`。303 项后端剪辑、原库及文稿回归和目标 Ruff、mypy、前端类型与 ESLint 通过。原包 1,426 项摘要一致，132 组继续登记。本次验证了缺件识别和补交路径。四组浏览器动效的实际原件、HY-A1 字体和 AH-S03 B 版字体授权状态继续单列待核验。本轮未采购授权或调用付费接口。

## 写稿来源随确认稿进入剪辑

显式采用草稿时，同一事务保存项目正文、草稿版本、采用记录及来源。来源含参考原文、拆解报告、事实卡、采用草稿及其摘要、原写稿方法版本和正文 SHA256。标题、音色等设置改变时，正文相同的版本继续关联原资料。正文改变或切换到音频驱动时，新的版本会解除该关联。普通保存时重新输入相同文字也不会恢复已解除的关联。重新采用可建立一条新的采用记录。

确认口播时同时冻结正文及其来源。剪辑任务按所选生成结果的确认版本核对正文和来源，版本历史可展开查看资料编号，剪辑来源回执一并提供。旧 handoff v1 继续使用其原 manifest，历史项目和版本未推断补写来源。迁移 `20261110_0051` 为项目和版本各增加一个可空 JSON 字段。实际 PostgreSQL 18.4 完成从 0050 升级、降级和再次升级，核对原项目、旧确认快照及两个可空 JSONB 字段。SQLite 的 0050 测试副本亦执行了升级。记录为 `C:/tl/writing-origin-20261110/postgres-migration-evidence.json` 和同目录 `migration-evidence.json`。

本地由同一真实口播截取 4.833 秒。经网站 API 保存参考原文、拆解报告、事实卡和草稿，显式采用并改标题后创建口播任务，再人工改稿。旧确认稿继续带原资料来源。独立剪辑任务 `097da646-6ae1-4193-b6c3-0a3aea8bf9f7` 从旧口播生成结果识别 24 个词点，原生导出 768×1366 字幕片，验证范围请求 HTTP 206、完整解码及下载件摘要。原声分轨与同源独立解码音频波形差为 −143.31 dBFS。证据见同目录 `delivery-evidence.json` 与 `media-evidence.json`。写稿及生成服务均使用受控本地响应，素材为现有实录。这次验证来源流转、实际识别和剪辑，真实模型文稿质量与业务视听仍需验收。无新增付费请求或部署。

Chrome 在版本历史展开旧确认稿的四项资料编号，在剪辑任务核对同一确认稿和事实卡，下载来源回执并实播和下载同摘要成片。浏览器证据在同目录 `browser-evidence.json`。374 项相关后端回归通过，最终调整后复跑 11 项专项。目标 Ruff、mypy、前端类型、ESLint、OpenAPI 生成及差异检查通过。

## 沿用指定预览继续调整

代理就绪或已确认的任务可选「沿用此版继续调整」。页面从该任务保存的选项恢复音乐、保留原景段落、强调词和配图，并与从初始编排打开的控件分别管理。新预览独立保存。创建时核对原片、编排、项目、所有者、库版本、上版代理文件编号和摘要。编译回执记录上版身份。归档中的旧模板 ID 在当前版本缺失时，单条候选继续可读并说明状态。其他候选仍可使用。

独立 worker 只在上版代理仍可复核时尝试跨任务复用。对原生字幕组件核对原片、全部冻结绑定、渲染工具及适配版本，再逐镜头比对请求、MP4 摘要和透明序列逐帧摘要。素材绑定、镜头编号或原生请求变化时重新渲染，依赖任务侧文件的场景也重新渲染。新版完整执行版面、混音、解码、代理及确认校验。

从同一条实际数字人口播及已冻结的历史模型词段编排新建基准任务 `8e94901a-e7bf-4775-bc05-e86d97961320`，背景音乐降低 6 dB。故意传入错误代理摘要返回 409。衍生任务 `dfb3b6d1-8eac-4dc4-a6b7-5c4a464883f4` 仅关闭背景音乐，实际复用 7 个原生字幕镜头，其余场景重新编码。前后均有 8 种原生动效、10 次出现，原声分轨摘要一致。上版代理身份与设置复核一致，新版 40.627 秒成片通过范围请求、下载摘要及独立完整解码。记录在 `C:/tl/preview-version-20261110/delivery-evidence.json`。本轮沿用保存的编排，无新增模型付费调用或数据库迁移。

460 像素视口 Chrome 从基准预览恢复「背景音乐降低 6 dB」，仅将 38.29 至 40.19 秒的 JJ-S02 设为原景。任务 `e45636dc-a93a-4cc1-8ef9-7dd8f47d7a5a` 独立完成，保留 7 种动效，复用 6 个原生字幕镜头。原声分轨摘要、上版代理和音乐设置复核一致。该段的动效提示音随原生段撤下。对 5 个同期画面，在该动效改变的像素区域，新片与原片的 RGB 平均绝对误差为 0.72 至 1.11，原代理对应母版为 59.93 至 102.30。Chrome 确认后实播并下载 1080×1920 文件，摘要与服务端一致。证据见同目录 `browser-evidence.json` 与 `segment-picture-evidence.json`，本地下载件为 `website-segment-revision-hd.mp4`。

376 项相关后端回归通过，最终更新的历史模板用例随 18 项专项再次通过。目标 Ruff、mypy、前端类型、ESLint、OpenAPI 生成及差异检查通过。现场联调验证局部调整、原生渲染和交付，模型业务语义及用户整片视听仍待验收。

## 动效种类、出现次数与重复段调整

页面分别显示模板可选种类、模型候选选中的种类和出现次数，以及独立 worker 按实际原生画面核验的种类和出现次数。五种为组合出片下限，十种是规划的优先目标。语义合同通过但选组不足五种的模型候选可查看，保存为原生编排和生成预览均返回 422，单条和批量沿用同一门槛。基础字幕组 Z-M00 不计入动效种类或出现次数。

「精简重复动效」由用户主动选择。它将可改为原景的后续重复入场预选为保留原景，保留每种动效当前的首次出现及已编辑的强调词、配图。提交前仍可逐段取消。重复入场继续可用于默认编排及手动调整。

用已有 40.627 秒数字人口播和已保存编排，从基准代理选择精简两段。Chrome 提交前显示由八种十次变为八种八次，沿用原代理摘要和音乐降低 6 dB。任务 `2735c8ec-bdd8-4946-a9a7-b152d8398f3d` 由独立 worker 编码。代理与确认后的成片均返回实际核验的八种八次，高清接口返回 HTTP 206。仅 AH-S08 从三次减为一次，提示音从十三条减为十一条。其余提示音的素材、处理后摘要和成片起音一致，原声分轨摘要一致。Chrome 实播并下载 1080×1920 成片，下载摘要与服务端一致且完整解码。证据见 `C:/tl/motion-density-20261110/browser-evidence.json`，下载件在同目录。对此前 HY-A2 整片按同一规则重数，原生回执为十一种、十一次。

复核 HY-A2 原版右下角人物窗样片。39.43、40.40、42.00 秒人物按约 47% 等比适配，保持原层级。对 39.30 秒起的成片人脸区域抽取连续 108 帧，其中 106 帧不同。同期人物透明轨的 120 帧中有 119 帧不同，最长连续同帧为两帧。源视频为 24 fps，合成为 30 fps。原声分轨相对独立解码的实录波形误差为 −143.34 dBFS。资料见 `C:/tl/slant-native-size-20261110/presenter-motion-recheck.json` 和同目录交付回执。

377 项相关后端回归通过。目标 Ruff、mypy、前端类型、ESLint、OpenAPI 生成和前端精简规则测试通过。本轮沿用已保存编排，无新增付费调用或部署。全库可用状态、模型语义和整片用户视听仍按前述条件验收。

## 产品讲解与知识口播接入当前工作树

从另一个隔离工作树迁入「产品讲解」和「知识口播」，各组合 16 种原库动效。当前网站有 42 套组合模板，覆盖 125 组不同原生动效。两组继续使用同一套转录、源素材、原生编译与交付。沿用当前分支的原片比例、候选与成片计数、预览调整、文稿来源及原件核验。现有模板继续使用原请求协议。

这两组的模型输入携带实际词序号、识别时钟和原生字段。候选只引用实录词点、模板动效和本期素材。网站逐项核对原生字数、读时、素材和关系，并从合格候选中挑选可连续渲染的编排。准备时排除项目避用组和运行依赖不足的组，不为它们生成词段适配示例。模型响应不足五种仍可核对，继续由原生候选和出片入口把关。该协议的输出上限为 8500 token，实际账单取决于网关用量。

从原隔离运行目录保留实际网关响应、请求、实录和摘要，以新数据库副本和任务目录重新验证。当前网站 API 重新冻结候选，再由独立 worker 原生渲染。清洁用品产品讲解任务 `2bbdb1a0-261b-4b94-b65d-e647475cc126` 为 48.475 秒，10 种动效共 15 次入场，17 条提示音和一条背景乐。桌面收纳知识口播任务 `dad7baf8-46f6-4e50-a5b2-a1f3c546886a` 为 40.123 秒，10 种动效共 10 次入场，15 条提示音和一条背景乐。两条下载件为 768×1366。代理和确认后的母版范围请求均返回 206。母版完整解码并核对下载摘要，原声分轨相对独立解码原片的波形差均低于 −143 dBFS。成片及交付回执在 `C:/tl/tengli-merged-groups-20261110` 的 `product` 和 `knowledge` 子目录。

Chrome 实际选择两套模板并提交新准备任务。产品讲解和知识口播分别使用 240 和 201 个实录词点，各带 132 组目录，网关均未提交。两条成片也分别在 Chrome 实播和下载，下载摘要与 API 一致。浏览器回执位于两个子目录的 `browser-evidence.json`。原包 1,426 项摘要重新核验一致。381 项相关后端回归通过，随后加入项目避用与运行依赖的请求预检用例，5 项专项再次通过。目标 Ruff、mypy 和差异检查通过。此次验证使用已捕获的实际网关响应，无新增付费调用或部署。仍需用户验收视听、验证当前准备的新请求经过实际模型，并补齐原库缺件和授权。

## Linux 独立剪辑 worker 的内部 Hypit 运行

新增本地可选 `compose.editing-hypit.yaml`。将已安装的私有运行目录指向 `POLARIS_HYPIT_RUNTIME_HOST`，并将 `POLARIS_HYPIT_INTERNAL_WORKSPACE` 指向唯一的内部开发工作区。目录内提供 `node/bin/node`、`node_modules/@hypit/hypit/bin/hypit.mjs` 及完整的 `chromium` 目录，其中浏览器入口为 `chromium/chrome`。在同一 Node.js 安装下提供原版渲染器声明的 `@hyperframes/engine` 和 `@hyperframes/producer` 0.7.101。与基础、剪辑及原件覆盖配置合并后，API、规划 worker 和剪辑 worker 获得相同的只读目录和 Node.js 搜索路径，运行目录不存在时 Compose 报错。剪辑 worker 启用容器 init，以回收原生渲染启动的子进程。静态合并回执为 `C:/tl/hypit-linux-internal-20261110/compose-validation.json`。

运行预检检查 Node.js 22.15.0 下限和两个固定版本的 Hyperframes 包。Windows 原有的 Hypit 机器级包目录也通过核验。配置了 Hypit 的 `--check-runtime` 还会启动受审计的 CLI 和指定的无头 Chromium，检查浏览器画布。使用独立 WSL Docker Engine 的无外网容器实测，Node.js 24.13.0、Hypit 0.2.12 和 Chromium 156.0.8078.4 可用。CLI 模块与原 Windows 验证版的 SHA256 相同。未登记工作区、生产环境及缺少 Node.js 均被拦截。最终回执为同目录的 `runtime-complete-probe.json` 和 `scope-probe.json`。Hypit 的第三方托管和多租户使用仍须取得书面授权。 [Hypit 0.2.12 原发布包](https://registry.npmjs.org/@hypit/hypit/-/hypit-0.2.12.tgz) [Hypit 许可](https://raw.githubusercontent.com/hypit-ai/hypit/main/LICENSE)

同一口播的 Windows 与 Linux 识别 WAV 分别有 775,600 和 775,680 个 16 kHz 单声道样本。源视频摘要与时长一致，现有来源门槛按音频摘要拦下直接重用的 Windows 编排。Linux 技术验证重新识别并对齐当前录音。校对稿在两端的 240 个实录词点文字及时间一致，Linux 保留自己提取的音频和转录摘要。独立挂载的两个原字体和抠像模型也与原库登记的摘要一致。

HY-A2 单组测试实际渲染了 120 帧。缺少 Hyperframes 包时，原生 Build 在绘制阶段明确报错。补齐两项固定版本后可编码并完整解码。没有容器 init 时原 CLI 在关停报告仍检测到 worker PID。启用 init 后，使用同一原生输入重渲，输出摘要一致且原 CLI 报告 worker 已停止。原版右下窗仍为 `[483, 1014, 597, 906]`，输入透明人物轨保持等比。单组回执为 `component-evidence.json`。


使用重新测量的 Linux 词轴，将相同原生方案登记为独立操作者候选。断网容器内的 HTTP API、独立剪辑进程和测试 SQLite 库完成任务 `d0b459d2-48ee-4a9a-a9b6-b9c7b62d81f2`。48.475 秒整片使用 11 种原生动效、16 条提示音和一条背景乐。HY-A2 的三条提示音在成片第 1194、1206、1230 帧起音，原声分轨相对独立解码原片的波形差为 −146.37 dBFS。原生版面检查及完整解码通过，Hypit 正常关停。代理和确认后的母版范围请求返回 206。容器 Chromium 从 API 实播 768×1366 母版，下载摘要与服务端一致。复跑母版与首次完整编码的母版摘要相同。39.43、40.40、42.00 秒人物等比位于右下，前后恢复全幅。回执为同目录 `delivery-evidence.json`、`playback-evidence.json`、`geometry-evidence.json`，下载件为 `linux-hypit-slant-hd.mp4`。

384 项相关后端回归通过，加入原生依赖检查后 59 项专项再次通过。目标 Ruff、mypy 和差异检查通过。本轮未新增付费调用或部署。整片语义和用户视听仍待验收，五组原件或授权及 Hypit 对外托管授权仍单列。

## HY-A2 原人物窗的编译与成片复验

用户确认原模板的右下角位置和层级可用，人物需保持原比例。编译核对原 SVML 的 `fg` 坐标，原生适配把同期透明人物轨等比放入 `[483, 1014, 597, 906]`，编码尺寸为 597×906，媒体轨以 `contain` 放入同一窗口。原斜卡和人物的遮挡关系沿用原模板。冻结的历史全幅方案仍按各自版本回放。

同一条真实口播和已核对的词级编排在隔离网站 API 及独立 worker 重渲。任务 `3e4ec9a5-faad-455d-9145-7ac2cc342057` 完成 48.475 秒母版，含 11 种原生动效、16 条原库提示音和一条背景乐。A2 原生段有 120 帧。母版在 39.43、40.40、42.00 秒实测两轴缩放均约 47%，横纵倍率之差小于 1%。前后保持原片画幅。连续抽查 108 帧的人物区域得到 107 个不同帧，八处抽帧均更接近同期原片而非冻结参考帧。原声分轨波形误差为 −146.37 dBFS。Chromium 实播 768×1366 母版，代理和母版范围请求均返回 206，下载摘要与服务端一致，母版完整解码。

供验收的成片为 `C:/tl/hypit-a2-original-frame-20261110/website-a2-original-frame.mp4`。同目录保留 `delivery-evidence.json`、`geometry-evidence.json` 及 `presenter-clock-evidence.json`。315 项相关回归、目标 Ruff 与 mypy 通过。本轮沿用本地编排复验，无新增付费调用或部署，整片视听待用户验收。

## 浏览器原件批量补交

在 `backend` 目录运行下列命令，按原包列出浏览器图片的完整相对路径。`--bindings` 指向 API 和 worker 已使用的 `POLARIS_VIDEO_EDITING_NATIVE_BINDINGS_FILE`。清单按原路径去重，并列出使用共用入口的组。补交文件的本机绝对路径、登记来源和工具配置均留在私有绑定文件，报告可独立传给交付者。

```sh
python scripts/register_motion_browser_originals.py --package <已安装原包> --bindings <私有绑定文件>
```

收到原件后，将文件按报告的 `native_path` 放在独立、持久的交付目录。加上 `--original-delivery --source <交付目录> --provenance <交付批次或归档记录>` 可预检。加 `--apply` 才原子更新私有绑定，现有 `resources`、`tools` 和通过核验的图片记录继续保留。路径越界、格式错误、超限和已索引的字节身份不符都会拒绝。已索引文件标记 `catalog_sha256`，其余原件标记 `operator_attested` 并记录交付来源。诊断目录需用 `--diagnostic` 登记。剪辑任务仍按当前使用分支冻结所需原件。原 ZIP 和安装目录保持只读。

实际原包的空绑定预检列出 212 个路径。CX-G05 有 141 个，CX-G08 至 G10 的共用入口有 71 个，其中 G10 两张图有目录摘要和字节数。补查原包内 990 个源文本和清单文件，未找到这批已索引资源的内嵌 Base64 原件。交付索引见 `C:/tl/motion-original-drop-20261110/browser-original-request.json`。四份字体的原始名称、字节数、摘要及原库权利标记见同目录 `font-original-request.json`。

在独立测试绑定中批量预检并登记 69 张诊断帧，复跑时清单摘要一致。一张同路径异字节的 G10 JPEG 被拒绝。新登记进入真实 CX-G05 编译冻结和浏览器原生渲染，回执记录 69 个实际加载的文件，组件独立解码 100 帧、89 个不同画面。原包 1,426 项完整性复核通过。`diagnostic-native-evidence.json` 仅登记导入和渲染验证，四个浏览器组及 HY-A1 的真实原件状态仍待补齐，AH-S03 B 版单列。316 项剪辑、原库与文稿回归通过，最终 14 项专项、目标 Ruff 和 mypy 通过。

## HY-A1 三张原卡的实录编译

HY-A1 原入口的三张卡继续使用原 `label-card` 组件、层级、位置及俊雅字体槽。网站组件编译校验三张卡的首词、文字及实录视频来源，将变更写入原 materializer 生成的任务副本。原 schema 仍要求空 `attributes`。每次滑动保留相对入场的原帧点，卡间间隔按实录伸缩，第三张卡至少保留原末段时长。原库详情显示组件验证范围及字体缺件，组合模板仍使用原有的组和模型请求合同。

使用同一条清洁用品实录，词点 39.770、40.190、40.770 秒的三项用途分别对应组件内第 0、13、30 帧。核对三张卡的相对动作帧和原层级。同期源视频从 39.770 秒实际截取 101 帧并完整解码。编译拦截缺失字体及错误摘要，原生 worker 也拒绝以错误字节绑定该资源 ID。原包 1,426 项摘要保持一致。回执见 `C:/tl/hypit-a1-component-20261110/component-contract-evidence.json`。

默认和 Hypit 图片模板的冻结规划请求按改动前后的代码重算，摘要一致。独立容器复跑 HY-A2 原生组件，120 帧完整解码，右下窗口保持 597×906，输出与前一版摘要一致。回执见同目录的 `preservation-evidence.json` 和 `component-evidence.json`。317 项相关回归、目标 Ruff、mypy、前端类型及 ESLint 通过。HY-A1 待提供确切原字体及项目使用授权后进行原生画面验证，再核对自动选组、字幕安全区和入场音效。原库将该俊雅文件标为非商用版本。 [造字工房俊雅及授权](https://www.makefont.com/font-1564.html)

## 沿用预览更换单段原生动效

在「调整本次出片」中打开「单段更换动效」。候选限同一组合模板中可使用已有实录文字和事件词点的原生透明字效。替换按新动效的原参数和入场音效重新编译，保留该段的实录边界及先前保存的其他调整。网站提交和 worker 均核对同一候选、项目避用项和至少五种不同动效的门槛。旧编排、代理和确认过的成片仍可追溯。本轮沿用已有任务字段，无数据库迁移或付费规划调用。

对已有 40.627 秒数字人口播和前一版代理，通过网站 API 将 2.65 至 4.57 秒的 BG-S04 替换为 BG-S05。任务 `0fb38f4c-63e8-45e6-ab0b-496db625f3a6` 的八个未改镜头原生编码摘要一致，11 条其他提示音的素材及实际起音一致，主字幕锚点、原声和背景乐分轨摘要相同，并保留手工指定的一段原景。两版适配器摘要不同，本次重新编码各段。新成片含 7 种原生动效共 9 次出现，Chrome 确认、播放并下载 1080×1920 高清，代理和高清范围请求均返回 206。再次从新版进入调整时，浏览器恢复了换段选择、音乐设置和原景勾选。

同段 BG-S02 的正文与强调字在原生检查中发生四帧碰撞。独立 worker 实际返回 `EDITING_EFFECT_LAYOUT_FAILED`，该尝试未开放代理或高清。两项回执见 `C:/tl/motion-segment-effect-20261110/delivery-evidence.json` 和同目录 `effect-layout-failure-evidence.json`。可查看 `website-segment-effect-hd.mp4` 约 3 秒处的替换结果。318 项相关回归、目标 Ruff、mypy、前端类型和 ESLint 通过，原包 1,426 项完整性复核通过。新片整体视听仍待用户验收。

## 可变帧率原片的人物取帧

独立剪辑任务读取原片解码后的显示时间戳，检查与原生平均帧率换算的累计偏差。对确认有偏差的原片，FFmpeg 按显示时间生成同宽高的无音轨 30 fps 副本，交给已核对摘要的原 `unified.core.media` 取帧。原包、原片、音频、实录词点和模板构图保留。正常恒定帧率继续走原取帧路径。副本和原片摘要进入回执及交付恢复指纹，避免把此前按不同帧时钟出过的成片当成当前产物。异常时间戳或无法生成取帧轨时任务显示对应原因。

取已有口播的 8 秒做技术输入，前段和后段刻意使用两种画面帧率，音轨保留原有内容。网站接受真实上传，独立 worker 完成识别、原生字幕成片和交付。原片 136 个显示帧，副本 240 帧。以原显示时间确定同期参考帧，十处嘴部区域的平均像素差为 2.62 至 2.96，平均帧率旧取帧的对照为 6.95 至 19.75。原声分轨与独立解码的原音误差为 −143.31 dBFS。恒定帧率对照的 1,163 帧识别为恒定帧率。Chrome 从网站 API 实播 768×1366 成片，范围请求返回 206，下载摘要一致。`C:/tl/motion-presenter-vfr-20261110/website-vfr-narration.mp4` 为基础字幕验证片，同目录有 `timing-evidence.json`、`delivery-evidence.json` 和 `browser-evidence.json`。

另用同一条 48 秒真实口播和原音频包做变帧率技术输入，运行已核对词点的 HY-A2 原生组件。原片 843 个显示帧，取帧副本 1,454 帧。右下人物窗保持原坐标和 597×906 尺寸，组件 120 帧完整解码。39.43、40.40、42.00 秒对应画面的人物横纵缩放均约 47%，两轴差小于 1%。回执为同目录 `a2-component-evidence.json` 和 `a2-geometry-evidence.json`。本期验证覆盖共享原生取帧、基础字幕交付及 A2 组件，其他独立取帧入口和配套素材的变帧率适配仍待实测。319 项相关回归、目标 Ruff、mypy、前端类型和 ESLint 通过。原包 1,426 项完整性复核通过。

## 补充视频按实际显示时间取帧

独立 worker 在编译后检查本次选用且已暂存的项目视频，按原件摘要复用同一份测量。可变帧率素材生成同宽高的无音轨 30 fps 副本。原生共享取帧入口核对原件和副本摘要后，沿用原绑定的起播词点、片内起点、裁切及片尾规则读取画面。项目原件、原生绑定、字幕词轴和口播原声保留。恒定帧率视频沿用原取帧路径。回执纳入成片恢复及跨预览复用校验。另对 MOV 和 WebM 运行取帧准备，其中 WebM 容器含 5.308 秒音轨，按实际视频时间戳生成的取帧副本为 4.267 秒。

用同一条 48.475 秒真实口播，以及由本期已登记实录近景制作的变帧率技术素材，走网站上传、冻结词级编排、独立 worker、代理确认和母版交付。近景仅用于核对取帧，没有商品或使用演示。任务 `11235cba-5449-4c9b-84c6-bf2abeea6d2a` 选用的两条视频只有一条需要生成取帧副本。84 个显示帧转换为 128 帧，原件下载摘要一致。在 CXBR02 与 CXBR04 的补充视频区各抽取四帧。对照原件显示时间戳选出的画面，平均像素差为 1.67 至 1.80，按平均帧率换算帧号的对照为 8.64 至 17.83。五个晨曦场景的原生画面投影、同期人物取帧、字幕读区与入场音效均通过检查，原声分轨与独立解码的原音差为 −143.34 dBFS。

成片有 10 种原生动效共 11 次出现，含 13 条原库提示音和一条背景乐。代理及母版范围请求返回 206，Chrome 从网站 API 实播并下载 768×1366 母版，摘要与服务端一致。片子和回执位于 `C:/tl/motion-material-vfr-20261110`，母版为 `website-vfr-material.mp4`。本轮沿用已核对的词轴和本地受控编排，覆盖共享原生取帧路径。其他独立原生取帧入口、实际模型选组及用户整片视听仍待验证。323 项相关回归、目标 Ruff、mypy、前端类型、ESLint 和原包 1,426 项摘要复核通过。仅对隔离测试库应用已有迁移。

## 试听和替换本次背景音乐

「调整本次出片」可试听现用曲目，并为已有单首背景音乐的编排更换原库曲目。可选曲目需核对原件摘要、原库本地使用标记、编排要求的时长和项目避用备忘。试听走原库已有的鉴权音频入口。新曲从文件开头播放，沿用原编排入点、出点、淡入淡出和音量曲线，可同时保留降低 6 dB 的设置。替换作为本次预览选项记录，继续调整时恢复已选曲目。多首曲目的原编排仍可按原方式调整音量。没有数据库迁移。

从已有 40.627 秒数字人口播代理继续调整，Chrome 读取 13 首可替换曲目，实播原库「未匹配_028.mp3」，生成任务 `2e4f6b3c-4f51-43d3-98d8-e608f7de2bc8`。未登记曲目返回 422，其他项目读取返回 404，重复提交返回同一任务。新版保留降低 6 dB、一个原景段和 BG-S05 的单段替换。独立 worker 重渲后，9 个原生镜头、整片视频流、原声分轨及 12 条提示音的摘要和时点均与上版相符。新背景乐分轨的四处波形与所选原曲独立解码的相关系数约为 1.000，与原选曲的绝对相关系数低于 0.09。

新版含 7 种原生动效、共 9 次出现。Chrome 确认、实播并下载 1080×1920 母版，代理及母版范围请求均为 206，下载摘要相符，完整解码通过。继续调整新版时恢复了已选曲目和降音量设置。成片在 `C:/tl/motion-music-replacement-20261110/website-replaced-music-hd.mp4`，同目录有 `delivery-evidence.json`、`music-wave-evidence.json` 和 `stream-evidence.json`。324 项回归、目标 Ruff、mypy、前端类型、ESLint、OpenAPI 复算和原包 1,426 项摘要复核通过。此片沿用已有编排，整片听感待用户验收。

## 语义候选通过后自动生成代理

使用已有口播转录和组合模板准备请求。可运行的模板默认勾选「候选通过后自动生成代理预览」，也可按本次请求取消勾选。仍由用户明确点击付费模型提交，准备步骤保留免费。自动选项随任务持久化，与实际供应商请求内容分开。

规划 worker 先保存并核验实际词点、候选和供应商响应，再沿用人工预览入口的原生编排准入与固定请求编号，创建独立剪辑任务。响应保存后若 worker 中断，维护进程会重新投递待接续任务。已保存的候选继续使用原响应，剪辑任务与规划链接同时提交。候选不足五种动效或其他准入条件变化时，保留已保存的语义结果和具体失败原因。已有计划、单条和批量手工预览沿用各自入口。自动出片止于代理，高清仍由用户对对应预览版本确认。无数据库迁移。

在隔离数据库副本构造「已保存真实词级候选，代理尚未提交」的接续状态。维护扫描经 Redis 8.8.0 向独立规划进程投递，复用原响应、只创建一个等待剪辑的任务，第二次扫描返回零条。恢复进程关闭模型执行开关，保存的响应摘要及规划尝试数保持一致。独立 PostgreSQL 18.4 的 JSONB 测试核对七类状态，仅选中待接续记录。回执在 `C:/tl/motion-auto-preview-20261110/redis-recovery-evidence.json` 和同目录的 `postgres-recovery-predicate.json`。327 项相关回归、目标 Ruff、mypy、前端类型、ESLint 与 OpenAPI 复算通过。

Chrome 从已有真实口播的准备记录提交规划 `28b2bfb5-a8a1-4a00-91ba-80387a2d1f44` 后关闭标签页。规划进程接受一次本地受控响应，直接创建剪辑任务 `f28f5cac-1a77-4ec4-bb3a-09d49a4fb4d5`。重放提交和规划消息沿用同一任务。独立剪辑进程重新编码 48.475 秒整片，含 10 种原生动效共 11 次、13 条提示音和一条背景乐。重新打开网站可由规划链接定位并播放 358×640 代理，确认后实播、下载 768×1366 母版。代理与母版范围请求返回 206，下载摘要和独立全量解码通过。母版与同输入的手工接续对照摘要一致。回执为同目录 `delivery-evidence.json`，母版为 `website-auto-preview-hd.mp4`。此验证使用保存的实录词轴和本地回放的语义响应，真实模型自动选组与整片视听验收仍待完成。

## 直接转录口播并进入动效规划

网站原片入口增加「识别口播，准备动效剪辑」，可选择已完成的数字人口播或上传视频。「生成基础字幕片」是独立入口。直接转录沿用剪辑 worker 的原音提取、识别、确认稿来源校验和恢复机制。在完成状态提交已核对摘要的逐词转录及同源分析 WAV。每句试听按原片词点扣除实测音轨起点偏移。文字校对仍以独立版本保存，可在原声上重新对齐并生成新的词轴。规划可以直接从该记录开始。作品页继续只收录可交付成片，代理和高清仍通过原生编排、校验和确认。没有数据库迁移。

Chrome 上传一条 48.475 秒实录并提交直接转录任务 `67d2e2d1-24a6-4b6f-a3b9-5ba1082e5b86`。独立 worker 用本机 FunASR 实际识别 243 个词点及 25 个分句。原声 WAV 支持 206 分段读取，点击第三句从 2.810 秒定位并实际播放。网站保存既有候选文字的测试修订，随后本机 fa-zh 完成任务 `db8233ed-9a42-4b56-8f2a-4edf8d27dcc4`，得到 240 个词点。逐词文字及实测边界与同原声的既有候选一致。两条任务均以转录就绪结束，未写出 episode 或视频产物。页面的「使用此转录开始规划」自动选中刚对齐的记录。329 项回归、目标 Ruff、mypy、前端类型、ESLint 和 OpenAPI 复算通过。

另一条测试从已完成的数字人口播任务进入相同转录入口。任务 `2ede77e9-56f6-40b3-b1c1-441a87d6f2c3` 从已登记视频的原音识别出 24 个词点，回执与数字人所用确认稿匹配，并保留确认稿版本及事实卡标识。此次复用已保存的生成来源，没有请求生成服务。

真实网站和独立 worker 将新词轴通过规划接口交给原生剪辑。模型环节在隔离环境用一次本地回放返回已核对方案，按实测词点绑定到新词轴。关闭 Chrome 后，规划任务 `8da6b312-8596-43f1-8cb6-1fc6e0acc7e6` 继续提交代理任务 `21e97d8c-d15c-4321-87b8-a671b923c63d`。原生 worker 按摘要复用同一份转录，未再识别、对齐或请求模型。重新打开网站后，Chrome 实播 358×640 代理，确认后实播并下载 768×1366 母版。母版长 48.475 秒，含 10 种原生动效、11 次出现、13 条原库提示音和一条原库背景乐。代理及母版支持 206 分段读取。下载摘要与服务端一致，FFmpeg 完整解码及原包完整性复核通过。母版为 `C:/tl/motion-direct-transcript-20261110/website-direct-transcript-hd.mp4`，SHA256 为 `50c1e62c8b683ad5812f3f2c55635aba16dd3c7a38c83290e27c45e07b138b9e`。同目录保留 `delivery-evidence.json`、`native-transcript-binding-evidence.json` 和 `generated-source-evidence.json`。此轮验证实际识别、原生渲染和网站交付，真实模型的语义编排和试片画面、听感仍待验收。

## 动效规划前检查原片画幅

直接转录 worker 复用 FFprobe 对原片的实测结果，将宽、高及原生竖屏适用性随转录原子保存。网站保留横屏或非方形像素原片的试听、下载与校对，并在转录卡显示画幅。规划列表仅纳入可用画幅与尚未测量的历史转录。API 拒绝为已知不适用的原片新建规划或原生编排。旧直接转录如无测量字段，由规划 worker 核对原件摘要后，在初次模型调用之前检查画幅。已提交的历史模型响应继续走原恢复逻辑。剪辑渲染和规划共用同一画幅规则，使用约 9:16 的竖屏及方形像素，未声明像素比例的原片沿用方形像素解释。未引入自动裁切、拉伸或数据库迁移。

在隔离网站用 Chrome 提交同一条 48.475 秒实录的 768×1366 原片及 1280×720 加边测试副本。独立 worker 对两条都实际运行 FunASR，分别得到 243 个词点，词文、边界及分析原声摘要一致。横屏任务 `182380d6-4ff4-4ee8-a3da-cc79c4b8ad70` 显示实测宽高，校对入口可用，原声分段请求返回 206。手工调用规划接口返回 409，数据库无该原片的规划任务。竖屏任务 `66ad557f-252b-4188-bd99-8c82bc9c25a2` 可由转录卡选入规划，晨曦模板的请求 `921d55dc-952a-4338-978f-4001ea391ae8` 正常完成免费准备。此次测试范围到规划准入，无模型提交或新成片。证据为 `C:/tl/motion-orientation-preflight-20261110/browser-orientation-evidence.json`。

回归另外覆盖编码尺寸为 9:16 但像素比例为 4:3 的转录，以及升级前已经准备的直接转录在第一次模型提交前被拦截。332 项剪辑、文稿及原库回归、目标 Ruff、mypy、前端类型、ESLint、OpenAPI 复算及原包 1,426 项完整性核对通过。

## 原生排版失败的片段定位与恢复

原生编排保存每个镜头与实际词级片段的对应。出现排版失败时，剪辑 worker 只保存未通过镜头的动效组、片段、首次异常的实际时点及记录数，失败卡据此显示位置。原报告和素材路径保留在内部。已登记的原生叠字按现有角色和时间规则识别。原报告同时含有允许的叠字和其他碰撞时，剩余碰撞仍阻止交付，失败卡仅统计剩余项。

「调整出错片段」打开同一份原生编排，恢复失败尝试已保存的局部调整。有已经核验的前版代理时，继续使用它的身份作为本次修订来源。用户可调整可用的段落设置并提交新的代理任务。重做仍经过原生排版、声音、可见动效数量及媒体校验，高清仍由用户确认。没有数据库迁移。

使用一条 40.627 秒的既有数字人口播和已核对词轴，独立 worker 重新运行 BG-S02，任务 `3f7d96f9-aae8-45ae-b45d-50562025ece8` 从 3.183 秒起有四条原生逐帧异常。失败卡指向 `effect-3`，没有开放代理或高清。Chrome 从该卡进入调整，确认背景乐降低 6 dB 和另一段原景仍勾选，随后仅把出错片段改为同模板的 BG-S05。任务 `db69c5c5-4c68-48aa-a3ab-db1ad5c78a11` 沿用同一编排及上版已核验代理的身份，重新生成含七种原生动效、九次出现、12 条提示音及一首背景乐的成片。原声分轨和主字幕词点摘要与上版一致，上版代理及失败记录继续可查。

Chrome 实播代理并确认、实播、下载 1080×1920 高清。两种成品的范围请求均返回 206，下载摘要及完整解码通过。母版 SHA256 为 `e6b44d71b92ce6b9abb502aefd7dafc0170ae9570c32cf6932537252416dee50`。文件为 `C:/tl/motion-layout-repair-20261110/website-layout-repair-hd.mp4`，同目录有 `collision-status.json` 和 `delivery-evidence.json`。334 项相关回归、最终 41 项专项复验、目标 Ruff、mypy、前端类型、ESLint、OpenAPI 复算和原包 1,426 项完整性核对通过。本轮覆盖确定性排版拒绝和用户局部重做，沿用已保存的编排，未请求模型。试片视听仍待用户验收。

## 实录否定的动效文字校验

按实际转录字符位置识别「不是」「并非」「不代表」等明确否定标记，再映射回原词 ID。原生文字和强调词落入该否定分句时须保留完整标记，分段或把模型关系改成普通说明也适用。显式分句标点及「而是」可结束前一分句，数字内部的小数点及逗号不会将否定提前截断，「是不是」按疑问表达处理。可选的手动强调词沿用同一规则。组合模板的候选池会筛掉违反规则的单段，继续选择其余合格动效。独立语义编排则返回明确的否定错误。沿用原文、词轴、模型请求及模板配置，无数据库迁移。此校验覆盖列出的明确表达，其他条件和隐含否定仍需语义验收。

使用通勤杯真实口播及原校对词轴，摘要对应实录的「不是占地方」从 3.890 至 4.990 秒。以同一个原生 AH-S05 候选分别绑定完整五个词点和后半句「占地方」。本地受控响应的组合规划 `9e20cfcf-2d2f-4328-8102-4af2c40ccfc2` 明确筛掉缺少否定的候选。另一份跨两段的普通说明响应 `f59dfdab-68b9-429b-9a45-2ce7e8ea7e0d` 被拒绝，未创建剪辑任务，重放未再请求供应方。保留完整文字的规划 `35b26814-1f56-40d6-b4c4-12930f81c2ee` 自动交给原生任务 `ada80f0b-d2d0-446b-a5a3-0633870bde47`。编译回执记录五个原词 ID 和 3.890 秒的镜头起点，原生组件已编码。整片通过可见效果与混音核对，共九种动效、十一次出现、11 条提示音及一首背景乐。

Chrome 实测两种拒绝提示，随后播放代理、确认、实播并下载 720×1280 高清。成片为 52.067 秒，5.4 秒抽帧可见完整文字。范围请求返回 206，下载摘要和全量解码通过。成片 `C:/tl/motion-negation-guard-20261110/website-negation-preserved-hd.mp4`，SHA256 为 `f9109cfb8907c2822a089827953647481d129061e6e4b88c2f587f53a0f85969`。同目录保留 `planning-evidence.json`、`native-evidence.json` 和 `delivery-evidence.json`。此轮使用本地受控模型响应，原包 1,426 项完整性核对通过，实际模型选组及整片视听仍待验收。

对 148 对可匹配的历史编排和转录去重复算，共检查 3,086 个原生文字锚和 69 个强调词范围，没有新增拦截。另有 11 份归档找不到配套转录，单列为未复算。回执见 `C:/tl/motion-negation-guard-20261110/archive-audit.json`。342 项相关回归、目标 Ruff、mypy、前端类型及 ESLint 通过。

## 实录报价和规格的词段校验

复用主字幕的数字与单位定义，将常见商品计量、金额、分位及数字分隔符映射回同一次实录的词 ID。普通动效文字和强调词不能在该表达内部切断。组合模板先淘汰截断的候选，独立语义编排返回明确错误，手动强调词选项也沿用同一校验。「14块9」中的尾数保留，遇到「14块9瓶」这种后一个数字自带单位的表达则分别核对。连续「1000克两斤」按实录保留两段独立规格，数字与单位沿用实录原样。

原 YY6O01 至 YY6O06 继续按原数量和单位槽渲染，两个槽须引用同一处实录。Z-M10 可保留大字数字配含完整规格的正文，W-R07 可保留原单位标签配同一次已绑定的数量。原组件仍核对自己的槽、事件、时序及读区。对 151 对可匹配的既有编排及转录复算，3,142 个原生文字锚和 69 个强调词范围内无新增拦截，29 个分槽锚点通过其原模板例外。另有 11 份归档缺配套转录。回执见 `C:/tl/motion-quantity-guard-20261110/archive-evidence.json`。

另将同一实录的 YY6O04 原生组件重新编译并执行原检查和渲染，分别保留「4」和「斤」的原槽，输出完整解码。组件摘要为 `c21525804ebb4d6167bbadd28e53c656ba2cc202e406618a243d0c3d64d0efd2`，回执为同目录 `split-slot-evidence.json`。

使用清洁用品真实口播和已校对的原词轴。「14块9」为 1.090 至 1.730 秒，「1000克」为 14.690 至 15.630 秒。组合规划 `00c7eafa-3b2a-41c2-ba03-7e2ff6c48a42` 筛掉把报价截到「14块」的候选，网页显示明确原因。独立语义规划 `79e81136-a60e-4b63-b932-046b10b07a74` 只绑定「1000」，返回 `EDITING_QUANTITY_ANCHOR_INCOMPLETE`，未创建原生任务，重放未再次请求供应方。完整的本地回放响应 `e7b69423-7ffc-47b8-a4c4-bbccf3b8d20b` 自动接续原生任务 `4062c44c-1b23-4c4b-a5d5-ba7d4f75d76d`，SG-S09 保留实录 18.190 秒起的「4斤」两个词点，18.8 秒成片抽帧可见。

Chrome 从网站播放代理，确认、实播并下载 768×1366 高清。48.475 秒成片使用十种动效、十五次出现、17 条原库提示音及一首背景乐。代理及母版范围请求均返回 206，下载摘要与全量解码通过。文件为 `C:/tl/motion-quantity-guard-20261110/website-quantity-preserved-hd.mp4`，SHA256 为 `c6fe3c272a49a901d306c887a5b04b221b0adc2c5b47b4e2419ce7e8b7659a9d`。同目录保存 `planning-evidence.json`、`native-evidence.json` 及 `delivery-evidence.json`。351 项相关回归、目标 Ruff、mypy、前端类型、ESLint 与原包 1,426 项完整性核对通过。本轮使用保存的实录及本地回放响应，未新增付费模型请求、部署或数据库迁移。整片视听及当前真实模型选组仍待验收。

## 实录适用条件的动效校验

在实际词点上识别明确的「如果」「只要」「只有」「除非」等条件与对应结果，及「仅限」「仅适用于」一类适用范围。强调词或原生字槽若使用这一范围，需要保留前提。结果含「才」「否则」等原连接词时，绑定结果也需覆盖连接词。同一原生效果的多个文字槽可以共同承担前提，仍按原模板核对各层的入场、容量和读时。口语「如果还能下单的」可用原槽表达「如果还能」和「下单」，句尾语气助词不改变这次前提。独立语义结果省略前提时拒绝，组合模板则筛掉相应候选，手动换强调词按本次其余文字槽一并核对。此规则覆盖明确句式和指定的结果信号，隐含适用范围仍需语义验收。

复算 154 对既有编排和实录，112 对识别到受保护的条件。91 个涉及条件的原生片段符合规则，5 个原生片段因缺少前提进入复核。另有 11 份归档无配套词轴。现有成片仍按其已确认版本读取，复用上述五个片段出新片须重新通过语义合同。核对记录见 `C:/tl/motion-condition-guard-20261110/archive-evidence.json`。

使用同一条清洁用品实录及校对词轴。「如果还能下单的」从 45.810 至 46.730 秒，后续行动从 46.890 至 48.050 秒。组合任务 `d7ccd08c-37e2-447c-9a7b-ac85159bb271` 筛除只显示抢购动作的 BG-S04 候选。把前提放在原景、行动单独做花字的独立语义任务 `27a507ac-95c3-444b-b92f-ef5a4926bb25` 返回 `EDITING_CONDITION_ANCHOR_INCOMPLETE`，未创建剪辑任务，重放未再次调用响应来源。保留条件的组合任务 `84bd0ea1-48eb-4587-91e6-531a5b7d64f2` 自动接续原生任务 `9e8cd35c-2762-4992-bcca-6af8a9676696`，AHG-S02 分别绑定「如果还能」与「下单」共六个原词点，成片 46.88 秒抽帧中两槽与主字幕可同时核对。

Chrome 显示两类拒绝原因，播放代理并确认、实播及下载 768×1366 高清。代理及母版范围请求为 206，整片 48.475 秒完整解码，含十种动效、十五次出现、17 条原库提示音及一首背景乐。独立 worker 新任务重新渲染同一原片与完整编排，高清摘要与上一轮一致。样片为 `C:/tl/motion-condition-guard-20261110/website-condition-preserved-hd.mp4`，同目录保留 `planning-evidence.json`、`native-evidence.json` 及 `delivery-evidence.json`。361 项相关回归和 38 项最终专项复验、目标 Ruff、mypy、前端类型、ESLint 及原包 1,426 项完整性核对通过。沿用本地回放响应，整片视听和当前真实模型选组仍待验收。

## 实录时序的独立听标复算

在 `backend` 下运行以下命令，可用同一份独立听标对自动识别、校对后强制对齐各跑一次。报告记录原片、实际 WAV、转录、标注的摘要和识别版本，换一版词轴就写新报告。输入 `prepared.json` 使用对应 worker 回执。标注以分析 WAV 的零点计时，工具用回执的实际偏移对比原片词轴，并核对 WAV 时长和摘要。

```text
python -m scripts.audit_motion_alignment --prepared prepared.json --audio speech.wav --transcript transcript.json --reference human-marks.json --out timing-report.json
```

先听原声，分别标记关键词首和整句首尾。标签按原话、出现次序及实际总次数定位，精确到已测的词边界，不在一个词内分摊毫秒。重复词次数不符、字落在识别单位内部、人工句界与整句切分不同均单列并计入标签总数。词首阈值 150 毫秒，句首和句尾各 300 毫秒，恰好等于阈值仍在容许范围。报告区分可测标签、超差、无法匹配和只标了一个类别的样本。来源字段区分人工听标与技术诊断，命令不更新网站审查状态。

用 48.475 秒上传实录和 40.627 秒数字人口播实际运行命令。两条均从网站登记的识别和强制对齐产物核对摘要，样本目录为 `C:/tl/motion-timing-calibration-20261110/validated`。两份 `blind` 分别保留同源 WAV 和空人工标注模板，听标者无需打开机器时间轴。诊断把自动识别的 6 个词首及 41 个机器分句作为技术对照。对同一词轴回读的误差为零。对两份校对后词轴，6 个词首均可匹配，其中 3 个相差超过 150 毫秒，最大 479 毫秒。41 个机器分句中只有 1 个与校对后的整句文本及切分相符，其句尾相差 560 毫秒。其余单列为文本或切分差异。两套机器结果分歧用于定位优先听标位置。

两条实录分别注入 310 毫秒偏差，全部诊断词点被判超差。替换 WAV 摘要后拒绝评分，也未写出报告。核对回执为同目录 `diagnostic-evidence.json`。364 项剪辑、文稿及原库回归、目标 Ruff、mypy 及原包 1,426 项完整性复核通过。本次未出新片或发起付费调用。两份样本尚无人工标注，150 毫秒词首和 300 毫秒句界目标仍待人工基准校准。

## 恢复文案时保留该版写稿来源

文案历史中的「恢复此版本」按同一项目下的历史版本编号保存新草稿。项目先保存当前待同步内容，再按所选历史快照恢复正文和该版绑定的参考原文、拆解报告、事实卡、采用草稿。服务端对照已保存快照，拒绝改动正文后提交的恢复请求、跨项目版本及过期项目修订。恢复没有生成任务。重试沿用原请求编号，避免重复保存。普通手动改回相同文字继续按普通保存处理。OpenAPI 增加可选恢复字段，省略该字段时沿用旧请求摘要，数据结构无需迁移。

在隔离数据库副本保存一张更新的测试事实卡，再在 Chrome 从历史选中旧确认稿，恢复及刷新。旧稿和旧事实卡随新草稿 `165a3f31-1db6-4dff-aaff-f00788e69d09` 一并读回。重复提交返回同一个草稿，原确认记录逐字段一致。经正常生成入口确认后得到新版本 `62f551a3-da96-4003-a407-98f636767b0b`，下载的旧版 handoff 合同及朗读文字核对通过。生成服务在本地回放已存在的实录片段。独立剪辑任务 `9fe2d72d-18ea-480e-b40a-b6c39d8c0cfa` 从实际录音识别 24 个词点，回执关联新确认稿和旧事实卡，分析原声范围请求返回 206。该任务只运行到转录就绪。

回执为 `C:/tl/writing-restore-20261110/delivery-evidence.json`。419 项后端回归、最终 4 项写稿专项、8 项前端会话测试、目标 Ruff、mypy、前端类型、ESLint 与 OpenAPI 复算通过。原 Motion 1,426 项及原写稿 33 项完整性复核通过。没有新增付费请求。本轮验证历史恢复及下游来源继承，真实模型写稿与整片验收仍待完成。

## 交付前核对最终音轨

独立剪辑 worker 在母版交付前，以实际原片独立解码口播，按原生音量和整片时长与原声分轨比对。以 48 kHz 逐个 250 毫秒窗口核对实际 AAC 解码与原声、提示音、背景乐分轨的相加结果。另核对音画轨起点、音轨时长和所选分轨在编码母版里的波形贡献。安静窗口有绝对误差容限，允许不足一个 AAC 帧的末尾填充，不延长审核范围。用户关闭背景乐时按无音乐方案校验。失败时保留剪辑任务并显示声音核对错误。代理继续复制同一编码音轨，校验规则纳入任务恢复摘要。原生提示音素材、处理后片段及可见入场帧仍通过现有独立回执核对。

在 169 份拥有对应原片、分轨及母版的 Windows 历史成品上复算。另有 49 个归档条目缺少可比较文件，单列未测。对 48.475 秒清洁用品母版制作五个只供诊断的故障副本。分别省掉背景乐、提示音，删掉 39.20 至 39.65 秒的口播，把 2.30 秒的单条提示音后移 220 毫秒，以及将整条音轨延迟 200 毫秒。五个副本都在交付校验返回 `EDITING_SOUND_OUTPUT_INVALID`，均未写入交付回执。记录为 `C:/tl/motion-master-audio-20261110/archive-mix-evidence.json` 和 `fault-evidence.json`。

Windows 独立任务 `e04f4e22-61d5-4d25-908a-6e5ab4eefd75` 从同一实录和冻结编排重新编码 10 种、15 次原生动效，含 17 条提示音和一首背景乐。比较 2,326,800 帧音频样本，母版相对三条分轨的全片误差为 −32.98 dB。Chrome 实播、确认、下载 768×1366 母版，代理及母版范围请求返回 206。下载摘要与同输入上一版一致，完整解码通过。文件为同目录 `website-verified-audio-hd.mp4`。该次验证使用本地回放规划响应，发生在下面显式固定声道的改动之前。

Linux FFmpeg 5.1.9 的实测旧母版将立体声提示音折到单声道，提示音相对预期立体声波形的投影增益约为 0.173。网站适配对已固定摘要的原生 episode 输出，在原声、背景乐分轨及母版输出三处声明立体声。原剪辑图的原声范围、原生素材、音效时间及增益不变，原包源码保持原样。取同一 Linux 原片、原生混音图和 16 条已生成提示音复算，立体声母版的提示音投影增益为 0.999，背景乐为 0.993，整片相对混音误差 −33.55 dB。回执为 `linux-diagnose.json` 和 `linux-remix-evidence.json`。另将 Windows 母版交给 Linux 解码器复验时发现原声分轨存在解码器差异。当前逐样本原声校验以同环境原生渲染及解码为准。

断网 Linux 容器从已冻结的 HY-A2 实录词轴重新提交任务 `174d493b-c2f0-4742-967d-db323c620782`，独立 worker 生成 48.475 秒立体声成片。共有 11 种原生动效、16 条原库提示音及一首背景乐。与上一版对照，提示音资产、处理后片段摘要及起音逐条一致。HY-A2 三条音效仍位于零基成片第 1194、1206、1230 帧。右下原生窗口仍为 597×906，三处同期人物横纵倍率均约为 0.47，进出场恢复全幅。前后视频流摘要不同，整片对比的 SSIM 为 0.999435。容器 Chromium 实播、确认、下载 768×1366 母版，代理和高清范围请求返回 206。下载件完整解码，复制到本机后摘要再次一致。文件为 `C:/tl/motion-master-audio-20261110/website-linux-stereo-a2-hd.mp4`，SHA256 为 `a23742d61507e9067cbfb4df38f2ba5a4e05dfbdcc8c5e5592ae89b38ff18f7a`。同目录有 `linux-website-evidence.json`、`linux-geometry-evidence.json` 和逐帧 `linux-frame-ssim.txt`。

424 项相关后端回归、目标 Ruff、mypy、前端类型及 ESLint 通过，原 Motion 包 1,426 项摘要复核通过。无新增付费请求、部署或数据库迁移。本轮验证原生声音混音与网站交付，沿用保存的编排，整片听感及真实模型选组仍待验收。

## 保留原片实测的口播起点

原片音画流标记不一致时，worker 读取首个实际解码音频帧，相对原视频起点记录毫秒偏移及 48 kHz 样本偏移。转录用完整分析 WAV，词点按同一偏移映射到原片。原生导出的任务内声音图按样本保留音频的实际位置，晚起点在原声分轨保留前置静音，早起点只收去已逐声道验证的画面前静音。超过 20 毫秒的相对偏移还要求容器给出可测的画面时长与帧率，自动处理上限为 500 毫秒。画面起点沿用既有 20 毫秒准入边界，画面外有可听原声时停止并显示原因。整片声音校验单独解码原音并按样本索引比对，和原生图的移位操作分开。已确认历史作品继续按原版本读取，重新交付以本版声音校验为准。没有数据库迁移。

真实口播测试件保留原视频流，将首段安静区后的原音封装为起点 0.240 秒的 PCM 轨。对照原音时钟，最后实录词仍落在本次媒体的原有时长内。另制作两份画面晚 15 毫秒的实录输入。一份首段无声，按 −720 样本位移通过原生字幕渲染和母版比对。另一份首段保留实际人声，准备阶段拒绝，无产物。另取同一实录的 VP9/Opus WebM，容器音轨起点为 −7 毫秒，首个实际音频帧从零开始，按零偏移处理。700 毫秒测试输入进入时钟复核。时钟边界回执为 `C:/tl/motion-source-offset-20261110/clock-boundary-evidence.json`。

240 毫秒样本经网站上传，独立 worker 实际识别及强制对齐。对齐后有 240 个词点，首词从 0.410 秒开始，末词至 48.050 秒。基于该词轴回放已保存的候选选组响应，得到新原生任务 `fcb7081e-c7b2-48fc-9c73-ea4a89b00d49`，共十种动效、十五次出现、17 条原库提示音和一首背景乐。合成回执记录 11,520 样本的偏移。独立对照首段为零 PCM，之后五处实录波形误差均低于 −104 dBFS。把同一母版按错误的零偏移复核时，原声比对拒绝。回执为同目录 `native-evidence.json` 和 `source-voice-evidence.json`。

Chrome 显示画面前有原声的拒绝原因，转录校对页在第三句按分析 WAV 的 2.550 秒定位。组合任务完成后，Chrome 播放代理、确认、实播并下载 768×1366 母版。两种产物均支持 206，母版完整解码并核对摘要。文件为 `C:/tl/motion-source-offset-20261110/website-source-offset-hd.mp4`，SHA256 为 `cc0af8613e9dd1c1fd450ae023aca37630fa5e574db0e0ae7a8b85c6b112f9f3`。同目录保留 `delivery-evidence.json`。428 项相关后端回归、最终 48 项时钟专项、目标 Ruff、mypy、前端类型和 ESLint 通过。原 Motion 包 1,426 项摘要复核通过。未新增付费调用，本轮验证实测时钟及网站出片，真实模型语义与用户视听仍待验收。

## 2026-11-11 HY-A2 右下人物窗重渲验证

用户明确原版右下角位置和人物遮挡层级可以保留，人物按原比例进入窗口。复核原包 `scene-l-a2-mock.svml` 的 `fg` 坐标为 `[483, 1014, 597, 906]`。用户引用的 `hypit-a2-natural-20261110` 下载件使用历史全幅前景。当前适配以原窗口和层级合成 597×906 的等比透明轨，原生斜卡和前景按原顺序叠放。

以已保存的编排和同一实录重提 Windows 本地任务 `54c5527e-b950-4029-b41c-d5ed032f02d5`。独立 worker 生成 48.475 秒母版，含 11 种原生动效、16 条提示音和一首背景乐。对网站实际下载件在 39.43、40.40、42.00 秒与同期原片做局部特征配准，两轴倍率均约 0.47，轴间相对差最大 0.84%。38.80 与 43.60 秒恢复原片尺度。片段内连续 108 帧人脸区域均发生变化，原声与独立解码的实录通过整片样本比对。HY-A2 的三条提示音起点为 39.80、40.20、41.00 秒。

Chrome 实播代理，确认后实播并下载 768×1366 母版。两种产物均返回 206，母版完整解码和摘要核对通过。新下载件为 `C:/tl/hypit-a2-native-window-20261111/website-a2-original-window-hd.mp4`，同目录保留 `geometry-evidence.json` 和 `browser-evidence.json`。原包 1,426 项完整性复核通过。此次使用已有编排验证模板适配与交付，用户视听待验收。

## 重新规划时继承已确认的局部调整

在已经验证的人工调整版代理上选择「将人工调整带入另一份规划」，再从同原片的已完成规划选择新版本。服务端核对代理文件、项目、实录词轴和组合模板，按首末实录词 ID 映射手动片段。动效、文字和图片的调整还要求该段的原生槽位及绑定兼容。没有指定替换曲目时，降低背景乐须对应相同的原配乐。片段被拆合、移除或已经转成原景，或者槽位变化时，页面提示冲突并保留原代理。成功时，新剪辑任务记录前版代理摘要、所选规划及受保护片段，新版和原版分别可见。选择已有规划这一步只提交渲染任务。接口沿用现有任务表，无新增迁移。

使用已有的 48.475 秒口播、实录词轴和本地回放的两份规划响应。Chrome 显示拆合冲突，服务端拒绝错误的代理摘要。兼容版本重复提交返回同一个任务。独立 worker 完成 `29c7247f-9fab-4166-8dbc-18311896c037`。3.750 至 5.710 秒仍按人工设置使用原景，片段编号从 `effect-3` 映射为 `effect-0`。沿用背景乐降低 6 dB 的设置，原声分轨摘要一致。未锁定的编排可变化，动效从九种十四次变为九种十三次，母版含 15 条提示音和一首背景乐。Chrome 实播代理、确认、实播并下载 768×1366 母版，旧代理仍可见，下载件完整解码并核对摘要。回执为 `C:/tl/motion-replan-edits-20261111/browser-submitted.json`、`native-evidence.json` 和 `browser-evidence.json`。

432 项相关后端回归、目标 Ruff、mypy、前端类型与 ESLint 通过。图片、文字及动效替换的跨编排映射有合同测试覆盖，此次浏览器实跑覆盖原景和背景乐。原包 1,426 项摘要复核通过。此阶段使用本地回放规划，无新增付费调用。真实模型语义和用户视听待验收。

## W-R15 的原动作与实录词首对应

多角色模板准备阶段从同一份实际词轴识别按序出现的关门、交接和禁行短语。只选已测量的词首，原词拆成多个识别单位时仍保留首个真实词点。否定关门或交接、动作顺序颠倒、找不到完整组合时跳过 W-R15，其他同模板动效照常可选。三类短语使用有限规则，未能识别的措辞进入普通模板候选。原生编译独立复核三条绑定并沿用原共享切点、插画槽和声音时钟。已保存的规划请求仍按其冻结字段重放，新出片的 W-R15 须通过词点校验。配图内容与流程的语义仍要按本期素材核对。

在原本机合成流程口播的已测词轴上，正确计划从「关上门」「开始交接」「禁止跳过验收」分别取词首并通过原生候选登记。将关门动作与共享切点同时挪到前句「稿」字时，规划以 `EDITING_ROLE_ACTION_ANCHOR_INVALID` 拒绝，未创建剪辑任务，直接编译也拒绝。回执见 `C:/tl/motion-role-word-anchors-20261111/role-evidence.json`。此正例验证到候选登记。

另在隔离项目为实际桌面收纳口播登记 16 张流程图作为反例。页面说明 W-R15 因实录动作不足被跳过。使用同一组合模板与保存的候选响应，独立 worker 重新编码任务 `62d761a6-4c8a-4112-a0bd-bf0271d80e8a`，整片 40.123 秒，含十种原生动效、15 条提示音和一首背景乐。Chrome 实播代理，确认后实播并下载 768×1366 母版。范围请求返回 206，下载件完整解码，摘要与同原片和同选组的早期技术对照一致。新任务产物为同目录 `website-desk-role-safe-hd.mp4`，另有 `submitted.json`、`knowledge-native.json` 和 `browser-evidence.json`。

437 项相关后端回归、最终专项复验、目标 Ruff、mypy、前端类型和 ESLint 通过。原包 1,426 项完整性复核通过。本轮使用保存的转录和本地回放规划，实际模型选择及用户视听待验收。

## 按原片显示旋转进入竖屏剪辑

上传原片带标准显示矩阵时，转录和规划按实际显示方向记录画幅。自动处理可核对的整四分之一圈旋转和对应的原点平移。镜像、剪切、缩放及无法确认的旋转进入复核。旧转录缺少显示变换校验记录时，新规划在请求模型前重新探测已核对摘要的原片。原生帧采样使用任务内已转正的 30 fps 画面副本，原始文件和口播声轨仍是各自验证依据。最终高清校验确认显示矩阵和编码尺寸。原版适配仍在相同的音画时钟上导出。 [FFmpeg 显示矩阵](https://www.ffmpeg.org/doxygen/trunk/group__lavu__video__display.html) · [FFmpeg 旋转输入选项](https://ffmpeg.org/ffmpeg.html)

对实际 48.475 秒清洁用品口播制作一份技术输入，画面编码为 1366×768，加 90 度显示矩阵后为 768×1366，原 AAC 流摘要逐字节一致。镜像反例在准备阶段返回旋转复核，未发布转录或成片。正例从网站上传，经本地 FunASR 和实际强制对齐得到 240 个词点。独立 worker 重新编码任务 `c20ec631-459b-4c64-9a5c-a7e4d3d7ed08`，成片含十种原生动效共十五次、17 条原库提示音和一首背景乐。原声分轨与独立解码的整段误差低于 −138 dBFS。人物采样副本从 1,163 个源帧生成 1,454 帧，记录实际显示尺寸和原件摘要。

Chrome 显示镜像拒绝原因，随后实播代理、确认、实播并下载 768×1366 高清。代理和高清返回 206，下载摘要与服务端一致并完整解码。五处同时间点对比显示原片和任务画面副本的八位通道平均像素差均小于 0.90。三处下载件的同期人物抽样误差小于 1.42。另用断网 Linux worker 镜像复测同一输入前两秒的转正，实际解码 60 帧且尺寸一致。下载件为 `C:/tl/motion-display-rotation-20261111/website-upright-native-hd.mp4`，同目录有 `native-evidence.json`、`orientation-evidence.json` 和 `browser-evidence.json`。Linux 复验范围限于画面转正。

442 项相关后端回归、目标 Ruff 和 mypy 通过。原包 1,426 项摘要复核一致。规划响应使用本地回放，视觉与听感待用户验收。复核 132 组目录与 42 套网站组合模板，后者仍覆盖 125 组可选动效。四个浏览器组及 HY-A1 的原件或授权继续单列，水果专用组保持下架，Z-M00 继续作为原景使用。

## 逐句修订草稿时保留事实来源

「拆解与事实写稿」中的已保存草稿可以修订标题、正文及每句引用的事实。「借鉴结构创作」允许在同一段落拆句或合句，仍须顺序覆盖原拆解。「按原结构改编」保留原句对应关系并再次运行同事的原检查器。修订使用该草稿冻结的原文、拆解和事实卡，继承其缺失事实、禁词、替换限制及口播字数预算。对于后来重新出现的原文事实，沿用该草稿最初的替换约束。检查通过后另存草稿，记录父稿及三份来源资料的摘要。重复保存回读同一版本。采用、确认及生成继续使用各自入口，修订没有外部模型请求或数据库迁移。已有确认稿及 handoff v1 可照常读取。

在独立数据库副本复用已保存的逐句稿。修订后通过同事的原 `shadow_check.py`，核对逐句回执和三项替换。把一个额外口播句塞入同一个原句槽时，即使事实映射通过，也由原检查器拒绝。同一请求回放读取同一草稿，回执见 `C:/tl/writing-draft-revision-20261111/shadow-evidence.json`。

Chrome 在结构稿中将一句拆成两句，分别勾选原事实卡的价格与包装。直接改用较新事实卡里的价格时，保存被拒绝，编辑内容仍可修改。保存成功后重复请求返回同一草稿 `92648f41-6d5b-41fb-ab69-7da40a1e65a0`，原稿及先前确认稿均可回读。采用新草稿后，确认稿 `feca13b8-92a3-40c1-94c8-891eca199d6e` 与 handoff v1 正文一致。为校验接口，生成阶段在本地回放既有 4.833 秒真实口播，本次改稿只调整断句，实际口播文字一致。

独立 worker 处理任务 `a8d37c82-f640-48e1-a283-b2d2f06e52f3`。FunASR 从原片转录得到 24 个词点。剪辑源回执可核对原事实卡、修订草稿及确认稿。Chrome 实播并下载原生字幕成片，范围请求返回 206。下载件 768×1366，音视频完整解码，摘要与服务端一致，原声分轨误差为 −138.492 dBFS。下载件为 `C:/tl/writing-draft-revision-20261111/website-revised-writing-hd.mp4`，回执为同目录 `revision-evidence.json` 和 `delivery-evidence.json`。

443 项相关后端回归、目标 Ruff、mypy、前端类型和 ESLint 通过。动效原包 1,426 项、写稿原包 33 项完整性复核通过。两种改稿方式均用原事实卡约束修订，事实真实性仍由使用者核对。本次生成使用本地回放，字幕和听感待验收。

## 原片上传回执中断后的恢复

原片上传支持可选请求编号，工作区和用户范围内复用同一原片记录。重传时核对项目、确认稿、媒体类型、字节数和摘要。并发上传使用各自的临时文件，只保留成功登记的原片。确认已登记的文件缺失或发生变化时要求重新选择。没有请求编号的调用沿用既有行为，无新增数据库迁移。

网站在同一次文件选择期间复用上传请求编号。上传回执丢失时，可在页面重试，或改选识别口播和基础字幕中的另一个入口。剪辑任务提交使用单独的请求编号，提交回执丢失时重试同一配置即可回到同一任务。已收到任务回执后，页面直接显示任务并由现有轮询更新。刷新页面后需要重新选择本地文件。数据库提交结果无法判断时暂时保留该次写入文件，避免删除可能已经入库的原片。

Chrome 选择真实口播短片。本地转发层分别在上传和剪辑提交成功入库后断开连接。页面显示两类可重试提示。从识别口播改选基础字幕时，原片请求编号和原片摘要一致。再点基础字幕时，剪辑任务编号也一致。数据库和任务卷最终分别只有一条原片记录、一个原片文件和一个剪辑任务 `5500d2e8-f5ef-4cec-b4c4-d564e36df4ec`。两套 API 实例并发提交同一编号的测试验证了主键争用后读回同一结果，且只有一个文件。换项目、内容或媒体类型均返回冲突，已登记文件发生变化时也拒绝重放。

独立 worker 一次完成恢复后的任务。实际 FunASR 转录得到 24 个词点，原库导出 4.833 秒的 768×1366 字幕片。Chrome 从项目剪辑页实播和下载，范围请求返回 206，下载摘要与服务端一致。音视频完整解码，原声分轨误差为 −138.492 dBFS。此次使用同一真实口播短片，独立重新渲染得到与前次字幕样片相同的成片摘要。下载件为 `C:/tl/editing-upload-retry-20261111/website-upload-retry-hd.mp4`，同目录保留 `recovery-evidence.json` 与 `delivery-evidence.json`。

444 项相关后端回归、两实例并发专项、目标 Ruff、mypy、前端类型、ESLint 和 OpenAPI 更新通过。动效原包 1,426 项完整性复核通过。本轮验证基础字幕链路的故障恢复，无新增付费调用。

## 保留实录中的数量范围和限定词

按实录词点识别显式区间、比例、百分比说法、上下限、约数和起售限定。原生文字、规划强调词及手动换词都核对该表达的首尾词。普通精确数值仍可按原合同使用配对数值和单位槽。遇到受保护的完整短语，候选字槽放不下时筛除该候选。中文数字比例中的原冒号保留。检查覆盖已列明的常用表达，口语隐含范围继续由语义验收核对。

网站准备的新请求会在原词轴上标明受保护范围。产品讲解和知识口播使用原零基词序，其他规划使用实际词 ID。自动提供的字数与读时示例也排除截断表达的片段。两份旧的紧凑和完整合同请求仍按各自冻结内容与摘要回读。已生成的旧成片可照常读取，新渲染仍复核内容。本次无新增数据库迁移。

在同一清洁用品实录及 240 个已保存词点上，17.850 秒起的「足足4斤」占四个词点。原 SG-S09 的总量槽只能容纳两字，本次保持原槽。旧式截断候选在产品讲解中被跳过，独立语义模式返回 `EDITING_QUANTITY_ANCHOR_INCOMPLETE`。本地回放候选将该段交给原 AH-S05 的四字强调槽。两种请求都实测标注正确范围，紧凑请求的提示样例中没有截断该短语。记录为 `C:/tl/motion-quantity-scope-20261111/planning-evidence.json` 和同目录的 `legacy-request-evidence.json`。

独立 worker 导出任务 `68ca2cf9-b423-4c3f-8b03-80f61e1bdad9`。整片 48.475 秒，使用九种原生动效、十五次出现、17 条提示音和一首背景乐。原生文字绑定了第 86 至 89 个零基词点，18.8 秒实拍抽帧可见完整字效、人物和主字幕。原声分轨相对原片的峰值误差为 −138.49 dBFS。试跑时一次更改提示文案造成来源复核拒绝，保留原提示后重试同一任务通过。原库 1,426 项完整性核对通过。457 项相关后端回归及目标 Ruff、mypy、前端类型和 ESLint 通过。本次用实际词轴和本地回放规划，真实模型选择及整片视听待用户验收。

Chrome 显示两类候选拒绝提示，实际播放 358×640 代理，确认后播放并下载 768×1366 母版。代理及母版范围请求均返回 206，下载摘要和完整解码通过。交付件为 `C:/tl/motion-quantity-scope-20261111/website-quantity-scope-hd.mp4`，同目录有 `delivery-evidence.json`、`native-evidence.json` 和 18.8 秒抽帧。

## 并列事项分别绑定实录词点

已有并列关系的原生动效逐项核对本段词点。每项至少绑定一个原生文字或素材槽。各项按实录顺序使用互不重叠的范围。同一短语在实录中确实重复时，可以按各次词点分别绑定。原场景允许多张插画共用一句话的顺序叙事仍由该组合同核对。模板候选发现重叠时筛除该段，独立语义计划返回 `EDITING_PARALLEL_ITEMS_INVALID`。编译沿用同一规则。无新增数据库迁移，也未改原生模板槽位和动作。

从已完成的清洁用品编排取同一真实词轴，给原 AH-S05 的两个字槽分别登记相同的第 69 至 92 个词点。旧版语义和模板候选检查都接受，见 `C:/tl/motion-parallel-anchors-20261111/prior-bypass.json`。另复查 162 对历史规划和转录中的并列关系，103 段通过新规则，未配对的历史记录另计。复查仅覆盖并列项的词点和原生绑定。

同一口播通过网站 API 再提交上述反例。独立规划失败，未创建代理。产品讲解组合筛掉该候选，保留九种动效和十四次出现。桌面口播反例将前后两项共享一个词点，网站规划拒绝。原始正例分别绑定第 114 至 115、116 至 118、120 至 121 个零基词点，原 Z-M14 继续按原词槽和入场事件编译。API 回执为同目录 `negative-evidence.json`、`archive-evidence.json` 和 `submitted.json`。

独立 worker 重新渲染任务 `199f9654-354d-492e-81d7-716bae6705e2`。原生场景在 22.110 至 24.570 秒编入「书桌」「办公桌」「桌面」，24.18 秒抽帧可见三项。40.123 秒母版包含十种原生动效、15 条提示音和一首背景乐，原声分轨峰值误差为 −138.491 dBFS。Chrome 显示反例拒绝提示，实播代理，确认后实播并下载 768×1366 母版。两种产物范围请求返回 206，母版完整解码，摘要与服务端及同编排先前实片一致。本次产物从当前任务重新编码，用于核对有效编排的兼容性。

下载件为 `C:/tl/motion-parallel-anchors-20261111/website-desk-parallel-verified-hd.mp4`，同目录有 `browser-evidence.json`、`knowledge-native.json` 及抽帧。458 项相关回归、目标 Ruff、mypy、前端类型与 ESLint 通过，原库 1,426 项完整性复核通过。本轮使用真实词轴及本地回放规划，实际模型的关系判断和整片视听仍待验收。

## 从我的作品定位一条历史剪辑

「查看本条剪辑」携带项目编号和任务锚点。项目页先读取最近 100 条，链接所指的任务不在列表时按编号补查，并滚动、聚焦到对应任务。详情接口支持同时校验项目，仍沿用工作区及用户的访问检查。项目里的父版与代理任务链接也共用定位逻辑。最近任务的产物批量读取，日期相同时用任务编号稳定排序。未保存项目先等待项目就绪。

项目页的成片与代理改为用户点播时读取媒体。现有预览确认、成片文件摘要检查、字幕试听定位和下载入口继续沿用。旧版项目打开到首次展开规划面板之前，真实转发日志中已有九个不同任务的媒体请求。本轮使用隔离数据库副本复验历史交付，无数据库迁移。

在真实项目的数据库副本加入 55 条无媒体的已取消测试记录，早期任务 `19b7c8a0-dd49-49f9-bc15-9a5f744f01ba` 因而超出最近 100 条。实测最近列表用一次任务查询及一次产物查询，显示 37 张有真实媒体的卡。Chrome 从另一个已保存项目的「我的作品」翻页找到该条，跳转后聚焦到旧任务。点播之前记录到零次剪辑媒体请求。证据见 `C:/tl/editing-delivery-focus-20261111/sql-evidence.json` 及同目录的 `initial-navigation-evidence.json`。

Chrome 实播该 720×1280 历史母版，拖到 6 秒后继续播放并下载。另用同项目内的任务锚点定位 360×640 代理并实播，代理卡保留待确认状态，未开放高清下载。母版与代理均收到 HTTP 206。字幕校对按钮从尚未预载的播放器跳到 12.51 秒开始播放。下载件为 `C:/tl/editing-delivery-focus-20261111/website-history-focused.mp4`，SHA256 与服务端一致，完整解码通过。回执见同目录 `playback-evidence.json`。本轮验证已交付媒体的定位、回放和下载。

在独立 Chrome 标签使用错误项目与该任务编号组合，详情返回 404，页面显示原因，未加载任务卡或剪辑媒体。最终回执为同目录 `delivery-evidence.json`。458 项相关回归、目标 Ruff、mypy、前端类型与 ESLint 通过，OpenAPI 与前端类型已更新，原库 1,426 项完整性复核通过。

## 原库编码证据跨任务卷共用

原库目录、动效详情和新规划准备统一按原库版本读取编码记录。API 和规划 worker 可设置同一个 `POLARIS_VIDEO_EDITING_LIBRARY_EVIDENCE_DIR`。该变量指向版本子目录的父级，当前版本为 `c10429057a86`。未设置时继续读取任务卷下的 `_library-validation/<版本>`。本地 Compose 可用覆盖配置将证据父目录只读挂载到两个服务的同一容器路径，并将变量设为该容器路径。已保存规划继续沿用各自冻结的记录。

`audit_motion_library.py` 可通过同名变量向版本子目录登记真实原生回执，原有 `--state-dir` 仍可指定完整的版本目录。登记进程需要该目录的写权限。用已完整解码的 AH-S03 A 版原生回执实测登记到独立目录，未改原 ZIP 和现有回执。

在已有清洁用品口播项目的数据库副本和独立任务卷中复现。旧默认路径在该卷显示 132 组待实测。指定原证据目录后，API 的 132 条目录及新规划准备任务 `65bfe9f7-6de6-4c2d-8dfb-ae463fddf927` 的冻结快照逐组一致。准备请求保留全部 132 个组 ID，组合模板的 16 组编码状态与快照一致。116 组有成功样本，11 组同时有成功和失败记录，5 组待实测。AH-S03 的 A 版有编码证据，B 版仍待实测。169 份原记录的摘要在读取前后相同。画面验收仍为 0 组。

Chrome 在项目加载完成后展开原库目录，核对汇总、HY-A2 编码未验收、HY-A1 待实测和 AH-S03 两个原始版本的不同状态。API 与浏览器的回执为 `C:/tl/motion-shared-evidence-20261111/registry-evidence.json` 和同目录 `browser-evidence.json`。

本轮验证跨卷读取与登记，沿用真实口播和已有对齐结果。459 项相关回归、目标 Ruff、mypy 和 Compose 配置解析通过。无数据库迁移和新增模型调用。

## 工作目录创建失败后重试原任务

两条独立 worker 队列领到任务后，在租约检查及异常处理范围内建立本次工作目录。创建失败会同时结束任务和本次尝试，清除租约并返回 `EDITING_TASK_STORAGE_UNAVAILABLE`。页面提示存储恢复后重试。尝试目录无法写入时，数据库状态照常保存。规划失败若无法读取文件回执，也先保存任务状态。重新提交使用原任务编号、原片和已冻结输入。

旧代码在两项文件系统回归中都直接抛出建目录异常。修复后，在真实清洁用品口播项目的独立数据库副本中，用两个单独的 Celery 进程和 Redis 8.8.0 复验。测试仅在两条新任务的目录位置放置阻断文件。剪辑任务 `fc85606c-6a65-436d-8508-4d1dc3418b76` 和规划准备任务 `c1120db8-d6c4-4445-8c21-478e039719bb` 均在第一次尝试明确失败，清除租约且未发布产物。移除阻断文件后，通过 API 重试原编号。规划第二次到达已准备，未提交模型请求。

剪辑第二次完整编码 15 段原生画面，48.475 秒整片含 9 种动效、15 次出现、17 条提示音和一首背景乐。代理及确认后的高清均返回 HTTP 206。新下载件完整解码，SHA256 与服务端及同输入的前版母版一致。成片为 `C:/tl/motion-storage-recovery-20261111/website-storage-recovered-hd.mp4`。故障及交付回执为同目录 `failure-evidence.json`、`delivery-evidence.json`。本轮使用已有规划复跑原生编译与交付，原包 1,426 项摘要复核通过。

Chrome 从项目中的原任务实播 768×1366 母版，跳到 18 秒继续播放并下载，下载摘要与 API 一致。浏览器回执为同目录 `browser-evidence.json`。461 项相关后端回归、目标 Ruff、mypy、前端类型与 ESLint 通过。无数据库迁移、部署或新增付费请求。真实模型规划及用户视听验收仍待完成。

## 从历史确认稿与剪辑回查写稿来源

文案版本与带确认稿来源的剪辑任务可按需查看该版参考原文、拆解、事实卡及采用草稿。草稿逐句显示所对应的原句或拆解功能，并列出绑定的事实。只读接口按工作区、用户、项目和文案版本查询。服务端核对采用记录、原草稿、确认稿正文摘要、来源文档摘要和写稿时冻结的输入摘要。恢复成的新草稿仍可回查原采用记录。直接手填相同正文的版本沿用无采用来源的状态。

从已有真实口播项目复制独立数据库，加入 205 条较新事实资料。历史确认稿 `feca13b8-92a3-40c1-94c8-891eca199d6e` 的资料已不在最近 200 条列表，按版本仍能读取修订稿及其原事实卡。另回查此前确认稿，返回各自的原稿。独立对照剪辑任务 `a8d37c82-f640-48e1-a283-b2d2f06e52f3` 的原片回执，以及 handoff v1 的确认稿编号与正文。该次读取在写稿生成关闭时完成，原写稿包 33 项摘要通过。回执为 `C:/tl/writing-version-sources-20261111/api-evidence.json`。

专项验证跨用户和跨项目请求无权读取。事实卡正文及其行内摘要一同改动后，冻结的输入摘要仍能识别变化。461 项相关后端回归、最终 5 项写稿专项、目标 Ruff、mypy、前端类型与 ESLint 通过。OpenAPI 及前端接口类型已更新，复算 OpenAPI 字节一致。本轮验证已交付口播的来源回查，无数据库迁移、模型调用或新渲染。

Chrome 从「文案版本」和该历史成片的剪辑卡分别展开四类资料，显示同一份历史确认稿的原文、报告、事实卡和逐句草稿。两次页面各在展开后发起一次来源请求。回执为同目录 `browser-evidence.json`。

## Hypit 出片前统一运行预检

网站的候选列表、剪辑提交和独立 worker 共用原 Hypit 工具检查。核对内部开发工作区、CLI 版本和摘要、Node.js 版本、浏览器入口及 Hyperframes 固定版本。列表同一请求只检查一次。权限不满足时沿用原内部工作区限制。配置属于内部工作区但工具校验失败时，返回 `EDITING_HYPIT_RUNTIME_UNAVAILABLE`，候选与原库条目继续可查。提交和编译按应用局部修改后的活动段落判断是否需要 Hypit，已明确恢复原景的段落无需调用该引擎。

在真实 HY-A2 项目的独立数据库中，仅改动诊断副本的 CLI 字节。旧版本仍显示可出片并收下任务。新版显示当前不可出片，提交在入队前返回 503。错工作区仍返回原权限错误。配置经核对的原工具后可入队。旧样片中的 SG-S09 总量只显示「4斤」，在当前实录词点规则下被拦截。联调候选改用已经验证的 AH-S05 文字槽保留「足足4斤」，HY-A2 原生配方、词点和人物窗口保持相同。回执在 `C:/tl/hypit-runtime-admission-20261111` 的 `before.json`、`after.json` 及 `corrected-admission.json`。

合法编排的任务 `ebf01355-c411-409f-8101-07bdb0f1b820` 入队后，独立 worker 在使用同一诊断副本时拒绝编译，未发布产物。恢复经核对的 CLI 后，原编号重试并重新编码。48.475 秒成片含 11 种原生动效、16 条提示音和一首背景乐。HY-A2 原窗口为 597×906，39.43、40.40 和 42.00 秒人物横纵倍率均约 0.47。同期人物连续 108 帧可见变化，三条提示音在 39.80、40.20、41.00 秒进入。

Chrome 核对工具异常时预览按钮收起，原工具配置下重新可用，并实播、下载 768×1366 新母版。代理和高清范围响应为 206，下载摘要和完整解码通过。成片为同目录 `website-hypit-verified-runtime-hd.mp4`，另保存 `delivery-evidence.json`、`geometry-evidence.json` 和 `browser-evidence.json`。462 项相关后端回归、103 项专项、目标 Ruff、mypy、前端类型与 ESLint 通过。原 Motion 包 1,426 项摘要核对一致。此次沿用本地工程候选，未新增付费请求或部署，真实模型规划与用户视听仍待验收。

## 在高清成片上记录人工验收

已交付的成片卡可分别记录语义、时序、画面和听感，支持待验收、通过、需调整及备注。高清确认仍只登记交付。人工验收绑定可下载母版的产物编号和 SHA256，保存前核对任务归属、可见状态、解码记录及实际文件。验收记录保存在任务已有的检查点字段，无数据库迁移。原生校验报告和原库组件样本状态各自独立。

同一成片的相同提交可回读已保存结果。两个不同验收基于同一旧版本并发写入时，只提交一份，另一份返回 409。新生成的成片有独立验收记录。专项核对等待高清的任务、代理、其他用户、错误摘要、文件变化和过期写入均不能修改验收，已完成任务仍可从作品页下载。

Chrome 在数据库副本中从「我的作品」打开 48.475 秒的 HY-A2 成片 `ebf01355-c411-409f-8101-07bdb0f1b820`，实播至 40 秒后填写两项联调意见。转发层在服务端保存后断开首个回执。页面轮询读回已保存结果，重复请求未再次增加版本，刷新后备注和两项状态一致。该片和前一版分别保留状态，下载件与原母版摘要一致。原联调数据库仍无人工验收记录，测试标记只保存在隔离副本。证据为 `C:/tl/motion-film-review-20261111/browser-evidence.json`。

462 项相关后端回归、最终并发验收专项、目标 Ruff、mypy、前端类型与 ESLint 通过。OpenAPI 及前端接口类型已更新。本轮验证验收交付，沿用已有真实成片。

## 原字体及模型补件合并

在 `backend` 目录按资源 ID 预检交付文件。可重复传入 `--candidate`。报告列出原件摘要、字节数、原权利标记和本次文件身份状态。

```sh
python -m scripts.register_motion_local_dependencies --package <已安装原包> --bindings <现有私有绑定> --candidate <原资源ID> <补交文件>
```

核对完交付来源后加 `--provenance <交付记录>` 和 `--apply`。整批身份均相符才会合并。现有有效路径、其他资源、工具和浏览器素材登记继续保留。新增绑定保存交付来源与原始摘要。字体及图片补交共用写入锁，并在提交前复核清单版本。原件继续从持久交付目录读取。HY-A1 仍需原字体和适用的使用授权，再进行组件和整片验证。

用原 adapter 在一次性清单副本复现整份重建会清空其他字段。新入口以原 Arial 字体复验。干跑无写入，混入错误 HY-A1 字体的一批整体被拒绝。合并时保留 69 条浏览器诊断登记与原工具，重复合并摘要一致，实际联调绑定文件未变化。真实 AH-S03 A 版使用合并后的清单重新编码，576×330、30 fps、36 帧完整解码。该结果是字体补件和组件渲染验证。HY-A1 保持待实测，正式原库目录仍有五组待实测，1,426 项原包摘要核对一致。回执在 `C:/tl/motion-dependency-intake-20261111` 的 `intake-evidence.json` 和 `native-evidence.json`。

463 项相关回归、30 项补件与编译专项、目标 Ruff 与 mypy 通过。四组浏览器原图和相关字体仍按 `C:/tl/motion-original-drop-20261110` 的两份交付清单收件。本轮无部署或新增付费调用。

## 按现行词点规则重核已保存的模型响应

产品讲解和知识口播的已完成规划增加「按现行规则重核已保存响应」。服务端先核对原请求、实录转录、网关响应、合同回执及已归档语义的摘要，再用相同的实录词轴、模板、项目素材和备忘运行当前展开规则。默认采用遇到规则差异时提示重核。主动重核且结果有差异时另存编排，保留两版语义摘要和同一份网关来源；重复操作返回同一份编排。结果一致时复用原编排。独立剪辑进程在编译前重复核对新编排及来源，项目备忘变化仍须重新准备，至少五种动效的门槛继续适用。无数据库迁移。

以已保存的两次真实腾力网关响应联调，新增模型调用为零。产品讲解的旧编排有 10 种动效、15 次出现。重核筛掉了包括 SG-S09 截断实录数量在内的候选，得到 9 种、14 次，另存编排 `22167bb9-dea9-40b7-8560-f4ffcfdd496c`。知识口播的 10 种、10 次保持一致，复用原编排。核对旧请求、响应、合同文件、旧编排及已发布试片的摘要和可读性。损坏的档案或数据库中的错误语义摘要即使显式重核也会拒绝。

独立 worker 为产品讲解重新渲染任务 `eed93587-8f73-4a1d-95de-0614ea97cb5d`。本地网站确认后下载 48.475 秒、768×1366 母版，代理与母版范围请求均为 206，母版摘要核对及完整音视频解码通过。核验 9 种动效、14 次出现、16 条提示音与一首背景乐，实录原声分轨与旧版的摘要一致。原 Motion 包 1,426 项文件完整性核对通过。证据在 `C:/tl/motion-response-revalidation-20261111` 的 `delivery-evidence.json` 和 `knowledge-evidence.json`，同目录 `website-product-revalidated-hd.mp4` 为新出片。

Chrome 从旧规划卡触发重核，页面显示另存的原生编排链接。浏览器记录只提交了重核接口，旧成片与新成片在同一项目中均可查看。实播新母版并下载，下载摘要与独立 worker 交付件相同，见同目录 `browser-evidence.json`。

464 项相关后端回归、目标 Ruff、mypy、前端类型和 ESLint 通过，OpenAPI 与接口类型已同步。这一轮验证历史响应的重核、原生渲染和交付，语义与视听仍待人工验收。

## 在代理和高清中按原生混音点位试听

剪辑任务卡新增「按点位试听音效与配乐」。展开时读取当前任务的声音校验产物。列表以原生回执的实测音效起音和背景乐起止为准，点击从同一张任务卡的播放器开始，音效预留 0.7 秒听前文和观察动作。也可逐条打开原包音频。原包与混音切换时暂停另一播放器，声音校验记录仍可下载。点位缺失或不符合合同会提示读取失败，试听不自动写入人工验收。沿用已鉴权的产物和原音频接口，无新增数据库字段。

复用已保存的 HY-A2 原窗口编排，独立 worker 新建任务 `cc57e84f-bdda-499e-ae72-2fde2f9fcf5a`，代理等待确认高清。以旧高清任务 `ebf01355-c411-409f-8101-07bdb0f1b820` 核对，16 条音效的原件与处理后摘要、实测起音和混音分轨摘要逐项一致，背景乐绑定也一致。HY-A2 三条起音为 39.800、40.200、41.000 秒。实际代理音视频完整解码，原包 1,426 项完整性复核通过。证据见 `C:/tl/motion-sound-review-20261111` 下的 `preview-evidence.json` 和 `mix-comparison.json`。

Chrome 在 425 像素视口实播 768×1366 母版及新 358×640 代理，均由 39.800 秒音效行定位，确认播放经过该点。两版都核对了原音效及原背景乐的下载摘要与范围响应。播放原音效时对应视频暂停。浏览器注入一份格式不符的回执验证错误提示，重试后恢复真实点位。证据在同目录 `browser-evidence.json`。40 项声音与交付回归、前端 `tsc --noEmit` 及目标 ESLint 通过。此轮是试听链路与混音技术验证，听感继续待人工验收。

## 租约过期后的自动接管与 handoff v1 的时区兼容

剪辑与规划队列领取任务时消费本次投递预留。写入阶段或失败结果须同时满足当前执行令牌和有效租约。过期尝试保留给维护进程重新投递，同一任务号由下一次尝试接管，旧尝试记为被接替。待领取的任务继续保留投递防重窗口。两项回归均在基线 `f22b86b` 复现过期尝试误写失败，修复后均通过。

隔离 PostgreSQL 18.4 从空库迁移到 `20261110_0051`，实际 HTTP API、Redis 8.8.0、维护进程和两个独立 Celery 队列读写同一库。测试让两个 worker 第一次读取原包后暂停 36 秒，租约设置为 30 秒。维护进程自动重新投递，无人工重试。剪辑 `b94f9c8a-c95f-493d-a36a-459c9e6a48c2` 与规划 `d922040d-0cca-4f41-86e2-16c01d25168d` 分别在首轮领取约 39.48 和 39.52 秒后开始第二次尝试。规划到达已准备，网关状态为未提交。剪辑沿用已保存的真实网关响应衍生编排，重新编码并确认交付 48.475 秒母版，实际含 9 种动效、14 次出现、16 条音效及一首背景乐。代理和母版范围读取为 206，下载件完整解码，摘要与前次同编排母版一致。原包 1,426 项摘要核对通过。新出片为 `C:/tl/motion-lease-recovery-20261111/website-lease-recovered-hd.mp4`，回执为同目录 `delivery-evidence.json`。

同一套 PostgreSQL 实测旧 handoff v1 首次签发使用 UTC，读取后以数据库的 `Asia/Shanghai` 偏移签名，首次令牌读清单返回 401，重发后生成的旧令牌可读。修复后签发与回读都将到期时间标准化为 UTC。对仍在有效期内、以当前数据库偏移签发的旧 v1 令牌继续核验原签名。用基线与修复版 HTTP 进程在同一个隔离数据库交叉验证，新令牌在 UTC 与上海时区服务间一致，旧版的两个签发结果在修复版均可读。已核对旧 ZIP、委托清单、确认稿、原音频与原片摘要，音视频范围请求为 206。回调重放只保留一条，撤回授权后返回 401。证据为同目录 `handoff-evidence.json`。

467 项相关后端回归通过，目标 Ruff、mypy 和差异检查通过。本轮验证任务恢复、技术交付和旧交接兼容。新增模型调用为零，无数据库迁移改动。复核原库全部 132 组的登记记录，127 组有编码样本，CX-G05、CX-G08–10 和 HY-A1 仍待原件或适用授权。模型语义与用户视听继续分别记录。

## 原库运行证据的迁移预检

原库目录、组详情和规划准备读取同一份发布版本证据。读取时核对记录结构、版本、分组、编号及原生输入和回执的摘要字段。成功记录须包含输出摘要、实际帧率、画幅和帧数，失败记录须包含原生失败码。无法核验的文件保留在原位，目录及详情单列数量，其他有效记录可继续用于状态显示和规划准备。证据仍是每条输入的编码记录，语义、画面及听感验收独立。静态审计命令可加 `--state-dir <发布版本证据目录>`，输出各组有效及异常数量，便于迁移后预检。

在实际 169 份记录的迁移副本中加两份故障文件。基线遇到截断 JSON 时目录返回 500，另一份缺少编码证据的记录把 HY-A1 标成已有样本。修复后目录返回 132 组、197 项内置资源、699 项外部引用，单列两份异常。HY-A1 仍待实测，AH-S03 A 版保留原记录。新规划准备保留 132 组目录及相符的状态，网关未提交。迁移副本的 171 份文件摘要在读取前后一致。实际 CLI 与 API 回执分别为 `C:/tl/motion-evidence-transfer-20261111/migration-cli-audit.json` 和同目录 `migration-api-evidence.json`。

逐份关联现有 155 条成功记录的原生输入、原生回执和视频摘要。独立解码全部 155 个历史组件样本，覆盖 127 组、24,067 帧，尺寸、帧率和帧数逐项一致。在另一证据目录复核五类引擎各一条真实输入回执的登记。14 条历史失败登记仍保留。本轮解码范围为成功组件样本。两份交接原 ZIP 与 1,426 项 Motion 原包完整性复核通过。定向复查四个交付及补件位置，未找到缺件的原始字节。证据为同目录 `physical-evidence-inventory.json`、`independent-decode.json`、`writer-proof.json` 和 `missing-originals-recheck.json`。

Chrome 打开迁移副本，复核目录总数和两份异常提示、HY-A1 待实测，以及 AH-S03 的 A 版有效记录和 B 版待实测。浏览器回执为同目录 `browser-evidence.json`。468 项相关后端回归、目标 Ruff、mypy、前端类型、ESLint 及差异检查通过。本轮验证目录迁移和历史组件复验，五组原件或适用授权继续待补，整片用户验收继续单列。

## YYO08 原生推近入场保留完整实录价格

YYO08 的原生画面绘制主题和第二段文字，原配置另有一个必填的三字辅助标题槽。适配此前固定截取主题首词，导致「14块9」的「14」进入辅助槽，整段因数量不完整被拒绝。现在遇到首词截断数量时，依次尝试复用已经选定的完整主题、第二段文字，两者都受原槽位宽度和数量完整性约束。可见文字、模板动作帧和词点维持原绑定。回归在基线 `cf98071` 复现截断，修复后通过。

历史真实网关产品回执按现行规则最多排出 9 种、14 次。该回执的 YYO08 候选还存在第二段词点超过原生动作范围的问题，继续保留为拒绝。另用同一份 48.475 秒实录和本地受控规划，加入符合原动作范围的入场。原生主题为「14块9」，第二段为「两大瓶」，辅助槽复用「两大瓶」。第二段在局部第 35 帧进场，首个原生提示音在成片第 33 帧即 1.100 秒起音。原生推近带有问号，这份回执验证绑定与时间轴，语义和视听须另行验收。历史网关响应的文件及数据库内容保持一致，新增外部模型调用为零。

独立剪辑 worker 完成任务 `20401b19-41ad-4814-bae9-33936c8765ed`。网站确认并下载 768×1366 母版，实测 10 种原生动效、14 次出现、16 条提示音及一首背景乐。代理和母版范围请求为 206，母版完整解码，Chrome 实播越过新入场后下载，下载摘要与服务端交付一致。新片为 `C:/tl/motion-yy08-price-binding-20261111/website-yy08-verified-binding-hd.mp4`，同目录保留交付、浏览器及抽帧证据。原包 1,426 项完整性复核通过，469 项相关后端回归、目标 Ruff、mypy 和差异检查通过。

按交接摘要复查本机 Adobe、Windows 和 fontconfig 字体缓存，核对 850 个文件，未找到待补字体原件。厂商公开入口尚未提供可与交接摘要比对、可用于本项目的原文件。五组缺件和 AH-S03 B 版继续分别登记。

## YYO08 的原生问号对应实录短问句

原模板固定绘制问号。新规划提示、简表时间例和候选校验都检查问句槽的实录证据。当前接受带问号的短句，或在实录分句边界明确以「吗」结束的短问句。对齐证据不足时让其他符合条件的候选竞争。原生字数、入场窗口和读时继续独立校验。简表按当前规则重核旧响应，完整结构的自动规划也校验此槽。已交付母版继续可读，原模板、原素材和旧响应均保留。已准备但尚未提交的规划如果请求提示发生变化，按原有请求摘要机制重新准备。

在隔离库重核上一轮受控回执，「两大瓶」作为陈述被排除，另存 9 种动效的编排 `59862eb9-a428-485c-ba6d-27e29ad29219`，旧母版范围读取仍为 206。同一候选以完整结构提交校验也被拒绝。只读复核两份真正的历史腾力网关响应，产品讲解仍为 9 种、14 次，知识口播仍为 10 种、10 次。本轮外部模型调用为零。

正例用已有 38.467 秒实录「准备上新，先做哪张图？」。原项目的 YYO08 选组备忘为避用，只在隔离数据库通过备忘接口登记为可考虑，再运行本地受控规划。独立 worker 完成任务 `82f599e7-cf42-43fe-902c-44e5caf5ec22`，主题显示「上新」，问句槽的实录词点位于原生局部第 38 帧，实片显示「哪张图」及原问号，主字幕保留「先做哪张图？」。整片有 7 种动效、7 条提示音和一首背景乐，YYO08 的起音是零基成片第 14 帧。原声分轨的源片偏移为 0，峰值差 −138.491 dBFS。

本地网站确认并下载 1080×1920 母版，代理和母版范围请求为 206，下载摘要和完整解码通过。Chrome 实播越过问句入场，下载摘要与 worker 母版一致。原 Motion 包 1,426 项完整性复核通过。试片及 `delivery-evidence.json`、`rejection-evidence.json`、`archived-gateway-evidence.json`、`browser-evidence.json`、`question-frame.png` 在 `C:/tl/motion-yy08-question-gate-20261111`。467 项相关后端回归通过，补充数字比例和句末标点边界后再跑 25 项规划及溯源回归，Ruff、mypy 和差异检查通过。这次试片用于核对问句和原生交付，整片语义、画面及听感仍待用户验收。

## 分页读取超过 200 份资料的文稿历史

基线 `9cdfa6e` 的文稿工作区只取最近 200 份资料。新增按保存时间和文档编号翻页的资料接口，每页默认 25 份。草稿、拆解所绑定的原文、拆解或事实卡随页按需返回，范围始终限当前项目、用户及工作区。已有列表接口继续使用原返回格式。网页按文档编号合并已加载的页，后台刷新首页时保留历史位置和当前选择。文稿任务与对标提取任务的已保存标记直接按任务编号核对，历史文档排出首页后仍显示已保存。公开文稿时间统一返回 UTC，无数据库迁移。

SQLite 和 PostgreSQL 均从同一隔离副本资料集读回 211 份资料，九页顺序相同且无漏项或重复。第 206 条为旧列表找不到的既有草稿。单条草稿页同时返回其原文、拆解和事实卡，与完整历史中的文档 ID 和摘要一致。PostgreSQL 从空库迁移至 `20261110_0051`，数据库使用 `Asia/Shanghai`，API 时间为 UTC。跨项目游标拒绝，旧格式日期的同时间戳翻页也通过。

Chrome 在隔离项目点击八次加载历史，选中旧草稿，等待后台刷新后仍保留该选择。仅修订标题，另存草稿 `11d9dfcc-40e1-40f6-a11f-2f21fbad7006`，逐句内容与原事实映射相同。明确采用后只新增编辑器草稿 `dc33210e-f0ea-48a1-97a2-9124484bd952`，已确认版本和原来源回读相同，已有成片仍支持 206 范围读取。源数据库摘要一致，外部模型调用为零。实测回执位于 `C:/tl/writing-history-pagination-20261111` 的 `api-evidence.json`、`postgres-evidence.json` 和 `browser-evidence.json`。

478 项相关后端回归通过，时间标准化后复跑文稿与对标专项。Ruff、mypy、前端类型、ESLint、OpenAPI 生成和差异检查通过。原写稿方法包 33 项完整性复核通过。本轮验证文稿历史、修订和既有交付的关联。

## 从已校验的高清母版恢复损坏的代理

基线 `9593839` 的待确认任务会拦截损坏代理的高清确认。网页现在可从读取错误进入代理恢复。接口按项目权限、当前代理编号与摘要、代理和母版的校验回执以及母版实际字节登记原任务重试。独立 worker 再核对母版，只重新编码并完整解码代理。代理产物与回执在租约保护的同一事务中更新。新代理分配新编号，重复提交恢复请求沿用原任务，旧确认请求无法开放高清。后续调整继续指向原生母版的尝试目录。产物下载同时核对文件归属的任务目录、字节数和摘要。无数据库迁移。

以 38.467 秒真实问句成片的隔离副本测试。先改动代理的一字节，Chrome 播放请求返回 409，随后从任务卡提交恢复。领取前再改动副本母版的一字节，worker 拦截首轮并保留具体失败码。将副本母版恢复至原摘要后，Chrome 用原任务编号重试。第二轮只编码代理，恢复件与原代理摘要一致并分配新编号。旧确认被拒绝，暂存高清仍不可读。Chrome 实播 360×640 新代理并确认后，高清返回 HTTP 206。浏览器下载件与原母版逐字节一致，代理和下载件均通过独立完整解码。原七组动效和音轨沿用旧母版。原数据库和全部原产物的摘要不变。

测试记录为 `C:/tl/motion-preview-repair-20261111/delivery-evidence.json`，下载对照件在同目录 `website-repaired-preview-hd.mp4`。本轮验证交付恢复，原生渲染和外部模型调用均为零。478 项相关后端回归、Ruff、mypy、前端类型、ESLint、OpenAPI 与差异检查通过。原 Motion 包 1,426 项完整性复核通过。恢复入口以仍有可验证的暂存母版为条件，母版不能核验时需恢复原文件或从冻结编排另行生成。

## 基础字幕保留横屏和方屏原片比例

基线 `d9b10ad` 的基础字幕与组合动效共用原生竖屏准入。基础字幕现可接收方形像素的横屏、方屏及其他比例竖屏。横屏母版上限为 1920×1080，其他画幅上限为 1080×1920。范围内沿用原尺寸，按编码需要对齐偶数像素。新路径使用原 episode、selection、bindings 和原生连续原片底轨，在合成命令中按显示比例完整放入画布。原生字幕、原声、时钟和验收继续沿用。组合动效与既有 9:16 路径沿用原尺寸和原合成规则，非方形像素输入仍需处理后使用。无数据库迁移或公共接口字段变更。

两条输入使用同一条真实录音对应的画幅测试件，横屏 1280×720、48.475 秒，方屏 720×720、9.000 秒。横屏此前只完成了转录。本次用独立 worker 重新实际识别、调用原生合成并完成交付。横屏的 243 个词点、实录词时及分析原声摘要与历史对照一致。新横屏有 25 段基础字幕，方屏实际识别 48 个词点并生成 6 段。两份成片在 1、4、7 秒所抽原片边缘像素相同，无字幕的上部画面平均像素误差均小于 0.46。原声分轨相对源片的峰值差约为 −138.49 dBFS。原包 1,426 项完整性复核通过，无外部模型调用。

Chrome 从本地网站实际播放并下载两条高清，媒体范围请求均返回 206，下载摘要与 worker 交付件一致，音视频独立完整解码通过。测试目录为 `C:/tl/motion-source-aspect-20261111`，两条高清分别为 `landscape-website-subtitles-hd.mp4`、`square-website-subtitles-hd.mp4`，同目录有两份交付回执、`clock-comparison.json` 和 `browser-evidence.json`。484 项相关后端回归、目标 Ruff、mypy、前端类型、ESLint 和差异检查通过。这两条验证基础字幕和原画幅交付，视觉及听感验收仍单独记录。

## 浏览器补件区分原件与诊断用途

基线 `b893c85` 可将旧 CX-G05 诊断成片导入为成功编码证据。补件登记现要求声明原件或诊断用途。无目录摘要的旧记录需重新核对来源并明确登记。可匹配原库字节摘要的旧记录仍按原摘要核验。已知诊断字节在同一绑定中不能靠改用途或换路径变成无目录摘要的原件。网站目录、剪辑编译和普通原生入口只接纳原件。诊断图经任务冻结后可在独立单组命令使用 `--diagnostic-browser-images`，原生回执记下每张实际加载图的诊断身份。

原库编码证据导入按实际渲染分支重新核对活动原件和已加载回执。CX-G05、CX-G09、CX-G10 的旧成功记录若没有该项核验，需要从原生回执重新导入。对现有正式目录重新统计，132 组均登记，127 组有 155 份编码样本，现有正式记录均可读取。CX-G05、CX-G08、CX-G09、CX-G10、HY-A1 仍待原件，AH-S03 的 B 版单列。

隔离网站接口分别读正式绑定、旧未分类诊断绑定和新诊断绑定，三种均报告 CX-G05 缺 69 张活动底板。网站编译和普通原生入口拒绝诊断图。真实单组诊断复跑读取 69 张测试图，独立解码 100 帧，其中 89 种画面。新旧两份诊断回执均无法进入原库成功记录。正式绑定及原 Motion 包 1,426 项摘要一致。441 项剪辑、原库和文稿相关测试通过，目标 Ruff、mypy 和差异检查通过。记录见 `C:/tl/motion-browser-original-scope-20261111` 下 `runtime-retry/verification.json` 和 `catalog-audit.json`。本次验证入库隔离及原生诊断，待补件组的正式编码、语义和视听状态仍待验收。

## HY-A1 原字体字节和组件验证凭据

基线 `a3dcd3c` 的 HY-A1 组件入口只检查原俊雅字节。现将原文件核验和组件使用凭据分开。已有使用凭据时，以 `register_motion_local_dependencies` 的 `--component-use-reference <原资源ID> <凭据索引编号>` 随原件候选提交。摘要匹配且整批通过后，`--apply` 将编号保存到私有绑定，匹配原库版本和字体摘要。预检只报告是否提交了候选凭据以及当前已登记状态。已有匹配文件可原路径补记。网站目录分别显示两项状态，编号保留在私有绑定。

HY-A1 编译、单组原生启动和成功证据导入均要求原字体字节及已登记凭据。独立单组 CLI 通过 `--native-bindings` 读取私有绑定，批验证沿用现有配置。证据导入使用 `POLARIS_VIDEO_EDITING_NATIVE_BINDINGS_FILE` 指向同一私有绑定。该凭据范围限原生组件验证。HY-A1 整片选组仍待组件原生编码、项目用途核对及画面听感验收。

沿用实际口播的「洗碗、刷锅、洗水果」词点。同期源片从 39.770 秒截取并完整解码 101 帧，三张原卡编译入场点为第 0、13、30 帧。用错误字节与隔离测试凭据分别请求补件、编译和原生启动，均被拦截。网站接口同时核对正式绑定的两项待补状态，以及孤立测试凭据与字节不匹配的两项独立状态。正式绑定摘要及 Motion 原包 1,426 项摘要通过核对。正式台账仍为 132 组登记、127 组有编码证据。442 项相关后端测试、目标 Ruff、mypy、前端类型与 ESLint 通过。验证回执见 `C:/tl/hypit-a1-font-admission-20261111/verification.json`。HY-A1 原生动画编码等待确切原字体及适用凭据。

Chrome 在当前项目副本打开原库目录，HY-A1 详情同时显示原件未登记、组件验证待登记使用凭据以及原字体的非商用标记。页面核对在同目录 `browser-current/browser-evidence.json` 和 `browser-current/hy-a1-catalog.png`。

## 当前基线重渲两条已捕获真实网关响应

在基线 `dc50ff7` 为产品讲解和知识口播各建立独立数据库及任务目录。按原摘要复制实录、补充素材、转录和服务器已保存的腾力网关请求及响应，只在副本里重定向文件位置。两份响应通过当前规则重核，原请求、响应、词轴、素材和编排摘要能追溯到新任务。网站 API 生成新剪辑任务，两个独立 worker 分别重新编译原 episode、selection、bindings 并编码。新任务目录未带入旧渲染缓存。两份来源数据库、原档案文件和 Motion 原包 1,426 项摘要通过复核。

产品讲解任务 `dd4a49d0-e56d-4653-9dbc-7afe98dfb441` 为 48.475 秒，实际编码 14 个原生动效片段，覆盖 9 种原生组，含 16 条提示音和一首背景乐。知识口播任务 `e2e1530f-0991-45ce-a5a7-a65d66fe8825` 为 40.123 秒，实际编码 10 个原生动效片段，覆盖 10 种原生组，含 15 条提示音和一首背景乐。逐条核对了 24 份原生编码回执、时间窗和输出摘要。两条原声分轨相对独立解码原片的峰值误差为 −138.491 dBFS，母版可测得提示音和背景乐分轨贡献。两条成片独立完整解码。新任务产物与同编排的历史母版逐字节一致。

本地 API 先提供代理，确认后开放 768×1366 高清，两类产物范围请求返回 206。Chrome 通过确认后的真实成片接口播放、跳播并下载，下载摘要与 worker 交付件一致。母版与三类回执在 `C:/tl/motion-authentic-replay-current-20261111` 的 `product` 和 `knowledge` 子目录，核对脚本为同级 `verify.py` 和 `playback.py`。本轮为历史真实网关响应与当前原生交付的端到端复验，新增模型调用为零。新请求的真实模型运行、原库剩余组和用户视听仍待验收。应用代码及数据库合同沿用基线。

## 核对 CX-G08 未绑定本期人物时的原人物图

基线 `5a0b826` 漏记 CX-G08 的原人物分支。共享 `engine.js` 在本期人物为空时，将 `legacy/assets/img/person.png` 交给 `renderScene` 的人物层。CX-G09、CX-G10 对该路径仅有启动加载。补交目录新增原资源 `media-b5a7277378d0b6890a95`，1,507,702 字节，按原目录 SHA256 核验。网站和原生入口在 CX-G08 采用原人物分支时核对这一项。原生编译仍可使用本期明确绑定的人物，之后由原入口继续校验共用字体等实际运行依赖。补件命令当前列出 213 个原生路径，分别来自 G05 入口的 141 个路径和共享入口的 72 个路径。目录保留每个分支的用途。

对原包和同一原输入做前后对照。旧预检会放过缺失的历史人物图。Chrome 直接运行摘要一致的原 `renderer.html`，4×4 透明响应导致人物区域留空，隔离诊断色块送入同一人物参数后该区像素发生变化。新编译和原生启动均在进浏览器前拦截缺图分支，补件工具拒绝同路径异字节的 PNG。本地网站组详情能区分 CX-G08 的人物用途和另外两组的共用启动用途。正式绑定及原 Motion 包 1,426 项摘要通过核对。此处验证原绘制分支和补件准入，CX-G08 整组仍待共用字体及实际原生编码。

定向复查五处项目交付与运行目录、两份原 ZIP、较早交接 ZIP 及独立剪辑方案文档。扫描路径、归档成员及源文本内嵌数据，八个已登记待查资源尚未找到摘要一致的副本。新补件清单、搜索与浏览器像素回执见 `C:/tl/motion-g08-original-presenter-20261111` 下的 `browser-original-request.json`、`targeted-byte-search.json` 和 `verification.json`。正式目录仍为 132 组登记、127 组有编码样本。

另用已绑定人物的 CX-G04 运行对照，在独立目录重新编码并完整解码 80 个不同画面帧。输出摘要与历史同输入样本一致，回执为同目录 `registered-presenter-control.json`。443 项相关后端回归、目标 Ruff、mypy 及差异检查通过。应用接口和数据库合同沿用基线。

## 分开核验 CX-G04、CX-G06 的原图与纯色分支

基线 `b6df490` 会放过 CX-G04、CX-G06 的缺失历史人物。CX-G06 另有一条默认绘制原图底板的分支。原 `renderer.html` 读取 `legacy/assets/img/g06-bg.png`，早期样本在此处收到透明占位。网站编译和原生启动现按实际分支要求原人物图、原底板或两者。原底板为 `media-f1715b277c0d286a7e58`，1,217,358 字节，按原目录 SHA256 核验。使用现有原生纯色模式的 CX-G06 以同一份原生回执证明模式生效，复用缓存及登记编码证据时均核对。目录区分画面所用原件和共用入口预加载，补件清单列出两个入口共 216 个已核查路径。

原输入实测三个缺件分支均在原生启动前被拦截。CX-G06 早期原背景样本的回执无法通过现行入库。去掉纯色标记的隔离缓存副本也被拒绝。用已登记的本期素材在新目录重渲 CX-G04 和 CX-G06，分别独立完整解码 100 帧和 269 帧，与各自历史同输入有效样本摘要一致。CX-G06 原生回执确认 `original_solid_mode`。两个新回执均登记到本地共享台账。

台账保留原 169 份历史文件及摘要。网站当前读取 132 组，127 组有成功编码证据，合计 154 份。CX-G04、CX-G06 各有一份本期重新核验的编码证据。三个旧记录保留，其中两份由新样本承接，一份 CX-G06 早期样本因缺原背景不计成功。缺件检查、原生重渲和台账回执在 `C:/tl/motion-browser-original-branches-20261111`。指定目录与归档的定向字节检查暂未找到原底板。原 Motion 1,426 项摘要复核通过。两组本轮验证范围为原生组件，原人物和原图分支仍等待原件。

另对同一时间和坐标实际解码背景像素，早期原图分支为黑色 `[0, 0, 0]`，重渲纯色分支为 `[96, 127, 103]`，见 `background-pixel-check.json`。447 项相关后端回归、目标 Ruff、mypy、前端类型及 ESLint 通过。应用接口和数据库合同沿用基线。
