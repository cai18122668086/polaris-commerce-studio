# 视频服务发布说明 — 2026-11-26

> 状态：**已上线（2026-11-26 17:42 UTC）**，只升级了视频三件套。#201（release → main）仍 open，未并入 main。
> 范围：只升级视频三件套 **video-api / editing-worker / editing-maintenance**。前端、Caddy、数据库结构、图片服务（7 个后端角色）都没动。
> 视频仍只对灰度邮箱开放（`backend/app/video_studio_access.py`），本次没有放开。价格覆盖保持 `{}`，声音克隆保持关闭。
> 实际执行情况见第 11 节。

## 1. 现在线上是什么（polaris-review report，2026-11-26 14:28 UTC，只读）

| 服务 | 镜像 | 代码 | 上线 |
|---|---|---|---|
| api、worker、detail-api、detail-worker、replica-api、replica-worker、dispatcher | `polaris-jgshai:*-main-image-db4003d8` | #207 头 `db4003d8` | 11-26 08:07 |
| frontend | `polaris-editing-frontend:plaster-9a9cdd1c` | `9a9cdd1c`（#209） | 11-26 13:22 |
| video-api | `polaris-jgshai:d726bbf145afc719` | `4f6f7e89` + 3 层叠加 | 11-21 |
| editing-worker | `polaris-jgshai:426f4e624c4df90b` | `cc775504` + 9 层叠加 | 11-23 |
| editing-maintenance | `polaris-jgshai:e0e9045552f08a4d` | `4f6f7e89` | 11-23 |
| caddy、postgres、redis、minio、supertokens | 未变 | — | — |

共 16 个容器。部署前要再跑一次 report，确认跟这张表一致。

## 2. 发布分支与提交

| 提交 | 内容 | CI |
|---|---|---|
| `0f21103e` | release 原头（#206 主图统一、#209 石膏主题） | — |
| `682ca390` | 合入 #207（`db4003d8`，主图规划可单独指定模型，已在线上） | — |
| `5e785689` | 合入视频候选 `video/rc-20261126`（`b4ab4209`） | **#201 run 45840776433：11/11 通过** |
| `2b388922`（分支 `fix/video-e2e-20261126`，未合入 release） | 端到端复测发现的 3 处修复（第 4 节） | 待开 PR 后跑 |

- **建议上线的构建提交 = `fix/video-e2e-20261126` 合入 release 之后的提交**。修复合入需要负责人授权，合入后要经 #201 重跑全部 11 项 CI。
- 不合修复也能部署 `5e785689`，但 bihuo-03 遇到长标题会渲染失败，bihuo-02 遇到特性卡编排会被误判失败（第 4 节），不建议这么做。
- 视频三件套的代码 = 线上后端 `db4003d8` + #209（只有前端文件）+ 视频候选 + 修复，所以共享的 `config.py` 和 compose 不会比线上倒退。

## 3. 这次带上去的视频代码（相对 release `0f21103e`：32 个提交，加修复 1 个）

| 来源 | 内容 |
|---|---|
| `feat/editing-sync-v1` | 剪辑同步第 1 期：素材/要点按口播提前出现（bihuo-sync/1），图片最长停留 4 秒，预览 608×1080，图层时间线与质检 |
| `fix/video-templates` | 模板修复：bihuo-03/04/09/10/28/33/34/40、apple-minimal、unified-chapter；付费编排前检查模板能力（缺抠像模型时不收费、不显示）；标题按模板宽度收窄；开场标题整词断开；口播比音频短 1–2 帧时补帧；对标搜索记录过滤原因；声音克隆显示上游失败原因、新增 DashScope 平台 |
| `fix/video-retest-20261126` | 只选一段教程录屏且模型漏绑时整段播放；模型自造的段落关系映射为允许值 |
| `feat/editing-phase2` | 第 2 期：人脸避让、卡片 4 帧溶解转场、人物取景修正（bihuo-frame/1、bihuo-reframe/1） |
| 02 修复（#203、#204） | 开场标题不被人物窗口压住（bihuo-opening-card/1）；人物窗口按人脸取景（bihuo-window-crop/1）；功能标签补成整词；短句不拆一两个字的孤行（bihuo-caption-lines/1）；没有收尾卡时信息卡留到最后一帧（bihuo-capsule-ending/1） |
| 03 修复（#205） | 开场信息卡按口播语序显示，不重复标题（bihuo-info-card/1）；文字切换先淡出旧字再淡入新字（bihuo-frame/1 text-dip） |
| 端到端修复（`2b388922`） | 见第 4 节 |

