"""查看用户好感度状态和变动历史。"""
from core.userdb import db

uid = "<USER_QQ>"
u = db.get_user(uid)
if u:
    print("好感度:", u["affection"])
    print("最后聊天日期:", u["last_chat_date"])
    print("最后批处理日期:", u["last_batch_date"])
    print("称呼:", u["nickname_pref"])

rows = db.conn.execute(
    "SELECT delta, reason, ts FROM affection_log WHERE user_id=? ORDER BY id DESC LIMIT 25",
    (uid,),
).fetchall()
print()
print("--- 最近25条好感度变动 ---")
for r in rows:
    d = r["delta"]
    sign = "+" if d > 0 else ""
    print(f'  {sign}{d}  {r["reason"]}  [{r["ts"][:16]}]')

# 每日总结是否在跑：看 tasks 是否有 pending
try:
    from core.tasks import _pending
    print()
    print("后台任务队列:", len(_pending) if _pending is not None else "无队列对象")
except Exception as e:
    print("tasks 检查:", e)
