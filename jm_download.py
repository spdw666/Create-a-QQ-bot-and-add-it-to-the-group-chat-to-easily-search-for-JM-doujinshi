# -*- coding: utf-8 -*-
"""
JM娘 核心下载模块
功能：输入禁漫漫画ID → 下载整本（全部章节）→ 打包为一个ZIP
用法（命令行测试）: python jm_download.py <漫画ID>
"""
import glob
import os
import re
import shutil
import sys
import time
import zipfile

from jmcomic import JmOption, Feature, download_album, JmModuleConfig, JmDownloader

# 代理配置（环境变量控制）：JM_PROXY=http://127.0.0.1:7890 走代理；留空=直连（海外服务器用）
JM_PROXY = os.environ.get('JM_PROXY', '').strip()


def _patch_zip_store():
    """
    打包提速：图片（webp/jpg）已是压缩格式，ZIP 默认 DEFLATED 再压缩收益极小却费CPU。
    无加密时改用 ZIP_STORED（只打包不压缩），大本子打包时间可从分钟级降到秒级。
    """
    zip_plugin = JmModuleConfig.REGISTRY_PLUGIN.get('zip')
    if zip_plugin is None:
        return
    orig = zip_plugin.open_zip_file
    if getattr(orig, '_jm_fast_patched', False):
        return

    def fast_open(self, zip_path, encrypt_dict=None):
        if encrypt_dict is None:
            return zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED)
        return orig(self, zip_path, encrypt_dict)

    fast_open._jm_fast_patched = True
    zip_plugin.open_zip_file = fast_open


_patch_zip_store()

# 下载根目录（与脚本同级）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')

# 图片扩展名（用于统计进度）
IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.webp', '.png', '.gif')

# 下载并发配置（调低以减少禁漫CDN 502错误；过高的并发反而触发服务器限流）
IMAGE_CONCURRENCY = 14   # 单本图片并发线程数（默认30，实测30并发易触发502）
PHOTO_CONCURRENCY = 6    # 单本内章节并发数（默认32；长连载本子6章并行已足够）

# 已取消下载的 album_id 集合（进程内全局；set 操作线程安全）
CANCELLED_ALBUMS = set()

# ---------- ZIP 加密配置 ----------
# 开启后打包的ZIP带密码（AES-128），防止QQ内容扫描导致「文件瞬间失效」/上传被风控。
# 注意：加密ZIP需 WinRAR / 7-Zip / ZArchiver（手机）等支持AES的工具解压，系统自带解压不支持。
# 密码通过环境变量 JM_ZIP_PASSWORD 配置（不写死在代码里，避免泄露）
ZIP_ENCRYPT = True
ZIP_PASSWORD = os.environ.get('JM_ZIP_PASSWORD', 'CHANGE_ME')


def is_zip_encrypted(zip_path):
    """检测ZIP文件是否带密码（读取第一个条目的 flag_bits 第0位）"""
    try:
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                return bool(info.flag_bits & 0x1)
        return False
    except Exception:
        return False


def ensure_encrypted_zip(zip_path):
    """
    确保ZIP是加密的：若未加密则现场用 pyzipper AES-128 重打包为加密ZIP并替换原文件。

    QQ 上传时会扫描ZIP内容，成人漫画图会触发 rich media transfer failed；
    加密后内容不可扫描，上传即成功。旧缓存/旧版本产物未加密，命中时先转换。

    :param zip_path: ZIP绝对路径
    :return: 处理后的ZIP路径（转换成功或原本已加密返回原路径；失败返回None）
    """
    try:
        import pyzipper
        import zipfile
        import tempfile

        if is_zip_encrypted(zip_path):
            return zip_path
        # 先读到内存再写加密版（临时文件，避免读写着同一文件）
        with zipfile.ZipFile(zip_path) as src:
            items = []
            for info in src.infolist():
                items.append((info.filename, src.read(info.filename)))
        fd, tmp_path = tempfile.mkstemp(suffix='.zip', dir=os.path.dirname(zip_path))
        os.close(fd)
        with pyzipper.AESZipFile(tmp_path, 'w', pyzipper.ZIP_DEFLATED) as zf:
            zf.setencryption(pyzipper.WZ_AES, nbits=128)
            zf.setpassword(ZIP_PASSWORD.encode())
            for name, data in items:
                zf.writestr(name, data)
        os.replace(tmp_path, zip_path)  # 原子替换
        print(f'[加密] 已转换未加密ZIP为加密版: {os.path.basename(zip_path)}', flush=True)
        return zip_path
    except Exception as e:
        print(f'[加密] 转换失败: {e!r}', flush=True)
        return None


