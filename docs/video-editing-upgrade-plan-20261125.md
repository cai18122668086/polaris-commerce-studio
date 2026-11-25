# 智能剪辑质量升级方案（2026-11-25）

范围：智能剪辑（`bihuo-full-suite` 25 套成套模板 + `apple-minimal-v1`）的三个质量问题，以及两项新能力：AI 自动配图、MG 动效模板辅助剪辑。
代码基线：`origin/release/commercial-20261125` @ `dcb27b6`。行号均指这个提交。
证据来源：代码走读；开发环境已有的一次真实渲染（规划 a478acaf → 渲染 31c23e00，模板 bihuo-02-v1，11.85 秒）的离线测量；J 的全模板实测见第 2.5 节。

---

## 1. 渲染链路（现状）

```
口播源 ──ASR/FA 逐字时钟──► Transcript(tokens: start_ms/end_ms)
   │
   ├─ 规划：一次 LLM 调用 → AppleSuitePlan（只含 token ID，不含时间）
   │     video_editing_apple_contracts.build_request (176-330)
   │     video_planner_policy.normalize_suite_output (66-)
   │     bihuo_suite/planning.verify_plan (285-353)
   │
   ├─ 编译：token ID → 秒
   │     bihuo_suite/planning.compile_render_input (356-428)
   │       → video_editing_apple_contracts.compile_render_input (636-782)
   │       → video_materials.compile_request (106-189)（视频素材抽帧）
   │       → registry.compile_request → 各模板 runtime.compile_request
   │       → conditional_layout.prepare / adaptive_layout（版本化显示修正）
   │
   ├─ 源准备：bihuo_suite/source.prepare (138-209)
   │     非 1080×1920@25 的源一律 scale+fps=25 重编码（libx264 crf16）
   │     需要抠像的模板：foreground.prepare（u2net 人像蒙版，逐帧 PNG，按源 SHA 缓存）
   │
   ├─ 渲染：独立子进程 python -m app.video_editing_bihuo_cached_render
   │     每帧在 Python/PIL 里合成 RGBA 图层 → rgb24 管道 → ffmpeg
   │     例：fk-1104 runtime.render_mp4 (98-108)：-r 25, libx264 -preset fast -crf 18, -threads 2
   │
   ├─ 校验：video_editing_apple_pipeline (647-666)：解码一遍，查 1080×1920、h264、时长误差 ≤80ms
   ├─ 混音：video_editing_suite_sound（视频流 -c:v copy，不再重编码）
   └─ 预览：video_editing_preview (61-109)：长边 640 → 360×640，libx264 veryfast crf 27
```

要点：

- **渲染引擎不是 JS/Remotion，也不是 ffmpeg 滤镜图**，而是每个模板自带的 Python 合成器（PIL + numpy + OpenCV），逐帧画好后用管道送给 ffmpeg 编码。
- **旧笔记里的 "Motion library"** 是作者交付的一个按字节锁定的归档（`motion_library.py:15` `MOTION_SHA256`），安装在只读目录，供旧的 native 剪辑链路（`video_editing_native_*`，30fps，`video_editing_native_frame_clock.py:18`）使用。bihuo 模板把其中的 `apple_minimal` 组件（V01/V02/V03、pilot 缓动）**vendored** 到每个模板目录（例如 `templates/fk-1104-know-white-capsule/core/vendor/apple_minimal/`）。`apple_minimal/motion.json` 用的 `motiongit-template` 清单格式（specVersion 0.1.0-draft.1）是仓库里唯一的模板描述格式，MG 组件沿用它（见第 5 节）。
- **模板 = 代码 + 少量数据**。`catalog.json` 登记 25 个模板（全部 enabled），每个模板是一个独立的 bundle 目录（runtime.py + 引擎 + vendor + 字体 + 少量 JSON 参数），`bundle.json` 里逐文件锁 SHA256，`registry._installed` (88-104) 启动时校验，改一个字节就拒绝加载。已接受的计划按原样编译（README）。**所以修复不能直接改模板文件，要像 `conditional_layout` 那样做成带版本号的宿主侧策略**，只对新渲染生效，并写进回执。
- 帧率、分辨率、编码：全链路写死 1080×1920 / 25fps（`source.py:172`、`video_materials.py:77`、`foreground.py:35,86`、各 runtime 的 `round(t*25)` 和以帧为单位的常量）。成片 crf 18 / preset fast；预览 360×640 / crf 27。
- 动画实现：每个模板自写缓动函数，形式是 `ease(a, b, t)`（时间区间 → 0..1）。有 smoothstep（`pilot.ease`，pilot.py:24-26）、三次缓出（`media._out` 40-42，多个模板的 `out`）、余弦（`capsule_engine.pose` 24）和**线性**（`tpl_6c9775d0ad/renderer_v2.ramp` 15、`tpl_b4738a1cc2`）。没有统一的关键帧或时间线模型；位移和缩放在每帧里 `round()` 成整数像素（`media.render` 195、`capsule_engine.text_at` 60）。

---

## 2. 诊断

### 2.1 素材没跟上口播（同步）

素材出现时刻的计算：

1. 规划模型给每个素材一个词段 `first/last_token_id`，外加 `show_at_token_id` 和 `edge`。提示词写的是「用 show_at_token_id 和 edge 决定**在这句哪个词开始或结束后**出现」（`video_editing_apple_contracts.py:250`）。
2. `edge` 的**默认值是 `"end"`**（`video_editing_apple_contracts.py:51`）。
3. 编译时：`start = word.start_ms if edge == "start" else word.end_ms`（`video_editing_apple_contracts.py:711`）。
4. 模板拿到 `start` 后，从这一刻**才开始**入场渐变，例如 bihuo-02/03/04 的 V03 入场是 8 帧三次缓出加模糊（`capsule_engine.py:39`、`media.py:187-191`）。

**根因（按影响排序）：**

