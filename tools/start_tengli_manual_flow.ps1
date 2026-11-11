param(
    [string]$RunRoot = 'C:/tl/tengli-template-styles-20261111/site-batch',
    [string]$ProviderEnv = 'D:/Desktop/cyh/tengli/polaris-commerce-studio/backend/.env',
    [string]$Python = 'C:/Users/a1726/codex-workspaces/tengli-motion-20261109/.venv/Scripts/python.exe',
    [int]$ApiPort = 8018,
    [int]$WebPort = 3018
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$node = (Get-Command node -ErrorAction Stop).Source
$vinext = Join-Path $repo 'node_modules/vinext/dist/cli.js'
$logs = Join-Path $RunRoot 'manual-runtime-logs'
foreach ($required in @($ProviderEnv, $Python, $vinext, (Join-Path $RunRoot 'site.db'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing local dependency: $required"
    }
}
New-Item -ItemType Directory -Path $logs -Force | Out-Null

function Get-Listener([int]$Port) {
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Quote-Argument([string]$Value) { '"' + $Value + '"' }

$api = Get-Listener $ApiPort
if ($api) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($api.OwningProcess)"
    if ($owner.CommandLine -notlike '*tengli_manual_flow_runtime.py*') {
        throw "API port $ApiPort is occupied by another service. No process was stopped."
    }
} else {
    $apiArgs = @(
        (Quote-Argument (Join-Path $PSScriptRoot 'tengli_manual_flow_runtime.py')),
        '--root', (Quote-Argument $RunRoot),
        '--provider-env', (Quote-Argument $ProviderEnv),
        '--enable-user-submissions', '--port', $ApiPort
    )
    $env:PYTHONUTF8 = '1'
    Start-Process -FilePath $Python -ArgumentList $apiArgs -WorkingDirectory $repo `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'api.log') `
        -RedirectStandardError (Join-Path $logs 'api-error.log') | Out-Null
}

$web = Get-Listener $WebPort
if ($web) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($web.OwningProcess)"
    if ($owner.CommandLine -notlike '*vinext*') {
        throw "Web port $WebPort is occupied by another service. No process was stopped."
    }
} else {
    $env:VITE_LOCAL_DEV_AUTH = 'true'
    $env:NEXT_PUBLIC_LOCAL_DEV_AUTH = 'true'
    $env:VITE_API_PROXY_TARGET = "http://127.0.0.1:$ApiPort"
    Start-Process -FilePath $node -ArgumentList @((Quote-Argument $vinext), 'dev', '--port', $WebPort) `
        -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs 'web.log') `
        -RedirectStandardError (Join-Path $logs 'web-error.log') | Out-Null
}

Write-Output "Local manual flow: http://localhost:$WebPort/video-studio/avatars"
Write-Output 'Generation starts only when you submit it in the interface. No paid task was submitted by this launcher.'
