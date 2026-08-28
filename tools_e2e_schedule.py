"""端到端：日程注入 system prompt 后，菟菚能否自然说出"在干嘛"。"""
import asyncio

from core.pipeline import process
from core.userdb import db

uid = "sched-e2e"
db.ensure_user(uid)
for t in ("messages", "kv_store", "affection_log"):
    db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)


async def main():
    # 先设个心情，让日程有调剂
    from core import mood

    mood.update_mood(uid, 70 - mood.current_mood(uid)[0])  # 开心
    r = await process(uid, "在干嘛呢", merged_msg=False)
    print("== 问'在干嘛' ==")
    print(r)
    print()
    r2 = await process(uid, "你今天都做什么呀", merged_msg=False)
    print("== 问'今天做什么' ==")
    print(r2)

    for t in ("messages", "kv_store", "affection_log"):
        db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
    db.conn.commit()


asyncio.run(main())
