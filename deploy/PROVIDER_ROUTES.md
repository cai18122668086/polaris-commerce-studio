# 正式站模型与线路（可版本化记录）

唯一来源：`deploy/provider_routes.py` 里的 `PRODUCTION_PROVIDER_ROUTES`。
`compose.production.yml` 的默认值、`.env.production.example`、
`generate_production_env.py` 的默认值都由 `deploy/tests/test_provider_routes.py`
保证与它一致。这里只放地址、模型名和顺序；**所有 key 都不进 Git**，仍由服务器上
现有的私有 env / override 文件注入。

## 当前策略（2026-11-26 起）

| 用途 | 顺序 | 地址 | 模型 |
|---|---|---|---|
| 规划 / 识图 / 审核 | 1–4 | api.ooapi.cc（`POLARIS_PROVIDER_FAILOVER_*`，key 从上到下） | gpt-6.1-sol |
| 规划 / 识图 / 审核 | 最后兜底 | api.jgshai.cn（`POLARIS_ANALYSIS_*`） | gpt-6.1-sol |
| 主图规划 | 同上 | 同上 | gpt-6.1-sol（`POLARIS_MAIN_IMAGE_PLANNER_MODEL`） |
| 出图 | 1 | api.artflow.vip（`POLARIS_IMAGE_*`） | gpt-image-2.5-flare |
| 出图 | 兜底 | api.jgshai.cn（`POLARIS_TENGLI_*`，`POLARIS_REPLICA_IMAGE_FAILOVER_ENABLED=true`） | gpt-image-2 |

`POLARIS_PROVIDER_ROTATION_ORDER=failover,failover-1,failover-2,failover-3,failover-4,failover-*,primary`。

- `failover-*` 代表全部带编号的 ooapi 线路（按 key 的先后），所以不论配了多少个 key，
  全部都排在 jgshai 前面。
- 只配一个 ooapi key 时，线路名是 `failover` 而不是 `failover-1`，所以 `failover` 也写上。
- `failover-1…4` 仍然逐个写出：不认识 `failover-*` 的旧镜像会忽略这个名字，
  照样把现在的 4 个 key 排在前面。
- 正式站现在配了 4 个 key，实际顺序与线上原来的 `failover-1,…,failover-4,primary` 完全相同。
- 注意：在还不认识 `failover-*` 的旧镜像上，第 5 个及以后的 key 仍会排在 jgshai 之后，
  要等用上包含本改动的镜像才生效。

## 核对线上（只读）

在正式站主机上：

```sh
sudo python3 -I deploy/provider_routes.py          # 默认核对 6 个出图/规划服务
sudo python3 -I deploy/provider_routes.py worker   # 只核对一个
```

它只调用 `docker inspect`，输出每个服务的实际线路顺序；不一致时列出差异并返回 1。
key 只报个数、是否重复、是否存在，绝不打印值。dispatcher 只分发任务，不在核对范围。

## 以后重新部署的影响

- 用仓库的 `compose.production.yml` 或 `generate_production_env.py` 新生成配置时，
  默认就是上表；服务器上仍需提供 4 个 key（`POLARIS_PROVIDER_FAILOVER_API_KEY`，逗号分隔）
  以及 `POLARIS_ANALYSIS_API_KEY`、`POLARIS_IMAGE_API_KEY`、`POLARIS_TENGLI_API_KEY`。
  缺 ooapi key 时只剩 jgshai 一条规划线路，核对脚本会报 `failover_key_count` 不一致。
- 正式站现在实际用的是三层叠加：
  `/opt/polaris/releases/image-upload-exif-403cd42ce95a/active.compose.private.json`
  → `/etc/polaris/jgshai-release/<svc>.json`
  → `/etc/polaris/route-ooapi-first-20261126/<svc>.override.json`
  （dispatcher 的第一层是 `/etc/polaris/provider-routing-20261106-0833/active-main.private.json`）。
  显式设置的值优先于本文件的默认值，所以合并本 PR 本身不改变线上任何行为。
  之后的发布要么继续带上第三层，要么改用按本策略新生成的配置；发布后都跑一次核对脚本。
- `deploy/prepare_domestic_detail_release.py` 生成详情页服务时会固定为单账号
  （`POLARIS_PROVIDER_FAILOVER_ENABLED=false`、`ROTATION_ORDER=primary`）。
  重跑它后详情页会退回单线路，需要再叠加第三层，核对脚本会把这种情况标出来。
- `deploy/planner-recovery-20261030/release.py` 是 10-30 的一次性发布脚本，写死了旧顺序
  `primary,failover-1,failover-2,failover-3`，不要再用于正式站。

## 回滚

- 线上：`sudo /etc/polaris/route-ooapi-first-20261126/rollback.sh <服务…>` 恢复成
  jgshai 优先（models-61sol 那一层）；再往前是 `/etc/polaris/models-61sol-20261126/rollback.sh`
  （模型回到改 6.1 之前）。
- 仓库：revert 本 PR 即可，默认值回到 gpt-5.6-sol / ooapi 单线路；不影响已运行的容器。

## 已知线上差异（暂不清理）

一键复刻 API 容器 `polaris-production-replica-api-1`（镜像 `3d0c6bc577bc`）的 `/app/app/`
里多出 6 个 Git 中已没有的文件，日期 2026-11-07，来自 `codex/aliexpress-crawler-20261107`
（3e6ea389）那一版镜像层；叠加构建不会删除旧文件：

- `aliexpress_images.py`
- `amazon_product.py`
- `commerce_images.py`
- `commerce_sources.py`
- `everyinfra.py`（`replica_exact_versions/v16/replica.py` 的 `from .everyinfra` 指向的是 v16 目录下的同名文件，不是它）
- `marketplace_images.py`

当前代码没有任何地方引用它们，对运行没有影响。下次从干净基础镜像重建一键复刻镜像时会自然消失；在那之前不要手动删除线上文件。
