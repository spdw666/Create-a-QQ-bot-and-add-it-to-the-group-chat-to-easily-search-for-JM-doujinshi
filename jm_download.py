# -*- coding: utf-8 -*-
"""
JM娘 核心下载模块
功能：输入禁漫漫画ID → 下载整本（全部章节）→ 打包为一个ZIP
用法（命令行测试）: python jm_download.py <漫画ID>
"""
import glob
import hashlib
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
# 以图搜本：图片 sha256 → 结果缓存（同图秒回，防重复请求/不对重搜重复调用）
_IMG_RESULT_CACHE = {}
# 新识图源（ascii2d/Yandex）默认关闭：服务器 DC IP 被反爬；配好 JM_PROXY/住宅代理后置 1 启用
USE_NEW_IMAGE_SOURCES = bool(os.environ.get('JM_NEW_IMAGE_SOURCES', '').strip())

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
        # jmcomic 的 JmImageDetail 没有 from_album 属性（只有 from_photo→章节），
        # 正确路径是 image.from_photo.from_album.album_id（图片→章节→整本）。
        # 之前误用 image.from_album 会抛 AttributeError 被吞掉，导致取消永不生效。
        album_id = None
        try:
            album_id = image.from_photo.from_album.album_id
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

    返回前校验 ZIP 有效性：损坏/无效的缓存文件删除并视为无缓存（返回 None），
    避免命中坏缓存后 ensure_encrypted_zip 打开失败导致整个下载失败。

    :return: (zip绝对路径, 标题) 或 (None, None)
    """
    import zipfile
    task_dir = _task_dir(album_id, work_dir)
    zips = glob.glob(os.path.join(task_dir, '**', '*.zip'), recursive=True)
    for zip_path in list(zips):
        if not zipfile.is_zipfile(zip_path):
            # 损坏/截断的 ZIP（常见于下载/打包/上传过程中被中断）：清掉，当作没缓存
            print(f'[缓存] 移除损坏的ZIP: {zip_path}', flush=True)
            try:
                os.remove(zip_path)
            except OSError:
                pass
            zips.remove(zip_path)
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
        return {'title': album.title, 'chapter_count': len(ids), 'page_count': total,
                'author': getattr(album, 'author', '') or '',
                'tags': getattr(album, 'tags', '') or ''}
    except Exception:
        return None


def get_album_page_count(album_id):
    """获取漫画总页数（用于下载进度）。失败返回 0。"""
    info = get_album_info(album_id)
    return info['page_count'] if info else 0


def _pick_smallest_chapters(items, n=3, client=None):
    """从候选 (id, title) 里随机挑 n 本，并发拉详情后选章节数最少的一本。
    复用外部 client（传入）避免每次重复初始化 jmcomic 配置——这是提速关键。
    单本详情最多等 5 秒（禁漫 API 偶发挂起时不拖垮整个命令）。
    返回 dict{id,title,author,chapter_count} 或 None（全部失败）"""
    import random
    from concurrent.futures import ThreadPoolExecutor

    picks = random.sample(list(items), min(n, len(items)))

    def _fetch(aid, title):
        try:
            if client is not None:
                detail = client.get_album_detail(aid)
            else:
                opt = _apply_proxy(JmOption.default())
                c = opt.new_jm_client()
                detail = c.get_album_detail(aid)
            return (len([p for p in detail]), str(detail.id), detail.title,
                    getattr(detail, 'author', '') or '')
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_fetch, *p) for p in picks]
        fetched = []
        for fut in futures:
            try:
                r = fut.result(timeout=5)  # 单本详情上限 5 秒，超时放弃该本
                if r:
                    fetched.append(r)
            except Exception:
                pass
    if not fetched:
        return None
    ch, aid, title, author = min(fetched, key=lambda x: x[0])
    return {'id': aid, 'title': title or '', 'author': author, 'chapter_count': ch}


def get_random_hot_album():
    """
    随机推荐：从近30天最火（按浏览量排序）的本子中挑一本**章节数最少**的（好下载）。
    候选 3 本并发详情，约 1-2 秒。

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
        items = list(page.iter_id_title())
        if not items:
            return None
        # 从前 30 本里挑章节数最少的（避免总是同一本），复用上面已创建的 client 提速
        return _pick_smallest_chapters(items[:30], client=client)
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

