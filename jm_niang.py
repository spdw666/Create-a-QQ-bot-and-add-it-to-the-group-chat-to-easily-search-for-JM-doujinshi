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
import socket
import sys
import time
import uuid
import datetime

import websockets

from jm_store import (
    add_subscription,
    cancel_job_by_prefix,
    cancel_latest_active_job,
    count_active_jobs,
    create_job,
    decode_subscription_json,
    get_job,
    get_job_by_recent_index,
    get_store_stats,
    list_jobs,
    list_all_subscriptions,
    list_active_jobs_all,
    list_subscriptions,
    remove_subscription_by_recent_index,
    set_subscription_cadence,
    update_job,
    update_subscription_state,
)

from jm_download import (
    download_album_to_zip,
    find_cached_zip,
    get_album_info,
    get_album_chapters,
    get_random_hot_album,
    get_random_tag_album,
    search_album,
    search_author_album,
    search_tag_album,
    get_ranking,
    search_by_image,
    search_by_image_deep,
    count_images,
    cleanup_old_dirs,
    download_album_chapters_to_zip,
    split_zip_for_delivery,
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
FIRST_CONNECTION = True  # 首次连接不发恢复通知，重连才发
START_TIME = time.time()  # 进程启动时刻（自查命令用）
CUR_CONN_TIME = None  # 当前 NapCat WS 连接建立时刻（自查命令用）

# 允许使用机器人的群白名单。空列表 = 所有群都能用。
# 想限制只让某个群使用，填群的数字ID，例如: ALLOWED_GROUPS = [123456789]
ALLOWED_GROUPS = []

# 同时允许的下载任务数（同时下载的本数），其余排队
# 3本同时下载易触发禁漫CDN限流(502)，默认2本
MAX_CONCURRENT_DOWNLOADS = 2
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
DOWNLOAD_QUEUE = 0  # 当前排队等待的任务数（排队位置提示用）
ACTIVE_TASKS = {}  # 正在处理的任务状态：album_id -> {phase, done, total}（排队告知用）
# 单个用户至多一项执行中和一项等待任务，避免一个人占满全局下载槽位。
MAX_ACTIVE_JOBS_PER_USER = 2
ADMIN_USERS = {value.strip() for value in os.environ.get('JM_ADMIN_USERS', '').split(',') if value.strip()}
QUEUE_PAUSED = False
QUEUE_RESUME_EVENT = asyncio.Event()
QUEUE_RESUME_EVENT.set()

# ---------- HTTP 下载链接分享配置 ----------
# 服务器公网IP与HTTP服务端口（腾讯云轻量控制台需放行该端口）
# 公网IP通过环境变量 JM_PUBLIC_IP 配置（不写死在代码里，避免泄露）
PUBLIC_IP = os.environ.get('JM_PUBLIC_IP', '127.0.0.1')
HTTP_PORT = 8080
HTTP_BASE_URL = f'http://{PUBLIC_IP}:{HTTP_PORT}'
# 分享目录（http.server 服务的根目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARE_DIR = os.path.join(BASE_DIR, 'http_dl')

# 禁漫天堂 APP 安装包（用户发"安装包"等关键词时加密上传到群文件）
APK_DIR = os.path.join(BASE_DIR, 'apk')
APK_FILE = '禁漫天堂APP.apk'
APK_URLS = (
    'https://github.com/hect0x7/JMComic-APK/releases/download/2.0.33/2.0.33.apk',  # GitHub 官方发布（主用）
    'https://18comic.vip/static/apk/2.0.33.apk',      # 官网直链（备用，可能反爬403）
)
JM_PROXY = os.environ.get('JM_PROXY', '').strip()  # 可选 HTTP 代理（下载 APK 用）


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
        # 文件名含 ❤️/[ ]/中文 等字符会被 QQ 客户端截断链接导致 404，用安全短名
        m = re.match(r'\[JM(\d+)\]', os.path.basename(zip_path))
        short_name = f'JM{m.group(1)}.zip' if m else f'{token}.zip'
        dest = os.path.join(dest_dir, short_name)
        shutil.copy2(zip_path, dest)
        return f'{HTTP_BASE_URL}/{token}/{short_name}'
    except Exception as e:
        log(f'发布HTTP链接失败: {e!r}')
        return None


# ---------------------------------------------------------------- 消息解析

# 使用说明（@机器人 + 说明/帮助/help 时发送）
HELP_TEXT = (
    '📖 JM娘 使用说明\n'
    '———————————————\n'
    '💡 触发方式：只 @我（不带命令）= 弹出按钮菜单；或 @我 + 命令\n\n'
    '📥 下载漫画：@我 + 数字ID\n'
    '   例：@JM娘 1460484\n'
    '   （也支持 @JM娘 /jm1460484）\n'
    '   下载前会先告知页数和预计时间\n\n'
    '📚 指定章节：@我 下载 JM123456 第2-5章\n'
    '   或：@我 下载 JM123456 最新\n\n'
    '🛑 取消下载：@我 取消\n'
    '   （也支持：停止 / stop / 算了）\n'
    '   停止当前下载并清除已下载的缓存\n\n'
    '📋 查看任务：@我 任务\n'
    '   查看正在处理的任务及预计剩余时间\n\n'
    '🧾 我的下载：@我 我的下载 / 我的任务\n'
    '   查看你自己的下载历史与当前任务（机器人重启后仍保留）\n'
    '   @我 重发 1 可重新处理第 1 条记录\n\n'
    '⭐ 收藏订阅：@我 收藏 JM123456 / 订阅作者 名字 / 订阅标签 标签\n'
    '   @我 我的收藏 · 取消收藏 1 · 订阅设置 每周\n\n'
    '🔍 自查：@我 自查\n'
    '   查看运行时长与当前连接状态\n\n'
    '🎲 随机推荐：@我 随机\n'
    '   （也支持：抽一本 / 推荐 / 来一本）\n'
    '   从近30天最火的本子里随机抽一本推荐\n\n'
    '📱 安装包：@我 安装包\n'
    '   （也支持：禁漫 / 禁漫天堂 / 禁漫安装包 / 天堂安装包 / jm安装包 / jm2安装包 / jm3安装包）\n'
    '   发送禁漫天堂 APP 安装包（加密ZIP+密码）\n\n'
    '🎭 今日属性：@我 今日属性\n'
    '   随机占卜你的今日属性（NTR/纯爱等标签）\n'
    '   并附赠一本对应标签的本子（含ID）\n\n'
    '🔍 搜索：@我 + 关键词/本子名\n'
    '   例：@JM娘 人妻、@JM娘 枫与铃、@JM娘 琉璃川\n'
    '   返回最新 5 本（含ID）；自动匹配简体/繁体/日文写法\n'
    '   💡 结果超过5本时，直接发「下一页」翻页、「第N页」跳转（无需@）\n\n'
    '✍️ 作者搜索：@我 作者 + 名字\n'
    '   例：@JM娘 作者 きょくちょ\n'
    '   返回该作者最新的 5 本（含ID），同样支持翻页\n\n'
    '🏷️ 标签搜索：@我 标签 + 标签名\n'
    '   例：@JM娘 标签 人妻\n'
    '   返回该标签最新的 5 本（含ID），支持翻页\n\n'
    '📋 详情预览：@我 详情 + ID\n'
    '   例：@JM娘 详情 350234\n'
    '   查看标题/作者/标签/章节页数（纯文字）\n\n'
    '📊 排行榜：@我 日榜/周榜/月榜\n'
    '   返回榜单前 5 本（含ID），支持翻页\n\n'
    '🔎 以图搜本：@我 + [发送图片]\n'
    '   或 @我 识图 → 20秒内直接发图（无需再@）\n'
    '   识图反查本子出处，并尝试在禁漫匹配同款\n\n'
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

# 按钮式命令菜单（@我 菜单 / 按钮 时返回）。NapCat/OneBot v11 协议不支持可点击按钮，
# 这里做成"按钮网格"清单：无参数功能直接发按钮词（免@），带参数功能照抄按钮上的格式 @我 即可。
BUTTON_MENU = (
    '🎛️ JM娘 命令面板（点下方按钮词，直接在群里发送即可）\n'
    '————————————————\n\n'
    '🟦 直接发送 · 无需@我\n'
    '   〔随机〕〔今日属性〕〔日榜〕〔周榜〕\n'
    '   〔月榜〕〔安装包〕〔任务〕〔自查〕\n\n'
    '🟩 需@我 + 参数\n'
    '   〔下载〕@我 + 数字ID\n'
    '   〔搜索〕@我 + 关键词\n'
    '   〔作者〕@我 作者 + 名字\n'
    '   〔标签〕@我 标签 + 名称\n'
    '   〔详情〕@我 详情 + ID\n'
    '   〔序号操作〕@我 下载 3 / 详情 3\n'
    '   〔识图〕@我 识图 → 20秒内发图\n\n'
    '🟨 其他\n'
    '   〔菜单〕@我 菜单 · 〔说明〕@我 说明\n'
    '   搜索超过5本：直接发〔下一页〕/〔第3页〕翻页\n'
    '   我的记录：@我 我的下载 / 我的任务\n'
    '   收藏订阅：@我 收藏 JM123456 / 我的收藏\n'
    '   取消下载：@我 取消\n'
    f'   🔐 压缩包密码：{ZIP_PASSWORD}\n'
)

# 菜单命令词（@我 菜单/按钮 → 返回 BUTTON_MENU）
MENU_WORDS = {'菜单', '按钮', '面板', 'menu', 'button'}

# 说明类命令词
HELP_WORDS = {'说明', '帮助', 'help', '使用说明', 'usage', '怎么用'}

# 取消类命令词
CANCEL_WORDS = {'取消', '停止', 'stop', 'cancel', '算了'}

# 随机推荐类命令词
RANDOM_WORDS = {'随机', '抽一本', '推荐', '来一本', '随缘', 'random', '随机推荐', '随机来一本'}

# 安装包类命令词
INSTALL_WORDS = {'jm2安装包', 'jm安装包', 'jm3安装包', '安装包', '禁漫', '禁漫天堂', '禁漫安装包', '天堂安装包'}

# 今日属性命令词
TAG_WORDS = {'今日属性', '属性', 'today'}

# 排行榜命令词
RANK_WORDS = {'日榜', '周榜', '月榜', 'day', 'week', 'month'}

# 任务查询命令词（@机器人 任务 → 查看当前处理中任务及预计时间）
TASK_WORDS = {'任务', '队列', '排队', 'task', 'queue'}

# 个人任务与下载历史（按“群 + 用户”隔离，重启后仍可查看）
MY_TASK_WORDS = {'我的任务', '我的下载', '下载历史', '我的历史'}
RESEND_RE = re.compile(r'^\s*重发\s*(\d{1,2})\s*$')

# 收藏/订阅：默认周报，后台每小时检查一次变化并聚合到到期摘要中。
FAVORITE_RE = re.compile(r'^\s*收藏\s*(.+?)\s*$')
SUBSCRIBE_AUTHOR_RE = re.compile(r'^\s*订阅作者\s+(.+?)\s*$')
SUBSCRIBE_TAG_RE = re.compile(r'^\s*订阅标签\s+(.+?)\s*$')
UNSUBSCRIBE_RE = re.compile(r'^\s*(?:取消收藏|取消订阅)\s*(\d{1,2})\s*$')
SUBSCRIPTION_SETTING_RE = re.compile(r'^\s*订阅设置\s*(每日|每天|每周)\s*$')
MY_FAVORITE_WORDS = {'我的收藏', '我的订阅', '订阅列表'}
SUBSCRIPTION_CHECK_SECONDS = int(os.environ.get('JM_SUBSCRIPTION_CHECK_SECONDS', '3600'))
SUBSCRIPTION_CADENCE_SECONDS = {'daily': 86400, 'weekly': 7 * 86400}

# 自查命令词（@机器人 自查 → 报告运行时长与连接状态）
SELF_CHECK_WORDS = {'自查'}

# 翻页命令词（支持免@：用户直接发「下一页」即可翻页；'继续'等宽泛词不收录，防普通聊天误触发）
NEXT_WORDS = {'下一页', '翻页', '下页', 'next'}

# 重新搜索命令词（@触发：对上次搜索结果不满意时重搜）
RETRY_WORDS = {'不对', '重新搜', '错了', '重搜', '搜错了', 'retry'}
DEEP_IMAGE_RETRY_WORDS = {'都不对', '深度识图', '深搜'}

# 识图意图命令词（@触发：进入 20 秒等待窗口，期间直接发的图自动识图）
IMAGE_WAIT_WORDS = {'识图', '搜图', '以图搜本', '搜本'}

# 识图等待窗口（group_id -> {user_id, expires}）：@识图后 20 秒内该用户发的图自动识图
IMAGE_WAIT = {}
IMAGE_WAIT_SECONDS = 20

# 每群关键词搜索冷却（group_id -> 上次搜索时间戳）
SEARCH_COOLDOWN = {}


def search_cooldown_hit(group_id):
    """每群 10 秒冷却：随机推荐也走禁漫搜索接口，与关键词搜索共用冷却防刷"""
    now = time.monotonic()
    if now - SEARCH_COOLDOWN.get(group_id, 0) < 10:
        return True
    SEARCH_COOLDOWN[group_id] = now
    return False


# 搜索结果翻页状态（(group_id, user_id) -> {keyword, kind, head, results, page, ts}）。
# 同一群里的不同用户各自拥有结果和翻页位置，避免 A 的搜索覆盖 B。
SEARCH_STATE = {}
SEARCH_STATE_TTL = 600  # 10分钟不翻页则过期
PAGE_SIZE = 5


def _search_state_key(group_id, user_id):
    return str(group_id), str(user_id)


def get_search_state(group_id, user_id):
    return SEARCH_STATE.get(_search_state_key(group_id, user_id))


def set_search_state(group_id, user_id, state):
    cleanup_search_states()
    SEARCH_STATE[_search_state_key(group_id, user_id)] = state
    return state


def clear_search_state(group_id, user_id):
    SEARCH_STATE.pop(_search_state_key(group_id, user_id), None)


def cleanup_search_states():
    now = time.time()
    for key, state in list(SEARCH_STATE.items()):
        if now - state.get('ts', 0) > SEARCH_STATE_TTL:
            SEARCH_STATE.pop(key, None)


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
        chap = f' 章节：{r["chapter_count"]}章' if r.get('chapter_count') else ''
        lines.append(f'{i}. 《{escape_cq(r["title"])}》{chap}\n'
                     f'   🔢 ID：{r["id"]}')
    if page < total_pages:
        lines.append('💡 直接发「下一页」翻页，或发「第N页」跳转（无需@我）')
    else:
        lines.append('✅ 已查看完全部结果')
    lines.append('💡 @我「下载 3」或「详情 3」可操作列表第 3 本')
    return '\n'.join(lines)


def render_image_result(result):
    """渲染识图结果消息文本（识图分支与重搜共用）"""
    lines = ['🔍 识图结果：']
    if result.get('ocr_texts'):
        lines.append(f'🔤 封面文字：{" / ".join(escape_cq(t) for t in result["ocr_texts"])}')
    if result.get('llm_words'):
        lines.append(f'🤖 AI 识别：{" / ".join(escape_cq(t) for t in result["llm_words"])}')
    if result['source_title']:
        lines.append(f'📕 来源：《{escape_cq(result["source_title"][:60])}》')
    if result['source_author']:
        lines.append(f'✍️ 作者：{escape_cq(result["source_author"])}')
    if result['source_url']:
        lines.append(f'🔗 {escape_cq(result["source_url"])}')
    if result['matches']:
        lines.append(f'📚 禁漫匹配到 {len(result["matches"])} 本：')
        for i, r in enumerate(result['matches'], 1):
            score, reason = image_match_confidence(result, r)
            stars = '★' * score + '☆' * (5 - score)
            lines.append(f'{i}. 《{escape_cq(r["title"])}》 章节：{r["chapter_count"]}章\n'
                         f'   🔢 ID：{r["id"]}\n'
                         f'   可信度：{stars}（{escape_cq(reason)}）')
        lines.append('想要下载？@我 + 发送对应的ID，或 @我「下载 1」\n'
                     '都不对？@我 发送「都不对」进入深度识图')
    else:
        lines.append('⚠️ 禁漫未搜到同款本子')
    return '\n'.join(lines)


async def handle_next_page(api, group_id, user_id, silent=False, page=None):
    """
    翻页/跳页：显示上一次搜索结果的下一页（page=None）或第 page 页。
    silent=True（免@触发）时无状态则静默忽略；跳转越界自动收敛到有效页。
    """
    state = get_search_state(group_id, user_id)
    if not state or time.time() - state['ts'] > SEARCH_STATE_TTL:
        clear_search_state(group_id, user_id)
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


# 详情预览触发词（@JM娘 详情 <ID> → 纯文字详情，不发图防QQ内容扫描）
DETAIL_WORDS = ('详情', '预览', '看看', 'info', 'detail')


def extract_detail_id(text: str):
    """从@后的文本中提取「详情 <ID>」的漫画ID，提取不到返回 None"""
    if not text:
        return None
    low = text.lower().strip()
    for w in DETAIL_WORDS:
        if low.startswith(w):
            rest = low[len(w):].strip().lstrip('：:： ').strip()
            aid = extract_album_id(rest)
            if aid:
                return aid
            # 「详情350234」无空格也支持
            m = re.fullmatch(r'\s*(\d{5,9})\s*', rest)
            if m:
                return m.group(1)
    return None


# 中文数字（页码跳转用）：支持 一~九十九
CN_DIGITS = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def _cn_to_int(s):
    """中文数字转整数：四→4，十→10，十二→12，二十→20，二十五→25；无法转换返回 None"""
    if '十' not in s:
        return CN_DIGITS.get(s)
    if s == '十':
        return 10
    if s.startswith('十'):
        return 10 + CN_DIGITS.get(s[1], 0)
    if s.endswith('十'):
        return CN_DIGITS.get(s[0], 0) * 10
    head, tail = s.split('十', 1)
    return CN_DIGITS.get(head, 0) * 10 + CN_DIGITS.get(tail, 0)


def extract_page(text: str):
    """提取页码跳转命令：'第2页' / '第 2 页' / '2页' / '第四页' → 2；否则 None"""
    if not text:
        return None
    m = re.fullmatch(r'第?\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*页', text)
    if not m:
        return None
    g = m.group(1)
    return int(g) if g.isdigit() else _cn_to_int(g)


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


def extract_tag(text: str):
    """提取标签搜索命令：'标签 xxx' / '标签:xxx' / 'tag xxx' → 返回标签名，否则 None"""
    if not text:
        return None
    low = text.lower()
    for prefix in ('标签', 'tag'):
        if low.startswith(prefix):
            rest = text[len(prefix):].strip(' :：、,，')
            return rest or None
    return None


def extract_images(msg):
    """提取消息中的图片段（url 优先，file 本地路径兜底）"""
    out = []
    for seg in msg.get('message') or []:
        if seg.get('type') == 'image':
            d = seg.get('data', {})
            out.append({'url': d.get('url', ''), 'file': d.get('file', '')})
    return out


# 允许的本地图片路径前缀（NapCat 缓存目录），防以图搜本读取任意本地文件
LOCAL_IMG_PREFIXES = ('/root/Napcat/', '/root/.config/QQ/', '/opt/jmniang/')

# 图片大小上限（防超大文件占用内存/外传）
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB


def _read_limited(path):
    """读文件并限大小（10MB）"""
    try:
        with open(path, 'rb') as f:
            data = f.read()
        return data if len(data) <= MAX_IMAGE_BYTES else None
    except Exception:
        return None


def _http_fetch(url):
    """下载图片 URL（域名白名单 + 大小上限）"""
    import requests
    host = url.split('/')[2].split('?')[0]
    if not (host.endswith('.qpic.cn') or host == 'multimedia.nt.qq.com.cn'):
        return None
    try:
        r = requests.get(url, timeout=30)
        return r.content if r.status_code == 200 and len(r.content) <= MAX_IMAGE_BYTES else None
    except Exception:
        return None


def fetch_image_bytes(img_ref):
    """
    下载图片：
    1. url 下载（仅 QQ 图片 CDN 域名白名单 + 大小上限，防 SSRF）
    2. file 绝对路径（限 NapCat 缓存目录前缀）
    3. file 纯文件名（在 NapCat 缓存目录下递归查找）
    """
    import glob
    url = img_ref.get('url') or ''
    if url.startswith('http'):
        data = _http_fetch(url)
        if data:
            return data
    path = img_ref.get('file') or ''
    if path:
        # 绝对路径：仅白名单前缀
        if os.path.sep in path:
            if path.startswith(LOCAL_IMG_PREFIXES) and os.path.isfile(path):
                data = _read_limited(path)
                if data:
                    return data
        else:
            # 纯文件名（NapCat 通常给文件名）：在 QQ 缓存目录查找（文件名大小写不敏感）
            for pattern in (f'/root/.config/QQ/*/nt_data/Pic/**/{path}',
                            f'/root/.config/QQ/NapCat/**/{path}'):
                for hit in glob.glob(pattern, recursive=True)[:1]:
                    data = _read_limited(hit)
                    if data:
                        return data
    return None


async def fetch_image_with_api(api, img_ref):
    """识图图片获取：先 url/本地 file；失败用 OneBot get_image API 拿 NapCat 解析出的真实路径再读"""
    data = await asyncio.to_thread(fetch_image_bytes, img_ref)
    if data:
        return data
    file_name = img_ref.get('file') or ''
    if file_name:
        try:
            resp = await api('get_image', {'file': file_name}, timeout=15)
            d = (resp or {}).get('data') or {}
            path = d.get('file') or ''
            if path and path.startswith(LOCAL_IMG_PREFIXES):
                data = await asyncio.to_thread(_read_limited, path)
                if data:
                    return data
            url = d.get('url') or ''
            if url.startswith('http'):
                data = await asyncio.to_thread(_http_fetch, url)
                if data:
                    return data
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- 核心业务

async def _group_file_exists(api, group_id, file_name, retries=2, delay=6):
    """查询群文件根目录列表，判断目标文件是否已存在（上传事件确认超时的假失败检测）
    带重试：上传完成到文件出现在群文件列表之间有延迟（QQ 后台写入），立即查会误判失败"""
    for _ in range(retries):
        try:
            resp = await api('get_group_root_files', {'group_id': group_id}, timeout=30)
            files = (resp.get('data') or {}).get('files') or []
            if any((f.get('file_name') or f.get('name')) == file_name for f in files):
                return True
        except Exception:
            pass
        await asyncio.sleep(delay)
    return False


def _fmt_duration(sec):
    """秒 → 可读时长（x天x小时x分x秒，前导 0 单位省略）"""
    d, r = divmod(int(sec), 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = [f'{d}天' if d else '', f'{h}小时' if h else '', f'{m}分' if m else '', f'{s}秒']
    return ''.join(parts)


def _qq_process_etime():
    """QQ 进程存活时长（Linux ps 查询；失败/非 Linux 返回 None）"""
    try:
        import subprocess
        out = subprocess.run(['ps', '-eo', 'etime,args'], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if '/root/Napcat/opt/QQ/qq --no-sandbox' in line:
                return line.split()[0]  # HH:MM:SS 或 D-HH:MM:SS
    except Exception:
        pass
    return None


def extract_chapter_download(text: str):
    """解析“下载 JM123456 第2-5章”或“下载 123456 最新”。"""
    if not text:
        return None
    m = re.fullmatch(
        r'\s*(?:下载|下)\s*(?:/)?(?:jm)?\s*(\d{5,9})\s*'
        r'(?:(?:第\s*(\d+)\s*(?:[-~～到至]\s*(\d+)\s*)?章)|最新)\s*',
        text, re.IGNORECASE,
    )
    if not m:
        return None
    album_id, start, end = m.groups()
    return album_id, ('latest' if start is None else (int(start), int(end or start)))


def extract_result_action(text: str):
    """解析“下载 3”/“详情 3”这类基于当前结果列表的操作。

    仅接受 1~3 位的序号，避免把正常的 5~9 位 JM ID 误判成序号。
    """
    if not text:
        return None
    m = re.fullmatch(r'\s*(下载|下|详情|预览)\s*(\d{1,3})\s*', text.lower())
    if not m:
        return None
    return m.group(1), int(m.group(2))


def get_result_by_index(group_id, user_id, index):
    """取用户最近搜索/榜单/识图结果的第 index 本（1-based）。"""
    state = get_search_state(group_id, user_id)
    if not state or time.time() - state.get('ts', 0) > SEARCH_STATE_TTL:
        clear_search_state(group_id, user_id)
        return None
    results = state.get('results') or []
    if index < 1 or index > len(results):
        return None
    state['ts'] = time.time()
    return results[index - 1]


def chapter_range_from_source(source):
    """从持久化来源字段恢复章节范围；整本任务返回 None。"""
    m = re.fullmatch(r'chapter:(\d+)(?:-(\d+))?', str(source or ''))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or m.group(1))


def _parse_etime(t):
    """ps etime 文本 → 秒；支持 MM:SS / HH:MM:SS / D-HH:MM:SS 三种格式；失败返回 None"""
    try:
        if '-' in t:
            d, rest = t.split('-', 1)
            h, m, s = rest.split(':')
            return int(d) * 86400 + int(h) * 3600 + int(m) * 60 + int(s)
        parts = t.split(':')
        if len(parts) == 2:  # MM:SS（不足 1 小时）
            m, s = parts
            return int(m) * 60 + int(s)
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + int(s)
    except Exception:
        return None


def _self_check_cache_stats():
    """统计本地下载/分享缓存；只读元数据，不打开 ZIP 内容。"""
    zip_count, zip_bytes, share_count, share_bytes = 0, 0, 0, 0
    for root, _dirs, files in os.walk(DOWNLOAD_DIR):
        for filename in files:
            if filename.lower().endswith('.zip'):
                try:
                    zip_count += 1
                    zip_bytes += os.path.getsize(os.path.join(root, filename))
                except OSError:
                    pass
    for root, _dirs, files in os.walk(SHARE_DIR):
        for filename in files:
            try:
                share_count += 1
                share_bytes += os.path.getsize(os.path.join(root, filename))
            except OSError:
                pass
    return zip_count, zip_bytes, share_count, share_bytes


def _self_check_dns():
    try:
        socket.getaddrinfo('18comic.vip', 443, type=socket.SOCK_STREAM)
        return True
    except OSError:
        return False


def _self_check_napcat_port():
    try:
        with socket.create_connection((WS_HOST, WS_PORT), timeout=2):
            return True
    except OSError:
        return False


def render_self_check():
    """一次性汇总进程、NapCat、网络、下载、识图、缓存与持久化状态；绝不显示凭据。"""
    start_txt = datetime.datetime.fromtimestamp(START_TIME).strftime('%m-%d %H:%M:%S')
    lines = [f'🤖 JM娘综合自查',
             f'【进程】自 {start_txt} 启动，已运行 {_fmt_duration(time.time() - START_TIME)}']
    if CUR_CONN_TIME:
        conn_txt = datetime.datetime.fromtimestamp(CUR_CONN_TIME).strftime('%m-%d %H:%M:%S')
        napcat = f'已连接（自 {conn_txt} 起 {_fmt_duration(time.time() - CUR_CONN_TIME)}）'
    else:
        napcat = '机器人尚未建立 WS 连接'
    lines.append(f'【NapCat】{napcat}；8081 端口 {"可达" if _self_check_napcat_port() else "不可达"}')
    secs = _parse_etime(_qq_process_etime() or '')
    if secs is not None:
        lines.append(f'【QQ】进程已存活 {_fmt_duration(secs)}')
    lines.append(f'【网络】禁漫域名 DNS {"正常" if _self_check_dns() else "失败"}；本机 WS 仅检测，不发起下载请求')
    usage = shutil.disk_usage(BASE_DIR)
    lines.append(f'【下载】队列 {"暂停" if QUEUE_PAUSED else "运行"}；活跃 {len(ACTIVE_TASKS)}/{MAX_CONCURRENT_DOWNLOADS}；等待 {max(0, DOWNLOAD_QUEUE - len(ACTIVE_TASKS))}；磁盘可用 {format_bytes(usage.free)}')
    image_sources = ['OCR/iQDB']
    if os.environ.get('JM_SAUCENAO_KEY'):
        image_sources.append('SauceNAO')
    if os.environ.get('JM_LLM_KEY'):
        image_sources.append('视觉 LLM')
    if os.environ.get('JM_AGENTKEY_KEY'):
        image_sources.append('AgentKey 中转')
    lines.append('【识图】可用链路：' + '、'.join(image_sources) + '；支持置信度与“都不对”深度复核')
    zip_count, zip_bytes, share_count, share_bytes = _self_check_cache_stats()
    lines.append(f'【缓存】下载 ZIP {zip_count} 个 / {format_bytes(zip_bytes)}；分享文件 {share_count} 个 / {format_bytes(share_bytes)}')
    try:
        stats = get_store_stats()
        lines.append(f'【记录】任务 {stats.get("jobs", {})}；订阅 {stats.get("subscriptions", 0)} 项')
    except Exception:
        lines.append('【记录】SQLite 状态暂不可读')
    lines.append('✅ 自查不显示密码、密钥、Cookie 或聊天内容')
    return '\n'.join(lines)


def _match_text(value):
    return re.sub(r'[^\w\u4e00-\u9fffぁ-んァ-ン]', '', str(value or '')).lower()


def image_match_confidence(result, match):
    """给识图候选一个可解释的 1–5 星置信度，不把推测伪装成确定答案。"""
    title = _match_text(match.get('title'))
    score, reasons = 1, []
    source_title = _match_text(result.get('source_title'))
    if source_title and title and (source_title in title or title in source_title):
        score += 2
        reasons.append('标题验证')
    for word in (result.get('ocr_texts') or [])[:6]:
        normalized = _match_text(word)
        if len(normalized) >= 3 and title and normalized in title:
            score += 1
            reasons.append('OCR')
            break
    for word in (result.get('llm_words') or [])[:4]:
        normalized = _match_text(word)
        if len(normalized) >= 3 and title and normalized in title:
            score += 1
            reasons.append('AI 提取')
            break
    author = _match_text(result.get('source_author'))
    if author and author in _match_text(match.get('author')):
        score += 1
        reasons.append('作者验证')
    if result.get('source_url'):
        reasons.append('视觉来源')
    score = max(1, min(5, score))
    return score, ' + '.join(dict.fromkeys(reasons)) or '候选匹配'


def render_task_status():
    """当前正在处理的任务状态文本（含预计剩余时间）。无任务返回空串"""
    lines = []
    for aid, t in list(ACTIVE_TASKS.items()):
        if t['phase'] == '下载中' and t['total'] > 0:
            remain = t['total'] - t['done']
            est_min = max(1, int(remain * SECONDS_PER_PAGE_MAX / 60))
            lines.append(f'{len(lines) + 1}. 漫画 {aid}：下载中 {t["done"]}/{t["total"]} 页，'
                         f'约还需 {est_min} 分钟')
        elif t['phase'] == '上传中':
            lines.append(f'{len(lines) + 1}. 漫画 {aid}：上传中，约还需 1-2 分钟')
        else:
            lines.append(f'{len(lines) + 1}. 漫画 {aid}：准备中…')
    return '\n'.join(lines)


async def render_admin_status():
    """管理员诊断：只展示机器人任务元数据与本机资源，不含用户聊天内容/凭据。"""
    stats = await asyncio.to_thread(get_store_stats)
    jobs = await asyncio.to_thread(list_active_jobs_all)
    usage = shutil.disk_usage(BASE_DIR)
    lines = [
        '🛠️ 管理诊断',
        f'· 队列：{"已暂停" if QUEUE_PAUSED else "运行中"}；全局并发 {len(ACTIVE_TASKS)}/{MAX_CONCURRENT_DOWNLOADS}；等待 {max(0, DOWNLOAD_QUEUE - len(ACTIVE_TASKS))}',
        f'· 磁盘：可用 {format_bytes(usage.free)} / 总计 {format_bytes(usage.total)}',
        f'· 持久化任务：{stats.get("jobs", {})}；订阅 {stats.get("subscriptions", 0)} 项',
        f'· 进程：已运行 {_fmt_duration(time.time() - START_TIME)}；NapCat {"已连接" if CUR_CONN_TIME else "未连接"}',
    ]
    if jobs:
        lines.append('· 活跃任务：')
        for job in jobs[:10]:
            title = escape_cq(job.get('title') or f'JM{job["album_id"]}')
            lines.append(f'  {job["job_id"][:8]} {job["status"]} 群{job["group_id"]} 用户{job["user_id"]} 《{title}》')
    return '\n'.join(lines)


def is_admin(user_id):
    return str(user_id) in ADMIN_USERS


def _job_status_text(status):
    return {
        'queued': '排队中', 'running': '处理中', 'completed': '已完成',
        'cancelled': '已取消', 'failed': '失败',
    }.get(status, status or '未知')


def render_personal_jobs(group_id, user_id, active_only=False):
    """渲染当前群内该用户自己的持久化任务和历史。"""
    jobs = list_jobs(group_id, user_id, limit=10)
    if active_only:
        jobs = [j for j in jobs if j['status'] in ('queued', 'running')]
    if not jobs:
        return ''
    lines = []
    for index, job in enumerate(jobs, 1):
        title = escape_cq(job.get('title') or f'JM{job["album_id"]}')
        detail = f'{index}. {_job_status_text(job["status"])} · 《{title}》\n   🔢 ID：{job["album_id"]}'
        if job.get('total_pages'):
            detail += f' · {job["total_pages"]} 页'
        if job['status'] == 'completed' and job.get('zip_path') and os.path.isfile(job['zip_path']):
            detail += ' · 缓存可重发'
        if job.get('error') and job['status'] == 'failed':
            detail += f' · {escape_cq(job["error"][:60])}'
        lines.append(detail)
    return '\n'.join(lines)


async def send_album_detail(api, group_id, album_id):
    """发送纯文字漫画详情；直接 ID 与“详情 序号”共用。"""
    await api('send_group_msg', {
        'group_id': group_id,
        'message': f'📋 正在获取漫画 {album_id} 的信息…'
    })
    info = await asyncio.to_thread(get_album_info, album_id)
    if info:
        tags = ', '.join(str(t) for t in (info.get('tags') or [])[:8])
        msg = (f'📕《{escape_cq(info["title"])}》\n'
               f'✍️ 作者：{escape_cq(info.get("author") or "未知")}\n'
               f'🏷️ 标签：{escape_cq(tags) if tags else "无"}\n'
               f'📚 共 {info["chapter_count"]} 章 / {info["page_count"]} 页\n'
               f'🔗 禁漫：https://18comic.vip/album/{album_id}\n'
               f'💾 @我 {album_id} 即可下载')
        await api('send_group_msg', {'group_id': group_id, 'message': msg})
        return info
    await api('send_group_msg', {
        'group_id': group_id,
        'message': f'❌ 获取漫画 {album_id} 信息失败（ID 不存在或网络波动）'
    })
    return None


def _subscription_kind_text(kind):
    return {'album': '作品收藏', 'author': '作者订阅', 'tag': '标签订阅'}.get(kind, kind)


def render_subscriptions(group_id, user_id):
    subscriptions = list_subscriptions(group_id, user_id)
    if not subscriptions:
        return ''
    lines = []
    for index, sub in enumerate(subscriptions, 1):
        label = escape_cq(sub.get('label') or sub['target'])
        cadence = '日报' if sub.get('cadence') == 'daily' else '周报'
        lines.append(f'{index}. {_subscription_kind_text(sub["kind"])}：{label}（{cadence}）')
    return '\n'.join(lines)


def _subscription_items(sub):
    """同步查询单个订阅的最新候选，返回用于去重的简化项目列表。"""
    kind, target = sub['kind'], sub['target']
    if kind == 'author':
        results = search_author_album(target, 20) or []
        return [{'id': str(item['id']), 'title': item.get('title', '')} for item in results]
    if kind == 'tag':
        results = search_tag_album(target, 20) or []
        return [{'id': str(item['id']), 'title': item.get('title', '')} for item in results]
    if kind == 'album':
        info = get_album_info(target)
        if not info:
            return []
        # 页数变化可作为连载作品更新信号。
        return [{'id': str(target), 'title': info.get('title', ''), 'version': str(info.get('page_count', 0))}]
    return []


def _subscription_item_key(item):
    return f'{item.get("id", "")}:{item.get("version", "")}'


async def check_subscriptions(api, force_digest=False):
    """检查订阅并按个人节奏发送聚合摘要；首轮只建立基线，不打扰用户。"""
    now = int(time.time())
    digest_lines, to_mark_digested = {}, []
    subscriptions = await asyncio.to_thread(list_all_subscriptions)
    for sub in subscriptions:
        if not force_digest and sub.get('last_checked_at') and now - sub['last_checked_at'] < SUBSCRIPTION_CHECK_SECONDS:
            continue
        try:
            current = await asyncio.to_thread(_subscription_items, sub)
        except Exception as e:
            log(f'订阅检查失败 {sub["subscription_id"][:8]}: {e!r}')
            continue
        current = current[:30]
        seen = decode_subscription_json(sub.get('seen_json'))
        pending = decode_subscription_json(sub.get('pending_json'))
        if not seen:
            # 初次收藏仅记录当前版本，避免把历史内容当成“新更新”。
            await asyncio.to_thread(update_subscription_state, sub['subscription_id'],
                                    seen=current, pending=pending, checked=True, digested=True)
            continue
        seen_keys = {_subscription_item_key(item) for item in seen}
        new_items = [item for item in current if _subscription_item_key(item) not in seen_keys]
        pending_keys = {_subscription_item_key(item) for item in pending}
        pending.extend(item for item in new_items if _subscription_item_key(item) not in pending_keys)
        await asyncio.to_thread(update_subscription_state, sub['subscription_id'],
                                seen=current, pending=pending[-30:], checked=True)
        cadence = SUBSCRIPTION_CADENCE_SECONDS.get(sub.get('cadence'), SUBSCRIPTION_CADENCE_SECONDS['weekly'])
        due = force_digest or (sub.get('last_digest_at') and now - sub['last_digest_at'] >= cadence)
        if pending and due:
            key = (sub['group_id'], sub['user_id'])
            label = escape_cq(sub.get('label') or sub['target'])
            previews = '；'.join(f'《{escape_cq(item.get("title") or item.get("id"))}》' for item in pending[:5])
            digest_lines.setdefault(key, []).append(
                f'· {_subscription_kind_text(sub["kind"])}「{label}」新增 {len(pending)} 项：{previews}'
            )
            to_mark_digested.append(sub['subscription_id'])
    for (group_id, user_id), lines in digest_lines.items():
        await api('send_group_msg', {
            'group_id': int(group_id) if str(group_id).isdigit() else group_id,
            'message': f'[CQ:at,qq={user_id}] 📬 JM娘订阅摘要\n' + '\n'.join(lines) +
                       '\n💡 可发送「我的收藏」管理订阅。'
        })
    for subscription_id in to_mark_digested:
        await asyncio.to_thread(update_subscription_state, subscription_id, pending=[], digested=True)


async def subscription_loop(api):
    while True:
        try:
            await check_subscriptions(api)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log(f'订阅后台任务出错: {e!r}')
        await asyncio.sleep(max(60, SUBSCRIPTION_CHECK_SECONDS))


# 进度条总条数控制：大本子（~90页起）全程约 7 条，小本子（几十页）目标条数随页数减少（2~4条），控制总量不刷屏。
TARGET_PROGRESS_MSGS = 7          # 大本子封顶的总进度条数
PROGRESS_MIN_MSGS = 2             # 小本子最少 2 条
PROGRESS_PAGES_PER_MSG = 15       # 约每 15 页增加 1 条（线性，封顶 7）
# 单页平均下载耗时（秒），用于估算总时长进而反推报进度间隔（SECONDS_PER_PAGE_MIN/MAX 的中值）
AVG_SECONDS_PER_PAGE = 1.05
# 进度间隔下限（秒）：仅防消息过密导致刷屏
PROGRESS_INTERVAL_MIN = 8


def _target_progress_msgs(total_pages):
    """根据页数确定全程目标进度条数：小本子少（≥2条）、大本子封顶 TARGET_PROGRESS_MSGS。"""
    if not total_pages or total_pages <= 0:
        return TARGET_PROGRESS_MSGS
    import math
    target = total_pages / PROGRESS_PAGES_PER_MSG
    return max(PROGRESS_MIN_MSGS, min(TARGET_PROGRESS_MSGS, int(math.ceil(target))))


def _progress_thresholds(target_msgs):
    """返回按目标条数划分的中途进度阈值（0~1 之间的百分比断点）。
    例 target=4 → [0.25,0.5,0.75]；start=1，到达 100% 由打包分支提示。
    target<=1 返回空（只有起始 + 完成两条）。"""
    if not target_msgs or target_msgs <= 1:
        return []
    return [i / target_msgs for i in range(1, target_msgs)]


def progress_interval(total_pages):
    """根据本子页数反推「下载中」报进度间隔（秒）。
    间隔 = 预估总时长 / 目标条数。小本子目标条数少（20页→2条、40页→3条）总条数克制；
    大本子目标条数封顶 7 条，全程约 7 条。页数未知用默认 10s。"""
    if not total_pages or total_pages <= 0:
        return 10
    target = _target_progress_msgs(total_pages)
    interval = total_pages * AVG_SECONDS_PER_PAGE / target
    return max(PROGRESS_INTERVAL_MIN, interval)


async def monitor_progress(api, group_id, album_id, total_pages, download_task, task_dir=None):
    """定时汇报下载进度：**按进度百分比阈值触发**（依赖目标条数），无论下载快慢，
    中途汇报条数都被严格控制在目标条数以内，杜绝卡网时刷屏。
    达到 100% 进入打包阶段发一次性提示。"""
    task_dir = task_dir or os.path.join(DOWNLOAD_DIR, str(album_id))
    target = _target_progress_msgs(total_pages)
    # 阈值断点：例如 target=4 → [0.25,0.5,0.75]（发3条中途进度，100%时由打包分支提示）
    thresholds = _progress_thresholds(target)
    th_idx = 0
    reported_any = False
    zip_notified = False
    while not download_task.done():
        done = count_images(task_dir)
        if album_id in ACTIVE_TASKS:
            ACTIVE_TASKS[album_id]['done'] = done
        # 打包阶段：页数下载完成但任务未结束（ZIP 加密压缩需 1-2 分钟），发一次性提示
        if total_pages > 0 and done >= total_pages and not zip_notified:
            zip_notified = True
            try:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'📦 漫画 {album_id} 下载完成，正在打包ZIP（加密压缩约需1-2分钟）…'
                })
            except Exception:
                pass
            await asyncio.sleep(3)
            continue
        if total_pages > 0:
            progress = done / total_pages
            # 一旦有下载进度就发一条起始进度，保证小本子也有反馈
            if done > 0 and not reported_any:
                reported_any = True
                pct = int(done * 100 / total_pages)
                try:
                    await api('send_group_msg', {
                        'group_id': group_id,
                        'message': f'⏳ 漫画 {album_id} 下载中… {pct}%（{done}/{total_pages}）'
                    })
                except Exception:
                    pass
                while th_idx < len(thresholds) and progress >= thresholds[th_idx]:
                    th_idx += 1
            elif thresholds and th_idx < len(thresholds) and progress >= thresholds[th_idx]:
                pct = int(done * 100 / total_pages)
                try:
                    await api('send_group_msg', {
                        'group_id': group_id,
                        'message': f'⏳ 漫画 {album_id} 下载中… {pct}%（{done}/{total_pages}）'
                    })
                except Exception:
                    pass
                th_idx += 1
                if th_idx >= len(thresholds) and not reported_any:
                    reported_any = True
        else:
            # 页数未知：按时间每 10 秒报一次已下载张数
            try:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'📥 漫画 {album_id} 下载中… 已下载 {done} 张图（本子较大请耐心等待）'
                })
                await asyncio.sleep(10)
                continue
            except Exception:
                pass
        await asyncio.sleep(3)