class DownloadCancelledError(Exception):
    """用户取消下载"""
    pass


class CancelableDownloader(JmDownloader):
    """支持取消的下载器：每张图下载前检查取消标记，命中则快速失败中止下载"""

    def before_image(self, image, img_save_path):
        try:
            album_id = image.from_album.album_id
        except Exception:
            album_id = None
        if album_id is not None and str(album_id) in CANCELLED_ALBUMS:
            raise DownloadCancelledError(f'用户取消了下载: {album_id}')
        return super().before_image(image, img_save_path)

# ZIP文件名中的标题前缀，如 "[JM1460484]xxx.zip"
TITLE_PREFIX_RE = re.compile(r'^\[JM\d+\]\s*')


def _apply_proxy(option):
    """根据环境变量 JM_PROXY 设置/清除 jmcomic 代理（默认配置指向 127.0.0.1:7890，海外服务器需清除）"""
    try:
        meta = option.client.postman.src_dict['meta_data']
        if JM_PROXY:
            meta['proxies'] = {'http': JM_PROXY, 'https': JM_PROXY}
        else:
            meta['proxies'] = None
    except Exception:
        pass
    return option


def _task_dir(album_id, work_dir=None):
    if work_dir is None:
        work_dir = DOWNLOAD_DIR
    return os.path.join(work_dir, str(album_id))


def find_cached_zip(album_id, work_dir=None):
    """
    查找该漫画是否已下载过（缓存命中）。

    :return: (zip绝对路径, 标题) 或 (None, None)
    """
    zips = glob.glob(os.path.join(_task_dir(album_id, work_dir), '**', '*.zip'), recursive=True)
    if not zips:
        return None, None
    zip_path = zips[0]
    title = os.path.basename(zip_path)[:-4]  # 去掉 .zip
    title = TITLE_PREFIX_RE.sub('', title)
    return zip_path, title


def get_album_info(album_id):
    """
    获取漫画信息（下载前预告用）：标题、章节数、总页数。
    各章节详情并发请求（每线程独立 client）。失败返回 None。
    """
    try:
        from concurrent.futures import ThreadPoolExecutor

        option = _apply_proxy(JmOption.default())
        client = option.new_jm_client()
        album = client.get_album_detail(album_id)
        ids = [photo.id for photo in album]
        if not ids:
            return {'title': album.title, 'chapter_count': 0, 'page_count': 0}

        def _count(pid):
            try:
                opt = JmOption.default()
                c = opt.new_jm_client()
                detail = c.get_photo_detail(pid, fetch_album=False)
                return len(detail.page_arr or [])
            except Exception:
                return 0

        with ThreadPoolExecutor(max_workers=min(8, len(ids))) as ex:
            total = sum(ex.map(_count, ids))
        return {'title': album.title, 'chapter_count': len(ids), 'page_count': total}
    except Exception:
        return None


def get_album_page_count(album_id):
    """获取漫画总页数（用于下载进度）。失败返回 0。"""
    info = get_album_info(album_id)
    return info['page_count'] if info else 0


