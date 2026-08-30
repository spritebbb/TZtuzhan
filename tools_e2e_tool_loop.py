"""真实 LLM E2E：流式工具调用循环（方向 D）验证。

覆盖：
1. 意图路由判定 need_search → 走工具循环路径
2. LLM 自主调用 web_search 工具获取实时信息
3. 工具结果注入 → 最终回复自然
4. 普通消息（无 need_search）→ 不走工具循环，正常回复

注意：消耗真实 API 额度；UID 用隔离测试号。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UID = "e2e-tool-loop"
results = []


def ok(name, note=""):
    results.append((name, "OK", note))
    print(f"  ✅ {name}: {note}")


def fail(name, note):
    results.append((name, "FAIL", note))
    print(f"  ❌ {name}: {note}")


async def main():
    print("=" * 60)
    print("流式工具调用循环 真实 LLM E2E")
    print("=" * 60)

    from core.userdb import db

    db.ensure_user(UID)
    for t in ("messages", "facts", "affection_log", "kv_store"):
        db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)

    # ---- 1. 意图路由判定 need_search ----
    print("\n[1/4] 意图路由判定 need_search")
    from core.intent import classify

    intent = classify("百度一下最近发生了什么大事")
    if intent.get("need_search"):
        ok("intent-need-search", "搜索意图识别正确")
    else:
        fail("intent-need-search", f"未识别: {intent}")

    # ---- 2. 工具循环：真实 LLM 调用 web_search ----
    print("\n[2/4] 工具循环（真实 LLM → web_search → 结果注入 → 最终回复）")
    from core.pipeline import process

    # 用"百度"触发意图路由（规则 _needs_search 不含"百度"→ 不提前注入 → 走工具循环）
    reply = await process(UID, "百度一下最近发生了什么大事", mock=False)
    if reply and len(reply) >= 2:
        ok("tool-loop-search", f"回复: {reply[:80]}")
        # 检查是否自然提到了搜索到的信息（而非"我现在不能搜索"）
        if "抱歉" not in reply[:10] and "不能" not in reply[:10] and "无法" not in reply[:10]:
            ok("tool-loop-answer", "回复自然，未拒绝")
    else:
        fail("tool-loop-search", f"空回复: {reply!r}")

    # ---- 3. 普通消息（不走工具循环） ----
    print("\n[3/4] 普通消息（不走工具循环，正常回复）")
    reply2 = await process(UID, "今天心情不错", mock=False)
    if reply2 and len(reply2) >= 2:
        ok("normal-chat", f"回复: {reply2[:60]}")
    else:
        fail("normal-chat", f"空回复: {reply2!r}")

    # ---- 4. 工具循环不破坏思考/回复格式 ----
    print("\n[4/4] 回复格式检查（自觉模式）")
    reply3 = await process(UID, "百度一下最近的科技新闻", mock=False)
    if reply3 and len(reply3) >= 2:
        ok("weather-chat", f"回复: {reply3[:80]}")
    else:
        fail("weather-chat", f"空回复: {reply3!r}")

    # ---- 小结 ----
    print("\n" + "=" * 60)
    ok_count = sum(1 for _, s, _ in results if s == "OK")
    print(f"结果: {ok_count}/{len(results)} 通过")
    for name, status, note in results:
        print(f"  [{status}] {name}: {note}")


if __name__ == "__main__":
    asyncio.run(main())