async def upload_delivery_file(api, group_id, album_id, zip_path, part_index=1, part_total=1):
    """上传一个交付 ZIP 并发布 HTTP 链接；返回上传状态和链接。"""
    loop = asyncio.get_event_loop()
    size = os.path.getsize(zip_path)
    file_name = os.path.basename(zip_path)
    http_url = await loop.run_in_executor(None, publish_http_link, zip_path)
    prefix = f'（第 {part_index}/{part_total} 卷）' if part_total > 1 else ''
    await api('send_group_msg', {
        'group_id': group_id,
        'message': f'《{escape_cq(file_name)}》{prefix}\n大小：{format_bytes(size)}\n正在上传到群文件…'
    })
    result, last_err = None, ''
    upload_interval = max(10, min(30, int(size / (10 * 1024 * 1024))))
    for attempt in range(1, 3):
        upload_task = asyncio.create_task(api('upload_group_file', {
            'group_id': group_id, 'file': zip_path, 'name': file_name,
        }, timeout=1200))
        waited = 0
        while not upload_task.done():
            await asyncio.sleep(upload_interval)
            if upload_task.done():
                break
            waited += upload_interval
            try:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'📤 漫画 {album_id}{prefix} 上传中…已等待 {waited} 秒'
                })
            except Exception:
                pass
        try:
            result = await upload_task
        except asyncio.TimeoutError:
            last_err, result = '上传超时', None
        except Exception as e:
            last_err, result = str(e), None
        retcode = result.get('retcode') if result else None
        if retcode == 0:
            break
        exists = await _group_file_exists(api, group_id, file_name)
        if exists is True:
            log(f'上传事件确认失败但群文件已存在（假失败），视为成功: {file_name}')
            result = {'retcode': 0}
            break
        if attempt >= 2:
            log(f'上传失败(第{attempt}次): {last_err or retcode}')
            break
        await asyncio.sleep(8)
    return {
        'path': zip_path, 'name': file_name, 'size': size, 'url': http_url,
        'retcode': result.get('retcode') if result else None, 'error': last_err,
    }