def get_random_hot_album():
    """
    随机推荐：从近30天最火（按浏览量排序）的本子中随机挑一本。

    :return: dict {id, title, author, chapter_count} 或 None（失败）
    """
    try:
        import random
        from jmcomic import JmMagicConstants

        option = _apply_proxy(JmOption.default())
        client = option.new_jm_client()
        # 空关键词 + 本月 + 按浏览量（热度）排序
        page = client.search_site('', page=1, order_by=JmMagicConstants.ORDER_BY_VIEW,
                                  time=JmMagicConstants.TIME_MONTH)
        ids = list(page.iter_id())
        if not ids:
            return None
        # 从前 30 本里随机挑（避免总是同一本）
        album_id = random.choice(ids[:min(30, len(ids))])
        detail = client.get_album_detail(album_id)
        return {
            'id': str(detail.id),
            'title': detail.title,
            'author': detail.author,
            'chapter_count': len([p for p in detail]),
        }
    except Exception:
        return None


# 中日异体字映射（简体→日文常用汉字）：禁漫标题大量用日文汉字，站内搜索是精确子串匹配，
# 不做异体归一化，需生成变体逐个搜索。按需扩展。
SEARCH_VARIANTS = {'琉': '瑠', '绘': '絵', '姬': '姫', '战': '戦', '读': '読', '兽': '獣'}

# 中文虚词 → 日文假名：中文用户打「枫与铃」，日文标题是「枫と铃」。
# 常见虚词系统映射（含繁体形），变体兜底、原文优先，无歧义风险。
WORD_VARIANTS = {'与': 'と', '與': 'と', '和': 'と', '的': 'の', '之': 'の'}

ALL_VARIANTS = {**SEARCH_VARIANTS, **WORD_VARIANTS}

# 中文虚词单字：降级搜索时不作为核心字（这些字在日文标题中通常以假名出现）
FILLER_CHARS = set('与與和的了之是在有及或')


def _build_keywords(keyword):
    """生成搜索词变体：原文 + 简转繁 + 异体字/假名替换（原文优先，去重保序）"""
    variants = [keyword]

    def add(v):
        if v and v not in variants:
            variants.append(v)

    try:
        import zhconv
        add(zhconv.convert(keyword, 'zh-hant'))
    except Exception:
        pass  # zhconv 未安装时退化为仅原文搜索
    for v in list(variants):
        for cn, jp in ALL_VARIANTS.items():
            if cn in v:
                add(v.replace(cn, jp))
    return variants


def _core_chars(keyword):
    """提取核心字符（汉字/假名/字母数字），过滤中文虚词单字"""
    return [c for c in keyword
            if re.match(r'[0-9A-Za-z\u4e00-\u9fff\u3040-\u30ff\u31f0-\u31ff]', c)
            and c not in FILLER_CHARS]


def _field_match(text, core_chars):
    """text 是否包含全部核心字（每个核心字用其变体匹配，如 铃→铃/鈴）"""
    return all(any(v in text for v in _build_keywords(ch)) for ch in core_chars)


def _title_match(title, core_chars):
    """标题是否包含全部核心字（兼容旧名）"""
    return _field_match(title, core_chars)


def _search_by_core_chars(keyword, client, max_count, search_fn, match_field):
    """
    降级搜索（普适兜底，无字典依赖）：完整关键词搜索失败后，
    把关键词拆成核心字（如 枫与铃→枫/铃），每个核心字单独搜索，
    取标题同时包含全部核心字的候选——覆盖任何「中文写法 vs 日文写法」差异。

    ponytail: 每个核心字只搜第1页（约20-30候选/字），超冷门本子可能漏，命中率不够再翻页。
    """
    chars = _core_chars(keyword)
    if not (2 <= len(chars) <= 5):
        return []
    candidates = []  # [(aid, title)]，保持搜索结果顺序
    seen = set()
    for ch in chars:
        for kw in _build_keywords(ch):
            try:
                page = search_fn(kw, page=1)
                for aid, title in page.iter_id_title():
                    if aid not in seen:
                        seen.add(aid)
                        candidates.append((aid, title))
            except AssertionError:
                continue  # 该核心字变体无结果
            except Exception:
                continue
    matched = [aid for aid, title in candidates if _field_match(title, chars)]
    results = []
    # 快筛用搜索页标题；详情字段可能不同（搜索页条目带角色名/tag），故拉详情后二次校验
    for aid in matched[:max_count * 3]:
        try:
            detail = client.get_album_detail(aid)
        except Exception:
            continue  # 单本详情拉取失败则跳过
        if match_field:
            field_val = getattr(detail, match_field, None)
            if isinstance(field_val, list):
                field_val = ' '.join(str(x) for x in field_val)
            if not _field_match(field_val or '', chars):
                continue  # 详情主字段不含全部核心字 → 丢弃（宁缺毋滥）
        results.append({
            'id': str(detail.id),
            'title': detail.title,
            'author': detail.author,
            'chapter_count': len([p for p in detail]),
        })
        if len(results) >= max_count:
            break
    return results


