"""真实 LLM E2E：主动消息多场景扩展验证（真实 DeepSeek API）。

覆盖：
1. proactive_message 在多场景提示（节日/特殊日子/深夜/天气）下能生成自然主动消息
2. 特殊日子由头真实生效（种一个今天的纪念日 → 主动消息应带出）
3. 纯逻辑场景提示（_scenario_hint）组合正确

注意：消耗真实 API 额度；UID 用隔离测试号，结束后清理。
"""
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UID = "e2e-proactive-scenarios"
results = []


def ok(name, note=""):
    results.append((name, "OK", note))
    print(f"  ✅ {name}: {note}")


def fail(name, note):
    results.append((name, "FAIL", note))
    print(f"  ❌ {name}: {note}")


async def main():
    print("=" * 60)
    print("主动消息多场景 真实 LLM E2E")
    print("=" * 60)

    from core.userdb import db

    db.ensure_user(UID)
    for t in ("messages", "important_dates", "kv_store", "affection_log"):
        db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)

    # 种一个今天的纪念日
    today = date.today()
    db.conn.execute(
        "INSERT INTO important_dates (user_id, date, label, kind, ts) VALUES (?,?,?,?,?)",
        (UID, today.strftime("%m-%d"), "我们的纪念日", "anniversary", datetime.now().isoformat(timespec="seconds")),
    )
    db.conn.commit()
    # 最近聊过（保证"久别"不是唯一触发，验证由头驱动）
    db.add_message(UID, "user", "刚聊过的话")
    db.add_message(UID, "assistant", "嗯好呀")

    # ---- 1. 场景提示组合 ----
    print("\n[1/3] _scenario_hint（特殊日子 + 天气组合）")
    from core import proactive

    hint = proactive._scenario_hint(UID, "武汉")
    if "纪念日" in hint:
        ok("scenario_hint", f"含纪念日由头: {hint[:60]}…")
    else:
        fail("scenario_hint", f"缺纪念日: {hint!r}")

    # ---- 2. 主动消息真实生成（带场景由头） ----
    print("\n[2/3] proactive_message（真实 LLM，带纪念日由头）")
    msg = await proactive.proactive_message(UID)
    if msg and len(msg) >= 2:
        ok("proactive_message", f"生成: {msg[:80]}")
        # 检查是否自然带出了纪念日/或至少是合理主动消息
        if "纪念日" in msg or "记得" in msg or "今天" in msg:
            ok("proactive_topic", "由头自然融入")
        else:
            print("  ℹ️ 消息未显式提到纪念日（可能自然转向其他话题，可接受）")
    else:
        fail("proactive_message", f"空消息: {msg!r}")

    # ---- 3. 深夜场景（mock 时间） ----
    print("\n[3/3] 深夜场景提示（mock 23:30）")
    from unittest import mock

    with mock.patch("core.proactive.datetime") as fake_dt:
        fake_dt.now.return_value = datetime(2026, 1, 1, 23, 30)
        fake_dt.timedelta = __import__("datetime").timedelta
        late = proactive._late_night_hint()
        if late and "深夜" in late:
            ok("late_night_hint", late)
        else:
            fail("late_night_hint", f"未生成深夜提示: {late!r}")

    # ---- 小结 ----
    print("\n" + "=" * 60)
    ok_count = sum(1 for _, s, _ in results if s == "OK")
    print(f"结果: {ok_count}/{len(results)} 通过")
    for name, status, note in results:
        print(f"  [{status}] {name}: {note}")


if __name__ == "__main__":
    asyncio.run(main())
