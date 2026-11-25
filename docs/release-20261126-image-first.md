# 生产发布手册：图片功能先行（2026-11-26 凌晨窗口）

> 状态：**草案，待经营者批准**。本文只做准备，未部署、未改动 /opt/polaris 下任何内容。
> 发布源：`release/commercial-20261125`，取证时 HEAD = `7a44f6f2`（当天还会有图片修复合入，执行前按 §0 冻结最终 SHA）。
> 取证方式：`polaris-review report`（只读），polaris-admin 账号下可读的发布记录，以及服务器上 release 分支检出的 `git log/diff`。
> 本文不含任何密钥、口令或环境变量取值。

---

## 发布说明（给经营者）

**用户能看到的变化**

- 首页、帮助中心、灵感专区改为**未登录也能打开**（首页含价格与常见问题），其余页面仍需登录。
- 全站换成「熔光」暗色新版界面（首页落地页、创作首页、各工具页统一风格）。
- 隐私政策更新：写明支付通过支付宝或微信支付完成，去掉英文用词。
- 主图/套图修复：任务状态显示不再失真、第 6 页审核不再硬卡住、素材库不再出现中间图；首页填的商品描述会带进套图工作台卖点栏。
- 高峰保护：单个账号同时最多跑 3 个图片任务；按 IP/会话限流（每分钟 1800/600 次，正常使用碰不到）；超长任务到点自动结束并**退回未用积分**。
- 电商爬虫相关接口改为仅管理员可调用。
- **视频创作不开放**：仍只对一个灰度邮箱可见，其他用户看不到入口（已核对，见 §6）。

**停机与影响**

- 窗口：北京时间 02:00–05:00，预计实际操作 90–120 分钟（其中备份 20–40 分钟，视 MinIO 体量）。
- 用户可感知的中断合计约 **3–5 分钟**，分几段：
  - 数据库重启（参数调整必须重启）：约 **1 分钟**内网站报错/转圈，登录也会暂时失败；
  - 主 API 切换：约 30 秒接口报错；
  - 前端切换：约 20–30 秒页面打不开；
  - 网关（Caddy）重新加载：正常为 0；若线上网关关闭了管理接口，只能重启，会有约 3–5 秒中断，**且同时影响 api.jgshai.cn 与 pay.jgshai.cn**。
- 窗口开始时正在生成的图片任务：先等跑完再切换 worker，不主动中断。

**风险（详见 §4）**

1. **最高风险，已发现**：线上主图服务正在运行的「EXIF 方向照片上传修复」（`403cd42`）**不在发布分支里**。直接发布会让手机竖拍照片上传重新报错。发布前必须把 `403cd42` 合入发布分支（可干净合入，无冲突）。
2. 服务器内存紧张：取证时 swap 已用 3.6/4 GB。新配置放大了数据库、API、worker 的上限，同机还跑着开发/预发环境和多个开发进程。窗口内必须先停掉同机的开发、压测和构建任务。
3. 线上不是用仓库里的 compose 直接部署，而是每个服务各自一份「生成的私有 compose + 覆盖文件」。新配置（API 3 进程、限流、数据库参数、新增 ecommerce-api、网关路由）都要逐个服务手工改写，容易漏项。手册已列出每一项和检查命令。
4. 视频灰度账号：本次不升级视频服务，新前端里的 3 个视频新接口会对灰度账号返回 404（价格显示、找回进行中作品、提交结果核对）。普通用户不受影响。
5. 数据库迁移 0053 只增加字段和约束，旧版本程序兼容，回退时不需要回滚库结构。

**需要经营者确认**：① 同意 02:00–05:00 窗口与上述中断；② 同意先合入 EXIF 修复再冻结版本；③ 冒烟测试会真实生成 1 个主图任务（消耗测试账号少量积分）；④ 首页价格文案已核对。

---

## 0. 冻结版本（窗口前完成）

1. 把 `403cd42ce95a`（`fix: accept EXIF-oriented image uploads without changing originals`，来自 `origin/codex/upload-exif-audit-20261119`）合入 `release/commercial-20261125`。已验证 `git merge-tree HEAD 403cd42` 无冲突；它改动 `backend/app/storage.py`、`backend/app/routes_v1.py` 并新增 `backend/tests/test_upload_exif_integrity.py`。
2. 当天后续图片修复合入后，确定最终 `RELEASE_SHA`（40 位），要求 CI 全绿。
3. 用最终 SHA 重新执行 §2 中的差异命令，确认：迁移仍只有 0053；`backend/requirements.lock`、`package.json`、`package-lock.json` 未变（变了就不能用叠加镜像构建，见 §3.3）；`backend/app` 没有删除文件。
4. 下文 `RELEASE_SHA`、`STAMP=20261126` 都是占位符，执行时替换。

---

## 1. 生产现在是怎么部署的

### 1.1 结论

- 单机：香港生产机（8 核 / 15.6 GB 内存 / 4 GB swap，根分区 296 G，取证时剩余 91 G），Docker Compose 项目名 `polaris-production`，16 个运行中容器。同机还有开发视频栈（`polaris-videodev`）、mpay、tengli，以及开发预览（3130 端口）。
- **没有统一的部署入口。** `/opt/polaris/current` 不存在（brief 说它是普通目录，实际 `ls` 报 No such file or directory）。每个服务由**各自的发布目录**启动，容器标签 `com.docker.compose.project.config_files` 记录的是一串有序的 compose 文件：一份生成的 `active.compose.private.json`，后面跟若干 `*.override.json`。
- 发布记录在 `/opt/polaris/releases/<名称>/` 与 `/etc/polaris/<名称>/`（root 0700/0600）。名称是 `<主题>-<sha12>`。
- 应用镜像大多是**叠加镜像**：先把线上镜像打标签当底座，在上面 `COPY` 修改过的源码，必要时再 `RUN npm run build`，而不是从头构建。

### 1.2 以往发布用的固定套路（取自发布记录）

**A. prepare（生成私有 compose）**，例如 `releases/commerce-cdn-fe636e289932/release_commerce_sources.py`、`deploy/sister-audit-20261030/release.py`、`deploy/release_customer_feedback.py`：

1. `docker inspect polaris-production-<role>-1`，读出 `Image`、`Config.Env`、`Config.Cmd`、`Entrypoint`、网络别名和挂载；
2. 用 `docker compose -f <原 config_files> config --format json` 取出该服务定义，把 env/cmd/网络/挂载换成线上实际值（`$` 转义成 `$$`），去掉 `build`/`depends_on`；
3. 写出 `baseline.json`（各角色 容器ID+镜像ID）、`rollback.compose.private.json`（原镜像）、`active.compose.private.json`（新镜像），全部 0600；
4. `docker compose -p polaris-production -f active.compose.private.json config --quiet`。

**B. apply（切换）**：

```sh
COMPOSE_IGNORE_ORPHANS=true docker compose -p polaris-production -f <root>/active.compose.private.json \
  up -d --no-deps --no-build --pull never <role...>
```

然后等 `State.Health.Status == healthy`；失败就用 `rollback.compose.private.json` 执行同一条命令。最后核对其他角色的容器 ID 和镜像均未变化，写 `release-evidence.json`。

**C. 追加覆盖文件**（最近一次 `releases/bihuo-bgm-20261119/activate.sh`，以及 deploy/README「HK-02 settings」）：

```sh
files=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' polaris-production-<role>-1)
args=(--project-name polaris-production); IFS=, read -ra f <<<"$files"; for x in "${f[@]}"; do args+=(-f "$x"); done
sudo -n docker compose "${args[@]}" -f <root>/<role>.override.json up -d --no-deps --no-build --pull never <role>
```

覆盖文件只写 `{"services":{"<role>":{"image":"sha256:…"}}}` 或需要改的 env。worker 切换前先用 `celery inspect active/reserved` 确认空闲。

