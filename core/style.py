"""场景化表达风格：把用户的「场景→表达方式」结构化记下来，菟菚在对应场景自然贴合。

借鉴 Maibot expression_learner 的「情境→风格」对思想，但更轻量：
- 不搞向量索引，直接用 LLM 从对话提炼「场景→表达方式」对
- 同批提炼（与画像/口头禅共用游标）
- 注入时按场景归类，让菟菚在对应场景自然贴合用户的表达习惯

与现有 style_profile 的关系：style_profile 是整体风格描述，
style_map 是细粒度的场景化风格，两者互补。
"""
from __future__ import annotations

from .log import logger
from .userdb import db

_STYLE_PROMPT = """你是表达风格分析师。从下面的对话中，分析**用户**在不同场景下的表达方式，输出一个 JSON。

每一个条目是一条「场景→表达方式」的对，格式：
{"styles": [{"situation": "场景描述", "style": "用户的表达方式"}]}

规则：
- situation：场景描述，不超过 15 字（如「对方倾诉烦恼时」「对方开玩笑时」「对方聊工作烦恼时」「对方聊日常琐事时」）
- style：该场景下用户的表达方式，不超过 20 字（如「喜欢用短句+省略号」「爱用语气词+表情」「说话直接不含糊」「喜欢用反问和调侃」）
- 从对话中判断，不编造
- 最多输出 5 条
- 没有明显风格特征就输出 {"styles": []}
"""


def style_map_prompt_text(user_id: str) -> str:
    """构建注入 system prompt 的场景化风格描述；无则返回空串。"""
    rows = db.get_style_map(user_id, 10)
    if not rows:
        return ""
    lines = []
    for r in rows:
        lines.append(f"· 当{r['situation']}：{r['style']}")
    return "你观察到对方在不同场景的表达方式：\n" + "\n".join(lines)


async def extract_style_map(user_id: str, *, rows=None, done=0) -> bool:
    """LLM 从对话提炼场景化表达风格，写入 user_style_map。

    参数同 extract_profile：rows/done 由外部传入时同批提炼。
    """
    from .llm import chat

    if rows is None:
        last_id = db.get_last_profile_msg_id(user_id)
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
                {"role": "system", "content": _STYLE_PROMPT},
                {"role": "user", "content": f"对话记录：\n{transcript}"},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        import json

        text = resp.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
    except Exception:
        logger.exception("[风格] {} 提炼失败", user_id)
        db.set_last_profile_msg_id(user_id, done)
        return False

    if not isinstance(data, dict):
        db.set_last_profile_msg_id(user_id, done)
        return False
    for item in data.get("styles") or []:
        if not isinstance(item, dict):
            continue
        s = str(item.get("situation", "")).strip()[:40]
        st = str(item.get("style", "")).strip()[:60]
        if s and st:
            db.add_style_map(user_id, s, st)
    db.set_last_profile_msg_id(user_id, done)
    return True


def style_map_text(user_id: str) -> str:
    """人类可读的 /风格 文本。"""
    rows = db.get_style_map(user_id, 20)
    if not rows:
        return "（菟菚还没注意到你在不同场景的表达方式，多聊聊她就知道了）"
    lines = []
    for r in rows:
        lines.append(f"· 当{r['situation']}：{r['style']}（观察到{r['count']}次）")
    return "菟菚观察到的你的表达方式：\n" + "\n".join(lines)