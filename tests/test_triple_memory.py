"""结构化事实记忆（五元组）的纯逻辑测试。

覆盖：
- _parse_triples：解析 JSON 五元组数组（含围栏/损坏容错）
- extract_triples mock：返回固定五元组
- save_triples：入库 + 去重
- query_triples：TF-IDF 检索命中相关三元组
- format_triples：格式化注入文本
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import triple_memory, userdb

db = userdb.db

UID = "pytest-triples"


def _clean():
    db.ensure_user(UID)
    db.conn.execute("DELETE FROM triples WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)


# ---- 解析 ----

def test_parse_triples_plain():
    out = triple_memory._parse_triples('[["用户","人物","喜欢","猫","动物"]]')
    assert out == [["用户", "人物", "喜欢", "猫", "动物"]]


def test_parse_triples_fenced():
    out = triple_memory._parse_triples('```json\n[["用户","人物","养","猫","动物"]]\n```')
    assert len(out) == 1 and out[0][2] == "养"


def test_parse_triples_bad_length_filtered():
    out = triple_memory._parse_triples('[["用户","人物","喜欢"],["用户","人物","喜欢","猫","动物"]]')
    assert len(out) == 1 and len(out[0]) == 5


def test_parse_triples_garbage():
    assert triple_memory._parse_triples("完全不是JSON") == []


# ---- 提取（mock） ----

def test_extract_triples_mock():
    import asyncio

    out = asyncio.run(triple_memory.extract_triples("我喜欢猫", mock=True))
    assert len(out) == 1 and len(out[0]) == 5


# ---- 保存 + 去重 ----

def test_save_triples_dedup():
    _clean()
    n1 = triple_memory.save_triples(UID, [["用户", "人物", "喜欢", "猫", "动物"]], "src1")
    n2 = triple_memory.save_triples(UID, [["用户", "人物", "喜欢", "猫", "动物"]], "src2")
    n3 = triple_memory.save_triples(UID, [["用户", "人物", "喜欢", "下雨天", "概念"]], "src3")
    assert n1 == 1
    assert n2 == 0  # 重复不存
    assert n3 == 1
    rows = db.conn.execute("SELECT * FROM triples WHERE user_id=?", (UID,)).fetchall()
    assert len(rows) == 2


# ---- 检索 ----

def test_query_triples_relevant():
    _clean()
    triple_memory.save_triples(UID, [
        ["用户", "人物", "喜欢", "下雨天", "概念"],
        ["用户", "人物", "养", "布偶猫", "动物"],
        ["用户", "人物", "讨厌", "香菜", "物品"],
    ])
    hits = triple_memory.query_triples(UID, "你记得我养了什么吗")
    # 布偶猫相关应被检索到
    assert any("猫" in o or "猫" in s for _, _, _, o, _ in hits for s in [""]) or \
        any("布偶猫" in str(h) for h in hits)


def test_query_triples_empty():
    _clean()
    assert triple_memory.query_triples(UID, "anything") == []


# ---- 格式化 ----

def test_format_triples():
    text = triple_memory.format_triples([("用户", "人物", "喜欢", "猫", "动物")])
    assert "用户(人物) —[喜欢]→ 猫(动物)" in text


def test_format_triples_empty():
    assert triple_memory.format_triples([]) == ""