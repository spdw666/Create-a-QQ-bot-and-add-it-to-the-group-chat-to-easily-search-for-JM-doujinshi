# -*- coding: utf-8 -*-
"""
JM娘 QQ机器人主程序
==========================================
功能：群里发一串数字（禁漫漫画ID），自动下载整本、打包ZIP、上传到群。

协议：OneBot v11（反向 WebSocket 服务端），配合 NapCat 使用。
配置：NapCat WebUI 中新增「OneBot 反向 WebSocket 服务端」，
      地址填 ws://127.0.0.1:8081，消息格式选 array 或 string 均可。

启动：python jm_niang.py
"""
import asyncio
import json
import os
import re
import secrets
import shutil
import sys
import time
import uuid

import websockets

from jm_download import (
    download_album_to_zip,
    find_cached_zip,
    get_album_info,
    get_random_hot_album,
    search_album,
    search_author_album,
    count_images,
    cleanup_old_dirs,
    cancel_download,
    cleanup_cancelled,
    DownloadCancelledError,
    CANCELLED_ALBUMS,
    DOWNLOAD_DIR,
    ZIP_ENCRYPT,
    ZIP_PASSWORD,
    is_zip_encrypted,
    ensure_encrypted_zip,
)

WS_HOST = '127.0.0.1'
WS_PORT = 8081

# 允许使用机器人的群白名单。空列表 = 所有群都能用。
# 想限制只让某个群使用，填群的数字ID，例如: ALLOWED_GROUPS = [123456789]
ALLOWED_GROUPS = []

# 同时允许的下载任务数（同时下载的本数），其余排队
# 3本同时下载易触发禁漫CDN限流(502)，默认2本
MAX_CONCURRENT_DOWNLOADS = 2
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# ---------- HTTP 下载链接分享配置 ----------
# 服务器公网IP与HTTP服务端口（腾讯云轻量控制台需放行该端口）
# 公网IP通过环境变量 JM_PUBLIC_IP 配置（不写死在代码里，避免泄露）
PUBLIC_IP = os.environ.get('JM_PUBLIC_IP', '127.0.0.1')
HTTP_PORT = 8080
HTTP_BASE_URL = f'http://{PUBLIC_IP}:{HTTP_PORT}'
# 分享目录（http.server 服务的根目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARE_DIR = os.path.join(BASE_DIR, 'http_dl')


# ---------------------------------------------------------------- 工具函数

def log(msg):
    print(f'[JM娘] {msg}', flush=True)


def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f'{size:.1f}{unit}'
        size /= 1024
    return f'{size:.1f}TB'


def escape_cq(text):
    """转义CQ码特殊字符，防止群成员通过关键词/标题构造 [CQ:...] 让机器人@全体/冒名发图"""
    return (str(text)
            .replace('&', '&amp;').replace('[', '&#91;').replace(']', '&#93;').replace(',', '&#44;')
            .replace('\n', ' '))


def zip_password_note(zip_path):
    """返回ZIP密码提示文案（仅当ZIP带密码时），用于群消息提示"""
    if ZIP_ENCRYPT and is_zip_encrypted(zip_path):
        return f'🔐 压缩包密码：{ZIP_PASSWORD}\n（需WinRAR/7-Zip/ZArchiver等支持加密ZIP的工具解压）'
    return ''


def publish_http_link(zip_path):
    """
    把ZIP复制到HTTP分享目录（随机token子目录），返回浏览器下载链接。
    失败返回 None（比如磁盘问题）。
    """
    try:
        token = secrets.token_hex(4)  # 8位随机token，防目录遍历/猜链接
        dest_dir = os.path.join(SHARE_DIR, token)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(zip_path))
        shutil.copy2(zip_path, dest)
        return f'{HTTP_BASE_URL}/{token}/{os.path.basename(zip_path)}'
    except Exception as e:
        log(f'发布HTTP链接失败: {e!r}')
        return None


# ---------------------------------------------------------------- 消息解析

