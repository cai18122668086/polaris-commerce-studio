# 主图六件套（Aurora v2 标准版）慢与质量问题诊断 · 2026-11-25

> 范围：dev 栈（HK 100.108.64.53）两次真实运行，只读排查，未改代码、未部署、未发起付费调用。
> 代码基线：`origin/release/commercial-20261125` @ `7a44f6f`。
> 样本：
> - `job_9323577dd79d47348bb2079660a53c87`：24m06s，5/6，第 6 页 `HARNESS_BLOCKED`
> - `job_14b899b823c946c18242e1c2ca96c33c`：重试，6m14s，第 6 页 `AURORA_SET_AUDIT_FAILED`
>
> 对照：详情 4 页 5m48s，创意图 33s，白底图 26s。

## 0. 结论摘要

**慢的原因（按影响排序）**

1. **审图比生图更慢，并且占了 65% 的时间。** 每次单页审图调用 `gpt-5.6-sol` 要 70–114 秒，输出 3.6k–5.9k token，其中 29 项检查和 22 个观察字段都要写成散文 JSON。11 次审图合计 946 秒，11 次生图合计 456 秒。
2. **6 页 100% 都走了返修（每页 2 次生图 + 2 次审图），而返修的主要触发原因是一个 bug：审图模型从没收到审核合同。** `_audit_v20_candidate` 组装了 `audit_contract`，里面有 `authorized_fact_pool`、`page_contract` 和 `layout_observation_contract`，并放进了 `product_information`。但 `aurora_v20_visual_audit` 的 prompt body（`backend/app/xinghe_agent.py:11407-11431`）不拼接 `product_information`，`_plan_transport`（`xinghe_agent.py:2520-2560`）也只发送 prompt 文本和图片。所以 11 次审图全部判定「未提供 authorized_fact_pool」，`factual_copy_match` 和 `no_unsupported_claim` 每次都是材料性失败。旁证：6 页首审的 prompt_tokens 是 10480–10489，几乎相同，说明随页变化的合同没有进入请求。
3. **严格串行。** `POLARIS_AURORA_EXECUTION_MODE=sequential_v20`（`config.py:228-233` 默认值，dev 也这样配）。`execution.py:1760-1780` 在数据库层只放行「下一张连续页」。代码里已有 `parallel_v20` 和 `parallel_v20_calibrated`。按 2026-09-16 的 handoff 文档，当时生产用的是 `parallel_v20`，6 页同时启动；2026-10-05 的 `6b27a555 feat(aurora): switch deployment to sequential v20` 改回了串行，提交里没写原因。
4. **第二次审图不改变结果。** 返修后的页面无论审图结论如何都会被接受，失败项只写进 `residual_issues`（`skill_sources/.../v20/scripts/runtime/session.py:346`）。第 1 页的二审有 10 项材料性失败，照样交付。也就是说，二审在关键路径上花了约 75 秒 × 5 页，却不影响交付。

**质量低的原因**

