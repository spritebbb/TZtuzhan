"""端到端：话题锚定在真实 LLM 下的效果（模拟"想你了"被旧话题带偏的场景）。"""
import asyncio

from core.pipeline import process
from core.userdb import db

uid = "ctx-e2e"
db.ensure_user(uid)
for tbl in ("messages", "kv_store", "affection_log"):
    db.conn.execute(f"DELETE FROM {tbl} WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)


async def main():
    # 先铺垫一个旧话题（赶路/上班），制造"旧话题痕迹"
    for m in ["我今天要赶路去外地，很晚才到", "嗯，到了跟你说", "对了你养猫吗"]:
        await process(uid, m, mock=False)
    # 然后切换话题：想你了（此前会冒出"路上注意安全"这种旧话题尾巴）
    r = await process(uid, "想你了", merged_msg=False)
    print("== 切换话题后回复 ==")
    print(r)
    print()
    # 再看一个倾诉场景
    r2 = await process(uid, "今天好累啊，工作特别多", merged_msg=False)
    print("== 倾诉场景回复 ==")
    print(r2)

    for tbl in ("messages", "kv_store", "affection_log"):
        db.conn.execute(f"DELETE FROM {tbl} WHERE user_id=?", (uid,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
    db.conn.commit()


asyncio.run(main())
