# Copy this file to D:\Polaris\local-worker\worker.env.ps1 and fill in the
# values returned by the Worker enrollment flow. This file is intentionally not
# committed with real credentials.

$env:POLARIS_WORKER_API_URL = "https://your-control-plane.example"
$env:POLARIS_WORKER_SESSION_TOKEN = "<short-lived-token>"
$env:POLARIS_WORKER_ID = "wrk_xxx"
$env:POLARIS_WORKER_PROFILE_ROOT = "D:\Polaris\ecommerce-profiles"
$env:POLARIS_WORKER_CAPABILITIES = "browser.taobao,browser.tmall"
$env:PLAYWRIGHT_BROWSERS_PATH = "D:\Tools\ms-playwright"

# Optional tuning. Keep the defaults unless the control plane requires a
# different polling cadence.
# $env:POLARIS_WORKER_HEARTBEAT_INTERVAL = "20"
# $env:POLARIS_WORKER_POLL_INTERVAL = "2"
# $env:POLARIS_WORKER_LEASE_INTERVAL = "30"
