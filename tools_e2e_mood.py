"""端到端：心情注入 system prompt + 好感度联动。"""
import asyncio

from core import affection, mood
from core.config import config
from core.persona import build_system_prompt
from core.pipeline import process
from core.userdb import db

uid = "mood-e2e"
db.ensure_user(uid)
for tbl in ("messages", "kv_store", "affection_log"):
    db.conn.execute(f"DELETE FROM {tbl} WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)

print("== 1. 心情注入 system prompt ==")
db.set_affection_absolute(uid, 60)
db.set_mood(uid, 80)  # 开心
p = build_system_prompt(stage="亲密", address="哥哥", lover_confirm=False, first_chat=False, affection=60, user_id=uid)
for line in p.split("\n"):
    if "心情" in line:
        print("  INJECT:", line.strip())

print("\n== 2. 好感度联动（心情开心时加分多）==")
print("  当前好感:", db.get_user(uid)["affection"], "心情:", mood.current_mood(uid)[0])
# 设心情雀跃 90 → 好感应该涨得更快
mood.update_mood(uid, 90 - mood.current_mood(uid)[0])
print("  设心情90后 好感:", db.get_user(uid)["affection"])


async def main():
    # 走 pipeline 发一条正常聊天，看好感变化是否放大
    before = db.get_user(uid)["affection"]
    await process(uid, "今天有点忙，不过想到你就没那么累了")
    after = db.get_user(uid)["affection"]
    print(f"\n  发送关心消息: 好感 {before} -> {after} (+{after-before})")

    # 心情低落时被骂 → 扣分更狠
    mood.update_mood(uid, 5 - mood.current_mood(uid)[0])
    print("  设心情5(低落)后 好感:", db.get_user(uid)["affection"])
    before = db.get_user(uid)["affection"]
    await process(uid, "傻逼，滚")
    after = db.get_user(uid)["affection"]
    print(f"  辱骂消息: 好感 {before} -> {after} ({after-before})")

    for tbl in ("messages", "kv_store", "affection_log"):
        db.conn.execute(f"DELETE FROM {tbl} WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
    db.conn.commit()


asyncio.run(main())