# 使用说明（@机器人 + 说明/帮助/help 时发送）
HELP_TEXT = (
    '📖 JM娘 使用说明\n'
    '———————————————\n'
    '💡 触发方式：先 @我，再发送命令\n\n'
    '📥 下载漫画：@我 + 数字ID\n'
    '   例：@JM娘 1460484\n'
    '   （也支持 @JM娘 /jm1460484）\n'
    '   下载前会先告知页数和预计时间\n\n'
    '🛑 取消下载：@我 取消\n'
    '   （也支持：停止 / stop / 算了）\n'
    '   停止当前下载并清除已下载的缓存\n\n'
    '🎲 随机推荐：@我 随机\n'
    '   （也支持：抽一本 / 推荐 / 来一本）\n'
    '   从近30天最火的本子里随机抽一本推荐\n\n'
    '🔍 搜索：@我 + 关键词/本子名\n'
    '   例：@JM娘 人妻、@JM娘 枫与铃、@JM娘 琉璃川\n'
    '   返回最新 5 本（含ID）；自动匹配简体/繁体/日文写法\n'
    '   💡 结果超过5本时，直接发「下一页」翻页、「第N页」跳转（无需@）\n\n'
    '✍️ 作者搜索：@我 作者 + 名字\n'
    '   例：@JM娘 作者 きょくちょ\n'
    '   返回该作者最新的 5 本（含ID），同样支持翻页\n\n'
    '❓ 查看说明：@我 说明\n'
    '   （也支持：帮助 / help / 使用说明）\n\n'
    '⚠️ 温馨提示\n'
    '· 同时最多下载 2 本，多人请求会排队\n'
    '· 大本子需要较长时间，期间会汇报进度\n'
    '· 下载过的漫画会直接发送缓存\n'
    f'· 压缩包带密码：{ZIP_PASSWORD}\n'
    '  （需WinRAR/7-Zip/ZArchiver等支持加密ZIP的工具解压）\n'
    '· 数字ID可在禁漫网页/APP的漫画详情页找到'
)

# 说明类命令词
HELP_WORDS = {'说明', '帮助', 'help', '使用说明', 'usage', '菜单', '怎么用'}

# 取消类命令词
CANCEL_WORDS = {'取消', '停止', 'stop', 'cancel', '算了'}

# 随机推荐类命令词
RANDOM_WORDS = {'随机', '抽一本', '推荐', '来一本', '随缘', 'random'}

# 翻页命令词（支持免@：用户直接发「下一页」即可翻页；'继续'等宽泛词不收录，防普通聊天误触发）
NEXT_WORDS = {'下一页', '翻页', '下页', 'next'}

# 每群关键词搜索冷却（group_id -> 上次搜索时间戳）
SEARCH_COOLDOWN = {}


def search_cooldown_hit(group_id):
    """每群 10 秒冷却：随机推荐也走禁漫搜索接口，与关键词搜索共用冷却防刷"""
    now = time.monotonic()
    if now - SEARCH_COOLDOWN.get(group_id, 0) < 10:
        return True
    SEARCH_COOLDOWN[group_id] = now
    return False


# 搜索结果翻页状态（group_id -> {keyword, kind, head, results, page, ts}）
SEARCH_STATE = {}
SEARCH_STATE_TTL = 600  # 10分钟不翻页则过期
PAGE_SIZE = 5


def render_search_page(state, page):
    """渲染搜索结果第 page 页（1-based）的消息文本，末尾提示翻页/结束"""
    results = state['results']
    total = len(results)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * PAGE_SIZE
    lines = [f'{state["head"]}（第 {page}/{total_pages} 页 · 共 {total} 本）：']
    for i, r in enumerate(results[start:start + PAGE_SIZE], start + 1):
        lines.append(f'{i}. 《{escape_cq(r["title"])}》 章节：{r["chapter_count"]}章\n'
                     f'   🔢 ID：{r["id"]}')
    if page < total_pages:
        lines.append('💡 直接发「下一页」翻页，或发「第N页」跳转（无需@我）')
    else:
        lines.append('✅ 已查看完全部结果')
    return '\n'.join(lines)


async def handle_next_page(api, group_id, silent=False, page=None):
    """
    翻页/跳页：显示上一次搜索结果的下一页（page=None）或第 page 页。
    silent=True（免@触发）时无状态则静默忽略；跳转越界自动收敛到有效页。
    """
    state = SEARCH_STATE.get(group_id)
    if not state or time.time() - state['ts'] > SEARCH_STATE_TTL:
        SEARCH_STATE.pop(group_id, None)
        if not silent:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '📄 没有可翻页的搜索结果（请先搜索，或翻页状态已过期）'
            })
        return
    state['ts'] = time.time()  # 刷新有效期
    total_pages = max(1, (len(state['results']) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page is None:
        target = state['page'] + 1
        if target > total_pages:
            state['page'] = total_pages
            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'📄 已经是最后一页了，共 {len(state["results"])} 本'
            })
            return
    else:
        target = max(1, min(page, total_pages))  # 跳转越界收敛（第99页→最后一页）
    state['page'] = target
    await api('send_group_msg', {
        'group_id': group_id,
        'message': render_search_page(state, target)
    })

