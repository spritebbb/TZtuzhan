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
from core.search import web_search
from core.userdb import db

# 控制台统一用 UTF-8 输出，避免 GBK 编码器无法打印颜文字（´･ω･` 等）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

USER_ID = "local-user"


async def main(mock: bool) -> None:
    print("菟菚 · 本地调试模式" + ("（mock，无真实 LLM）" if mock else ""))
    print("命令：exit 退出 · /好感度 查看 · /好感度 <0-100> 设置")
    print()

    while True:
        try:
            text = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text in ("exit", "quit"):
            break
        if text.startswith(("/好感", "/aff")):
            _handle_aff_cmd(text)
            continue
        if text.startswith(("/搜索", "/搜")):
            _handle_search_cmd(text)
            continue

        reply = await process(USER_ID, text, mock=mock)

        u = db.get_user(USER_ID)
        print(f"菟菚> {reply}")
        print(f"      [好感度 {u['affection']} · 阶段「{affection.stage_of(u['affection'])}」"
              f" · 称呼 {u['nickname_pref'] or '未设定'}]")


def _handle_aff_cmd(raw: str) -> None:
    """处理 /好感 命令：查看或设置好感度。"""
    parts = raw.strip().split()
    if len(parts) < 2 or parts[1] in ("查看", "看", "查询", "当前"):
        print("当前 " + affection.describe(USER_ID))
        return
    try:
        affection.set_affection(USER_ID, int(parts[1]))
        print("已设置 -> " + affection.describe(USER_ID))
    except ValueError:
        print("用法：/好感 80 或 /好感（查看当前），也可用 /aff")


def _handle_search_cmd(raw: str) -> None:
    """处理 /搜索 命令：联网搜索并展示结果。"""
    query = raw.strip()
    for pre in ("/搜索", "/搜"):
        if query.startswith(pre):
            query = query[len(pre):].lstrip(":： ")
            break
    if not query:
        print("用法：/搜索 <关键词>")
        return
    print(f"正在搜索「{query}」...")
    results = web_search(query)
    if not results:
        print("（未找到结果，或搜索引擎不可用）")
        return
    for r in results[:5]:
        print(f"- {r['title']} | {r['snippet'][:60]} | {r['url']}")


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