async def handle_jm_request(ws, api, group_id, user_id, album_id, job_id=None, chapter_range=None):
    """下载并上传一个漫画，负责回复群消息"""
    loop = asyncio.get_event_loop()
    # 重复请求防护：同一漫画已在下载/上传流程中时不再重复发起（防 QQ 消息重推导致发两个包）
    if album_id in ACTIVE_DOWNLOADS:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'⏳ 漫画 {album_id} 正在处理中，请稍等片刻…'
        })
        if job_id:
            await asyncio.to_thread(update_job, job_id, status='cancelled',
                                    error='相同漫画正在处理中', finished=True)
        return
    ACTIVE_DOWNLOADS.append(album_id)  # 立即占位，消除并发窗口（防双任务双份进度）
    ACTIVE_TASKS[album_id] = {
        'phase': '准备中', 'done': 0, 'total': 0,
        'group_id': str(group_id), 'user_id': str(user_id), 'job_id': job_id or '',
    }  # 排队告知用
    if job_id:
        await asyncio.to_thread(update_job, job_id, status='running', started=True)
    try:
        # 1. 缓存命中则直接上传（旧缓存若未加密，现场转加密，否则QQ会拒收）
        cached_zip, cached_title = (None, None)
        if chapter_range is None:
            cached_zip, cached_title = await loop.run_in_executor(None, find_cached_zip, album_id)
        if cached_zip:
            if ZIP_ENCRYPT:
                cached_zip = await loop.run_in_executor(None, ensure_encrypted_zip, cached_zip)
            if not cached_zip:
                raise RuntimeError(f'缓存ZIP加密转换失败: {album_id}')
            zip_path, title = cached_zip, cached_title
            if job_id:
                await asyncio.to_thread(update_job, job_id, title=title, zip_path=zip_path)
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
            total_pages = info['page_count'] if info and chapter_range is None else 0
            if info:
                if job_id:
                    await asyncio.to_thread(update_job, job_id, title=info['title'], total_pages=total_pages)
                est_low = max(1, int(total_pages * SECONDS_PER_PAGE_MIN / 60))
                est_high = max(est_low + 1, int(total_pages * SECONDS_PER_PAGE_MAX / 60))
                scope = '' if chapter_range is None else f'（指定第 {chapter_range[0]}-{chapter_range[1]} 章）'
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'📋 漫画信息确认\n'
                               f'📕《{escape_cq(info["title"])}》\n'
                               f'📚 共 {info["chapter_count"]} 章 / {info["page_count"]} 页 {scope}\n'
                               f'⏱️ 预计下载 {est_low}-{est_high} 分钟（取决于网速）\n'
                               f'📦 下载完自动打包ZIP上传群文件\n'
                               f'❌ 不想要了？@我 发送「取消」'
                })
            else:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'开始下载漫画 {album_id}（获取信息失败，无预览）…'
                })

            # 3. 启动下载 + 进度轮询（活跃任务已在入口登记占位）
            ACTIVE_TASKS[album_id]['phase'] = '下载中'
            ACTIVE_TASKS[album_id]['total'] = total_pages
            if chapter_range is None:
                download_task = loop.create_task(asyncio.to_thread(download_album_to_zip, album_id))
            else:
                download_task = loop.create_task(asyncio.to_thread(
                    download_album_chapters_to_zip, album_id, chapter_range[0], chapter_range[1]
                ))
            progress_dir = None
            if chapter_range is not None:
                selector = str(chapter_range[0]) if chapter_range[0] == chapter_range[1] else f'{chapter_range[0]}-{chapter_range[1]}'
                progress_dir = os.path.join(DOWNLOAD_DIR, 'partials', str(album_id), selector)
            progress_task = loop.create_task(
                monitor_progress(api, group_id, album_id, total_pages, download_task, progress_dir)
            )
            result_data = await download_task
            zip_path, title = result_data[0], result_data[1]
            await progress_task

            # 4. 下载期间被取消：清理残留并回复
            if album_id in CANCELLED_ALBUMS:
                await loop.run_in_executor(None, cleanup_cancelled, album_id)
                if job_id:
                    await asyncio.to_thread(update_job, job_id, status='cancelled',
                                            error='用户取消', finished=True)
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'🗑️ 漫画 {album_id} 已取消下载，缓存已清理'
                })
                return

            # 打包提示已由 monitor_progress 在打包开始时发送，此处不重复

        if album_id in ACTIVE_TASKS:
            ACTIVE_TASKS[album_id]['phase'] = '上传中'
        delivery_paths = await loop.run_in_executor(None, split_zip_for_delivery, zip_path)
        if len(delivery_paths) > 1:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'📦 文件过大，已自动分为 {len(delivery_paths)} 个可独立解压的加密 ZIP。'
            })
        deliveries = []
        for index, delivery_path in enumerate(delivery_paths, 1):
            deliveries.append(await upload_delivery_file(
                api, group_id, album_id, delivery_path, index, len(delivery_paths)
            ))
        uploaded = all(item['retcode'] in (0, None) for item in deliveries)
        if job_id:
            await asyncio.to_thread(
                update_job, job_id, status='completed', title=title, zip_path=zip_path,
                upload_status='group_file' if uploaded else 'link_only', finished=True,
            )
        if uploaded:
            names = '、'.join(escape_cq(item['name']) for item in deliveries)
            msg = f'✅ 已上传到群文件：{names}'
        else:
            errors = '; '.join(item['error'] or str(item['retcode']) for item in deliveries if item['retcode'] not in (0, None))
            msg = f'⚠️ 部分群文件上传失败：{escape_cq(errors)}\n可使用下方浏览器链接下载'
        urls = [item['url'] for item in deliveries if item['url']]
        if urls:
            label = '📎 浏览器直接下载：' if len(urls) == 1 else '📎 浏览器直接下载（每卷独立）：'
            msg += '\n\n' + label + '\n' + '\n'.join(escape_cq(url) for url in urls)
        pwd_note = zip_password_note(zip_path)
        if pwd_note:
            msg += f'\n\n{pwd_note}'
        await api('send_group_msg', {
            'group_id': group_id,
            'message': msg
        })

    except DownloadCancelledError:
        # 用户取消下载：清理残留目录
        await loop.run_in_executor(None, cleanup_cancelled, album_id)
        if job_id:
            await asyncio.to_thread(update_job, job_id, status='cancelled', error='用户取消', finished=True)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🗑️ 漫画 {album_id} 已取消下载，缓存已清理'
        })
    except asyncio.TimeoutError:
        if job_id:
            await asyncio.to_thread(update_job, job_id, status='failed', error='处理超时', finished=True)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'⏱️ 漫画 {album_id} 处理超时，请稍后重试。'
        })
    except Exception as e:
        log(f'处理 {album_id} 失败: {e!r}')
        if job_id:
            await asyncio.to_thread(update_job, job_id, status='failed', error=str(e), finished=True)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'❌ 漫画 {album_id} 处理失败：{e}\n'
                       f'可能原因：ID不存在/已删除、网络波动、禁漫拦截。'
        })
    finally:
        if album_id in ACTIVE_DOWNLOADS:
            ACTIVE_DOWNLOADS.remove(album_id)
        ACTIVE_TASKS.pop(album_id, None)


