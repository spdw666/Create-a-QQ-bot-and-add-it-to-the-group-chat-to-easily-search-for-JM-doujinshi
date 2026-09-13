[CmdletBinding()]
param()

# Register a current-user logon task. The task itself runs only cmd.exe and the
# project batch launcher, avoiding startup-folder shortcuts, VBS, wscript, and
# PowerShell at logon.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $PSScriptRoot 'run_local_watchdog.cmd'
$TaskName = 'JM娘本地机器人'
$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path -LiteralPath $Launcher)) { throw "找不到本地启动器：$Launcher" }
if (-not (Test-Path -LiteralPath (Join-Path $Root '.env'))) { throw '找不到 .env。请先运行 start_jmniang.bat 完成首次配置。' }
if (-not (Test-Path -LiteralPath (Join-Path $Root '.venv\Scripts\python.exe'))) { throw '找不到 .venv。请先运行 start_jmniang.bat 安装依赖。' }

$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument ('/d /c ""{0}""' -f $Launcher)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "已注册登录自启动计划任务：$TaskName" -ForegroundColor Green
Write-Host '任务仅在当前用户登录后运行 cmd 启动器；不需要管理员权限。NapCat 必须由你自己的兼容安装方式保持登录，机器人会在 8081 出现前持续重连。' -ForegroundColor Yellow
