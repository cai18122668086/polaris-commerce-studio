# Polaris Backend

Phase 1.1 生产数据与 API v1 基础。当前执行器仍不接图片生成服务。

## 已实现

- FastAPI 应用与统一错误结构。
- PostgreSQL 持久化与 Alembic 数据库迁移。
- PNG、JPEG、WebP 上传校验与 S3 兼容对象存储。
- 用户、工作区成员和服务端租户边界。
- 关系化 job、job_item、job_asset、attempt、plan 和 usage 模型。
- API v1、幂等写入、事务 outbox、额度预留与精确成本。
- 私有对象存储与短期访问 URL。
- Redis + Celery Worker 和独立 outbox dispatcher。
- 详情图计划确认门槛与零付费模拟执行器。

## 完整环境

从仓库根目录启动：

```bash
docker compose up -d --build
```

访问：

- API：`http://localhost:8000`
- OpenAPI：`http://localhost:8000/docs`
- 存活检查：`http://localhost:8000/health/live`
- 就绪检查：`http://localhost:8000/health/ready`
- MinIO 控制台：`http://localhost:9001`

开发默认密码只允许用于本机 Compose；对外环境必须替换。

## 快速单元测试

单元测试使用 SQLite 和本地临时存储，不依赖 Docker：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m mypy --config-file backend\pyproject.toml backend\app
.\.venv\Scripts\python.exe -m pytest backend
```

开发身份默认工作区为 `ws_development`。该模式只能用于本地开发；
`POLARIS_ENVIRONMENT=production` 时会拒绝 development 身份和开发密钥。

## 当前限制

- 模拟执行器只生成任务状态与占位输出元数据，不生成图片。
- 前端尚未整体切换到这些接口。
- 没有真实登录供应商、支付或付费 API。
- 尚未配置生产域名、HTTPS、监控、备份和生产密钥。
- 前端页面尚未从 mock 数据切换到 API v1。