# Google Cloud Vision API key（Web Detection 识图；每月前1000次免费。
# 获取：console.cloud.google.com → 启用 Cloud Vision API → 凭据 → API 密钥）
GOOGLE_KEY = os.environ.get('JM_GOOGLE_KEY', '').strip()

# E-Hentai 登录 cookie（以图搜本；登录 e-hentai.org 后 F12 控制台执行 document.cookie 复制整串）
EH_COOKIES = os.environ.get('JM_EH_COOKIES', '').strip()

# Google Web Detection 的泛词（description 太泛，搜禁漫会命中无关本子，过滤掉）
GOOGLE_IGNORE = {'manga', 'anime', 'comic', 'hentai', 'doujinshi', '同人誌', '同人志',
                 '漫画', 'アニメ', 'illustration', 'drawing', 'pixiv'}


def _post_stealth(url, files=None, data=None, headers=None, timeout=60, allow_redirects=True):
    """高伪装 POST 回退（curl_cffi 浏览器 TLS 指纹）：requests 被反爬拦截时自动切换。
    兼容 curl_cffi 新旧版（旧版 files=，新版 CurlMime multipart）。返回 Response 或 None
    allow_redirects=False 用于需要捕获 302 Location 的识图站（如 ascii2d）"""
    try:
        from curl_cffi.requests import Session
        session = Session(impersonate='chrome')
        kwargs = {'timeout': timeout}
        if data:
            kwargs['data'] = data
        if headers:
            kwargs['headers'] = headers
        if not allow_redirects:
            kwargs['allow_redirects'] = False
        if files:
            try:
                return session.post(url, files=files, **kwargs)
            except NotImplementedError:  # curl_cffi >= 0.16 废除 files，改用 CurlMime
                from curl_cffi.curl import CurlMime
                mime = CurlMime()
                for name, (fname, content, ctype) in files.items():
                    mime.addpart(name=name, filename=fname, data=content, content_type=ctype)
                return session.post(url, multipart=mime, **kwargs)
        return session.post(url, **kwargs)
    except Exception:
        return None


def _sauce_search(img_bytes):
    """SauceNAO 识图（需 SAUCENAO_KEY）。返回 [(similarity, keywords, url)]，失败返回 []"""
    if not SAUCENAO_KEY:
        return []
    files = {'file': ('img.jpg', img_bytes)}
    data = {'db': 999, 'output_type': 2, 'numres': 5, 'api_key': SAUCENAO_KEY}
    try:
        import requests
        r = requests.post('https://saucenao.com/search.php',
                          files=files, data=data, timeout=60)
    except Exception:
        r = _post_stealth('https://saucenao.com/search.php', files=files, data=data)
    if r is None:
        return []
    try:
        j = r.json()
        if j.get('header', {}).get('status') != 0:
            return []
        out = []
        for res in j.get('results', []):
            h, d = res.get('header', {}), res.get('data', {})
            # 提取全部可用搜索词字段；作者类字段单独归类（后续走 search_author_album 作者匹配）
            kws, authors = [], []
            for key in ('title', 'jp_name', 'eng_name', 'source', 'member_name',
                        'author_name', 'creator'):
                v = d.get(key)
                vals = []
                if isinstance(v, str) and v.strip():
                    vals.append(v.strip())
                elif isinstance(v, list):
                    vals.extend(str(x).strip() for x in v if str(x).strip())
                if key in ('member_name', 'author_name', 'creator'):
                    authors.extend(vals)
                else:
                    kws.extend(vals)
            out.append((float(h.get('similarity', 0)), kws,
                        (d.get('ext_urls') or [''])[0], authors))
        return out
    except Exception:
        return []


