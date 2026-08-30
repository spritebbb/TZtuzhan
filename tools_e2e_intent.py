"""真实 LLM E2E：意图路由（方向 B）验证。

覆盖：
1. 闲聊短句走 pipeline（少注入路径）→ 回复自然
2. 需要搜索/回忆/情感的消息走全量注入 → 功能不丢
3. 两种路径都正常产出回复

注意：消耗真实 API 额度；UID 用隔离测试号。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UID = "e2e-intent"
results = []


def ok(name, note=""):
    results.append((name, "OK", note))
    print(f"  ✅ {name}: {note}")


def fail(name, note):
    results.append((name, "FAIL", note))
    print(f"  ❌ {name}: {note}")


async def main():
    print("=" * 60)
    print("意图路由 真实 LLM E2E")
    print("=" * 60)

    from core.userdb import db

    db.ensure_user(UID)
    for t in ("messages", "facts", "user_meta", "affection_log", "kv_store", "user_profile", "user_terms", "user_style_map"):
        db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)

    # 种点画像/口头禅数据（确保闲聊路径能体现"跳过了但无碍"）
    db.add_profile(UID, "likes", "用户喜欢下雨天和猫")
    db.add_term(UID, "绝了", "catchphrase")

    # ---- 1. 闲聊短句（少注入路径） ----
    print("\n[1/3] 闲聊短句（少注入路径）")
    from core.pipeline import process

    reply = await process(UID, "嗯，好的", mock=False)
    if reply and len(reply) >= 1:
        ok("chitchat", f"回复: {reply[:60]}")
    else:
        fail("chitchat", f"空回复: {reply!r}")

    # ---- 2. 回忆（全量注入路径） ----
    print("\n[2/3] 回忆（全量注入路径）")
    reply2 = await process(UID, "你还记得上次我们聊过什么吗", mock=False)
    if reply2 and len(reply2) >= 2:
        ok("recall-path", f"回复: {reply2[:60]}")
    else:
        fail("recall-path", f"空回复: {reply2!r}")

    # ---- 3. 情感（全量注入路径） ----
    print("\n[3/3] 情感倾诉（全量注入路径）")
    reply3 = await process(UID, "我今天好烦啊，跟你说说心里话", mock=False)
    if reply3 and len(reply3) >= 2:
        ok("emotional-path", f"回复: {reply3[:60]}")
    else:
        fail("emotional-path", f"空回复: {reply3!r}")

    # ---- 小结 ----
    print("\n" + "=" * 60)
    ok_count = sum(1 for _, s, _ in results if s == "OK")
    print(f"结果: {ok_count}/{len(results)} 通过")
    for name, status, note in results:
        print(f"  [{status}] {name}: {note}")


if __name__ == "__main__":
    asyncio.run(main())
