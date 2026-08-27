"""私聊主插件：菟菚对话核心（QQ 私聊专用，不处理群消息）。

流程：收消息 → 好感度规则 → 称呼提取 → 记忆检索 → 拼 prompt → LLM → 存档 → 回复
"""
import re

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Message, PrivateMessageEvent

from core import affection
from core.llm import chat
from core.memory import recall, short_term_messages
from core.persona import build_system_prompt
from core.userdb import db

# 称呼提取：用户回复「叫我哥哥」这类短句时记录（第一次对话的称呼确认）
ADDRESS_RE = re.compile(r"(?:叫我|喊我|称呼我|你可以叫我|你叫我)[:：]?\s*(\S{1,12})")

private_msg = on_message(priority=5, block=True)
set_address_cmd = on_command("称呼", priority=4, block=True)


async def _pipeline(user_id: str, text: str) -> str:
    user = db.ensure_user(user_id)
    first_chat = not user["first_chat_done"]

    # 1) 好感度即时规则（含跨天回滚）
    affection.on_message(user_id, text)

    # 2) 称呼提取（仅首次对话后、且尚无偏好时）
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
    reply = await chat(messages)

    # 6) 存档
    db.add_message(user_id, "user", text)
    db.add_message(user_id, "assistant", reply)
    db.add_long_memory(user_id, f"用户说：{text}")
    db.add_long_memory(user_id, f"菟菚说：{reply}")
    db.set_first_chat_done(user_id)
    return reply


@private_msg.handle()
async def handle_private(event: PrivateMessageEvent):
    text = event.get_plaintext().strip()
    if not text:
        await private_msg.finish(Message("……(´･ω･`)"))
    try:
        reply = await _pipeline(str(event.user_id), text)
    except Exception as e:
        reply = f"……藤蔓打结了(´･_･`)\n（{e}）"
    await private_msg.finish(Message(reply))


@set_address_cmd.handle()
async def handle_set_address(event: PrivateMessageEvent):
    text = event.get_plaintext().strip()
    if not text:
        await set_address_cmd.finish(Message("用法：/称呼 哥哥"))
    db.set_nickname(str(event.user_id), text)
    await set_address_cmd.finish(Message(f"好，以后就这么叫你：{text}(￣▽￣)"))