# 当前正在下载的 album_id 列表（下载开始append，结束remove；取消时取最近一个）
ACTIVE_DOWNLOADS = []

# 时间估算：每页下载耗时区间（秒），取决于代理带宽
SECONDS_PER_PAGE_MIN = 0.6
SECONDS_PER_PAGE_MAX = 1.5


def parse_group_message(msg, bot_qq):
    """
    解析群消息：是否 @了机器人 + 文本内容。

    :return: (是否@机器人, 纯文本)
    """
    at_me = False
    parts = []
    for seg in msg.get('message') or []:
        seg_type = seg.get('type')
        if seg_type == 'at':
            qq = str(seg.get('data', {}).get('qq', ''))
            if qq == str(bot_qq):
                at_me = True
        elif seg_type == 'text':
            parts.append(seg.get('data', {}).get('text', ''))
    return at_me, ''.join(parts).strip()


def extract_album_id(text: str):
    """从@后的文本中提取禁漫ID（纯数字 / /jm数字 / album链接），提取不到返回 None"""
    if not text:
        return None
    # 纯数字：@机器人后直接发数字（如 "1460484"）
    m = re.fullmatch(r'\s*(\d{5,9})\s*', text)
    if m:
        return m.group(1)
    # /jm数字（兼容旧命令）
    m = re.search(r'/jm\s*(\d{5,9})', text, re.IGNORECASE)
    if m:
        return m.group(1)
    # album 链接
    m = re.search(r'album/(\d{5,9})', text, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def extract_page(text: str):
    """提取页码跳转命令：'第2页' / '第 2 页' / '2页' → 2；否则 None"""
    if not text:
        return None
    m = re.fullmatch(r'第?\s*(\d{1,2})\s*页', text)
    return int(m.group(1)) if m else None


def extract_author(text: str):
    """提取作者搜索命令：'作者 xxx' / '作者:xxx' / 'author xxx' → 返回作者名，否则 None"""
    if not text:
        return None
    low = text.lower()
    for prefix in ('作者', 'author'):
        if low.startswith(prefix):
            rest = text[len(prefix):].strip(' :：、,，')
            return rest or None
    return None


# ---------------------------------------------------------------- 核心业务

async def monitor_progress(api, group_id, album_id, total_pages, download_task):
    """轮询下载目录汇报进度：有总页数按 25%/50%/75% 报百分比；拿不到页数则每30秒报绝对进度"""
    task_dir = os.path.join(DOWNLOAD_DIR, str(album_id))
    reported = set()
    thresholds = [25, 50, 75]
    last_abs_report = 0.0
    while not download_task.done():
        done = count_images(task_dir)
        now = time.monotonic()
        if total_pages > 0:
            pct = int(done * 100 / total_pages)
            for t in thresholds:
                if pct >= t and t not in reported:
                    reported.add(t)
                    try:
                        await api('send_group_msg', {
                            'group_id': group_id,
                            'message': f'⏳ 漫画 {album_id} 下载中… {pct}%（{done}/{total_pages}）'
                        })
                    except Exception:
                        pass
        elif now - last_abs_report >= 30:
            # 降级：拿不到总页数时，每30秒报一次已下载张数
            last_abs_report = now
            try:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'📥 漫画 {album_id} 下载中… 已下载 {done} 张图（本子较大请耐心等待）'
                })
            except Exception:
                pass
        await asyncio.sleep(5)


