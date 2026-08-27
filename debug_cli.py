"""本地调试 CLI：不依赖 QQ / NapCat，终端直接和菟菚聊天。

用法：
  python debug_cli.py --mock      # 无 API key，模拟回复，跑通全流程
  python debug_cli.py             # 使用 .env 里的真实 LLM

数据写入 data/bot.db（用户 id 为 local-user），与 QQ 数据隔离。
"""
import argparse
import asyncio
import sys

from core import affection
from core.pipeline import process
from core.userdb import db

# 控制台统一用 UTF-8 输出，避免 GBK 编码器无法打印颜文字（´･ω･` 等）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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


def _ask_reset() -> None:
    """启动时询问是否清除上次数据（仅当存在历史数据时；默认不清除）。"""
    try:
        count = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except Exception:
        count = 0
    if count == 0:
        return
    answer = input("检测到上次的本地数据，是否清除后重新开始？[y/N] ").strip().lower()
    if answer in ("y", "yes"):
        db.reset()
        print("已清除本地数据（记忆/好感度/称呼）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="使用模拟回复（无需 API key）")
    parser.add_argument("--reset", action="store_true", help="强制清除本地数据后重新开始（跳过询问）")
    args = parser.parse_args()
    if args.reset:
        db.reset()
        print("已清除本地数据（记忆/好感度/称呼）")
    else:
        _ask_reset()
    asyncio.run(main(args.mock))
