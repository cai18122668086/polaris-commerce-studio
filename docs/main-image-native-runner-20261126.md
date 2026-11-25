# 主图六件套：质量损失定位与「原生 skill 运行器」方案 · 2026-11-26

> 作者：agent X。范围：只读排查 `release/commercial-20261125`（`94b2b52f`），离线运行原版 harness，以及一次经负责人批准的付费 A/B（6 页，1 套）。没有改动发布分支，没有启停 dev 容器，没有部署。
> 原版 skill：`aurora-domestic-ecommerce-main-image` v2.0.0（2026-11-25 之前与仓库 `backend/skill_sources/aurora-domestic-ecommerce-main-image-v20` 逐字节一致）。
> 对照样本：`job_9323577`（第一轮，补丁前）、`job_fc8fd45f`（第二轮 `5e69e556`，网站目前最好的一次）、`job_cff3069`、`job_431e1f7`。
> A/B 产物：服务器 `~/work/skill-native/run-ab/`；Mac `~/polaris-shots/2026-11-26/skill-native/`（`compare.html`）。

## 0. 结论

1. **网站发给生图模型的请求，与原版 skill 在同一端点上发出的请求几乎一样。** 补丁前的 job_9323577，p0/p1 的 prompt 与原版 harness 离线重放的结果逐字节相同；参考图都是同一张源海报，尺寸、质量、模型、edit 模式也都相同。「3.7k–6.9k 字合同和 Python dict」是 skill 自己 `compile_prompt()` 的产物，不是网站绕出来的。
2. **A/B 结果：在同一端点、同一模型上忠实直跑原版 skill，并没有比网站好。** 单页上，原版的搜索主图和场景页更饱满（有真实涂抹动作，信息更全）；但整套明显更差：已判的 7 张图里 7 张主标题都是源海报上的「7天美白 / 一润到底」，与各页主卖点（260g 大容量、烟酰胺·色淡林精华配方、浮光栀子香）无关，版式也反复回到海报的左瓶右字，整套像同一张海报的变体。网站的镜头指令和卖点再分配补丁反而部分压住了这个问题。
3. **因此，「Agent 直跑质量好」的来源不在这层包装里，而在生图这一层。** 最大的单一因素是把源海报作为 `/v1/images/edits` 的输入，并且 `input_fidelity=high`：模型会保留海报的版式和标题，不管 prompt 要求什么（D1）。Agent 环境里的生图工具很可能不是这种调用（Codex 的生图工具保存在 thread 的 generated-image 目录，skill 的恢复规则就是按它写的），但这一点我没有办法在服务器上验证。
4. **集成确实引入了几处损伤**，都可以低成本修掉：与 core-policy 相反的 `COPY_POLICY`（把海报原文判为越权，触发整页重建）；搜索主图八轴校准不看图，用检查分数换算；判官拿不到 visual-audit.md 和 commercial-performance.md；判官被要求照抄版式 token（32/32），防克隆检查形同虚设；不转录源图文案。

**建议的顺序（与原任务设想不同，理由见 §2）：**

1. 先修集成损伤（约 1 天，不增加调用次数）：撤掉 `COPY_POLICY`（负责人已让 M2 改回原版文案规则）；八轴并入 p0 审图同一次调用，真看像素；判官 system prompt 改为 skill 三份 reference 原文；版式字段如实观察；开始前转录源图文案。
2. 再修生图层（1–2 天，小额付费实验）：在 p1、p2 上做单变量对照：`input_fidelity=low`；用本地抠图得到的干净商品图替代海报作为 image[0]，海报只用于转录事实；必要时试 Responses API 的图像工具。指标：海报标题照搬率、版式克隆率、标签逐字正确率。同时请负责人提供一次 Agent 直跑的原始记录（用的是哪个生图工具和模型、实际发出的 prompt），确认「好质量」的基准。
3. 生图层对齐后，再做原生运行器（§3–§8，约 5–6 天，开关 `native_v20`）。它的价值是去掉 5 个补丁和一整层兼容代码、让行为与 skill 原文一致、便于以后直接升级 skill；单靠它不会提升画质。

## 1. 质量在哪里丢的