def _do_search(keyword, search_method, match_field, max_pages=3):
    """
    搜索主体：变体循环（简→繁、异体、虚词→假名）+ 多页拉取 + 并发详情校验 + 核心字降级。
    返回全部命中结果（上层可切片翻页）。

    :param search_method: 'search_site'（按标题/关键词）或 'search_author'（按作者）
    :param match_field: 详情校验字段 'title' / 'author'
    :param max_pages: 每个变体拉取的搜索页数（禁漫每页约24本）
    :return: list[dict{id,title,author,chapter_count}]；无结果返回 []；请求失败返回 None
    """
    from concurrent.futures import ThreadPoolExecutor

    # 清洗：&/= 会破坏搜索接口 URL 参数结构（jmcomic 直拼关键词进 query）；空关键词不发请求
    keyword = str(keyword or '').replace('&', ' ').replace('=', ' ').strip()[:50]
    if not keyword:
        return []
    try:
        option = _apply_proxy(JmOption.default())
        client = option.new_jm_client()
        search_fn = getattr(client, search_method)
    except Exception:
        return None

    # 1. 收集候选：每个变体前 max_pages 页（去重保序，最新优先）
    variants = _build_keywords(keyword)
    ids, seen = [], set()
    network_failed = False
    for kw in variants:
        for page in range(1, max_pages + 1):
            try:
                new_ids = list(search_fn(kw, page=page).iter_id())
            except AssertionError:
                break  # 该变体没有更多页
            except Exception:
                network_failed = True
                break
            if not new_ids:
                break
            for aid in new_ids:
                if aid not in seen:
                    seen.add(aid)
                    ids.append(aid)
    # ponytail: 候选截断120本（≈24页展示），翻页想看更多时再调大 max_pages
    ids = ids[:120]

    # 2. 并发拉详情并校验（每线程独立 client，jmcomic 线程安全要求）
    def _fetch(aid):
        try:
            opt = _apply_proxy(JmOption.default())
            c = opt.new_jm_client()
            detail = c.get_album_detail(aid)
        except Exception:
            return None  # 单本详情拉取失败则跳过
        if match_field:
            # 校验详情字段含变体子串（list 字段如 tag_list 先拼成字符串）
            field_val = getattr(detail, match_field, None)
            if isinstance(field_val, list):
                field_val = ' '.join(str(x) for x in field_val)
            if not any(v in (field_val or '') for v in variants):
                return None  # 搜索页条目命中但详情主字段不含关键词，丢弃
        return {
            'id': str(detail.id),
            'title': detail.title,
            'author': detail.author,
            'chapter_count': len([p for p in detail]),
        }

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(_fetch, ids):
            if r:
                results.append(r)

    if results:
        return results
    if network_failed and not ids:
        return None  # 上层提示"搜索失败"
    # 全部变体均无结果：核心字降级搜索（普适兜底，如 枫与铃 → 枫と铃；降级最多5本，不翻页）
    return _search_by_core_chars(keyword, client, 5, search_fn, match_field)


def search_album(keyword, max_count=5):
    """按关键词/名称搜索本子（匹配标题），返回前 max_count 本。无结果返回 []，请求失败返回 None"""
    results = _do_search(keyword, 'search_site', 'title')
    return results[:max_count] if results else results