1. **参考图本身是一张带文字和排版的成品海报**（`evidence/source-01.png`）。第 0、1、3、5 页在 `IDENTITY_SENSITIVE_PAGES = {0,1,3,5}`（`runtime/core.py:24`）下走 `PRODUCT_PRESERVING_EDIT`，直接编辑这张海报，结果是排版被克隆。第 6 页首稿与原图几乎逐像素一致；第 1 页和第 2 页首稿基本照搬原图版式。整套 6 页都是同一个正面瓶身、同一套奶油金色飘带，「260g」在 5/6 页出现。
2. **生图 prompt 是 3.7k–6.9k 字的「合同」文本**，混着枚举 token（`ASYMMETRIC_SEARCH_FRAME`）和 Python dict 的 repr（`{'identity': ...}`）。返修时还把审图结论 `str(repair)` 整段拼进去（`compiler.py` 的 `【唯一自动返修】`），而审图结论本身来自上面的 bug，要求「删除 7天美白」，和同一 prompt 里「主卖点=7天美白」直接冲突。图像模型拿到的是互相矛盾的指令，返修大多只删掉一行字。
3. **审图漏掉了真正的保真问题。** 第 4 页交付图的瓶标是「精华身体乳」（原图是「精光身体乳」），`product_identity_match` 却给了 97 分。审图 system prompt 里还残留了别的品类的规则（`aurora_main_image_provider.py:96-101`：wheel count、seat count、red/black partition、steering wheel、dashboard），这是童车案例留下的。
4. **规划把文字型卖点分给了需要视觉证据的页。** `_assign_claims`（`runtime/compiler.py:98-122`）在不重复的事实少于 6 条时用 `ranking[index % len]` 回收。本例的 5 条事实里「260g」和「260g 大容量」实为同一条，第 5 页（规格收口页）就拿到了首页钩子「7天美白，一润到底」（`TEXT_ONLY_VERIFIED`），而且没有辅助卖点。这一页一定会触发「卖点主导但证据非主视觉」的一致性规则，结果在第一次运行中 `HARNESS_BLOCKED`；重试时生成的又是首页翻版，整组审核判失败。
5. **分辨率只有 1024×1024**（`quality="high", size="1024x1024"`，`aurora_main_image_provider.py:206-212`）。详情页用 1440×1920，Amazon 套图用 2048×2048。

## 1. job_9323577 时间拆解

数据来源：`jobs`、`job_items`、`job_attempts`、`job_assets`、`outbox_events`，`/srv/polaris-dev/videodev/data/aurora-main-image/<job>/` 下各文件的 mtime，以及 `planner-transport/.../<job>/*.json` 里的 `api_latency_seconds` 和 usage。

### 1.1 阶段时间线

| 阶段 | 时间 (UTC+8) | 耗时 |
|---|---|---|
| 创建 → outbox 发布 / 开始 | 12:57:22 → 12:58:41 | **79 s**（同一时刻提交的 3 个任务都等了 72–105 s。这是 worker 或 outbox 启动等待，属于环境因素；重试任务只等了 2 s） |
| 商品身份分析（identity，LLM） | 12:58:41 → 12:58:56 | 15 s（主路由 0.1 s URLError，随后 failover-1 用 14.3 s） |
| 六页方案编译（确定性代码，无 LLM） | 12:58:56 → 12:58:57 | <1 s（`job_plans` rev1，213 KB） |
| 第 1–6 页（见下表） | 12:58:57 → 13:22:47 | 23m50s |
| 风格校准（LLM，第 2 页后） | 13:08:02 → 13:08:22 | 20 s |
| 整组审核 | 未执行（第 6 页被阻断） | — |
| 上传 / 落库 / harness 子进程 | 合计 | ≈ 9 s |

### 1.2 逐页（秒）

| 页 | 角色 | 生图1 | 审图1 | 生图2（返修） | 审图2 | 页总计 | 结果 |
|---|---|---|---|---|---|---|---|
| 1 | 搜索主图 | 31 | 107 | 62 | 84 | 4:45 | 交付（带 10 项残留失败） |
| 2 | 身份页 | 37 | 114 | 32 | 75 | 4:40（含风格校准 20） | 交付 |
| 3 | 核心卖点证明 | 32 | 77 | 77 | 86 | 4:33 | 交付 |
| 4 | 场景 / 操作 | 45 | 81 | 36 | 73 | 3:56 | 交付（瓶标文字错误） |
| 5 | 细节 / 信任 | 37 | 99 | 36 | 70 | 4:04 | 交付 |
| 6 | 规格收口 | 31 | 80 | — | — | 1:52 | HARNESS_BLOCKED |
| **合计** | | **456 s（7.6 min）** | **946 s（15.8 min）** | | | **24:06** | 5/6 |

时间占比：审图 65%，生图 32%，其余 3%。

重试任务 `job_14b899`：生图 32 s → 审图 102 s → 返修生图 38 s → 审图 137 s → 整组审核 63 s（`PLANNER_SCHEMA_INVALID`，模型返回非 JSON，延迟 53 s，prompt 13.5k token）。

