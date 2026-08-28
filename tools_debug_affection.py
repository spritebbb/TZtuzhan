"""调试好感度基础奖励。"""
import asyncio
from datetime import date

from core import affection
from core.userdb import db, kv_get, kv_set

uid = "aff-debug"
db.ensure_user(uid)
db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM affection_log WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)
print("初始好感:", db.get_user(uid)["affection"])

key = f"bonus:{date.today().isoformat()}:chat_count"
print("kv_get 初值:", repr(kv_get(uid, key)))
kv_set(uid, key, "5")
print("kv_get 设5后:", repr(kv_get(uid, key)))


async def main():
    await affection.on_message(uid, "测试1")
    print("聊天1次后:", db.get_user(uid)["affection"], "kv:", kv_get(uid, key))
    await affection.on_message(uid, "测试2")
    print("聊天2次后:", db.get_user(uid)["affection"], "kv:", kv_get(uid, key))
    rows = db.conn.execute(
        "SELECT delta, reason FROM affection_log WHERE user_id=?", (uid,)
    ).fetchall()
    for r in rows:
        print(f"  {r['delta']} {r['reason']}")
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM affection_log WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
    db.conn.commit()


asyncio.run(main())
