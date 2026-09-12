<#
.SYNOPSIS
  Read-only preflight for the local QQ/NapCat boundary.

.DESCRIPTION
  JM-Niang never injects, starts, patches, or stops QQ/NapCat.  This helper
  only reads the QQ executable version and blocks versions with a documented
  local incompatibility before an operator manually starts NapCat.
#>
[CmdletBinding()]
param(
    [string]$QQPath
)

$ErrorActionPreference = 'Stop'

function Resolve-QQPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        return $RequestedPath
    }

    $running = Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and (Test-Path -LiteralPath $_.ExecutablePath -PathType Leaf) } |
        Select-Object -First 1
    if ($running) {
        return $running.ExecutablePath
    }

    foreach ($candidate in @(
        (Join-Path ${env:ProgramFiles} 'Tencent\QQNT\QQ.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Tencent\QQNT\QQ.exe')
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

$resolvedPath = Resolve-QQPath $QQPath
if (-not $resolvedPath) {
    Write-Host '未发现 QQ.exe，跳过 QQ/NapCat 版本预检。请在登录 NapCat 前自行确认兼容性。' -ForegroundColor Yellow
    exit 0
}

$item = Get-Item -LiteralPath $resolvedPath
$version = $item.VersionInfo.FileVersion
if ([string]::IsNullOrWhiteSpace($version)) {
    Write-Host "无法读取 QQ 文件版本：$resolvedPath" -ForegroundColor Yellow
    exit 0
}

# Keep this deliberately small: absence from this list is not a compatibility
# guarantee.  Add a version only with a reproducible upstream finding.
$blocked = @{
    '9.9.32.51246' = '已知与当前 NapCat 注入适配不兼容；不要尝试注入。请保留此 QQ 供日常使用，并改用已验证的独立兼容运行环境。'
}

Write-Host "检测到 QQ：$resolvedPath" -ForegroundColor Cyan
Write-Host "版本：$version" -ForegroundColor Cyan
if ($blocked.ContainsKey($version)) {
    Write-Host ''
    Write-Host "NapCat 安全阻止：$($blocked[$version])" -ForegroundColor Red
    Write-Host 'JM娘本体不会修改 QQ；此检查也没有启动、停止或写入 QQ。' -ForegroundColor Yellow
    exit 2
}

Write-Host '该版本不在项目的已知阻止列表中；这不是 NapCat 官方兼容性保证。请按 NapCat 当前文档完成登录和 OneBot 配置。' -ForegroundColor Yellow
exit 0
