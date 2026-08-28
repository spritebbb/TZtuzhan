"""今日日程表模块功能测试。"""
import asyncio

from core import schedule
from core.config import config
from core.userdb import db

uid = "schedule-test"
db.ensure_user(uid)
for t in ("kv_store", "messages", "affection_log"):
    db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)


def main():
    # 1. 生成日程（无城市、默认心情）
    s = schedule.build_schedule(uid)
    print("== 默认日程 ==")
    for item in s:
        print(f"  {item['period']}：{item['todo'][:35]}")
    print(f"  共 {len(s)} 段")
    print()

    # 2. 带城市（天气调剂）
    s2 = schedule.build_schedule(uid, city=config.mood_city or "襄阳")
    print(f"== 带城市({config.mood_city or '襄阳'}) ==")
    print("  第一段:", s2[0]["todo"][:40])
    print()

    # 3. 日程描述（/日程 命令用）
    desc = schedule.describe(uid)
    print("== describe ==")
    print(desc)
    print()

    # 4. prompt 注入段
    prompt = schedule.schedule_prompt(uid)
    print("== schedule_prompt ==")
    print(prompt[:120])
    print()

    # 5. 同日缓存（同一天不应变化）
    s3 = schedule.build_schedule(uid)
    print("缓存一致（同一天相同）:", s3 == s)

    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM messages WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM affection_log WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
    db.conn.commit()
    print("\n全部通过")


main()