| # | 原因 | 证据 | 估计延迟 |
|---|---|---|---|
| S1 | 锚点可以落在句中任意一个词上，而模型倾向选名词（「这支**樱花**护手霜」）。素材在说到这个词时才出现，比句首晚 0.5–1.5 秒 | `contracts.py:250`；`planner_policy.normalize_material_anchors` (23-63) 只把越界的锚点拉回词段内，不往句首挪 | 0.3–1.5 s |
| S2 | 默认 `edge="end"`：再晚一个字的时长 | `contracts.py:51,711` | 0.15–0.3 s |
| S3 | 入场从锚点开始，不提前。人眼大约在不透明度过半时才算「出现了」 | 入场区间：bihuo-02/03/04 `[s, s+0.32]`；bihuo-13 青瓷 `out(s, s+24帧)`=0.96 s（`qingci_engine.py:53-54,174`）；bihuo-24 青白 `out(s, s+20帧)`（`qingbai_engine.py:148`）；bihuo-19 / bihuo-11 线性 `ramp(s, s+0.32/0.36)`；只有个别模板提前 0.04–0.24 s（teal、navy、neon、meiye、share-paper） | 0.07–0.25 s |
| S4 | 各模板的时间约定不一致：有的用口播词段起点，有的用 show_at 词 | `video_materials.py:158-159` 的注释原话 | 不定 |
| S5 | 素材的结束时间被截到这句话的结尾（bihuo-02/04），句子一结束图就淡出，下一张图要等下一个锚点，中间出现空窗和闪烁 | `fk-1104 runtime.py:40` `end=min(duration, span.end)`，对比 `contracts.py:722-723` 原意是「持续到下一个素材」 | 观感为「一闪而过」 |
| S6 | 要点卡片先出空卡：bihuo-02 的信息卡在开场结束时（1.77 s）进场，第一条要点到 3.21 s 才出现，中间 1.4 秒是空白卡片 | 本次实测 31c23e00：`card_times=[1.77,2.01]`，`items[0].at=3.21` | 观感为「内容跟不上」 |
| S7 | 视频素材用 cv2 按 `round(time*fps)` 取帧，VFR 手机素材按平均帧率换算，会慢慢漂移；非顺序访问用 `CAP_PROP_POS_FRAMES` 跳帧，长 GOP 的 H.264 上不精确 | `media._sample` (83-117) | 长片段数百毫秒 |

可以排除的原因：

- ASR 时钟本身没有明显的系统偏移。FunASR 的时间戳是 60 ms 网格，代码已经补偿了 CIF 峰值的 −90 ms 偏移和尾部填充（`video_editing_funasr.py:26-30, 92-133`）。31c23e00 的逐字时钟落在 10/30/50 ms 的相位上，相邻词首尾相接，没有成段漂移。在有确认稿的情况下还会走 FA 强制对齐（`video_editing_confirmed_alignment.py`）。
- 素材加载没有队列或异步延迟：渲染是离线逐帧进行的，图片第一次访问就缓存（`media._IMAGES`）。

结论：「素材没跟上」**主要是锚点选择的语义（S1、S2）加上入场不提前（S3）**，而不是 ASR 漂移或加载延迟。S5、S6 让慢半拍的感觉更明显。

### 2.2 人物被遮挡

- **全链路没有人脸、人体或主体检测**。在 `bihuo_suite/` 和 `video_editing_*.py` 里搜 face / detect / subject / safe，只找到字体变量；`sleepgrid_engine.py:157` 的注释直接写着 "no face avoidance crop"。
- 唯一的人像模型是 u2net 人像抠像（`foreground.py:14-16`），只用于 5 个 `requires_foreground` 的模板（bihuo-11/16/19/26/33），而且只用来抠前景，不参与布局。
- 素材框和人物窗口都是**按参考样片里那个人测量的固定坐标**：
  - bihuo-02：人物取景 `raw_crop=[0,420,1080,1080]`（`data/template.json`），只取源的 y=420–1500 这一条。人站得高一点、头在 y<420 时就会被切掉头顶；
  - 素材框：bihuo-23 藏青 `[47,312,1034,1135]`（`fk-1028 runtime.py:71`）、bihuo-27 莓夜 `[54,126,1022,1118]`（`meiye runtime.py:52`）、bihuo-08 `[54,154,1026,1150]`（`sleepgrid_engine.py:234`）、bihuo-48 `[54,350,1026,1130]`（`multimedia_engine.py:62`）。这些框几乎占满上半屏，而 9:16 口播的人脸通常在 y≈350–900；
  - `adaptive_layout.app_geometry` (54-65) 只按素材横竖比选两种固定框，不看人在哪里。
- 31c23e00 的实测抽帧（t=0.8 s）：开场人物窗口压住了上方标题卡的左半边（「冬天」被盖住）。这是反方向的遮挡：图层顺序和坐标都是固定的，不会让位。

**根因：** 版式是参考样片的复刻，坐标针对样片里的那个人；系统不知道新视频里人在哪里，也没有安全区约束。

### 2.3 动效和转场不顺滑