**D. 迁移**（`deploy/sister-audit-20261030/release.py`）：先 `stop --timeout 1200` 停 worker 并确认空闲，再用新镜像跑一次性容器：

```sh
docker compose -p polaris-production -f <root>/active.compose.private.json run --rm --no-deps -T \
  api python -m alembic -c /app/alembic.ini upgrade <目标版本>
```

之后 `SELECT version_num FROM alembic_version` 核对，再依次起 API、worker、frontend。

**E. 早期整站切换**（`/opt/polaris/cutover-fb6f581.sh`，2026-09-30，现已不用作整站入口）：env 在 `/etc/polaris/polaris.production.env`；`docker image tag` 旧镜像为 `polaris/rollback-<role>:<stamp>` 并写 `rollback.override.yml`；停 Caddy 和所有写入方后做配对备份（`pg_dump -Fc` + MinIO 卷 tar + sha256），再 `compose up -d --no-build --pull never`，由 `migrate` 服务（`alembic upgrade head`）先跑完。这份脚本的「保留旧镜像标签 + 回滚覆盖文件」做法本次沿用。

### 1.3 各服务当前来源（2026-11-25 08:30 UTC，`polaris-review report`）

| 服务 | 镜像标签 | OCI 源码版本 | compose 来源（发布目录） | 启动时间 UTC |
|---|---|---|---|---|
| api | `polaris-jgshai:db2610a7b1113800` | `403cd42` | image-upload-exif-403cd42ce95a | 11-21 06:40 |
| detail-api | `polaris-jgshai:2fa035d02ecd676a` | `403cd42` | image-upload-exif-403cd42ce95a（+ hk-02 detail-api 覆盖） | 11-23 03:19 |
| detail-worker | `polaris-jgshai:14e0d6974df64443` | `403cd42` | image-upload-exif-403cd42ce95a | 11-23 02:58 |
| replica-api | `polaris-jgshai:94a4e76b1bced332` | `403cd42` | image-upload-exif-403cd42ce95a | 11-21 06:53 |
| replica-worker | `polaris-jgshai:e91911bd3ce71d57` | `403cd42` | image-upload-exif-403cd42ce95a | 11-23 02:58 |
| worker | `polaris-jgshai:e33641aa115d2031` | `403cd42` | image-upload-exif-403cd42ce95a | 11-23 02:58 |
| dispatcher | `polaris-jgshai:dispatcher-queue-ff69077207ef` | 标签写 `e4feefb`（底座标签），实际是底座 `polaris-jgshai:8232edb835e5caa0` + `COPY outbox.py`，该文件与 `a76eb63b` 一致（只差 CRLF） | 报告无引用（配置文件不在 /opt/polaris/releases 下，可能在 /etc/polaris；+ hk-02 dispatcher 覆盖） | 11-23 03:35 |
| frontend | `polaris-editing-frontend:align-sound-20261119` | `abca6ea` | pr192-images-abca6ea, editing-audio-align-e040fdb7734e | 11-21 04:32 |
| video-api | `polaris-jgshai:d726bbf145afc719` | `4f6f7e89` + 叠加 | yiyuan-avatar-f2ecbfff6c23, bihuo-bgm-20261119, avatar-presenter-prompt-cd2a07e93b83 | 11-21 06:53 |
| editing-worker | `polaris-jgshai:426f4e624c4df90b` | `cc775504` + 叠加 | video-pr188-cfr-078d46bc1c14 + 9 个覆盖 | 11-23 02:58 |
| editing-maintenance | `polaris-jgshai:e0e9045552f08a4d` | `4f6f7e89` | video-pr188-cfr-078d46bc1c14 | 11-23 03:00 |
| caddy | `caddy:2.10.2-alpine@sha256:4c6e91c6…` | – | video-editing-d05b3b689dde（整合网关，含 www/api/pay 各域名与视频路由） | 11-21 06:53 |
| postgres | `postgres:18.4-alpine@sha256:9a8afca5…` | – | 2e262616（`deploy/compose.production.yml`，无 `command`，即默认 max_connections=100、shared_buffers=128MB，限 512 MiB / 0.5 核） | 11-21 04:32 |
| redis / minio / supertokens | 固定摘要 | – | 2e262616 | 11-21 04:32 |

数据卷：`polaris-internal-staging_postgres_data`、`polaris-internal-staging_minio_data`、`polaris-internal-staging_redis_data`（历史名称，external）。
crawl-worker / crawl-maintenance 已退役，未运行。没有常驻的 migrate 容器。

**取证限制**：polaris-admin 读不到 root 0700 的发布目录（包括 image-upload-exif-403cd42ce95a、video-editing-d05b3b689dde）、`/etc/polaris`、Docker socket，也不能连库。sudo 读取被本次会话的权限策略拒绝。因此下文凡是写「执行人先核对」的地方，都需要在窗口里用 root 执行只读命令确认。

### 1.4 生产数据库当前版本

所有运行中的后端版本（`403cd42`、`4f6f7e89`、`cc775504`）的迁移目录完全相同，最新都是 `20261116_0052_growth_rewards`。据此推断**生产 head = `20261116_0052`**。没有直接读库，窗口内第一项预检就是核对它（§3.1）。

---

## 2. 从各服务现版本到发布 HEAD 的变更

差异命令（冻结 SHA 后重跑）：

```sh
git diff --stat 403cd42ce95a RELEASE_SHA -- backend/app backend/migrations
git diff --stat abca6ea0fcc3 RELEASE_SHA -- app components features lib public next.config.ts
git diff 403cd42ce95a RELEASE_SHA -- '*.env.example' backend/app/config.py
```

### 2.1 数据库迁移

| 迁移 | 内容 | 是否可回退 | 锁与耗时 |
|---|---|---|---|
| `20261125_0053_video_credit_holds`（down = 0052） | `credit_reservations` 新增 3 个可空列 `owner_type/owner_id/charge_action`；`job_id` 改为可空；加 CHECK `ck_credit_reservations_owner`；建部分唯一索引 `uq_credit_reservations_active_owner` 和普通索引 `ix_credit_reservations_owner` | **可以**。`downgrade()` 会先数 `job_id IS NULL OR owner_type IS NOT NULL` 的行，有视频冻结记录就拒绝回退。本次不升级 video-api，不会产生这类行，因此可回退。**旧版本程序兼容新结构**（新增列可空，旧代码写入总带 job_id，满足 CHECK），应用回滚时**不需要**回退库结构 | PostgreSQL 上 batch 模式是原地 ALTER。ADD COLUMN 与 DROP NOT NULL 只改元数据；加 CHECK 和两次 CREATE INDEX（非 CONCURRENTLY）会短暂锁表并扫一遍 `credit_reservations`。表规模为积分预留记录，预计秒级 |

除 0053 外没有其他待执行迁移。新 api/worker 的 ORM 模型已包含这 3 列，**必须先迁移再启动新镜像**。

### 2.2 图片后端：api、detail-api、detail-worker、replica-api、replica-worker、worker（现 `403cd42` → HEAD）

`backend/app` 共 63 个文件、约 +4570/−155 行，其中视频文件占大半（在这些服务里不会被调用）。依赖锁、Dockerfile、`catalog_assets`、`skill_sources`、`source_manifests` 都没变，`backend/app` 也没有删除文件。图片相关变更：

