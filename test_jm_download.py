# -*- coding: utf-8 -*-
"""JM娘 核心逻辑测试：ZIP 加密配置与检测"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 测试用 ZIP 密码（生产环境通过环境变量 JM_ZIP_PASSWORD 配置，见 jm_download.py）
TEST_PASSWORD = 'test-pass-123'
os.environ.setdefault('JM_ZIP_PASSWORD', TEST_PASSWORD)


def test_zip_encrypt_constants():
    from jm_download import ZIP_ENCRYPT, ZIP_PASSWORD
    assert ZIP_ENCRYPT is True
    assert ZIP_PASSWORD == TEST_PASSWORD


def test_is_zip_encrypted_false(tmp_path):
    """未加密 ZIP 应返回 False"""
    from jm_download import is_zip_encrypted
    z = tmp_path / 'plain.zip'
    with zipfile.ZipFile(z, 'w') as f:
        f.writestr('a.txt', 'hello')
    assert is_zip_encrypted(str(z)) is False


def test_is_zip_encrypted_true(tmp_path):
    """AES 加密 ZIP 应返回 True（模拟 jmcomic 加密打包产物）"""
    from jm_download import is_zip_encrypted
    import pyzipper
    z = tmp_path / 'enc.zip'
    with pyzipper.AESZipFile(z, 'w', pyzipper.ZIP_DEFLATED) as f:
        f.setencryption(pyzipper.WZ_AES, nbits=128)
        f.setpassword(TEST_PASSWORD.encode())
        f.writestr('a.txt', 'hello')
    assert is_zip_encrypted(str(z)) is True


def test_ensure_encrypted_zip_converts(tmp_path):
    """未加密ZIP应被现场转换为AES加密ZIP（QQ内容扫描绕过）"""
    from jm_download import ensure_encrypted_zip, is_zip_encrypted, ZIP_PASSWORD
    import pyzipper
    z = tmp_path / 'plain.zip'
    with zipfile.ZipFile(z, 'w') as f:
        f.writestr('a.txt', 'secret content')
        f.writestr('b.txt', 'more content')
    assert is_zip_encrypted(str(z)) is False
    out = ensure_encrypted_zip(str(z))
    assert out == str(z)
    assert is_zip_encrypted(str(z)) is True
    # 加密后可读且内容一致（用密码解出）
    with pyzipper.AESZipFile(str(z)) as f:
        f.setpassword(ZIP_PASSWORD.encode())
        assert f.read('a.txt').decode() == 'secret content'


def test_ensure_encrypted_zip_skips_encrypted(tmp_path):
    """已加密ZIP不应重复转换"""
    from jm_download import ensure_encrypted_zip, is_zip_encrypted
    import pyzipper
    z = tmp_path / 'enc.zip'
    with pyzipper.AESZipFile(z, 'w', pyzipper.ZIP_DEFLATED) as f:
        f.setencryption(pyzipper.WZ_AES, nbits=128)
        f.setpassword(TEST_PASSWORD.encode())
        f.writestr('a.txt', 'hello')
    out = ensure_encrypted_zip(str(z))
    assert out == str(z)
    assert is_zip_encrypted(str(z)) is True


def test_import_jm_niang():
    """主程序可正常导入，关键配置存在"""
    import jm_niang
    assert jm_niang.WS_PORT == 8081
    assert '压缩包带密码' in jm_niang.HELP_TEXT


def test_escape_cq_blocks_injection():
    """恶意关键词/标题中的 [CQ:...] 码应被转义，防止机器人被利用@全体/发图"""
    from jm_niang import escape_cq
    out = escape_cq('[CQ:at,qq=all] 看 & 链接, 快来看')
    assert '[CQ:at' not in out
    assert '&#91;CQ' in out
    assert '&amp;' in out
    assert '&#44;' in out
    assert '\n' not in escape_cq('a\nb')


def test_parse_etime():
    """ps etime 三种格式：MM:SS / HH:MM:SS / D-HH:MM:SS"""
    import jm_niang
    p = jm_niang._parse_etime
    assert p('08:44') == 8 * 60 + 44
    assert p('07:46:00') == 7 * 3600 + 46 * 60
    assert p('2-03:04:05') == 2 * 86400 + 3 * 3600 + 4 * 60 + 5
    assert p('') is None
    assert p('abc') is None


def test_search_album_sanitize_injection_chars():
    """&/= 注入字符应被清洗；清洗后为空则不发起搜索"""
    from jm_download import search_album
    assert search_album('&=') == []
    assert search_album(None) == []
    assert search_album('  ') == []


def test_build_keywords_variants():
    """搜索变体：原文 + 简转繁 + 中日异体字（简体琉璃川应生成日文汉字瑠璃川变体）"""
    from jm_download import _build_keywords
    assert _build_keywords('琉璃川') == ['琉璃川', '瑠璃川']
    assert _build_keywords('人妻') == ['人妻']  # 简繁同形，不重复
    v = _build_keywords('灭霸之战')
    assert '滅霸之戰' in v and '灭霸之戦' in v
    assert _build_keywords('メイド教育') == ['メイド教育']  # 日文原样保留
    assert '枫と铃' in _build_keywords('枫与铃')  # 中文虚词→日文假名
    assert '楓與鈴' in _build_keywords('枫与铃')  # 简转繁


def test_core_chars_and_title_match():
    """核心字降级搜索：虚词被过滤，标题含全部核心字（含变体）即命中"""
    from jm_download import _core_chars, _title_match
    assert _core_chars('枫与铃') == ['枫', '铃']
    assert _core_chars('人妻') == ['人', '妻']
    assert _title_match('枫と铃', ['枫', '铃']) is True
    assert _title_match('楓與鈴', ['枫', '铃']) is True  # 繁体/异体变体也命中
    assert _title_match('枫糖', ['枫', '铃']) is False  # 缺核心字不命中


def test_extract_author():
    """作者搜索命令解析：'作者 xxx' / '作者:xxx' / 'author xxx'；非作者命令返回 None"""
    from jm_niang import extract_author
    assert extract_author('作者 きょくちょ') == 'きょくちょ'
    assert extract_author('作者:柚木N') == '柚木N'
    assert extract_author('作者：きょくちょ') == 'きょくちょ'
    assert extract_author('author 柚木N') == '柚木N'
    assert extract_author('人妻') is None
    assert extract_author('作者') is None
    assert extract_author('') is None


def test_extract_tag():
    """标签搜索命令解析：'标签 xxx' / '标签:xxx' / 'tag xxx'；非标签命令返回 None"""
    from jm_niang import extract_tag
    assert extract_tag('标签 人妻') == '人妻'
    assert extract_tag('标签:百合') == '百合'
    assert extract_tag('tag 触手') == '触手'
    assert extract_tag('人妻') is None
    assert extract_tag('标签') is None


def test_extract_page():
    """页码跳转解析：'第2页' / '第 2 页' / '2页' / 中文数字'第四页'；聊天文本不误触发"""
    from jm_niang import extract_page
    assert extract_page('第2页') == 2
    assert extract_page('第 2 页') == 2
    assert extract_page('2页') == 2
    assert extract_page('第12页') == 12
    assert extract_page('第1页') == 1
    assert extract_page('第四页') == 4
    assert extract_page('第十页') == 10
    assert extract_page('第十二页') == 12
    assert extract_page('第二十五页') == 25
    assert extract_page('二十页') == 20
    assert extract_page('四页') == 4  # 不带「第」也可
    assert extract_page('你看第3页') is None  # 带前后缀的聊天文本不是命令
    assert extract_page('下一页') is None
    assert extract_page('') is None


def test_render_search_page():
    """翻页渲染：每页5本、全局序号、页数/总数、末页提示"""
    import jm_niang
    results = [{'title': f'本{i}', 'chapter_count': 1, 'id': str(100000 + i), 'author': 'a'}
               for i in range(12)]
    state = {'head': '🔍 关键词「x」', 'results': results, 'page': 1, 'ts': 0}
    p1 = jm_niang.render_search_page(state, 1)
    assert '第 1/3 页' in p1 and '共 12 本' in p1
    assert '1. 《本0》' in p1 and '5. 《本4》' in p1
    assert '6. ' not in p1  # 第1页不含第6本
    assert '下一页' in p1  # 非末页提示翻页
    p2 = jm_niang.render_search_page(state, 2)
    assert '6. 《本5》' in p2 and '10. 《本9》' in p2  # 全局序号连续
    p3 = jm_niang.render_search_page(state, 3)
    assert '11. 《本10》' in p3 and '12. 《本11》' in p3
    assert '已查看完全部结果' in p3  # 末页提示
    assert '下一页' not in p3


def test_handle_message_branches():
    """消息层端到端：mock 群消息事件与 API，验证各命令路由与回复内容"""
    import asyncio
    import time as _time
    import jm_niang
    from jm_niang import handle_message, SEARCH_COOLDOWN, SEARCH_STATE

    BOT_QQ = '2337295608'
    GROUP = 810152420
    sent = []

    async def fake_api(action, params=None, timeout=60):
        sent.append((action, params))
        return {'retcode': 0, 'status': 'ok', 'data': {}}

    def mk_msg(text, at=True):
        segs = []
        if at:
            segs.append({'type': 'at', 'data': {'qq': BOT_QQ}})
        segs.append({'type': 'text', 'data': {'text': text}})
        return {'post_type': 'message', 'message_type': 'group',
                'group_id': GROUP, 'user_id': 999, 'message': segs}

    def run(text):
        sent.clear()
        SEARCH_COOLDOWN.clear()  # 测试间清除冷却
        asyncio.run(handle_message(None, fake_api, mk_msg(text), BOT_QQ))

    def run_no_at(text):
        """免@消息（普通群消息，未@机器人）"""
        sent.clear()
        SEARCH_COOLDOWN.clear()
        asyncio.run(handle_message(None, fake_api, mk_msg(text, at=False), BOT_QQ))

    def run_img(text):
        """@机器人 + 图片段消息（以图搜本）"""
        sent.clear()
        SEARCH_COOLDOWN.clear()
        msg = mk_msg(text)
        msg['message'].append({'type': 'image', 'data': {'url': 'http://fake/1.jpg', 'file': ''}})
        asyncio.run(handle_message(None, fake_api, msg, BOT_QQ))

    def run_img_no_at():
        """免@图片消息（识图等待窗口测试）"""
        sent.clear()
        SEARCH_COOLDOWN.clear()
        msg = mk_msg('', at=False)
        msg['message'].append({'type': 'image', 'data': {'url': 'http://fake/1.jpg', 'file': ''}})
        asyncio.run(handle_message(None, fake_api, msg, BOT_QQ))

    # 1. 说明
    run('说明')
    assert len(sent) == 1 and '使用说明' in sent[0][1]['message']
    # 1b. 自查：报告进程运行时长与连接状态
    run('自查')
    assert len(sent) == 1 and '自查报告' in sent[0][1]['message'] and '机器人进程' in sent[0][1]['message']
    # 2. 关键词搜索：12本 → 第1页 + 翻页提示 + 状态缓存
    jm_niang.search_album = lambda kw, n=5: [{'title': f'本{i}', 'chapter_count': 1,
                                              'id': str(100000 + i), 'author': 'a'}
                                             for i in range(12)]
    run('人妻')
    joined = '\n'.join(p['message'] for _, p in sent)
    assert '第 1/3 页' in joined and '共 12 本' in joined and '下一页' in joined
    assert SEARCH_STATE.get(GROUP) is not None
    # 3. 翻页：下一页 → 第2页（全局序号6-10）
    run('下一页')
    m2 = sent[0][1]['message']
    assert '第 2/3 页' in m2 and '6. 《本5》' in m2 and '10. 《本9》' in m2
    # 3b. 免@翻页：用户不@机器人直接发「下一页」也能翻页
    run_no_at('下一页')
    m2b = sent[0][1]['message']
    assert '第 3/3 页' in m2b and '12. 《本11》' in m2b
    # 3c. 免@翻页到最后一页后再翻 → 提示最后一页
    run_no_at('翻页')
    assert '最后一页' in sent[0][1]['message']
    # 3d. 免@无状态时静默（普通聊天出现「下一页」不打扰）
    SEARCH_STATE.pop(GROUP, None)
    run_no_at('下一页')
    assert sent == []
    # 3e. 免@时其他文本不响应（聊天内容不触发）
    run_no_at('今天天气不错')
    assert sent == []
    # 3f. 跳页：@机器人 第3页 → 直达第3页
    SEARCH_STATE[GROUP] = {'head': '🔍 关键词「人妻」',
                           'results': [{'title': f'本{i}', 'chapter_count': 1,
                                        'id': str(100000 + i), 'author': 'a'}
                                       for i in range(12)],
                           'page': 1, 'ts': _time.time()}
    run('第3页')
    m3f = sent[0][1]['message']
    assert '第 3/3 页' in m3f and '11. 《本10》' in m3f
    # 3g. 免@跳回第1页
    run_no_at('第1页')
    m3g = sent[0][1]['message']
    assert '第 1/3 页' in m3g and '1. 《本0》' in m3g
    # 3h. 越界跳转收敛到最后一页
    run_no_at('第99页')
    m3h = sent[0][1]['message']
    assert '第 3/3 页' in m3h
    # 3i. 聊天里「你看第3页」不是跳转命令
    run_no_at('你看第3页')
    assert sent == []
    SEARCH_STATE.pop(GROUP, None)
    # 4. 作者搜索
    jm_niang.search_author_album = lambda a, n=5: [{'title': f'{a}本{i}', 'chapter_count': 1,
                                                    'id': str(200000 + i), 'author': a}
                                                   for i in range(3)]
    run('作者 きょくちょ')
    joined3 = '\n'.join(p['message'] for _, p in sent)
    assert '作者「きょくちょ」' in joined3 and 'ID：200000' in joined3
    # 5. 作者无结果文案
    jm_niang.search_author_album = lambda a, n=5: []
    run('作者 不存在')
    assert sent[-1][1]['message'] == '没有找到该作者所对应的本子'
    # 6. 随机推荐
    jm_niang.get_random_hot_album = lambda: {'id': '123456', 'title': '随机本',
                                             'author': '作者A', 'chapter_count': 3}
    run('随机')
    joined6 = '\n'.join(p['message'] for _, p in sent)
    assert '随机推荐' in joined6 and 'ID：123456' in joined6
    # 6b. 今日属性：@原用户 + 属性 + 附赠本子
    jm_niang.get_random_tag_album = lambda: {'tag': 'NTR', 'id': '654321',
                                             'title': '属性本', 'author': '作者B',
                                             'chapter_count': 2}
    run('今日属性')
    joined_tag = '\n'.join(p['message'] for _, p in sent)
    assert '[CQ:at,qq=999]' in joined_tag  # @原请求用户
    assert '今日你的属性是【NTR】' in joined_tag
    assert 'ID：654321' in joined_tag
    assert '《属性本》' in joined_tag
    # 6c. 今日属性失败提示
    jm_niang.get_random_tag_album = lambda: None
    run('今日属性')
    assert '占卜失败' in sent[-1][1]['message']
    # 6d. 标签搜索
    jm_niang.search_tag_album = lambda t, n=5: [{'title': f'{t}本{i}', 'chapter_count': 1,
                                                 'id': str(300000 + i), 'author': 'a'}
                                                for i in range(3)]
    run('标签 人妻')
    joined_tag_s = '\n'.join(p['message'] for _, p in sent)
    assert '标签「人妻」' in joined_tag_s and 'ID：300000' in joined_tag_s
    # 6e. 标签无结果文案
    jm_niang.search_tag_album = lambda t, n=5: []
    run('标签 不存在')
    assert sent[-1][1]['message'] == '没有找到该标签所对应的本子'
    # 6f. 排行榜
    jm_niang.get_ranking = lambda rt: [{'title': f'榜{i}', 'chapter_count': 1,
                                        'id': str(400000 + i), 'author': 'a'}
                                       for i in range(8)]
    run('日榜')
    joined_rank = '\n'.join(p['message'] for _, p in sent)
    assert '日榜' in joined_rank and '第 1/2 页' in joined_rank and 'ID：400000' in joined_rank
    # 6g. 以图搜本：@机器人 + 图片 → 识图回复含来源与禁漫匹配
    jm_niang.fetch_image_bytes = lambda ref: b'fake-img'
    jm_niang.search_by_image = lambda b: {'source_title': '楓と鈴', 'source_author': 'きょくちょ',
                                          'source_url': 'https://example.com/1',
                                          'matches': [{'title': '楓と鈴 (全)', 'chapter_count': 1,
                                                       'id': '1235379', 'author': 'きょくちょ'}]}
    run_img('以图搜本测试')
    joined_img = '\n'.join(p['message'] for _, p in sent)
    assert '识图结果' in joined_img and '楓と鈴' in joined_img and 'ID：1235379' in joined_img
    # 6h. 识图失败提示
    jm_niang.search_by_image = lambda b: None
    run_img('识图失败测试')
    assert '识图失败' in sent[-1][1]['message']
    # 6i. 识图意图：@识图 → 进入等待窗口
    jm_niang.search_by_image = lambda b: {'source_title': 'T', 'source_author': '',
                                          'source_url': '', 'matches': [],
                                          'ocr_texts': ['T']}
    run('识图')
    assert '秒内直接发送图片' in sent[-1][1]['message']
    assert GROUP in jm_niang.IMAGE_WAIT
    # 6i2. 纯@（空文本）→ 输出按钮功能菜单（不再进入识图等待窗口）
    jm_niang.IMAGE_WAIT.pop(GROUP, None)  # 清掉 6i 设置的等待窗口
    run('')
    assert '命令面板' in sent[-1][1]['message']
    assert GROUP not in jm_niang.IMAGE_WAIT
    # 6j. 等待窗口内免@发图 → 自动识图
    jm_niang.IMAGE_WAIT[GROUP] = {'user_id': 999, 'expires': _time.time() + 20}
    run_img_no_at()
    joined_wait = '\n'.join(p['message'] for _, p in sent)
    assert '识图结果' in joined_wait
    # 6k. 窗口内其他用户发图不触发（user_id 不匹配）
    jm_niang.IMAGE_WAIT[GROUP] = {'user_id': 888, 'expires': _time.time() + 20}
    run_img_no_at()
    assert sent == []  # 无响应
    # 6l. 窗口过期后发图不触发
    jm_niang.IMAGE_WAIT[GROUP] = {'user_id': 999, 'expires': _time.time() - 1}
    run_img_no_at()
    assert sent == []
    # 7. 无结果关键词文案
    jm_niang.search_album = lambda kw, n=5: []
    run('无此本子')
    assert sent[-1][1]['message'] == '没有找到该关键词所对应的本子'
    # 8. 重新搜索：@不对 → 重跑上次搜索（mock 计数验证 search_album 被再次调用）
    call_count = [0]
    def counted_search(kw, n=5):
        call_count[0] += 1
        return [{'title': f'重搜{kw}{i}', 'chapter_count': 1,
                 'id': str(500000 + i), 'author': 'a'} for i in range(2)]
    jm_niang.search_album = counted_search
    run('人妻')
    assert call_count[0] == 1
    run('不对')
    joined_retry = '\n'.join(p['message'] for _, p in sent)
    assert call_count[0] == 2  # 重搜触发了第二次搜索
    assert '重新搜索' in joined_retry and 'ID：500000' in joined_retry
    # 9. 无状态时重搜 → 提示无记录
    SEARCH_STATE.pop(GROUP, None)
    run('错了')
    assert '没有可重新搜索的记录' in sent[0][1]['message']
    # 10. 详情预览：@详情 350234 → 纯文字详情（mock get_album_info，不发图）
    from jm_niang import extract_detail_id, get_album_info as real_get_info
    jm_niang.get_album_info = lambda aid: {
        'title': f'详情本{aid}', 'chapter_count': 2, 'page_count': 50,
        'author': '作者甲', 'tags': ['NTR', '人妻']}
    run('详情 350234')
    m10 = sent[-1][1]['message']
    assert '详情本350234' in m10 and '作者甲' in m10 and 'NTR' in m10 and '50 页' in m10
    assert '350234 即可下载' in m10
    # 10b. 详情无空格/预览/失败文案
    run('详情350234')
    assert '详情本350234' in sent[-1][1]['message']
    run('预览 350234')
    assert '详情本350234' in sent[-1][1]['message']
    jm_niang.get_album_info = lambda aid: None
    run('详情 350234')
    assert '信息失败' in sent[-1][1]['message']
    jm_niang.get_album_info = real_get_info
    # 10c. extract_detail_id 纯函数
    assert extract_detail_id('详情 350234') == '350234'
    assert extract_detail_id('详情350234') == '350234'
    assert extract_detail_id('预览 123456') == '123456'
    assert extract_detail_id('350234') is None  # 纯数字走下载命令，不是详情
    assert extract_detail_id('随便详情') is None
    # 11. 菜单命令：@我 菜单 → 按钮式命令面板
    run('菜单')
    assert '命令面板' in sent[0][1]['message'] and '随机' in sent[0][1]['message']
    run('按钮')
    assert '命令面板' in sent[0][1]['message']
    # 11b. 免@按钮：直接发「随机」触发随机推荐（等同点按钮）
    jm_niang.get_random_hot_album = lambda: {'id': '123456', 'title': '随机本',
                                             'author': '作者A', 'chapter_count': 3}
    run_no_at('随机')
    joined_btn = '\n'.join(p['message'] for _, p in sent)
    assert '随机推荐' in joined_btn and 'ID：123456' in joined_btn
    # 11c. 免@按钮：直接发「今日属性」触发
    jm_niang.get_random_tag_album = lambda: {'tag': 'NTR', 'id': '654321',
                                             'title': '属性本', 'author': '作者B',
                                             'chapter_count': 2}
    run_no_at('今日属性')
    assert '今日你的属性是【NTR】' in sent[-1][1]['message']
    # 11d. 免@按钮：直接发「日榜」触发榜单
    jm_niang.get_ranking = lambda rt: [{'title': '榜1', 'chapter_count': 1,
                                        'id': '400000', 'author': 'a'}]
    run_no_at('日榜')
    joined_rank_noat = '\n'.join(p['message'] for _, p in sent)
    assert '日榜' in joined_rank_noat and 'ID：400000' in joined_rank_noat
    # 11e. 免@按钮：直接发「任务」触发（无任务时提示）
    jm_niang.ACTIVE_DOWNLOADS.clear() if hasattr(jm_niang, 'ACTIVE_DOWNLOADS') else None
    run_no_at('任务')
    assert ('当前任务' in sent[-1][1]['message'] or '没有正在处理' in sent[-1][1]['message'])
    # 11f. 免@按钮：直接发「自查」触发
    run_no_at('自查')
    assert '自查报告' in sent[-1][1]['message']
    # 11g. 免@按钮：直接发「说明」触发
    run_no_at('说明')
    assert '使用说明' in sent[-1][1]['message']
    # 11h. 免@未命中按钮词（普通聊天）静默
    run_no_at('这是聊天不是命令')
    assert sent == []
    # 11i. NO_AT_BUTTONS 词表完整性（收录了核心无参功能）
    from jm_niang import NO_AT_BUTTONS
    assert '随机' in NO_AT_BUTTONS and '今日属性' in NO_AT_BUTTONS and '日榜' in NO_AT_BUTTONS
    assert '安装包' in NO_AT_BUTTONS and '任务' in NO_AT_BUTTONS and '自查' in NO_AT_BUTTONS


def test_cancelable_downloader_before_image():
    """取消机制：before_image 通过 image.from_photo.from_album.album_id 命中取消标记"""
    import jm_download
    from jm_download import CancelableDownloader, DownloadCancelledError, CANCELLED_ALBUMS

    class FakeAlbum:
        album_id = '542920'

    class FakePhoto:
        from_album = FakeAlbum()

    class FakeImage:
        from_photo = FakePhoto()

    # 清空取消标记
    CANCELLED_ALBUMS.clear()

    # 用 object.__new__ 绕过 JmDownloader.__init__（不需要真实 option），只测 before_image 逻辑
    downloader = object.__new__(CancelableDownloader)

    # 无取消标记：不抛异常，正常调 super().before_image
    img = FakeImage()
    called = {}
    origin_before = jm_download.JmDownloader.before_image
    jm_download.JmDownloader.before_image = lambda self, i, p: called.setdefault('hit', True)
    try:
        downloader.before_image(img, '/tmp/x.webp')  # 不应抛异常
    finally:
        jm_download.JmDownloader.before_image = origin_before
    assert called.get('hit') is True  # 走到了 super().before_image

    # 加取消标记：应抛 DownloadCancelledError
    CANCELLED_ALBUMS.add('542920')
    try:
        downloader.before_image(img, '/tmp/x.webp')
        raised = False
    except DownloadCancelledError:
        raised = True
    assert raised is True

    CANCELLED_ALBUMS.clear()


def test_find_cached_zip_removes_corrupt(tmp_path):
    """find_cached_zip 应移除损坏/无效 PDF... ZIP，返回无缓存而非命中坏缓存"""
    import jm_download
    from jm_download import find_cached_zip

    # 构造一个假漫画目录，放入一个"损坏"的 zip（非 zip 内容）和一个有效 zip
    task_dir = jm_download._task_dir('999999', str(tmp_path))
    import os
    os.makedirs(os.path.join(task_dir, '章节1'), exist_ok=True)

    corrupt = os.path.join(task_dir, '章节1', '[JM999999]坏.xip')
    # 保存副本 .zip 破坏名
    corrupt_zip = corrupt[:-4] + '.zip'
    with open(corrupt_zip, 'w', encoding='utf-8') as f:
        f.write('这不是一个 zip 文件，仅测试损坏缓存')

    # 有效 zip（用真实 zip）
    good_zip = os.path.join(task_dir, '[JM999999]好.zip')
    import zipfile as _zf
    with _zf.ZipFile(good_zip, 'w') as zf:
        zf.writestr('a.txt', 'hello')

    # find_cached_zip：应删除坏 zip，命中好 zip
    path, title = find_cached_zip('999999', str(tmp_path))
    assert title == '好', f'title={title!r}'
    assert os.path.basename(path) == '[JM999999]好.zip'
    # 坏 zip 应已被删除
    assert not os.path.exists(corrupt_zip)

    # 只剩损坏 zip 时：返回 (None, None) 且坏文件被删
    os.remove(good_zip)
    bad = os.path.join(task_dir, '[JM999999]坏2.zip')
    with open(bad, 'w', encoding='utf-8') as f:
        f.write('still not a zip')
    path2, title2 = find_cached_zip('999999', str(tmp_path))
    assert path2 is None and title2 is None
    assert not os.path.exists(bad)
# -*- coding: utf-8 -*-
"""验证取消修复：cancel_download 不再立即删除目录（避免与打包竞态）"""
import os
import jm_download
from jm_download import cancel_download, CANCELLED_ALBUMS


def test_cancel_download_does_not_rmtree(tmp_path):
    """取消只标记，不立即删目录（打包读文件时不被打断）"""
    album = '777777'
    task_dir = jm_download._task_dir(album, str(tmp_path))
    os.makedirs(task_dir, exist_ok=True)
    probe = os.path.join(task_dir, '00001.webp')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write('x')

    CANCELLED_ALBUMS.clear()
    ret = cancel_download(album, str(tmp_path))

    assert ret is True
    # 标记已加
    assert album in CANCELLED_ALBUMS
    # 目录和文件仍在（不立即删除，交给取消分支清理）
    assert os.path.isdir(task_dir)
    assert os.path.exists(probe)

    CANCELLED_ALBUMS.clear()


def test_progress_interval_adaptive():
    """进度条：目标条数随页数减少（20页≈2条、40页≈3条），大本子封顶7条，间隔由总时长/目标条数反推"""
    from jm_niang import _target_progress_msgs, progress_interval, TARGET_PROGRESS_MSGS, \
        AVG_SECONDS_PER_PAGE, PROGRESS_INTERVAL_MIN
    # 小本子目标条数少：20页→2条、40页→3条
    assert _target_progress_msgs(20) == 2
    assert _target_progress_msgs(40) == 3
    assert _target_progress_msgs(15) == 2  # 下限2条
    # 大本子封顶7条
    assert _target_progress_msgs(30000) == TARGET_PROGRESS_MSGS
    # 间隔 = max(下限, 总时长/目标条数)
    assert progress_interval(40) == max(PROGRESS_INTERVAL_MIN, 40 * AVG_SECONDS_PER_PAGE / 3)
    assert progress_interval(30000) == 30000 * AVG_SECONDS_PER_PAGE / TARGET_PROGRESS_MSGS
    # 未知/非正数 → 默认 10s
    assert progress_interval(0) == 10
    assert progress_interval(None) == 10
