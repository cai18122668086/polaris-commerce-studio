param(
    [string]$EnvFile = "D:\Polaris\local-worker\worker.env.ps1",
    [string]$WorkerRoot = "D:\Polaris\local-worker",
    [int]$RestartDelaySeconds = 5,
    [int]$MaxRestartDelaySeconds = 300
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"
$logRoot = Join-Path $WorkerRoot "logs"

New-Item -ItemType Directory -Force -Path $WorkerRoot, $logRoot | Out-Null

function Write-SupervisorLog([string]$Message) {
    $logFile = Join-Path $logRoot ("supervisor-{0:yyyyMMdd}.log" -f (Get-Date))
    Add-Content -LiteralPath $logFile -Value ("{0:O} {1}" -f (Get-Date), $Message)
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-SupervisorLog "worker python runtime missing: $python"
    exit 2
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-SupervisorLog "worker env file missing: $EnvFile"
    exit 2
}

. $EnvFile
$required = @(
    "POLARIS_WORKER_API_URL",
    "POLARIS_WORKER_ID",
    "POLARIS_WORKER_PROFILE_ROOT",
    "POLARIS_WORKER_CAPABILITIES"
)
$missing = @(
    $required | Where-Object {
        [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_))
    }
)
if ($missing.Count -gt 0) {
    Write-SupervisorLog ("worker env missing required keys: " + ($missing -join ","))
    exit 2
}
$tokenFile = [Environment]::GetEnvironmentVariable("POLARIS_WORKER_SESSION_TOKEN_FILE")
$token = [Environment]::GetEnvironmentVariable("POLARIS_WORKER_SESSION_TOKEN")
if ([string]::IsNullOrWhiteSpace($token) -and
    ([string]::IsNullOrWhiteSpace($tokenFile) -or -not (Test-Path -LiteralPath $tokenFile))) {
    Write-SupervisorLog "worker session token and token file are both missing"
    exit 2
}

while ($true) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdout = Join-Path $logRoot "worker-$stamp.out.log"
    $stderr = Join-Path $logRoot "worker-$stamp.err.log"
    try {
        Write-SupervisorLog "starting local worker"
        $process = Start-Process `
            -FilePath $python `
            -ArgumentList @("-m", "app.ecommerce_local_worker") `
            -WorkingDirectory $backendRoot `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -WindowStyle Hidden `
            -PassThru
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        Write-SupervisorLog "local worker exited with code $exitCode; restarting"
    } catch {
        Write-SupervisorLog ("worker supervisor error: " + $_.Exception.Message)
    }
    Start-Sleep -Seconds $RestartDelaySeconds
    $RestartDelaySeconds = [Math]::Min(
        $MaxRestartDelaySeconds,
        [Math]::Max(5, $RestartDelaySeconds * 2)
    )
}
