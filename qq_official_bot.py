# -*- coding: utf-8 -*-
"""
JM娘 官方机器人接入（QQ 开放平台 WebSocket 网关模式）

职责（与 NapCat 个人号分工）：
  - 收到 @官方JM娘（不带命令）→ 回复「按钮菜单」（markdown + 自定义 keyboard 按钮）
  - 轻量命令：随机 / 今日属性 / 日榜/周榜/月榜 / 搜索 / 作者 / 标签 / 详情 / 说明
  - 下载类命令（/jm数字）→ 提示"下载请发到群，由个人号 JM娘 处理"

依赖 jm_download.py 的搜索/榜单/随机函数（只查禁漫 API 返回文字，不依赖 NapCat）。

凭证从环境变量读取：QQ_APP_ID / QQ_APP_SECRET
"""
import asyncio
import json
import os
import time
import urllib.request

import jm_download
from jm_download import (
    search_album, search_author_album, search_tag_album,
    get_ranking, get_random_hot_album, get_random_tag_album, get_album_info,
)

# ---------------------------------------------------------------------------
# 配置（环境变量）
# ---------------------------------------------------------------------------
APP_ID = os.environ.get('QQ_APP_ID', '1905444742')
APP_SECRET = os.environ.get('QQ_APP_SECRET', '')

TOKEN_URL = 'https://bots.qq.com/app/getAppAccessToken'
API_BASE = 'https://api.sgroup.qq.com'  # 生产环境
GATEWAY_PATH = '/gateway'

# Intents：需要收「群聊 @ 消息」和「C2C 私聊」，频道私信
# GROUP_AND_C2C_EVENT = 1<<25，DIRECT_MESSAGE = 1<<12，GUILDS=1<<0，GUILD_MEMBERS=1<<1
INTENTS = (1 << 25) | (1 << 12) | (1 << 0) | (1 << 1) | (1 << 30)

# ---------------------------------------------------------------------------
# Token 管理（缓存 + 自动刷新，60 秒提前刷新）
# ---------------------------------------------------------------------------
_access_token = None
_token_expires_at = 0.0
_token_lock = asyncio.Lock()


def _http_json(url, data=None, headers=None, method=None, timeout=30):
    """同步 HTTP 请求，返回 JSON dict"""
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ('POST' if data is not None else 'GET'))
    req.add_header('Content-Type', 'application/json')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode('utf-8')
    return json.loads(raw) if raw else {}


async def _ensure_token():
    """返回有效 access_token（缓存 + 单飞刷新）"""
    global _access_token, _token_expires_at
    if _access_token and time.time() < _token_expires_at - 60:
        return _access_token
    async with _token_lock:
        if _access_token and time.time() < _token_expires_at - 60:
            return _access_token
        data = await asyncio.to_thread(
            _http_json, TOKEN_URL, {'appId': APP_ID, 'clientSecret': APP_SECRET}
        )
        token = data.get('access_token')
        if not token:
            raise RuntimeError(f'token 获取失败: {data.get("message", "未知错误")}')
        _access_token = token
        _token_expires_at = time.time() + int(data.get('expires_in', 7200))
        log = lambda msg: print(msg, flush=True)
        log(f'[token] 已刷新 access_token，过期时间 {_token_expires_at - time.time():.0f}s 后')
        return _access_token