- **⚠ 回退风险**：`storage.py` / `routes_v1.py` 会退回到 EXIF 修复之前（`ImageOps.exif_transpose(...).size`，且上传持久化阶段的 `UploadValidationError` 不再转成 400）。必须先完成 §0.1。
- `7a44f6f2` 主图任务状态失真、第 6 页审核硬阻断、素材库中间图（`aurora_main_image_provider.py`、`execution.py`、`services.py`、`tasks.py`）。
- `461ad00e` + `68c26518` 每个账号同时运行的任务数上限（图片 `POLARIS_USER_ACTIVE_IMAGE_JOB_LIMIT`，视频 `..._VIDEO_...`），在提交入口执行，因此 api、detail-api、replica-api 都要配置。
- `461ad00e` + `755a8830` 新增 `rate_limit.py`：Redis 固定窗口限流，Redis 不可用时放行；只信任代理网段转发的 XFF。
- `ef40e620` + `a47640a9` 新增 `celery_limits.py`：按队列设置软/硬超时，超时任务正常结算并退回预留积分。
- `9b0993d2` 已登录请求对 SuperTokens Core 的 get_user 缓存 30 秒。
- `database.py`：池参数统一走 `build_database_for(settings)`；`main.py`：挂载限流中间件；新设置 `POLARIS_ECOMMERCE_STARTUP_RECOVERY_ENABLED`。
- `76dd0f0d` 爬虫任务接口仅限管理员。
- `84f0de7a` 媒体下载可走 OSS 全球加速入口（默认关闭）。
- `de886eb1` **代码默认域名**从 tengliapi.xyz 改为 jgshai.cn：`supertokens_api_domain`、`supertokens_website_domain`、`tengli_base_url`、`provider_failover_base_url`、`credit_epay_base_url`、`credit_epay_return_url`、`video_script_base_url`。线上已经跑在 jgshai.cn，说明 env 很可能显式设置了这些值。§3.1 要核对：如果某个变量没有显式设置，切换后会改用新的默认值。
- `image_global_concurrency` 默认值从 3000 改为 40（Redis 全局上游并发）。如果线上 env 没有显式设置，新镜像会**自动**生效 40。
- `credit_payment_routes.py` 小改（回跳地址）；`models.py` 新增 0053 的 3 列。

### 2.3 dispatcher（底座 + `a76eb63b` 的 outbox.py → HEAD）

- `outbox.py`：HEAD 比线上补丁多一段：投递 `process_job` 时附加 `queue_limits(settings, queue)`，也就是 Celery 软/硬超时；另有 `fda1f9c8` 的 import 排列。
- 必须保留 hk-02 覆盖 `POLARIS_RETENTION_ENABLED=false`。

### 2.4 frontend（现 `abca6ea` → HEAD）

266 个文件（不含 backend/docs/tests），`package.json` 与 `package-lock.json` 未变，没有删除文件。

- 熔光暗色全站改版（`fcbc1409`、`d041b746`、`b03c761b`），首页加价格与 FAQ（`37009799`），英文小标题改中文。
- `b81d971a`：`/`、`/help`、`/inspiration` 对未登录访客公开（`lib/auth/routes.ts` 的 `MARKETING_PUBLIC_ROUTES`）。
- 隐私政策（`ffb25191`、`2c07d4ef`、`dcb27b60`）。
- 首页描述带入套图卖点栏（`ff7e1ee1`、`06b3b4bb`、`47874d63`）。
- `next.config.ts` 新增 `basePath: process.env.POLARIS_BASE_PATH`。**生产构建时必须不设置这个变量**，否则全站会挂到子路径下。
- 新增构建期变量（可选）：`NEXT_PUBLIC_ICP_NUMBER`、`NEXT_PUBLIC_PSB_NUMBER`（页脚备案号，不设置则只显示运营主体），`NEXT_PUBLIC_SITE_URL`（默认 `https://www.jgshai.cn`，用于 sitemap 和 robots）。
- 视频空间组件（`components/video-studio`、`features/video-studio`）大量更新，仅灰度账号可见。

### 2.5 视频服务：video-api、editing-worker、editing-maintenance（**本次不升级**）

- 现版本 `4f6f7e89` / `cc775504` + 多层叠加。HEAD 包含这些叠加对应的 PR（#197 `575e8fd6`、#198 `cc775504`、#199 `2d1a450a`、`cd2a07e9`、`f2ecbfff` 均是 HEAD 的祖先），但线上 editing-worker 的音频模块是逐字节锁定的叠加文件（`releases/bihuo-bgm-20261119/baseline.json`），需要单独验证。
- HEAD 的视频计费（`video_credit_billing.py`、`video_credit_prices.py`，`b039f0bd`/`0464084d`）**有代码默认价**：如果升级 video-api 又不设置 `POLARIS_VIDEO_CREDIT_PRICES`，灰度账号会开始被扣积分。所以本次保持不动，计费代码不会运行。
- 旧 video-api 与 0053 后的结构兼容（新增列可空，没有引用）。
- 影响：新前端对灰度账号会调用 3 个旧 video-api 没有的接口，即 `.../credit-prices`、`.../editing-works/active`、`.../generation-requests/{request_id}`，这些会返回 404。
- 以后单独升级视频服务时用 `deploy/video_studio/prepare.py` / `integrated_release.py`，并设置 `POLARIS_VIDEO_CREDIT_PRICES`（`{}` 表示全部不扣）和 `POLARIS_EDITING_WORKER_CONCURRENCY`。

### 2.6 新增服务与基础设施

| 项 | 现状 | 目标（`docs/capacity-20261125.md`、`deploy/compose.production.yml`） |
|---|---|---|
| ecommerce-api（新） | 无 | 与 api 同镜像，**单进程** uvicorn，768 MiB / 0.75 核，挂 `polaris-production_ecommerce_profiles`（external，需先确认存在）与 aurora 工作卷；网络与 api 相同 |
| Caddy | 整合网关，`/api/*` → `api:8000` | 新增 `@ecommerce path /api/ecommerce /api/ecommerce/*` → `ecommerce-api:8000`；所有转发到 Python API 的 `reverse_proxy` 加 `header_up X-Forwarded-For {remote_host}`。站点直连源站（DNS `43.155.30.39` = 本机出口，响应头 `via: 1.1 Caddy`，没有 CDN），`{remote_host}` 就是真实客户端 IP |
| api | 1 进程，384 MiB / 0.5 核（容量文档读数） | `--workers 3`，池 8+8、超时 10 s，`POLARIS_ECOMMERCE_STARTUP_RECOVERY_ENABLED=false`，`--forwarded-allow-ips` 改为私网段，1536 MiB / 1.5 核 |
| worker | 768 MiB / 0.75 核，并发 6 | 池 2+1，1536 MiB / 1.0 核 |
| postgres | 默认参数，512 MiB / 0.5 核 | `max_connections=200`、`shared_buffers=384MB`、`effective_cache_size=1GB`、`work_mem=4MB`、`maintenance_work_mem=64MB`，1536 MiB / 1.5 核 / pids 512。**需要重启** |
| supertokens | 0.5 核 | 1.0 核（可以 `docker update --cpus`，不用重启） |
| editing-worker / editing-maintenance | – | 并发 2、maintenance 256 MiB，属于视频，**本次不做** |

注意：改动前线上的理论连接峰值约 140，已经超过当前的 max_connections=100。所以要**先**调 PostgreSQL，**再**把 api 开到 3 个 worker（多出 32 个连接）。

### 2.7 环境变量

- 必须保持：`POLARIS_WORKSPACE_CREDIT_ENFORCEMENT_ENABLED=true`（brief 确认线上已是 true；仓库 compose 默认是 false，所以新生成的 compose 必须沿用线上值，不能套用仓库默认）。
- 本次需要加到**覆盖文件**里的变量（线上 compose 是从 inspect 生成的，不会自动带上仓库 compose 的默认值；代码默认值是「关闭」）：

