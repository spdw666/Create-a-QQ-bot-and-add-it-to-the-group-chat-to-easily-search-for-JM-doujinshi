[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $Root '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$Requirements = Join-Path $Root 'requirements.txt'
$Stamp = Join-Path $VenvDir '.requirements.sha256'
$OcrInstaller = Join-Path $PSScriptRoot 'install_ocr.ps1'

function Find-Python {
    $candidates = @(
        @{ Name = 'py'; Args = @('-3.11') },
        @{ Name = 'py'; Args = @('-3.12') },
        @{ Name = 'py'; Args = @('-3.10') },
        @{ Name = 'py'; Args = @('-V:Astral/CPython3.11') },
        @{ Name = 'py'; Args = @('-V:Astral/CPython3.12') },
        @{ Name = 'python'; Args = @() }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Name -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $exitCode = 1
        try {
            & $command.Source @($candidate.Args) -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' 2>$null
            $exitCode = $LASTEXITCODE
        } catch {
            # 缺失的 py 版本会在 Windows PowerShell 中成为 NativeCommandError；继续探测下一个候选。
        }
        if ($exitCode -eq 0) {
            return [PSCustomObject]@{ Exe = $command.Source; Args = @($candidate.Args) }
        }
    }
    # winget 刚安装 Python 时，当前 PowerShell 的 PATH 可能尚未刷新；直接检查常见安装位置。
    $installedPaths = @(
        (Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:ProgramFiles 'Python311\python.exe')
    )
    foreach ($path in $installedPaths) {
        if (-not (Test-Path $path)) { continue }
        $exitCode = 1
        try {
            & $path -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' 2>$null
            $exitCode = $LASTEXITCODE
        } catch {
            continue
        }
        if ($exitCode -eq 0) {
            return [PSCustomObject]@{ Exe = $path; Args = @() }
        }
    }
    return $null
}

function New-RandomPassword {
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $bytes = New-Object byte[] 20
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments, [string]$Action) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Action 失败，退出码：$LASTEXITCODE"
    }
}

function Get-Sha256([string]$Path) {
    # 不依赖 Get-FileHash，兼容裁剪版或较旧的 Windows PowerShell。
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ([System.BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '')
    } finally {
        $stream.Dispose()
        $hasher.Dispose()
    }
}

function Set-EnvValue([string]$Content, [string]$Name, [string]$Value) {
    $escapedName = [regex]::Escape($Name)
    return [regex]::Replace($Content, "(?m)^$escapedName=.*$", "$Name=$Value")
}

Set-Location $Root
$Python = Find-Python
if (-not $Python) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw '未找到受支持的 Python 3.10–3.12 或 winget。请安装 Python 3.11（勾选 Add Python to PATH）后重新双击本文件。'
    }
    Write-Host '正在通过 winget 安装 Python 3.11…' -ForegroundColor Yellow
    Invoke-Checked $winget.Source @('install', '--exact', '--id', 'Python.Python.3.11', '--accept-package-agreements', '--accept-source-agreements') 'Python 安装'
    $Python = Find-Python
    if (-not $Python) {
        throw 'Python 安装完成后仍未找到解释器。请确认安装成功后重新双击 start_jmniang.bat。'
    }
}

if (-not (Test-Path $VenvPython)) {
    Write-Host '正在创建独立 Python 环境…' -ForegroundColor Cyan
    Invoke-Checked $Python.Exe (@($Python.Args) + @('-m', 'venv', $VenvDir)) '创建 Python 虚拟环境'
}

$requirementsHash = Get-Sha256 $Requirements
$installedHash = if (Test-Path $Stamp) { (Get-Content $Stamp -Raw).Trim() } else { '' }
if ($requirementsHash -ne $installedHash) {
    Write-Host '正在安装机器人核心依赖（首次可能需数分钟）…' -ForegroundColor Cyan
    Invoke-Checked $VenvPython @('-m', 'pip', 'install', '-r', $Requirements) '安装项目依赖'
    Set-Content -LiteralPath $Stamp -Value $requirementsHash -Encoding ascii -NoNewline
}

$ocrReady = $false
try {
    & $VenvPython -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('rapidocr_onnxruntime') and importlib.util.find_spec('onnxruntime') else 1)" 2>$null
    $ocrReady = ($LASTEXITCODE -eq 0)
} catch {
    $ocrReady = $false
}
if (-not $ocrReady) {
    Write-Host "提示：本地 OCR 运行时尚未安装；机器人其余功能可正常启动。网络稳定后运行：$OcrInstaller" -ForegroundColor Yellow
}

$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) {
    Copy-Item (Join-Path $Root '.env.example') $EnvPath
    $publicHost = Read-Host '输入公网 IP/域名（直接回车仅本机测试，群成员无法打开 HTTP 链接）'
    if ([string]::IsNullOrWhiteSpace($publicHost)) { $publicHost = '127.0.0.1' }
    $envText = Get-Content $EnvPath -Raw
    $envText = Set-EnvValue $envText 'JM_ZIP_PASSWORD' (New-RandomPassword)
    $envText = Set-EnvValue $envText 'JM_PUBLIC_IP' $publicHost.Trim()
    Set-Content -LiteralPath $EnvPath -Value $envText -Encoding utf8 -NoNewline
    Write-Host "已生成 .env。请妥善保管其中的 ZIP 密码；它不会提交到 Git。" -ForegroundColor Green
}

& $VenvPython (Join-Path $Root 'run_jmniang.py') --check
if ($LASTEXITCODE -eq 3) {
    Write-Host ''
    Write-Host 'NapCat 尚未就绪：请登录 QQ，并在 NapCat 创建正向 WebSocket 服务端 ws://127.0.0.1:8081。' -ForegroundColor Yellow
    Write-Host '本启动器不会启动、注入、修补或结束 QQ/NapCat；请先自行确认该 QQ 版本受 NapCat 支持。' -ForegroundColor Yellow
    $compatibilityCheck = Join-Path $Root 'scripts\check_napcat_compatibility.ps1'
    if (Test-Path -LiteralPath $compatibilityCheck) {
        & $compatibilityCheck
        if ($LASTEXITCODE -eq 2) {
            Write-Host '已因已知不兼容 QQ 版本安全停止；请勿反复尝试 NapCat 注入。' -ForegroundColor Red
        }
    }
    Write-Host '详细步骤：docs\first-run.md' -ForegroundColor Yellow
    exit 3
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '启动 JM娘；关闭此窗口或按 Ctrl+C 可停止。' -ForegroundColor Green
& $VenvPython (Join-Path $Root 'run_jmniang.py')
exit $LASTEXITCODE
