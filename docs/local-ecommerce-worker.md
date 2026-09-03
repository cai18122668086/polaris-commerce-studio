# 本机电商执行代理

本机代理主动通过 HTTPS 连接 Polaris 控制面，在本机 profile 中运行商品浏览器抓取。Cookie、localStorage、浏览器 profile 和 CDP 地址不会上传服务器。

## 启动前配置

在本机 shell 中设置以下环境变量。`POLARIS_WORKER_SESSION_TOKEN` 使用后台注册接口返回的短期 session token，不要写入代码、日志或命令历史。

```powershell
$env:POLARIS_WORKER_API_URL = "https://your-control-plane.example"
$env:POLARIS_WORKER_SESSION_TOKEN = "<short-lived-token>"
$env:POLARIS_WORKER_ID = "wrk_xxx"
$env:POLARIS_WORKER_PROFILE_ROOT = "D:\Polaris\ecommerce-profiles"
$env:POLARIS_WORKER_CAPABILITIES = "browser.taobao,browser.tmall"
```

先执行配置自检：

```powershell
Set-Location backend
python -m app.ecommerce_local_worker --check-config
```

自检通过后启动：

```powershell
python -m app.ecommerce_local_worker
```

代理会周期发送心跳、领取任务并续租；按 `Ctrl+C` 或系统终止信号退出时，会停止领取并回报离线状态。首次灰度建议只配置一个淘宝/天猫能力和一个账号 profile。

## 安全边界

- 远程控制面地址必须使用 HTTPS；仅允许 `localhost`/`127.0.0.1` 使用 HTTP 做本地测试。
- 不要把 profile 根目录放入仓库或同步盘。
- 不要在 `request_payload`、任务结果或自定义 adapter 中放入 Cookie、密码、验证码、localStorage、profile 路径或 CDP 信息。
- 登录、风控、验证码和浏览器崩溃会作为安全任务错误回报，不能伪装成成功结果。
