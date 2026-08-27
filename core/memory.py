"""短期上下文 + 长期记忆检索。"""
from .userdb import db

SHORT_TERM_LIMIT = 30
LONG_TERM_TOP_K = 3


def short_term_messages(user_id: str) -> list[dict]:
    """最近 N 轮对话，作为 chat 的 messages 上下文。"""
    rows = db.recent_messages(user_id, SHORT_TERM_LIMIT)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def recall(user_id: str, query: str) -> list[str]:
    """长期记忆检索。

    v1 用关键词命中（见 userdb.search_long_memory），
    后续可无缝替换为向量检索（chromadb / sqlite-vec），接口不变。
    """
    return [h["content"] for h in db.search_long_memory(user_id, query, LONG_TERM_TOP_K)]
