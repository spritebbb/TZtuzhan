"""黑话/口头禅学习：记住用户的高频口头禅与黑话，菟菚对话中自然使用。

借鉴 Maibot 的 jargon_learner（黑话挖掘 + 含义推测 + 对话注入），简化适配单用户：
- 即时捕获：从用户每条消息里正则提取高频口头禅（如「啊这」「绝了」「emm」）
- LLM 提炼：批量对话里提炼黑话/网络词并给出含义
- 注入：把高频口头禅/黑话词给菟菚，自然使用营造同频感
"""
from __future__ import annotations

import re

from .log import logger
from .userdb import db

# 常见口头禅候选（正则捕获）：语气词/网络用语/短句
_CATCHPHRASE_RE = re.compile(
    r"(啊这|绝了|笑死|麻了|破防|绷不住了|泪目|离谱|真行|我焯|好家伙|"
    r"emm|emmm|嗯嗯|哈哈|hhhh|草|离谱他妈|6|蚌埠住了|乐了|寄了|摆了|"
    r"歪歪滴艾斯|栓q|瑞思拜|真香|老铁|集美|姐妹|干饭人|冲鸭|无语子|"
    r"芭比q了|家人们|懂的都懂|细说|展开说说)"
)

_TERM_PROMPT = """你是语言观察员。从下面的对话中提取**用户**经常用的口头禅和黑话，只输出一个 JSON。

口头禅：用户反复出现的口头语/语气词/口头禅（如「啊这」「绝了」「笑死」「emm」）
黑话：网络流行词、缩写、圈内黑话（如「yyds」「破防」「内卷」），需要给出含义

规则：
1. 只提取**用户**说过的话里的词（别把菟菚的回复算进去）
2. 口头禅要真实出现且高频（≥2 次优先），不要提取普通措辞
3. 黑话要给出简短的 meaning（10 字内）
4. 只输出 JSON：{"catchphrases": ["啊这", "绝了"], "slangs": [{"term": "yyds", "meaning": "永远的神"}]}
没有就输出 {"catchphrases": [], "slangs": []}
"""


def capture_from_message(text: str) -> list[str]:
    """从单条用户消息里即时捕获高频口头禅（正则快筛，后台累计）。

    返回新识别出的口头禅词。失败静默。
    """
    hits = _CATCHPHRASE_RE.findall(text)
    return list(dict.fromkeys(hits))  # 去重保序


def note_message(user_id: str, text: str) -> None:
    """记录一条用户消息里的口头禅（即时捕获，不阻塞对话）。"""
    try:
        for term in capture_from_message(text):
            db.add_term(user_id, term, "catchphrase")
    except Exception:
        logger.debug("[口头禅] 即时捕获失败")


def terms_prompt_text(user_id: str, max_items: int = 8) -> str:
    """构建注入 system prompt 的口头禅/黑话描述；无则返回空串。"""
    terms = db.get_terms(user_id, max_items)
    if not terms:
        return ""
    parts = []
    for t in terms:
        if t["category"] == "slang" and t["meaning"]:
            parts.append(f"{t['term']}（{t['meaning']}）")
        else:
            parts.append(t["term"])
    return "你注意到对方爱用的词：" + "、".join(parts)


async def extract_terms(user_id: str, day=None, *, rows=None, done=0) -> bool:
    """LLM 批量提炼用户口头禅/黑话。

    rows/done 由外部传入时（画像+口头禅同批提炼），直接用给定消息；
    否则自取 last_profile_msg_id 之后的新消息（与画像共用游标）。

    返回是否成功。失败静默。
    """
    from .llm import chat

    if rows is None:
        last_id = db.get_last_profile_msg_id(user_id)
        if day is not None:
            fetched = db.messages_between(user_id, day, day)
            if not fetched:
                return False
            rows = fetched[-60:]
            done = rows[-1]["id"] if rows else 0
        else:
            fetched = db.messages_after(user_id, last_id, 60)
            if len(fetched) < 8:
                return False
            rows = fetched
            done = rows[-1]["id"]
    if not rows:
        return False
    transcript = "\n".join(f"{r['role']}: {r['content']}" for r in rows)

    try:
        resp = await chat(
            [
                {"role": "system", "content": _TERM_PROMPT},
                {"role": "user", "content": f"对话记录：\n{transcript}"},
            ],
            temperature=0.2,
            max_tokens=300,
        )
        import json

        text = resp.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
    except Exception:
        logger.exception("[口头禅] {} 提炼失败", user_id)
        db.set_last_profile_msg_id(user_id, done)
        return False

    if not isinstance(data, dict):
        db.set_last_profile_msg_id(user_id, done)
        return False

    for term in data.get("catchphrases") or []:
        s = str(term).strip()[:20]
        if s:
            db.add_term(user_id, s, "catchphrase")
    for item in data.get("slangs") or []:
        if not isinstance(item, dict):
            continue
        s = str(item.get("term", "")).strip()[:20]
        if s:
            db.add_term(user_id, s, "slang", str(item.get("meaning", "")).strip()[:30])
    db.set_last_profile_msg_id(user_id, done)
    return True