async def enqueue_download(ws, api, group_id, user_id, album_id, source='id', chapter_range=None):
    """登记个人任务后进入现有全局并发队列。"""
    global DOWNLOAD_QUEUE
    active_count = await asyncio.to_thread(count_active_jobs, group_id, user_id)
    if active_count >= MAX_ACTIVE_JOBS_PER_USER:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'⏳ 你已有 {active_count} 个下载任务在处理中/排队中。'
                       '请等待完成，或 @我「取消」后再提交。'
        })
        return
    job_id = await asyncio.to_thread(create_job, group_id, user_id, album_id, source)
    DOWNLOAD_QUEUE += 1
    try:
        if SEMAPHORE.locked():
            tasks_txt = render_task_status()
            msg = f'📥 下载任务较多，漫画 {album_id} 已加入队列\n'
            if tasks_txt:
                msg += f'📋 当前任务：\n{tasks_txt}\n'
            msg += f'（前面还有约 {DOWNLOAD_QUEUE} 个任务，'
            msg += f'每个约 2-10 分钟，请耐心等待…）'
            await api('send_group_msg', {'group_id': group_id, 'message': msg})

        async with SEMAPHORE:
            await QUEUE_RESUME_EVENT.wait()
            job = await asyncio.to_thread(get_job, job_id)
            if not job or job.get('status') == 'cancelled':
                return  # 在排队期间被“取消”命令撤销
            await handle_jm_request(ws, api, group_id, user_id, album_id, job_id, chapter_range)
    finally:
        DOWNLOAD_QUEUE -= 1