方法：用 job_9323577 / job_fc8fd45f 保存的输入和商品身份，在服务器副本 `~/work/skill-native/offline*/` 上离线跑原版 `harness.py start → lock-identity → compile → authorize → generate-next`，取出每页的 `generation_request`（`prompt` 与 `imagegen_reference_paths`），与网站同页保存的 `generation-page-N-attempt-1.json` 逐行 diff（脚本 `~/work/skill-native/diff_prompts.py`）。网站的生图字段取自 `XingheGateway.edit`（`xinghe_agent.py:3125-3160`），审图输入取自 `_audit_v20_candidate`（`aurora_main_image_provider.py:1040-1160`）和 `xinghe_agent.py:11841-11870`。

说明：`planner-transport/<job>/` 目录属主为容器用户、权限 0700，本次没有读取（不提权）。生图请求字段由代码路径和每页保存的 generation request 还原；审图输入由代码路径还原。

### 1.1 生图请求：网站和原版几乎一样

| 项 | 原版 harness（离线重放） | 网站实际发送 | 判断 |
|---|---|---|---|
| prompt 来源 | `compile_prompt()` 生成的合同式中文 prompt | 同一 `generation_request.prompt` 原样发送 | 相同 |
| prompt 长度（job_9323577） | p0 4257 字、p1 3825 字 | p0 4257、p1 3825，**逐字节相同**；p2–p5 只差风格校准写入的【视觉世界】一行和 dict 键序 | 相同 |
| prompt 长度（job_fc8fd45f，`5e69e556` 之后） | 3350–3829 字 | 3586–4058 字：多了【镜头】一行、【文案权限】替换了原版的事实权限句、多了【商品名】；p1–p5 的主/辅卖点被网站补丁重新分配 | 网站补丁 |
| 「3.7k–6.9k 字合同黑话和 Python dict」 | **原版自己就是这样**：`str(page["type_hierarchy"])`、`str(style["palette_roles"])` 直接拼接；返修时 `str(repair)` 整段拼入（A/B 中 p0 返修 prompt 7869 字） | 同 | 不是集成引入的 |
| 参考图与顺序 | 初稿：`[source-01.png]`（edit target 与 allowlist 去重后只剩一张） | `[source-01.png]` | 相同 |
| 尺寸 / 质量 | skill 只要求 1:1 且 ≥1024² | `size=1024x1024, quality=high, n=1, output_format=png, input_fidelity=high` | skill 未规定 input_fidelity；网站固定 high |
| 模型 / 端点 | skill 交给「image tool」（Agent 环境自带的生图工具） | `POST {POLARIS_IMAGE_BASE_URL}/v1/images/edits`，`gpt-image-2.5-flare`；备用 Tengli `gpt-image-2` | 见 1.5 |
| edit / generate | 0、1、3、5 页「PRODUCT_PRESERVING_EDIT」，2、4 页「REFERENCE_GUIDED_GENERATION」 | 6 页全部走 `/images/edits`，源海报作为 `image[]` | 在这个端点上两种模式是同一个调用 |
| 返修画布 | `REPAIR_CANVAS_ONLY`：只发失败稿一张；`REBUILD_FROM_PRODUCT_EVIDENCE`：只发原图 | 补丁后：失败稿 + 原图（`session.py` Polaris patch）；返修文字改为 `_repair_lines()` 编号清单 + 标签锁定 | 网站补丁 |
| 出图后处理 | — | 1024² 原样保存；非 1024 时 LANCZOS 缩放 + JPEG q95 | 本例无影响 |

**结论：网站发给生图模型的东西，和原版 skill 在同一端点上会发的东西基本一致。** 第一轮 job_9323577 的 p0/p1 prompt 与原版逐字节相同，仍然出现了「编辑海报 → 版式克隆」。A/B 也复现了这一点（见 §2，原版直跑 p0 首稿同样是源海报的左右版式翻拍）。所以「prompt 太长、全是合同」不是网站绕出来的，而是 skill 自己的 prompt，在 `/images/edits` + 海报做参考 + `input_fidelity=high` 这个组合下的表现。

### 1.2 输入阶段：网站少做了 skill 要求 Agent 做的两件事

