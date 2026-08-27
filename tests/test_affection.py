"""好感度系统核心逻辑测试（纯函数 + 表逻辑，不依赖 LLM/bot）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core import affection
from core.userdb import db


# ---- 阶段 / 羁绊映射 ----
def test_stage_of():
    assert affection.stage_of(0) == "初识"
    assert affection.stage_of(24) == "初识"
    assert affection.stage_of(25) == "熟悉"
    assert affection.stage_of(49) == "熟悉"
    assert affection.stage_of(50) == "亲密"
    assert affection.stage_of(74) == "亲密"
    assert affection.stage_of(75) == "恋人"
    assert affection.stage_of(100) == "恋人"


def test_bond_level():
    assert affection.bond_level(70) is None
    assert affection.bond_level(75)[0] == "眷恋"
    assert affection.bond_level(84)[0] == "眷恋"
    assert affection.bond_level(85)[0] == "热恋"
    assert affection.bond_level(94)[0] == "热恋"
    assert affection.bond_level(95)[0] == "白头"
    assert affection.bond_level(100)[0] == "白头"


# ---- 检测函数 ----
def test_check_care():
    assert affection.check_care("你累不累")
    assert affection.check_care("辛苦了")
    assert affection.check_care("想你了")
    assert not affection.check_care("今天天气不错")
    assert not affection.check_care("我吃了个苹果")


def test_check_nickname_used():
    assert affection.check_nickname_used("菟菚晚安", "菟菚")
    assert not affection.check_nickname_used("晚安", "菟菚")
    assert not affection.check_nickname_used("菟菚", None)
    assert not affection.check_nickname_used("菟菚", "你")


def test_check_abuse():
    assert affection.check_abuse("你真是个傻逼")
    assert affection.check_abuse("SB")
    assert not affection.check_abuse("今天天气不错")


# ---- describe 进度条 ----
def test_describe_with_progress():
    db.ensure_user("pytest-aff")
    db.set_affection_absolute("pytest-aff", 72)
    desc = affection.describe("pytest-aff")
    assert "亲密" in desc
    assert "█" in desc  # 进度条
    assert "3 点" in desc  # 距下一阶段
    db.set_affection_absolute("pytest-aff", 88)
    desc2 = affection.describe("pytest-aff")
    assert "恋人" in desc2
    assert "热恋" in desc2  # 羁绊等级
    # 清理
    db.conn.execute("DELETE FROM users WHERE user_id=?", ("pytest-aff",))
    db.conn.execute("DELETE FROM affection_log WHERE user_id=?", ("pytest-aff",))
    db.conn.commit()


# ---- 每日奖励去重 ----
def test_daily_bonus_dedup():
    db.ensure_user("pytest-bonus")
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", ("pytest-bonus",))
    db.conn.commit()
    first = affection.try_daily_bonus("pytest-bonus", "care", 1, "测试")
    second = affection.try_daily_bonus("pytest-bonus", "care", 1, "测试")
    assert first is True
    assert second is False  # 当天已给过
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", ("pytest-bonus",))
    db.conn.execute("DELETE FROM users WHERE user_id=?", ("pytest-bonus",))
    db.conn.execute("DELETE FROM affection_log WHERE user_id=?", ("pytest-bonus",))
    db.conn.commit()


# ---- 单日扣分上限 ----
def test_penalty_limit():
    db.ensure_user("pytest-pen")
    db.conn.execute("DELETE FROM affection_log WHERE user_id=?", ("pytest-pen",))
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", ("pytest-pen",))
    db.conn.commit()
    db.set_affection_absolute("pytest-pen", 90)
    # 插入 3 笔 -3（模拟当天已扣 -9）
    from datetime import date

    today = date.today().isoformat()
    for i in range(3):
        db.conn.execute(
            "INSERT INTO affection_log (user_id, delta, reason, ts) VALUES (?,?,?,?)",
            ("pytest-pen", -3, "测试", f"{today}T01:00:0{i}"),
        )
    db.conn.commit()
    assert affection._daily_penalty_total("pytest-pen") == -9
    assert affection._penalty_ok("pytest-pen", -3) is False  # -12 < -10 → 拒绝
    assert affection._penalty_ok("pytest-pen", -1) is True  # -10 → 允许
    db.conn.execute("DELETE FROM affection_log WHERE user_id=?", ("pytest-pen",))
    db.conn.execute("DELETE FROM users WHERE user_id=?", ("pytest-pen",))
    db.conn.commit()