def _google_web_search(img_bytes):
    """Google Vision Web Detection 识图（需 GOOGLE_KEY，每月前1000次免费）。
    返回 [(score, keywords)]，keywords 为过滤泛词后的实体描述，失败返回 []"""
    if not GOOGLE_KEY:
        return []
    try:
        import base64
        import requests
        b64 = base64.b64encode(img_bytes).decode()
        r = requests.post('https://vision.googleapis.com/v1/images:annotate',
                          params={'key': GOOGLE_KEY},
                          json={'requests': [{
                              'image': {'content': b64},
                              'features': [{'type': 'WEB_DETECTION', 'maxResults': 10}],
                          }]},
                          timeout=60)
        j = r.json()
        wd = (j.get('responses') or [{}])[0].get('webDetection', {})
        out = []
        for e in wd.get('webEntities', []):
            desc = (e.get('description') or '').strip()
            if desc and desc.lower() not in GOOGLE_IGNORE:
                out.append((float(e.get('score', 0)), [desc]))
        return out[:10]
    except Exception:
        return []


def _ehentai_search(img_bytes):
    """E-Hentai 以图搜本（需 JM_EH_COOKIES 登录 cookie）。返回 [(title, url)]，失败返回 []。
    注意：EH 只支持彩色图（封面/CG），黑白漫画内页搜不了；免费账号有日额度"""
    if not EH_COOKIES:
        return []
    try:
        import requests
        r = requests.post('https://upld.e-hentai.org/image_lookup.php',
                          files={'sfile': ('img.jpg', img_bytes, 'image/jpeg')},
                          data={'f_sfile': 'File Search'},
                          headers={'Cookie': EH_COOKIES,
                                   'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
                          timeout=60)
        html = r.text
        out = []
        # 有结果页：gallery 链接 + 附近标题文本；<a href=".../g/<id>/<token>/">
        for m in re.finditer(
                r'<a[^>]*href="(https://e-hentai\.org/g/(\d+)/([0-9a-f]+)/?)"[^>]*>(.*?)</a>',
                html, re.S):
            url, title = m.group(1), re.sub(r'<[^>]+>', ' ', m.group(4))
            title = re.sub(r'\s+', ' ', title).strip()
            out.append((title[:150], url))
            if len(out) >= 3:
                break
        return out
    except Exception:
        return []


def _iqdb_search(img_bytes):
    """iqdb 识图（无需 key，doujinshi 覆盖一般，作兜底）。返回 [(title, url)]，失败返回 []"""
    files = {'file': ('img.jpg', img_bytes, 'image/jpeg')}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        import requests
        r = requests.post('https://iqdb.org/', files=files, headers=headers, timeout=60)
    except Exception:
        r = _post_stealth('https://iqdb.org/', files=files, headers=headers, timeout=60)
    if r is None:
        return []
    try:
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


def _ascii2d_search(img_bytes):
    """ascii2d 识图（无需 key，覆盖 Pixiv/推特/Danbooru 等日英标题）。
    上传 multipart → 302 拿结果页 → 特征检索页解析。返回 [(title, url)]，失败返回 []"""
    files = {'file': ('img.jpg', img_bytes, 'image/jpeg')}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
               'Referer': 'https://ascii2d.net/'}
    try:
        import requests
        r = requests.post('https://ascii2d.net/search/multi', files=files,
                          headers=headers, timeout=60, allow_redirects=False)
    except Exception:
        r = _post_stealth('https://ascii2d.net/search/multi', files=files,
                          headers=headers, timeout=60, allow_redirects=False)
    if r is None:
        return []
    try:
        # multipart 上传成功返回 302，Location 指向结果页（色合检索 /search/color/<hash>）
        location = r.headers.get('location') or r.headers.get('Location') or ''
        if not location:
            return []
        if not location.startswith('http'):
            location = 'https://ascii2d.net' + location
        # 切到特征检索（比色合检索更准）：/search/color/xxx → /search/xxx
        if '/color/' in location:
            location = location.replace('/color/', '/')
        page = requests.get(location, headers=headers, timeout=60)
        html = page.text
        out = []
        # 结果块：<div class="row item">…</div>，标题在 .detail-link 的 <a>，作者/来源在 .detail-sub
        for m in re.finditer(r'<div class="row item">(.*?)</div>\s*</div>', html, re.S):
            block = m.group(1)
            a = re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not a:
                continue
            url, title = a.group(1), re.sub(r'<[^>]+>', ' ', a.group(2))
            title = re.sub(r'\s+', ' ', title).strip()
            if not title or 'ascii2d' in url:
                continue
            # 作者/来源补充进标题（禁漫搜索更易命中）：detail-sub 的第一行文本
            sub = re.search(r'detail-sub[^>]*>(.*?)</div>', block, re.S)
            if sub:
                sub_text = re.sub(r'<[^>]+>', ' ', sub.group(1))
                sub_text = re.sub(r'\s+', ' ', sub_text).strip()
                if sub_text and sub_text.lower() not in title.lower():
                    title = f'{title} {sub_text}'
            out.append((title[:150], url))
            if len(out) >= 3:
                break
        return out
    except Exception:
        return []