def search_author_album(author, max_count=5):
    """按作者名搜索本子（匹配作者字段），返回前 max_count 本。无结果返回 []，请求失败返回 None"""
    results = _do_search(author, 'search_author', 'author')
    return results[:max_count] if results else results


def search_tag_album(tag, max_count=5):
    """按标签搜索本子（标签是独立元数据，标题不一定含标签词，故不校验详情字段）。无结果返回 []，请求失败返回 None"""
    results = _do_search(tag, 'search_tag', None)
    return results[:max_count] if results else results


# SauceNAO 识图 API key（免费注册 https://saucenao.com/user.php；留空则仅用 iqdb 兜底识图）
SAUCENAO_KEY = os.environ.get('JM_SAUCENAO_KEY', '').strip()


def _sauce_search(img_bytes):
    """SauceNAO 识图（需 SAUCENAO_KEY）。返回 [(similarity, title, member, source, url)]，失败返回 []"""
    if not SAUCENAO_KEY:
        return []
    try:
        import requests
        r = requests.post('https://saucenao.com/search.php',
                          files={'file': ('img.jpg', img_bytes)},
                          data={'db': 999, 'output_type': 2, 'numres': 3,
                                'api_key': SAUCENAO_KEY},
                          timeout=60)
        j = r.json()
        if j.get('header', {}).get('status') != 0:
            return []
        out = []
        for res in j.get('results', []):
            h, d = res.get('header', {}), res.get('data', {})
            out.append((float(h.get('similarity', 0)), d.get('title') or '',
                        d.get('member_name') or '', d.get('source') or '',
                        (d.get('ext_urls') or [''])[0]))
        return out
    except Exception:
        return []


def _iqdb_search(img_bytes):
    """iqdb 识图（无需 key，doujinshi 覆盖一般，作兜底）。返回 [(title, url)]，失败返回 []"""
    try:
        import requests
        r = requests.post('https://iqdb.org/', files={'file': ('img.jpg', img_bytes)},
                          headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
                          timeout=90)
        html = r.text
        out = []
        # iqdb 结果行：<tr> 含 matchThumb（最佳匹配）/ additional match 标记，行内有外部站点链接
        for m in re.finditer(r'<tr[^>]*>.*?</tr>', html, re.S):
            row = m.group(0)
            low = row.lower()
            if 'matchthumb' not in low and 'additional match' not in low:
                continue
            a = re.search(r'<a href="(https?://[^"]+)"[^>]*class="[^"]*external', row) or \
                re.search(r'<a href="(https?://[^"]+)"', row)
            url = a.group(1) if a else ''
            if not url or 'iqdb' in url:
                continue
            title = re.sub(r'<[^>]+>', ' ', row)
            title = re.sub(r'\s+', ' ', title).strip()
            out.append((title[:150], url))
            if len(out) >= 3:
                break
        return out
    except Exception:
        return []


def search_by_image(img_bytes):
    """
    以图搜本：SauceNAO（需 JM_SAUCENAO_KEY）+ iqdb 兜底识图，用识图标题/作者去禁漫搜索匹配。

    :return: dict{source_title, source_author, source_url, matches:[{id,title,author,chapter_count}]}；
             识图无结果返回 None（matches 可为空列表=识图成功但禁漫未匹配）
    """
    candidates = []  # (title, member, url) 全部展示候选
    match_candidates = []  # 参与禁漫匹配的候选（SauceNAO 需 sim≥55；低相似度只展示不匹配，防误搜出无关本子）
    for sim, title, member, _src, url in _sauce_search(img_bytes):
        # doujinshi 封面经裁剪/压缩/加水印后相似度普遍 40-60%，≥40 纳入展示
        if sim >= 40:
            candidates.append((title, member, url))
            if sim >= 55:
                match_candidates.append((title, member))
            if len(candidates) >= 3:
                break
    for title, url in _iqdb_search(img_bytes):
        candidates.append((title, '', url))
        match_candidates.append((title, ''))
        if len(candidates) >= 5:
            break
    if not candidates:
        return None
    # 识图标题/作者 → 禁漫搜索（四层变体自动生效）
    matches, seen = [], set()
    for title, member in match_candidates[:5]:
        for r in (search_album(title, max_count=3) or []):
            if r['id'] not in seen:
                seen.add(r['id'])
                matches.append(r)
        if member:
            for r in (search_author_album(member, 3) or []):
                if r['id'] not in seen:
                    seen.add(r['id'])
                    matches.append(r)
        if len(matches) >= 5:
            break
    return {
        'source_title': candidates[0][0],
        'source_author': candidates[0][1],
        'source_url': candidates[0][2],
        'matches': matches[:5],
    }


