"""卡片渲染测试：好感度/心情/日程图片卡片能正常生成且尺寸合理。"""
import pytest

from core.cards import render_affection_card, render_mood_card, render_schedule_card


def test_affection_card_png():
    b = render_affection_card(
        user_id="t1",
        affection=68,
        stage="亲密",
        next_threshold=75,
        bond=("眷恋", "描述"),
    )
    assert b is not None
    # PNG 魔数
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(b) > 500


def test_affection_card_all_stages():
    for stage in ("初识", "熟悉", "亲密", "恋人"):
        b = render_affection_card(
            user_id="t1",
            affection={"初识": 10, "熟悉": 30, "亲密": 60, "恋人": 90}[stage],
            stage=stage,
            next_threshold=None if stage == "恋人" else 75,
            bond=("眷恋", "x") if stage == "恋人" else None,
        )
        assert b is not None
        assert b[:4] == b"\x89PNG"


def test_affection_card_max_stage():
    # 恋人满级：无下一阶段
    b = render_affection_card(
        user_id="t1", affection=100, stage="恋人", next_threshold=None, bond=("白头", "x")
    )
    assert b is not None


def test_mood_card_png():
    b = render_mood_card(mood=72, label="开心", desc="今天心情不错", weather="今日天气：晴 · 基线 75")
    assert b is not None
    assert b[:8] == b"\x89PNG\r\n\x1a\n"


def test_mood_card_all_labels():
    for label in ("雀跃", "开心", "平淡", "低落", "慵懒"):
        b = render_mood_card(mood=50, label=label, desc="测试", weather="")
        assert b is not None


def test_schedule_card_png():
    items = [
        {"period": "早上", "todo": "赖床到九点"},
        {"period": "上午", "todo": "晒太阳发呆"},
        {"period": "中午", "todo": "吃个午饭"},
        {"period": "下午", "todo": "追番补番"},
        {"period": "晚上", "todo": "陪你聊天"},
        {"period": "深夜", "todo": "想你还不睡"},
    ]
    b = render_schedule_card(items=items, head="今天我是这样安排哒")
    assert b is not None
    assert b[:8] == b"\x89PNG\r\n\x1a\n"


def test_schedule_card_empty():
    b = render_schedule_card(items=[], head="")
    assert b is not None