async def _search_image_with_timeout(img_bytes, timeout=60, deep=False):
    """识图超时保护；深度模式绕过缓存并额外识别中心裁图。"""
    return await asyncio.wait_for(
        asyncio.to_thread(search_by_image_deep if deep else search_by_image, img_bytes), timeout=timeout)


def ensure_apk_zip():
    """确保禁漫天堂APP加密ZIP存在（首次调用时下载APK并加密打包，之后走缓存）。
    包内：安卓APK + 苹果用户说明txt（苹果无官方App，只能网页版）。
    返回 zip 路径；失败返回 None。"""
    import glob
    import pyzipper
    import requests
    os.makedirs(APK_DIR, exist_ok=True)
    # 缓存命中：目录里已有打包好的 zip
    for z in glob.glob(os.path.join(APK_DIR, '*.zip')):
        if os.path.getsize(z) > 0:
            return z
    # 下载 APK（GitHub 官方发布主用；官网直链备用）
    apk_path = os.path.join(APK_DIR, APK_FILE)
    if not os.path.exists(apk_path) or os.path.getsize(apk_path) == 0:
        for url in APK_URLS:
            try:
                proxies = {'http': JM_PROXY, 'https': JM_PROXY} if JM_PROXY else None
                r = requests.get(url, timeout=180, proxies=proxies, headers={
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 12) JMniang/1.0'})
                if r.status_code == 200 and len(r.content) > 1024 * 1024:
                    with open(apk_path, 'wb') as f:
                        f.write(r.content)
                    log(f'APK 下载成功: {url} ({len(r.content) // 1024 // 1024}MB)')
                    break
            except Exception as e:
                log(f'APK 下载失败({url[:50]}): {e!r}')
        if not os.path.exists(apk_path):
            return None
    # 苹果用户下载地址（txt 文件，Safari 打开链接下载苹果版）
    ios_note = '苹果用户请在 Safari 浏览器打开以下网址下载安装：\nhttps://jmcomic-zzz.one/ios_app/index.php\n'
    ios_txt = os.path.join(APK_DIR, '苹果用户下载地址.txt')
    with open(ios_txt, 'w', encoding='utf-8') as f:
        f.write(ios_note)
    # AES-128 加密打包（安卓APK + 苹果下载地址txt）
    zip_path = os.path.join(APK_DIR, '禁漫天堂安装包_安卓+苹果.zip')
    try:
        with pyzipper.AESZipFile(zip_path, 'w', compression=pyzipper.ZIP_DEFLATED,
                                 encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(ZIP_PASSWORD.encode())
            zf.write(apk_path, arcname='禁漫天堂APP_安卓.apk')
            zf.write(ios_txt, arcname='苹果用户下载地址.txt')
        log(f'安装包打包完成: {zip_path}')
        return zip_path
    except Exception as e:
        log(f'安装包打包失败: {e!r}')
        return None


async def handle_apk_request(api, group_id):
    """安装包命令：HTTP 链接秒回 → 群文件上传尽力而为（大文件富媒体上传受 QQ 风控限制，不可靠）"""
    # 下载/打包是阻塞操作，放线程池
    zip_path = await asyncio.to_thread(ensure_apk_zip)
    if not zip_path:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '⚠️ 安装包准备失败（下载或打包出错），稍后再试试～'
        })
        return
    file_name = os.path.basename(zip_path)
    size = os.path.getsize(zip_path)
    link = publish_http_link(zip_path)
    # 1. 先发浏览器链接 + 密码（秒回，不依赖上传耗时）
    msg = f'📱 禁漫天堂 APP 安装包（安卓+苹果，{format_bytes(size)}）：\n'
    if link:
        msg += f'🌐 浏览器下载：{link}\n'
    msg += (f'📦 包内：安卓.apk + 苹果用户下载地址.txt\n'
            f'{zip_password_note(zip_path)}\n'
            f'⏳ 同时尝试上传群文件，请稍候…')
    await api('send_group_msg', {'group_id': group_id, 'message': msg})
    # 2. 上传：只传一次不重试（防重复文件——NapCat 假失败检测 API 不稳定时重试会传两个）
    result = None
    try:
        result = await api('upload_group_file', {
            'group_id': group_id,
            'file': zip_path,
            'name': file_name,
        }, timeout=300)
    except Exception as e:
        result = None
        log(f'安装包上传异常: {e!r}')
    retcode = result.get('retcode') if result else None
    if retcode != 0:
        # 假失败检测：事件确认失败但文件可能已传上
        if await _group_file_exists(api, group_id, file_name):
            result = {'retcode': 0}
    if not (result and result.get('retcode') in (0, None)):
        # 上传未成功：提示用户用链接（链接已发过，不重复发）
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '⚠️ 群文件上传未成功，请用上方浏览器链接下载～'
        })
    # 上传成功则静默（文件已出现在群里，链接消息里已有全部信息）


