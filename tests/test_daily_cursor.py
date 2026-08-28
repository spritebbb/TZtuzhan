"""验证 daily.extract_facts 游标推进不再吞掉当天新消息。"""
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import daily
from core.userdb import db

uid = "pytest-daily-cursor"
db.ensure_user(uid)
for t in ("messages", "facts", "user_meta", "affection_log", "long_memory"):
    db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)

yesterday = date.today() - timedelta(days=1)


def _add(day: date, i: int, text: str):
    db.conn.execute(
        "INSERT INTO messages (user_id, role, content, ts) VALUES (?,?,?,?)",
        (uid, "user", text, f"{day.isoformat()}T10:{i:02d}:00"),
    )
    db.conn.commit()


def test_extract_facts_day_cursor_does_not_eat_today():
    """day 分支的游标应停在当日最后一条，不吞掉今天的新消息。"""
    _add(yesterday, 0, "昨天消息0")
    _add(yesterday, 1, "昨天消息1")
    _add(yesterday, 2, "昨天消息2")
    yesterday_rows = db.messages_between(uid, yesterday, yesterday)
    yesterday_last_id = yesterday_rows[-1]["id"]

    _add(date.today(), 0, "今天新消息0")
    _add(date.today(), 1, "今天新消息1")

    # 模拟 run_daily_batch 调 extract_facts(uid, yesterday)
    async def _go():
        with mock.patch("core.daily.chat") as m_chat:
            m_chat.return_value = '{"facts": [], "style": ""}'
            await daily.extract_facts(uid, yesterday)

    import asyncio

    asyncio.run(_go())

    # 游标应停在昨天最后一条，而非今天的 max
    cursor = db.get_last_fact_msg_id(uid)
    assert cursor == yesterday_last_id, f"游标应=昨日最后({yesterday_last_id})，实际={cursor}"

    # 今天的新消息应仍可见（未来会被惰性提炼）
    after = db.messages_after(uid, cursor, 60)
    assert len(after) == 2, f"今天的新消息应仍可见(2)，实际={len(after)}"

    # 清理
    for t in ("messages", "facts", "user_meta", "affection_log", "long_memory"):
        db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
    db.conn.commit()
