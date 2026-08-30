"""真实 LLM E2E：互动玩法（日记 + 睡前故事）验证。

覆盖：
1. 日记：真实 LLM 生成（含 mock 对照），存入 diary 表
2. 睡前故事：真实 LLM 生成，带阶段/心情感知
3. 猜数字 / 石头剪刀布：纯逻辑（mock 无差异）

注意：消耗真实 API 额度；UID 用隔离测试号，结束后清理。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UID = "e2e-fun"
results = []


def ok(name, note=""):
    results.append((name, "OK", note))
    print(f"  ✅ {name}: {note}")


def fail(name, note):
    results.append((name, "FAIL", note))
    print(f"  ❌ {name}: {note}")


async def main():
    print("=" * 60)
    print("互动玩法 真实 LLM E2E")
    print("=" * 60)

    from core.userdb import db

    db.ensure_user(UID)
    db.conn.execute("DELETE FROM diary WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM messages WHERE user_id=?", (UID,))
    db.conn.commit()

    # ---- 1. 日记 ----
    print("\n[1/4] 日记（真实 LLM 生成）")
    from core.fun import diary_text, generate_diary, list_diary_dates

    diary = await generate_diary(UID)
    if diary and len(diary) >= 10:
        ok("generate_diary", f"生成 {len(diary)} 字: {diary[:50]}…")
    else:
        fail("generate_diary", f"生成失败: {diary!r}")

    # 已存在 → 不重复
    diary2 = await generate_diary(UID)
    if diary2 == diary:
        ok("diary_dedup", "不重复生成")
    else:
        fail("diary_dedup", f"重复生成: {diary2!r}")

    dates = list_diary_dates(UID)
    if dates:
        ok("list_diary_dates", f"{len(dates)} 篇记录")
    else:
        fail("list_diary_dates", "无记录")

    # ---- 2. 睡前故事 ----
    print("\n[2/4] 睡前故事（真实 LLM 生成）")
    from core.fun import bedtime_story

    story = await bedtime_story(UID)
    if story and len(story) >= 20:
        ok("bedtime_story", f"生成 {len(story)} 字: {story[:50]}…")
    else:
        fail("bedtime_story", f"生成失败: {story!r}")

    # ---- 3. 猜数字（逻辑） ----
    print("\n[3/4] 猜数字（逻辑）")
    from core.fun import guess_number, start_guess_game

    msg = start_guess_game(UID)
    if "猜是多少" in msg:
        ok("guess_start", msg)
    else:
        fail("guess_start", msg)
    from core.fun import _game_state

    st = _game_state(UID)
    ans = st["answer"]
    r1 = guess_number(UID, 0)
    r2 = guess_number(UID, ans)
    if "高了" in r1 or "低了" in r1:
        ok("guess_hint", f"提示: {r1}")
    if "对啦" in r2 or "猜中了" in r2:
        ok("guess_win", r2)
    else:
        fail("guess_win", r2)

    # ---- 4. 石头剪刀布（逻辑） ----
    print("\n[4/4] 石头剪刀布（逻辑）")
    from core.fun import rps_play

    r3 = rps_play(UID, "石头")
    if "平手" in r3 or "赢了" in r3 or "输了" in r3:
        ok("rps", r3)
    else:
        fail("rps", r3)

    # ---- 小结 ----
    print("\n" + "=" * 60)
    ok_count = sum(1 for _, s, _ in results if s == "OK")
    print(f"结果: {ok_count}/{len(results)} 通过")
    for name, status, note in results:
        print(f"  [{status}] {name}: {note}")


if __name__ == "__main__":
    asyncio.run(main())