| 变量 | 值 | 加到哪些服务 |
|---|---|---|
| `POLARIS_RATE_LIMIT_ENABLED` | `true` | api, ecommerce-api, detail-api, replica-api |
| `POLARIS_RATE_LIMIT_WINDOW_SECONDS` / `_PER_IP` / `_PER_USER` | 60 / 1800 / 600 | 同上 |
| `POLARIS_RATE_LIMIT_TRUSTED_PROXIES` | 不设（用代码默认私网段） | – |
| `POLARIS_USER_ACTIVE_IMAGE_JOB_LIMIT` | `3` | api, ecommerce-api, detail-api, replica-api |
| `POLARIS_USER_ACTIVE_VIDEO_JOB_LIMIT` | 不设（视频不升级） | – |
| `POLARIS_CELERY_SOFT_TIME_LIMIT_{IMAGE,DETAIL,REPLICA}_SECONDS` | 不设即用默认 2400 / 3600 / 3000 | – |
| `POLARIS_CELERY_TIME_LIMIT_GRACE_SECONDS` | 默认 120 | – |
| `POLARIS_DATABASE_POOL_SIZE` / `_MAX_OVERFLOW` / `_POOL_TIMEOUT_SECONDS` | 8 / 8 / 10 | api |
| 同上 | 2 / 1 | worker |
| 同上 | 8 / 8 / 20（hk-02 已有，保持） | detail-api |
| `POLARIS_ECOMMERCE_STARTUP_RECOVERY_ENABLED` | `false` | api（只有 ecommerce-api 做启动恢复） |
| `POLARIS_IMAGE_GLOBAL_CONCURRENCY` | 若线上已显式设置，就保持原值并记录；未设置则新默认 40 自动生效 | 全部图片服务 |

- `.env.example` 新增的变量都是可选的：`NEXT_PUBLIC_ICP_NUMBER` / `NEXT_PUBLIC_PSB_NUMBER` / `NEXT_PUBLIC_SITE_URL`（前端构建期）；`POLARIS_VIDEO_CREDIT_PRICES`（只给 video-api，本次不用）。`POLARIS_TENGLI_BASE_URL` 的示例值改为 `https://api.jgshai.cn`。

---

## 3. 窗口执行手册（北京时间 02:00–05:00）

约定：全部用 root 在生产机执行；`P=polaris-production`；
`R=/etc/polaris/image-first-${RELEASE_SHA:0:12}`（私有文件，0700）；
`S=/opt/polaris/releases/image-first-${RELEASE_SHA:0:12}`（源码和 Dockerfile）；
`B=/opt/polaris/backups/20261126-image-first`。
命令里**不要**用 `docker inspect` 打印完整 Env，只用 `sed 's/=.*//'` 看变量名。

### 3.0 T-1 天（白天，可提前做，不影响线上）

1. 完成 §0，并把 `git archive RELEASE_SHA` 解到 `$S/src`。
2. **核对线上镜像里有没有未入库的补丁**（每个要替换的角色都做）：

   ```sh
   for role in api detail-api detail-worker replica-api replica-worker worker; do
     img=$(docker inspect -f '{{.Image}}' $P-$role-1)
     docker run --rm --network none --entrypoint sh "$img" -c 'cd /app/app && find . -type f -name "*.py" | LC_ALL=C sort | xargs sha256sum' > $R/live-$role.sha
   done
   mkdir -p /tmp/ref403 && git -C <repo> archive 403cd42ce95a backend/app | tar -x -C /tmp/ref403
   (cd /tmp/ref403/backend/app && find . -type f -name '*.py' | LC_ALL=C sort | xargs sha256sum) > $R/ref-403cd42.sha
   for role in ...; do diff $R/ref-403cd42.sha $R/live-$role.sha && echo "$role = 403cd42"; done
   ```

   不一致的文件要逐个确认：是否已在 RELEASE_SHA 里。dispatcher 用同样方法与 `a76eb63b` 比对。
3. 构建镜像（§3.3），可以在 T-1 天晚上做，用 `nice -n 19` 且避开高峰。构建本身不改线上状态。
4. 生成每个角色的覆盖文件和回滚文件（§3.6），然后 `docker compose ... config --quiet` 全部通过。
5. 准备 Caddyfile 候选（§3.7），并在线上 Caddy 镜像里 `validate` 通过。

### 3.1 预检（02:00）

```sh
# 版本与健康
polaris-review report                 # 存档到 $R/pre-report.txt
docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | sort > $R/containers-before.txt
for c in $(docker ps --format '{{.Names}}' | grep ^$P-); do
  echo "$c $(docker inspect -f '{{.Image}} {{.RestartCount}} {{index .Config.Labels "com.docker.compose.project.config_files"}}' $c)"; done > $R/baseline.txt
# 数据库版本必须是 20261116_0052
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c 'SELECT version_num FROM alembic_version'
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c 'SHOW max_connections; SHOW shared_buffers; SELECT count(*) FROM pg_stat_activity'
# 进行中的工作（为 0 最好；不为 0 就等它们结束，或记录下来后继续）
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c "SELECT status, count(*) FROM jobs WHERE status IN ('queued','planning','processing','cancelling') GROUP BY 1"
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c "SELECT count(*) FROM outbox_events WHERE status IN ('pending','publishing','failed')"
# env：只看变量名和布尔开关，不打印值
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' $P-api-1 | sed 's/=.*//' | sort > $R/api-env-names.txt
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' $P-api-1 | grep -c '^POLARIS_WORKSPACE_CREDIT_ENFORCEMENT_ENABLED=true$'   # 必须 = 1
grep -E 'SUPERTOKENS_(API|WEBSITE)_DOMAIN|TENGLI_BASE_URL|PROVIDER_FAILOVER_BASE_URL|CREDIT_EPAY_(BASE|RETURN)_URL|IMAGE_GLOBAL_CONCURRENCY' $R/api-env-names.txt
#   ↑ 缺少哪个，就要在覆盖文件里显式写入线上现用值（取值从 tengliapi 默认改成 jgshai 默认会改变行为）
# 卷与网络
docker volume ls --format '{{.Name}}' | grep -E 'ecommerce_profiles|aurora|minio_data|postgres_data'
docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' $P-api-1 $P-caddy-1
# 资源
free -m; df -h / ; df -i /
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' | sort
# Caddy 管理接口是否开启（决定 §3.7 能否 reload）
docker exec $P-caddy-1 sh -c 'grep -nE "^\s*admin" /etc/caddy/Caddyfile || echo "admin 未声明=默认开启 localhost:2019"'
```

预检同时要做到：

- 暂停同机的开发和压测：`~/work/preview-release.sh stop`（3130），确认 `~/work/loadtest/RUNNING` 不存在，`heavy.lock` 没有被占用；按容量文档第 3 节停掉 `polaris-videodev` 的 editing-worker；宿主机上不要有 node/workerd/pytest。
- swap 用量 > 1 GB 时，先停开发栈，再等 swap 回落（必要时 `swapoff -a && swapon -a`，前提是可用内存足够）。

### 3.2 全量备份（02:10，在线，无停机）

使用 release 分支的 `deploy/backup/polaris-backup.sh`。它在线执行：pg_dump 用导出快照做一致性备份，同时生成逐表行数；MinIO 用 `mc mirror` 增量镜像；不停止任何容器。