async def handle_jm_request(ws, api, group_id, user_id, album_id):
    """下载并上传一个漫画，负责回复群消息"""
    loop = asyncio.get_event_loop()
    try:
        # 1. 缓存命中则直接上传（旧缓存若未加密，现场转加密，否则QQ会拒收）
        cached_zip, cached_title = await loop.run_in_executor(None, find_cached_zip, album_id)
        if cached_zip:
            if ZIP_ENCRYPT:
                cached_zip = await loop.run_in_executor(None, ensure_encrypted_zip, cached_zip)
            if not cached_zip:
                raise RuntimeError(f'缓存ZIP加密转换失败: {album_id}')
            zip_path, title = cached_zip, cached_title
            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'📦 漫画 {album_id} 之前下载过，直接发送缓存：\n《{escape_cq(title)}》\n正在上传…'
            })
        else:
            # 2. 下载前预告：标题 / 章节数 / 页数 / 预计时间
            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'收到！正在获取漫画 {album_id} 的信息…'
            })
            info = await loop.run_in_executor(None, get_album_info, album_id)
            total_pages = info['page_count'] if info else 0
            if info:
                est_low = max(1, int(total_pages * SECONDS_PER_PAGE_MIN / 60))
                est_high = max(est_low + 1, int(total_pages * SECONDS_PER_PAGE_MAX / 60))
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'📋 漫画信息确认\n'
                               f'📕《{escape_cq(info["title"])}》\n'
                               f'📚 共 {info["chapter_count"]} 章 / {total_pages} 页\n'
                               f'⏱️ 预计下载 {est_low}-{est_high} 分钟（取决于网速）\n'
                               f'📦 下载完自动打包ZIP上传群文件\n'
                               f'❌ 不想要了？@我 发送「取消」'
                })
            else:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'开始下载漫画 {album_id}（获取信息失败，无预览）…'
                })

            # 3. 登记活跃任务，启动下载 + 进度轮询
            ACTIVE_DOWNLOADS.append(album_id)
            try:
                download_task = loop.create_task(
                    asyncio.to_thread(download_album_to_zip, album_id)
                )
                progress_task = loop.create_task(
                    monitor_progress(api, group_id, album_id, total_pages, download_task)
                )
                zip_path, title = await download_task
                await progress_task
            finally:
                if album_id in ACTIVE_DOWNLOADS:
                    ACTIVE_DOWNLOADS.remove(album_id)

            # 4. 下载期间被取消：清理残留并回复
            if album_id in CANCELLED_ALBUMS:
                await loop.run_in_executor(None, cleanup_cancelled, album_id)
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'🗑️ 漫画 {album_id} 已取消下载，缓存已清理'
                })
                return

            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'📦 下载完成，正在打包ZIP…'
            })

        size = os.path.getsize(zip_path)
        file_name = os.path.basename(zip_path)
        pwd_note = zip_password_note(zip_path)

        # 发布HTTP下载链接（无论群文件上传成败都发，双保险）
        http_url = await loop.run_in_executor(None, publish_http_link, zip_path)

        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'《{escape_cq(title)}》\n大小：{format_bytes(size)}\n正在上传到群文件…'
        })

        # 上传群文件（大文件可能较慢，给足超时；QQ偶发限流，自动重试5次）
        result = None
        last_err = ''
        for attempt in range(1, 6):
            try:
                result = await api('upload_group_file', {
                    'group_id': group_id,
                    'file': zip_path,
                    'name': file_name,
                }, timeout=1200)
            except asyncio.TimeoutError:
                last_err = '上传超时'
                result = None
            except Exception as e:
                last_err = str(e)
                result = None

            retcode = result.get('retcode') if result else None
            if retcode in (0, None):
                break
            last_err = (result.get('message') or result.get('wording') or '')[:200] or f'retcode={retcode}'
            log(f'上传失败(第{attempt}次): {last_err}，8秒后重试…')
            await asyncio.sleep(8)

        retcode = result.get('retcode') if result else None
        if retcode in (0, None):
            msg = f'✅ 已上传到群文件：{escape_cq(file_name)}\n（{format_bytes(size)}）'
        else:
            msg = f'⚠️ 群文件上传失败：{last_err or f"retcode={retcode}"}\n' \
                  f'QQ风控/文件过大常导致此问题，文件仍在服务器本地，可直接用下方浏览器链接下载'
        # 浏览器下载链接优先展示（不经过QQ审核，稳定可用）
        if http_url:
            msg += f'\n\n📎 浏览器直接下载：{escape_cq(http_url)}'
        if pwd_note:
            msg += f'\n\n{pwd_note}'
        await api('send_group_msg', {
            'group_id': group_id,
            'message': msg
        })

    except DownloadCancelledError:
        # 用户取消下载：清理残留目录
        await loop.run_in_executor(None, cleanup_cancelled, album_id)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🗑️ 漫画 {album_id} 已取消下载，缓存已清理'
        })
    except asyncio.TimeoutError:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'⏱️ 漫画 {album_id} 处理超时，请稍后重试。'
        })
    except Exception as e:
        log(f'处理 {album_id} 失败: {e!r}')
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'❌ 漫画 {album_id} 处理失败：{e}\n'
                       f'可能原因：ID不存在/已删除、网络波动、禁漫拦截。'
        })