def _yandex_search(img_bytes):
    """Yandex 以图搜图（cbird 接口 + curl_cffi chrome 指纹，反爬较强失败时静默）。
    返回 [(title, url)]，失败返回 []"""
    try:
        from curl_cffi.requests import Session
        session = Session(impersonate='chrome')
        session.get('https://yandex.com/images/', timeout=60)
        # 新版 curl_cffi 废除了 files=，用 CurlMime 上传（兼容 requests 风格文件）
        try:
            r = session.post(
                'https://yandex.com/images-apphost/image-details?cbird=111',
                files={'upfile': ('img.jpg', img_bytes, 'image/jpeg')},
                headers={'Origin': 'https://yandex.com',
                         'Referer': 'https://yandex.com/images/'},
                timeout=60)
        except NotImplementedError:
            from curl_cffi.curl import CurlMime
            mime = CurlMime()
            mime.addpart(name='upfile', filename='img.jpg', data=img_bytes, content_type='image/jpeg')
            r = session.post(
                'https://yandex.com/images-apphost/image-details?cbird=111',
                multipart=mime,
                headers={'Origin': 'https://yandex.com',
                         'Referer': 'https://yandex.com/images/'},
                timeout=60)
        j = r.json()
        out = []
        for site in (j.get('sites') or [])[:5]:
            title = (site.get('title') or '').strip()
            url = (site.get('url') or '').strip()
            if title and url:
                out.append((title[:150], url))
            if len(out) >= 3:
                break
        return out
    except Exception:
        return []


# OCR 忽略词（封面常见无关文字/水印；精确匹配，保守不过滤）
OCR_IGNORE = {'r18', 'r-18', '18禁', 'for adults', 'only', 'adults', '無修正', '无修正',
              'dl版', 'dl', 'comic', 'manga', 'sample',
              'chubold.com', 'jnp comiomic', 'jmcomic', '18comic', '18comic.vip', 'www.18comic.vip', '禁漫天堂'}

_OCR_ENGINE = None


def _get_ocr_engine():
    """RapidOCR 懒加载单例（模型加载较慢，避免每次实例化）"""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _ocr_text(img_bytes):
    """RapidOCR 提取图片文字（中/英/日）。返回 [text]，失败返回 []"""
    import os
    import tempfile
    try:
        fd, path = tempfile.mkstemp(suffix='.jpg')
        with os.fdopen(fd, 'wb') as f:
            f.write(img_bytes)
        try:
            result, _ = _get_ocr_engine()(path)
        finally:
            os.remove(path)
        if not result:
            return []
        texts = []
        for _box, text, score in result:
            t = (text or '').strip()
            if score >= 0.5 and 2 <= len(t) <= 40 and t.lower() not in OCR_IGNORE:
                texts.append(t)
        return texts
    except Exception:
        return []