```sh
# 1) 磁盘检查：需要 ≥ max(20G, 2×镜像体积 + 备份体积 + 10G)
du -sh /var/lib/docker/volumes/polaris-internal-staging_minio_data/_data
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c "SELECT pg_size_pretty(pg_database_size('polaris'))"
df -B1G --output=avail / | tail -1
docker system df          # 只看，不要 prune

# 2) MinIO 凭据文件：从容器 env 直接写入 0600 文件，不在终端显示
install -d -m 700 $B
umask 077; docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' $P-minio-1 \
  | grep -E '^MINIO_ROOT_(USER|PASSWORD)=' > $R/minio-backup.env
test "$(wc -l < $R/minio-backup.env)" = 2
#   脚本要求的是 MINIO_ROOT_USER/PASSWORD；生产 env 文件里叫 POLARIS_MINIO_ROOT_*，所以不能直接传 env 文件

# 3) 先 dry-run，再正式执行
bash $S/src/deploy/backup/polaris-backup.sh --pg-container $P-postgres-1 --minio-container $P-minio-1 \
  --minio-env $R/minio-backup.env --target $B --keep-days 30 --dry-run
bash $S/src/deploy/backup/polaris-backup.sh --pg-container $P-postgres-1 --minio-container $P-minio-1 \
  --minio-env $R/minio-backup.env --target $B --keep-days 30
tail -5 $B/backup.log

# 4) 校验
D=$(ls -t $B/pg/polaris-*.dump | head -1)
sha256sum "$D" | awk '{print $1}' | diff - "$D.sha256"
docker exec -i $P-postgres-1 pg_restore -l < "$D" | grep -c 'TABLE DATA'
wc -l "$D.counts"; find $B/minio -type f | wc -l
# 5) 可选：恢复演练（在生产 postgres 里建临时库，结束后删除，会增加数据库负载，建议备份完成后执行）
ALLOW_PRODUCTION_DRILL=1 bash $S/src/deploy/backup/polaris-restore-drill.sh --pg-container $P-postgres-1 --dump "$D" \
  --minio-container $P-minio-1 --minio-env $R/minio-backup.env --mirror $B/minio
# 6) 同时保存当前 Caddyfile 与各角色的 compose 文件清单
docker cp $P-caddy-1:/etc/caddy/Caddyfile $R/Caddyfile.before && chmod 600 $R/Caddyfile.before
```

备份通过的条件：`backup.log` 以 `backup done` 结尾；sha256 一致；`pg_restore -l` 能列出内容；`.counts` 行数大于 0；镜像对象数与源端接近（`mc mirror` 不加 `--remove`）。这份备份和线上在同一块盘上，条件允许时要拷到异机。旧香港机只剩约 9.5 G，容量不够时要另找存储。

**回滚（本步）**：备份不改线上，失败就中止发布，不需要回滚。

### 3.3 构建镜像（T-1 晚或 02:30）

依赖未变，按以往发布的做法，**在各自线上镜像上叠加源码**，保留每个镜像原有的依赖、Chromium 和入口。

```sh
STAMP=20261126; cd $S
# 旧镜像打回滚标签（不要 prune）
for role in api detail-api detail-worker replica-api replica-worker worker dispatcher frontend; do
  docker image tag "$(docker inspect -f '{{.Image}}' $P-$role-1)" polaris/rollback-$role:$STAMP; done

# 后端叠加（每个角色一份，底座就是它自己的回滚标签）
cat > backend-overlay.Dockerfile <<'EOF'
ARG BASE
FROM ${BASE}
USER root
COPY src/backend/app/ /app/app/
COPY src/backend/migrations/ /app/migrations/
COPY src/backend/alembic.ini /app/alembic.ini
ARG REV
LABEL org.opencontainers.image.revision=${REV}
USER 10001:10001
EOF
for role in api detail-api detail-worker replica-api replica-worker worker dispatcher; do
  docker build --network none -f backend-overlay.Dockerfile --build-arg BASE=polaris/rollback-$role:$STAMP \
    --build-arg REV=$RELEASE_SHA -t polaris-jgshai:$role-image-first-${RELEASE_SHA:0:12} . > build-$role.log 2>&1
done
# 先用原镜像确认用户：docker image inspect -f '{{.Config.User}}' <旧镜像>，USER 行与之保持一致

# 前端叠加：保留旧的哈希静态资源，避免已打开旧页面的用户加载 chunk 404
cat > frontend-overlay.Dockerfile <<'EOF'
ARG BASE
FROM ${BASE}
USER root
WORKDIR /app
ENV VITE_LOCAL_DEV_AUTH=false
COPY src/app /app/app
COPY src/components /app/components
COPY src/features /app/features
COPY src/lib /app/lib
COPY src/public /app/public
COPY src/next.config.ts /app/next.config.ts
COPY src/backend/app/processing_notice.json /app/backend/app/processing_notice.json
RUN if [ -n "${POLARIS_BASE_PATH:-}" ]; then echo "POLARIS_BASE_PATH must be unset" >&2; exit 1; fi; \
    if [ -d /app/dist/client/_polaris-static ]; then cp -a /app/dist/client/_polaris-static /tmp/prev-static; fi; \
    npm run build > /tmp/build.log 2>&1 || { tail -80 /tmp/build.log; exit 1; }; \
    if [ -d /tmp/prev-static ]; then cp -an /tmp/prev-static/. /app/dist/client/_polaris-static/; fi
ARG REV
LABEL org.opencontainers.image.revision=${REV}
USER 1000:1000
EOF
docker build --network none -f frontend-overlay.Dockerfile --build-arg BASE=polaris/rollback-frontend:$STAMP \
  --build-arg REV=$RELEASE_SHA -t polaris-editing-frontend:image-first-${RELEASE_SHA:0:12} . > build-frontend.log 2>&1
# 记录不可变 ID
for t in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep image-first-${RELEASE_SHA:0:12}); do
  echo "$t $(docker image inspect -f '{{.Id}}' $t)"; done > $R/candidate-images.txt
```

构建验收：

- 前端：容器内 `grep -rl 'theme-ember' /app/dist | head -1` 能找到；抽查 `/app/dist/client` 下的资源地址，应以 `/_polaris-static/` 开头，不能带 `/site/` 子路径前缀。
- 后端：`docker run --rm --network none --entrypoint python <api 新镜像> -c "import app.rate_limit, app.celery_limits; from app.storage import validate_prepared_image"` 通过，且 `grep -c exif_transpose /app/app/storage.py` 为 0（EXIF 修复已包含）。
- 如果 `package-lock.json` 或 `requirements.lock` 有变化，就不能用叠加构建，改用 `deploy/backend.Dockerfile` / `deploy/frontend.Dockerfile` 加线上相同的基础镜像摘要完整构建，并预留拉取依赖的网络时间。

**回滚（本步）**：只新增了镜像标签，不需要回滚。

### 3.4 PostgreSQL 参数与重启（02:45，预计数据库不可用 30–60 秒）

为什么先做这一步：api 开到 3 个 worker 以后连接数会超过当前的 100；而且参数和镜像分开改，出了问题容易定位。

```sh
# 1) 等 worker 空闲（celery inspect active/reserved 为空），再暂停投递和消费，避免任务在数据库重启时失败
for w in worker detail-worker replica-worker; do docker exec $P-$w-1 celery -A app.celery_app:celery_app inspect active --timeout 5 | tail -3; done
docker stop -t 1200 $P-dispatcher-1 $P-worker-1 $P-detail-worker-1 $P-replica-worker-1
# 2) postgres 覆盖文件
cat > $R/postgres.override.json <<'EOF'
{"services":{"postgres":{
  "command":["postgres","-c","max_connections=200","-c","shared_buffers=384MB","-c","effective_cache_size=1GB",
             "-c","work_mem=4MB","-c","maintenance_work_mem=64MB"],
  "mem_limit":"1536m","cpus":1.5,"pids_limit":512}}}
EOF
files=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' $P-postgres-1)
envf=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.environment_file"}}' $P-postgres-1)
args=(-p $P); [ -n "$envf" ] && args+=(--env-file "$envf"); IFS=, read -ra f <<<"$files"; for x in "${f[@]}"; do args+=(-f "$x"); done
printf '%s\n' "${args[@]}" > $R/postgres.compose-args          # 回滚用
docker compose "${args[@]}" -f $R/postgres.override.json config --quiet
docker compose "${args[@]}" -f $R/postgres.override.json config --format json | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]["postgres"]; print(s["command"], s["volumes"])'
#   确认卷仍是 polaris-internal-staging_postgres_data，镜像摘要未变
# 3) 重建（官方镜像 STOPSIGNAL=SIGINT 走快速关闭，stop_grace_period 60 s）
time COMPOSE_IGNORE_ORPHANS=true docker compose "${args[@]}" -f $R/postgres.override.json up -d --no-deps --no-build --pull never postgres
until [ "$(docker inspect -f '{{.State.Health.Status}}' $P-postgres-1)" = healthy ]; do sleep 2; done
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c 'SHOW max_connections; SHOW shared_buffers'   # 200 / 384MB
# 4) 恢复旧 worker 和 dispatcher（仍是旧镜像），确认 api / supertokens / video-api 自动重连（pool_pre_ping）
docker start $P-worker-1 $P-detail-worker-1 $P-replica-worker-1 $P-dispatcher-1
curl -fsS https://www.jgshai.cn/health/ready
```

