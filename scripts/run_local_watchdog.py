"""Run JM娘's local watchdog without creating a console window at logon."""

from __future__ import annotations

import ctypes
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time
from ctypes import wintypes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
BOT = PROJECT_ROOT / "run_jmniang.py"
NAPCAT_LAUNCHER = PROJECT_ROOT / "scripts" / "launch_portable_napcat.py"
LOG_DIRECTORY = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIRECTORY / "jmniang-local.log"
RETRY_DELAY_SECONDS = 10
ERROR_ALREADY_EXISTS = 183
WATCHDOG_MUTEX_NAME = "Local\\JMNiangLocalWatchdog"


def write_log(level: str, message: str) -> None:
    """Append only operational status; no settings or credentials are read."""
    LOG_DIRECTORY.mkdir(exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with LOG_FILE.open("a", encoding="utf-8", newline="") as log_file:
        log_file.write(f"{timestamp} [{level}] {message}\n")


def validate_installation() -> int:
    if not PYTHON.is_file():
        write_log("ERROR", "未找到 .venv\\Scripts\\python.exe，请先运行 start_jmniang.bat。")
        return 2
    if not (PROJECT_ROOT / ".env").is_file():
        write_log("ERROR", "未找到 .env，请先运行 start_jmniang.bat 完成首次配置。")
        return 3
    if not NAPCAT_LAUNCHER.is_file():
        write_log("ERROR", "未找到隔离 NapCat 启动器。")
        return 4
    return 0


def no_window_flags() -> int:
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


def ensure_portable_napcat() -> int:
    try:
        completed = subprocess.run(
            [str(PYTHON), "-X", "utf8", str(NAPCAT_LAUNCHER), "--ensure"],
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=no_window_flags(),
            check=False,
        )
    except OSError:
        return 6
    return completed.returncode


def run_bot_once() -> int:
    try:
        with LOG_FILE.open("ab") as log_file:
            completed = subprocess.run(
                [str(PYTHON), "-X", "utf8", str(BOT)],
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=no_window_flags(),
                check=False,
            )
    except OSError:
        return 6
    return completed.returncode


def acquire_watchdog_mutex() -> int | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, WATCHDOG_MUTEX_NAME)
    if not handle:
        return None
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def release_watchdog_mutex(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.ReleaseMutex(handle)
    kernel32.CloseHandle(handle)


def run_preflight() -> int:
    result = validate_installation()
    if result:
        return result
    return subprocess.run(
        [str(PYTHON), "-X", "utf8", str(NAPCAT_LAUNCHER), "--preflight"],
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=no_window_flags(),
        check=False,
    ).returncode


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--preflight":
        return run_preflight()
    if len(sys.argv) != 1:
        return 2

    result = validate_installation()
    if result:
        return result

    mutex = acquire_watchdog_mutex()
    if mutex is None:
        return 0

    try:
        napcat_result = ensure_portable_napcat()
        if napcat_result:
            write_log("WARN", f"隔离 NapCat 启动器返回 {napcat_result}。")

        while True:
            write_log("INFO", "启动 JM娘。")
            exit_code = run_bot_once()
            write_log("WARN", f"JM娘退出（{exit_code}），{RETRY_DELAY_SECONDS} 秒后重试。")
            time.sleep(RETRY_DELAY_SECONDS)
    finally:
        release_watchdog_mutex(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