# 视觉大模型配置（内页图识别：画面描述 → 标签搜索；SiliconFlow OpenAI 兼容 API）
LLM_API_KEY = os.environ.get('JM_LLM_KEY', '').strip()
LLM_API_URL = 'https://api.siliconflow.cn/v1/chat/completions'
LLM_MODEL = 'Qwen/Qwen3-VL-8B-Instruct'

# 视觉大模型的候选标签（与今日属性标签池一致，便于搜禁漫 tag）
LLM_TAGS = ('NTR、纯爱、人妻、女仆、百合、触手、后宫、制服、催眠、调教、姐弟、母女、痴女、'
            '巨乳、贫乳、熟女、辣妹、黑丝、白丝、露出、泳装、兔女郎、巫女、护士、OL、教师、'
            '学生、猫娘、魅魔、精灵、兽耳、异世界、时间停止')


def _llm_describe(img_bytes):
    """视觉大模型描述漫画内页，返回搜索词列表（标签/特征/画面文字）。无 key 或失败返回 []"""
    if not LLM_API_KEY:
        return []
    import base64
    try:
        import requests
        b64 = base64.b64encode(img_bytes).decode()
        prompt = ('这是一张成人漫画的内页。请观察画面并输出：\n'
                  f'1. 题材标签：从以下范围挑选 2-4 个最贴切的（只输出词）：{LLM_TAGS}\n'
                  '2. 画面中的角色特征词 2-3 个（如：黑发双马尾、兔女郎装、教室）\n'
                  '3. 如果画面中有可读文字，原样输出\n'
                  '只输出结果，各项用逗号分隔，不要任何解释。')
        r = requests.post(LLM_API_URL,
                          headers={'Authorization': f'Bearer {LLM_API_KEY}',
                                   'Content-Type': 'application/json'},
                          json={'model': LLM_MODEL,
                                'messages': [{'role': 'user', 'content': [
                                    {'type': 'image_url',
                                     'image_url': {'url': f'data:image/jpeg;base64,{b64}'}},
                                    {'type': 'text', 'text': prompt},
                                ]}],
                                'max_tokens': 300},
                          timeout=60)
        j = r.json()
        text = j.get('choices', [{}])[0].get('message', {}).get('content', '') or ''
        words = [w.strip() for w in re.split(r'[,，、\n]+', text) if w.strip()]
        return words[:8]
    except Exception:
        return []


_LLM_JSON_RE = re.compile(r'\{.*\}', re.S)


def _llm_extract_fields(img_bytes):
    """LLM 结构化提取：标题候选/作者/标签/画面文字 → dict；无 key 或失败返回 {}"""
    if not LLM_API_KEY:
        return {}
    import base64
    import json
    try:
        import requests
        b64 = base64.b64encode(img_bytes).decode()
        prompt = ('这是禁漫天堂的漫画图片（封面或内页）。请识别图片并只输出一个 JSON 对象（不要输出任何其他文字）：\n'
                  '{\"title_candidates\": [\"作品标题候选，1-3个，优先日文原名/中文名，必须来自图片中的书名文字\"], '
                  '\"author_candidates\": [\"作者名，0-2个，仅当图片中出现时给出\"], '
                  '\"tags\": [\"题材标签，0-5个，如 NTR、纯爱、巨乳、校园\"], '
                  '\"text\": \"图片中所有可读文字，原样逗号分隔\"}')
        r = requests.post(LLM_API_URL,
                          headers={'Authorization': f'Bearer {LLM_API_KEY}',
                                   'Content-Type': 'application/json'},
                          json={'model': LLM_MODEL,
                                'messages': [{'role': 'user', 'content': [
                                    {'type': 'image_url',
                                     'image_url': {'url': f'data:image/jpeg;base64,{b64}'}},
                                    {'type': 'text', 'text': prompt},
                                ]}],
                                'max_tokens': 600},
                          timeout=60)
        j = r.json()
        text = j.get('choices', [{}])[0].get('message', {}).get('content', '') or ''
        m = _LLM_JSON_RE.search(text)
        if not m:
            return {}
        data = json.loads(m.group(0))
        fields = {}
        for k in ('title_candidates', 'author_candidates', 'tags'):
            v = data.get(k) or []
            fields[k] = [str(x).strip() for x in v if str(x).strip()]
        fields['text'] = str(data.get('text', ''))[:200]
        return fields
    except Exception:
        return {}