| # | 原因 | 证据 |
|---|---|---|
| M1 | 25 fps，而且用户上传的 30/60 fps 源会被**丢帧转成 25 fps**，连人物本身都会顿挫（30→25 每 6 帧丢 1 帧） | `source.py:150-156,172` |
| M2 | 视频素材同样用 `fps=25` 抽帧（`video_materials.py:77`），或者用 cv2 按 `round(t*src_fps)` 取帧（`media.py:105`），步长是 1,1,1,1,2 这样的不均匀序列，画面会抖 | 同左 |
| M3 | 整数像素定位：慢速位移和缩放时每帧取整，0.3 px/帧这样的运动会变成「停、停、跳」的阶梯；窗口大小每帧取整后重新 LANCZOS 缩放，边缘会闪 | `media.py:195-198`、`capsule_engine.py:51,60` |
| M4 | 线性缓动和硬切：部分模板用线性 `ramp`；素材之间没有交叉过渡（上一张在 `end-0.16` 淡出，下一张从 0 淡入，中间可能露底）；bihuo-02 的素材在句末被截断（S5） | `renderer_v2.py:15`、`capsule_engine.py:42` |
| M5 | 多次有损编码：上传源 crf16 重编码一次，成片 crf18 / preset fast 再编码一次，预览 crf27 / veryfast 第三次。31c23e00：源 2.6 Mb/s → 成片 1.07 Mb/s | `source.py:176-180`、`runtime.py:100`、`preview.py:87-96` |
| M6 | **用户审片看到的是 360×640 的预览**，视频码率只有 67 kb/s。mpdecimate 认为 296 帧里有 107 帧和前一帧近似相同（成片只有 8 帧），细微动效被压没了。「质量差」的第一印象多半来自这里 | 31c23e00 `outputs/preview.mp4` 实测；`PROXY_MAX_EDGE = 640`（`preview.py:12`） |
| M7 | rgb24 → yuv420p 没有指定色彩矩阵，也没打 bt709 标签，播放器可能按 bt601 解释，出现轻微色偏 | `runtime.py:100` |
| M8 | 渲染很慢，所以不敢加帧：11.85 秒用了 165.8 秒（约 0.56 秒/帧，单进程，`-threads 2`），60 秒的片子约 14 分钟。直接上 60fps 会到 34 分钟左右 | 31c23e00 `render-receipt.json` `render_seconds` |

### 2.4 模板现状

- 25 个模板（`catalog.json`），22 个带 `images`（bihuo-29/34/36 没有），3 个带 `video_materials`（bihuo-02/03/04，`video_materials.NATIVE_VIDEO`），5 个需要抠像。
- 模板之间几乎不共享代码：每个 bundle 各自 vendor 一份 apple_minimal、各自写缓动、各自写死坐标。可复用的「组件」只有 V01/V02/V03（人物窗口、媒体窗口）和几个字幕引擎（T01–T05、`subtitle_engine`）。
- 文本类动效（标题、名片、要点、结论胶囊、章节）都是各模板里的专用代码，参数来自规划结果（`items`、`chapters`、`conclusion` 等）。
- **MG 的插入点：** `registry.compile_request` 之后、渲染之前，有一个已经被验证过的挂钩模式：`conditional_layout.execution` 和 `video_materials.execution` 都是在渲染时包装模板的 `render_frame` / `render_layers`（`video_materials.py:239-264`）。MG 叠加层可以用同样的方式在模板输出的 RGB 帧上（或图层字典里指定的 z 序位置）再合成，不需要改模板文件。

### 2.5 J 的全模板实测

> J 正在逐个模板真实渲染，结果会写到 `~/work/e2e/findings-video-full.md`，证据帧在 `~/polaris-shots/2026-11-25/e2e-video-full/quality/`。本节在 J 交付后补上：每个模板的同步差（素材可见时刻 − 词段起点）、遮挡帧数和比例、帧率与重复帧。第 6 节的阈值先按代码分析给出，拿到实测分布后再校准。

---

## 3. 修复方案

总原则：**不改已安装的模板文件**（bundle 有哈希锁定，已接受的计划要能原样复现）。所有修复做成**带版本号的宿主侧策略**，和 `conditional_layout`（`VERSION = "bihuo-conditional-layout/1"`）一样只对新渲染生效，并把策略版本写进 `render-receipt.json`。需要改模板内部的项目（帧率、整数像素），走 `tools/install_bihuo_template.py` 重新发布 bundle 版本。

### 3.1 同步：`bihuo_suite/sync_policy.py`（`bihuo-sync/1`）

在 `bihuo_suite/planning.compile_render_input` 调用 `contracts.compile_render_input` 之前改写 `verified`，在 `fitted_recipe` 里改写 `resolved`：

1. **锚点回到句首**：素材的 `show_at_token_id` 统一改成词段的 `first_token_id`，`edge="start"`。只有一种例外：词段超过 2.5 秒，并且模型选的锚点词是名称、数值或卖点关键词时，保留原锚点。计划本身不改，只在编译时换算，所以旧计划也能用新策略渲染。
2. **提前量（lead-in）**：可见起点 = `floor_to_frame(span.start − lead)`，其中 `lead = 120 ms + 该模板入场曲线到 50% 不透明度所需的时间`。按模板建一张入场曲线表（例如 bihuo-02 的 V03 是 8 帧三次缓出，到 50% 约 0.07 s，lead 约 190 ms；青瓷 24 帧缓出，lead 约 320 ms）。结果下限是开场结束时刻 `opening_end`，并且不早于上一个素材的结束。取整时一律**向下取整到帧**（`floor(t*25)/25`），不用 `round`。
3. **素材持续到下一个素材**：传给模板的 `spoken_span.end` 改成「下一个素材的可见起点」或正文结束（`body_end`），修掉 S5。图片最少停留 1.2 秒，不够时与下一张合并成一段。
4. **要点、功能卡、章节用同样的提前量**（`points[].start`、`features[].start`、`chapters[].time`）。
5. bihuo-02 的空卡问题（S6）**不在第 1 期处理**：卡片进场和人物缩窗绑在同一个开场时刻（`runtime.py:51-52`），单独推迟卡片会在人物让出的位置留下空白。第 2 期和版式避让一起做：卡体先只显示标题行，第一条要点前 0.35 秒再展开行区。
6. 提示词（schema v3）：去掉「哪个词开始或结束后出现」，改成「素材从它所配那句话的第一个词开始」。`edge` 默认值改成 `"start"`。

- **工作量**：1 天（策略模块、入场曲线表、测试）。提示词和 schema v3 另加 0.5 天。
- **风险**：低。只改编译输入，不动模板和计划。主要风险是个别模板的内部约束（比如 `Feature cards must follow material playback`）因为时间提前而触发校验错误，需要逐个模板回归。

### 3.2 遮挡：主体检测 + 安全区约束