- 预计影响：PostgreSQL 停止加启动通常在 10–20 秒内完成；健康检查通过、各服务重连，合计 30–60 秒。这段时间网站接口报错，登录失败。
- SuperTokens 如果 1 分钟内还没恢复，执行 `docker restart $P-supertokens-1`（约 20 秒）。
- supertokens CPU：`docker update --cpus 1.0 $P-supertokens-1`，不用重启；同时写进它的覆盖文件，避免下次重建时被还原。

**回滚（本步）**：用 `$R/postgres.compose-args` 里的原文件列表，不带覆盖文件，执行 `up -d --no-deps --no-build --pull never postgres`，回到默认参数和 512 MiB，影响同样约 1 分钟。如果数据目录损坏（极少见），按 §3.10 的恢复流程处理。

### 3.5 迁移 0053（03:00，在线）

```sh
# 用新 api 镜像跑一次性迁移，网络和 env 与 api 相同（用 §3.6 生成的 api 覆盖参数）
docker compose $(cat $R/api.compose-args) -f $R/api.override.json run --rm --no-deps -T \
  api python -m alembic -c /app/alembic.ini upgrade 20261125_0053
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c 'SELECT version_num FROM alembic_version'   # 20261125_0053
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c "\d credit_reservations" | grep -E 'owner_type|charge_action|ck_credit_reservations_owner'
```

如果 `run` 带出了 `depends_on`，加 `--no-deps`（已加）。迁移只锁 `credit_reservations`，旧服务照常运行。

**回滚（本步）**：一般**不需要**回退库结构，因为旧程序兼容 0053。确实要回退时：

```sh
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c "SELECT count(*) FROM credit_reservations WHERE job_id IS NULL OR owner_type IS NOT NULL"  # 必须为 0
docker compose $(cat $R/api.compose-args) -f $R/api.override.json run --rm --no-deps -T \
  api python -m alembic -c /app/alembic.ini downgrade 20261116_0052
```

downgrade 自带保护：存在视频冻结记录时会直接报错退出。

### 3.6 生成覆盖文件并滚动更新（03:10–03:50）

每个角色的覆盖文件只写镜像、命令、需要改的 env 和资源；其他配置全部沿用线上 `config_files` 列表（沿用 §1.2 C 的做法，并保留 hk-02 覆盖）：

```sh
mk_args() { local role=$1 files envf; files=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' $P-$role-1)
  envf=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.environment_file"}}' $P-$role-1)
  { echo -p; echo $P; [ -n "$envf" ] && { echo --env-file; echo "$envf"; }; IFS=, read -ra f <<<"$files"; for x in "${f[@]}"; do echo -f; echo "$x"; done; } > $R/$role.compose-args; }
for role in api detail-api detail-worker replica-api replica-worker worker dispatcher frontend; do mk_args $role; done
img() { docker image inspect -f '{{.Id}}' "$1"; }
```

覆盖文件内容（用 python 写成 JSON，0600），每个角色都同时生成一份**只含旧镜像 ID** 的 `$role.rollback.json`：

| 角色 | image | 其他改动 |
|---|---|---|
| api | `img polaris-jgshai:api-image-first-…` | `command` = 线上 `Config.Cmd`，`--forwarded-allow-ips=*` 换成 `127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`，末尾加 `--workers 3`；env 加池 8/8/10、`POLARIS_ECOMMERCE_STARTUP_RECOVERY_ENABLED=false`、限流 4 项、`POLARIS_USER_ACTIVE_IMAGE_JOB_LIMIT=3`；`mem_limit: 1536m`、`cpus: 1.5`、`pids_limit: 512` |
| ecommerce-api（新） | 同 api 新镜像 | 新文件 `$R/ecommerce-api.compose.json`：由 api 的 `docker compose $(cat api.compose-args) config --format json` 复制 `services.api` 得到，改名为 `ecommerce-api`；command 不加 `--workers`；env 同 api，但**不要** `ECOMMERCE_STARTUP_RECOVERY=false`，池用 3+2；`mem_limit: 768m`、`cpus: 0.75`；挂载 `polaris-production_ecommerce_profiles:/app/.data/ecommerce-session`（卷不存在时先 `docker volume create`）；网络沿用 api 的（external），不要复制 api 的网络别名 |
| detail-api | 新镜像 | 限流 4 项 + 图片上限 3；保留 hk-02 池 8/8/20 |
| replica-api | 新镜像 | 限流 4 项 + 图片上限 3 |
| worker | 新镜像 | 池 2/1；`mem_limit: 1536m`、`cpus: 1.0` |
| detail-worker / replica-worker | 新镜像 | 无 |
| dispatcher | 新镜像 | 保留 `POLARIS_RETENTION_ENABLED=false` |
| frontend | `img polaris-editing-frontend:image-first-…` | 无 |

全部先 `docker compose $(cat $R/$role.compose-args) -f $R/$role.override.json config --quiet`，必须通过。

**顺序**（每步都等到 `healthy` 再走下一步；切换函数）：

```sh
roll() { local role=$1; COMPOSE_IGNORE_ORPHANS=true docker compose $(cat $R/$role.compose-args) -f $R/$role.override.json \
  up -d --no-deps --no-build --pull never $role
  for i in $(seq 1 60); do s=$(docker inspect -f '{{.State.Health.Status}}' $P-$role-1); [ "$s" = healthy ] && return 0; sleep 3; done; return 1; }
back() { local role=$1; COMPOSE_IGNORE_ORPHANS=true docker compose $(cat $R/$role.compose-args) -f $R/$role.rollback.json \
  up -d --no-deps --no-build --pull never $role; }
```

1. **ecommerce-api**（新增，没有流量）：
   `docker compose -p $P -f $R/ecommerce-api.compose.json up -d --no-deps --no-build --pull never ecommerce-api`，等待 healthy；
   再从 caddy 容器确认名字能解析：`docker exec $P-caddy-1 wget -qO- http://ecommerce-api:8000/health/ready`。
2. **Caddy 加载新路由**（§3.7）。
3. **api**：`roll api`，约 30 秒接口不可用。
   验证：`docker exec $P-api-1 ps -ef | grep -c 'uvicorn'` ≥ 4（主进程 + 3 个 worker）；`curl -fsS https://www.jgshai.cn/health/ready`。
4. **detail-api**、**replica-api**：`roll detail-api; roll replica-api`。
5. **worker 系列**：每个角色先确认空闲（`celery inspect active/reserved` 都为空），然后 `roll worker; roll detail-worker; roll replica-worker`。
   有任务在跑就等它结束。旧 worker 的 `stop_grace_period` 是 90 秒，图片任务可能长达 40 分钟，**不要**强行停。
