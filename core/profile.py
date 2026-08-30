"""用户画像系统：把「关于你的信息」结构化记下来，菟菚越来越懂你。

借鉴 Maibot 的 person_info（"永远都在更加了解你"）思想，但简化适配单用户：
- 分类画像：basic（基本信息）/ likes（喜好）/ dislikes（厌恶）/
  habits（习惯）/ personality（性格特征）/ other
- LLM 定期从对话提炼，写入 user_profile 表（带去重）
- 画像描述注入 system prompt，让菟菚自然引用（"你喜欢的…""我记得你不爱…"）
- `/画像` 命令可查看菟菚对你了解的全貌

与 facts 的关系：facts 是"具体事实流水"，profile 把事实归纳成结构化的
分类画像，注入时更清晰、更有"懂你"的感觉。
"""
from __future__ import annotations

from .log import logger
from .userdb import db

# 分类显示名
_CATEGORY_LABELS = {
    "basic": "基本信息",
    "likes": "喜好",
    "dislikes": "厌恶",
    "habits": "习惯",
    "personality": "性格",
    "other": "其他",
}

_PROFILE_PROMPT = """你是记忆整理员。根据下面的对话，把关于**用户**的长期信息整理成结构化的画像，只输出一个 JSON。

分类与规则：
- basic：基本信息——年龄/职业/城市/家庭/身份等客观信息（如「用户是程序开发」「用户住在襄阳」）
- likes：喜好——用户喜欢的东西、爱好、爱吃的、爱玩的（如「用户喜欢下雨天」「用户爱听民谣」）
- dislikes：厌恶——用户讨厌/不喜欢的（如「用户讨厌吃香菜」「用户不喜欢被催」）
- habits：习惯——作息、日常行为习惯（如「用户习惯熬夜到两点」「用户每天通勤坐地铁」）
- personality：性格——行为风格/性格特征（如「用户性格偏内向」「用户说话直接干脆」）
- other：不属于以上分类但值得长期记住的

规则：
1. 只提炼**长期稳定**的信息，别把一次性话题记进去（如"今天吃了饺子"不算习惯，除非反复出现）
2. 每条短句，以「用户」开头，不超过 20 字
3. 不确定的信息不要编造；没有该分类的信息就省略该键
4. 只输出 JSON：{"basic": [...], "likes": [...], "dislikes": [...], "habits": [...], "personality": [...], "other": [...]}
没有值得记录的画像就输出 {"basic": [], "likes": [], "dislikes": [], "habits": [], "personality": [], "other": []}
"""


def _parse_json(resp: str) -> dict:
    import json

    text = resp.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def profile_prompt_text(user_id: str, max_items: int = 15) -> str:
    """构建注入 system prompt 的画像描述文本；无画像返回空串。

    max_items 限制注入条数，防止画像积累过多把 system prompt 撑爆。
    """
    rows = db.get_profile(user_id)
    if not rows:
        return ""
    # 按分类分组（每类限 max_items/6 条左右，总量不超过 max_items）
    per_cat = max(1, max_items // 6)
    groups: dict[str, list[str]] = {}
    for r in rows:
        groups.setdefault(r["category"], []).append(r["content"])
    lines = []
    for cat in ("basic", "likes", "dislikes", "habits", "personality", "other"):
        items = groups.get(cat)
        if not items:
            continue
        label = _CATEGORY_LABELS.get(cat, cat)
        lines.append(f"{label}：" + "；".join(items[:per_cat]))
    return "你记得的关于对方的事：\n" + "\n".join(lines)


def profile_text(user_id: str) -> str:
    """构建人类可读的画像文本（/画像 命令用）。"""
    rows = db.get_profile(user_id)
    if not rows:
        return "（菟菚还没记下关于你的画像，多聊聊她就更懂你了）"
    groups: dict[str, list[str]] = {}
    for r in rows:
        groups.setdefault(r["category"], []).append(r["content"])
    lines = []
    for cat in ("basic", "likes", "dislikes", "habits", "personality", "other"):
        items = groups.get(cat)
        if not items:
            continue
        label = _CATEGORY_LABELS.get(cat, cat)
        lines.append(f"· {label}：" + "；".join(items))
    return "菟菚心里的你：\n" + "\n".join(lines)


async def extract_profile(user_id: str, day=None, *, rows=None, done=0) -> bool:
    """从一段对话提炼用户画像写入 user_profile 表。

    参数：
    - day 非空：提炼该日全部对话（每日模式）；
    - day 为空且未传 rows：提炼 last_profile_msg_id 之后的新消息（惰性模式）；
    - rows/done 由外部传入时（画像+口头禅同批提炼），直接用给定消息，不再自取。

    返回是否成功。失败静默（不阻塞对话）。
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
                {"role": "system", "content": _PROFILE_PROMPT},
                {"role": "user", "content": f"对话记录：\n{transcript}"},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        data = _parse_json(resp)
    except Exception:
        # 失败不推进游标：保留这批消息，下次提炼仍能重试（避免永久丢数据）
        logger.exception("[画像] {} 提炼失败（不推进游标，稍后重试）", user_id)
        return False

    if not isinstance(data, dict):
        logger.warning("[画像] {} 提炼返回格式异常（不推进游标）", user_id)
        return False

    added = 0
    for cat in ("basic", "likes", "dislikes", "habits", "personality", "other"):
        items = data.get(cat)
        if not isinstance(items, list):
            continue
        for item in items:
            # LLM 偶发输出 dict/list 而非字符串：直接跳过，避免 str() 存入垃圾文本
            if not isinstance(item, str):
                continue
            text = item.strip()[:80]
            if not text:
                continue
            if db.add_profile(user_id, cat, text, "llm") is not None:
                added += 1
    db.set_last_profile_msg_id(user_id, done)
    if added:
        logger.info("[画像] {} 新增 {} 条画像", user_id, added)
    return True