# ---------------------------------------------------------------------------
# 出站：发群消息 / 私聊消息（REST API）
# ---------------------------------------------------------------------------
# 按钮菜单（自定义 keyboard，无需模板）
_BUTTON_ROWS = [
    [
        {'id': 'b_random', 'render_data': {'label': '🐲 随机', 'visited_label': '随机', 'style': 1},
         'action': {'type': 2, 'permission': {'type': 2}, 'data': '随机', 'reply': True, 'unsupport_tips': '请更新QQ版本'}},
        {'id': 'b_today', 'render_data': {'label': '🎭 今日属性', 'visited_label': '今日属性', 'style': 1},
         'action': {'type': 2, 'permission': {'type': 2}, 'data': '今日属性', 'reply': True, 'unsupport_tips': '请更新QQ版本'}},
    ],
    [
        {'id': 'b_day', 'render_data': {'label': '📊 日榜', 'visited_label': '日榜', 'style': 1},
         'action': {'type': 2, 'permission': {'type': 2}, 'data': '日榜', 'reply': True, 'unsupport_tips': '请更新QQ版本'}},
        {'id': 'b_week', 'render_data': {'label': '周榜', 'visited_label': '周榜', 'style': 1},
         'action': {'type': 2, 'permission': {'type': 2}, 'data': '周榜', 'reply': True, 'unsupport_tips': '请更新QQ版本'}},
        {'id': 'b_month', 'render_data': {'label': '月榜', 'visited_label': '月榜', 'style': 1},
         'action': {'type': 2, 'permission': {'type': 2}, 'data': '月榜', 'reply': True, 'unsupport_tips': '请更新QQ版本'}},
    ],
    [
        {'id': 'b_help', 'render_data': {'label': '📖 说明', 'visited_label': '说明', 'style': 0},
         'action': {'type': 2, 'permission': {'type': 2}, 'data': '说明', 'reply': True, 'unsupport_tips': '请更新QQ版本'}},
    ],
]

BUTTON_MENU_MARKDOWN = (
    '# 🎛️ JM娘 命令面板\n'
    '点下方按钮，会自动填入命令（群聊需再按一下发送）\n\n'
    '**轻量功能**（官方机器人直接回复）\n'
    '- 随机 / 今日属性 / 日榜 / 周榜 / 月榜\n'
    '- 搜索：@我 + 关键词\n'
    '- 作者 / 标签 / 详情 / 说明\n\n'
    '**下载功能**（走 NapCat 个人号）\n'
    '- 发送 `/jm<ID>` 到群里\n'
    '- 由群里的个人号 JM娘 处理下载\n'
)


def _button_payload(rows):
    return {'content': {'rows': [{'buttons': row} for row in rows]}}


# ---------------------------------------------------------------------------
# 命令处理
# ---------------------------------------------------------------------------
def _fmt_search(results, head):
    if results is None:
        return '❌ 搜索失败（网络波动或禁漫拦截），稍后再试试～'
    if not results:
        return '没有找到对应的本子'
    lines = [f'{head}：']
    for i, r in enumerate(results[:5], 1):
        chap = f' 章节：{r["chapter_count"]}章' if r.get('chapter_count') else ''
        lines.append(f'{i}. 《{r["title"]}》{chap}\n   🔢 ID：{r["id"]}')
    lines.append('想要下载？发送 /jm<ID> 到群（由个人号 JM娘 处理）')
    return '\n'.join(lines)


def _fmt_random(info):
    if not info:
        return '❌ 随机推荐失败，稍后再试试～'
    return (f'🎲 随机推荐（近30天热门）\n'
            f'📕《{info["title"]}》\n'
            f'✍️ 作者：{info["author"] or "未知"}\n'
            f'📚 共 {info["chapter_count"]} 章\n'
            f'🔢 ID：{info["id"]}\n'
            f'想要？发送 /jm{info["id"]} 到群（由个人号 JM娘 处理）')


def _fmt_today(info):
    if not info:
        return '❌ 占卜失败，稍后再试试～'
    return (f'🎭 今日你的属性是【{info["tag"]}】！\n'
            f'📕 附赠《{info["title"]}》\n'
            f'🔢 ID：{info["id"]}\n'
            f'想要？发送 /jm{info["id"]} 到群')


def _fmt_rank(text, results):
    if results is None:
        return '❌ 获取榜单失败，稍后再试试～'
    if not results:
        return '榜单暂无数据'
    lines = [f'📊 {text}（前5）：']
    for i, r in enumerate(results[:5], 1):
        lines.append(f'{i}. 《{r["title"]}》🔢 {r["id"]}')
    return '\n'.join(lines)