1. **检测（按源缓存）**：新增 `bihuo_suite/subject.py`，在 `source.prepare` 之后运行。
   - 每 0.2 秒采样一帧（5 fps）。人脸用 OpenCV 5 自带的 `cv2.FaceDetectorYN`（YuNet，ONNX 模型约 230 KB，和 u2net 一样锁哈希、只读安装）；人体轮廓复用已经安装的 u2net 人像蒙版（`foreground.py`），取 alpha>0.5 的外接框。两个依赖都已经在 editing 镜像里（`opencv-python-headless==5.0.0.93`、`onnxruntime`），不需要加新包。
   - 输出 `subject.json`：每个采样时刻的 face box、person box 和置信度，外加全片并集，按 `source_sha + model_sha + version` 缓存在 `_subject/`。CPU 耗时约 60 秒视频 3–6 秒。
2. **安全区**：
   - `face_safe` = 人脸框外扩 25%（上方再加 15%，留给头发）；
   - `person_safe` = 人体框在肩部以上的部分；
   - 字幕区单独保留。
3. **布局约束（按模板分类处理）**：
   - **人物窗口类**（bihuo-02/03/04/14 等，人物缩进窗口）：把固定 `raw_crop` 换成跟随人脸的取景。取景框中心对齐人脸中心，按时间做 1 秒窗口的平滑，取景框大小固定。这样窗口里永远是脸，不会切掉头顶。
   - **满屏人物 + 叠加卡片类**（bihuo-23/27/08/48 等）：先算候选素材框与 `face_safe` 的交集。超过人脸面积的 5% 时，按顺序尝试：① 换成模板自带的另一个框（大部分模板有上/下两套，如 `app_geometry(bottom=…)`）；② 卡片整体下移到人脸下方，缩小到最小可读尺寸；③ 卡片显示期间把人物缩进窗口（模板有这个机制时）；④ 都不行就改成全屏素材加短暂硬切。按负责人决定，全屏 B-roll 单次最长 2.5 秒，超过就拆段并在中间切回人物；其他卡片和字幕任何时候都不能压脸。
   - **抠像类**（5 个 requires_foreground）：素材放在人物后面，已经避免遮挡，只需要检查文字不压脸。
4. 实现方式：和 `adaptive_layout` 一样在 `conditional_layout.prepare` 阶段改编译参数里的框坐标，并写进回执 `layout_safety: {version, adjustments[]}`。

- **工作量**：检测和缓存 1 天；人物窗口跟随取景 1 天；叠加框避让要逐模板适配，按一类模板 0.5–1 天算，25 个模板约 6–8 天。
- **风险**：中。跟随取景如果平滑不够会晃，要做死区和平滑。避让会改变样片的版式，需要设计师确认每个模板的备选框。

### 3.3 顺滑度

按收益/成本排序：

| 改动 | 内容 | 工作量 | 风险 |
|---|---|---|---|
| P1 预览升级 | `PROXY_MAX_EDGE` 640 → 1080（输出 608×1080），crf 27 → 22，preset veryfast → faster。只改 `preview.py` | 0.5 小时 | 低。预览文件约增大 3–4 倍（11.8 秒约 0.4 MB → 1.5 MB） |
| P2 素材抽帧 | 所有视频素材统一走 `video_materials._frames` 的 ffmpeg 预抽帧（去掉 `NATIVE_VIDEO` 例外），用 `fps=25:round=near` 加 `-fps_mode cfr`，VFR 先按时间戳归一 | 0.5 天 | 低 |
| P3 素材交叉过渡 | 相邻素材 4–6 帧交叉淡化（上一张不提前淡出，等下一张盖上）。在 sync_policy 里把 `end` 延长 6 帧，配合 3.1 第 3 条 | 0.5 天 | 低 |
| P4 成片编码 | crf 18 → 16，preset fast → medium，加 `-colorspace bt709 -color_primaries bt709 -color_trc bt709`，用 `-vf scale=out_color_matrix=bt709` 做 rgb→yuv，GOP 2 秒。要改模板 `render_mp4`，可以由宿主在 `video_editing_bihuo_cached_render` 里拦截 `subprocess.Popen` 参数，或重新发布 bundle | 1 天 | 低。码率约 +30% |
| P5 亚像素合成 | 在 vendor `media.render`、`capsule_engine` 等公共组件里把 `round()` 定位改成仿射变换（`Image.transform(AFFINE, BICUBIC)`），或者在 2× 画布上合成后再缩小。需要重新发布 bundle | 2–3 天（公共组件） + 逐模板回归 | 中。像素级输出会变，样片对比要重新确认 |
| P6 统一缓动 | 线性 `ramp` 改成三次缓出（入场）/ 缓入缓出（位移），提供共享的 `easing.py`：cubic-out、quint-out、柔和弹簧（无回弹）。只改使用线性的模板 | 1 天 | 低 |
| P7 原生帧率 | 输出帧率跟源走：25 fps 源输出 50 fps（每个源帧用两次，动效按 50 fps 计算），30/60 fps 源输出 60 fps，不再把人物丢帧到 25。前提是 P8，并且要清理模板里大量写死的 25 和按帧计的常量 | 每个模板 1–2 天，合计 3–4 周 | 高 |
| P8 并行渲染 | 把帧区间切成 K 段，每段独立子进程渲染并编码成封闭 GOP 的片段，再用 `ffmpeg -f concat -c copy` 拼起来。8 核机器在和正式站共用的情况下取 K=3 | 2 天 | 中。要保证各段的编码参数和时间戳完全一致；模板里的缓存（`lru_cache`、`_READERS`）每个进程各一份，内存要看住 |

关于 30/60fps：对口型源本来就是 25 fps，直接输出 30 fps 会让人物每 5 帧重复一帧，反而更顿。所以不建议统一改成 30，改为跟源帧率走（P7）。上传视频人物顿挫的真正原因是 M1（源被丢帧到 25 fps），根治办法就是让渲染器按源帧率出片，也就是 P7；不建议用 `minterpolate` 插帧凑 25 fps，口型和手部会出伪影。在 P7 完成前，30 fps 上传源的人物会继续有轻微顿挫。

---

## 4. AI 自动配图

### 4.1 触发规则

