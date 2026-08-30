"""稠密向量记忆：SiliconFlow embedding + sqlite-vec 向量检索。

- embed(text) → 1024 维向量（SiliconFlow API，Qwen3-Embedding-0.6B，带本地缓存）
- index(user_id, id, text)：给一条 long_memory/facts 记录建向量
- search(user_id, query, top_k)：向量相似度检索
- 任一环节失败自动回退空（调用方仍走原有 TF-IDF 检索），不阻塞对话
"""
import hashlib
import json
import sqlite3
import threading
import urllib.request
from pathlib import Path

from .config import config
from .log import logger

VECTOR_DIM = 1024
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"

# 独立向量库连接（vec0 虚拟表需 load_extension）
_vec_conn: sqlite3.Connection | None = None
# 跨线程访问串行化：连接可被 asyncio.to_thread 的工作线程使用，
# sqlite3 需 check_same_thread=False，所有 conn 操作经此锁串行。
# 用 RLock：_vconn 首次建连接也会取锁，而调用方（index/search 等）已持锁。
_vec_lock = threading.RLock()
# embedding 缓存：text -> 向量（省 API 调用）
_emb_cache: dict[str, list[float]] = {}
_EMB_CACHE_MAX = 2000


def _vconn() -> sqlite3.Connection:
    global _vec_conn
    if _vec_conn is None:
        with _vec_lock:
            if _vec_conn is None:
                import sqlite_vec

                conn = sqlite3.connect(config.data_dir / "bot.db", check_same_thread=False)
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


def index(
    user_id: str, record_id: int, text: str, kind: str = "lm"
) -> bool:
    """给一条记忆记录建向量索引。成功返回 True，失败返回 False（不阻塞）。

    Args:
        user_id: 用户 id
        kind: 记录类型 — "lm"（long_memory）或 "facts"（facts）
        record_id: 该类型记录的主键 id
        text: 文本内容
    """
    try:
        vec = embed(text)
        if not vec:
            return False
        key = f"{user_id}:{kind}:{record_id}"
        with _vec_lock:
            conn = _vconn()
            conn.execute("DELETE FROM vec_memory WHERE id = ?", (key,))
            conn.execute(
                "INSERT INTO vec_memory (id, text_embedding) VALUES (?, ?)",
                (key, _vec_str(vec)),
            )
            conn.commit()
        return True
    except Exception:
        logger.warning("[向量] 建索引失败：{}:{}:{}", user_id, kind, record_id)
        return False


def search(
    user_id: str, query: str, top_k: int = 5, kind: str | None = None
) -> list[tuple[int, float]]:
    """向量检索，返回 [(record_id, distance), ...]（distance 越小越相似）。

    Args:
        user_id: 用户 id
        query: 查询文本
        top_k: 返回条数
        kind: 过滤类型 — "lm"、"facts" 或 None（不过滤所有类型）
    """
    try:
        vec = embed(query)
        if not vec:
            return []
        with _vec_lock:
            conn = _vconn()
            # 放大 k 避免多用户下当前用户的候选被其他用户挤出
            rows = conn.execute(
                "SELECT id, distance FROM vec_memory WHERE text_embedding MATCH ? AND k = ?",
                (_vec_str(vec), top_k * 20),
            ).fetchall()
        prefix = f"{user_id}:{kind}:" if kind else f"{user_id}:"
        out = []
        for r in rows:
            rid_str = r["id"]
            if not rid_str.startswith(prefix):
                continue
            try:
                parts = rid_str.split(":", maxsplit=2)
                out.append((int(parts[2]), r["distance"]))
            except (ValueError, IndexError):
                continue
        out.sort(key=lambda x: x[1])
        return out[:top_k]
    except Exception:
        logger.warning("[向量] 检索失败：{}", query[:30])
        return []


def indexed_count() -> int:
    """当前向量索引总条数（用于判断是否需要回填）。"""
    try:
        with _vec_lock:
            conn = _vconn()
            return conn.execute("SELECT COUNT(*) AS c FROM vec_memory").fetchone()["c"]
    except Exception:
        return 0


def backfill(user_id: str = "", limit: int = 1000) -> int:
    """给存量记忆补建向量索引（启动时后台执行）。

    遍历 long_memory + facts 里还没有向量索引的记录，逐条建索引。
    返回本次新建的条数。失败静默（下次启动再补）。

    注意：按表分 kind 命名空间，避免两表 id 冲突覆盖索引。

    锁策略（修 database is locked）：
    - 读连接用独立连接 + busy_timeout（不占主线程 db.conn 写锁）
    - embedding 网络调用在写事务外进行（避免 long-run 写锁阻塞主线程写）
    - 索引插入分批提交（每批几十条），及时释放写锁，主线程写不受长时间阻塞
    """
    # 在 to_thread 工作线程里执行，需独立读连接（不能碰主线程建的 db.conn）
    read_conn = sqlite3.connect(config.data_dir / "bot.db", timeout=10)
    read_conn.row_factory = sqlite3.Row
    built = 0
    pending: list[tuple[str, str]] = []  # 待处理的 (key, content)
    try:
        # 阶段 0：锁外收集所有候选（读扫描 + exists 判断交给阶段 2，这里只读数据表）
        for table, kind in (("long_memory", "lm"), ("facts", "facts")):
            last_id = 0
            while True:
                rows = read_conn.execute(
                    "SELECT id, user_id, content FROM {} WHERE id > ? ORDER BY id LIMIT ?".format(table),
                    (last_id, limit),
                ).fetchall()
                if not rows:
                    break
                for row in rows:
                    rid, uid, content = row["id"], row["user_id"], row["content"]
                    last_id = rid
                    if user_id and uid != user_id:
                        continue
                    pending.append((f"{uid}:{kind}:{rid}", content))
        # 阶段 1：锁外全部 embedding（无锁、无写事务，主线程读写完全不受影响）
        embedded: list[tuple[str, list[float]]] = []
        for key, content in pending:
            vec = embed(content)
            if not vec:
                continue
            embedded.append((key, vec))
        if not embedded:
            if built:
                logger.info("[向量] 存量回填完成，新增 {} 条索引", built)
            return 0
        # 阶段 2：锁内 exists 过滤 + 快速插入 + 分批提交（锁只持有本地毫秒级操作）
        with _vec_lock:
            conn = _vconn()
            for key, vec in embedded:
                exists = conn.execute(
                    "SELECT 1 FROM vec_memory WHERE id=?", (key,)
                ).fetchone()
                if exists:
                    continue
                conn.execute(
                    "INSERT INTO vec_memory (id, text_embedding) VALUES (?, ?)",
                    (key, _vec_str(vec)),
                )
                built += 1
                # 分批提交：每 50 条释放一次写锁，避免长事务阻塞主线程写
                if built % 50 == 0:
                    conn.commit()
            conn.commit()
        if built:
            logger.info("[向量] 存量回填完成，新增 {} 条索引", built)
    except Exception:
        logger.warning("[向量] 存量回填失败（下次启动重试）")
    finally:
        read_conn.close()
    return built
