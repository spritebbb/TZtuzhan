"""查看用户好感度状态和变动历史。

用法: python tools_check_affection.py [QQ号]
（不传则读取 .env 的 PROACTIVE_USER_ID 或环境变量 CHECK_UID）
"""
import os
import sys

from core.userdb import db

uid = (
    sys.argv[1]
    if len(sys.argv) > 1
    else os.getenv("CHECK_UID") or os.getenv("PROACTIVE_USER_ID", "").split(",")[0].strip()
)
if not uid:
    print("请传入 QQ 号: python tools_check_affection.py <QQ号>")
    sys.exit(1)
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