- 只在模板有 `images` 能力时可用（22 个模板）。用户在剪辑页显式打开「缺图时 AI 配图」，开关旁边显示单价和本次最多张数；**默认关闭**。
- 候选片段：正文区间内（`opening_end` 到 `quote_start`），没有被任何用户素材覆盖的语义段，并且同时满足：
  - 时长 ≥ 1.6 秒；
  - 内容可以画出来：场景、使用动作、成分或质地、对比或数据的比喻。纯态度句、过渡句、口号不配图；
  - 和前后已有素材间隔 ≥ 2 秒，避免图片连成幻灯片。
- 数量上限：每 30 秒最多 2 张，全片最多 6 张，用户可以把上限调得更低。
- 由规划模型在**同一次**规划调用里给出（schema v3 新增 `image_requests`，最多 6 条），不增加 LLM 调用次数：

```json
{"image_requests": [{
  "first_token_id": "t000031", "last_token_id": "t000044",
  "purpose": "scene|usage|texture|concept|comparison",
  "subject": "护手霜挤在指尖，质地清透",
  "must_show_product": false
}]}
```

服务端会再校验一遍：间隔、上限、是否和用户素材重叠，不合格的直接丢弃并写进 warnings。

### 4.2 提示词

服务端拼装，模型只提供 `subject` 和 `purpose`，不直接写最终提示词：

```
[模板风格锚] + [purpose 句式] + [subject] + [商品事实（来自项目商品资料/参考稿，仅名词和属性）]
+ [构图：竖版 2:3 或模板框比例，主体居中偏下，上方 20% 留白给标题]
+ [固定负面约束：画面内无文字、无 logo、无水印、无人脸特写、不出现品牌名]
```

- **风格锚**：每个模板一条，写进模板元数据的 `image_style`，例如：
  - bihuo-02 白底胶囊：「明亮的产品摄影，浅暖灰背景，柔和顶光，浅景深，干净留白」；
  - bihuo-09 杏黄古卷：「暖黄纸质感，胶片颗粒，低饱和」。
  同一个视频的所有配图共用同一个风格锚和同一个 seed（供应商支持时），保证风格一致。
- **商品一致性**：`must_show_product=true` 并且项目里有商品图时，走图片编辑或参考图模式（沿用 `creative_image_provider` / xinghe 的参考图链路），以商品图为参考。没有商品图时，`must_show_product` 强制改成 false，只画场景和概念，**不凭空画商品**，避免画错包装。
- 所有文字字段按不可信数据处理，只作为提示词里的引用内容（和现有规划提示词的规则一致，`contracts.py:276`）。

### 4.3 供应商、尺寸、延迟

- **供应商**：复用站内现有的 OpenAI 兼容图片网关。主路由是 `image_base_url` / `image_model`（`config.py:268-270`，gpt-image-2.5-flare），备用是 `provider_failover_image_model`（`config.py:274-278`，gpt-image-2）。共用全站的图片并发上限 `image_global_concurrency`（`config.py:333`）和供应商额度账本（`provider_quota_ledger`），不另开通道。
- **尺寸**：1024×1536（竖版）或 1536×1024（横版），按目标框比例选，medium 质量。生成后按模板框比例居中裁切，保存原图。
- **延迟预算**：在「规划完成 → 渲染」之间新增 `generating_images` 阶段，N 张并行（单个工作区最多 3 路并发）。软预算 90 秒，硬上限 180 秒。超时或失败的片段走降级（4.5），不阻塞整片渲染。

### 4.4 缓存与存储

- 缓存键：`sha256(规范化提示词 + 模型 + 尺寸 + 风格锚版本 + 参考图 SHA)`。命中就直接复用，不再计费。重新规划、重新渲染、同一段文案换模板（风格锚相同时）都能命中。
- 结果存成剪辑素材（`video_editing_materials` 表），新增 `origin = "ai_generated"`，并记录提示词摘要、模型、缓存键和计费 hold id。这样「素材库」里看得到、能复用，用户也可以删除。现有的 `/image-results` 导入接口（`video_editing_material_routes.py:334`）说明这张表本来就支持外来图片。

### 4.5 审核与降级

- **审核**：①提示词侧，规划输出的 `subject` 先过站内已有的文本规则，再加一份敏感词表（医疗功效、绝对化用语、名人等）；②供应商侧，被内容策略拒绝（`content_policy` 一类错误）时，直接降级、不重试、不扣费；③结果侧（第 3 期），用 `tengli_vision_model` 抽检：画面里是否有文字或 logo，和 subject 是否相关。
- **降级顺序**：①缓存里同段落的旧图；②这一段改用模板的文字要点或文字卡表现（模板本来就支持「没有图片时不生成空图片槽」，`contracts.py:297`）；③什么都不加。降级的片段在界面上标「未配图」，并给出原因。

### 4.6 计费

按 `docs/video-pricing-20261125.md` 的公式：

```
上游实际成本 ≈ ¥0.1/张（负责人 2026-11-25 确认）
+ 25% 失败余量（按次收费的供应商操作）→ ¥0.125
× 3 ÷ ¥0.06/积分 = 6.25 → 向上取整 7 积分/张（负责人定价）
```

- 新增计费动作 `editing_auto_image`（`video_credit_prices.VideoPricedAction`、`DEFAULT_PRICES`、`.env.example`、固定测试三处同步改）。
- **每张图一个 hold**：`owner_type="editing_image"`，`owner_id=图片请求 id`。这样符合 `video_credit_billing.hold` 现有的「一个 owner 一个动作一个 hold」模型（132-228），不需要给 hold 加数量参数。生成成功就结算，失败、超时、被审核拒绝就释放；缓存命中不建 hold。
- 用户点「重新生成」会生成一张新图，按一张重新计费，确认弹窗里写明。
- 剪辑按钮上显示的预估：「智能剪辑 · 20 积分 + AI 配图最多 N×7 积分（按实际生成张数）」。
- 已定：7 积分/张（见第 8 节）。和站内单图 5 积分处在同一量级。

### 4.7 界面

在剪辑工作台的分段列表里（`editing-workbench`）：

