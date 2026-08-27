"""短期上下文 + 长期记忆检索。

v1 用关键词（二元组）命中；语义检索在此基础上做 LLM 查询扩展：
用户疑似回忆时，先把问题扩展成几个检索词再查，提升召回。
接口（recall / recall_facts）保持同步签名，语义扩展在内部 await 完成；
调用方本就位于 async 上下文（pipeline.process / test_memory）。
"""
import json

from .config import config
from .llm import chat
from .log import logger
from .userdb import db

SHORT_TERM_LIMIT = 30
LONG_TERM_TOP_K = 3

# 疑似回忆触发词：命中才做 LLM 查询扩展（省一次 LLM 调用）
_RECALL_HINTS = (
    "上次", "之前", "以前", "还记得", "记得吗", "那天", "昨天", "刚才",
    "我说过", "你答应", "我们说好", "你不是说", "你不是答应", "老地方", "那个",
)


def looks_like_recall(text: str) -> bool:
    """判断这句是否在翻旧账/回忆以前的事（决定要不要做语义扩展）。"""
    return any(w in text for w in _RECALL_HINTS)


async def expand_query(user_id: str, query: str, *, mock: bool = False) -> list[str]:
    """把用户问题扩展成几个检索关键词/短语（语义检索的召回来源）。

    只取 2-6 个实体词（人名/物品/地点/事件/喜好），不保留疑问词和口语虚词。
    mock=True 或 LLM 失败时退化为原句，保证功能可用。
    """
    if not config.memory_semantic:
        return [query]
    if mock:
        return [query]
    prompt = (
        "你是记忆检索助手。用户问了一个问题（可能是在回忆以前聊过的事）。"
        "请提取 2-6 个最适合去聊天记录里检索的『关键词/短语』，要具体（人名、物品、地点、事件、喜好、约定等），"
        "不要疑问词、不要语气词、不要整句复述。只输出 JSON 数组字符串，如 [\"养猫\",\"猫粮\",\"布偶\"]，不要其他文字。\n"
        f"用户的问题：{query}"
    )
    try:
        resp = await chat(
            [{"role": "system", "content": "只输出 JSON 数组，不要任何解释。"}, {"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200,
        )
        cleaned = resp.strip().strip("`").strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        terms = json.loads(cleaned)
        if isinstance(terms, list) and terms:
            return [str(t) for t in terms if str(t).strip()]
    except Exception:
        logger.warning("[记忆] 查询扩展失败，退化为原句检索：{}", query)
    return [query]


def short_term_messages(user_id: str) -> list[dict]:
    """最近 N 轮对话，作为 chat 的 messages 上下文。"""
    rows = db.recent_messages(user_id, SHORT_TERM_LIMIT)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


async def recall(user_id: str, query: str, *, mock: bool = False) -> list[str]:
    """长期记忆检索（对话原文片段）。

    v1 用关键词命中；语义模式（MEMORY_SEMANTIC=1）下先做 LLM 查询扩展再检索，
    仅当语句疑似回忆时触发。接口签名不变，调用方无需感知。
    """
    if looks_like_recall(query):
        return await _recall_with_expansion(user_id, query, mock=mock)
    return [h["content"] for h in db.search_long_memory(user_id, query, LONG_TERM_TOP_K)]


async def recall_facts(user_id: str, query: str, *, mock: bool = False) -> list[str]:
    """检索 LLM 提炼的长期事实（用户喜好/约定等）。"""
    if looks_like_recall(query):
        return await _facts_with_expansion(user_id, query, mock=mock)
    return [h["content"] for h in db.search_facts(user_id, query, LONG_TERM_TOP_K)]


async def _recall_with_expansion(user_id: str, query: str, *, mock: bool = False) -> list[str]:
    terms = await expand_query(user_id, query, mock=mock)
    return [h["content"] for h in db.search_long_memory_multi(user_id, terms, LONG_TERM_TOP_K)]


async def _facts_with_expansion(user_id: str, query: str, *, mock: bool = False) -> list[str]:
    terms = await expand_query(user_id, query, mock=mock)
    found: list[str] = []
    for t in terms:
        for h in db.search_facts(user_id, t, LONG_TERM_TOP_K):
            if h["content"] not in found:
                found.append(h["content"])
        if len(found) >= LONG_TERM_TOP_K:
            break
    return found[:LONG_TERM_TOP_K]
