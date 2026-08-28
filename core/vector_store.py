"""稠密向量记忆：SiliconFlow embedding + sqlite-vec 向量检索。

- embed(text) → 1024 维向量（SiliconFlow API，Qwen3-Embedding-0.6B，带本地缓存）
- index(user_id, id, text)：给一条 long_memory/facts 记录建向量
- search(user_id, query, top_k)：向量相似度检索
- 任一环节失败自动回退空（调用方仍走原有 TF-IDF 检索），不阻塞对话
"""
import hashlib
import json
import sqlite3
import urllib.request
from pathlib import Path

from .config import config
from .log import logger

VECTOR_DIM = 1024
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"

# 独立向量库连接（vec0 虚拟表需 load_extension）
_vec_conn: sqlite3.Connection | None = None
# embedding 缓存：text -> 向量（省 API 调用）
_emb_cache: dict[str, list[float]] = {}
_EMB_CACHE_MAX = 2000


def _vconn() -> sqlite3.Connection:
    global _vec_conn
    if _vec_conn is None:
        import sqlite_vec

        conn = sqlite3.connect(config.data_dir / "bot.db")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_memory USING vec0(id TEXT PRIMARY KEY, text_embedding float[{VECTOR_DIM}])"
        )
        conn.commit()
        _vec_conn = conn
    return _vec_conn


def enabled() -> bool:
    """embedding 功能是否可用（SiliconFlow key 已配）。"""
    return bool(config.image_api_key)  # 复用 SiliconFlow key


def embed(text: str) -> list[float] | None:
    """文本 → 向量；失败返回 None（调用方回退）。"""
    if not enabled():
        return None
    text = text.strip()
    if not text:
        return None
    # 缓存命中
    if text in _emb_cache:
        return _emb_cache[text]
    try:
        payload = json.dumps(
            {
                "model": EMBED_MODEL,
                "input": [text],
                "encoding_format": "float",
                "dimensions": VECTOR_DIM,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{config.image_base_url.rstrip('/')}/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {config.image_api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        embs = data.get("data") or []
        if not embs or not embs[0].get("embedding"):
            return None
        vec = list(embs[0]["embedding"])
        if len(_emb_cache) >= _EMB_CACHE_MAX:
            _emb_cache.clear()
        _emb_cache[text] = vec
        return vec
    except Exception:
        logger.warning("[向量] embedding 失败：{}", text[:30])
        return None


def _vec_str(vec: list[float]) -> str:
    return json.dumps(vec, separators=(",", ":"))


def index(user_id: str, record_id: int, text: str) -> bool:
    """给一条记忆记录建向量索引。成功返回 True，失败返回 False（不阻塞）。"""
    try:
        vec = embed(text)
        if not vec:
            return False
        key = f"{user_id}:{record_id}"
        conn = _vconn()
        # 先删旧索引再插入（UPSERT 语义）
        conn.execute("DELETE FROM vec_memory WHERE id = ?", (key,))
        conn.execute(
            "INSERT INTO vec_memory (id, text_embedding) VALUES (?, ?)",
            (key, _vec_str(vec)),
        )
        conn.commit()
        return True
    except Exception:
        logger.warning("[向量] 建索引失败：{}:{}", user_id, record_id)
        return False


def search(user_id: str, query: str, top_k: int = 5) -> list[tuple[int, float]]:
    """向量检索，返回 [(record_id, distance), ...]（distance 越小越相似）。

    vec0 KNN 查询用 `k = ?` 内嵌限制条数；user_id 过滤在 Python 侧做
    （vec0 的 MATCH 不支持与 LIKE/WHERE 组合）。
    """
    try:
        vec = embed(query)
        if not vec:
            return []
        conn = _vconn()
        rows = conn.execute(
            "SELECT id, distance FROM vec_memory WHERE text_embedding MATCH ? AND k = ?",
            (_vec_str(vec), top_k * 3),  # 多取一些再按 user 过滤
        ).fetchall()
        out = []
        prefix = f"{user_id}:"
        for r in rows:
            rid_str = r["id"]
            if not rid_str.startswith(prefix):
                continue
            try:
                out.append((int(rid_str.split(":", 1)[1]), r["distance"]))
            except ValueError:
                continue
        out.sort(key=lambda x: x[1])
        return out[:top_k]
    except Exception:
        logger.warning("[向量] 检索失败：{}", query[:30])
        return []


def indexed_count() -> int:
    """当前向量索引总条数（用于判断是否需要回填）。"""
    try:
        conn = _vconn()
        return conn.execute("SELECT COUNT(*) AS c FROM vec_memory").fetchone()["c"]
    except Exception:
        return 0


def backfill(user_id: str = "", limit: int = 1000) -> int:
    """给存量记忆补建向量索引（启动时后台执行）。

    遍历 long_memory + facts 里还没有向量索引的记录，逐条建索引。
    返回本次新建的条数。失败静默（下次启动再补）。
    """
    from .userdb import db

    built = 0
    try:
        conn = _vconn()
        for table in ("long_memory", "facts"):
            rows = db.conn.execute(
                f"SELECT id, user_id, content FROM {table} ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            for row in rows:
                rid, uid, content = row["id"], row["user_id"], row["content"]
                if user_id and uid != user_id:
                    continue
                # 与 index() 一致的 key 格式：{user_id}:{record_id}
                key = f"{uid}:{rid}"
                exists = conn.execute(
                    "SELECT 1 FROM vec_memory WHERE id=?", (key,)
                ).fetchone()
                if exists:
                    continue
                vec = embed(content)
                if not vec:
                    continue
                conn.execute(
                    "INSERT INTO vec_memory (id, text_embedding) VALUES (?, ?)",
                    (key, _vec_str(vec)),
                )
                built += 1
        conn.commit()
        if built:
            logger.info("[向量] 存量回填完成，新增 {} 条索引", built)
    except Exception:
        logger.warning("[向量] 存量回填失败（下次启动重试）")
    return built