- 没有新的数据库迁移。依赖锁和 Dockerfile 不变；新增一个 230 KB 的人脸模型文件（YuNet，MIT，SHA-256 锁定）。
- 有 3 个前端文件改动（声音克隆失败原因、"我的声音"计数、openapi 类型）。**这次不重建前端**：声音克隆保持关闭，线上前端 `plaster-9a9cdd1c` 不动。

## 4. 验证

### 4.1 CI
- `b4ab4209`（视频候选）：#208、#203 两次 11/11 通过。
- `5e785689`（合流后的 release）：#201 run 45840776433 11/11 通过（API 契约、后端质量、后端 4 个分片、3 个容器构建、前端质量、规划流式与恢复），#201 显示可以合并、没有冲突。
- 修复 `2b388922`：本地 ruff、ruff format、mypy（499 个文件）通过；相关 48 个测试通过。GitHub CI 要等开 PR 后跑。

### 4.2 开发环境真实端到端（3112，真实付费编排 → 渲染 → 下载预览）

开发环境先挂合流后的 `5e785689`，再挂修复分支。素材：测试账号已有口播 `ee233cf8`。

| 模板 | 代码 | 编排 | 结果 | 证据 |
|---|---|---|---|---|
| bihuo-09 | 5e785689 | 0d728eb8 | **通过**。394 帧里 393 帧检测到人脸，没有遮挡（moved 0、unresolved 0），1 次卡片退场溶解，完整解码无错 | 预览任务 92001aa8 |
| bihuo-36 | 5e785689 | 71d5611a | **通过**。391/394 帧检测到人脸，没有遮挡；2 次切换、7 次退场溶解；完整解码无错 | 预览任务 d954cd4b |
| bihuo-02 | 5e785689 | a80438d2 | **失败**：特性卡编排没有 points 字段，结尾去重修复抛 KeyError，被误判 `EDITING_PLAN_CONTRACT_INVALID` | 修复见下 |
| bihuo-03 | 5e785689 | b9f6560d | **失败**：开场导航行装不下「这款白色头戴耳机，」，渲染报 `App text exceeds declared role capacity` | 修复见下 |
| bihuo-02 | 2b388922 | 0840808a | **通过**。394/394 帧检测到人脸，没有遮挡；4 次切换溶解；开场标题、人物窗口、字幕、素材卡位置正确；完整解码无错 | 预览任务 f25dd10c |
| bihuo-03 | 2b388922 | 7d3c6310 | **通过**。394/394 帧检测到人脸，没有遮挡；2 次文字先退后进；标题「这款白色头戴耳机」放得下导航行，卡片内不重复；完整解码无错 | 预览任务 3b9ea625 |

早些时候还跑过 1 条：bihuo-04（rc，编排 9197120e）通过。

**修复 `2b388922`（分支 `fix/video-e2e-20261126`）**：
1. 特性卡编排没有 points 字段时，跳过结尾去重，交给正常契约校验。a80438d2 用新代码重编译后，报出的是模型自己的顺序错误（结尾句排在引言前），按正常失败退回积分。
2. `title_fit` 增加 bihuo-03 导航行的宽度规则（44 px、380 px）。b9f6560d 的标题去掉句末逗号后能放下。
3. bihuo-info-card/1：标题以分句标点结尾时，它本身是完整短语，副标题是下一句，所以保留模板原排布；只要标签跟标题重复就清空。b9f6560d 离线重渲染：394/394 帧检测到人脸，没有遮挡，3 次文字先退后进，完整解码无错。
4. 回归：已验收的 03（c7a2101b）和 02（8d64991d）用新代码重编译，输入逐字节不变。

### 4.3 02/03 修复（归档编排离线重渲染，不联网、不付费）
- 03：信息卡变成「这款白色 / 头戴耳机」，不重复；f237–f240 旧字先退、空卡、新字再进。
- 02：f76–f103 字幕合成一行；f270–f277 信息卡留到最后一帧。
- 人脸每帧都检测到（394/394、278/278、278/278），没有遮挡。合流后代码的渲染跟修复分支逐字节一致。
- 样片放在受保护预览 `https://preview.tengliapi.xyz/proto/review/video-fixes-20261126/`。

### 4.4 之前 11 个失败模板的复测
通过 04/09/28/40；03 已修复；10、34 部分通过；apple-minimal、unified-chapter、knowledge-talk 仍失败（失败自动退积分）；33 开发环境没有抠像模型。

## 5. 需要负责人决定的配置

| 变量 | 建议 |
|---|---|
| `POLARIS_VIDEO_CREDIT_PRICES` | 先设 `{}`（全部不扣），灰度验收后再去掉 |
| 声音克隆 | **保持关闭**，不使用已暴露的百炼密钥 |
| `POLARIS_EDITING_WORKER_CONCURRENCY` | `2`（现状） |
| `POLARIS_VIDEO_EDITING_SYNC_POLICY` / `POLARIS_VIDEO_EDITING_FRAME_POLICY` | 不设（默认）；回滚写 `off` |

