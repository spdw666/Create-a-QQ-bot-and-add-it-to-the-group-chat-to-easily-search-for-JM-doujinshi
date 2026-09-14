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
set "NAPCAT_ROOT=%LOCALAPPDATA%\JM-Niang-runtime\NapCatPortable"
set "NAPCAT_NODE=%NAPCAT_ROOT%\node.exe"
set "NAPCAT_PROFILE_DIR=%NAPCAT_ROOT%\napcat\config"
set "NAPCAT_LOG=%NAPCAT_ROOT%\logs\scheduled-napcat.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul
if not exist "%PYTHON%" (
    >> "%LOG%" echo [%date% %time%] [ERROR] 未找到 .venv\Scripts\python.exe，请先运行 start_jmniang.bat。
    exit /b 2
)
if not exist "%ROOT%\.env" (
    >> "%LOG%" echo [%date% %time%] [ERROR] 未找到 .env，请先运行 start_jmniang.bat 完成首次配置。
    exit /b 3
)

rem The dedicated NapCat logon task can be rejected by Task Scheduler before
rem cmd.exe reaches its script.  The bot's own logon task is known-good, so
rem it also performs this small, idempotent local 8081 recovery before Python
rem starts.  It only touches JM娘's isolated runtime under %%LOCALAPPDATA%%.
call :ensure_portable_napcat
if /i "%~1"=="--preflight" exit /b 0

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
    >> "%LOG%" echo [%date% %time%] [INFO] 本机 NapCat 8081 已可用，无需重复启动。
    goto :eof
)

if not exist "%NAPCAT_NODE%" (
    >> "%LOG%" echo [%date% %time%] [WARN] 未找到便携 NapCat node.exe，跳过本地恢复。
    goto :eof
)
if not exist "%NAPCAT_ROOT%\index.js" (
    >> "%LOG%" echo [%date% %time%] [WARN] 未找到便携 NapCat index.js，跳过本地恢复。
    goto :eof
)
if not exist "%NAPCAT_PROFILE_DIR%" (
    >> "%LOG%" echo [%date% %time%] [WARN] 未找到便携 NapCat 配置目录，跳过本地恢复。
    goto :eof
)

set "NAPCAT_ACCOUNT="
for /f "usebackq delims=" %%F in (`dir /b /a-d "%NAPCAT_PROFILE_DIR%\napcat_*.json" 2^>nul ^| %SystemRoot%\System32\findstr.exe /r /x "napcat_[0-9][0-9]*\.json"`) do (
    set "NAPCAT_PROFILE=%%~nF"
    set "NAPCAT_ACCOUNT=!NAPCAT_PROFILE:napcat_=!"
    goto :napcat_profile_found
)
>> "%LOG%" echo [%date% %time%] [WARN] 未找到便携 NapCat 登录配置，跳过本地恢复。
goto :eof

:napcat_profile_found
if not exist "%NAPCAT_ROOT%\logs" mkdir "%NAPCAT_ROOT%\logs" 2>nul
pushd "%NAPCAT_ROOT%" || (
    >> "%LOG%" echo [%date% %time%] [WARN] 无法进入便携 NapCat 目录，跳过本地恢复。
    goto :eof
)
>> "%LOG%" echo [%date% %time%] [INFO] 8081 不可用，启动隔离的便携 NapCat 恢复连接。
start "" /b "%NAPCAT_NODE%" ".\index.js" -q "%NAPCAT_ACCOUNT%" >> "%NAPCAT_LOG%" 2>&1
set "NAPCAT_START_CODE=%ERRORLEVEL%"
popd
if not "%NAPCAT_START_CODE%"=="0" >> "%LOG%" echo [%date% %time%] [WARN] 便携 NapCat 启动命令返回 %NAPCAT_START_CODE%。
goto :eof
