"""日程影响心情：日程时段情绪 + 特殊日子加成会改变心情基线。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schedule import period_for_hour, schedule_mood_offset
from core.userdb import db

uid = "pytest-sched-mood"
db.ensure_user(uid)
for t in ("kv_store", "messages", "affection_log"):
    db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)


def test_period_for_hour():
    """按小时应映射到正确的日程时段。"""
    assert period_for_hour(8) == "清晨"
    assert period_for_hour(10) == "上午"
    assert period_for_hour(12) == "中午"
    assert period_for_hour(15) == "下午"
    assert period_for_hour(18) == "傍晚"
    assert period_for_hour(21) == "晚上"
    assert period_for_hour(23) == "深夜"
    assert period_for_hour(2) == "凌晨"


def test_schedule_mood_offset_by_period():
    """晚上（想陪你）的情绪偏移应高于白天慵懒时段。"""
    evening = schedule_mood_offset(uid, hour=21)
    early = schedule_mood_offset(uid, hour=7)
    assert evening >= 3
    assert evening > early


def test_schedule_mood_offset_special_day():
    """有特殊日子时（生日）全天心情加成应出现。"""
    from core.userdb import save_important_date

    import datetime

    today = datetime.date.today().strftime("%m-%d")
    save_important_date(uid, today, "测试生日", "birthday", None)
    offset = schedule_mood_offset(uid, hour=7)  # 清晨本应 +0，但有生日加成
    # 清理
    db.conn.execute("DELETE FROM important_dates WHERE user_id=?", (uid,))
    db.conn.commit()
    assert offset >= 10


def test_baseline_clamped():
    """日程情绪叠加后基线应限制在 0-100。"""
    from core import mood

    base = mood._baseline_for("晴", uid)  # 晴基线75 + 日程偏移
    assert 0 <= base <= 100


def test_period_transition_corrects_mood():
    """跨日程时段后，心情应按时段情绪差即时校正（日程影响心情可感）。"""
    import datetime

    from core import mood

    db.set_mood(uid, 60)
    now = datetime.datetime.now()
    # 用2小时前作为"上次更新"，此时段与当前可能不同
    past = now - datetime.timedelta(hours=2)
    db.conn.execute(
        "UPDATE users SET mood_updated_at=? WHERE user_id=?", (past.isoformat(), uid)
    )
    db.conn.commit()
    m, _ = mood.current_mood(uid, city="襄阳")
    assert 0 <= m <= 100
    # 只要当前时段偏移 >= 2小时前时段偏移，校正后心情不应低于60（漂移+校正都向上）
    from core.schedule import schedule_mood_offset

    old_off = schedule_mood_offset(uid, hour=max(0, now.hour - 2))
    new_off = schedule_mood_offset(uid, hour=now.hour)
    # 当 new_off >= old_off 时，校正为非负
    if new_off >= old_off:
        assert m >= 60