def _llm_search_plan(fields):
    """LLM 字段 → 有序搜索计划（标题优先、作者次之、标签兜底），上限 5 条"""
    plan = []
    for t in (fields.get('title_candidates') or [])[:3]:
        plan.append(('title', t))
    for a in (fields.get('author_candidates') or [])[:2]:
        plan.append(('author', a))
    for g in (fields.get('tags') or [])[:2]:
        plan.append(('tag', g))
    return plan[:5]


def search_by_image(img_bytes):
    """以图搜本（缓存版）：同一张图秒回缓存结果；实现见 _search_by_image_impl"""
    h = hashlib.sha256(img_bytes).hexdigest()
    cached = _IMG_RESULT_CACHE.get(h)
    if cached is not None:
        res = dict(cached)
        res['cached'] = True
        return res
    res = _search_by_image_impl(img_bytes)
    if res is not None:
        _IMG_RESULT_CACHE[h] = res
        if len(_IMG_RESULT_CACHE) > 300:
            for k in list(_IMG_RESULT_CACHE)[:100]:
                _IMG_RESULT_CACHE.pop(k, None)
    return res


def _search_by_image_impl(img_bytes):
    """
    以图搜本：SauceNAO（需 JM_SAUCENAO_KEY）+ iqdb 兜底识图，用识图标题/作者去禁漫搜索匹配。

    :return: dict{source_title, source_author, source_url, matches:[{id,title,author,chapter_count}]}；
             识图无结果返回 None（matches 可为空列表=识图成功但禁漫未匹配）
    """
    # 1. OCR 提取封面文字（标题文字是识别金标准，优先于视觉识图）
    ocr_texts = _ocr_text(img_bytes)
    matches, seen = [], set()
    if ocr_texts:
        for t in ocr_texts[:6]:
            for r in (search_album(t, max_count=3) or []):
                if r['id'] not in seen:
                    seen.add(r['id'])
                    matches.append(r)
            if len(matches) >= 5:
                break
        if matches:
            return {
                'source_title': ocr_texts[0],
                'source_author': '',
                'source_url': '',
                'matches': matches[:5],
                'ocr_texts': ocr_texts[:6],
            }
    # 2. 视觉识图（SauceNAO + Google + E-Hentai + iQDB + ascii2d + Yandex 六路并发，总耗时=最慢一路，60s 总超时内全部出结果）
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        f_sauce = pool.submit(_sauce_search, img_bytes)
        f_google = pool.submit(_google_web_search, img_bytes)
        f_eh = pool.submit(_ehentai_search, img_bytes)
        f_iqdb = pool.submit(_iqdb_search, img_bytes)
        f_ascii2d = pool.submit(_ascii2d_search, img_bytes) if USE_NEW_IMAGE_SOURCES else None
        f_yandex = pool.submit(_yandex_search, img_bytes) if USE_NEW_IMAGE_SOURCES else None
        f_llm = pool.submit(_llm_extract_fields, img_bytes)  # LLM 结构化提取与引擎并行
        sauce_results = f_sauce.result()
        google_results = f_google.result()
        eh_results = f_eh.result()
        iqdb_results = f_iqdb.result()
        ascii2d_results = f_ascii2d.result() if f_ascii2d else []
        yandex_results = f_yandex.result() if f_yandex else []
        llm_fields = f_llm.result() or {}
    candidates = []  # (kws, url) 展示候选
    match_candidates = []  # 参与禁漫标题匹配的候选（SauceNAO 需 sim≥55；低相似度只展示不匹配，防误搜出无关本子）
    author_candidates = []  # 参与禁漫作者匹配的候选（SauceNAO 作者字段）
    for sim, kws, url, authors in sauce_results:
        # doujinshi 封面经裁剪/压缩/加水印后相似度普遍 40-60%，≥40 纳入展示
        if sim >= 40 and kws:
            candidates.append((kws, url))
            if sim >= 55:
                match_candidates.append(kws)
                if authors:
                    author_candidates.append(authors)
            if len(candidates) >= 3:
                break
    for score, kws in google_results:
        # Google webEntities score 为相关度（可>1）；≥1.0 为强匹配才参与禁漫搜索，防泛词误搜
        if kws and score >= 0.6:
            candidates.append((kws, ''))
            if score >= 1.0:
                match_candidates.append(kws)
            if len(candidates) >= 5:
                break
    for title, url in eh_results:
        candidates.append(([title], url))
        match_candidates.append([title])
        if len(candidates) >= 5:
            break
    for title, url in iqdb_results:
        candidates.append(([title], url))
        match_candidates.append([title])
        if len(candidates) >= 5:
            break
    for title, url in ascii2d_results:
        candidates.append(([title], url))
        match_candidates.append([title])
        if len(candidates) >= 5:
            break
    for title, url in yandex_results:
        candidates.append(([title], url))
        match_candidates.append([title])
        if len(candidates) >= 5:
            break
    if not candidates:
        # 3. 视觉大模型结构化兜底：引擎全灭时，用 LLM 提取的标题/作者/标签正向搜索禁漫
        for kind, kw in _llm_search_plan(llm_fields):
            try:
                fn = {'title': search_album, 'author': search_author_album, 'tag': search_tag_album}[kind]
                for r in (fn(kw, max_count=3) or []):
                    if r['id'] not in seen:
                        seen.add(r['id'])
                        matches.append(r)
            except Exception:
                continue
            if len(matches) >= 5:
                break
        llm_words = (llm_fields.get('title_candidates') or []) + (llm_fields.get('tags') or [])
        if llm_fields:
            return {
                'source_title': (llm_fields.get('title_candidates') or llm_fields.get('tags') or [''])[0],
                'source_author': (llm_fields.get('author_candidates') or [''])[0],
                'source_url': '',
                'matches': matches[:5],
                'ocr_texts': ocr_texts[:6],
                'llm_words': llm_words[:6],
            }
        return None
    # 识图关键词 → 禁漫搜索（四层变体自动生效）；标题优先，作者名补充（作者候选走 search_author_album）
    matches, seen = [], set()
    for kws in match_candidates[:5]:
        for kw in kws[:3]:
            for r in (search_album(kw, max_count=3) or []):
                if r['id'] not in seen:
                    seen.add(r['id'])
                    matches.append(r)
        if len(matches) >= 5:
            break
    for authors in author_candidates[:3]:
        for a in authors[:2]:
            for r in (search_author_album(a, max_count=3) or []):
                if r['id'] not in seen:
                    seen.add(r['id'])
                    matches.append(r)
        if len(matches) >= 5:
            break
    first_kws = candidates[0][0]
    return {
        'source_title': first_kws[0],
        'source_author': first_kws[1] if len(first_kws) > 1 else '',
        'source_url': candidates[0][1],
        'matches': matches[:5],
        'ocr_texts': ocr_texts[:6],
    }