async def handle_image_search(api, group_id, user_id, images):
    """识图处理：取图 → search_by_image → 缓存状态 → 回复（@+图 与 等待窗口 两处共用）"""
    if search_cooldown_hit(group_id):
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '⏳ 识图太快啦，等几秒再试试～'
        })
        return
    await api('send_group_msg', {
        'group_id': group_id,
        'message': '🔍 正在识图搜本，稍等…'
    })
    img_bytes = await fetch_image_with_api(api, images[0])
    if not img_bytes:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '❌ 图片获取失败，请重发一次（或检查图片是否已过期）'
        })
        return
    try:
        result = await _search_image_with_timeout(img_bytes)
    except asyncio.TimeoutError:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '⏱️ 识图超过1分钟，已放弃。稍后再试试，或换一张更清晰的图～'
        })
        return
    if result is None:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '❌ 识图失败：图源未被识图引擎收录\n'
                       '（SauceNAO/iQDB 对部分本子封面无收录，试试发更清晰的原图）'
        })
        return
    # 缓存最近一张图到搜索状态：@不对 时用同一张图重新识图
    set_search_state(group_id, user_id, {
        'kind': 'image', 'keyword': '', 'img_bytes': img_bytes,
        'head': '🔍 识图', 'results': result.get('matches') or [], 'page': 1, 'ts': time.time(),
    })
    await api('send_group_msg', {
        'group_id': group_id,
        'message': render_image_result(result)
    })


# 免@按钮词 → 对应功能（用户直接发这些词即可触发，等同"点按钮"）
# 只收录无参数功能，防普通聊天误触发；词须精确匹配（fullmatch，见 handle_no_at_button）
NO_AT_BUTTONS = {
    '随机': 'random', '推荐': 'random', '抽一本': 'random', '来一本': 'random', '随缘': 'random',
    '今日属性': 'tag', '属性': 'tag',
    '日榜': 'rank:day', '周榜': 'rank:week', '月榜': 'rank:month',
    '安装包': 'apk', '禁漫': 'apk', '禁漫天堂': 'apk', '禁漫安装包': 'apk', '天堂安装包': 'apk',
    '任务': 'task', '队列': 'task', '排队': 'task',
    '我的任务': 'my_task', '我的下载': 'my_download', '下载历史': 'my_download',
    '自查': 'selfcheck',
    '说明': 'help', '帮助': 'help', '菜单': 'menu', '按钮': 'menu',
}


