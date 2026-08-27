"""对话流水线：收文本 → 好感度 → 称呼提取 → 记忆检索 → 拼 prompt → LLM → 存档 → 回复。

被 QQ 插件（plugins/private_chat）和本地调试（debug_cli / smoke_test）共用，
保证各处行为一致。
"""
import re
from datetime import datetime, timedelta

from . import affection
from .llm import chat, extract_address
from .memory import recall, recall_facts, short_term_messages
from .persona import build_system_prompt
from .search import web_search
from .userdb import db

# 会话空闲判定：离上一条消息超过该分钟数，视为上一场聊完，补提尾部事实
_IDLE_SESSION_MINUTES = 30
_IDLE_MIN_NEW = 4


def _long_gap(ts: str | None) -> bool:
    """判断某时间戳是否距现在超过空闲阈值。"""
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (datetime.now() - t).total_seconds() >= _IDLE_SESSION_MINUTES * 60


_ADDRESS_ASK_WORDS = ("称呼你", "怎么称", "怎么叫", "叫你什么", "想让你怎么称呼", "叫你", "叫法")


def _asked_address(last_assistant: str | None) -> bool:
    """判断菟菚上一句是否在问称呼（用于捕捉用户直接报名字的情况）。"""
    return bool(last_assistant) and any(w in last_assistant for w in _ADDRESS_ASK_WORDS)


_SEARCH_KEYS = ("搜索", "搜一下", "查一下", "帮我查", "查查", "新闻", "天气", "多少钱", "价格", "汇率", "现在几点", "最新", "今天有", "今天有没有")


def _needs_search(text: str) -> bool:
    """是否命中需要联网搜索的内容。"""
    return any(k in text for k in _SEARCH_KEYS)

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


def _extract_reply(text: str) -> str:
    """从「先思考后发言」的输出里提取【回复】段；无标记则整段当回复。"""
    m = re.search(r"【回复】\s*(.*)", text, re.S)
    return m.group(1).strip() if m else text.strip()


_PAREN_RE = re.compile(r"（[^）]*）|\([^)]*\)")


def strip_actions(text: str) -> str:
    """移除模型输出里的任何括号旁白（动作/语气/屏幕提示），只留台词。"""
    return _PAREN_RE.sub("", text).strip()


async def process(user_id: str, text: str, *, mock: bool = False) -> str:
    """处理一条用户消息，返回菟菚的回复。"""
    user = db.ensure_user(user_id)
    first_chat = not user["first_chat_done"]

    # 1) 好感度即时规则（含跨天回滚）
    await affection.on_message(user_id, text)

    # 1.5) 惰性事实提炼（按消息批量 + 会话长时间没说话后补提尾部）
    try:
        from .daily import extract_facts  # 延迟导入避免循环

        unseen = db.max_message_id(user_id) - db.get_last_fact_msg_id(user_id)
        if unseen >= 10:
            await extract_facts(user_id)
        elif unseen >= _IDLE_MIN_NEW and _long_gap(db.last_message_ts(user_id)):
            await extract_facts(user_id)
    except Exception:
        pass

    # 2) 称呼与过分称呼处理（无论是否已设称呼，过分称呼都要检测并扣分）
    pref = user["nickname_pref"]
    bad_address = None
    address_intent = ADDRESS_RE.search(text) is not None
    candidate = None
    if not pref:
        if mock:
            m = ADDRESS_RE.search(text)
            candidate = clean_address(m.group(1)) if m else None
        elif address_intent or _asked_address(db.last_assistant_message(user_id)):
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
    facts = recall_facts(user_id, text)
    ctx = short_term_messages(user_id)

    # 3.5) 联网搜索（命中需要搜索的关键词时）
    search_hits = []
    if not mock and _needs_search(text):
        search_hits = web_search(text)

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
    if facts:
        messages.append(
            {
                "role": "system",
                "content": "你记住的关于对方的事（自然融入，不要复述）：\n"
                + "\n".join(f"- {f}" for f in facts),
            }
        )

    # 逐渐学习对方说话风格（由每日/定期提炼，注入供自然模仿）
    style = db.get_style(user_id)
    if style:
        messages.append(
            {
                "role": "system",
                "content": (
                    f"你逐渐观察到的对方的说话风格：{style}\n"
                    "自然地模仿对方的说话习惯（短句/语气词/表情节奏），但别生硬、别学得过头，保持你自己的慵懒温柔。"
                ),
            }
        )
    if search_hits:
        snippets = "\n".join(f"- {h['title']}：{h['snippet']}" for h in search_hits[:5])
        messages.append(
            {
                "role": "system",
                "content": (
                    "你刚刚随手查了一下，看到这些信息（可能有误）：\n"
                    + snippets
                    + "\n把它们揉进你温柔、慵懒的语气里回答，像你刚好知道、随口告诉对方；"
                    "不要生搬硬套、不要列成清单、不要说「根据搜索」「据我所知」这类报告腔。"
                ),
            }
        )
    messages.extend(ctx)
    messages.append({"role": "user", "content": text})

    # 对方回得很短 → 提示模型别让话题冷场（借一句接住）
    if len(text) <= 4:
        messages.append(
            {
                "role": "system",
                "content": (
                    "对方这轮回得很短，话题有点冷场了。别让对话就这么结束——"
                    "自然接一句：追问个小问题、抛个新话题、或轻轻调侃一下，保持慵懒但别冷场。"
                    "（就一句，别啰嗦）"
                ),
            }
        )

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
    if stage == "初识":
        messages.append(
            {
                "role": "system",
                "content": (
                    "你们现在是刚认识的阶段，态度要冷淡疏远：回复尽量简短客气、保持距离、"
                    "不主动热络、不撩、不说甜话；可以少一些热情的接话和反问，对方再热情也别被带偏。"
                ),
            }
        )
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

    # 5) 先思考再说话：让模型输出【思考】+【回复】，只把【回复】发给对方
    messages.append(
        {
            "role": "system",
            "content": (
                "回复前先在心里想一想，感受对方这句话背后的情绪和意图，掂量怎么接最自然、分寸怎么拿捏。"
                "然后输出两段：\n"
                "【思考】你内心真实的想法（用你自己的语气，不发给对方，不用客套）\n"
                "【回复】你实际发给对方的话（保持你的风格：短句、慵懒温柔、像发消息一截一截，但一次回复最多两三截）\n"
                "两段都要写，【回复】才是对方会看到的。"
            ),
        }
    )
    raw = await chat(messages, mock=mock)
    reply = strip_actions(_extract_reply(raw))

    # 6) 存档
    db.add_message(user_id, "user", text)
    db.add_message(user_id, "assistant", reply)
    db.add_long_memory(user_id, f"用户说：{text}")
    db.add_long_memory(user_id, f"菟菚说：{reply}")
    db.set_first_chat_done(user_id)
    return reply
