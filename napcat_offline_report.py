# -*- coding: utf-8 -*-
"""napcat_offline_report.py — 每2小时掉线汇总报告（cron 独立运行，不依赖 jmniang 进程状态）

统计 journalctl 最近2小时的「NapCat 已连接」次数（= 掉线恢复/重连次数），
通过 OneBot WS 发到通知群。n<=0 静默。
"""
import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta

WS_URL = 'ws://127.0.0.1:8081'
NOTIFY_GROUP = int(os.environ.get('JM_NOTIFY_GROUP', '810152420'))
WINDOW_HOURS = 2


def get_reconnect_times():
    """返回 [(datetime, ...)]：最近2小时内 jmniang 日志中的重连成功时刻"""
    out = subprocess.run(
        ['journalctl', '-u', 'jmniang', '--since', f'{WINDOW_HOURS} hours ago', '--no-pager'],
        capture_output=True, text=True, timeout=30).stdout
    times = []
    for line in out.splitlines():
        if 'NapCat 已连接' not in line:
            continue
        try:
            ts = ' '.join(line.split()[:3])  # "Aug 14 18:42:05"
            times.append(datetime.strptime(ts, '%b %d %H:%M:%S').replace(year=datetime.now().year))
        except ValueError:
            continue
    return times


async def send_report(msg):
    import websockets
    async with websockets.connect(WS_URL) as ws:
        echo = str(uuid.uuid4())
        await ws.send(json.dumps({'action': 'send_group_msg',
                                  'params': {'group_id': NOTIFY_GROUP, 'message': msg},
                                  'echo': echo}))
        try:
            while True:
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if resp.get('echo') == echo:
                    break
        except Exception:
            pass


def main():
    times = get_reconnect_times()
    n = len(times)
    if n <= 0:
        return  # 2小时内无重连，静默
    now = datetime.now()
    if n == 1:
        mins = max(0, int((now - times[0]).total_seconds() // 60))
        interval_text = f'（约 {mins} 分钟前恢复）'
    else:
        gaps = [(times[i + 1] - times[i]).total_seconds() for i in range(n - 1)]
        avg = int(sum(gaps) / len(gaps) // 60)
        interval_text = f'，平均每隔约 {avg} 分钟重连一次'
    msg = f'📊 掉线报告（过去2小时）：机器人共重连 {n} 次{interval_text}。当前已恢复在线 ✅'
    try:
        asyncio.run(send_report(msg))
        print('sent:', msg)
    except Exception as e:
        print('send failed (QQ 掉线中？):', e)


if __name__ == '__main__':
    main()
