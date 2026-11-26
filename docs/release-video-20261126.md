# 视频服务发布说明（草稿，待负责人批准）— 2026-11-26

> 状态：**草稿，未部署**。负责人确认前不动正式站。
> 范围：只升级视频三件套 **video-api / editing-worker / editing-maintenance**。前端、Caddy、数据库结构、图片服务都不动。
> 视频仍只对灰度邮箱 `1474953130@qq.com` 开放（`backend/app/video_studio_access.py`），本次不放开。

## 1. 现在线上是什么

| 服务 | 镜像 | 代码 | 上线时间 |
|---|---|---|---|
| video-api | `polaris-jgshai:d726bbf145afc719` | `4f6f7e89` + 3 层叠加 | 11-21 |
| editing-worker | `polaris-jgshai:426f4e624c4df90b` | `cc775504` + 9 层叠加 | 11-23 |
| editing-maintenance | `polaris-jgshai:e0e9045552f08a4d` | `4f6f7e89` | 11-23 |
| frontend | `image-first-86206ecccc8b` | release `86206ecc` | 11-25 |

（来源：`polaris-review report`，2026-11-26。）

## 2. 这次带上去的代码

发布分支：`video/rc-20261126` = `release/commercial-20261125`（86206ecc，正式站当前版本）+ 以下分支，全部无冲突合并：

| 分支 | 内容 |
|---|---|
| `feat/editing-sync-v1` | 剪辑同步第 1 期：素材/要点按口播提前出现（bihuo-sync/1），图片最长停留 4 秒，预览 608×1080，图层时间线与质检 |
| `fix/video-templates` | 模板修复：bihuo-03/04/09/10/28/33/34/40、apple-minimal、unified-chapter；付费编排前检查模板能力（缺抠像模型时不收费、不显示）；标题按模板宽度收窄；开场标题整词断开；口播比音频短 1–2 帧时补帧；对标搜索记录过滤原因；声音克隆显示上游失败原因、新增 DashScope 平台 |
| `fix/video-retest-20261126` | 只选一段教程录屏且模型漏绑时，按开场后到结论前整段播放；模型自造的段落关系（如 chapter）映射为允许值 |
| `feat/editing-phase2` | 剪辑第 2 期：人脸避让、卡片 4 帧溶解转场、人物取景修正（bihuo-frame/1、bihuo-reframe/1），质检加遮挡与人脸可见 |
| `feat/video-pricing`（release 已含） | 视频积分价：口型 50、形象动作 60、声音克隆 30、编排 10、渲染 10、写稿 10、形象登记 5、搜索 5 |

无新数据库迁移（0053 已随图片发布上线）。依赖锁、Dockerfile 不变；新增一个 230 KB 的人脸模型文件随代码打进镜像（YuNet，MIT，SHA-256 锁定）。

## 3. 开发环境验证（3112，真实付费）

- 后端检查：ruff、mypy 全部通过；视频/剪辑/成套模板测试全部通过。
- 之前失败的 11 个可见模板用新代码真实重跑并**导出成片**核对（脸、字幕、转场、锚点；记录 `~/work/e2e/vf-int/ACCEPTANCE.md`）：
  - 通过：bihuo-04、09、28、40；
  - 部分通过：bihuo-03（0–9.6 s 开场卡文案倒序）、bihuo-10（约 11.4 s 起总结按钮无字）、bihuo-34（0–3.5 s 标题断词；6.97–7.91 s 上一句字幕残影重叠）；
  - 仍失败：apple-minimal（模型输出损坏）、unified-chapter、knowledge-talk（图文槽位绑定契约）——这些模板付费编排失败时积分自动退回；
  - 未能出片：bihuo-33（开发环境无抠像模型，编排前拦截、不扣费；旧编排离线复验通过）。
- 第 2 期离线重渲染（不调模型、不联网）：高位人脸源下标题从脸上移到胸前；窗口模板切头经取景修正后人脸回到窗口内（填充带取两角背景）；人物换版式滑动期间不做避让，字幕不来回跳；无冲突的模板逐像素不变。
- **第 2 期尚未在开发环境做端到端（真实编排 → 渲染 → 导出）验证**，上线前需补 3–4 条。

## 4. 需要负责人决定的配置

| 变量 | 建议 | 说明 |
|---|---|---|
| `POLARIS_VIDEO_CREDIT_PRICES` | **先设 `{}`（全部不扣）**，灰度验收后再去掉 | 不设置就按代码默认价扣灰度账号积分 |
| `POLARIS_VIDEO_COSYVOICE_PLATFORM` + 百炼密钥 | 设为 `dashscope`，用负责人的百炼密钥（**先轮换**，旧的在聊天里出现过） | 线上旧的千问代理密钥没开通声音复刻，克隆一直失败 |
| `POLARIS_EDITING_WORKER_CONCURRENCY` | `2`（现状） | 同机还有正式站其他服务 |
| `POLARIS_VIDEO_EDITING_SYNC_POLICY` | 不设（默认 `bihuo-sync/1`） | 回滚写 `off` |
| `POLARIS_VIDEO_EDITING_FRAME_POLICY` | 不设（默认 `bihuo-frame/1`） | 回滚写 `off`，立即恢复第 1 期画面 |

## 5. 步骤（执行人照做，每步留证据）

1. 发布前核对（只读）：正式站视频三件套容器 ID/镜像与第 1 节一致；`/motion-dependencies` 下是否有抠像模型 `model-01eb6a29…`（有则 5 个抠像模板可用，没有则自动隐藏、不收费）。
2. 用 `video/rc-20261126` 的确切提交构建后端镜像，记录镜像 ID。
3. 按 `deploy/video_studio/integrated_release.py` 的 prepare → backup → rehearse → apply → verify 顺序执行；只换 video-api、editing-worker、editing-maintenance，`--no-deps --no-build --pull never`。
4. 验证：匿名访问视频接口 401；普通账号看不到入口；灰度账号能进；3 个新接口（价格、进行中作品、结果核对）不再 404；用灰度账号跑 1 条剪辑（免费重渲染已有计划，不触发付费生成）。
5. 核对其他容器 ID/镜像未变。

## 6. 回滚

- 只回滚视频三件套到第 1 节的旧镜像（`rollback.compose.private.json`），数据库不动（无新迁移）。
- 只想关掉第 2 期画面效果：`POLARIS_VIDEO_EDITING_FRAME_POLICY=off` 重启 editing-worker，不用换镜像。

## 7. 已知未解决

- knowledge-talk 需要一次新的付费编排验证。
- bihuo-14/15 顶部模糊带（冻结模板内部写死）。
- 约 24 个隐藏模板仍因契约失败，保持隐藏。
- 第 2 期只覆盖有逐帧接口的 11 个模板的避让和转场；其余 14 个模板只受益于取景修正。
- 素材抽帧统一（P2）、成片编码（P4）、统一缓动（P6）未做。
