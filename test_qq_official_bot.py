# -*- coding: utf-8 -*-
"""验证 qq_official_bot.py 的命令路由与按钮 payload（离线，mock 禁漫函数）"""
import qq_official_bot as bot


def test_process_command_menu(monkeypatch):
    # 纯@/菜单/说明 → 返回菜单
    assert bot.process_command('') == (True, None)
    assert bot.process_command('菜单')[0] is True
    assert bot.process_command('说明')[0] is True
    assert bot.process_command('help')[0] is True


def test_process_command_random(monkeypatch):
    bot.get_random_hot_album = lambda: {'id': '123456', 'title': '随机本',
                                        'author': '作者A', 'chapter_count': 3}
    is_menu, reply = bot.process_command('随机')
    assert is_menu is False
    assert '随机推荐' in reply and '123456' in reply and '/jm123456' in reply


def test_process_command_today(monkeypatch):
    bot.get_random_tag_album = lambda: {'tag': 'NTR', 'id': '654321',
                                        'title': '属性本', 'author': 'B', 'chapter_count': 2}
    is_menu, reply = bot.process_command('今日属性')
    assert is_menu is False
    assert 'NTR' in reply and '654321' in reply


def test_process_command_rank(monkeypatch):
    bot.get_ranking = lambda rt: [{'title': '榜1', 'id': '400000', 'chapter_count': 1}]
    is_menu, reply = bot.process_command('日榜')
    assert is_menu is False and '日榜' in reply and '400000' in reply
    # 周榜/月榜路由
    assert bot.process_command('周榜')[1] is not None
    assert bot.process_command('月榜')[1] is not None


def test_process_command_search(monkeypatch):
    bot.search_album = lambda kw, n=5: [{'title': '本1', 'id': '100000', 'chapter_count': 1}]
    is_menu, reply = bot.process_command('人妻')
    assert is_menu is False and '关键词' in reply and '100000' in reply


def test_process_command_download(monkeypatch):
    # /jm数字 和 纯数字 → 提示走个人号
    is_menu, reply = bot.process_command('/jm1460484')
    assert is_menu is False and '下载' in reply and '/jm1460484' in reply
    is_menu2, reply2 = bot.process_command('1460484')
    assert '/jm1460484' in reply2


def test_button_payload(monkeypatch):
    payload = bot._button_payload(bot._BUTTON_ROWS)
    assert 'content' in payload and 'rows' in payload['content']
    first_btn = payload['content']['rows'][0]['buttons'][0]
    assert first_btn['action']['type'] == 2  # 指令按钮
    assert first_btn['action']['data'] == '随机'
    assert first_btn['render_data']['label'] == '🐲 随机'
