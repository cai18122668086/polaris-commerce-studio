param(
    [ValidateSet("Install", "Uninstall", "RunNow")]
    [string]$Action = "Install",
    [string]$TaskName = "PolarisCommerceLocalWorker",
    [string]$WorkerRoot = "D:\Polaris\local-worker"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $repoRoot "tools\run_local_worker.ps1"
$template = Join-Path $repoRoot "tools\local-worker.env.example.ps1"
$envFile = Join-Path $WorkerRoot "worker.env.ps1"

if ($Action -eq "Uninstall") {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task $TaskName. Worker files were preserved at $WorkerRoot."
    exit 0
}

if (-not (Test-Path -LiteralPath $envFile)) {
    New-Item -ItemType Directory -Force -Path $WorkerRoot | Out-Null
    Copy-Item -LiteralPath $template -Destination $envFile
    Write-Host "Created $envFile from the template. Fill in the Worker values, then rerun with -Action Install."
    exit 2
}
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Worker supervisor script not found: $runner"
}

New-Item -ItemType Directory -Force -Path (Join-Path $WorkerRoot "logs") | Out-Null
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$argument = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -EnvFile `"$envFile`" -WorkerRoot `"$WorkerRoot`""
$taskAction = New-ScheduledTaskAction -Execute $powershell -Argument $argument
$taskTrigger = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Seconds 30)
$taskSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $taskAction `
    -Trigger $taskTrigger `
    -Settings $taskSettings `
    -User "SYSTEM" `
    -RunLevel Highest `
    -Description "Persistent Polaris Commerce Studio local ecommerce Worker" `
    -Force | Out-Null

Write-Host "Installed $TaskName. It starts at boot and restarts after Worker exit."
if ($Action -eq "RunNow") {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started $TaskName."
}
