@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem This is intentionally a plain cmd launcher so the logon task does not use
rem a startup-folder shortcut, VBS, wscript, or PowerShell.
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "BOT=%ROOT%\run_jmniang.py"
set "LOG_DIR=%ROOT%\logs"
set "LOG=%LOG_DIR%\jmniang-local.log"
set "NAPCAT_LAUNCHER=%ROOT%\scripts\launch_portable_napcat.py"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul
if not exist "%PYTHON%" (
    >> "%LOG%" echo [%date% %time%] [ERROR] 未找到 .venv\Scripts\python.exe，请先运行 start_jmniang.bat。
    exit /b 2
)
if not exist "%ROOT%\.env" (
    >> "%LOG%" echo [%date% %time%] [ERROR] 未找到 .env，请先运行 start_jmniang.bat 完成首次配置。
    exit /b 3
)
if not exist "%NAPCAT_LAUNCHER%" (
    >> "%LOG%" echo [%date% %time%] [ERROR] 未找到隔离 NapCat 启动器。
    exit /b 4
)

rem The bot task is the known-good login entry point.  It performs a small,
rem idempotent local 8081 recovery before Python starts, using the project
rem Python launcher so child Node does not inherit this cmd console.
if /i "%~1"=="--preflight" (
    "%PYTHON%" -X utf8 "%NAPCAT_LAUNCHER%" --preflight >nul 2>&1
    exit /b !ERRORLEVEL!
)

call :ensure_portable_napcat

:restart
>> "%LOG%" echo [%date% %time%] [INFO] 启动 JM娘。
"%PYTHON%" -X utf8 "%BOT%" >> "%LOG%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
>> "%LOG%" echo [%date% %time%] [WARN] JM娘退出（%EXIT_CODE%），10 秒后重试。
timeout /t 10 /nobreak >nul
goto restart

:ensure_portable_napcat
%SystemRoot%\System32\netstat.exe -ano | %SystemRoot%\System32\findstr.exe /r /c:":8081 .*LISTENING" >nul
if not errorlevel 1 (
    goto :eof
)
"%PYTHON%" -X utf8 "%NAPCAT_LAUNCHER%" --ensure >nul 2>&1
set "NAPCAT_START_CODE=!ERRORLEVEL!"
if not "%NAPCAT_START_CODE%"=="0" >> "%LOG%" echo [%date% %time%] [WARN] 隔离 NapCat 启动器返回 %NAPCAT_START_CODE%。
goto :eof
