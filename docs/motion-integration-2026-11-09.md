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