def process_command(text):
    """处理一条命令文本，返回 (is_menu, reply_text)"""
    text = (text or '').strip()
    low = text.lower()

    # 纯 @ / 菜单 / 按钮 → 按钮菜单
    if not text or low in ('菜单', '按钮', '面板', '说明', '帮助', 'help', 'menu'):
        return True, None  # is_menu=True，回复按钮菜单

    # 随机
    if low in ('随机', '推荐', '抽一本', '来一本', '随缘', 'random') or low.startswith('随机'):
        return False, _fmt_random(get_random_hot_album())

    # 今日属性
    if low in ('今日属性', '属性', 'today'):
        return False, _fmt_today(get_random_tag_album())

    # 榜单
    rank_map = {'日榜': 'day', '周榜': 'week', '月榜': 'month',
                'day': 'day', 'week': 'week', 'month': 'month'}
    if low in rank_map:
        rt = rank_map[low]
        cn = {'day': '日榜', 'week': '周榜', 'month': '月榜'}[rt]
        return False, _fmt_rank(cn, get_ranking(rt))

    # 标签搜索
    if low.startswith('标签') or low.startswith('tag '):
        tag = low.replace('标签', '').replace('tag', '').strip().lstrip('：: ').strip()
        if tag:
            return False, _fmt_search(search_tag_album(tag, 5), f'🏷️ 标签「{tag}」')

    # 作者搜索
    if low.startswith('作者') or low.startswith('author '):
        author = low.replace('作者', '').replace('author', '').strip().lstrip('：: ').strip()
        if author:
            return False, _fmt_search(search_author_album(author, 5), f'✍️ 作者「{author}」')

    # 详情
    if low.startswith('详情') or low.startswith('预览') or low.startswith('detail'):
        rest = low.replace('详情', '').replace('预览', '').replace('detail', '').strip().lstrip('：: ').strip()
        m = __import__('re').fullmatch(r'(\d{5,9})', rest)
        if m:
            info = get_album_info(m.group(1))
            if info:
                tags = ', '.join(str(t) for t in (info.get('tags') or [])[:8])
                return False, (f'📕《{info["title"]}》\n'
                               f'✍️ 作者：{info.get("author") or "未知"}\n'
                               f'🏷️ 标签：{tags or "无"}\n'
                               f'📚 共 {info["chapter_count"]} 章 / {info["page_count"]} 页\n'
                               f'💾 下载：发送 /jm{m.group(1)} 到群')
            return False, f'❌ 获取漫画 {m.group(1)} 信息失败'

    # 下载类：/jm数字 或纯数字
    m = __import__('re').search(r'/jm\s*(\d{5,9})', low) or __import__('re').fullmatch(r'(\d{5,9})', low)
    if m:
        aid = m.group(1)
        return False, f'📥 下载功能由个人号 JM娘 处理：\n请在群里发送 `/jm{aid}`（@个人号 2337295608），即可打包下载。'

    # 关键词搜索（兜底）
    return False, _fmt_search(search_album(text[:50], 5), f'🔍 关键词「{text[:50]}」')


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
async def main():
    token = await _ensure_token()
    # 获取网关地址
    gw = await asyncio.to_thread(
        _http_json, f'{API_BASE}{GATEWAY_PATH}',
        headers={'Authorization': f'QQBot {token}', 'X-Union-Appid': APP_ID}, method='GET'
    )
    ws_url = gw.get('url')
    print(f'[gateway] {ws_url}', flush=True)

    import websockets
    async with websockets.connect(ws_url) as ws:
        # 收 Hello (op=10) 拿心跳周期
        seq = None
        session_id = None
        heartbeat_interval = 41250

        # 先收 Hello
        raw = await ws.recv()
        hello = json.loads(raw)
        if hello.get('op') == 10:
            heartbeat_interval = hello['d'].get('heartbeat_interval', 41250)

        # 发 Identify (op=2)
        identify = {
            'op': 2,
            'd': {
                'token': f'QQBot {token}',
                'intents': INTENTS,
                'shard': [0, 1],
                'properties': {'$os': 'linux', '$browser': 'jmniang', '$device': 'jmniang'},
            }
        }
        await ws.send(json.dumps(identify))
        print('[ws] 已发送 Identify', flush=True)

        async def send_heartbeat():
            while True:
                await asyncio.sleep(heartbeat_interval / 1000)
                try:
                    await ws.send(json.dumps({'op': 1, 'd': seq}))
                except Exception:
                    break

        hb_task = asyncio.create_task(send_heartbeat())

        async def handle_message_event(d):
            nonlocal token
            # 群聊 @ 消息
            group_openid = d.get('group_openid') or d.get('group_id')
            user_openid = d.get('author', {}).get('user_openid') or d.get('user_openid')
            content = d.get('content', '')
            msg_id = d.get('id')
            timestamp = d.get('timestamp')

            # 处理命令
            is_menu, reply = process_command(content)

            token = await _ensure_token()
            headers = {'Authorization': f'QQBot {token}', 'X-Union-Appid': APP_ID,
                       'Content-Type': 'application/json'}

            if is_menu:
                # 发按钮菜单：markdown + keyboard
                body = {
                    'msg_type': 2,
                    'msg_id': msg_id,
                    'content': ' ',
                    'markdown': {'content': BUTTON_MENU_MARKDOWN},
                    'keyboard': _button_payload(_BUTTON_ROWS),
                }
                url = f'{API_BASE}/v2/groups/{group_openid}/messages'
            else:
                body = {
                    'msg_type': 0,
                    'msg_id': msg_id,
                    'content': reply,
                }
                url = f'{API_BASE}/v2/groups/{group_openid}/messages'

            try:
                await asyncio.to_thread(_http_json, url, body, headers, 'POST')
                print(f'[reply] -> {content[:30]!r}', flush=True)
            except Exception as e:
                print(f'[reply-error] {e!r}', flush=True)

        async def handle_c2c(d):
            # 私聊消息：简单回按钮菜单
            user_openid = d.get('author', {}).get('user_openid')
            if not user_openid:
                return
            token = await _ensure_token()
            headers = {'Authorization': f'QQBot {token}', 'X-Union-Appid': APP_ID,
                       'Content-Type': 'application/json'}
            body = {'msg_type': 0, 'content': '发「说明」查看功能，或发关键词/ID。下载请用群里个人号。',
                    'msg_id': d.get('id')}
            url = f'{API_BASE}/v2/users/{user_openid}/messages'
            try:
                await asyncio.to_thread(_http_json, url, body, headers, 'POST')
            except Exception as e:
                print(f'[c2c-error] {e!r}', flush=True)

        # 事件循环
        async for message in ws:
            try:
                data = json.loads(message)
            except Exception:
                continue
            op = data.get('op')
            if op == 0:
                seq = data.get('s')
                t = data.get('t')
                d = data.get('d', {})
                if t == 'READY':
                    session_id = d.get('session_id')
                    print(f'[ready] session={session_id}', flush=True)
                elif t == 'GROUP_AT_MESSAGE_CREATE':
                    await handle_message_event(d)
                elif t == 'C2C_MESSAGE_CREATE':
                    await handle_c2c(d)
                elif t == 'GROUP_MESSAGE_CREATE':
                    # 全量群消息（若开了权限），也当 @ 处理
                    await handle_message_event(d)
            elif op == 11:
                pass  # heartbeat ack
            elif op == 7:
                print('[ws] 需重连 (op=7)', flush=True)
                break
            elif op == 9:
                print('[ws] 鉴权失败 (op=9)，token 可能过期', flush=True)
                break

        hb_task.cancel()


if __name__ == '__main__':
    if not APP_SECRET:
        print('错误：请设置环境变量 QQ_APP_SECRET')
        raise SystemExit(1)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