- AI 配图的片段显示缩略图，右上角是小号文字标签「AI 配图」（不用胶囊加圆点）；
- 三个操作：**预览**（点开大图，并显示这张图出现的时间段）、**替换**（从素材库选一张或上传，原 AI 图保留在素材库）、**重新生成**（可以改一句描述，显示「7 积分」，确认后生成）；
- 降级的片段显示「未配图 · 原因」和「重试」；
- 替换和重新生成之后只重渲染，不重新规划（素材绑定沿用 `video_editing_image_edits` 的替换机制）。

---

## 5. MG 动效模板

### 5.1 资产格式：原生组件 + motiongit 清单（不用 Lottie 作主格式）

理由：

- 现在的渲染器是 PIL/numpy 逐帧合成，没有 Lottie 渲染器。引入 rlottie 或 skia 要加原生依赖，editing 镜像也要重新验证；
- MG 的核心是**中文文字**（标题、数据、卖点）。Lottie 的文字层依赖字形嵌入，中文字体和换行都很难处理；
- 原生组件可以直接复用模板字体（`registry.fonts`）、`raster_cache` 字形缓存和安全区信息。

格式：每个组件一个目录，沿用仓库已有的 `motiongit-template` 规范，把 `contentType` 设为 `"component"`：

```
mg/components/data_callout/
  motion.json          # 清单：id、version、contentType=component、runtime.entry、output.fps、permissions
  params.schema.json   # JSON Schema：可由规划填写的参数
  component.py         # render(params, t, ctx) -> Layer(rgba, bbox)
  tracks.json          # 关键帧轨道：[{prop, keys:[{t, v, ease}]}]，时间以「入场/停留/出场」相对表示
  preview.mp4          # 作者自测样片（不进 bundle 哈希，存示例库）
```

运行时接口：

```python
def render(params: dict, t: float, ctx: Ctx) -> Layer:
    """纯函数：同样的 params、t、ctx 必须输出同样的像素。
    ctx: size, fps, fonts, palette(模板色板 token), safe_zones(人脸/人体/字幕), scale"""
```

- 时间：`anchor = {first_token_id, last_token_id}`，加上 `lead_ms`（默认用 3.1 的提前量）、`in_ms`、`hold`（到词段结束或下一事件）、`out_ms`。编译时换算成秒，并向下取整到帧。
- 缓动：只允许共享 `easing.py` 里的曲线（cubic-out、quint-out、in-out-cubic、柔和弹簧且无回弹）。位移和缩放一律亚像素合成（P5）。
- 合成：用 2.4 节的挂钩，在模板图层字典里指定 z 序（`above: "presenter"` / `below: "captions"`）。模板没有暴露图层时，在最终 RGB 上合成。
- Lottie 作为第 4 期的可选输入：只用于**不含文字**的装饰贴纸和转场遮罩，通过 rlottie 预渲染成 PNG 序列再走同一接口。

### 5.2 参数规范（示例：`data_callout`）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["value", "anchor"],
  "properties": {
    "value":  {"type": "string", "maxLength": 8, "description": "实录里的数值原文，如 72h / 3 倍"},
    "unit":   {"type": "string", "maxLength": 4},
    "label":  {"type": "string", "maxLength": 10},
    "count_up": {"type": "boolean", "default": true},
    "anchor": {"$ref": "#/$defs/span"},
    "placement": {"enum": ["auto", "upper", "lower", "beside_presenter"], "default": "auto"},
    "tone": {"enum": ["ink", "ember", "paper"], "default": "ink"}
  },
  "additionalProperties": false
}
```

所有文字参数都必须绑定实录词段，服务端用现有的 `_span` 校验（`contracts.py:359-385`），和字幕规则一样不允许编造文字。`placement: auto` 由安全区求解：在人脸和字幕区以外，选离锚点最近且足够大的空位。

### 5.3 初始组件库（10 个）

| # | 组件 | 用途 | 动效（默认时长 @25fps） |
|---|---|---|---|
| 1 | `title_reveal` 标题揭示 | 开场或章节大标题 | 遮罩自下而上擦出，字距从 +4% 收到 0；入场 0.48 s cubic-out，出场 0.24 s 淡出 |
| 2 | `lower_third` 人名条 | 姓名和头衔 | 细线从左延展 → 姓名上移淡入 → 头衔延迟 0.12 s；停留后整体左移淡出 |
| 3 | `data_callout` 数据强调 | 数值、倍数、时长 | 数字从 0 计数到目标值（0.6 s，quint-out），单位后补，底部细线标注 |
| 4 | `feature_card` 卖点卡 | 单个卖点（图标 + 两行文字） | 卡片 6% 位移加淡入，图标晚 0.08 s；同一组卡片依次错开 0.1 s |
| 5 | `checklist` 要点清单 | 2–4 条要点 | 逐条按词段起点出现，当前条加粗，其余降到 60% 不透明度 |
| 6 | `compare_split` 对比卡 | A/B、以前/现在 | 左右两半依次滑入，中缝细线后补（对应现有 `comparisons`） |
| 7 | `step_progress` 步骤条 | 第 1/2/3 步 | 节点依次点亮，进度线跟随当前步推进 |
| 8 | `quote_card` 金句 | 结论、引用 | 引号先出现，两行分层揭示（对应现有 `conclusion`） |
| 9 | `transition` 转场 | 段落切换 | 三种：柔和推移（8 帧）、亮度擦除（10 帧）、轻缩放交叉淡化（6 帧）。不做旋转、闪白、故障风 |
| 10 | `marker` 标注 | 圈出或指向画面局部，价格签 | 描边路径动画（stroke-dashoffset 效果），0.4 s；价格签轻微下落，不回弹 |

### 5.4 品牌规则（组件库默认值，CI 强制检查）

- 色板 token：`ink #151311`、`paper #F4F0E9`、`stone #8C857C`、`ember #D9572B`、`amber #E9893A`、`gold #B8955A`。**不允许蓝色和紫色**（负责人决定：只约束新做的 MG 组件，现有模板保留原色）：CI 把所有组件默认色和渲染出的像素转到 HSV，色相 190°–300° 且饱和度 >0.25 的像素占比超过 0.5% 就失败。
- 克制：不用外发光、霓虹描边、粒子、镜头光晕；阴影只允许一层，不透明度 ≤ 18%，模糊 ≤ 24 px；强调色每帧只出现一处。
- 文字：使用模板字体角色（title/body），最小字号 30 px（1080 宽），行宽 ≤ 18 个汉字。
- **组件色板**：模板在元数据里给出自己的中性色（底色、正文色）映射，组件的强调色始终来自上面的暖色板。现有模板里有不少本来就是蓝、紫色系（bihuo-15 蓝白光晕、bihuo-28 紫夜荧光、bihuo-29 紫夜光窗等），按负责人决定这些模板保留原色，但叠加在上面的 MG 组件不继承它们的蓝紫强调色。

