[CmdletBinding()]
param()

# 旧版 PowerShell 守护器，保留给手动维护场景。
# 登录自启动请使用 install_autostart.ps1：它注册计划任务并由 run_local_watchdog.cmd 执行。
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$LogDir = Join-Path $Root 'logs'
$Log = Join-Path $LogDir 'jmniang-local.log'
$mutexCreated = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\JMNiangLocalWatchdog', [ref]$mutexCreated)

if (-not $mutexCreated) { exit 0 }

try {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    if (-not (Test-Path $Python)) {
        Add-Content -LiteralPath $Log -Value "$(Get-Date -Format s) [ERROR] 未找到 .venv，请先运行 start_jmniang.bat。" -Encoding utf8
        exit 2
    }
    if (-not (Test-Path (Join-Path $Root '.env'))) {
        Add-Content -LiteralPath $Log -Value "$(Get-Date -Format s) [ERROR] 未找到 .env，请先运行 start_jmniang.bat。" -Encoding utf8
        exit 2
    }
    Set-Location $Root
    while ($true) {
        Add-Content -LiteralPath $Log -Value "$(Get-Date -Format s) [INFO] 启动 JM娘。" -Encoding utf8
        $exitCode = 1
        try {
            # 由 cmd 合并 Python 的 stdout/stderr，避免 PowerShell 将普通 stderr 提示包装成 NativeCommandError。
            $bot = Join-Path $Root 'run_jmniang.py'
            $command = '""{0}" -X utf8 "{1}" >> "{2}" 2>&1"' -f $Python, $bot, $Log
            & $env:ComSpec /d /c $command
            $exitCode = $LASTEXITCODE
        } catch {
            Add-Content -LiteralPath $Log -Value "$(Get-Date -Format s) [ERROR] 子进程调用异常：$($_.Exception.GetType().Name)" -Encoding utf8
        }
        Add-Content -LiteralPath $Log -Value "$(Get-Date -Format s) [WARN] JM娘退出（$exitCode），10 秒后重试。" -Encoding utf8
        Start-Sleep -Seconds 10
    }
}
finally {
    if ($mutexCreated) {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }
}
