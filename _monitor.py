# -*- coding: utf-8 -*-
"""JM娘 实时监控 v2：每 3 分钟检查；远程检查脚本一次性部署到服务器"""
import sys, time, re, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import paramiko

# 密码从 .deploy_secret 读取（与 deploy.py 一致，不入库）
_SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.deploy_secret')

def _pwd():
    try:
        with open(_SECRET_FILE, encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ''

REMOTE_CHECK = r'''#!/bin/bash
echo "8081=$(ss -tln 2>/dev/null | grep -c ':8081 ')"
echo "QQ=$(ps aux | grep -c '[o]pt/QQ/qq')"
echo "JM=$(ps aux | grep -c '[j]m_niang.py')"
echo "SCREEN=$(screen -ls 2>/dev/null | grep -c napcat)"
echo "SWAP_USED=$(free -m | awk '/Swap/{print $3}')"
echo "ZIP_PW=$(tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value jmniang)/environ 2>/dev/null | grep -cE '^JM_ZIP_PASSWORD=')"
echo "---JM_LOG---"
journalctl -u jmniang -n 6 --no-pager | grep -vE "连接断开|重连" | tail -4
echo "---UP_LOG---"
journalctl -u jmniang -n 80 --no-pager | grep -iE "上传|upload|retcode|失败|加密" | tail -5
echo "---ZIP_ENC---"
python3 <<'PYEOF'
import glob, os, pyzipper
for z in sorted(glob.glob('/opt/jmniang/downloads/*/*/*.zip'), key=os.path.getmtime, reverse=True)[:2]:
    try:
        with pyzipper.AESZipFile(z) as zf:
            i = zf.infolist()[0]
            print('ENC:', i.flag_bits & 1 == 1, os.path.basename(z)[:40])
    except Exception as e:
        print('FAIL:', type(e).__name__, os.path.basename(z)[:40])
PYEOF
echo "---NC_TAIL---"
grep -E "账号状态|FATAL|登录成功" /tmp/qq_start.log 2>/dev/null | tail -3
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect('64.90.13.42', username='root', password=_pwd(), timeout=25)
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/mon_check.sh', 'w') as f:
        f.write(REMOTE_CHECK)
    sftp.close()
    ssh.exec_command('chmod +x /tmp/mon_check.sh')
    print('[deploy] /tmp/mon_check.sh installed', flush=True)
    ssh.close()
except Exception as e:
    print(f'[deploy] FAILED: {type(e).__name__} (SSH 冷却中，3 分钟后自动重试)', flush=True)

while True:
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect('64.90.13.42', username='root', password=_pwd(), timeout=15)
        ssh.get_transport().set_keepalive(20)
        stdin, stdout, stderr = ssh.exec_command('bash /tmp/mon_check.sh', timeout=60)
        out = stdout.read().decode('utf-8', 'ignore')
        ssh.close()
        m = dict(re.findall(r'^(\w+)=(\d+)', out, re.M))
        ts = time.strftime('%H:%M:%S')
        s8081, qq, jm, scr, swap, zpw = (m.get(k, '?') for k in ('8081', 'QQ', 'JM', 'SCREEN', 'SWAP_USED', 'ZIP_PW'))
        status = 'OK'
        if s8081 != '1':
            status = 'ALERT-8081-DOWN'
        elif jm != '1':
            status = 'ALERT-JM-DEAD'
        elif qq == '0':
            status = 'ALERT-QQ-DEAD'
        print(f'[{ts}] {status} 8081={s8081} QQ={qq} jm={jm} swapMB={swap} ZIP_PW={zpw}', flush=True)
        print('---JM_LOG---' + out.split('---JM_LOG---')[-1].split('---UP_LOG---')[0][:400], flush=True)
        print('---UP_LOG---' + out.split('---UP_LOG---')[-1].split('---ZIP_ENC---')[0][:400], flush=True)
        print('---ZIP_ENC---' + out.split('---ZIP_ENC---')[-1].split('---NC_TAIL---')[0][:200], flush=True)
        print('---NC_TAIL---' + out.split('---NC_TAIL---')[-1][:200], flush=True)
    except Exception as e:
        print(f'[{time.strftime("%H:%M:%S")}] MONITOR-SSH-FAIL: {type(e).__name__}', flush=True)
    time.sleep(180)