# 排行榜 API 映射（jmcomic 原生支持，返回 JmSearchPage 与搜索同构）
RANK_METHODS = {'day': 'day_ranking', 'week': 'week_ranking', 'month': 'month_ranking'}


def get_ranking(rank_type, max_pages=3):
    """
    排行榜（day/week/month）：拉前 max_pages 页（每页约24本）并发取详情，返回全量结果。
    榜单无变体概念，直接复用搜索的并发详情模式。

    :return: list[dict{id,title,author,chapter_count}]；请求失败返回 None
    """
    from concurrent.futures import ThreadPoolExecutor

    method = RANK_METHODS.get(rank_type)
    if not method:
        return None
    try:
        option = _apply_proxy(JmOption.default())
        client = option.new_jm_client()
        rank_fn = getattr(client, method)
    except Exception:
        return None
    ids, seen = [], set()
    for page in range(1, max_pages + 1):
        try:
            new_ids = list(rank_fn(page=page).iter_id())
        except Exception:
            break  # 该榜单没有更多页或请求失败
        if not new_ids:
            break
        for aid in new_ids:
            if aid not in seen:
                seen.add(aid)
                ids.append(aid)
    # ponytail: 截断120本（与搜索一致，翻页够用）
    ids = ids[:120]

    def _fetch(aid):
        try:
            opt = _apply_proxy(JmOption.default())
            c = opt.new_jm_client()
            detail = c.get_album_detail(aid)
        except Exception:
            return None
        return {
            'id': str(detail.id),
            'title': detail.title,
            'author': detail.author,
            'chapter_count': len([p for p in detail]),
        }

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(_fetch, ids):
            if r:
                results.append(r)
    return results


# 今日属性标签池（随机抽一个标签，搜该标签随机附赠一本）
FUN_TAGS = [
    'NTR', '纯爱', '人妻', '女仆', '百合', '触手', '后宫', '制服', '催眠', '调教',
    '姐弟', '母女', '痴女', '寝取', '巨乳', '贫乳', '熟女', '辣妹', '黑丝', '白丝',
    '露出', '泳装', '兔女郎', '巫女', '护士', 'OL', '教师', '学生', '青梅竹马', '姐妹',
    '猫娘', '魅魔', '精灵', '兽耳', '异世界', '时间停止',
]


def get_random_tag_album():
    """
    今日属性：从标签池随机挑一个标签，搜索该标签并随机返回一本。

    :return: dict{tag, id, title, author, chapter_count}；连续3次失败返回 None
    """
    import random

    for _ in range(3):
        tag = random.choice(FUN_TAGS)
        results = search_album(tag, max_count=5)
        if results:
            album = random.choice(results)
            return {'tag': tag, **album}
    return None


def cancel_download(album_id, work_dir=None):
    """
    标记取消下载并删除已下载的缓存目录。
    下载线程会通过 CancelableDownloader 在数秒内停止。
    """
    album_id = str(album_id)
    CANCELLED_ALBUMS.add(album_id)
    task_dir = _task_dir(album_id, work_dir)
    if os.path.isdir(task_dir):
        shutil.rmtree(task_dir, ignore_errors=True)  # 文件占用时删不干净，下载停止后会再清一次
    return True


