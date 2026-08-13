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

    # 1. 说明
    run('说明')
    assert len(sent) == 1 and '使用说明' in sent[0][1]['message']
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
    # 7. 无结果关键词文案
    jm_niang.search_album = lambda kw, n=5: []
    run('无此本子')
    assert sent[-1][1]['message'] == '没有找到该关键词所对应的本子'