### 1.3 并发

- 页之间：**严格串行**。`execution.py:1760-1780` 规定只有 `ordinal == 已成功页数` 的那一行能被领取；每页的「生成 → 审图 → 返修 → 审图」也是同一个协程顺序执行（`aurora_main_image_provider.py:168-317`）。
- 生效的限制：dev 上 celery `--concurrency=2`，`POLARIS_XINGHE_CONCURRENCY=4`，`POLARIS_IMAGE_GLOBAL_CONCURRENCY=6`（Redis 准入；生产示例是 40）。串行模式下这三个上限都用不上，同一时刻只有 1 个上游请求。
- 单任务内没有 semaphore 限制页数，瓶颈完全来自串行协议。

### 1.4 上游调用数

| 类型 | job_9323 | 重试 |
|---|---|---|
| 生图 `gpt-image-2.5-flare`（artflow primary），high，1024² | 11 | 2 |
| 身份分析 `gpt-5.6-sol` | 1 | 0（复用） |
| 单页审图 `gpt-5.6-sol` | 11 | 2 |
| 风格校准 | 1 | 0 |
| 整组审核 | 0 | 1（失败） |
| 规划器主路由立即 URLError（每次 LLM 调用前都有一次） | 13 | 3 |

审图 token：输入约 113k，输出约 48.5k，其中推理 1.0k–2.1k/次。`jobs.api_request_count=17`，与实际 24 次有效上游调用不一致，计费和统计口径需要核对。

### 1.5 关键路径

`排队 → identity → [生图 → 审图 → 返修生图 → 审图] × 6（串行）→ 整组审核`。单页约 4.3 分钟，乘以 6。其中约 2/3 是审图 LLM 的输出时间，约 54 token/s × 4.4k token。

## 2. 提速杠杆（单项估算；基线为每页 4.3 min，共 24 min）

| 杠杆 | 机制 / 证据 | 预计节省 | 成本影响 |
|---|---|---|---|
| **A. 把审核合同真正发给审图模型** | 修 `xinghe_agent.py:11407` 的 prompt body，追加 `product_information`（其他 profile 已有同样做法，例如 `:1677`、`:11553`）。首审失败项中，第 3、4 页只有事实池相关的失败；第 1、6 页的 TEXT_ONLY 失败也会被合同里的 `renderable_claim_must_survive_copy_removal=false` 消除 | 预计 3–4 页不再返修，**−7 至 −9 min** | 生图减少 3–4 张，审图减少 3–4 次；单次审图输入增加约 6–10k token，**总成本下降** |
| **B. 精简审图输出** | 输出量决定延迟。改为只返回材料项的 pass/score，失败项附一句证据；22 项 observations 只保留 harness 规则真正用到的字段。目标 ≤1.2k token | 每次审图 85 s → 25–35 s，串行下 **−9 至 −11 min** | 输出 token −70% |
| **C. 二审移出关键路径** | 返修后的结果无论如何都会交付（`session.py:346`）。二审可以后台跑，只用来披露残留问题；也可以直接取消 | 每个返修页 −75 s，**−5 至 −6 min** | 审图次数减少 |
| **D. 并行** | `parallel_v20_calibrated`：先串行生成第 0、1 页（用于搜索和风格校准），再并行第 2–5 页。`parallel_v20`：6 页全部并行。代码已存在，生产在 9 月跑过 | calibrated：关键路径 6 槽变 3 槽，**24 → 约 12 min**；全并行约 5 min | 成本不变；dev 需要 `XINGHE_CONCURRENCY ≥ 4`，`IMAGE_GLOBAL_CONCURRENCY ≥ 6` |
| **E. 分数达标就跳过返修** | 只有身份、事实或硬错误类失败才返修；其余项加权均分 ≥ 80 时直接接受 | 每避免一次返修 −2 min | 成本下降 |
| **F. 换更快的判官模型** | 中继只有 `gpt-5.6-sol` 稳定（`config.py` 注释）。可以给审图 profile 加 `reasoning_effort: low`，推理目前 1–2k token，约 20–35 s | 每次审图 −20 s 左右（B 之后收益变小） | 成本下降；有审图变松的风险 |
| **G. 降低中间分辨率** | 生图已经是 1024，没有下降空间。审图时把 1254 px、1.6 MB 的 PNG 原图缩到 768 送审，只减少少量图像 token | <5% | 成本小幅下降 |
| **H. 缓存商品分析** | identity 只调一次，14 s；重试时已复用 | ≤15 s | — |
| **I. 边出边看** | **已实现**：每页通过后立即写入 `job_assets`（13:03:42、13:08:22……，UTC+8），工作台在 `results.length>0` 时就渲染（`components/domestic-main-image-workspace.tsx:464`）。串行模式下第一张约 5 分钟出现；配合 D 之后约 2 分钟 | 体感提升 | — |
| **J. 超时与 failover** | ① 规划器主路由每次都在 0.1 s 内 URLError（16/16 次），说明 dev 的 primary endpoint 配错或不可达，目前只浪费 0.1 s；但如果变成挂起，就要等 `planner_primary_timeout_seconds=300` 才切换。② `POLARIS_ANALYSIS_TIMEOUT_SECONDS=1200`，审图没有单独的超时上限。③ 整组审核返回非 JSON 时，按 7a44f6f 已改成换键重试 | 防止出现 5–20 min 的长尾 | — |