async def handle_no_at_button(api, group_id, user_id, text):
    """免@按钮路由：text 精确命中 NO_AT_BUTTONS 时执行对应功能，返回 True；否则返回 False（交由上层静默/翻页）"""
    low = text.lower().strip()
    action = NO_AT_BUTTONS.get(low)
    if action is None:
        # 支持中文全角/空格等差异很小，直接精确匹配即可；未命中返回，不影响翻页逻辑
        return False

    async def send(message):
        await api('send_group_msg', {'group_id': group_id, 'message': message})

    if action in ('random', 'tag'):
        if search_cooldown_hit(group_id):
            await send('⏳ 操作太快啦，等几秒再试试～')
            return True
        if action == 'random':
            await send('🎲 正在从近30天最火的本子里随机抽一本，稍等…')
            info = await asyncio.to_thread(get_random_hot_album)
            if not info:
                await send('❌ 随机推荐失败（网络波动或禁漫拦截），稍后再试试～')
                return True
            await send(f'🎲 随机推荐（近30天热门）\n'
                       f'📕《{escape_cq(info["title"])}》\n'
                       f'✍️ 作者：{escape_cq(info["author"] or "未知")}\n'
                       f'📚 共 {info["chapter_count"]} 章\n'
                       f'🔢 ID：{info["id"]}\n'
                       f'📎 https://18comic.vip/album/{info["id"]}\n'
                       f'想要？@我 + 发送这个ID 即可打包下载')
        else:
            await send('🎭 正在为你占卜今日属性，稍等…')
            info = await asyncio.to_thread(get_random_tag_album)
            if not info:
                await send('❌ 占卜失败（网络波动或禁漫拦截），稍后再试试～')
                return True
            await send(f'🎭 今日你的属性是【{escape_cq(info["tag"])}】！\n'
                       f'📕 附赠一本「{escape_cq(info["tag"])}」本子（章节少好下载）：\n'
                       f'《{escape_cq(info["title"])}》\n'
                       f'✍️ 作者：{escape_cq(info["author"] or "未知")}  章节：{info["chapter_count"]}章\n'
                       f'🔢 ID：{info["id"]}\n'
                       f'想要？@我 + 发送这个ID 即可打包下载')
        return True

    if action.startswith('rank:'):
        rank_type = action.split(':', 1)[1]
        cn = {'day': '日榜', 'week': '周榜', 'month': '月榜'}[rank_type]
        if search_cooldown_hit(group_id):
            await send('⏳ 查询太快啦，等几秒再试试～')
            return True
        await send(f'📊 正在获取{cn}，稍等…')
        results = await asyncio.to_thread(get_ranking, rank_type)
        if results is None:
            await send('❌ 获取榜单失败（网络波动或禁漫拦截），稍后再试试～')
            return True
        if not results:
            await send('榜单暂无数据')
            return True
        state = set_search_state(group_id, user_id, {
            'head': f'📊 {cn}',
            'results': results, 'page': 1, 'ts': time.time(),
            'kind': 'rank', 'keyword': rank_type,
        })
        await send(render_search_page(state, 1))
        return True

    if action == 'apk':
        await handle_apk_request(api, group_id)
        return True

    if action == 'task':
        tasks_txt = render_task_status()
        if tasks_txt:
            await send(f'📋 当前任务：\n{tasks_txt}')
        else:
            await send('✅ 当前没有正在处理的任务，可以直接@我下载哦～')
        return True

    if action in ('my_task', 'my_download'):
        jobs_txt = await asyncio.to_thread(
            render_personal_jobs, group_id, user_id, action == 'my_task'
        )
        if jobs_txt:
            heading = '📋 我的任务：' if action == 'my_task' else '📚 我的下载（最近10条）：'
            await send(heading + '\n' + jobs_txt)
        else:
            await send('✅ 你当前没有排队任务' if action == 'my_task' else '📚 还没有你的下载记录')
        return True

    if action == 'selfcheck':
        await send(render_self_check())
        return True

    if action == 'help':
        await send(HELP_TEXT)
        return True

    if action == 'menu':
        await send(BUTTON_MENU)
        return True

    return False


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
        # 识图等待窗口：@过「识图」后 20 秒内，该用户直接发的图自动识图
        wait = IMAGE_WAIT.get(group_id)
        if wait and time.time() < wait['expires'] and str(wait['user_id']) == str(user_id):
            images = extract_images(msg)
            if images:
                IMAGE_WAIT.pop(group_id, None)
                await handle_image_search(api, group_id, user_id, images)
                return
        elif wait:
            IMAGE_WAIT.pop(group_id, None)  # 过期清理
        # 翻页/跳页命令免@：直接发「下一页」或「第N页」，无需先@机器人；无状态则静默
        page_num = extract_page(text) if text else None
        if text and (text.lower() in NEXT_WORDS or page_num):
            await handle_next_page(api, group_id, user_id, silent=True, page=page_num)
            return
        # 免@按钮命令：直接发「随机/日榜/安装包/任务/自查…」等按钮词即可触发（等同点按钮）
        if text:
            handled = await handle_no_at_button(api, group_id, user_id, text)
            if handled:
                return
        return
    log(f'收到群 {group_id} 用户 {user_id} 命令: {text[:40]!r}')

    # 说明命令：@机器人 + 说明/帮助/help 等
    if text.lower() in HELP_WORDS:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': HELP_TEXT
        })
        return

    # 菜单命令：@机器人 + 菜单/按钮/面板 → 返回按钮式命令面板
    if text.lower() in MENU_WORDS:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': BUTTON_MENU
        })
        return

    # 取消命令：@机器人 + 取消/停止 等
    if text.lower() in CANCEL_WORDS:
        job = await asyncio.to_thread(cancel_latest_active_job, group_id, user_id)
        if job:
            target = str(job['album_id'])
            active = ACTIVE_TASKS.get(target)
            is_running = bool(active and active.get('job_id') == job['job_id'])
            if is_running:
                await asyncio.to_thread(cancel_download, target)
                message = f'🛑 正在取消下载 {target}，已下载的缓存将一并清除…'
            else:
                message = f'🗑️ 已取消排队任务 {target}'
            await api('send_group_msg', {
                'group_id': group_id,
                'message': message
            })
        else:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '✅ 你当前没有正在下载或排队的任务'
            })
        return

    # 安装包：@机器人 + jm安装包/安装包 等 → 禁漫天堂APP（加密ZIP）
    if text.lower() in INSTALL_WORDS:
        await handle_apk_request(api, group_id)
        return

    # 随机推荐：@机器人 + 随机/抽一本 等 → 近30天热门随机一本
    if text.lower() in RANDOM_WORDS or text.lower().startswith('随机'):
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
                       f'✍️ 作者：{escape_cq(info["author"] or "未知")}\n'
                       f'📚 共 {info["chapter_count"]} 章\n'
                       f'🔢 ID：{info["id"]}\n'
                       f'📎 https://18comic.vip/album/{info["id"]}\n'
                       f'想要？@我 + 发送这个ID 即可打包下载'
        })
        return

    # 今日属性：@机器人 + 今日属性 → @原用户 随机属性 + 附赠对应标签本子
    if text.lower() in TAG_WORDS:
        if search_cooldown_hit(group_id):
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '⏳ 占卜太快啦，等几秒再试试～'
            })
            return
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '🎭 正在为你占卜今日属性，稍等…'
        })
        info = await asyncio.to_thread(get_random_tag_album)
        if not info:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '❌ 占卜失败（网络波动或禁漫拦截），稍后再试试～'
            })
            return
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'[CQ:at,qq={user_id}] 🎭 今日你的属性是【{escape_cq(info["tag"])}】！\n'
                       f'📕 附赠一本「{escape_cq(info["tag"])}」本子（章节少好下载）：\n'
                       f'《{escape_cq(info["title"])}》\n'
                       f'✍️ 作者：{escape_cq(info["author"] or "未知")}  章节：{info["chapter_count"]}章\n'
                       f'🔢 ID：{info["id"]}\n'
                       f'想要？@我 + 发送这个ID 即可打包下载'
        })
        return

    # 排行榜：@机器人 + 日榜/周榜/月榜 → 榜单前N本（支持翻页/跳页）
    if text.lower() in RANK_WORDS:
        if search_cooldown_hit(group_id):
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '⏳ 查询太快啦，等几秒再试试～'
            })
            return
        rank_type = {'日榜': 'day', '周榜': 'week', '月榜': 'month',
                     'day': 'day', 'week': 'week', 'month': 'month'}[text.lower()]
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'📊 正在获取{escape_cq(text)}，稍等…'
        })
        results = await asyncio.to_thread(get_ranking, rank_type)
        if results is None:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '❌ 获取榜单失败（网络波动或禁漫拦截），稍后再试试～'
            })
            return
        if not results:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '榜单暂无数据'
            })
            return
        state = set_search_state(group_id, user_id, {
            'head': f'📊 {escape_cq(text)}',
            'results': results, 'page': 1, 'ts': time.time(),
            'kind': 'rank', 'keyword': rank_type,
        })
        await api('send_group_msg', {
            'group_id': group_id,
            'message': render_search_page(state, 1)
        })
        return

    # 标签搜索：@机器人 + 标签 + 名称 → 带该标签的本子
    tag = extract_tag(text)
    if tag:
        if search_cooldown_hit(group_id):
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '⏳ 搜索太快啦，等几秒再试试～'
            })
            return
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🏷️ 正在搜索标签「{escape_cq(tag)}」的本子，稍等…'
        })
        results = await asyncio.to_thread(search_tag_album, tag, 200)
        if results is None:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '❌ 搜索失败（网络波动或禁漫拦截），稍后再试试～'
            })
            return
        if not results:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '没有找到该标签所对应的本子'
            })
            return
        state = set_search_state(group_id, user_id, {
            'head': f'🏷️ 标签「{escape_cq(tag)}」的本子',
            'results': results, 'page': 1, 'ts': time.time(),
            'kind': 'tag', 'keyword': tag,
        })
        await api('send_group_msg', {
            'group_id': group_id,
            'message': render_search_page(state, 1)
        })
        return

    # 翻页/跳页：@机器人 + 下一页/翻页/第N页（也支持免@直接发）
    page_num = extract_page(text)
    if text.lower() in NEXT_WORDS or page_num:
        await handle_next_page(api, group_id, user_id, page=page_num)
        return

    # 深度识图：与普通重搜不同，绕过缓存并以中心裁图再次识别、合并候选。
    if text.lower() in DEEP_IMAGE_RETRY_WORDS:
        state = get_search_state(group_id, user_id)
        if not state or state.get('kind') != 'image' or time.time() - state['ts'] > SEARCH_STATE_TTL:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '📄 没有可深度复核的识图记录（请先发图识别）'
            })
            return
        img_bytes = state.get('img_bytes')
        if not img_bytes:
            await api('send_group_msg', {'group_id': group_id, 'message': '❌ 图片已过期，请重新发图'})
            return
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '🧪 正在深度识图：将跳过缓存，并对封面主体重新检索（最多约90秒）…'
        })
        try:
            result = await _search_image_with_timeout(img_bytes, timeout=90, deep=True)
        except asyncio.TimeoutError:
            await api('send_group_msg', {'group_id': group_id, 'message': '⏱️ 深度识图超时，已停止。请换更清晰的原图再试'})
            return
        if result is None:
            await api('send_group_msg', {'group_id': group_id, 'message': '❌ 深度识图未找到新线索，请换原图或包含标题的页面'})
            return
        state['results'] = result.get('matches') or []
        state['ts'] = time.time()
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '🧪 深度复核完成（原图 + 中心裁图）：\n' + render_image_result(result)
        })
        return

    # 管理命令：管理员白名单来自 JM_ADMIN_USERS；未配置时默认无人拥有管理权限。
    if text.startswith('管理') or text.startswith('管理员'):
        if not is_admin(user_id):
            await api('send_group_msg', {'group_id': group_id, 'message': '⛔ 该命令仅限管理员使用'})
            return
        command = re.sub(r'^(?:管理员|管理)\s*', '', text).strip()
        if command in {'', '帮助', 'help'}:
            help_text = ('🛠️ 管理命令\n'
                         '· 管理 状态 / 管理 任务\n'
                         '· 管理 暂停队列 / 管理 恢复队列\n'
                         '· 管理 取消 <任务ID前6位>\n'
                         '· 管理 检查订阅 / 管理 发送订阅摘要')
            await api('send_group_msg', {'group_id': group_id, 'message': help_text})
            return
        if command in {'状态', '任务', '自查'}:
            await api('send_group_msg', {'group_id': group_id, 'message': await render_admin_status()})
            return
        if command in {'暂停队列', '暂停'}:
            global QUEUE_PAUSED
            QUEUE_PAUSED = True
            QUEUE_RESUME_EVENT.clear()
            await api('send_group_msg', {'group_id': group_id, 'message': '⏸️ 队列已暂停：正在下载/上传的任务会完成，未开始任务保持等待'})
            return
        if command in {'恢复队列', '恢复'}:
            QUEUE_PAUSED = False
            QUEUE_RESUME_EVENT.set()
            await api('send_group_msg', {'group_id': group_id, 'message': '▶️ 队列已恢复'})
            return
        cancel_match = re.fullmatch(r'取消\s+([0-9a-fA-F]{6,32})', command)
        if cancel_match:
            job = await asyncio.to_thread(cancel_job_by_prefix, cancel_match.group(1))
            if not job:
                await api('send_group_msg', {'group_id': group_id, 'message': '📄 未找到唯一的活跃任务 ID 前缀'})
                return
            active = ACTIVE_TASKS.get(str(job['album_id']))
            if active and active.get('job_id') == job['job_id']:
                await asyncio.to_thread(cancel_download, job['album_id'])
            await api('send_group_msg', {'group_id': group_id, 'message': f'🗑️ 已取消任务 {job["job_id"][:8]}（JM{job["album_id"]}）'})
            return
        if command == '检查订阅':
            await check_subscriptions(api)
            await api('send_group_msg', {'group_id': group_id, 'message': '✅ 已完成订阅检查（按用户设置的日报/周报节奏发送）'})
            return
        if command == '发送订阅摘要':
            await check_subscriptions(api, force_digest=True)
            await api('send_group_msg', {'group_id': group_id, 'message': '✅ 已触发订阅摘要汇总'})
            return
        await api('send_group_msg', {'group_id': group_id, 'message': '❓ 未识别管理命令。@我 管理 帮助 查看用法'})
        return

    # 重新搜索：@机器人 + 不对/错了/重新搜 → 重跑上一次搜索
    if text.lower() in RETRY_WORDS:
        state = get_search_state(group_id, user_id)
        if not state or time.time() - state['ts'] > SEARCH_STATE_TTL:
            clear_search_state(group_id, user_id)
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '📄 没有可重新搜索的记录（请先搜索一次）'
            })
            return
        kind = state.get('kind', 'search')
        keyword = state.get('keyword', '')
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🔁 正在重新搜索，稍等…'
        })
        if kind == 'image':
            img_bytes = state.get('img_bytes')
            if not img_bytes:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': '❌ 图片已过期，请重新发图'
                })
                return
            try:
                result = await _search_image_with_timeout(img_bytes)
            except asyncio.TimeoutError:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': '⏱️ 重新识图超过1分钟，已放弃。稍后再试试～'
                })
                return
            if result is None:
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': '❌ 重新识图失败（图源未被识图引擎收录）'
                })
                return
            state['ts'] = time.time()
            await api('send_group_msg', {
                'group_id': group_id,
                'message': render_image_result(result)
            })
            return
        if kind == 'search':
            results = await asyncio.to_thread(search_album, keyword, 200)
        elif kind == 'author':
            results = await asyncio.to_thread(search_author_album, keyword, 200)
        elif kind == 'tag':
            results = await asyncio.to_thread(search_tag_album, keyword, 200)
        elif kind == 'rank':
            results = await asyncio.to_thread(get_ranking, keyword)
        else:
            results = None
        if results is None:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '❌ 重新搜索失败（网络波动或禁漫拦截），稍后再试试～'
            })
            return
        if not results:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '没有找到该关键词所对应的本子'
            })
            return
        state['results'] = results
        state['page'] = 1
        state['ts'] = time.time()
        await api('send_group_msg', {
            'group_id': group_id,
            'message': render_search_page(state, 1)
        })
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
        state = set_search_state(group_id, user_id, {
            'head': f'✍️ 作者「{escape_cq(author)}」的本子',
            'results': results, 'page': 1, 'ts': time.time(),
            'kind': 'author', 'keyword': author,
        })
        await api('send_group_msg', {
            'group_id': group_id,
            'message': render_search_page(state, 1)
        })
        return

    # 结果序号操作：@机器人 + 下载 3 / 详情 3。
    # 只接受带 @ 的操作，避免普通聊天中的短句误触发下载。
    result_action = extract_result_action(text)
    if result_action:
        action, index = result_action
        result = get_result_by_index(group_id, user_id, index)
        if not result:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'📄 没有第 {index} 条可操作的结果（请先搜索，或结果已过期）'
            })
            return
        album_id = str(result.get('id', ''))
        if not album_id:
            await api('send_group_msg', {'group_id': group_id, 'message': '❌ 该结果缺少漫画 ID，无法操作'})
            return
        if action in ('详情', '预览'):
            await send_album_detail(api, group_id, album_id)
        else:
            await enqueue_download(ws, api, group_id, user_id, album_id, source='result')
        return

    # 详情预览命令：@机器人 + 详情 <ID> → 纯文字详情（不发图，防QQ内容扫描）
    detail_id = extract_detail_id(text)
    if detail_id:
        log(f'群 {group_id} 用户 {user_id} 请求详情: {detail_id}')
        await send_album_detail(api, group_id, detail_id)
        return

    # 个人任务/下载历史：读取 SQLite，重启机器人后仍可保留。
    if text.lower() in MY_TASK_WORDS:
        active_only = text.lower() == '我的任务'
        jobs_txt = await asyncio.to_thread(render_personal_jobs, group_id, user_id, active_only)
        if jobs_txt:
            heading = '📋 我的任务：' if active_only else '📚 我的下载（最近10条）：'
            footer = '\n💡 @我「重发 1」可重新处理对应记录' if not active_only else ''
            await api('send_group_msg', {'group_id': group_id, 'message': heading + '\n' + jobs_txt + footer})
        else:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '✅ 你当前没有排队任务' if active_only else '📚 还没有你的下载记录'
            })
        return

    resend_match = RESEND_RE.fullmatch(text)
    if resend_match:
        index = int(resend_match.group(1))
        job = await asyncio.to_thread(get_job_by_recent_index, group_id, user_id, index)
        if not job:
            await api('send_group_msg', {'group_id': group_id, 'message': f'📄 没有第 {index} 条下载记录'})
            return
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🔁 正在重新处理 JM{job["album_id"]}（优先使用服务器缓存）…'
        })
        chapter_range = chapter_range_from_source(job.get('source'))
        await enqueue_download(
            ws, api, group_id, user_id, job['album_id'],
            source=job['source'] if chapter_range else 'resend', chapter_range=chapter_range
        )
        return

    # 收藏作品：可写 JM ID，或对自己的当前结果写“收藏 3”。
    favorite_match = FAVORITE_RE.fullmatch(text)
    if favorite_match:
        value = favorite_match.group(1).strip()
        result = get_result_by_index(group_id, user_id, int(value)) if value.isdigit() and len(value) <= 3 else None
        album_id = str(result['id']) if result else extract_album_id(value)
        if not album_id:
            compact = re.fullmatch(r'(?:jm)?\s*(\d{5,9})', value, re.IGNORECASE)
            album_id = compact.group(1) if compact else None
        if not album_id:
            await api('send_group_msg', {'group_id': group_id, 'message': '💡 用法：收藏 JM123456，或先搜索后发送「收藏 3」'})
            return
        label = result.get('title', '') if result else f'JM{album_id}'
        added = await asyncio.to_thread(add_subscription, group_id, user_id, 'album', album_id, label)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'⭐ 已收藏《{escape_cq(label)}》；首次检查只建基线，后续变更会进入摘要。'
                       if added else '📌 这部作品已经在你的收藏里了'
        })
        return

    author_match = SUBSCRIBE_AUTHOR_RE.fullmatch(text)
    if author_match:
        value = author_match.group(1).strip()
        result = get_result_by_index(group_id, user_id, int(value)) if value.isdigit() and len(value) <= 3 else None
        author = str(result.get('author') or '') if result else value
        if not author:
            await api('send_group_msg', {'group_id': group_id, 'message': '❌ 该结果没有作者信息，请直接写「订阅作者 名字」'})
            return
        added = await asyncio.to_thread(add_subscription, group_id, user_id, 'author', author, author)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🔔 已订阅作者「{escape_cq(author)}」的更新摘要' if added else '📌 该作者已经订阅'
        })
        return

    tag_sub_match = SUBSCRIBE_TAG_RE.fullmatch(text)
    if tag_sub_match:
        tag_name = tag_sub_match.group(1).strip()[:50]
        added = await asyncio.to_thread(add_subscription, group_id, user_id, 'tag', tag_name, tag_name)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🔔 已订阅标签「{escape_cq(tag_name)}」的更新摘要' if added else '📌 该标签已经订阅'
        })
        return

    if text.lower() in MY_FAVORITE_WORDS:
        subscriptions = await asyncio.to_thread(render_subscriptions, group_id, user_id)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': '⭐ 我的收藏与订阅：\n' + subscriptions + '\n💡 发送「取消收藏 1」删除；「订阅设置 每周」调整摘要频率'
                       if subscriptions else '⭐ 你还没有收藏或订阅。可发送「收藏 JM123456」「订阅作者 名字」「订阅标签 标签」'
        })
        return

    unsubscribe_match = UNSUBSCRIBE_RE.fullmatch(text)
    if unsubscribe_match:
        removed = await asyncio.to_thread(remove_subscription_by_recent_index, group_id, user_id, int(unsubscribe_match.group(1)))
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'🗑️ 已取消{_subscription_kind_text(removed["kind"])}「{escape_cq(removed.get("label") or removed["target"])}」'
                       if removed else '📄 没有对应的收藏/订阅编号'
        })
        return

    setting_match = SUBSCRIPTION_SETTING_RE.fullmatch(text)
    if setting_match:
        cadence = 'daily' if setting_match.group(1) in {'每日', '每天'} else 'weekly'
        updated = await asyncio.to_thread(set_subscription_cadence, group_id, user_id, cadence)
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'✅ 已将 {updated} 项订阅改为' + ('日报' if cadence == 'daily' else '周报')
                       if updated else '📄 还没有可设置的订阅'
        })
        return

    # 任务查询：@机器人 + 任务 → 查看当前处理中任务及预计剩余时间
    if text.lower() in TASK_WORDS:
        tasks_txt = render_task_status()
        if tasks_txt:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': f'📋 当前任务：\n{tasks_txt}'
            })
        else:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '✅ 当前没有正在处理的任务，可以直接@我下载哦～'
            })
        return

    # 自查：@机器人 + 自查 → 报告进程启动时刻/运行时长 + 当前QQ连接时长（纯本地计算）
    if text.lower() in SELF_CHECK_WORDS:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': render_self_check(),
        })
        return

    # 指定章节下载：@机器人 + 下载 JM123456 第2-5章 / 最新
    chapter_request = extract_chapter_download(text)
    if chapter_request:
        chapter_album_id, chapter_spec = chapter_request
        if chapter_spec == 'latest':
            album_data = await asyncio.to_thread(get_album_chapters, chapter_album_id)
            if not album_data or not album_data.get('chapters'):
                await api('send_group_msg', {
                    'group_id': group_id,
                    'message': f'❌ 获取漫画 {chapter_album_id} 的章节列表失败'
                })
                return
            last = len(album_data['chapters'])
            chapter_spec = (last, last)
        if chapter_spec[1] - chapter_spec[0] > 49:
            await api('send_group_msg', {
                'group_id': group_id,
                'message': '⚠️ 单次最多下载连续 50 章，请缩小范围后重试'
            })
            return
        selector = str(chapter_spec[0]) if chapter_spec[0] == chapter_spec[1] else f'{chapter_spec[0]}-{chapter_spec[1]}'
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'📚 已选择 JM{chapter_album_id} 第 {selector} 章，准备加入下载队列…'
        })
        await enqueue_download(
            ws, api, group_id, user_id, chapter_album_id,
            source=f'chapter:{selector}', chapter_range=chapter_spec,
        )
        return

    # 下载命令：@机器人 + /jm数字
    album_id = extract_album_id(text)
    if album_id:
        log(f'群 {group_id} 用户 {user_id} 请求下载: {album_id}')
        await enqueue_download(ws, api, group_id, user_id, album_id)
        return

    # 以图搜本：@机器人 + [图片]（text 为空但带图）→ 直接识图
    images = extract_images(msg)
    if images:
        log(f'识图请求: url={images[0]["url"][:100]!r} file={images[0]["file"][:80]!r}')
        await handle_image_search(api, group_id, user_id, images)
        return

    # 纯@（空文本、无图）→ 输出按钮功能菜单（用户@一下就能看到所有可用的按钮功能）
    if not text:
        await api('send_group_msg', {
            'group_id': group_id,
            'message': BUTTON_MENU
        })
        return

    # 识图意图：@机器人 + 识图/搜图 → 进入20秒等待窗口，期间直接发图即可
    if text.lower() in IMAGE_WAIT_WORDS:
        IMAGE_WAIT[group_id] = {'user_id': user_id, 'expires': time.time() + IMAGE_WAIT_SECONDS}
        await api('send_group_msg', {
            'group_id': group_id,
            'message': f'📸 请在 {IMAGE_WAIT_SECONDS} 秒内直接发送图片（无需再@我）'
        })
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
        state = set_search_state(group_id, user_id, {
            'head': f'🔍 关键词「{escape_cq(keyword)}」',
            'results': results, 'page': 1, 'ts': time.time(),
            'kind': 'search', 'keyword': keyword,
        })
        await api('send_group_msg', {
            'group_id': group_id,
            'message': render_search_page(state, 1)
        })


