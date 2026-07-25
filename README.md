# Polaris Commerce Studio

面向电商内容生产的 AI 图片工作台。当前仓库已完成《项目规划-新窗口交接.md》
定义的 Phase 0 前端，并开始建设 Phase 1 的统一后端与任务基础。

## 当前范围

- 首页与工具入口
- 个人控制台
- 局部修改工作台
- 商品详情包工作台
- 任务中心
- 素材库
- 帮助中心
- 全局任务抽屉与状态展示

Phase 1 第一批包含 FastAPI、PostgreSQL、Redis、Celery、S3 兼容对象存储、
图片上传校验、数据库迁移和统一任务模型。任务执行器当前只模拟完整状态流，
不会调用付费图片 API；也不包含真实登录、支付或部署。

## 本地开发

需要 Node.js `>=22.13.0`。

```bash
npm install
npm run dev
```

默认访问 `http://localhost:3000`。

## 完整后端环境（推荐）

需要 Docker Desktop 或可用的 Docker Engine / Compose。

```bash
docker compose up -d --build
```

- API：`http://localhost:8000`
- OpenAPI：`http://localhost:8000/docs`
- MinIO 控制台：`http://localhost:9001`

Compose 会启动 PostgreSQL 18、Redis 8、MinIO、API 和 Celery Worker。
配置中的密码仅供本机开发，测试或生产环境必须通过环境变量或密钥服务替换。

## 工程检查

```bash
npm run lint
npm run typecheck
npm run build

python -m venv .venv
.venv/Scripts/python -m pip install -e "backend[dev]"
.venv/Scripts/python -m ruff check backend
.venv/Scripts/python -m mypy --config-file backend/pyproject.toml backend/app
.venv/Scripts/python -m pytest backend
```

## 技术栈

- React 19
- Next.js App Router API
- vinext / Vite
- TypeScript
- Lucide Icons
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL 18
- Redis 8 / Celery 5
- S3 兼容对象存储（本地使用 MinIO）

前端目前仍以 `lib/mock-data.ts` 和页面内状态为主；后续批次会逐页切换到真实接口。