### 5.5 模板与组件的对应

每个模板在 `catalog.json` 里新增 `mg` 字段，声明允许使用的组件、每个组件的变体和默认摆位。例如：

```json
"mg": {"palette": "brand-ember", "components": {
  "data_callout": {"variant": "minimal-line", "placement": ["beside_presenter", "upper"]},
  "feature_card": {"variant": "white-rounded"},
  "transition":   {"variant": "soft-push"},
  "marker": {}
}}
```

初始对应（按版式族分组）：

| 版式族 | 模板 | 组件 |
|---|---|---|
| 白卡 / 应用窗口 | bihuo-02/03/04/40/47 | data_callout、feature_card、step_progress、marker、transition(soft-push) |
| 资讯 / 新闻 | bihuo-14/15/23/28/29/33 | title_reveal、lower_third、data_callout、compare_split、transition(luma-wipe) |
| 手记 / 古风 / 暖色 | bihuo-08/09/10/11/13/32/34/36 | title_reveal(纸质变体)、quote_card、marker(手绘描边)、transition(cross-zoom) |
| 抠像 / 沉浸 | bihuo-16/19/26 | data_callout、feature_card(半透明)、transition(soft-push) |
| 双语 / 其他 | bihuo-24/27/48 | lower_third、checklist、quote_card |

模板原有的同类机制（比如 bihuo-02 的清单、bihuo-04 的误区/真相卡）**优先保留**。MG 只补模板没有的表达，例如数据、标注和转场，不和模板自带的动效抢位置。

### 5.6 规划如何填参数

- schema v3 新增 `mg_cues`（最多 8 条）：`{component, anchor:{first,last}, params:{...}}`。提示词里只列出当前模板 `mg.components` 允许的组件，以及每个组件的 `params.schema.json`（压缩成字段名、类型、长度上限）。
- 服务端校验：组件在白名单里；参数符合 schema；文字等于实录词段原文；时间按源顺序且互不重叠；同一时刻最多 1 个 MG 组件加 1 个素材。不合格的条目丢弃，写进 warnings，不让整个计划失败。
- 确定性补充：数值类（`72小时`、`3倍`、`99%`）由服务端用正则在实录里找出来，作为 `data_callout` 的候选提供给模型，减少漏用。

### 5.7 渲染性能

- 组件的静态部分（文字栅格、卡片底板）用 `raster_cache` 按「参数 + 尺寸」缓存，每帧只做变换和合成。
- 预算：每个组件每帧 ≤ 8 ms（1080×1920），10 个组件的基准测试进 CI。按现在 0.56 秒/帧的总耗时，叠加 1–2 个组件影响不到 3%。
- 合成只处理组件的 bbox 区域，不对整帧做 alpha_composite。

### 5.8 新增 MG 组件的流程

1. 设计师在 AE/Figma 里给出参考动效和关键帧表（时长、曲线、位移），以及色板 token；
2. 开发写 `component.py` + `tracks.json` + `params.schema.json`，跑 `tools/mg_preview.py --component X --params sample.json` 出 3 秒样片和联系图；
3. CI 检查：schema 合法；确定性（同一输入渲染两次逐像素一致）；性能 ≤ 8 ms/帧；品牌色检查；安全区回归（放在人脸框上时必须自动避让）；
4. 设计评审样片后，打版本号并写进 `mg/catalog.json` 加哈希锁定（和 bundle 同一机制）；
5. 在需要的模板 `mg` 字段里启用，跑该模板的回归渲染。

---

## 6. 自动化质量检查（可放进 CI）

新增 `backend/tools/video_quality_check.py`，输入是渲染目录（`suite-input.json`、`render-receipt.json`、`final.mp4`），加上渲染时额外输出的**图层时间线** `layers-timeline.json`：由 `video_editing_bihuo_cached_render` 包装 `render_frame`，每帧记录每个图层的 bbox 和平均 alpha，只记数字，开销可以忽略。

| 指标 | 定义 | 阈值（初值，J 实测后校准） |
|---|---|---|
| **sync_gap_ms** | 对每个素材、要点、功能卡和 MG：图层可见度第一次 ≥ 0.5 的帧时刻 − 对应词段第一个词的 `start_ms` | p50 ∈ [−250, 0]，max ≤ +120，任何一个 > +300 都失败 |
| **material_dwell_s** | 每个素材可见度 ≥ 0.5 的连续时长 | ≥ 1.2 s |
| **occlusion_ratio** | 人物图层可见的帧里，人脸框（检测缓存，经人物图层变换映射到输出坐标）被它上方所有图层 bbox 覆盖的面积比例 | 每帧 ≤ 5%；超标帧占人物可见帧 ≤ 1%（全屏 B-roll 段除外） |
| **face_visible** | 在输出帧上用 YuNet 复检（每秒 2 帧）：人物窗口可见时，必须检测到人脸 | 召回率 ≥ 95% |
| **fps_cfr** | ffprobe：`r_frame_rate == avg_frame_rate == 目标值`，`nb_frames == round(duration*fps) ± 1` | 必须相等 |
| **dup_in_motion** | 动画进行中（时间线显示某个图层的 bbox 或 alpha 在变化）的帧里，和前一帧完全相同的比例 | ≤ 2% |
| **media_step_jitter** | 视频素材相邻输出帧对应的源帧序号差（时间线记录）的方差 | 等于 0（步长恒定）；30→25 的 1,1,1,1,2 模式会被判失败 |
| **preview_bitrate** | 预览视频码率 | ≥ 600 kb/s @608×1080 |
| **brand_hue** | MG 图层像素中，色相 190°–300° 且饱和度 > 0.25 的占比 | ≤ 0.5% |

