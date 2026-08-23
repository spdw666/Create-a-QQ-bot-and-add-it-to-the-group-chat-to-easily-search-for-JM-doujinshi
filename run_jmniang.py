#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JM娘本地启动器：加载 .env、检查配置，并启动 HTTP 分享服务与机器人。"""

from __future__ import annotations

import argparse
import asyncio
import functools
import http.server
import os
import re
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / '.env'
DEFAULT_PASSWORDS = {'', 'CHANGE_ME', 'change-this', 'replace-me'}
ENV_KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


@dataclass(frozen=True)
class RuntimeSettings:
    public_host: str
    http_bind: str
    http_port: int


def parse_env_text(text: str) -> dict[str, str]:
    """读取简单 .env 格式；真实系统环境变量的优先级更高。"""
    values: dict[str, str] = {}
    for number, original in enumerate(text.splitlines(), start=1):
        line = original.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        if '=' not in line:
            raise ValueError(f'.env 第 {number} 行缺少 =')
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not ENV_KEY.fullmatch(key):
            raise ValueError(f'.env 第 {number} 行的变量名无效：{key!r}')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_local_env(path: Path = ENV_FILE) -> bool:
    """加载仓库根目录 .env，且绝不覆盖外部已显式传入的环境变量。"""
    if not path.is_file():
        return False
    for key, value in parse_env_text(path.read_text(encoding='utf-8-sig')).items():
        os.environ.setdefault(key, value)
    return True


def validate_settings(env: dict[str, str] | None = None) -> tuple[RuntimeSettings, list[str]]:
    """在导入机器人模块前给出可操作的配置错误。"""
    source = os.environ if env is None else env
    password = source.get('JM_ZIP_PASSWORD', '').strip()
    public_host = source.get('JM_PUBLIC_IP', '').strip()
    http_bind = source.get('JM_HTTP_BIND', '0.0.0.0').strip() or '0.0.0.0'
    raw_port = source.get('JM_HTTP_PORT', '8080').strip() or '8080'
    errors: list[str] = []
    warnings: list[str] = []

    if password in DEFAULT_PASSWORDS:
        errors.append('JM_ZIP_PASSWORD 未设置或仍是示例值；请在 .env 中设置新的 ZIP 密码。')
    if not public_host:
        errors.append('JM_PUBLIC_IP 不能为空；请填写本机公网 IP、可访问域名或局域网 IP。')
    try:
        http_port = int(raw_port)
        if not 1 <= http_port <= 65535:
            raise ValueError
    except ValueError:
        errors.append('JM_HTTP_PORT 必须是 1 到 65535 的端口号。')
        http_port = 8080
    if public_host.lower() in {'127.0.0.1', 'localhost', '::1'}:
        warnings.append('JM_PUBLIC_IP 指向本机；群成员无法使用 HTTP 下载链接，但群文件上传仍可用。')
    if errors:
        raise ValueError('\n'.join(errors))
    return RuntimeSettings(public_host, http_bind, http_port), warnings


class QuietFileHandler(http.server.SimpleHTTPRequestHandler):
    """分享下载文件，不把每次请求刷进启动控制台。"""

    def log_message(self, _format: str, *_args: object) -> None:
        return


def start_share_server(settings: RuntimeSettings) -> http.server.ThreadingHTTPServer | None:
    share_dir = BASE_DIR / 'http_dl'
    share_dir.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(QuietFileHandler, directory=str(share_dir))
    try:
        server = http.server.ThreadingHTTPServer((settings.http_bind, settings.http_port), handler)
    except OSError as exc:
        print(
            f'[WARN] HTTP 分享服务未由本启动器启动（{settings.http_bind}:{settings.http_port}：{exc}）。\n'
            '   如果该端口已由 Nginx 或其他 HTTP 服务托管 http_dl/，可忽略；否则群内下载链接不可用。',
            file=sys.stderr,
        )
        return None
    threading.Thread(target=server.serve_forever, name='jm-http-share', daemon=True).start()
    print(f'[OK] HTTP 分享服务：http://{settings.public_host}:{settings.http_port}/')
    return server


def napcat_available(host: str = '127.0.0.1', port: int = 8081) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description='启动 JM娘并托管本地 HTTP 分享目录。')
    parser.add_argument('--check', action='store_true', help='只检查 .env 与 NapCat 8081，不启动服务。')
    parser.add_argument('--no-http', action='store_true', help='不启动内置 HTTP 分享服务（交给 Nginx 等外部服务）。')
    args = parser.parse_args()

    if not load_local_env():
        print('[ERROR] 找不到 .env。请运行 start_jmniang.bat 生成配置，或复制 .env.example 为 .env。', file=sys.stderr)
        return 2
    try:
        settings, warnings = validate_settings()
    except ValueError as exc:
        print(f'[ERROR] 配置检查失败：\n{exc}', file=sys.stderr)
        return 2
    for warning in warnings:
        print(f'[WARN] {warning}', file=sys.stderr)

    napcat_ok = napcat_available()
    print('[OK] NapCat 正向 WebSocket（127.0.0.1:8081）已就绪。' if napcat_ok
          else '[WARN] NapCat 8081 当前不可达；机器人会持续重连。')
    if args.check:
        return 0 if napcat_ok else 3

    server = None if args.no_http else start_share_server(settings)
    try:
        import jm_niang
        asyncio.run(jm_niang.main())
    except KeyboardInterrupt:
        print('\nJM娘 已停止。')
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
