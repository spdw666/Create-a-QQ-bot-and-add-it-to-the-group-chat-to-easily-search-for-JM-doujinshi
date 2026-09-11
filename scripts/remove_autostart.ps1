[CmdletBinding()]
param()

$ShortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'JM娘本地机器人.lnk'
if (Test-Path $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath
    Write-Host '已移除 JM娘 登录自启动快捷方式。'
} else {
    Write-Host '未发现 JM娘 登录自启动快捷方式。'
}