async def handle_message(ws, api, msg, bot_qq):
    """处理一条消息事件"""
    if msg.get('message_type') != 'group':
        return  # 只处理群消息
    if msg.get('post_type') != 'message':
        return
    if not bot_qq:
        return  # 未获取到机器人QQ，无法判断@，忽略

    group_id = msg.get('group_id')
    user_id = msg.get('user_id')

    # 群白名单过滤
    if ALLOWED_GROUPS and group_id not in ALLOWED_GROUPS:
        return

    # 必须 @机器人 才响应
    at_me, text = parse_group_message(msg, bot_qq)
    if not at_me:
        # 翻页/跳页命令免@：直接发「下一页」或「第N页」，无需先@机器人；无状态则静默
        page_num = extract_page(text) if text else None
        if text and (text.lower() in NEXT_WORDS or page_num):
            await handle_next_page(api, group_id, silent=True, page=page_num)
        return
    log(f'收到群 {group_id} 用户 {user_id} 命令: {text[:40]!r}')

    # 说明命令：@机器人 + 说明/帮助/help 等
    if text.lower() in HELP_WORDS:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': HELP_TEXT
        })
        return

    # 取消命令：@机器人 + 取消/停止 等
    if text.lower() in CANCEL_WORDS:
        if ACTIVE_DOWNLOADS:
            target = ACTIVE_DOWNLOADS[-1]  # 取消最近开始的任务
            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'🛑 正在取消下载 {target}，已下载的缓存将一并清除…'
            })
            await asyncio.to_thread(cancel_download, target)
        else:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '✅ 当前没有正在下载的任务'
            })
        return

    # 随机推荐：@机器人 + 随机/抽一本 等 → 近30天热门随机一本
    if text.lower() in RANDOM_WORDS:
        if search_cooldown_hit(group_id):
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '⏳ 搜索太快啦，等几秒再试试～'
            })
            return
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '🎲 正在从近30天最火的本子里随机抽一本，稍等…'
        })
        info = await asyncio.to_thread(get_random_hot_album)
        if not info:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '❌ 随机推荐失败（网络波动或禁漫拦截），稍后再试试～'
            })
            return
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🎲 随机推荐（近30天热门）\n'
                       f'📕《{escape_cq(info["title"])}》\n'
                       f'✍️ 作者：{escape_cq(info["author"])}\n'
                       f'📚 共 {info["chapter_count"]} 章\n'
                       f'🔢 ID：{info["id"]}\n'
                       f'📎 https://18comic.vip/album/{info["id"]}\n'
                       f'想要？@我 + 发送这个ID 即可打包下载'
        })
        return

    # 翻页/跳页：@机器人 + 下一页/翻页/第N页（也支持免@直接发）
    page_num = extract_page(text)
    if text.lower() in NEXT_WORDS or page_num:
        await handle_next_page(api, group_id, page=page_num)
        return

    # 作者搜索：@机器人 + 作者 + 名字 → 该作者的本子
    author = extract_author(text)
    if author:
        if search_cooldown_hit(group_id):
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '⏳ 搜索太快啦，等几秒再试试～'
            })
            return
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🔍 正在搜索作者「{escape_cq(author)}」的本子，稍等…'
        })
        results = await asyncio.to_thread(search_author_album, author, 200)
        if results is None:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '❌ 搜索失败（网络波动或禁漫拦截），稍后再试试～'
            })
            return
        if not results:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '没有找到该作者所对应的本子'
            })
            return
        # 清理过期翻页状态（群数量有限，全量扫描）
        now = time.time()
        for gid in [g for g, s in SEARCH_STATE.items() if now - s['ts'] > SEARCH_STATE_TTL]:
            SEARCH_STATE.pop(gid, None)
        SEARCH_STATE[group_id] = {
            'head': f'✍️ 作者「{escape_cq(author)}」的本子',
            'results': results, 'page': 1, 'ts': now,
        }
        await api('send_group_msg', {
            'group_id': group_id,
            'message': render_search_page(SEARCH_STATE[group_id], 1)
        })
        return

    # 下载命令：@机器人 + /jm数字
    album_id = extract_album_id(text)
    if album_id:
        log(f'群 {group_id} 用户 {user_id} 请求下载: {album_id}')

        # 排队通知（同时最多 MAX_CONCURRENT_DOWNLOADS 本在下载）
        if SEMAPHORE.locked():
            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'📥 下载任务较多，漫画 {album_id} 已加入队列，请稍等…'
            })

        async with SEMAPHORE:
            await handle_jm_request(ws, api, group_id, user_id, album_id)
        return

    # 关键词搜索：@机器人 + 关键词 → 返回前5本（ID列表）
    if text:
        # 每群冷却10秒，防刷搜索（ponytail: SEARCH_COOLDOWN 进程内增长不清理，群数量有限可接受）
        if search_cooldown_hit(group_id):
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '⏳ 搜索太快啦，等几秒再试试～'
            })
            return

        keyword = text[:50]  # 名称可较长；截断防超长消息，与 search_album 清洗一致
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🔍 正在搜索关键词「{escape_cq(keyword)}」，稍等…'
        })
        results = await asyncio.to_thread(search_album, keyword, 200)
        if results is None:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '❌ 搜索失败（网络波动或禁漫拦截），稍后再试试～'
            })
            return
        if not results:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '没有找到该关键词所对应的本子'
            })
            return
        # 清理过期翻页状态（群数量有限，全量扫描）
        now = time.time()
        for gid in [g for g, s in SEARCH_STATE.items() if now - s['ts'] > SEARCH_STATE_TTL]:
            SEARCH_STATE.pop(gid, None)
        SEARCH_STATE[group_id] = {
            'head': f'🔍 关键词「{escape_cq(keyword)}」',
            'results': results, 'page': 1, 'ts': now,
        }
        await api('send_group_msg', {
            'group_id': group_id,
            'message': render_search_page(SEARCH_STATE[group_id], 1)
        })