# 排行榜 API 映射（jmcomic 原生支持，返回 JmSearchPage 与搜索同构）
RANK_METHODS = {'day': 'day_ranking', 'week': 'week_ranking', 'month': 'month_ranking'}


def get_ranking(rank_type, max_pages=3):
    """
    排行榜（day/week/month）：只拉榜单页（自带标题/标签），**零详情请求**，3 页 <3 秒。
    榜单页无作者/章节数字段（值为空），渲染端做兼容。

    :return: list[dict{id,title,author,chapter_count}]；请求失败返回 None
    """
    method = RANK_METHODS.get(rank_type)
    if not method:
        return None
    try:
        option = _apply_proxy(JmOption.default())
        client = option.new_jm_client()
        rank_fn = getattr(client, method)
    except Exception:
        return None
    results, seen = [], set()
    for page in range(1, max_pages + 1):
        try:
            items = list(rank_fn(page=page).iter_id_title_tag())
        except Exception:
            break  # 该榜单没有更多页或请求失败
        if not items:
            break
        for aid, title, tags in items:
            if aid in seen:
                continue
            seen.add(aid)
            results.append({'id': str(aid), 'title': title or '',
                            'author': '', 'chapter_count': 0})
    # ponytail: 截断120本（与搜索一致，翻页够用）
    return results[:120]


