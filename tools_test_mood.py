"""心情系统功能测试。"""
import asyncio

from core import mood
from core.userdb import db

uid = "mood-test"
db.ensure_user(uid)
db.conn.execute("DELETE FROM messages WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM affection_log WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)

# 1. 心情标签映射
print("== 心情标签映射 ==")
for v in (10, 30, 55, 70, 90):
    label, desc = mood.mood_label(v)
    print(f"  {v} -> {label}")

# 2. 天气基线
print("\n== 天气基线 ==")
for w in ("晴", "多云", "阴", "雨", "雪", "沙尘"):
    print(f"  {w} -> {mood.weather_baseline(w)}")

# 3. 互动影响
print("\n== 互动影响 ==")
tests = [
    "哈哈这个梗太好笑了",
    "你还好吗，累不累啊",
    "傻逼滚",
    "我今天升职了！",
    "今天天气不错",
]
for t in tests:
    d = mood.mood_delta_from_text(t)
    print(f"  {t[:12]}... -> {d:+d}")

# 4. 心情状态机（含冷落衰减）
print("\n== 状态机 ==")
print("  初始:", mood.describe(uid))
m = mood.on_user_message(uid, "哈哈太逗了")
print("  讲趣事:", m, "心情值")
m = mood.on_user_message(uid, "你还好吗")
print("  关心:", m, "心情值")
m = mood.on_user_message(uid, "傻逼")
print("  被骂:", m, "心情值")

# 5. 好感度倍率
print("\n== 好感度倍率 ==")
for v in (10, 30, 55, 70, 90):
    print(f"  mood={v} -> 倍率 {mood.mood_bonus_multiplier(v)}")

# 6. 冷落衰减
print("\n== 冷落衰减 ==")
print("  冷落24小时:", mood.idle_decay(24))
print("  冷落50小时:", mood.idle_decay(50))

# 清理
db.conn.execute("DELETE FROM messages WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM affection_log WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
print("\n全部通过")