**组合效果**：A+B+C+D(calibrated) 下，每槽约「生图 40 s + 审图 30 s」，约 1/3 的页需要返修，关键路径 3 槽加整组审核约 **5–7 min**；全并行约 3–4 min。UI 文案「精致版约 40 分钟」（`lib/domestic-main-image-speed.ts`）也要同步修改。

## 3. 质量评估（亲自查看了交付图）

图片路径（dev）：`/srv/polaris-dev/videodev/data/aurora-main-image/job_9323577dd79d47348bb2079660a53c87/generated/page-0{1..5}-attempt-2.png`、`page-06-attempt-1.png`；重试任务：`.../job_14b899b823c946c18242e1c2ca96c33c/generated/page-06-attempt-{1,2}.png`；原图：`.../job_9323577.../evidence/source-01.png`。Mac 截图：`~/polaris-shots/2026-11-25/e2e-image/wb-domestic-main-image/01-top.png … 04-r3.png`。

| 维度 | 观察 | 评价 |
|---|---|---|
| 商品保真 | 瓶型、金色泵颈和底座、OLAY 字标都稳定；**第 4 页瓶标「精光」被写成「精华」**；重试第 6 页二稿泵颈上的 OLAY 压印消失 | 中上，有错字 |
| 构图 | 第 1 页是原图的左右镜像；第 6 页首稿几乎就是原图；6 页都是正面竖瓶加一侧文字 | **弱，同质化严重** |
| 中文排版 | 标题清晰，字重有力，可读性好 | 好 |
| 文字内容 | 「260g」出现 5 次，「7天美白」出现 4 次，每页都在重复原图的文案块 | 冗余 |
| 光线 / 材质 | 统一暖白棚拍，金属反射正确；乳液飘带、金色分子球这类 AI 套路元素偏多 | 中 |
| 整套一致性 | 色调一致，但角度、景别、场景差异不足（只有第 4 页有手部动作，第 5 页有质地微距）；没有上身、涂抹、肌肤这类品类必备画面 | 一致过度，缺少叙事 |
| 分辨率 / 压缩 | 1024² PNG，约 1.1–1.2 MB，无压缩伪影，但放大查看细节不足 | 中 |

**原因定位**

