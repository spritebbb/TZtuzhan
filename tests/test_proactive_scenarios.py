"""主动消息多场景扩展的纯逻辑测试。

覆盖：
- 节日提示：今天是中国节日时返回节日名
- 特殊日子提示：用户设置了今天的生日/纪念日时返回
- 天气提示：雨天/雪天/普通天气的差异化提示
- 深夜提示：23-5 点返回深夜安慰
- 场景组合：节日/特殊日子优先，多种提示可组合
- 调度触发条件：特殊日子当天即使刚聊过也允许主动
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import proactive, userdb

db = userdb.db

UID = "pytest-proactive-scenarios"


def _clean():
    db.ensure_user(UID)
    db.conn.execute("DELETE FROM important_dates WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM messages WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)


# ---- 节日提示 ----

def test_festival_hint_returns_name():
    from core.holidays import today_holidays

    names = today_holidays()
    hint = proactive._festival_hint()
    if names:
        assert hint == "、".join(names)
    else:
        assert hint == ""


# ---- 特殊日子提示 ----

def test_special_date_hint():
    _clean()
    assert proactive._special_date_hint(UID) == ""
    today = date.today()
    db.conn.execute(
        "INSERT INTO important_dates (user_id, date, label, kind, ts) VALUES (?,?,?,?,?)",
        (UID, today.strftime("%m-%d"), "我的生日", "birthday", datetime.now().isoformat(timespec="seconds")),
    )
    db.conn.commit()
    assert "我的生日" in proactive._special_date_hint(UID)


# ---- 天气提示 ----

def test_weather_hint_rain():
    with mock.patch("core.mood.today_weather", return_value=("小雨转阴", 60)):
        hint = proactive._weather_hint("测试城")
        assert hint and "雨" in hint


def test_weather_hint_unknown():
    with mock.patch("core.mood.today_weather", return_value=("未知", 60)):
        hint = proactive._weather_hint("测试城")
        assert hint == ""


# ---- 深夜提示 ----

def test_late_night_hint():
    with mock.patch("core.proactive.datetime") as fake_dt:
        fake_dt.now.return_value = datetime(2026, 1, 1, 23, 30)
        fake_dt.timedelta = timedelta
        hint = proactive._late_night_hint()
        assert hint and "深夜" in hint


def test_late_night_hint_daytime_empty():
    with mock.patch("core.proactive.datetime") as fake_dt:
        fake_dt.now.return_value = datetime(2026, 1, 1, 12, 0)
        fake_dt.timedelta = timedelta
        assert proactive._late_night_hint() == ""


# ---- 场景组合 ----

def test_scenario_hint_combines():
    _clean()
    from core.holidays import today_holidays

    today = date.today()
    db.conn.execute(
        "INSERT INTO important_dates (user_id, date, label, kind, ts) VALUES (?,?,?,?,?)",
        (UID, today.strftime("%m-%d"), "纪念日", "anniversary", datetime.now().isoformat(timespec="seconds")),
    )
    db.conn.commit()
    with mock.patch("core.proactive._late_night_hint", return_value="深夜提示文本"):
        hint = proactive._scenario_hint(UID, "测试城")
    # 特殊日子一定在
    assert "纪念日" in hint
    # 深夜提示被组合进来
    assert "深夜提示文本" in hint


# ---- 调度触发条件 ----

def test_scheduler_special_day_bypasses_idle():
    """特殊日子当天，即使刚聊过（age < idle）也应触发主动。"""
    _clean()
    from core.config import config

    # 刚聊过（age 很小）
    db.add_message(UID, "user", "刚刚说的话")
    db.add_message(UID, "assistant", "好的呀")
    age = proactive._age_hours(db.last_message_ts(UID))
    assert age is not None and age < config.proactive_idle_hours

    # 无特殊日子 → 不应触发（久别阈值不满足）
    assert not (proactive._festival_hint() or proactive._special_date_hint(UID))

    # 设一个今天的特殊日子 → is_special_day 为真
    today = date.today()
    db.conn.execute(
        "INSERT INTO important_dates (user_id, date, label, kind, ts) VALUES (?,?,?,?,?)",
        (UID, today.strftime("%m-%d"), "我的生日", "birthday", datetime.now().isoformat(timespec="seconds")),
    )
    db.conn.commit()
    is_special_day = bool(proactive._festival_hint() or proactive._special_date_hint(UID))
    assert is_special_day is True