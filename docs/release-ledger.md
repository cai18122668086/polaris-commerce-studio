# Polaris 发布与开发主线记录

当前取证日期：2026-10-17，北京时间。详细状态以 [基线整理结果](baseline-and-release-status-2026-10-17.md) 和 [机器可读生产清单](releases/2026-10-17-observed-production.json) 为准。

| 角色 | 当前版本或用途 |
|---|---|
| GitHub 正式目标 | main，当前 d19fd33；默认分支本来就是 main，本轮未更改 |
| 生产应用源码 | 812a1f7（API/Worker/Dispatcher/Frontend） |
| 生产爬虫源码 | c5eb50e（crawl worker / maintenance） |
| 生产数据库 | 20260930_0025 + 三个 stage 字段 64 的历史手工 DDL；生产未升级；候选已补 20261017_0026，CI 隔离验证 |
| 本地待审基线 | codex/main-reconciliation-20261017，位于 D:\Codex\worktrees\polaris-generation-recovery |
| 主目录过渡归档 | codex/workspace-preserved-20261017；本机 Worker 正在使用此目录的启动环境，禁止在此继续业务开发 |
| 未验收工作 | 9 条 codex/preserve-*-20261017 分支；用途/文件/提交见基线报告 |
| 当前业务优先级 | 国内详情规划与画面质量；国内主图用户实测正常，保护现有路径 |

候选审查：[PR #73](https://github.com/cai18122668086/polaris-commerce-studio/pull/73)，目标 main，草稿状态。它包含已观察的生产历史、两项 Skill 打包完整性修正和单独的历史扩列迁移；国内详情业务修复未混入。合并与上线均未批准。

## 固定流程

1. 从已批准 main 的明确 SHA 建立单一功能分支和 D:\Codex\worktrees 下的隔离工作树。禁止把归档分支整个文件盖到新基线。
2. 一项行为变更一个可审查提交。结构迁移与行为修正分开；其他功能的问题另行登记。
3. 本地合成/脱敏回放 -> 独立 PostgreSQL/Redis/MinIO 与测试账号 -> 主图及共享路径回归 -> 独立真实生成 -> 技术验收与画面验收分别记录。
4. PR 统一面向 main。提交、Skill 锁、依赖锁、迁移、CI、输入输出证据一致；获得用户确认后才合并。历史发布支线只作为来源，逐步停止使用。
5. 发布是独立审批步骤。发布清单必须包含 GitHub 提交、各角色镜像不可变 ID/摘要、Skill 内容哈希、迁移前后状态、队列与旧任务策略、回滚步骤。合并 main 不等于批准发布。
6. 不在服务器临时覆盖代码或使用未记账的源码挂载。紧急修复也先保留证据、在隔离分支验证，形成可追踪提交。
7. 本文件维护流程和版本摘要，日期生产清单保存不可变取证。后续发布追加新的日期清单，不覆盖历史；主文档维护接手入口，外部交付报告由仓库版本导出。

## 当前回滚锚点

保留 812a1f7 与 c5eb50e、机器清单中的实际镜像 ID、当前 Compose SHA-256、`/opt/polaris/releases/generation-recovery-3f91b7d/compose.before.yml` 的存在与哈希。本轮没有更新服务。历史回滚 Compose 仅是资料，未来必须先核对该文件中的镜像/卷/队列与实际兼容性；禁止自动执行旧文件或数据库缩列。

正式主线合并后，通过一次文档提交记录合并 SHA 和 PR；生产更新后，另行记录各服务生效时间与运行中任务处置。未经实际核验不能写成“本地/GitHub/生产全部一致”。
