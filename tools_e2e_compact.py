"""真实 LLM E2E：上下文 6 分区压缩（方向 A）验证。

覆盖：
1. compact_context 真实 LLM 生成 6 分区结构化摘要（关键事实/用户偏好等）
2. 摘要持久化到 kv_store（跨会话继承基础）
3. load_compact_summary 读回

注意：消耗真实 API 额度；UID 用隔离测试号。
"""
import asyncio
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UID = "e2e-compact6"
results = []


def ok(name, note=""):
    results.append((name, "OK", note))
    print(f"  ✅ {name}: {note}")


def fail(name, note):
    results.append((name, "FAIL", note))
    print(f"  ❌ {name}: {note}")


async def main():
    print("=" * 60)
    print("上下文 6 分区压缩 真实 LLM E2E")
    print("=" * 60)

    from core.userdb import db

    db.ensure_user(UID)
    db.conn.execute("DELETE FROM messages WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)

    # 种 70 条消息（超过压缩阈值），包含有价值的偏好/约定信息
    base = datetime.datetime.now() - datetime.timedelta(hours=2)
    contents = [
        "我喜欢下雨天窝在窗边看书",
        "周末要去参加同学的婚礼",
        "我养了一只布偶猫叫团子",
        "下周五要交季度报告，好焦虑",
        "跟你说好下个月一起去爬山",
        "最近在学做饭，想学红烧肉",
        "我讨厌香菜，别给我点",
        "昨天去了新开的咖啡馆",
    ]
    for i in range(70):
        ts = (base + datetime.timedelta(minutes=1) * i).isoformat(timespec="seconds")
        content = contents[i % len(contents)]
        db.conn.execute(
            "INSERT INTO messages (user_id, role, content, ts) VALUES (?,?,?,?)",
            (UID, "user" if i % 2 == 0 else "assistant", content, ts),
        )
    db.conn.commit()

    # ---- 1. 真实 6 分区压缩 ----
    print("\n[1/3] compact_context（真实 LLM 6 分区）")
    from core import memory

    result = await memory.compact_context(UID)
    if result is None:
        fail("compact_context", "返回 None")
        return
    summary, keep = result
    print(f"  📋 摘要:\n{summary}")
    if all(f"【{s}】" not in summary for s in memory.COMPACT_SECTIONS):
        fail("compact_sections", "摘要无 6 分区标记")
    else:
        ok("compact_sections", "含分区标记")
    if len(keep) > 0:
        ok("keep_recent", f"保留 {len(keep)} 条最近消息")
    else:
        fail("keep_recent", "未保留最近消息")

    # ---- 2. 持久化 ----
    print("\n[2/3] 摘要持久化（跨会话继承基础）")
    saved = memory.load_compact_summary(UID)
    if saved and saved == summary:
        ok("persist", "摘要已写入 kv_store 并可读回")
    else:
        fail("persist", f"持久化不一致: {saved!r}")

    # ---- 3. 跨会话继承 ----
    print("\n[3/3] 跨会话滚动继承（模拟新会话）")
    # 清空消息（模拟全新会话），仍能读到上次摘要
    db.conn.execute("DELETE FROM messages WHERE user_id=?", (UID,))
    db.conn.commit()
    inherited = memory.load_compact_summary(UID)
    if inherited and "关键事实" in inherited:
        ok("inherit", "新会话继承到上次 6 分区摘要")
    else:
        fail("inherit", f"未继承: {inherited!r}")

    # ---- 小结 ----
    print("\n" + "=" * 60)
    ok_count = sum(1 for _, s, _ in results if s == "OK")
    print(f"结果: {ok_count}/{len(results)} 通过")
    for name, status, note in results:
        print(f"  [{status}] {name}: {note}")


if __name__ == "__main__":
    asyncio.run(main())
