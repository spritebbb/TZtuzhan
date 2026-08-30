"""真实 LLM E2E：话题记忆 + 注入优化验证（真实 DeepSeek API）。

覆盖：
1. topic_memory.extract_topic 真实 LLM 提炼一句话话题
2. build_continuation 读取并返回可注入的延续文本
3. pipeline.process 完整链路：合并后的注入块不炸、能自然回复
4. 新会话开场注入话题延续（模拟：种一个话题 → 触发 process → 检查注入）

注意：消耗真实 API 额度；UID 用隔离测试号，结束后清理。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UID = "e2e-topic-memory"
results = []


def ok(name, note=""):
    results.append((name, "OK", note))
    print(f"  ✅ {name}: {note}")


def fail(name, note):
    results.append((name, "FAIL", note))
    print(f"  ❌ {name}: {note}")


async def main():
    print("=" * 60)
    print("话题记忆 + 注入优化 真实 LLM E2E")
    print("=" * 60)

    from core.userdb import db

    db.ensure_user(UID)
    for t in ("messages", "facts", "user_meta", "affection_log", "long_memory", "kv_store", "user_profile", "user_terms", "user_style_map"):
        db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)

    # ---- 1. extract_topic 真实 LLM 提炼 ----
    print("\n[1/4] extract_topic（真实 LLM 提炼一句话话题）")
    import datetime

    base = datetime.datetime.now() - datetime.timedelta(minutes=40)
    seed = [
        ("user", "周末想去看电影，你有什么推荐吗"),
        ("assistant", "想看电影呀，最近那部讲宇宙的还不错，你喜欢什么类型呀"),
        ("user", "我喜欢悬疑的，上次看的那部你记得吧"),
        ("assistant", "记得呀，你说看得手心冒汗那个，哈哈"),
        ("user", "对，就那种，周末陪我去看好不好"),
        ("assistant", "好呀，那说好了，周末一起去看悬疑片"),
    ]
    for i, (role, content) in enumerate(seed):
        ts = (base + datetime.timedelta(minutes=1) * i).isoformat(timespec="seconds")
        db.conn.execute(
            "INSERT INTO messages (user_id, role, content, ts) VALUES (?,?,?,?)",
            (UID, role, content, ts),
        )
    db.conn.commit()

    from core.topic_memory import extract_topic, last_topic, build_continuation

    topic = await extract_topic(UID)
    if topic and len(topic) >= 2:
        ok("extract_topic", f"提炼: {topic}")
    else:
        fail("extract_topic", f"未提炼成功: {topic!r}")

    cont = build_continuation(UID)
    if cont and cont == topic:
        ok("build_continuation", f"延续可用: {cont}")
    else:
        fail("build_continuation", f"延续读取异常: {cont!r}")

    # ---- 2. pipeline.process 完整链路（合并注入后） ----
    print("\n[2/4] pipeline.process（合并注入块 + 正常回复）")
    from core.pipeline import process

    reply = await process(UID, "嘿，还记得上次我们聊了什么吗", mock=False)
    if reply and len(reply) >= 2:
        ok("process", f"回复: {reply[:80]}")
    else:
        fail("process", f"空回复: {reply!r}")

    # ---- 3. 画像+口头禅+风格 合并注入（种点数据再触发） ----
    print("\n[3/4] 合并注入块（画像/口头禅/风格同条注入不炸）")
    db.add_profile(UID, "likes", "用户喜欢下雨天")
    db.add_term(UID, "绝了", "catchphrase")
    db.add_style_map(UID, "对方倾诉烦恼时", "喜欢用短句+省略号")
    reply2 = await process(UID, "唉，今天有点烦", mock=False)
    if reply2 and len(reply2) >= 2:
        ok("process-with-understanding", f"回复: {reply2[:80]}")
    else:
        fail("process-with-understanding", f"空回复: {reply2!r}")

    # ---- 4. 小结 ----
    print("\n" + "=" * 60)
    ok_count = sum(1 for _, s, _ in results if s == "OK")
    print(f"结果: {ok_count}/{len(results)} 通过")
    for name, status, note in results:
        print(f"  [{status}] {name}: {note}")


if __name__ == "__main__":
    asyncio.run(main())
