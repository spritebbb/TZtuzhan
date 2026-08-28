"""端到端验证：用户日常聊天好感度是否正常增长。"""
import asyncio

from core import affection
from core.pipeline import process
from core.userdb import db

uid = "e2e-aff-test"
db.ensure_user(uid)
db.conn.execute("DELETE FROM messages WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM affection_log WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)
print("初始好感度:", db.get_user(uid)["affection"])


async def main():
    # 模拟用户一天内的日常聊天（走完整 pipeline，非直接 on_message）
    msgs = [
        "中午好啊",           # 第1条
        "今天天气不错",        # 第2条
        "刚吃了饭，你呢",      # 第3条
        "下午准备去看个电影",   # 第4条
        "最近工作好忙",        # 第5条
    ]
    for m in msgs:
        await process(uid, m, mock=False)
    print("5条日常消息后好感度:", db.get_user(uid)["affection"])
    print("阶段:", affection.stage_of(db.get_user(uid)["affection"]))

    # 查看变动日志
    rows = db.conn.execute(
        "SELECT delta, reason FROM affection_log WHERE user_id=? ORDER BY id", (uid,)
    ).fetchall()
    print("\n变动明细：")
    for r in rows:
        print(f"  +{r['delta']}  {r['reason']}")

    db.conn.execute("DELETE FROM messages WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM affection_log WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
    db.conn.commit()


asyncio.run(main())