1. **源图文案转录。** SKILL.md 要求 Agent 在 `start` 之前，把用户同款商品图上清晰可读的文案转写进 `user_provided_display_facts`；core-policy 明确说这些文案就是用户事实。网站的 `_build_raw()`（`aurora_main_image_planner.py:609`）只放用户在表单里填的卖点，不转录。本例海报上的「密集美白，改善顽固色沉」「精华身体乳」「新品上市」都进不了事实池。
2. **商品身份由 Agent 看图写。** 网站用 `aurora_identity` profile 单独调用一次 LLM，job_9323577 的身份里出现了「Visible 260g designation associated with the product in the source layout」，把海报版式写成了商品身份。A/B 里按 skill 要求由 Agent 写的身份只描述瓶体本身，并逐字锁定瓶身文字「精光身体乳」，明确排除海报背景、标题、规格框。

### 1.3 网站加了一条与 skill 相反的文案规则

`5e69e556` 加入的 `COPY_POLICY`（compiler 补丁，同时进入生图 prompt 和审图合同）规定：「原海报或包装上的营销口号、角标和功效宣称……若不在事实池中，不得作为商品之外的文字出现」。skill 的 core-policy 与 visual-audit.md 恰恰相反：用户原图上可读的文案是用户事实，`no_unsupported_claim` 只在生成图**新增**事实时才失败。

后果（有记录）：
- job_fc8fd45f p0 首稿因为右侧规格框写了海报上本来就有的「精华身体乳」，同时触发 `factual_copy_match`、`no_unsupported_claim`、`no_hard_error` 三项材料性失败；`no_hard_error` 属于 `REBUILD_CHECKS`，于是整页从原图**重建**，而不是在初稿上局部返修。
- job_cff3069 的 p1 交付后仍被记为「带【新品上市】与未授权文案（残留）」。
- job_9323577 的 11 次审图里，`factual_copy_match` 和 `no_unsupported_claim` 失败了 9 次（当时审图模型拿不到事实池，`db2553b3` 已修）。

负责人 11-25 23:04 已让 M2 改回原版文案规则（costs.log「M2-r4 按负责人改用原版文案规则」）。

### 1.4 审图：判官没有拿到 skill 的评判标准，还改了规则

| 项 | skill 期望 | 网站实际 |
|---|---|---|
| 判官读到的标准 | Agent 已读 visual-audit.md、commercial-performance.md、core-policy.md 后看像素 | 自写的 `_AUDIT_SYSTEM_PROMPT`（约 3.5k 字）+ 页面合同 JSON。**三份 reference 的原文都没有进入请求**（`backend/app` 中只有 native-fast 的 manifest 列了它们）。搜索主图的分区比例、四级字体角色、「大商品 + 一句标题 + 装饰背景」退化特征，只能通过合同字段间接传达 |
| 版式观察 | 「观察必须与本页机器合同一致；页码或不同的句子不能证明版式差异」，即先观察，再比对 | system prompt 要求判官「从 layout_observation_contract 原样复制 token，不要写自然语言描述」。32 份网站审图里，5 个版式观察字段 **32/32 与合同完全相同**，包括 8 份 `layout_not_cloned` 判失败的审图。harness 的版式防克隆检查因此失效 |
| 搜索主图八轴校准 | Agent 单独看像素，八轴均分 ≥80 且每轴 ≥65，否则 p0 返修 | `_baseline_observation()`（`aurora_main_image_provider.py:2648`）不看图，把 8 个检查分数映射成 8 个轴：商业闭合 ← `page_role_expression`，文字层级 ← `typography_legibility`，空间纵深 ← `visual_performance_match`。刚通过审图的页面几乎必过（fc8fd45f：91.62）。**skill 专门为搜索主图设的第二道门实际不存在** |
| 分数规则 | 由 harness 判定材料性失败 | `_downgrade_nonmaterial_check_failures()`：只要判官给了整体 PASS，失败项分数被抬到 ≥70，变成建议项 |
| 返修后复审 | 返修稿完整复审；p0 的复审结果还要做八轴校准 | `accept-repair` 补丁：返修稿只查标签和身份（p0 除外），其余失败项不复审，直接记残留 |
| 额外规则 | — | 标签逐字核对门（盲读 + 代码比对，`label_fidelity.py`），失败时注入 `product_identity_match` 失败。这是 skill 没有、但方向正确的增强，应保留 |

