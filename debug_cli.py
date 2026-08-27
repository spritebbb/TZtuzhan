"""本地调试 CLI：不依赖 QQ / NapCat，终端直接和菟菚聊天。

用法：
  python debug_cli.py --mock      # 无 API key，模拟回复，跑通全流程
  python debug_cli.py             # 使用 .env 里的真实 LLM

数据写入 data/bot.db（用户 id 为 local-user），与 QQ 数据隔离。
"""
import argparse
import asyncio

from core import affection
from core.pipeline import process
from core.userdb import db

USER_ID = "local-user"


async def main(mock: bool) -> None:
    print("菟菚 · 本地调试模式" + ("（mock，无真实 LLM）" if mock else ""))
    print("输入 exit 退出\n")

    while True:
        try:
            text = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text in ("exit", "quit"):
            break

        reply = await process(USER_ID, text, mock=mock)

        u = db.get_user(USER_ID)
        print(f"菟菚> {reply}")
        print(f"      [好感度 {u['affection']} · 阶段「{affection.stage_of(u['affection'])}」"
              f" · 称呼 {u['nickname_pref'] or '未设定'}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="使用模拟回复（无需 API key）")
    args = parser.parse_args()
    asyncio.run(main(args.mock))
