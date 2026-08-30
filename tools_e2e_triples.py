"""真实 LLM E2E：结构化事实记忆（方向 C）验证。

覆盖：
1. extract_triples 真实 LLM 提取五元组
2. save_triples 入库
3. query_triples 检索相关三元组
4. pipeline 完整链路注入三元组（种数据 → 回忆 → 回复应自然体现）

注意：消耗真实 API 额度；UID 用隔离测试号。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UID = "e2e-triples"
results = []


def ok(name, note=""):
    results.append((name, "OK", note))
    print(f"  ✅ {name}: {note}")


def fail(name, note):
    results.append((name, "FAIL", note))
    print(f"  ❌ {name}: {note}")


async def main():
    print("=" * 60)
    print("结构化事实记忆 真实 LLM E2E")
    print("=" * 60)

    from core.userdb import db

    db.ensure_user(UID)
    db.conn.execute("DELETE FROM triples WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM messages WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)

    # ---- 1. 真实 LLM 提取五元组 ----
    print("\n[1/4] extract_triples（真实 LLM）")
    from core import triple_memory

    triples = await triple_memory.extract_triples(
        "用户说：我养了一只布偶猫叫团子，特别喜欢下雨天，下个月要交季度报告"
    )
    print(f"  📦 提取到 {len(triples)} 个五元组:")
    for t in triples:
        print(f"    {t}")
    if triples:
        ok("extract", f"{len(triples)} 个五元组")
    else:
        fail("extract", "未提取到")

    # ---- 2. 入库 ----
    print("\n[2/4] save_triples 入库")
    n = triple_memory.save_triples(UID, triples, source_msg="测试")
    rows = db.conn.execute("SELECT * FROM triples WHERE user_id=?", (UID,)).fetchall()
    if rows:
        ok("save", f"入库 {len(rows)} 条")
    else:
        fail("save", "未入库")

    # ---- 3. 检索 ----
    print("\n[3/4] query_triples 检索")
    hits = triple_memory.query_triples(UID, "你记得我养了什么吗")
    if hits:
        ok("query", f"命中: {hits[0][0]}({hits[0][1]}) —[{hits[0][2]}]→ {hits[0][3]}({hits[0][4]})")
    else:
        fail("query", "无命中")

    # ---- 4. pipeline 注入 ----
    print("\n[4/4] pipeline 完整链路（回忆触发三元组注入）")
    from core.pipeline import process

    reply = await process(UID, "你还记得我养了只什么猫吗", mock=False)
    if reply and len(reply) >= 2:
        ok("pipeline", f"回复: {reply[:80]}")
        if "团子" in reply or "猫" in reply:
            ok("pipeline-recall", "回复自然带出记忆")
    else:
        fail("pipeline", f"空回复: {reply!r}")

    # ---- 小结 ----
    print("\n" + "=" * 60)
    ok_count = sum(1 for _, s, _ in results if s == "OK")
    print(f"结果: {ok_count}/{len(results)} 通过")
    for name, status, note in results:
        print(f"  [{status}] {name}: {note}")


if __name__ == "__main__":
    asyncio.run(main())
