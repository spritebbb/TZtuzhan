"""今日日程表：作息模板、心情/天气/特殊日子调剂、缓存、prompt 注入。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import schedule
from core.userdb import db

uid = "pytest-schedule"
db.ensure_user(uid)
for t in ("kv_store", "messages", "affection_log"):
    db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)


def test_schedule_has_all_periods():
    """日程应覆盖一天的多个时段，且每段有安排。"""
    s = schedule.build_schedule(uid)
    periods = [x["period"] for x in s]
    assert "清晨" in periods and "上午" in periods and "中午" in periods
    assert "下午" in periods and "傍晚" in periods and "晚上" in periods
    assert all(x["todo"].strip() for x in s)


def test_schedule_cached_same_day():
    """同一天内重复生成应返回相同内容（缓存到 kv_store）。

    build_schedule 同步版不写缓存（规则兜底，随机调剂可能不同）；
    缓存一致性由 ensure_schedule 负责——异步生成一次后，后续读缓存固定。
    """
    import asyncio

    async def _go():
        a = await schedule.ensure_schedule(uid)
        b = await schedule.ensure_schedule(uid)
        return a, b

    a, b = asyncio.run(_go())
    assert a == b


def test_schedule_prompt_mentions_daily():
    """注入 prompt 应提到今日作息，且避免主动逐条汇报。"""
    p = schedule.schedule_prompt(uid)
    assert "日常" in p
    assert "别主动逐条汇报" in p


def test_describe_readable():
    """描述应是一段可读的日程文本。"""
    d = schedule.describe(uid)
    assert "今天我是这样安排" in d
    assert "：" in d  # 有时段：事项


def test_weather_and_mood_safe():
    """带城市/不带城市的生成都不报错（天气/心情调剂健壮）。"""
    assert schedule.build_schedule(uid, city="襄阳")
    assert schedule.build_schedule(uid, city="")


def test_special_day_schedule_not_repetitive():
    """特殊日子只应注入契合的时段，其余时段保持正常——不能 6 段全变成同一句。

    回归：曾出现 6 段全部是"今天是个特别的日子……我想只跟你分享。"的 bug。
    """
    from datetime import date

    from core.userdb import save_important_date

    # 给该测试用户造一个今天的特殊日子
    today = date.today().strftime("%m-%d")
    save_important_date(uid, today, "测试特别日子")
    # 清掉今日缓存，强制走规则模板
    for row in db.conn.execute(
        "SELECT key FROM kv_store WHERE user_id=? AND key LIKE 'schedule:%'", (uid,)
    ).fetchall():
        db.conn.execute("DELETE FROM kv_store WHERE user_id=? AND key=?", (uid, row["key"]))
    db.conn.commit()

    s = schedule._rule_schedule(uid)
    todos = [x["todo"] for x in s]
    # 6 段不应相同；且"特别日子"文案只出现一次
    assert len(set(todos)) >= 5, f"特殊日子日程过于重复: {todos}"
    special_count = sum(1 for t in todos if "特别" in t)
    assert special_count <= 2, f"特别文案注入过多: {special_count}"
    # 应至少有一段是完全正常的日常作息（不含"特别"）
    assert any("特别" not in t for t in todos), "应有正常作息时段"
