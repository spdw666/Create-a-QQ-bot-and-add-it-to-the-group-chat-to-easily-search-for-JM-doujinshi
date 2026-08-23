@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
rem 首次运行：自动准备 Python 虚拟环境、依赖与 .env；随后检查 NapCat 并启动。
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo 启动未完成，错误码：%EXIT_CODE%。请按上方提示处理后重新双击。
  pause
)
exit /b %EXIT_CODE%
