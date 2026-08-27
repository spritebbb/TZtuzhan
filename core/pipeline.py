"""对话流水线：收文本 → 好感度 → 称呼提取 → 记忆检索 → 拼 prompt → LLM → 存档 → 回复。

被 QQ 插件（plugins/private_chat）和本地调试（debug_cli / smoke_test）共用，
保证各处行为一致。
"""
import re

from . import affection
from .llm import chat
from .memory import recall, short_term_messages
from .persona import build_system_prompt
from .userdb import db

# 称呼提取：用户回复「叫我哥哥」这类短句时记录（第一次对话的称呼确认）
ADDRESS_RE = re.compile(r"(?:叫我|喊我|称呼我|你可以叫我|你叫我)[:：]?\s*(\S{1,12})")


async def process(user_id: str, text: str, *, mock: bool = False) -> str:
    """处理一条用户消息，返回菟菚的回复。"""
    user = db.ensure_user(user_id)
    first_chat = not user["first_chat_done"]

    # 1) 好感度即时规则（含跨天回滚）
    affection.on_message(user_id, text)

    # 2) 称呼提取（仅尚无偏好时）
    pref = user["nickname_pref"]
    if not pref:
        m = ADDRESS_RE.search(text)
        if m:
            db.set_nickname(user_id, m.group(1))
            pref = m.group(1)

    # 3) 记忆与上下文
    remembered = recall(user_id, text)
    ctx = short_term_messages(user_id)

    # 4) 组装 prompt
    system = build_system_prompt(
        stage=affection.stage_of(user["affection"]),
        address=pref,
        lover_confirm=bool(user["lover_confirm"]),
        first_chat=first_chat,
    )
    messages = [{"role": "system", "content": system}]
    if remembered:
        messages.append(
            {
                "role": "system",
                "content": "你记得这些过去的事（作为参考，自然融入）：\n"
                + "\n".join(f"- {t}" for t in remembered),
            }
        )
    messages.extend(ctx)
    messages.append({"role": "user", "content": text})

    # 5) 调用 LLM
    reply = await chat(messages, mock=mock)

    # 6) 存档
    db.add_message(user_id, "user", text)
    db.add_message(user_id, "assistant", reply)
    db.add_long_memory(user_id, f"用户说：{text}")
    db.add_long_memory(user_id, f"菟菚说：{reply}")
    db.set_first_chat_done(user_id)
    return reply