1. **参考图处理**：原图是成品海报，却被当作 `edit_target` 和身份依据直接编辑（`core.py:24`），模型自然倾向于保留原排版和原文案。identity 提取结果里还有一条 must_preserve「Visible 260g designation associated with the product in the source layout」，把海报版式写成了「身份」。
2. **prompt 构造**：合同式 prompt 太长，图像模型不会理解 `ASYMMETRIC_SEARCH_FRAME` 这类 token；Python repr 直接拼接；返修指令和主合同互相冲突（见 §0 质量第 2 点）。
3. **审核标准**：判官看不到合同，所以在错误的维度上打低分（事实池），又在真正的问题上放行（瓶标错字得 97 分、版式克隆只在部分页被发现）；system prompt 里混着童车规则。最后不管审图结论如何，二稿都会交付，审核实际上不起门禁作用。
4. **模型与参数**：`gpt-image-2.5-flare`、`quality=high`、1024²。质量档已经是最高；能提升的是尺寸和参考图的输入方式。dev 上配置的模型名：`POLARIS_IMAGE_MODEL=gpt-image-2.5-flare`，`POLARIS_PROVIDER_FAILOVER_IMAGE_MODEL=gpt-image-2.5-flare`，`POLARIS_TENGLI_IMAGE_MODEL=gpt-image-2`，`POLARIS_ANALYSIS_MODEL` 和 `POLARIS_TENGLI_VISION_MODEL` 都是 `gpt-5.6-sol`。
5. **第 6 页规划**：见 §0 质量第 4 点。规格收口页应该用规格、优惠或服务事实（这里是「260g」加「浮光栀子香」等组成规格簇），而不是复用首页的功效钩子。

## 4. 建议（按优先级）

| # | 建议 | 工作量 | 风险 | 每单成本 | 速度 | 质量 |
|---|---|---|---|---|---|---|
| 1 | **修复审图 prompt 不带合同的 bug**（`xinghe_agent.py:11407` 追加 `product_information=` JSON；加一个断言 prompt 里含 `authorized_fact_pool` 的测试） | 0.5 天 | 低 | ↓（返修减少） | −7~9 min | 审图维度回到正轨，返修变成真正的修复 |
| 2 | **修复卖点分配**：`_assign_claims` 做语义去重（子串或数字相同视为同一条）；第 5 页优先用规格、优惠、服务、属性组成的规格簇；`TEXT_ONLY_VERIFIED` 不能做证明页的主卖点；事实不足 6 条时第 5 页用规格加辅助卖点，不回收钩子 | 0.5–1 天 | 低 | ↓（不再整单重试） | 避免第 6 页失败和 6 min 重试 | 收口页有了实际内容 |
| 3 | **开启 `parallel_v20_calibrated`**（先在 dev 改环境变量实测；核对 09-16 handoff 中 RC-7「strictly in order」的回退路径，并追问 10-05 改回串行的原因） | 0.5 天配置 + 1 天回归 | 中 | 不变 | 24 → ~12 min；配合 1、4 约 6 min | 中性（calibrated 保留了风格校准） |
| 4 | **精简审图输出，二审移出关键路径**（材料项短格式；返修后的审图改为后台残留披露） | 2–3 天（需同步修改 skill `core.py` CHECK_NAMES、`audit.py` 一致性规则和归一化） | 中 | ↓ 约 30% LLM | −10~15 min（串行口径） | 中性 |
| 5 | **参考图预处理**：本地抠出商品（rembg 或 SAM，CPU 运行，无付费），用干净商品图做 edit 参考；海报只用于转录事实。另外新增「每页文案预算」（只放本页主卖点加 ≤1 条辅助）和「镜头多样化」（3/4 侧、俯拍、手持、上身涂抹、质地微距、平铺） | 2–3 天 | 中 | 不变 | — | **最大的质量提升**：消除克隆和同质化 |
| 6 | 重写生图 prompt 为简洁的美术指令（场景 / 镜头 / 光线 / 精确文案及位置 / 商品锁定）；返修指令先过滤掉与硬锁冲突的部分，再转成 ≤3 条具体可见改动 | 2 天 | 中 | 不变 | — | 中高 |
| 7 | 审图加确定性 OCR 校验（PaddleOCR 本地运行）：瓶标文字对照 identity 转录；删掉 system prompt 里的童车规则（`aurora_main_image_provider.py:96-101`） | 1 天 | 低 | 不变 | — | 能拦下「精华 / 精光」这类错字 |
| 8 | 交付前本地 2× 超分到 2048²（Real-ESRGAN，CPU 每张约 5–15 s，可与下一页并行） | 1 天 | 低 | 不变（不加付费） | +5–15 s/页，不在关键路径 | 清晰度提升 |
| 9 | 超时与路由：修复或移除 dev 上不可达的规划器 primary；审图 profile 单独设 120 s 超时并 failover；整组审核用 strict json_schema 并在本地重试一次 | 0.5 天 | 低 | 不变 | 消除长尾 | 降低失败率 |
| 10 | 审图 profile 加 `reasoning_effort: low`（A/B 后再决定） | 0.5 天 | 中（判官可能变松） | ↓ | −20 s/次 | 需要验证 |