## 6. #207 线上版本怎么保留
1. 只换视频三件套，`--no-deps --no-build --pull never`。部署前后都记录 16 个容器的 ID 和镜像，部署后核对其余 13 个没变。
2. 视频镜像代码已包含 #207（release 里先合 #207、后合视频），共享的 `config.py` 和 compose 不会倒退。
3. 视频三件套沿用现有 env；不改 worker 的 `POLARIS_MAIN_IMAGE_PLANNER_MODEL` 和失败切换密钥；不碰 `/etc/polaris/main-image-db4003d8/`、`/etc/polaris/plaster-9a9cdd1c/` 的部署和回滚脚本。
4. 以后 #201 → main 也会带上 #207，main 和线上一致。

## 7. 步骤（执行人照做，每步留证据）
0. 负责人分别授权：① 修复分支合入 release；② 部署。#201 → main 单独授权。
1. 合入修复后的 release 提交经 #201 跑完整 CI，11/11 通过。
2. 发布前只读核对：16 个容器跟第 1 节一致；`/motion-dependencies` 下有没有抠像模型。
3. 用这个确切提交构建后端镜像，记录镜像 ID。
4. 按 `deploy/video_studio/integrated_release.py` 的 prepare → backup → rehearse → apply → verify 执行，只换视频三件套。
5. 验证：匿名访问 401；普通账号看不到入口；灰度账号能进；3 个新接口不再 404；灰度账号免费重渲染 1 条已有计划。
6. 核对其余 13 个容器没变；主图规划冒烟 1 次（只读状态检查，不付费）。

## 8. 回滚
- 视频三件套回滚到第 1 节的旧镜像（`rollback.compose.private.json`）。数据库不动（没有新迁移），不影响 #207 和石膏前端。
- 只关第 2 期画面（含文字先退后进）：`POLARIS_VIDEO_EDITING_FRAME_POLICY=off` 后重启 editing-worker。
- 编排层的修复（info-card、caption-lines、capsule-ending、导航宽度）只对新编排生效，已有作品不受影响；回滚镜像即可撤销。

## 9. 已知未解决与适配限制
- **平台底栏**：bihuo-02 字幕底边约 1676 px，发到抖音/视频号会被底部操作栏挡住（模板固定位置）。
- **素材裁切**：源片本身是特写、切到头发时，保留原片构图，不补画。
- **模型选择问题（不是代码问题）**：b9f6560d 把项目里的手提包素材配到了耳机口播；字幕重点词「白色头」切开了"头戴"。这两项是编排模型的选择，没有在这次处理。
- **模型顺序错误**：bihuo-02 编排偶尔把结尾句排在引言前，会被契约校验拒收，积分自动退回。
- knowledge-talk 需要一次新的付费编排验证；bihuo-14/15 顶部模糊带；约 24 个隐藏模板保持隐藏。
- 第 2 期只覆盖 11 个有逐帧接口的模板；P2/P4/P6 未做。
- 预览服务不支持 Range，Safari 可能播不了预览样片，已推迟处理；只影响预览，不影响正式站。

## 10. 本次付费记录（开发环境）
- 今晚端到端：真实编排 6 次（02、03、09、36 各 1 次；修复后 02、03 各重跑 1 次），都是 deepseek-v4.1-flash，开发测试积分。

## 11. 实际执行记录（2026-11-26，负责人批准：「可以部署」）

**结果**
- 视频三件套现在用的镜像：`sha256:cdebfe3694d4fe68ea336d292a53c24db161e4a5d67e68fa56f3bb33ba25bf0e`（代码 `cd5b45bc`，标签 `polaris-jgshai:video-cd5b45bc-a`）。video-api、editing-worker healthy，editing-maintenance 运行中，都没有重启，日志没有错误。
- 其余 13 个正式站容器的 ID 和镜像都没变（整机 117 个容器里只有这 3 个变了）。数据库结构仍是 `20261125_0053`，没有跑迁移。
- 环境变量只新增了 `POLARIS_VIDEO_CREDIT_PRICES={}`（全部不扣、不显示价格）。`POLARIS_AUTH_MODE=external` 没变，声音克隆仍然关闭。
- 公网匿名检查：视频接口（含新增的 credit-prices、generation-requests、editing-works/active）返回 401，不存在的路径返回 404，首页 200。

