@echo off
setlocal EnableExtensions

rem This is intentionally a plain cmd launcher so the logon task does not use
rem a startup-folder shortcut, VBS, wscript, or PowerShell.
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "BOT=%ROOT%\run_jmniang.py"
set "LOG_DIR=%ROOT%\logs"
set "LOG=%LOG_DIR%\jmniang-local.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul
if not exist "%PYTHON%" (
    >> "%LOG%" echo [%date% %time%] [ERROR] 未找到 .venv\Scripts\python.exe，请先运行 start_jmniang.bat。
    exit /b 2
)
if not exist "%ROOT%\.env" (
    >> "%LOG%" echo [%date% %time%] [ERROR] 未找到 .env，请先运行 start_jmniang.bat 完成首次配置。
    exit /b 3
)

:restart
>> "%LOG%" echo [%date% %time%] [INFO] 启动 JM娘。
"%PYTHON%" -X utf8 "%BOT%" >> "%LOG%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
>> "%LOG%" echo [%date% %time%] [WARN] JM娘退出（%EXIT_CODE%），10 秒后重试。
timeout /t 10 /nobreak >nul
goto restart
