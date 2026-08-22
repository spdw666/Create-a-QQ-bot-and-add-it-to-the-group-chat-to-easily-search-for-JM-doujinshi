# -*- coding: utf-8 -*-
"""JM娘 无感部署脚本：升级窗口内 @JM娘 自动回复"正在升级中，请稍后"
用法：python deploy.py <本机文件> <服务器路径>
流程：起维护应答器 → 停 JM娘 → 上传(独立连接) → 起 JM娘 → 关维护应答器
异常安全：任何步骤失败都会尝试恢复 JM娘 并关闭应答器
"""
import os
import sys
import time

import paramiko

HOST = os.environ.get('JM_SERVER_HOST', '64.90.13.42')
USER = os.environ.get('JM_SERVER_USER', 'root')
# 密码从本地 secret 文件读取（不入库）；文件路径：仓库根目录/.deploy_secret
SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.deploy_secret')


def get_pass():
    try:
        with open(SECRET_FILE, encoding='utf-8') as f:
            p = f.read().strip()
        if p:
            return p
    except OSError:
        pass
    env_p = os.environ.get('JM_SERVER_PASS')
    if env_p:
        return env_p
    print(f'错误：找不到服务器密码。请创建 {SECRET_FILE} 写入密码，或设置环境变量 JM_SERVER_PASS')
    sys.exit(1)


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=get_pass(), timeout=30)
    ssh.get_transport().set_keepalive(10)
    return ssh


def run(ssh, cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read().decode('utf-8', 'ignore'),
            stderr.read().decode('utf-8', 'ignore'))


def upload(ssh, local_file, remote_file, tries=2):
    """base64 分块上传（exec 通道；服务器 sshd 对 SFTP 通道不稳定/限流）"""
    import base64
    with open(local_file, 'rb') as f:
        content = f.read().replace(b'\r\n', b'\n')
    b64 = base64.b64encode(content).decode()
    CHUNK = 60000
    for attempt in range(1, tries + 1):
        try:
            run(ssh, f'rm -f {remote_file}.new', timeout=30)
            for i in range(0, len(b64), CHUNK):
                part = b64[i:i + CHUNK]
                _, err = run(ssh, f"echo {part} >> {remote_file}.new", timeout=60)
                if err:
                    raise RuntimeError(f'chunk 写入失败: {err[:80]}')
            out, err = run(ssh, f'base64 -d {remote_file}.new > {remote_file} && rm -f {remote_file}.new && md5sum {remote_file}', timeout=120)
            if err:
                raise RuntimeError(f'base64 解码失败: {err[:80]}')
            import hashlib
            expect = hashlib.md5(content).hexdigest()
            if expect not in out:
                raise RuntimeError(f'md5 不一致: {out.strip()[:40]} != {expect}')
            return True
        except Exception as e:
            print(f'  上传失败(第{attempt}次): {type(e).__name__} {e}', flush=True)
            time.sleep(8)
    return False


def main():
    local_file = sys.argv[1]
    remote_file = sys.argv[2] if len(sys.argv) > 2 else None
    # Git Bash 会把 /opt/... 参数转成 Windows 路径；远程路径内置兜底
    PATH_MAP = {
        'jm_niang.py': '/opt/jmniang/jm_niang.py',
        'jm_download.py': '/opt/jmniang/jm_download.py',
        'README.md': '/opt/jmniang/README.md',
        'requirements.txt': '/opt/jmniang/requirements.txt',
        'maintain_reply.py': '/opt/jmniang/maintain_reply.py',
        'qq_official_bot.py': '/opt/jmniang/qq_official_bot.py',
    }
    import os
    base = os.path.basename(local_file)
    if remote_file is None or not remote_file.startswith('/'):
        remote_file = PATH_MAP.get(base)
    if not remote_file:
        print('无法确定远程路径，请检查 PATH_MAP')
        sys.exit(1)
    print(f'部署 {base} → {remote_file}', flush=True)

    ssh = connect()
    ok = False
    try:
        # 1. 启动维护应答器
        out, _ = run(ssh, 'nohup python3 /opt/jmniang/maintain_reply.py > /tmp/maintain_reply.log 2>&1 & sleep 1; ps -eo pid,args | grep "[m]aintain_reply" | head -1')
        print('[1] 维护应答器:', out.strip() or '启动失败?', flush=True)

        # 2. 停 JM娘
        run(ssh, 'systemctl stop jmniang && sleep 1')
        print('[2] JM娘 已停（@ 由维护应答器回复"正在升级中"）', flush=True)

        # 3. 上传（base64 分块，重试2次）
        if not upload(ssh, local_file, remote_file):
            raise RuntimeError('上传失败')
        print(f'[3] 已上传 {remote_file}', flush=True)

        # 4. 起 JM娘
        out, _ = run(ssh, 'systemctl start jmniang; sleep 5; systemctl is-active jmniang')
        print('[4] JM娘:', out.strip(), flush=True)
        if out.strip() != 'active':
            raise RuntimeError('JM娘 启动失败')

        ok = True
    except Exception as e:
        print(f'部署失败: {e!r}，尝试恢复 JM娘…', flush=True)
        run(ssh, 'systemctl start jmniang 2>/dev/null; sleep 3; systemctl is-active jmniang')
    finally:
        run(ssh, 'pkill -9 -f maintain_reply.py 2>/dev/null; sleep 1')
        out, _ = run(ssh, 'ps -eo pid,args | grep "[m]aintain_reply" || echo 已清理')
        print('[5] 维护应答器:', out.strip().splitlines()[-1] if out.strip() else '?', flush=True)

    ssh.close()
    print('部署完成' if ok else '部署失败（JM娘 已尝试恢复）', flush=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
