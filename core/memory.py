"""短期上下文 + 长期记忆检索。

v1 用关键词（二元组）命中；语义检索在此基础上做 LLM 查询扩展 + TF-IDF 重排序：
- 用户疑似回忆时，先把问题扩展成几个检索词再查
- 候选结果用 TF-IDF 余弦相似度重排（替代原始 bigram 重叠分）
- 接口（recall / recall_facts）保持同步签名，调用方本就位于 async 上下文
"""
import json
import math
import re
from collections import Counter

from .config import config
from .llm import chat
from .log import logger
from .userdb import db

_SHORT_TERM_LIMIT = 30
LONG_TERM_TOP_K = 3

# 长会话压缩：总消息超过该条数时，把旧部分摘要化，只保留最近的完整消息
COMPACT_TOTAL_TRIGGER = 60      # 超过多少条触发压缩
COMPACT_KEEP_RECENT = 14        # 保留最近多少条完整消息
COMPACT_OLDER_LIMIT = 200       # 参与摘要的旧消息上限（控制摘要 prompt 大小）

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
        "不要疑问词、不要语气词、不要整句复述。尤其注意：把问题里的『核心实体词』抽出来"
        "（比如『你还记得我上次说喜欢什么天气吗』→『下雨天』『晴天』，而不是『什么天气』），"
        "去掉『什么/怎么/哪/记得/上次/说』这类虚词和疑问词。只输出 JSON 数组字符串，"
        "如 [\"养猫\",\"猫粮\",\"布偶\"]，不要其他文字。\n"
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
    rows = db.recent_messages(user_id, _SHORT_TERM_LIMIT)
    return [{"role": r["role"], "content": r["content"]} for r in rows]



# 本地版 strip_actions（避免循环引用 pipeline）
_PAREN_RE = re.compile(r"（[^）]*）|\([^)]*\)")
def _strip_parens(text: str) -> str:
    return _PAREN_RE.sub("", text).strip()


# ---- TF-IDF 稀疏向量检索（真向量召回，替代纯 bigram 重叠打分）----
# 中文没有空格分词，这里用「字符二元组」做特征（对中文记忆检索够用且无依赖）。


def _tokenize(text: str) -> list[str]:
    """把文本切成字符二元组特征。"""
    t = re.sub(r"\s+", "", text)
    if len(t) < 2:
        return list(t)
    return [t[i : i + 2] for i in range(len(t) - 1)]