def cleanup_cancelled(album_id, work_dir=None):
    """下载线程停止后彻底清理取消任务的残留目录，并清除取消标记"""
    album_id = str(album_id)
    shutil.rmtree(_task_dir(album_id, work_dir), ignore_errors=True)
    CANCELLED_ALBUMS.discard(album_id)


def count_images(task_dir):
    """统计目录下已下载的图片数量（含子目录）"""
    count = 0
    if not os.path.isdir(task_dir):
        return 0
    for root, _dirs, files in os.walk(task_dir):
        for f in files:
            if f.lower().endswith(IMAGE_SUFFIXES):
                count += 1
    return count


def cleanup_old_dirs(work_dir=None, max_age_days=7, only_numeric=True):
    """
    删除超过 max_age_days 天的目录（图片+ZIP），防止磁盘被撑爆。
    正在下载的目录 mtime 持续更新，不会被误删。
    :param only_numeric: True=只清理纯数字目录（漫画ID目录）；False=清理所有子目录（HTTP分享token目录）
    """
    if work_dir is None:
        work_dir = DOWNLOAD_DIR
    if not os.path.isdir(work_dir):
        return 0
    now = time.time()
    removed = 0
    for name in os.listdir(work_dir):
        d = os.path.join(work_dir, name)
        if os.path.isdir(d) and (not only_numeric or name.isdigit()):
            if now - os.path.getmtime(d) > max_age_days * 86400:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    if removed:
        print(f'[清理] 已删除 {removed} 个超过 {max_age_days} 天的目录', flush=True)
    return removed


def download_album_to_zip(album_id, work_dir=None):
    """
    下载整本漫画并打包为一个 ZIP。若已有缓存直接返回。

    :param album_id: 禁漫漫画ID（album id）
    :param work_dir: 下载根目录，默认 <脚本目录>/downloads
    :return: (zip文件绝对路径, 标题字符串)
    """
    # 缓存命中：直接复用，不重复下载
    cached_zip, cached_title = find_cached_zip(album_id, work_dir)
    if cached_zip:
        return cached_zip, cached_title

    # 每个任务一个独立子目录，避免多任务互相干扰
    task_dir = _task_dir(album_id, work_dir)
    os.makedirs(task_dir, exist_ok=True)

    # 使用默认下载选项，把下载目录指向任务目录
    # 并发调低（IMAGE=14 / PHOTO=6）：30线程×多本并发易触发禁漫CDN 502限流
    option = _apply_proxy(JmOption.default())
    option.dir_rule.base_dir = task_dir
    option.download.threading.image = IMAGE_CONCURRENCY
    option.download.threading.photo = PHOTO_CONCURRENCY

    try:
        # 下载 + 自动打包ZIP（Feature.export_zip 在整本下载完后合并打包）
        # 使用 CancelableDownloader 支持下载中取消
        extra = Feature.export_zip
        if ZIP_ENCRYPT:
            # 加密打包（AES-128），防QQ内容扫描
            extra = Feature.export_zip(encrypt={'type': 'password', 'password': ZIP_PASSWORD})
        result = download_album(album_id, option, downloader=CancelableDownloader, extra=extra)
    except Exception as e:
        if str(album_id) in CANCELLED_ALBUMS:
            raise DownloadCancelledError(f'用户取消了下载: {album_id}') from e
        raise
    album = result.detail  # DownloadResult(detail, downloader)，detail 即 album 实体

    # 定位生成的ZIP文件
    zips = glob.glob(os.path.join(task_dir, '**', '*.zip'), recursive=True)
    if not zips:
        raise FileNotFoundError(f'下载成功但未找到打包生成的ZIP文件: {task_dir}')
    return zips[0], album.title


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python jm_download.py <漫画ID>')
        sys.exit(1)

    aid = sys.argv[1].strip()
    print(f'开始下载漫画 {aid} ...')
    try:
        zip_path, title = download_album_to_zip(aid)
        print(f'✅ 下载完成: {title}')
        print(f'📦 ZIP: {zip_path}')
    except Exception as e:
        print(f'❌ 下载失败: {e}')
        sys.exit(1)
