[CmdletBinding()]
param()

# OCR 是可选增强：网络恢复后可单独运行此脚本，不影响已经在线的机器人核心。
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Requirements = Join-Path $Root 'requirements-ocr.txt'

if (-not (Test-Path $Python)) { throw '找不到 .venv。请先运行 start_jmniang.bat。' }
Write-Host '正在安装本地 OCR 运行时（需要下载 ONNX/OpenCV，网络不稳定时可稍后重试）…' -ForegroundColor Cyan
& $Python -m pip install --timeout 30 --retries 2 -r $Requirements
if ($LASTEXITCODE -ne 0) { throw "OCR 安装失败，退出码：$LASTEXITCODE。核心机器人不受影响，可在网络恢复后重试。" }
& $Python -c "import rapidocr_onnxruntime, onnxruntime; print('OCR 运行时安装完成。')"
if ($LASTEXITCODE -ne 0) { throw 'OCR 包下载完成但导入失败；请重试或检查本机运行库。' }