6. **dispatcher**：`roll dispatcher`，然后检查 outbox pending 是否回落到 0。
7. **frontend**：`roll frontend`，约 20–30 秒页面不可用。
8. 资源：supertokens `docker update --cpus 1.0`（如果 §3.4 还没做）。
9. 核对视频服务、redis、minio、supertokens 的容器 ID 与 `$R/baseline.txt` 一致（只有 postgres 和上面这些角色发生了变化）。

**回滚（本步）**：按相反顺序对出问题的角色执行 `back <role>`，使用 `polaris/rollback-<role>:20261126` 对应的镜像 ID。ecommerce-api 回滚：先恢复 Caddyfile（§3.7），再 `docker compose -p $P -f $R/ecommerce-api.compose.json rm -sf ecommerce-api`。库结构保持在 0053（兼容旧程序）。

### 3.7 Caddy：先校验，再 reload（03:15，夹在 §3.6 第 1 步和第 3 步之间）

线上 Caddyfile 是整合网关（www / jgshai.cn / api.jgshai.cn / pay.jgshai.cn / 视频路由），**不要**用仓库里的 `deploy/Caddyfile.production` 整份替换，只做两处最小改动：

1. 在 `www.jgshai.cn` 站点内、`handle @api` 之前插入：

   ```caddy
   @ecommerce path /api/ecommerce /api/ecommerce/*
   handle @ecommerce {
   	reverse_proxy ecommerce-api:8000 {
   		header_up X-Forwarded-For {remote_host}
   	}
   }
   ```

2. 把转发到 `api:8000`、`detail-api:8000`、`replica-api:8000` 的每个 `reverse_proxy` 都改成带 `header_up X-Forwarded-For {remote_host}` 的块形式。视频和 `api.jgshai.cn`、`pay.jgshai.cn` 的路由不动。

```sh
cp $R/Caddyfile.before $R/Caddyfile.candidate && $EDITOR $R/Caddyfile.candidate
diff -u $R/Caddyfile.before $R/Caddyfile.candidate > $R/Caddyfile.diff   # 存档审阅
# 校验：在线上 Caddy 容器里（同镜像、同 env）
docker cp $R/Caddyfile.candidate $P-caddy-1:/tmp/Caddyfile.candidate
docker exec $P-caddy-1 caddy validate --config /tmp/Caddyfile.candidate --adapter caddyfile
# 写回宿主机上被挂载的那个文件：必须原地覆盖，保持 inode 不变，单文件 bind mount 才能看到新内容
host=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' $P-caddy-1)
cp -p "$host" $R/Caddyfile.host-before
cat $R/Caddyfile.candidate > "$host"
docker exec $P-caddy-1 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec $P-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

- `caddy reload` 依赖管理接口（localhost:2019）。**仓库模板里写的是 `admin off`**；如果线上也是这样（§3.1 已检查），reload 会失败，而 Caddy 2 不支持用信号重载。这时只能 `docker restart $P-caddy-1`（证书保存在 caddy_data 卷里，约 3–5 秒，三个域名同时短暂中断）。这一项需要经营者事先同意，否则把 Caddy 改动推迟，api 先保持 1 个 worker（见 §4 降级方案）。
- 验证：`curl -sI https://www.jgshai.cn/api/ecommerce/… `，并看 ecommerce-api 日志里出现请求；`api.jgshai.cn`、`pay.jgshai.cn` 首页或健康地址仍然正常响应。

**回滚（本步）**：`cat $R/Caddyfile.host-before > "$host"`，再 `caddy validate` 和 `caddy reload`（或 restart）。

### 3.8 冒烟测试（03:50）

```sh
for p in / /help /inspiration /legal/privacy /legal/terms /auth/login /health/live /health/ready /robots.txt /sitemap.xml; do
  printf '%s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 https://www.jgshai.cn$p)"; done   # 全部 200
curl -s -o /dev/null -w '%{http_code}\n' https://www.jgshai.cn/api/v1/video-studio/access   # 401（匿名）
curl -s -o /dev/null -w '%{http_code}\n' https://jgshai.cn/                                 # 301/308 → www
# 其他域名未受影响
curl -s -o /dev/null -w '%{http_code}\n' https://api.jgshai.cn/ ; curl -s -o /dev/null -w '%{http_code}\n' https://pay.jgshai.cn/
docker exec $P-postgres-1 psql -U polaris -d polaris -At -c 'SELECT count(*) FROM pg_stat_activity'   # 远低于 200
```

浏览器（无痕）里逐项检查：

1. 未登录打开 `/`：熔光暗色首页，有价格和 FAQ，顶栏**没有**「视频创作」。
2. 用普通测试账号登录：顶栏和手机菜单都没有「视频创作」；直接打开 `/video-studio` 显示「页面暂不可用」。
3. 用灰度账号登录：能看到「视频创作」入口；已知 3 个新接口返回 404（§2.5），不算失败。
4. 用手机竖拍、带 EXIF 方向的 JPEG 上传素材，应该成功（验证 EXIF 修复没有丢）。
5. 用测试账号提交 1 个主图任务：成功交付，积分结算一次，`outbox_events` 回到 0。另外连续提交第 4 个任务时，应收到「运行中任务已达上限」。
6. 账户页、充值页能打开（不实际付款）；支付回调地址 `POST /api/v1/payments/epay/notify` 不带签名时应返回 4xx，不能是 502。
7. 观察 30 分钟：`docker stats`、各容器 `RestartCount` 为 0、api 日志里 5xx 和 429 的数量、swap 用量。

### 3.9 回滚总表

| 步骤 | 触发条件 | 回滚动作 | 需要多久 |
|---|---|---|---|
| 3.2 备份 | 失败 | 中止发布（线上未改） | – |
| 3.3 构建 | 失败 | 中止发布 | – |
| 3.4 PostgreSQL | 起不来或参数报错 | 原 compose 文件列表（去掉覆盖文件）再 `up -d --no-deps postgres` | 约 1 分钟 |
| 3.5 迁移 | 报错 | alembic 事务会自动回滚；核对 `alembic_version` 仍为 0052。失败后在中途状态下手工 `downgrade` 0052 | 秒级 |
| 3.6 各角色 | 5 分钟内没有 healthy、反复重启、冒烟失败 | `back <role>`（`polaris/rollback-<role>:20261126` 的镜像 ID）；库结构保持 0053 | 每个角色 30–60 秒 |
| 3.6 ecommerce-api | 不健康 | 先恢复 Caddyfile，再删除容器；api 保持 1 个 worker、去掉 `ECOMMERCE_STARTUP_RECOVERY=false` | 1 分钟 |
| 3.7 Caddy | validate 失败 | 不写回宿主机文件 | 0 |
| 3.7 Caddy | reload 后异常 | 原样写回 `Caddyfile.host-before`，再 reload | 秒级 |
| 数据灾难 | 数据错乱、丢失 | 见 §3.10 | 30–60 分钟 |

### 3.10 数据恢复（只在数据灾难时使用）

不要对线上 `polaris` 库直接执行 `pg_restore --clean`（deploy/README 明确禁止）。

1. 停掉所有写入方：`docker stop` api、ecommerce-api、detail-api、replica-api、video-api、所有 worker、dispatcher、editing-*、supertokens。
2. 恢复到新库：
   `docker exec $P-postgres-1 createdb -U polaris polaris_restore`，然后
   `docker exec -i $P-postgres-1 pg_restore -U polaris -d polaris_restore --no-owner --exit-on-error < $D`。
3. 核对 `polaris_restore` 的逐表行数与 `$D.counts` 一致，`alembic_version` 为 0052。
4. 切换：`ALTER DATABASE polaris RENAME TO polaris_broken_20261126; ALTER DATABASE polaris_restore RENAME TO polaris;`（连接 `postgres` 库执行，此时不能有其他连接）。
5. 对象存储：把 `$B/minio/<bucket>` 用 `mc mirror` 反向镜像回 MinIO。备份之后新写入的对象会保留，不会造成破坏。
6. 所有角色按 `$role.rollback.json` 用旧镜像启动；Caddyfile 恢复为 `Caddyfile.host-before`。
7. 保留 `polaris_broken_20261126` 和新数据卷，等经营者批准后再清理。

