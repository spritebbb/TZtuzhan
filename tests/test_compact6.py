"""上下文 6 分区压缩（方向 A）的纯逻辑测试。

覆盖：
- _parse_compact_json：解析 6 分区 JSON（含 ```json 围栏 / 截断容错）
- _format_section_summary：JSON → 注入文本（缺字段跳过）
- compact_context mock：返回结构化摘要并持久化到 kv_store
- 跨会话继承：load_compact_summary / save_compact_summary 往返
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import memory, userdb

db = userdb.db

UID = "pytest-compact6"


def _clean():
    db.ensure_user(UID)
    db.conn.execute("DELETE FROM messages WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)


def _seed_messages(n: int):
    import datetime

    base = datetime.datetime.now() - datetime.timedelta(hours=1)
    for i in range(n):
        ts = (base + datetime.timedelta(minutes=1) * i).isoformat(timespec="seconds")
        db.conn.execute(
            "INSERT INTO messages (user_id, role, content, ts) VALUES (?,?,?,?)",
            (UID, "user" if i % 2 == 0 else "assistant", f"消息{i}号：我喜欢下雨天和养猫", ts),
        )
    db.conn.commit()


# ---- JSON 解析 ----

def test_parse_compact_json_plain():
    obj = memory._parse_compact_json('{"关键事实": "a", "用户偏好": "b"}')
    assert obj == {"关键事实": "a", "用户偏好": "b"}


def test_parse_compact_json_fenced():
    obj = memory._parse_compact_json('```json\n{"关键事实": "a"}\n```')
    assert obj == {"关键事实": "a"}


def test_parse_compact_json_truncated():
    # 缺右大括号（LLM 截断）→ 补全解析
    obj = memory._parse_compact_json('{"关键事实": "a", "用户偏好": "b"')
    assert obj and obj.get("关键事实") == "a"


def test_parse_compact_json_garbage():
    assert memory._parse_compact_json("完全不是JSON") is None


# ---- 格式化 ----

def test_format_section_summary_skips_empty():
    data = {"关键事实": "a", "用户偏好": "", "重要决定": "b"}
    text = memory._format_section_summary(data)
    assert "【关键事实】a" in text
    assert "【重要决定】b" in text
    assert "用户偏好" not in text  # 空字段跳过


# ---- 压缩（mock） ----

def test_compact_context_below_trigger():
    _clean()
    _seed_messages(10)  # 未达 60 条阈值
    import asyncio

    assert asyncio.run(memory.compact_context(UID, mock=True)) is None


def test_compact_context_mock_sections():
    _clean()
    _seed_messages(70)  # 超过阈值
    import asyncio

    result = asyncio.run(memory.compact_context(UID, mock=True))
    assert result is not None
    summary, keep = result
    assert "【关键事实】" in summary
    assert len(keep) > 0
    # 已持久化
    assert memory.load_compact_summary(UID) == summary


# ---- 跨会话继承 ----

def test_cross_session_inheritance():
    _clean()
    memory.save_compact_summary(UID, "【关键事实】用户喜欢养猫")
    assert memory.load_compact_summary(UID) == "【关键事实】用户喜欢养猫"

    # 模拟新会话：无消息也读得到继承的摘要
    assert memory.load_compact_summary(UID) is not None


def test_load_compact_summary_none():
    _clean()
    assert memory.load_compact_summary(UID) is None