### 1.5 退化清单与影响估计

影响分按「对最终交付图的可见质量」主观估计，满分 5。

| # | 退化 | 位置 | 证据 | 影响 |
|---|---|---|---|---|
| D1 | 源海报直接作为 `/images/edits` 的 image[0]，且 `input_fidelity=high`：首稿克隆海报版式，**连海报主标题也照搬**，无视本页 prompt 的主卖点 | skill 设计 × 端点参数 | 9323577 p0/p1 prompt 与原版相同仍克隆；A/B 中 8 张图有 7 张的主标题都是海报上的「7天美白 / 一润到底」，而这些页的主卖点分别是「260g 大容量」「烟酰胺·色淡林精华配方」「浮光栀子香」 | 5（skill 与网站共有，不是集成引入的；网站的镜头指令和卖点再分配补丁反而部分缓解了它） |
| D2 | `COPY_POLICY` 与 core-policy 相反，把海报原文判为越权 | compiler 补丁 + 审图合同 | fc8fd45f p0 因「精华身体乳」被判 hard error 后整页重建 | 4 |
| D3 | 不转录源图文案，事实池只剩表单卖点 | `_build_raw` | 9323577 第 6 页回收首页钩子；文案信息变少，页面变空 | 3 |
| D4 | 判官看不到 visual-audit.md / commercial-performance.md | `_AUDIT_SYSTEM_PROMPT` | grep；审图合同里只有字段 | 3 |
| D5 | 版式观察被要求原样复制合同 token | `_AUDIT_SYSTEM_PROMPT` | 32/32 判断字段与合同相同 | 2–3 |
| D6 | 搜索主图八轴校准由检查分数换算，不看像素 | `_baseline_observation` | 代码；fc8fd45f 91.62 | 3（搜索主图最重要） |
| D7 | 身份分析把海报版式写进 must_preserve | `aurora_identity` profile | 9323577 identity.json | 2 |
| D8 | 返修 prompt 与返修画布被改写；返修后不复审 | compiler / session 补丁 | `_repair_lines`、`accept_repair` | 1–2（方向未定，A/B 原版返修效果见 §2） |
| D9 | 卖点再分配、镜头指令补丁 | compiler 补丁 | diff | ±1（帮助多样性，但偏离原版且未单独验证） |

## 2. A/B：忠实直跑原版 skill vs 网站

**设置。** runner `~/work/skill-native/runner.py`（约 400 行，只用标准库；客户端 `apiclient.py`）按 SKILL.md 扮演 Agent：开始前看图转录源图文案并写 identity → `start / lock-identity / compile`（自动方案）→ 自动 `authorize` → 每页 `generate-next` → **一次**生图（harness 原 prompt + `imagegen_reference_paths` 原序）→ `record-generation` → 判图（system 里放 core-policy.md、visual-audit.md、commercial-performance.md 原文，版式字段如实观察）→ `audit-current` → 至多一次 `prepare-repair` → `calibrate-search`（与 p0 审图同一次调用，看像素）→ `calibrate-style` → `audit-set`。原版 harness 未做任何修改（`~/work/skill-native/skill-orig/`）。

生图与网站完全相同：`POST /v1/images/edits`，`gpt-image-2.5-flare`（POLARIS_IMAGE_* 主线路），`1024x1024 / high / input_fidelity=high / png`。判图用网站分析线路的 `gpt-5.6-sol`（与网站一样，主线路 URLError 后走 failover-1）。输入用 job_9323577 的商品名、品类、4 条卖点和「260g」，同一张源图。对照组是网站目前最好的一次 job_fc8fd45f（同输入）。

**过程（`run-ab/run.log`、`ledger.jsonl`）。** 转录得到「密集美白，改善顽固色沉」「精华身体乳」「新品上市」「OLAY超白瓶美白身体乳」；identity 只描述瓶体并逐字锁定「精光身体乳」。自动方案：p0「7天美白，一润到底」、p1「260g 大容量」、p2「烟酰胺·色淡林精华配方」、p3「浮光栀子香，精致香氛」、p4「260g」、p5「密集美白，改善顽固色沉」。

