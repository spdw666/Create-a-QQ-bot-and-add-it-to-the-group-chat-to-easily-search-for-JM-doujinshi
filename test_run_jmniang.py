# -*- coding: utf-8 -*-
"""本地启动器的离线配置测试。"""

import os

import pytest

from run_jmniang import load_local_env, parse_env_text, validate_settings


def test_parse_env_text_accepts_comments_quotes_and_export():
    values = parse_env_text("""
        # comment
        JM_ZIP_PASSWORD='safe value'
        export JM_PUBLIC_IP = example.test
    """)
    assert values == {'JM_ZIP_PASSWORD': 'safe value', 'JM_PUBLIC_IP': 'example.test'}


def test_parse_env_text_rejects_invalid_line():
    with pytest.raises(ValueError, match='缺少 ='):
        parse_env_text('NOT_AN_ASSIGNMENT')


def test_load_local_env_does_not_override_explicit_environment(tmp_path, monkeypatch):
    env_file = tmp_path / '.env'
    env_file.write_text('JM_ZIP_PASSWORD=file-value\nJM_PUBLIC_IP=example.test\n', encoding='utf-8')
    monkeypatch.setenv('JM_ZIP_PASSWORD', 'shell-value')
    monkeypatch.delenv('JM_PUBLIC_IP', raising=False)
    assert load_local_env(env_file) is True
    assert os.environ['JM_ZIP_PASSWORD'] == 'shell-value'
    assert os.environ['JM_PUBLIC_IP'] == 'example.test'


def test_validate_settings_requires_non_placeholder_password():
    with pytest.raises(ValueError, match='JM_ZIP_PASSWORD'):
        validate_settings({'JM_ZIP_PASSWORD': 'CHANGE_ME', 'JM_PUBLIC_IP': 'example.test'})


def test_validate_settings_accepts_valid_configuration_and_warns_for_loopback():
    settings, warnings = validate_settings({
        'JM_ZIP_PASSWORD': 'long-random-password',
        'JM_PUBLIC_IP': '127.0.0.1',
        'JM_HTTP_BIND': '127.0.0.1',
        'JM_HTTP_PORT': '9080',
    })
    assert settings.http_port == 9080
    assert settings.http_bind == '127.0.0.1'
    assert len(warnings) == 1


def test_validate_settings_rejects_invalid_http_port():
    with pytest.raises(ValueError, match='JM_HTTP_PORT'):
        validate_settings({
            'JM_ZIP_PASSWORD': 'long-random-password',
            'JM_PUBLIC_IP': 'example.test',
            'JM_HTTP_PORT': '99999',
        })
