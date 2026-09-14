"""Start JM娘's isolated NapCat without exposing runtime credentials."""

from __future__ import annotations

import os
from pathlib import Path
import re
import socket
import subprocess
import sys


PROFILE_NAME = re.compile(r"^napcat_(\d+)\.json$")


def candidate_runtime_roots() -> list[Path]:
    project_root = Path(__file__).resolve().parents[1]
    candidates: list[Path] = [project_root / ".jmniang-runtime" / "NapCatPortable"]
    app_data = os.environ.get("APPDATA")
    if app_data:
        candidates.append(Path(app_data) / "JM-Niang-runtime" / "NapCatPortable")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "JM-Niang-runtime" / "NapCatPortable")

    for parent in Path(__file__).resolve().parents:
        if parent.name.casefold() == "roaming":
            user_home = parent.parent.parent
            candidates.append(user_home / "AppData" / "Local" / "JM-Niang-runtime" / "NapCatPortable")
            break

    return candidates


def find_runtime() -> tuple[Path, str] | None:
    for runtime_root in candidate_runtime_roots():
        node = runtime_root / "node.exe"
        index = runtime_root / "index.js"
        profile_dir = runtime_root / "napcat" / "config"
        if not (node.is_file() and index.is_file() and profile_dir.is_dir()):
            continue

        for profile in profile_dir.iterdir():
            match = PROFILE_NAME.fullmatch(profile.name)
            if profile.is_file() and match:
                return runtime_root, match.group(1)
    return None


def port_is_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8081), timeout=1):
            return True
    except OSError:
        return False


def start(runtime_root: Path, account: str) -> int:
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            [str(runtime_root / "node.exe"), "index.js", "-q", account],
            cwd=runtime_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except OSError:
        return 6
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"--preflight", "--ensure"}:
        return 2
    mode = sys.argv[1]

    runtime = find_runtime()
    if runtime is None:
        return 5
    if mode == "--preflight":
        return 0
    port_ready = port_is_listening()
    return 0 if port_ready else start(*runtime)


if __name__ == "__main__":
    raise SystemExit(main())