| 页 | 首稿 | 判图结果 | 返修 | 返修后 |
|---|---|---|---|---|
| p0 搜索主图 | 海报左瓶右字的翻拍 | 74.0，10 项材料性失败（版式与合同相反、无真实证据、无底部闭合） | 画布返修，prompt 7869 字（含 `str(repair)`） | 90.52 通过；八轴 88.25 通过。左字右瓶 + 手臂涂抹乳液，信息完整，是两边最好的一张搜索主图 |
| p1 身份页 | 正面瓶 + 海报标题 | 72.59，失败（未用侧向镜头、版式近似上一页镜像） | 画布返修 | 82.24，残留 `layout_not_cloned`、`approved_plan_fidelity_match`；**标题仍是「7天美白 / 一润到底」** |
| p2 证明页 | 同上 | 69.0，含 hard 项，走 REBUILD | 从原图重建 | 83.9，残留 4 项；标题仍是「7天美白」 |
| p3 场景页 | 人物 + 瓶，标题仍是海报标题 | 85.97，2 项失败 | 画布返修 | 生成后（「浮光栀子香 / 精致香氛」+ 人物涂抹，较好）；复审时按协调要求暂停 |
| p4、p5 | — | — | — | 因生产部署暂停，未生成 |

**结果。**

- 时间：前 4 页（含 4 次返修）18.0 分钟，其中生图 5.4 分钟、判图 12.6 分钟。网站 fc8fd45f 6 页 18.3 分钟。按此速度整套约 26–28 分钟。
- 调用：8 张生图、9 次视觉调用（另有 1 次审图因暂停中断）；视觉 token 入 141k / 出 38k。估算费用（网站单价口径，生图 0.09/张）：生图 0.72 + LLM 约 18 万 token。完整一套预计 11–12 张生图、约 14 次视觉调用，比网站略多。
- 画面（亲自看图，`~/polaris-shots/2026-11-26/skill-native/compare.html`）：
  - 原版更好的地方：p0 搜索主图信息密度、四级文字和真实涂抹动作都比网站强；p3 场景页人物与动作自然。判图更诚实：版式观察写的是真实看到的结构（例如「左侧完整商品、右侧标题与规格卡的双栏商业海报」），所以克隆能被抓到。
  - 原版更差的地方：**整套同质化严重。** 7 张已判图的主标题全是海报的「7天美白 / 一润到底」，p1、p2 的版式和海报几乎一样，「260g 精华身体乳」规格框反复出现。网站那次 6 页标题各不相同，镜头也有差异（侧角、手持、人物、微距、平铺）。
  - 两边共同的问题：奶油色缎面 + 金色的同一种背景，瓶身正面居多。
- 我的判断：单张最好的图出在原版直跑（p0），但作为一套六图，网站 fc8fd45f 更好。**在同一端点上，原生运行器不能复现「Agent 直跑」的质量；质量差距不是包装造成的。**

**为什么。** 同一张源海报在 `/images/edits` + `input_fidelity=high` 下是强约束画布：p1 的 prompt 里主卖点是「260g 大容量」、短标题种子是「260g 大容量」，出图仍是海报标题。harness 的 prompt 越长、越抽象（合同 token、dict），模型越倾向于保留输入图里已经存在的文字和排版。网站的【镜头】和卖点再分配补丁用很具体的镜头指令部分打破了这种锚定，所以网站这一项反而更好。

**未完成部分。** 生产部署期间按要求停止：session 停在 p3（第 4 张）`AWAITING_VISUAL_AUDIT`，没有在途生图。部署结束后执行 `cd ~/work/skill-native && nice -n 19 python3 -I runner.py run-ab skill-orig/aurora-domestic-ecommerce-main-image offline/evidence/source-01.png` 即可原地续跑（约 3–4 张生图），然后重跑 `summarize.py` 和 `make_compare.py` 更新对照页。

## 3. 方案：在现有 worker 里原生运行 skill harness

### 3.1 原则

