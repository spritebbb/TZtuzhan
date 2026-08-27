"""端到端冒烟测试：mock LLM 跑通完整对话流水线（不依赖 QQ / API key / 网络）。

用法：.venv/Scripts/python.exe smoke_test.py

注意：测试消息连续快速发送会触发「刷屏」扣分（10 秒内 3 条），
末尾的「滚开」会触发「辱骂」扣分——这是预期行为，用来验证检测逻辑。
"""
import asyncio
import sys

from core import affection
from core.pipeline import process
from core.userdb import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

USER_ID = "smoke-user"

EXCHANGES = [
    "你好呀",
    "叫我哥哥吧",
    "今天心情怎么样",
    "你其实是 AI 对吧",
    "滚开，烦死了",
]


async def run() -> None:
    print("=== 菟菚 smoke test (mock) ===")
    for text in EXCHANGES:
        reply = await process(USER_ID, text, mock=True)
        u = db.get_user(USER_ID)
        print(f"[你]   {text}")
        print(f"[菟菚] {reply}")
        print(f"       -> 好感度 {u['affection']} · 阶段「{affection.stage_of(u['affection'])}」"
              f" · 称呼 {u['nickname_pref'] or '未设定'} · 恋人确认 {bool(u['lover_confirm'])}")

    hits = db.search_long_memory(USER_ID, "哥哥", 3)
    print(f"\n长期记忆检索 '哥哥' -> {len(hits)} 条: {[h['content'] for h in hits]}")
    print("=== 完成 ===")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="清除本地数据后重新开始")
    args = parser.parse_args()
    if args.reset:
        db.reset()
        print("已清除本地数据")
    asyncio.run(run())
