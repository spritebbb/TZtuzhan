"""记忆测试：短期连贯 + 长期事实提炼与检索（用完即删）。"""
import asyncio

from core import affection
from core.memory import recall_facts
from core.pipeline import process
from core.userdb import db

USER = "mem-test"

SEED = [
    "你好",
    "叫我以实玛利吧",
    "我平时超喜欢下雨天，下雨的时候心情特别好",
    "那挺好啊，我记下了。对了你平时忙不忙？",
    "我在一家游戏公司做策划，平时挺忙的",
    "游戏策划啊，是不是经常要熬夜？",
    "偶尔吧。对了我不吃香菜，看到香菜就难受",
    "那我记住啦，以后提到吃的避开香菜",
    "我们约好每周五晚上一起视频吧",
    "好呀，每周五晚上，我等你",
]


async def main() -> None:
    db.ensure_user(USER)
    affection.set_affection(USER, 55)  # 亲密，方便自然聊天
    for t in SEED:
        r = await process(USER, t, mock=False)
        print(f"你> {t}\n菟菚> {r}\n")

    print("=== 长期记忆 facts 表（提炼出的事实）===")
    rows = db.conn.execute("SELECT content FROM facts WHERE user_id=?", (USER,)).fetchall()
    for r in rows:
        print(" -", r["content"])

    print("\n=== 事实检索验证 ===")
    for q in ["下雨", "香菜", "周五", "游戏"]:
        print(f"  查「{q}」-> {recall_facts(USER, q)}")


if __name__ == "__main__":
    asyncio.run(main())
