# -*- coding: utf-8 -*-
"""WebUI 面板 pytest 测试：全部页面渲染 + 功能开关 API + 数据管理写操作。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from core.features import set_flag, flag
import webui

client = TestClient(webui.app)

# 所有页面路径（含新增）
ALL_PAGES = (
    "/", "/features", "/affection", "/mood", "/dates", "/memory",
    "/profile", "/terms", "/style", "/stickers", "/chat", "/logs", "/system",
)

# 真实用户（测试库里有数据时）
_UID = webui._first_uid()


@pytest.fixture(autouse=True)
def _restore_flags():
    for k in ("profile_enabled", "terms_enabled", "style_enabled", "emotion_sticker_enabled"):
        set_flag(k, True)
    yield
    for k in ("profile_enabled", "terms_enabled", "style_enabled", "emotion_sticker_enabled"):
        set_flag(k, True)


def test_dashboard():
    r = client.get("/")
    assert r.status_code == 200
    assert "菟菚" in r.text
    assert "仪表盘" in r.text


def test_all_pages():
    for path in ALL_PAGES:
        r = client.get(path)
        assert r.status_code == 200, f"{path} failed"


def test_flag_api():
    r = client.get("/api/flag/terms_enabled/0")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert flag("terms_enabled") is False
    client.get("/api/flag/terms_enabled/1")
    assert flag("terms_enabled") is True


def test_flag_api_unknown_name():
    r = client.get("/api/flag/nonexistent_flag/0")
    assert r.status_code == 200
    assert flag("nonexistent_flag") is True


def test_affection_set():
    if not _UID:
        pytest.skip("无用户数据")
    before = webui._q1("SELECT affection FROM users WHERE user_id=?", (_UID,))["affection"]
    target = 60 if before != 60 else 61
    r = client.post("/affection/set", data={"value": str(target), "reason": "pytest 测试"})
    assert r.status_code in (200, 302)
    after = webui._q1("SELECT affection FROM users WHERE user_id=?", (_UID,))["affection"]
    assert after == target
    # 还原
    client.post("/affection/set", data={"value": str(before), "reason": "pytest 还原"})
    restored = webui._q1("SELECT affection FROM users WHERE user_id=?", (_UID,))["affection"]
    assert restored == before
    # 日志里应有 pytest 记录
    logs = webui._q("SELECT reason FROM affection_log WHERE user_id=? ORDER BY id DESC LIMIT 10", (_UID,))
    assert any("pytest" in (l["reason"] or "") for l in logs)


def test_mood_set():
    if not _UID:
        pytest.skip("无用户数据")
    r = client.post("/mood/set", data={"value": "70", "reset": ""})
    assert r.status_code in (200, 302)
    assert webui._q1("SELECT mood_value FROM users WHERE user_id=?", (_UID,))["mood_value"] == 70
    # 重置
    client.post("/mood/set", data={"value": "0", "reset": "1"})
    assert webui._q1("SELECT mood_value FROM users WHERE user_id=?", (_UID,))["mood_value"] == 60


def test_dates_add_and_delete():
    if not _UID:
        pytest.skip("无用户数据")
    # 添加一条测试日子
    r = client.post("/dates/add", data={"date": "12-31", "label": "pytest测试日", "kind": "other", "year": ""})
    assert r.status_code in (200, 302)
    row = webui._q1("SELECT id FROM important_dates WHERE user_id=? AND label='pytest测试日'", (_UID,))
    assert row, "应能添加特殊日子"
    # 删除
    r = client.post(f"/dates/delete/{row['id']}")
    assert r.status_code in (200, 302)
    assert webui._q1("SELECT id FROM important_dates WHERE id=?", (row["id"],)) is None


def test_memory_delete_handles_missing():
    # 删除不存在的记录不应崩溃
    r = client.post("/memory/lm/delete/999999")
    assert r.status_code in (200, 302)
    r = client.post("/memory/fact/delete/999999")
    assert r.status_code in (200, 302)


def test_nav_has_all_links():
    r = client.get("/")
    for path in ALL_PAGES:
        assert f'href="{path}"' in r.text, f"导航应包含 {path}"
