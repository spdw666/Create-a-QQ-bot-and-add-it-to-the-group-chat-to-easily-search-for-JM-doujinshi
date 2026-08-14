#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JM娘 升级应答器：部署窗口内 @JM娘 时回复"正在升级中，请稍后"
部署流程：JM娘 停机前启动本脚本（独占回复）→ 停机上传 → 启动 JM娘 → 关闭本脚本
用法：python3 maintain_reply.py   （前台运行，ctrl-c 或 kill 退出）
"""
import asyncio
import json
import sys
import time

import websockets

BOT_QQ = '2337295608'
WS_URL = 'ws://127.0.0.1:8081'
COOLDOWN = {}  # group_id -> 上次回复时间戳


def log(s):
    print(f'[maintain] {time.strftime("%H:%M:%S")} {s}', flush=True)


async def main():
    # 断开后带退避重连，直到被 deploy.py kill（部署窗口内始终有应答）
    while True:
        try:
            ws = await websockets.connect(WS_URL, max_size=8 * 1024 * 1024)
        except Exception as e:
            log(f'连接 8081 失败: {e!r}，5秒后重试')
            await asyncio.sleep(5)
            continue
        log('维护应答器已上线')
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get('post_type') != 'message':
                    continue
                if msg.get('message_type') != 'group':
                    continue
                group_id = msg.get('group_id')
                text = msg.get('raw_message') or ''
                mentioned = f'[CQ:at,qq={BOT_QQ}]' in text or f'@{BOT_QQ}' in text
                if not mentioned:
                    continue
                now = time.time()
                if group_id in COOLDOWN and now - COOLDOWN[group_id] < 10:
                    continue
                COOLDOWN[group_id] = now
                await ws.send(json.dumps({
                    'action': 'send_group_msg',
                    'params': {
                        'group_id': group_id,
                        'message': '🚧 正在升级中，请稍后～',
                    },
                }))
                log(f'回复 @ 于群 {group_id}')
        except Exception as e:
            log(f'连接中断: {e!r}，5秒后重连')
            await asyncio.sleep(5)


asyncio.run(main())
