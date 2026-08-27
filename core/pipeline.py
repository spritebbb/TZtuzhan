"""对话流水线：收文本 → 好感度 → 称呼提取 → 记忆检索 → 拼 prompt → LLM → 存档 → 回复。

被 QQ 插件（plugins/private_chat）和本地调试（debug_cli / smoke_test）共用，
保证各处行为一致。
"""
import re

from . import affection
from .llm import chat, extract_address
from .memory import recall, short_term_messages
from .persona import build_system_prompt
from .userdb import db

# 称呼意图检测：判断「这句是否在设置称呼」（正则无法精确取名，只做判断 + mock 兜底）
ADDRESS_RE = re.compile(
    r"(?:你可以叫我|可以叫我|以后叫我|以后就叫我|以后都叫我|叫我一声|叫我|喊我|称呼我|你叫我)[:：]?\s*"
    r"[「『\"'“”《〈]*([^吧呀嘛啊呢哦啦呗哈咯～~。，,、!！?？…\s]{1,8})"
)
_TRAIL_CHARS = "吧呀嘛啊呢哦啦呗哈咯～~。，,、!！?？…"


def clean_address(name: str) -> str:
    """清理称呼：去掉引号包裹与尾部语气词，如「以实玛利吧」→「以实玛利」。"""
    name = name.strip(" \t「」『』\"'“”《〈》〉")
    return name.rstrip(_TRAIL_CHARS)


async def process(user_id: str, text: str, *, mock: bool = False) -> str:
    """处理一条用户消息，返回菟菚的回复。"""
    user = db.ensure_user(user_id)
    first_chat = not user["first_chat_done"]

    # 1) 好感度即时规则（含跨天回滚）
    affection.on_message(user_id, text)

    # 2) 称呼与过分称呼处理（无论是否已设称呼，过分称呼都要检测并扣分）
    pref = user["nickname_pref"]
    bad_address = None
    address_intent = ADDRESS_RE.search(text) is not None
    candidate = None
    if not pref:
        if mock:
            m = ADDRESS_RE.search(text)
            candidate = clean_address(m.group(1)) if m else None
        elif address_intent or len(text) <= 12:
            candidate = await extract_address(text)
    elif address_intent:
        # 已设称呼：仅在用户主动设置/更改称呼时检测（过分称呼同样扣分）
        if mock:
            m = ADDRESS_RE.search(text)
            candidate = clean_address(m.group(1)) if m else None
        else:
            candidate = await extract_address(text)
    if candidate:
        if affection.check_bad_address(candidate):
            db.update_affection(user_id, affection.BAD_ADDRESS_PENALTY, "要求不合适的称呼")
            bad_address = candidate
        else:
            db.set_nickname(user_id, candidate)
            pref = candidate

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

    # 拒绝不合适的称呼：给模型注入符合菟菚性格的坚定拒绝指令
    if bad_address:
        messages.append(
            {
                "role": "system",
                "content": (
                    f"用户刚才想让你用「{bad_address}」这种称呼，这让你很不舒服。"
                    "请温柔但坚定地拒绝：保持轻声细语、慵懒的性格，不慌不忙，"
                    "不要发火也不要妥协；可以带一点点病娇的占有欲，"
                    "比如表示这个称呼让你不喜欢；然后让他换个正常的称呼。"
                ),
            }
        )

    # 过早表白/求婚（初识/熟悉阶段）：当成变态，温柔拒绝 + 扣好感度
    stage = affection.stage_of(user["affection"])
    if stage in ("初识", "熟悉") and affection.check_early_confession(text):
        db.update_affection(user_id, affection.EARLY_CONFESSION_PENALTY, "过早表白/求婚")
        messages.append(
            {
                "role": "system",
                "content": (
                    "对方刚认识就这样表白、求婚，让你觉得太急切、像变态。"
                    "请温柔但明确地拒绝，保持距离感，符合你轻声细语、慵懒的性格；"
                    "不要答应，也不要发火；可以委婉提醒他你们还没那么熟。"
                ),
            }
        )

    # 5) 调用 LLM
    reply = await chat(messages, mock=mock)

    # 6) 存档
    db.add_message(user_id, "user", text)
    db.add_message(user_id, "assistant", reply)
    db.add_long_memory(user_id, f"用户说：{text}")
    db.add_long_memory(user_id, f"菟菚说：{reply}")
    db.set_first_chat_done(user_id)
    return reply