CI 方式：

- 用 3 段固定的测试口播（25 fps 对口型源、30 fps 手机竖拍、人脸偏上的站姿源），乘以每个版式族各 1 个代表模板；只渲染前 12 秒。每次合并跑一次，约 6 个渲染、10 分钟；
- 全模板 × 3 源的完整矩阵放在 nightly；
- 输出 JSON 报告和超标帧的联系图，作为 CI 产物上传。

---

## 7. 分期路线

### 第 1 期（约 1 天）：先修最明显的问题

| 项 | 内容 | 验收 |
|---|---|---|
| 1a | `sync_policy.py`（`bihuo-sync/1`）：锚点回句首、`edge=start`、按模板入场曲线提前、向下取整到帧、素材持续到下一个素材（3.1 第 1–4 条） | 31c23e00 同一计划重渲染（不重新规划，不产生 LLM 费用）：sync_gap p50 ∈ [−250, 0] ms |
| 1b | 预览升级 P1（608×1080，crf 22） | 预览码率 ≥ 600 kb/s；预览 mpdecimate 近似重复帧比例 ≤ 成片 + 3% |
| 1c | `layers-timeline.json` 时间线输出，加上 `video_quality_check.py` 的 sync_gap、dwell、fps_cfr、dup_in_motion、preview_bitrate 五项 | 对改前和改后的渲染各出一份报告，作为对比证据 |
| 1d | 回执里写入 `sync_policy` 版本；旧渲染（没有该字段）保持原行为的测试 | 现有 `test_bihuo*` / `test_video_editing*` 全部通过 |

### 第 2 期（约 1.5 周）：遮挡与顺滑

- `subject.py` 检测缓存、人物窗口跟随人脸取景、叠加框避让（先做白卡/应用窗口族和资讯族，覆盖 11 个模板）；
- P2 素材抽帧统一、P3 交叉过渡、P4 成片编码、P6 统一缓动；
- 质检加上 occlusion_ratio、face_visible、media_step_jitter；
- 验收：3 源 × 11 模板矩阵全部达到第 6 节阈值；设计师逐个模板看过联系图并签字。

### 第 3 期（约 2 周）：AI 自动配图

- schema v3 加 `image_requests`；新增 `generating_images` 阶段；缓存；`editing_auto_image` 计费；降级；工作台的预览、替换和重新生成；
- 验收：
  - 10 条真实口播中，≥ 80% 的配图人工评为「相关且风格统一」；
  - 失败或超时的片段 100% 降级，不阻塞出片，也不扣费；
  - 同一段文案重复渲染时缓存命中率 100%；
  - 账本中冻结、结算、释放与实际生成张数一致。

### 第 4 期（约 3 周）：MG 组件库

- 共享 `easing.py`、亚像素合成（P5）、MG 运行时挂钩、10 个组件、`mg_cues` 规划、5 个版式族的对应、作者工具和 CI；
- 验收：
  - 每个组件通过确定性、性能、品牌色、安全区四项检查；
  - 每个版式族至少 1 个模板启用 MG 并通过设计评审；
  - 加了 MG 的渲染耗时增加 ≤ 5%。

### 第 5 期（视需要）：高帧率

- P8 并行渲染（先做，单片耗时预计降到原来的 40% 左右），然后做 P7 源原生帧率（25→50、30→60）。
- 验收：30 fps 手机源输出 60 fps，人物没有重复帧，media_step_jitter = 0；60 秒视频的渲染耗时不超过现在 25 fps 单进程的耗时。

---

## 8. 负责人决定与待确认

### 8.1 已决定（2026-11-25）

| 议题 | 决定 | 对方案的影响 |
|---|---|---|
| AI 配图价格 | 上游实际成本约 ¥0.1/张，按公式 0.1 × 1.25 × 3 ÷ 0.06 = 6.25，向上取整为 **7 积分/张** | 4.6 节已改为 7 积分；`DEFAULT_PRICES["editing_auto_image"] = 7` |
| 蓝紫色 | 只有**新做的 MG 组件**必须遵守「不用蓝紫」；现有模板保留原色 | 5.4 节的品牌色检查只作用于 MG 组件库，不检查模板自身图层；MG 在蓝紫色模板里也用组件自己的暖色板，不继承模板蓝紫色 |
| 遮挡 | 全屏短 B-roll 可以短暂盖住人物，**单次最长 2.5 秒**；其他卡片和字幕都必须避开人脸 | 3.2 节避让兜底④限定为 ≤2.5 秒的全屏素材，更长的素材必须用前三种方式；第 6 节 occlusion_ratio 的豁免只给 ≤2.5 秒的全屏 B-roll 段 |
| 帧率 | 跟随源帧率（25→25/50，30→30/60），放在并行渲染之后的后期阶段 | 保持第 5 期顺序：先 P8 并行渲染，再 P7 |

### 8.2 仍待确认


1. **配图默认开还是关**：建议默认关、用户手动打开；或者默认开并设上限（例如最多 2 张）？
2. **是否允许 AI 图里出现「商品」**：没有商品图时，我们只画场景和概念，不画商品。有商品图时用参考图模式，但包装细节仍可能有偏差，要不要直接禁止？
3. **预览体积**：预览从约 0.4 MB 增大到约 1.5 MB（11.8 秒），存储和流量是否可以接受？
4. **重新规划的成本**：AI 配图和 MG 都依赖 schema v3，旧计划要享受新能力必须重新规划（10 积分）。是否对已有作品提供一次免费重新规划？
