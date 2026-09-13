[CmdletBinding()]
param()

$TaskName = 'JM娘本地机器人'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host '已移除 JM娘 登录自启动计划任务。'
} else {
    Write-Host '未发现 JM娘 登录自启动计划任务。'
}

# Clean up only the exact legacy shortcut that earlier project versions created.
$legacyShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'JM娘本地机器人.lnk'
if (Test-Path -LiteralPath $legacyShortcut) {
    Remove-Item -LiteralPath $legacyShortcut
    Write-Host '已清理旧版启动目录快捷方式。'
}
