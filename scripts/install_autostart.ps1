[CmdletBinding()]
param()

# 为当前 Windows 用户创建登录后自启动快捷方式；不需要管理员权限。
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Vbs = Join-Path $PSScriptRoot 'start_background.vbs'
$Startup = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $Startup 'JM娘本地机器人.lnk'

if (-not (Test-Path $Vbs)) { throw "找不到后台启动器：$Vbs" }
if (-not (Test-Path (Join-Path $Root '.env'))) { throw '找不到 .env。请先运行 start_jmniang.bat 完成首次配置。' }
if (-not (Test-Path (Join-Path $Root '.venv\Scripts\python.exe'))) { throw '找不到 .venv。请先运行 start_jmniang.bat 安装依赖。' }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$shortcut.Arguments = '"' + $Vbs + '"'
$shortcut.WorkingDirectory = $Root
$shortcut.Description = 'JM娘本地常驻守护'
$shortcut.Save()

Write-Host "已创建登录自启动：$ShortcutPath" -ForegroundColor Green
Write-Host '提示：请同时在 NapCat/QQ 侧开启开机或登录后启动；机器人会在 8081 出现前持续重连。' -ForegroundColor Yellow
