# Polaris Backend

Phase 1 第一批后端基础。当前目标是稳定 API 契约和任务生命周期，不接图片生成服务。

## 已实现

- FastAPI 应用与统一错误结构。
- PostgreSQL 持久化与 Alembic 数据库迁移。
- PNG、JPEG、WebP 上传校验与 S3 兼容对象存储。
- `local_edit`、`detail_pack` 统一任务模型。
- 任务创建、列表、详情、取消与重试。
- Redis + Celery 异步队列。
- 模拟排队、规划、处理中和完成状态（不调用图片 API）。
- OpenAPI 文档、CORS 和后端测试。

## 完整环境

从仓库根目录启动：

```bash
docker compose up -d --build
```

访问：

- API：`http://localhost:8000`
- OpenAPI：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health`
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

## 当前限制

- 模拟执行器只生成任务状态与占位输出元数据，不生成图片。
- 前端尚未整体切换到这些接口。
- 没有真实账号、支付、额度扣减或付费 API。
- 尚未配置生产域名、HTTPS、监控、备份和生产密钥。
