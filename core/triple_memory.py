"""结构化事实记忆（五元组：主体-谓词-客体-类型）。

参考 NagaAgent 的 GRAG quintuple_extractor，但落地到 SQLite（菟菚无 Neo4j）。

功能：
- extract_triples(text)：LLM 提取五元组
- save_triples(user_id, triples, source_msg)：存库（去重）
- query_triples(user_id, query)：RAG 检索（TF-IDF 匹配主体/客体/谓词）
- format_triples(triples)：格式化为注入文本

在 pipeline 中惰性提取 + 对话时检索注入。
"""
import json
import math
import re
from collections import Counter
from datetime import datetime

from .llm import chat
from .log import logger
from .userdb import db

# 一次最多提取的三元组数
_MAX_TRIPLES = 8

# 检索返回数
_RETRIEVE_TOP_K = 6

EXTRACT_PROMPT = """你是一个专业的中文事实抽取助手。从以下对话中提取有价值的事实性五元组：

(主体, 主体类型, 谓词, 客体, 客体类型)

## 类型可选
人物 / 地点 / 组织 / 物品 / 概念 / 时间 / 事件 / 活动 / 动物

## 提取规则
1. 只提取事实性信息：具体行为、实体关系、状态、属性、偏好、需求、计划、约定
2. 过滤以下内容：比喻/拟人/夸张、假设/想象、纯情感表达（"我很开心"）、赞美/调侃、闲聊废话
3. 一个句子可以提取多个五元组
4. 主体通常是"用户"或"菟菚"，客体是具体的事物

## 示例
输入：用户说：我喜欢下雨天养猫
输出：[["用户", "人物", "喜欢", "下雨天", "概念"], ["用户", "人物", "养", "猫", "动物"]]

输入：用户说：你像小太阳一样温暖
输出：[]  （比喻句，不提取）

输入：用户说：下个月要交季度报告，还想一起去爬山
输出：[["用户", "人物", "要交", "季度报告", "物品"], ["用户", "人物", "想去", "爬山", "活动"], ["用户", "人物", "约定", "一起去爬山", "活动"]]

只输出 JSON 数组，不要其他任何内容。
"""


def _tokenize(text: str) -> list[str]:
    """字符二元组特征（复用 memory.py 的 TF-IDF 逻辑）。"""
    t = re.sub(r"\s+", "", text)
    if len(t) < 2:
        return list(t)
    return [t[i:i + 2] for i in range(len(t) - 1)]


def _tfidf_score(query_terms: list[str], docs: list[tuple[int, str]]) -> list[tuple[float, int]]:
    """对候选文档做 TF-IDF 余弦相似度排序，返回 (score, doc_id) 列表。

    docs 形如 [(doc_id, text), ...]。
    """
    if not query_terms or not docs:
        return []
    doc_texts = [d[1] for d in docs]
    doc_tf = [Counter(_tokenize(d)) for d in doc_texts]
    df = Counter()
    for tf in doc_tf:
        for term in tf:
            df[term] += 1
    n_docs = max(1, len(docs))
    idf = {term: math.log((1 + n_docs) / (1 + df[term])) + 1 for term in df}

    q_tf = Counter(query_terms)
    q_vec = {t: (q_tf[t] * idf.get(t, 1)) for t in q_tf}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1

    scored: list[tuple[float, int]] = []
    for (doc_id, text), tf in zip(docs, doc_tf):
        if not tf:
            continue
        d_norm = math.sqrt(sum((cnt * idf.get(term, 1)) ** 2 for term, cnt in tf.items())) or 1
        dot = sum(q_tf[term] * idf.get(term, 1) * tf[term] for term in q_tf if term in tf)
        cos = dot / (q_norm * d_norm)
        scored.append((cos, doc_id))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _parse_triples(text: str) -> list[list[str]]:
    """解析 LLM 返回的 JSON 五元组数组。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    result = None
    try:
        result = json.loads(cleaned)
    except Exception:
        # 尝试从文本中提取 JSON 数组：用贪婪匹配到最后一个 ]，避免非贪婪在第一个 ] 截断
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
            except Exception:
                return []
    if not isinstance(result, list):
        return []
    valid = []
    for item in result:
        if isinstance(item, list) and len(item) == 5 and all(isinstance(x, str) for x in item):
            valid.append([x.strip() for x in item])
    return valid[:32]


async def extract_triples(text: str, *, mock: bool = False) -> list[list[str]]:
    """从文本中提取结构化五元组。"""
    if mock:
        return [["用户", "人物", "喜欢", "测试", "概念"]]
    try:
        resp = await chat(
            [{"role": "system", "content": EXTRACT_PROMPT}, {"role": "user", "content": text}],
            temperature=0.3,
            max_tokens=500,
        )
        triples = _parse_triples(resp)
        return triples[:_MAX_TRIPLES]
    except Exception:
        logger.exception("[三元组] 提取失败")
        return []


def save_triples(user_id: str, triples: list[list[str]], source_msg: str = "") -> int:
    """存五元组到数据库（去重），返回新插入数。"""
    now = datetime.now().isoformat(timespec="seconds")
    count = 0
    for t in triples:
        if len(t) != 5:
            continue
        sub, st, pred, obj, ot = t
        # 去重：相同主体+谓词+客体不重复存
        dup = db.conn.execute(
            "SELECT id FROM triples WHERE user_id=? AND subject=? AND predicate=? AND object=?",
            (user_id, sub, pred, obj),
        ).fetchone()
        if dup:
            continue
        db.conn.execute(
            "INSERT INTO triples (user_id, subject, subject_type, predicate, object, object_type, source_msg, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, sub, st, pred, obj, ot, source_msg[:200], now),
        )
        count += 1
    db.conn.commit()
    return count


def query_triples(user_id: str, query: str, top_k: int = _RETRIEVE_TOP_K) -> list[tuple[str, str, str, str, str]]:
    """检索与 query 相关的五元组，返回 (subject, subject_type, predicate, object, object_type) 列表。"""
    rows = db.conn.execute(
        "SELECT id, subject, subject_type, predicate, object, object_type FROM triples WHERE user_id=?",
        (user_id,),
    ).fetchall()
    if not rows:
        return []

    # 构建检索文本：主体+谓词+客体
    docs = [(r["id"], f"{r['subject']} {r['predicate']} {r['object']}") for r in rows]
    query_terms = _tokenize(query)
    tokens = list(set(query_terms + [t for t in re.split(r"[\s,，。！？、]", query) if len(t) > 1]))

    scored = _tfidf_score(tokens, docs)
    id_to_row = {r["id"]: r for r in rows}
    results = []
    seen = set()
    for _, doc_id in scored[:top_k]:
        r = id_to_row.get(doc_id)
        if not r:
            continue
        key = (r["subject"], r["predicate"], r["object"])
        if key not in seen:
            seen.add(key)
            results.append((r["subject"], r["subject_type"], r["predicate"], r["object"], r["object_type"]))
    return results


def format_triples(triples: list[tuple[str, str, str, str, str]]) -> str:
    """格式化为注入文本。"""
    if not triples:
        return ""
    lines = []
    for s, st, p, o, ot in triples:
        lines.append(f"{s}({st}) —[{p}]→ {o}({ot})")
    return "你记得的这些关于对方的事实：\n" + "\n".join(lines)