def _tfidf_candidates(
    query_terms: list[str],
    docs: list[str],
    top_k: int,
) -> list[tuple[float, str]]:
    """对候选文档做 TF-IDF 余弦相似度排序，返回 (score, doc) 列表。

    docs 是候选文本（如 bigram 命中的结果，或全部长期记忆/事实）。
    用 query 的 token 作为查询向量，与每篇文档的 TF-IDF 向量算余弦。
    """
    if not query_terms:
        return []
    # 文档集合的 IDF：df 计数
    doc_tf: list[Counter] = [Counter(_tokenize(d)) for d in docs]
    df: Counter = Counter()
    for tf in doc_tf:
        for term in tf:
            df[term] += 1
    n_docs = max(1, len(docs))
    idf = {term: math.log((1 + n_docs) / (1 + df[term])) + 1 for term in df}

    # 查询向量（tf*idf）
    q_tf = Counter(query_terms)
    q_vec = {t: (q_tf[t] * idf.get(t, math.log(1 + n_docs) + 1)) for t in q_tf}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1

    scored: list[tuple[float, str]] = []
    for doc, tf in zip(docs, doc_tf):
        if not tf:
            continue
        d_norm = math.sqrt(sum((cnt * idf.get(term, 1)) ** 2 for term, cnt in tf.items())) or 1
        dot = sum(q_tf[term] * idf.get(term, 1) * tf[term] for term in q_tf if term in tf)
        # 余弦 + 小量长度惩罚（避免短句刷分）
        cos = dot / (q_norm * d_norm)
        length_penalty = 1.0 if len(doc) >= 4 else 0.6
        scored.append((cos * length_penalty, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]


def message_count(user_id: str) -> int:
    """该用户总共的聊天消息数（用于判断是否需要压缩长会话）。"""
    row = db.conn.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row["c"] or 0


async def compact_context(user_id: str, *, mock: bool = False) -> tuple[str, list[dict]] | None:
    """长会话压缩：总消息很多时，把旧消息摘要成一段记忆，返回 (摘要, 最近完整消息)。

    返回 None 表示会话还不够长、无需压缩（保持原有 30 条上下文）。
    失败时也返回 None（调用方自然退化为原逻辑，不阻塞对话）。
    """
    try:
        total = message_count(user_id)
        if total < COMPACT_TOTAL_TRIGGER:
            return None
        rows = db.recent_messages(user_id, _SHORT_TERM_LIMIT)
        # 旧部分：最早一批（排除最近完整保留的那些）
        old_rows = db.recent_messages(user_id, min(COMPACT_OLDER_LIMIT, total))
        recent_count = min(COMPACT_KEEP_RECENT, len(rows))
        old_rows = old_rows[:-recent_count] if recent_count > 0 else old_rows
        if not old_rows:
            return None
        transcript = "\n".join(
            f"{'对方' if r['role'] == 'user' else '菟菚'}：{r['content'][:120]}"
            for r in old_rows
        )
        if not transcript.strip():
            return None
        if mock:
            summary = f"旧聊天的摘要：共 {len(old_rows)} 条，主题略"
        else:
            summary = await chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是记忆整理助手。下面是一段 AI 女友和一个朋友的旧聊天记录（按时间顺序）。"
                            "请压缩成一段 3-6 句的『记忆摘要』，只保留：①对方透露的关于自己的重要信息"
                            "（喜好、习惯、经历、约定、家人朋友、情绪状态）②两人的关系进展与默契"
                            "③对方说过的重要的事（说过要做什么/答应过什么）。丢掉闲聊废话。"
                            "用第三人称、客观、紧凑，不要复述对话，不要加评价。只输出摘要本身。"
                        ),
                    },
                    {"role": "user", "content": transcript},
                ],
                temperature=0.3,
                max_tokens=300,
            )
        summary = _strip_parens(summary).strip()
        keep = [{"role": r["role"], "content": r["content"]} for r in rows[-recent_count:]]
        return summary, keep
    except Exception:
        logger.exception("[记忆] 长会话压缩失败，退化为原上下文")
        return None


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
    # 原句始终参与检索：扩展词可能抽不准（含虚词/未命中实体），原句 bigram 是可靠兜底
    if query.strip() and query.strip() not in terms:
        terms = [query.strip()] + terms
    # 先取全部候选（放宽 top_k），再用 TF-IDF 重排
    all_rows = db.search_long_memory_multi(user_id, terms, 20)
    candidates = [h["content"] for h in all_rows]
    if not candidates:
        return []
    # 用原句 + 扩展词一起做查询向量
    query_terms = _tokenize(query) + [t for t in terms if len(t) > 1]
    scored = _tfidf_candidates(query_terms, candidates, LONG_TERM_TOP_K)
    tfidf_result = [doc for _, doc in scored]

    # 补充稠密向量检索（把 TF-IDF 没排第一但语义相似度高的结果也拉进来）
    try:
        from .vector_store import search as vec_search

        vec_results = vec_search(user_id, query, LONG_TERM_TOP_K)
        if vec_results:
            # 按 record_id 反查内容
            existing_ids = set()
            vec_docs: list[str] = []
            for rid, dist in vec_results:
                row = db.conn.execute(
                    "SELECT content FROM long_memory WHERE user_id=? AND id=?", (user_id, rid)
                ).fetchone()
                if row and row["content"] not in existing_ids:
                    existing_ids.add(row["content"])
                    vec_docs.append(row["content"])
            # 融合：向量结果排前面，TF-IDF 做补充（去重）
            seen = set(vec_docs)
            for doc in tfidf_result:
                if doc not in seen:
                    vec_docs.append(doc)
                    seen.add(doc)
            return vec_docs[:LONG_TERM_TOP_K]
    except Exception:
        logger.warning("[记忆] 向量检索补充失败，仅用 TF-IDF")
    return tfidf_result


async def _facts_with_expansion(user_id: str, query: str, *, mock: bool = False) -> list[str]:
    terms = await expand_query(user_id, query, mock=mock)
    # 原句始终参与检索（同 _recall_with_expansion）
    if query.strip() and query.strip() not in terms:
        terms = [query.strip()] + terms
    candidates: list[str] = []
    for t in terms:
        for h in db.search_facts(user_id, t, 10):
            if h["content"] not in candidates:
                candidates.append(h["content"])
    if not candidates:
        return []
    query_terms = _tokenize(query) + [t for t in terms if len(t) > 1]
    scored = _tfidf_candidates(query_terms, candidates, LONG_TERM_TOP_K)
    tfidf_result = [doc for _, doc in scored]

    # 补充稠密向量检索
    try:
        from .vector_store import search as vec_search

        vec_results = vec_search(user_id, query, LONG_TERM_TOP_K)
        if vec_results:
            existing_ids = set()
            vec_docs: list[str] = []
            for rid, dist in vec_results:
                row = db.conn.execute(
                    "SELECT content FROM facts WHERE user_id=? AND id=?", (user_id, rid)
                ).fetchone()
                if row and row["content"] not in existing_ids:
                    existing_ids.add(row["content"])
                    vec_docs.append(row["content"])
            seen = set(vec_docs)
            for doc in tfidf_result:
                if doc not in seen:
                    vec_docs.append(doc)
                    seen.add(doc)
            return vec_docs[:LONG_TERM_TOP_K]
    except Exception:
        logger.warning("[记忆] 事实向量检索补充失败，仅用 TF-IDF")
    return tfidf_result
