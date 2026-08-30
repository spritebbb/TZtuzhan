"""话题记忆（跨会话延续）的纯逻辑测试。

覆盖：
- 话题提炼：有足够新消息时提炼并落库、游标推进；消息不足时跳过
- 话题读取与延续提示：无话题返回 None、太旧的话题不再主动提
- mock 模式：返回固定话题文本
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import topic_memory, userdb
from core.topic_memory import build_continuation, extract_topic, last_topic

db = userdb.db

UID = "pytest-topic-memory"


def _clean():
    db.ensure_user(UID)
    db.conn.execute("DELETE FROM messages WHERE user_id=?", (UID,))
    for key in ("last_topic", "last_topic_ts", "last_topic_msg_id"):
        db.conn.execute("DELETE FROM kv_store WHERE user_id=? AND key=?", (UID, key))
    db.conn.commit()


def _seed_messages(n: int):
    import datetime

    base = datetime.datetime.now() - datetime.timedelta(minutes=30)
    for i in range(n):
        ts = (base + datetime.timedelta(minutes=1) * i).isoformat(timespec="seconds")
        db.conn.execute(
            "INSERT INTO messages (user_id, role, content, ts) VALUES (?,?,?,?)",
            (UID, "user" if i % 2 == 0 else "assistant", f"测试消息{i}号", ts),
        )
    db.conn.commit()


def test_extract_topic_mock_saves_and_advances():
    _clean()
    _seed_messages(6)
    import asyncio

    topic = asyncio.run(extract_topic(UID, mock=True))
    assert topic is not None
    assert last_topic(UID) == topic
    # 游标推进到最后一条消息 id
    from core.userdb import kv_get

    cursor = int(kv_get(UID, "last_topic_msg_id") or "0")
    max_id = db.conn.execute(
        "SELECT MAX(id) FROM messages WHERE user_id=?", (UID,)
    ).fetchone()[0]
    assert cursor == max_id


def test_extract_topic_skips_few_messages():
    _clean()
    _seed_messages(2)
    import asyncio

    topic = asyncio.run(extract_topic(UID, mock=True))
    assert topic is None  # 消息不足，不提炼
    assert last_topic(UID) is None


def test_build_continuation_returns_none_without_topic():
    _clean()
    assert build_continuation(UID) is None


def test_build_continuation_returns_topic():
    _clean()
    _seed_messages(6)
    import asyncio

    asyncio.run(extract_topic(UID, mock=True))
    cont = build_continuation(UID)
    assert cont is not None and len(cont) >= 2


def test_build_continuation_stale_topic_ignored():
    _clean()
    _seed_messages(6)
    import asyncio
    from datetime import datetime, timedelta

    asyncio.run(extract_topic(UID, mock=True))
    # 把话题时间改成 5 天前 → 不应再主动提
    from core.userdb import kv_set

    kv_set(UID, "last_topic_ts", (datetime.now() - timedelta(days=5)).isoformat(timespec="seconds"))
    assert build_continuation(UID) is None