# ---------------------------------------------------------------- WS 服务

async def handle_connection(ws):
    """WS连接处理：reader 后台任务统一消费数据，api() 匹配 echo 响应，事件分发给处理函数"""
    global FIRST_CONNECTION, CUR_CONN_TIME
    pending: dict = {}
    bot_qq_box = [None]  # 可变容器，reader 闭包读取
    log(f'NapCat 已连接: {ws.remote_address}')
    CUR_CONN_TIME = time.time()

    async def api(action, params=None, timeout=60):
        echo = str(uuid.uuid4())
        fut = asyncio.get_event_loop().create_future()
        pending[echo] = fut
        await ws.send(json.dumps({'action': action, 'params': params or {}, 'echo': echo}))
        return await asyncio.wait_for(fut, timeout)

    FIRST_CONNECTION = False

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
            elif (msg.get('post_type') == 'request' and msg.get('request_type') == 'group'
                  and msg.get('sub_type') == 'invite'):
                # 自动同意群邀请（进群后发欢迎消息）
                try:
                    await api('set_group_add_request', {
                        'flag': msg.get('flag', ''),
                        'sub_type': 'invite',
                        'approve': True,
                    }, timeout=10)
                    log(f"已同意入群邀请: group_id={msg.get('group_id')}")
                    await asyncio.sleep(2)
                    await api('send_group_msg', {
                        'group_id': msg.get('group_id'),
                        'message': '大家好，我是 JM娘～发「说明」查看我能做什么！',
                    }, timeout=10)
                except Exception as e:
                    log(f'处理群邀请失败: {e!r}')
            elif msg.get('post_type') == 'meta_event' and msg.get('meta_event_type') == 'heartbeat':
                pass  # 心跳忽略

    reader_task = asyncio.create_task(reader())
    subscription_task = asyncio.create_task(subscription_loop(api))

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
        subscription_task.cancel()
        try:
            await subscription_task
        except asyncio.CancelledError:
            pass
        for fut in pending.values():
            if not fut.done():
                fut.cancel()
        log('NapCat 连接断开')


async def cleanup_task():
    """每天清理一次超过 24 小时的下载目录和HTTP分享文件"""
    while True:
        try:
            await asyncio.to_thread(cleanup_old_dirs, DOWNLOAD_DIR, 1)
            await asyncio.to_thread(cleanup_old_dirs, SHARE_DIR, 1, False)
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