# ---------------------------------------------------------------- WS 服务

async def handle_connection(ws):
    """WS连接处理：reader 后台任务统一消费数据，api() 匹配 echo 响应，事件分发给处理函数"""
    pending: dict = {}
    bot_qq_box = [None]  # 可变容器，reader 闭包读取
    log(f'NapCat 已连接: {ws.remote_address}')

    async def api(action, params=None, timeout=60):
        echo = str(uuid.uuid4())
        fut = asyncio.get_event_loop().create_future()
        pending[echo] = fut
        await ws.send(json.dumps({'action': action, 'params': params or {}, 'echo': echo}))
        return await asyncio.wait_for(fut, timeout)

    async def reader():
        """统一消费 WS 数据：匹配 API 响应 / 分发事件"""
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if 'echo' in msg and msg['echo'] in pending:
                fut = pending.pop(msg['echo'])
                if not fut.done():
                    fut.set_result(msg)
            elif msg.get('post_type') == 'message':
                asyncio.create_task(handle_message(ws, api, msg, bot_qq_box[0]))
            elif msg.get('post_type') == 'meta_event' and msg.get('meta_event_type') == 'heartbeat':
                pass  # 心跳忽略

    reader_task = asyncio.create_task(reader())

    # 获取机器人自身QQ（用于判断是否被@）；reader 已运行，响应可被消费
    try:
        info = await api('get_login_info', {}, timeout=10)
        bot_qq_box[0] = str((info.get('data') or {}).get('user_id') or '')
        if bot_qq_box[0]:
            log(f'机器人QQ: {bot_qq_box[0]}')
        else:
            log('获取机器人QQ为空，@ 判断将不可用')
    except Exception as e:
        log(f'获取机器人QQ失败: {e!r}，@ 判断将不可用')

    try:
        await reader_task
    finally:
        for fut in pending.values():
            if not fut.done():
                fut.cancel()
        log('NapCat 连接断开')


async def cleanup_task():
    """每天清理一次超过 7 天的下载目录和HTTP分享文件"""
    while True:
        try:
            await asyncio.to_thread(cleanup_old_dirs, DOWNLOAD_DIR, 7)
            await asyncio.to_thread(cleanup_old_dirs, SHARE_DIR, 7, False)
        except Exception as e:
            log(f'清理任务出错: {e!r}')
        await asyncio.sleep(24 * 3600)


async def main():
    uri = f'ws://{WS_HOST}:{WS_PORT}'
    log(f'JM娘 启动，连接 NapCat 正向WS服务: {uri} …')
    asyncio.create_task(cleanup_task())  # 后台定时清理
    # 断线自动重连
    while True:
        try:
            async with websockets.connect(uri, ping_interval=None) as ws:
                await handle_connection(ws)
        except Exception as e:
            log(f'连接断开/失败: {e!r}，5秒后重连…')
            await asyncio.sleep(5)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\nJM娘 已停止')