# 今日属性标签池（随机抽一个标签，搜该标签随机附赠一本）
FUN_TAGS = [
    'NTR', '纯爱', '人妻', '女仆', '百合', '触手', '后宫', '制服', '催眠', '调教',
    '姐弟', '母女', '痴女', '寝取', '巨乳', '贫乳', '熟女', '辣妹', '黑丝', '白丝',
    '露出', '泳装', '兔女郎', '巫女', '护士', 'OL', '教师', '学生', '青梅竹马', '姐妹',
    '猫娘', '魅魔', '精灵', '兽耳', '异世界', '时间停止',
]


def get_random_tag_album():
    """
    今日属性：从标签池随机挑一个标签，该标签搜索里挑一本**章节数最少**的（好下载）。
    候选 3 本并发详情，约 1-2 秒。

    :return: dict{tag, id, title, author, chapter_count}；连续3次失败返回 None
    """
    import random

    for _ in range(3):
        tag = random.choice(FUN_TAGS)
        try:
            option = _apply_proxy(JmOption.default())
            client = option.new_jm_client()
            items = list(client.search_tag(tag).iter_id_title())
        except Exception:
            continue  # 该标签搜索失败，换下一个标签
        if items:
            pick = _pick_smallest_chapters(items[:24], client=client)  # 复用 client 提速
            if pick:
                pick['tag'] = tag
                return pick
    return None


def cancel_download(album_id, work_dir=None):
    """
    标记取消下载。不立即删除目录（避免与正在进行的 ZIP 打包读文件竞态，
    导致 FileNotFoundError）；下载线程会在数秒内通过断出检查停止，
    由 handle_jm_request 的取消分支或 cleanup_cancelled 统一清理。
    """
    album_id = str(album_id)
    CANCELLED_ALBUMS.add(album_id)
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

    def _do_download():
        try:
            # 下载 + 自动打包ZIP（Feature.export_zip 在整本下载完后合并打包）
            # 使用 CancelableDownloader 支持下载中取消
            extra = Feature.export_zip
            if ZIP_ENCRYPT:
                # 加密打包（AES-128），防QQ内容扫描
                extra = Feature.export_zip(encrypt={'type': 'password', 'password': ZIP_PASSWORD})
            return download_album(album_id, option, downloader=CancelableDownloader, extra=extra)
        except Exception as e:
            if str(album_id) in CANCELLED_ALBUMS:
                raise DownloadCancelledError(f'用户取消了下载: {album_id}') from e
            raise

    try:
        result = _do_download()
    except DownloadCancelledError:
        raise
    except Exception:
        # 下载失败自动重试一次：清理半成品（禁漫 CDN 波动/限流常见），重试时 jmcomic 域名刷新会换 CDN
        try:
            shutil.rmtree(task_dir, ignore_errors=True)
            os.makedirs(task_dir, exist_ok=True)
            result = _do_download()
        except DownloadCancelledError:
            raise
        except Exception:
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
