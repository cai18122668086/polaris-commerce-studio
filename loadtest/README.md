# 压测（staging）

只对本机 `127.0.0.1` 上的隔离 staging 栈施压。不连正式站、不调用任何付费上游；staging 里没有任何供应商密钥。

## 组成

| 文件 | 作用 |
| --- | --- |
| `guard.sh` | 安全阀。每 5 秒看一次主机与正式容器，任一条件成立就杀掉压测进程组：主机可用内存 < 2.5 GB；1 分钟负载 > 6；任一正式容器 CPU 连续 3 次 > 其上限 85%；任一正式容器重启/消失。日志 `~/work/loadtest/guard.log`。正式容器 = 名字不以 `polaris-videodev` / `polaris-loadstg` 开头的容器。只读 `docker stats --no-stream` 和 `docker inspect` 元数据。自测记录见 `guard-selftest.log`。 |
| `staging/compose.yaml` | staging 栈（项目名 `polaris-loadstg`）：postgres / redis / minio / supertokens / migrate / api / video-api / worker / detail-worker / replica-worker / dispatcher，与 `deploy/compose.production.yml` 同拓扑同队列，资源硬封顶合计 2.9 CPU、约 4.1 GiB；独立网络与数据卷，端口只绑 127.0.0.1（api 3410、video-api 3411、postgres 3415、supertokens 3417、minio 3419）。后端代码只读挂载被测分支的 `backend/`。 |
| `staging/stg-app.env` | 与正式站相同的后端参数（连接池 3+2、超时 5 s、`AUTO_PROCESS_JOBS=false`、celery 分发、worker 并发 6/6/2、prefetch 1……），去掉 SMTP、出口代理和全部密钥。 |
| `staging/stg_boot.py` + `staging/sitecustomize.py` | 进程内假上游（sitecustomize 让 `uvicorn --workers` 派生的子进程也打上补丁）：规划 5–10 s，出图 20–40 s（`FakeXingheGateway` / `FakeProvider`），复刻规划走离线假网关，视频供应商走 `httpx.MockTransport`（提交 1–3 s，60 s 后返回失败，没有真实媒体）。并修正原版假网关两个会让详情页必然失败的问题：provider_request_id 跨任务重复（撞唯一约束）、详情页要求 PNG 而假图是 JPEG。另外把视频工作台的单账号白名单放开给 `@loadtest.invalid` 测试账号（正式站只开放给一个预览账号）。 |
| `staging/stg.sh` | `stg.sh up baseline|after|<代码目录>`、`stop`、`down`、`status`、`logs <服务>`。`after` 会叠加 `compose.after.yaml`（按 perf/concurrency-50 的正式 compose 按比例缩小）和 `stg-app-after.env`。 |
| `setup_users.py` | 在 staging SuperTokens 上建测试账号（注册→用 Core API 标记邮箱已验证→登录→同意处理说明），输出 `users.json`。 |
| `polaris.js` | k6 场景。每个 VU 登录一次后循环：3% 注册新账号；40% 浏览（runtime、公告、工作区、作品统计、任务列表、素材列表、灵感案例、任务详情、积分）；20% 上传图片（约 0.77 MB PNG）+ 提交主图任务 + 轮询；10% 详情页（提交→规划→确认→轮询）；10% 复刻（上传两张→分析→确认→轮询）；10% 视频（权限、项目、形象、音色、价格→保存项目→提交口播任务→轮询）；7% 积分（余额、套餐、会员、流水、报价、下单意向）。 |
| `run.sh` | 跑一轮：与其他线程共用主机——开跑前 `touch ~/work/loadtest/RUNNING`（`~/work/heavy.sh` 见到它就不启动新的重任务），k6 一结束就删掉，两轮之间至少空 5 分钟；再等主机安静（负载 < 4、可用内存 > 4.5 GB），再在 `guard.sh` 保护下启动 k6，同时每 5 秒采集 staging 容器 CPU/内存和 celery 队列长度，结束后收集日志、OOM/重启信息并调用 `analyze.py`。 |
| `series.sh` | 依次跑 10 → 25 → 50 VU 三个阶段（各 30 s 爬坡 + 5 min 稳态）；某阶段被 guard 叫停就等主机安静后重跑，直到截止时间。 |
| `compare.py` | 把多轮 `analysis.json` 拼成对比表（报告里的表就是它生成的）。 |
| `analyze.py` | 汇总：每个接口 p50/p95/p99、意外状态比例、5xx、k6 超时/中断（status 0），任务端到端耗时与结果，队列峰值，容器峰值，日志信号（连接池超时、Traceback、IntegrityError、worker 被 SIGKILL 等）。 |

## 运行

```bash
# 1. staging
mkdir -p ~/work/loadstg/shim && cp staging/compose.yaml staging/stg-app.env staging/stg.sh ~/work/loadstg/
cp staging/compose.after.yaml staging/stg-app-after.env ~/work/loadstg/
cp staging/stg_boot.py staging/sitecustomize.py ~/work/loadstg/shim/
cp staging/stg.env.example ~/work/loadstg/stg.env && chmod 600 ~/work/loadstg/stg.env   # 填随机值
git worktree add --detach ~/work/loadstg/code-baseline <基线提交>
git worktree add --detach ~/work/loadstg/code-after origin/perf/concurrency-50
~/work/loadstg/stg.sh up baseline
# 2. 账号、图片、k6
python3 -I setup_users.py --count 60 --out ~/work/loadtest/users.json
#    ~/work/loadtest/data/product.png、reference.png（≤5 MB）；k6 v1.0.0 静态二进制放 ~/work/loadtest/bin/k6
cp guard.sh ~/work/loadtest/guard.sh
# 3. 压测
./series.sh baseline          # 或 ./run.sh <label> p10|p25|p50|full|smoke
~/work/loadstg/stg.sh up after && ./series.sh after
# 4. 收尾
~/work/loadstg/stg.sh stop    # 保留数据卷；down 会删容器（数据卷仍保留，需 docker volume rm 才删）
```

产物在 `~/work/loadtest/runs/<时间>-<label>-<阶段>/`：`k6.csv.gz`、`summary.json`、`stats.tsv`、`queues.tsv`、`logs/`、`containers.txt`、`guard.log`、`report.txt`、`analysis.json`。

## 局限

- 不覆盖前端（Next/vinext）和 Caddy；请求直接打 API 容器（主站接口打 api，视频接口打 video-api）。正式站另有 detail-api / replica-api 两个 API 容器，staging 把它们并进 api。
- 假上游只模拟延迟，不模拟供应商限流、超时、413 等错误；生成结果是占位图。
- 视频生成没有真实媒体，任务最终状态是失败/未知，只能衡量提交与轮询接口、后台任务对 video-api 的占用。剪辑（editing-worker，需要 ASR 模型和素材库）未覆盖。
- 积分充值：正式站当前没开积分试点，下单接口预期返回 403 `CREDIT_PILOT_REQUIRED`，不会产生支付。
