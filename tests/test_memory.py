"""记忆与向量检索测试（纯逻辑 + 内存 DB 隔离）。"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.memory import _tokenize, _tfidf_candidates, looks_like_recall


def test_looks_like_recall():
    assert looks_like_recall("上次说的那个呢")
    assert looks_like_recall("你还记得吗")
    assert looks_like_recall("之前你答应过我的")
    assert not looks_like_recall("今天天气不错")
    assert not looks_like_recall("帮我看看这个")


def test_tokenize_bigrams():
    toks = _tokenize("下雨天")
    assert toks == ["下雨", "雨天"] or "下雨" in toks
    assert "下雨" in _tokenize("下雨天好美")


def test_tfidf_ranks_relevant():
    docs = ["用户喜欢下雨天", "用户讨厌吃香菜", "明天要去爬山"]
    scored = _tfidf_candidates(_tokenize("下雨天好美"), docs, 3)
    assert scored[0][1] == "用户喜欢下雨天"
    scored2 = _tfidf_candidates(_tokenize("香菜真难吃"), docs, 3)
    assert scored2[0][1] == "用户讨厌吃香菜"


def test_sqlite_vec_roundtrip():
    """sqlite-vec 能加载并做相似检索（py3.14 wheel 验证）。"""
    import sqlite_vec

    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("CREATE VIRTUAL TABLE v USING vec0(a float[3])")
    conn.execute("INSERT INTO v (a) VALUES (?)", ("[1,0,0]",))
    conn.execute("INSERT INTO v (a) VALUES (?)", ("[0,1,0]",))
    rows = conn.execute(
        "SELECT rowid FROM v WHERE a MATCH ? ORDER BY distance LIMIT 1",
        ("[0.9,0.1,0]",),
    ).fetchall()
    assert rows[0][0] == 1  # 最接近 [1,0,0]
    conn.close()


def test_vector_store_embed_dims():
    """embedding 返回 1024 维（真实 API 可用时；不可用则跳过）。"""
    from core.vector_store import enabled, embed

    if not enabled():
        import pytest

        pytest.skip("SiliconFlow key 未配置")
    vec = embed("测试一下embedding")
    assert vec is not None
    assert len(vec) == 1024
