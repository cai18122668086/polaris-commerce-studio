# Phase 1 API 契约

本契约服务于局部修改和商品详情图两种任务。Phase 1 第一批只模拟任务执行，不调用图片 API。

## 资产

### `POST /api/assets`

使用 `multipart/form-data` 上传单张图片：

- `workspace_id`：工作区标识。
- `origin`：`upload`、`local_edit` 或 `detail_pack`。
- `file`：PNG、JPEG 或 WebP，默认不超过 20MB、4000 万像素。

文件写入 S3 兼容对象存储（本地 Compose 使用 MinIO），数据库只保存元数据和
`storage_key`。单元测试仍可使用临时本地存储。

### `GET /api/assets`

按 `workspace_id` 查询，可选 `origin`、`limit` 和 `offset`。

### `GET /api/assets/{asset_id}`

返回单个素材元数据。

## 任务

任务类型：

- `local_edit`
- `detail_pack`

任务状态：

- `draft`
- `queued`
- `planning`
- `processing`
- `partial`
- `completed`
- `failed`
- `cancelled`

### `POST /api/jobs`

示例：

```json
{
  "type": "local_edit",
  "workspace_id": "workspace-demo",
  "input_asset_ids": ["asset_xxx"],
  "configuration": {
    "quality": "balanced",
    "selection_coverage": 0.124
  },
  "prompt_version": "phase1-mock",
  "strategy_version": "phase1-mock",
  "estimated_cost": 2
}
```

局部修改必须有且只有一张输入素材；商品详情图支持同一商品的 1–8 张角度图。

### `GET /api/jobs`

按 `workspace_id` 查询，可选 `type`、`status`、`limit` 和 `offset`。

### `GET /api/jobs/{job_id}`

返回任务输入、配置、状态、进度、输出、错误、usage、成本和时间信息。

### `POST /api/jobs/{job_id}/cancel`

取消非终态任务。已完成、失败或已取消任务返回 `JOB_NOT_CANCELLABLE`。

### `POST /api/jobs/{job_id}/retry`

只有失败、部分成功或已取消任务可以重试；新任务保留 `retry_of_job_id` 和 `parent_job_id`。

## 错误结构

```json
{
  "error": {
    "code": "INPUT_ASSET_NOT_FOUND",
    "message": "部分输入素材不存在或不属于当前工作区。",
    "details": {
      "asset_ids": ["asset_missing"]
    }
  }
}
```

## 后续适配点

- 前端保留现有设计与数据结构，逐页切换到这些 HTTP 接口。
- 将模拟执行器替换为局部修改和商品详情图的真实服务层。
- 为对象下载补充短期签名 URL。
- 接入账号体系后，以服务端身份替换当前显式 `workspace_id`。