- **skill 原样 vendored，不打补丁。** 新目录 `backend/skill_sources/aurora-domestic-ecommerce-main-image-v20-native/`，附 sha256 清单，CI 校验与上游包逐字节一致。现有 `-v20` 目录里的 5 个 Polaris 补丁（`accept-repair`、`COPY_POLICY`、`CAMERA_DIRECTIVES`、卖点再分配、返修画布追加原图）不进入新引擎。确实有价值的（如镜头多样化）回到 skill 上游改，并单独 A/B。
- **harness 是唯一的状态机。** 网站代码只扮演 SKILL.md 里的「Agent」：读 harness 返回的请求，调用生图和判图，再把结果交回 harness。不再在网站侧改写合同、补字段、映射分数或替判官补默认值。
- **网站自有的基础设施全部保留**：积分预留/结算、job/job_item 状态机与 outbox、逐页资产落库和工作台逐张展示、断点恢复、网关 failover 与线路熔断、并发准入、标签逐字核对门、存储。

### 3.2 组件

```
JobWorker (现有 celery task, execution.py)
  └─ NativeAuroraEngine                       ← 新增，约 500 行
       ├─ HarnessRunner（复用 AuroraV20HarnessRunner：子进程 + argv 白名单 + 每 job 工作区）
       ├─ AgentDriver                         ← 新增：按 SKILL.md 扮演 Agent
       │    ├─ prestart(): 1 次视觉调用 → 源图文案转录 + identity.json
       │    ├─ judge(page): system = core-policy.md + visual-audit.md + commercial-performance.md 原文
       │    │               user = 身份 / 用户事实池 / 本页合同 / 原图 + 上一页 + 候选图
       │    │               输出 visual-judgment.schema.json；版式字段如实观察
       │    ├─ repair_plan(): 由 harness 的 required_repair 机械生成 repair.schema.json
       │    ├─ search_axes(): 与 p0 审图同一次调用返回（八轴，真看像素）
       │    ├─ style_tokens(): 1 次调用（p0+p1）
       │    └─ set_audit(): 1 次调用（6 张）
       ├─ ImageCall：XingheGateway.edit(prompt=request.prompt, sources=imagegen_reference_paths 原序)
       │    幂等键 = generation_token 摘要 → 一个 token 只允许一次上游调用（skill 规则）
       └─ LabelGate（保留）：盲读结果折算为 product_identity_match 失败，走 skill 自己的 REBUILD 分支
```

### 3.3 状态与恢复

- harness `session.json` 仍是事实来源，每次转移后写 `job_plans`（沿用 `_persist_session`）。
- 恢复：worker 重启时读 `state`。`AWAITING_GENERATED_ASSET` 时用同一幂等键向网关查回第一张已完成的图（对应 skill 的 `recover-generation`，绝不重新生成）；其余状态直接从当前状态继续。
- 页级进度：`audit-current` 判 `ACCEPTED*` 后立刻发布该页资产（与现在一样逐张出现）。
- 并发：skill 要求串行，并且 p0 后有搜索校准、p1 后有风格校准。新引擎只支持串行；`parallel_v20*` 不接入新引擎。

## 4. 从现有包装里去掉什么

| 去掉 | 原因 |
|---|---|
| `COPY_POLICY` 及审图合同里的 `copy_policy`、`authorized_identity_copy` | 与 core-policy 相反（D2） |
| `_AUDIT_SYSTEM_PROMPT` 与 `_normalize_visual_judgment_payload` 的默认值合成、`_downgrade_nonmaterial_check_failures`、`_audit_overall_pass` 等兼容层 | 判官改用 skill 原文标准；格式问题交给 harness 校验，失败就把错误回给判官重写一次 |
| 「从 layout_observation_contract 复制 token」 | D5 |
| `_baseline_observation()` 分数换算 | D6；八轴改为真看像素（和 p0 审图同一次调用，不增加调用次数） |
| harness 补丁 `accept-repair`、`_repair_lines`、返修画布追加原图、卖点再分配、镜头指令 | 回到原版；要保留就去上游改并 A/B |
| `generation_request["authorized_facts"]` 注入 | 事实来自转录后的 input.json，harness 自己持有 |
| `_bounded_visual_audit_sources` 的 4 图上限 | 保留（中继限制），但顺序改为 原图… + 上一页 + 候选 |

保留：`label_fidelity`（作为身份检查的补充）、网关 failover/熔断、积分、资产、outbox、恢复。

## 5. 方案确认：界面确认 vs 自动批准