---

## 4. 风险清单与放行条件

### 4.1 风险

| # | 风险 | 等级 | 缓解措施 |
|---|---|---|---|
| R1 | EXIF 修复 `403cd42` 不在发布分支，发布后手机照片上传会再次报错 | **阻断** | §0.1 先合入；§3.3 用 grep 检查；§3.8 第 4 项实测 |
| R2 | 线上镜像可能有未入库的手工补丁（dispatcher 已确认是 outbox.py 补丁，HEAD 包含它） | 高 | §3.0 第 2 步逐文件比对 sha256 |
| R3 | 内存超配：上限合计约 16 GB，物理内存 15.6 GB，取证时 swap 已用 3.6/4 GB；同机有开发栈、预发、压测和多个开发代理 | 高 | 窗口内停开发栈和代理；swap 持续 > 1 GB 就回滚 api 的 worker 数或降低并发 |
| R4 | 线上 compose 是从 inspect 生成的，新的 env、资源、命令要逐项手写，容易漏掉（例如没加 `ECOMMERCE_STARTUP_RECOVERY=false`，会导致 4 个进程都做电商恢复） | 高 | §2.7 表格；§3.6 每个角色都跑 `config --format json` 并逐项核对 |
| R5 | 代码默认值变化：域名默认改为 jgshai；全局图片并发默认 40；限流和单账号上限默认关闭 | 中 | §3.1 检查变量名；缺失的显式写入线上现用值 |
| R6 | Caddy `admin off` 时无法 reload，只能重启，会影响 api.jgshai.cn 和 pay.jgshai.cn | 中 | §3.1 预检；经营者事先同意；或推迟 Caddy 改动并让 api 保持单 worker |
| R7 | PostgreSQL 重启导致约 1 分钟不可用，进行中的任务可能失败 | 中 | 先等 worker 空闲、停 dispatcher；选低峰时段 |
| R8 | 限流误伤：如果前端 SSR 或内部服务通过可信网段访问 API 且不带 XFF，会共享同一个 IP 计数 | 低 | 阈值很宽（1800 次/分钟）；观察 429 日志，异常就设 `POLARIS_RATE_LIMIT_ENABLED=false` 并重启该角色 |
| R9 | 视频灰度账号：新前端对接旧 video-api，3 个新接口 404 | 低 | 已告知；视频服务以后单独升级 |
| R10 | 前端构建意外带上 `POLARIS_BASE_PATH` 或开发开关 | 中 | 构建时 `test -z`；冒烟检查资源路径 |
| R11 | 备份和线上在同一块盘，本机磁盘故障时无法恢复 | 中 | 尽量拷到异机 |
| R12 | api 开多进程后 `/health/metrics` 只反映单个 worker，会员维护循环跑 3 份（有行锁保证正确，数据库负载变成 3 倍） | 低 | 已在容量文档记录；观察数据库 CPU |
| R13 | 发布当天还有修复合入，最终版本与本文取证的 7a44f6f 不同 | 中 | §0.3 重跑差异检查；新增迁移就重新评估 |

### 4.2 放行（Go）条件，每一项都满足才开始

- [ ] 经营者批准本「发布说明」，并同意窗口、中断时长和冒烟测试的积分消耗。
- [ ] `RELEASE_SHA` 已冻结、CI 全绿、包含 `403cd42`。
- [ ] `alembic_version` = `20261116_0052`；待执行迁移只有 0053。
- [ ] 线上镜像 sha256 比对没有未解释的差异。
- [ ] 剩余磁盘 ≥ max(20 G, 2×镜像体积 + 备份体积 + 10 G)，inode 剩余 ≥ 10%。
- [ ] 备份完成，sha256、`pg_restore -l`、行数文件都通过。
- [ ] 全部覆盖文件 `config --quiet` 通过；Caddyfile 候选 `validate` 通过；Caddy admin 状态已知，并有对应方案。
- [ ] swap < 1 GB；同机开发栈、压测和代理任务已停。
- [ ] `POLARIS_WORKSPACE_CREDIT_ENFORCEMENT_ENABLED=true` 计数 = 1。

### 4.3 中止或回滚（No-go）条件

- 迁移失败，或 `alembic_version` 不等于 0053。
- 任何角色 5 分钟内没有 healthy，或 `RestartCount` 在增长。
- 冒烟测试任何一项失败（尤其是 EXIF 上传、主图任务、登录、支付回调路由、api 和 pay 域名）。
- 5xx 比例明显高于发布前，或出现大量 429。
- swap 持续 > 1.5 GB，或有容器因 OOM 被杀。
- 05:00 之前做不完：已完成的部分如果健康就保留（库结构兼容），没做的步骤留到下个窗口；拿不准就整体回滚。

### 4.4 降级方案

如果 ecommerce-api 或 Caddy 改动不能按计划完成，可以只发镜像：api 保持 1 个 worker（不加 `--workers 3`，也不加 `ECOMMERCE_STARTUP_RECOVERY=false`），不新增 ecommerce-api，不改 Caddy。PostgreSQL 参数照常调整。这样风险最小，失去的只是 api 的多进程扩容。

---

## 5. 附：取证命令（只读）

```sh
ssh polaris-review report
ssh polaris-admin 'ls -la /opt/polaris /opt/polaris/releases'
ssh polaris-admin 'cat /opt/polaris/releases/bihuo-bgm-20261119/{activate.sh,baseline.json,build-calibrated.sh}'
ssh polaris-admin 'cat /opt/polaris/releases/commerce-cdn-fe636e289932/release_commerce_sources.py'
ssh polaris-admin 'cat /opt/polaris/cutover-fb6f581.sh'
ssh polaris-admin 'cat /opt/polaris/releases/dispatcher-queue-ff69077207ef/Dockerfile'
git merge-base --is-ancestor 403cd42ce95a HEAD || echo "403cd42 不在发布分支"
git diff bd63c1db 403cd42ce95a -- backend/app/storage.py backend/app/routes_v1.py
for r in 403cd42ce95a 4f6f7e89034e cc7755043589 HEAD; do git ls-tree --name-only $r backend/migrations/versions/ | sort | tail -1; done
```

## 6. 附：视频入口隐藏核对（release HEAD，只读）

- 唯一入口在 `components/top-navigation.tsx`：桌面顶栏（第 165 行）和手机菜单（第 189 行）都只在 `useVideoStudioAccess()` 为真时渲染「视频创作」。
- `features/video-studio/access.ts`：`GET /api/v1/video-studio/access` 返回 401 时状态为 `revoked`，返回 403 或 404 时为 `denied`，其他错误抛异常（状态为 `error`），初始状态为 `checking`。只有返回 `allowed:true` 且带非空 `user_id` 时才算 `allowed`。授权状态不写入 localStorage 或 query 缓存，换账号和退出登录时会撤销。
- 首页 `app/page.tsx` → `components/tool-directory.tsx`（熔光落地页各区块 + `FEATURE_REGISTRY`），以及 `lib/tool-registry.ts`、`components/home-*`、`components/ember-landing.tsx`：都**没有**视频入口或视频文案。
- 直接访问 `/video-studio`：`VideoStudioGate` 在 denied 或 revoked 时只显示「页面暂不可用 / 返回首页」。
- 后端 `backend/app/video_studio_access.py` 对非灰度邮箱返回 404。线上匿名访问返回 401（已实测）。
- 结论：**没有权限的用户看不到入口**。唯一的外露是 `robots.txt` 的 Disallow 列表里有 `/video-studio`（`lib/site-seo.ts`），只暴露路径名，不暴露功能。