**一天内可完成的快速改进**：#1、#2、#3（先在 dev 配置实测）、#9，以及 #7 中删除童车规则那一半。预计效果：用时 24 min → 约 10–12 min，第 6 页失败模式消失，单任务生图次数 11 → 约 7–8 张。

**较深的改动**：#4、#5、#6、#8，以及 #7 的 OCR 部分。完成后预计 5–7 min，画面差异化和保真度明显改善。

**成本提示（每张约 ¥0.1，售价不变）**
- 会**降低**成本的：#1、#2、#4、#10、E（减少返修）。
- 成本**不变**的：#3、#5、#6、#7、#8（本地 CPU）。
- 会**增加**成本的：改为向上游请求 1536² 或 2048²（输出图像 token 约随像素数线性增长，1024² high 是 4160 token）；增加审图轮次；换更贵的判官模型。**这些不建议做，或必须先报价。** #1 会让单次审图输入增加约 6–10k token，但审图总次数减少，净效果是降低。

## 附：关键证据索引

- 串行门：`backend/app/execution.py:1760-1780`；执行模式默认值 `backend/app/config.py:228-233`；dev worker 环境 `POLARIS_AURORA_EXECUTION_MODE=sequential_v20`，celery `--concurrency=2`，`XINGHE_CONCURRENCY=4`，`IMAGE_GLOBAL_CONCURRENCY=6`
- 单页循环和参数：`backend/app/aurora_main_image_provider.py:168-317`（`quality="high"`、`size="1024x1024"`、`range(2)`）
- 审核合同组装：`aurora_main_image_provider.py:751-860`；审图 prompt 不含合同：`backend/app/xinghe_agent.py:11407-11431`；transport 只发 prompt 和图片：`xinghe_agent.py:2520-2560`；`max_completion_tokens=16000`：`xinghe_agent.py:2579-2588`
- 审图 system prompt（含童车规则）：`aurora_main_image_provider.py:59-120`
- 返修后无条件接受：`backend/skill_sources/aurora-domestic-ecommerce-main-image-v20/scripts/runtime/session.py:346`
- 卖点分配回收：`.../runtime/compiler.py:98-122`（第 105 行）；`IDENTITY_SENSITIVE_PAGES`：`.../runtime/core.py:24`；TEXT_ONLY 判定：`.../runtime/style.py:60-67`
- 一致性阻断规则：`.../runtime/audit.py:44`
- 审图记录：`/srv/polaris-dev/videodev/data/aurora-main-image/job_9323577.../judgment-page-*-attempt-*.json`；返修计划 `repair-page-*.json`；生图请求 `generation-page-*-attempt-*.json`；transport 日志 `planner-transport/1b3400719773d5260e1ae701/<job>/*.json`
- UI 进度和逐张展示：`components/domestic-main-image-workspace.tsx:462-464`；速度档文案：`lib/domestic-main-image-speed.ts`
