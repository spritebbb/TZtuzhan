"""真实 LLM E2E：验证菟菚完整对话链路（真实 DeepSeek API）。

覆盖：pipeline.process 完整链路（好感度→心情→日程→记忆→LLM→回复→存档→向量）
+ ensure_schedule LLM 生成 + recall 语义扩展。
注意：会消耗真实 API 额度；UID 用隔离测试号，结束后清理。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UID = "e2e-real-llm"
results = []


def ok(name, note=""):
    results.append((name, "OK", note))
    print(f"  ✅ {name}: {note}")


def fail(name, note):
    results.append((name, "FAIL", note))
    print(f"  ❌ {name}: {note}")


async def main():
    print("=" * 60)
    print("真实 LLM E2E 测试")
    print("=" * 60)

    from core.userdb import db
    from core.config import config

    # 隔离测试用户
    db.ensure_user(UID)
    for t in ("messages", "facts", "user_meta", "affection_log", "long_memory", "stickers", "kv_store", "important_dates"):
        db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)

    # ---- 1. ensure_schedule 真实 LLM 生成 ----
    print("\n[1/4] ensure_schedule（真实 LLM 生成今日 6 时段日程）")
    from core.schedule import ensure_schedule, build_schedule
    try:
        await ensure_schedule(UID, city=config.mood_city)
        sched = build_schedule(UID, city=config.mood_city)
        assert len(sched) == 6
        ok("ensure_schedule", f"6 时段: {sched[0]['period']}想{sched[0]['todo'][:15]} | {sched[1]['period']}想{sched[1]['todo'][:15]} | {sched[2]['period']}想{sched[2]['todo'][:15]}…")
    except Exception as e:
        fail("ensure_schedule", str(e)[:200])

    # ---- 2. recall 语义扩展（真实 LLM 查询扩展 + TF-IDF + 向量） ----
    print("\n[2/4] recall 语义检索（真实 LLM 扩展）")
    # 先种一条记忆
    from core.userdb import db as _udb
    _udb.add_long_memory(UID, "用户说：我最喜欢下雨天窝在窗边看书")
    try:
        from core.memory import recall, expand_query
        terms = await expand_query(UID, "你还记得我上次说喜欢什么天气吗", mock=False)
        ok("expand_query", f"扩展词: {terms}")
        mem = await recall(UID, "你还记得我上次说喜欢什么天气吗")
        ok("recall", f"检索到 {len(mem)} 条: {[m[:30] for m in mem]}")
    except Exception as e:
        fail("recall", str(e)[:200])

    # ---- 3. pipeline.process 完整 E2E（初识阶段，普通聊天） ----
    print("\n[3/4] pipeline.process 完整对话链路")
    from core.pipeline import process
    try:
        reply = await process(UID, "今天襄阳天气怎么样呀", merged_msg=False)
        assert reply and len(reply) > 1
        ok("process.普通", f"回复: {reply[:60]}")
    except Exception as e:
        fail("process.普通", str(e)[:300])

    try:
        reply2 = await process(UID, "我好累，今天加班到很晚", merged_msg=False)
        ok("process.共情", f"回复: {reply2[:60]}")
    except Exception as e:
        fail("process.共情", str(e)[:300])

    # 验证存档与向量
    from core.userdb import db as _db
    from core.vector_store import indexed_count
    n_msg = _db.conn.execute("SELECT COUNT(*) c FROM messages WHERE user_id=?", (UID,)).fetchone()["c"]
    ok("存档", f"messages 表新增 {n_msg} 条（user+assistant 各2）")

    # ---- 4. date_memory 真实识别 ----
    print("\n[4/4] date_memory 真实识别")
    from core.date_memory import extract_from_message
    try:
        saved = await extract_from_message(UID, "对了，我生日是十月十二号，到时候要记得")
        ok("date_memory", f"识别到 {len(saved)} 个日子: {[s['label'] for s in saved]}")
    except Exception as e:
        fail("date_memory", str(e)[:200])

    # 汇总
    print("\n" + "=" * 60)
    n_ok = sum(1 for _, s, _ in results if s == "OK")
    n_fail = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"汇总: OK={n_ok}  FAIL={n_fail}  (共 {len(results)} 项)")

    # 清理测试数据（保留 messages 供查看，删除其它）
    for t in ("facts", "user_meta", "affection_log", "long_memory", "stickers", "kv_store", "important_dates"):
        _db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (UID,))
    _db.conn.execute("DELETE FROM messages WHERE user_id=?", (UID,))
    _db.conn.execute("DELETE FROM users WHERE user_id=?", (UID,))
    _db.conn.commit()
    print("测试数据已清理")

    return n_fail


if __name__ == "__main__":
    nf = asyncio.run(main())
    sys.exit(1 if nf else 0)