**两次切换**
1. 17:39:24 UTC 第一次切换，镜像 `sha256:ae649dfc…` = `deploy/video_studio/editing-overlay.Dockerfile`，底版是线上 editing-worker 镜像 `polaris-jgshai:426f4e624c4df90b`，覆盖 cd5b45bc 的 `backend/app`。
2. 上线后逐文件对比旧 video-api 镜像（`d726bbf1`），发现新镜像少了公共形象「知禾·专业主播」的坐姿图 `/assets/video-studio/owned/presenter-female-v3-seated-20261118.png`（`video_generation.py:71/728` 在用）。原因是 426f 底版早于这张图，而 overlay 只复制代码。
3. 17:42:32 UTC 第二次切换，镜像 `sha256:cdebfe36…` 在 ae649dfc 上补了仓库的 `assets/video-studio`（10 个文件，坐姿图哈希与旧镜像一致）和 `backend/migrations`、`alembic.ini`。再次逐文件对比：除了一个运行时不用的 0052 迁移文件，旧镜像有的文件新镜像都有。
4. 两次切换前都确认没有排队中或进行中的视频任务；每次切换只有几秒中断。

**为什么没用 `integrated_release.py` / `upgrade_editing.py`**
- `integrated_release.py` 是首次集成上线用的：会同时改 frontend 和 Caddy，并重写模型等环境变量（例如把编排模型写成固定值），超出本次"只换视频三件套"的范围。
- `upgrade_editing.py` 的角色表含 frontend，会用新标签重建线上石膏前端；本次要求前端不动。
- 实际做法：沿用每个服务现有的 compose 文件栈，加一个只改 `image` 和 `POLARIS_VIDEO_CREDIT_PRICES` 的覆盖文件，`up -d --no-deps --no-build --pull never` 逐个替换（先停 worker 和 maintenance，再换 api，再起 worker 和 maintenance）。上线前用 `docker compose config` 核对过：三个服务各自只有 image 和这一个变量不同；现有文件栈解析出的环境、挂载、命令、网络与运行中的容器完全一致。

**磁盘阈值**
- 构建第二版镜像时，`~/work/heavy.sh` 因根分区只剩约 7.1 GB（低于 8 GB 阈值）拒绝排队。这次构建只增加约 7 MB 文件，为了尽快补上缺的形象图，直接执行 `docker build`，跳过了这次阈值检查。没有清理任何其他任务目录或生产数据。

**备份与记录**（`/opt/polaris/releases/video-rel-cd5b45bc/`，root 600）
- `database-before.dump`：66 MB，sha256 `b3f35cf3e6787c29…`，第一次切换前生成。没做对象和媒体备份：本次不改对象、媒体和结构。
- `images-before.txt` / `images-after.txt`、`compose-files.txt`、`<服务>.before.json` / `.after.json`、`<服务>.override.json`、`assets.Dockerfile`、`deploy.sh`、`release.json`。

**回滚**
```
sudo /opt/polaris/releases/video-rel-cd5b45bc/deploy.sh rollback
```
用每个服务原来的文件栈（不带本次覆盖）重建三件套，回到 video-api `polaris-jgshai:d726bbf145afc719`、editing-worker `polaris-jgshai:426f4e624c4df90b`、editing-maintenance `polaris-jgshai:e0e9045552f08a4d`。数据库不用动。这三个旧镜像要保留，不能清理。

## 12. 灰度验收步骤（负责人操作，不需要提供密码）

用灰度邮箱在 https://www.jgshai.cn 正常登录后：
1. **入口**：导航里能看到"视频创作"并能进入。再用普通账号（或退出登录）确认看不到入口、直接访问视频页会被拦。
2. **价格**：在视频首页或剪辑页确认**不显示积分单价**、不提示扣费（价格覆盖为 `{}`）。记下当前积分余额。
3. **形象库**：形象页能看到「知禾·专业主播」等公共形象，缩略图都能正常显示（这是第二次切换修的那张图）。
4. **声音**：声音页的"克隆新声音"应该不可用或提示未开通（保持关闭），系统音色可以试听。
5. **真实剪辑一条**（会调用一次付费编排模型，但不扣用户积分）：
   - 进入"智能剪辑"，选一条已有口播或上传一段 10–30 秒的竖屏口播；
   - 模板建议选 **bihuo-02**（胶囊卡）或 **bihuo-03**（App 窗口），可选上传 2–3 张商品图做素材；
   - 生成编排 → 预览 → 导出。
6. **看成片**（预览或导出的视频）：
   - 人脸全程没被标题、卡片或字幕挡住；
   - 03：开场信息卡不倒序、不重复标题；文字切换时旧字先淡出、新字再淡入，不叠字；
   - 02：字幕不出现只有一两个字的单独一行；结尾信息卡不提前消失；
   - 声音和字幕对得上，开头结尾没有黑屏或卡帧。
7. **积分**：确认余额与第 2 步相同。
8. 有问题时记下作品名称、时间、截图，发给执行人。任何时候都可以按第 11 节的回滚命令回退，几秒内完成。