skill 设计了两个用户检查点：生成前确认方案，生成后看整套。现在网站用 `auto_start_after_plan` 跳过第一个。

- **可选的方案确认步骤（建议做成开关，默认关）**：`compile` 后把 `plan_summary` 渲染成 skill 规定的六行表（页码/职责｜主卖点｜辅助卖点｜画面证明｜构图与主体｜阅读路径/文字层级｜不重复理由｜商业闭合），用户点「开始生成」时把按钮文字作为 `--approval-text` 调 `authorize`。用户可以在这一步删改转录出来的事实（例如去掉「新品上市」），改动走 `restart-campaign` + 重新 `compile`，不花生图费用。代价：多一次等待，用户离开页面就停在 `AWAITING_AUTHORIZATION`。
- **自动批准（默认）**：`authorize --approval-text "自动批准：一键生成"`。harness 不区分这两种文本，下游完全相同。
- 建议：默认自动批准，保证「一键出图」；在工作台提供「先看方案」勾选。界面只需一张只读表和一个确认按钮，后端只需一个 `POST /jobs/{id}/aurora/authorize`（`authorize_aurora_plan` 已存在）。

## 6. 预期质量、时间与成本

按 A/B 实测折算（同一端点、同一模型）：

| | 网站现状（fc8fd45f） | 原生运行器（同端点） | 原生运行器 + §0 第 2 步生图层修复（预期） |
|---|---|---|---|
| 质量 | 单页克制、偏空；六页标题各不相同 | 单页更饱满（搜索主图、场景页更强），但整套被海报主标题和版式拖成同一张图的变体 | 取决于生图层实验；只有这一列有望接近 Agent 直跑 |
| 时间 | 18.3 分钟 | 约 25–28 分钟（每页 生图 ~40 s + 判图 ~100 s，A/B 前 4 页全部返修） | 首稿通过率上升后约 15–20 分钟 |
| 生图次数 | 10 | 约 11–12（每页 2 次居多） | 7–9 |
| 判图调用 | 约 13 | 约 14（判图约 17k 入 / 5–6k 出 token 一次） | 约 10 |

判图耗时仍占约 2/3。上一份诊断里的提速杠杆（判图精简输出、二审移出关键路径、p2–p5 并行）与本方案不冲突，但「p2–p5 并行」违背 skill 的串行约定，原生模式下不采用。

## 7. 迁移与回滚

1. **开关**：新增 `POLARIS_AURORA_EXECUTION_MODE=native_v20`（与 `sequential_v20` 并列），再加按工作区灰度的 `aurora_native_runner_workspaces`。默认仍是 `sequential_v20`。
2. **dev 验证**：同一 OLAY 输入 + 另外 2 个品类（家电、食品各 1），各跑 1 套，对比 `sequential_v20`；指标：首稿通过率、返修率、八轴均分、标签核对、人工盲评。
3. **灰度**：内部工作区 → 10% 新任务 → 全量。job 创建时把模式写进 job 配置，执行中的 job 不受切换影响。
4. **回滚**：把环境变量改回 `sequential_v20` 并重启 worker。新旧引擎的工作区目录（`<job>/native-v20/` vs 现有平铺文件）分开，旧 job 能照常恢复；新引擎已开始的 job 继续由新引擎跑完（按 job 配置分派，不按全局变量）。
5. **清理**：全量稳定两周后，删除 `-v20` 补丁版 skill 和 §4 列出的兼容层。

## 8. 工作量

| 项 | 估计 |
|---|---|
| vendored 原版 skill + sha 校验 + 执行模式开关 | 0.5 天 |
| `NativeAuroraEngine` + `AgentDriver`（转录/身份、判图、返修计划、八轴、风格、整组） | 2 天（A/B runner `~/work/skill-native/runner.py` 约 400 行可直接改写） |
| 接入积分、资产发布、恢复（AWAITING_GENERATED_ASSET 回收）、标签核对门 | 1.5 天 |
| 测试：mock 网关全流程、恢复、回滚、harness 拒绝判断时的重写路径 | 1 天 |
| 可选方案确认 UI（六行表 + 确认按钮 + 开关） | 1 天 |
| dev 三品类验证 + 文档 | 1 天 |
| **合计** | **约 6 天**（不含 UI 为 5 天） |
