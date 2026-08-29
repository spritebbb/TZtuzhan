# -*- coding: utf-8 -*-
"""WebUI 面板 pytest 测试：页面渲染 + 开关 API + 数据管理。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from core.features import set_flag, flag
import webui

client = TestClient(webui.app)


@pytest.fixture(autouse=True)
def _restore_flags():
    set_flag("profile_enabled", True)
    set_flag("terms_enabled", True)
    set_flag("style_enabled", True)
    set_flag("emotion_sticker_enabled", True)
    yield
    set_flag("profile_enabled", True)
    set_flag("terms_enabled", True)
    set_flag("style_enabled", True)
    set_flag("emotion_sticker_enabled", True)


def test_dashboard():
    r = client.get("/")
    assert r.status_code == 200
    assert "菟菚" in r.text
    assert "仪表盘" in r.text


def test_all_pages():
    for path in ("/features", "/profile", "/terms", "/style", "/stickers", "/logs", "/chat"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} failed"


def test_flag_api():
    r = client.get("/api/flag/terms_enabled/0")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert flag("terms_enabled") is False
    # 恢复
    client.get("/api/flag/terms_enabled/1")
    assert flag("terms_enabled") is True


def test_flag_api_unknown_name():
    r = client.get("/api/flag/nonexistent_flag/0")
    assert r.status_code == 200
    # 未知开关不应被写入（默认 True）
    assert flag("nonexistent_flag") is True
