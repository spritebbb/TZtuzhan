"""对话流水线：收文本 → 好感度 → 称呼提取 → 记忆检索 → 拼 prompt → LLM → 存档 → 回复。

被 QQ 插件（plugins/private_chat）和本地调试（debug_cli / smoke_test）共用，
保证各处行为一致。
"""
import re
from datetime import datetime, timedelta

from . import affection
from .llm import chat, extract_address
from .log import logger
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


# 告别场景：用户说了这些，菟菚只需一句简短道别，不复读、不刷屏
_FAREWELL_RE = re.compile(r"(晚安|再见|拜拜|明天见|睡啦|睡了|先睡了|我睡了|告辞|886|睡了睡了)")
_FAREWELL_REPLY = {
    "晚安": "晚安🌙",
    "再见": "再见呀",
    "拜拜": "拜拜",
    "明天见": "明天见",
}


def trim_farewell(user_text: str, reply: str) -> str:
    """告别语境兜底：若用户消息是道别词，把回复精简成一句道别，避免刷屏/复读。"""
    m = _FAREWELL_RE.search(user_text)
    if not m:
        return reply
    word = m.group(1)
    # 若回复已经是一句简明道别（不长、无追问），保留
    lines = [l for l in reply.splitlines() if l.strip() and not l.startswith("【")]
    compact = " ".join(lines).strip()
    # 道别答复：来自词表，或回复很短含道别词
    if compact in _FAREWELL_REPLY.values():
        return compact
    if compact and len(compact) <= 8 and any(k in compact for k in ("晚安", "再见", "拜拜", "明天见", "睡")):
        # 已经是简短道别，保留原样
        return compact
    # 否则收敛成一句道别（避免复读对方的词 + 多条刷屏）
    return _FAREWELL_REPLY.get(word, f"{word}")


async def process(user_id: str, text: str, *, mock: bool = False, merged_msg: bool = False) -> str:
    """处理一条用户消息，返回菟菚的回复。

    merged_msg=True 表示 text 是用户连续发送的多条消息合并成的一段话，
    提示模型把这段当成对方一次性的完整表达，用一句精简的话回应整体，不逐条复读。
    """
    user = db.ensure_user(user_id)
    first_chat = not user["first_chat_done"]

    # 1) 好感度即时规则（含跨天回滚）
    await affection.on_message(user_id, text)

    # 1.1) v2 正向互动即时奖励（每日各上限 1 次；不阻塞、失败静默）
    try:
        # 用称呼交流
        if affection.check_nickname_used(text, user["nickname_pref"]):
            affection.try_daily_bonus(user_id, "nickname", affection.NICKNAME_BONUS, "用菟菚的称呼交流")
        # 关心菟菚
        if affection.check_care(text):
            affection.try_daily_bonus(user_id, "care", affection.CARE_BONUS, "关心菟菚")
        # 引用过去记忆（用户提到上次/之前/记得…，说明在引用共同经历）
        from .memory import looks_like_recall

        if looks_like_recall(text):
            affection.try_daily_bonus(user_id, "memory", affection.MEMORY_REFERENCE_BONUS, "提到共同经历/回忆")
        # 回应菟菚的主动消息（主动发过且 3 小时内回复）
        try:
            import datetime
            from .userdb import kv_get

            last_ts_str = kv_get(user_id, "last_proactive_ts")
            if last_ts_str:
                last_ts = datetime.datetime.fromisoformat(last_ts_str)
                if datetime.datetime.now() - last_ts < datetime.timedelta(hours=3):
                    affection.try_daily_bonus(user_id, "proactive_resp", affection.PROACTIVE_RESPONSE_BONUS, "回应菟菚的主动消息")
        except Exception:
            pass
    except Exception:
        logger.exception("[pipeline] 好感度即时奖励失败")

    # 1.5) 惰性事实提炼（按消息批量 + 会话长时间没说话后补提尾部）→ 后台执行，
    # 不阻塞本轮回复；失败只记日志（见 tasks.schedule 的 _runner）
    try:
        from .daily import extract_facts  # 延迟导入避免循环
        from .tasks import schedule

        unseen = db.max_message_id(user_id) - db.get_last_fact_msg_id(user_id)
        if unseen >= 10:
            schedule(f"facts:{user_id}", lambda: extract_facts(user_id))
        elif unseen >= _IDLE_MIN_NEW and _long_gap(db.last_message_ts(user_id)):
            schedule(f"facts:{user_id}", lambda: extract_facts(user_id))
    except Exception:
        logger.exception("[pipeline] 惰性事实提炼调度失败")

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

    # 3) 记忆与上下文（语义检索在疑似回忆时才扩展，内部已做失败退化）
    try:
        remembered = await recall(user_id, text, mock=mock)
        facts = await recall_facts(user_id, text, mock=mock)
    except Exception:
        logger.exception("[pipeline] 记忆检索失败，按无记忆继续")
        remembered, facts = [], []

    # 3.1) 长会话压缩：总消息超阈值时，把旧消息摘要成一段记忆，只保留最近的完整消息
    ctx = short_term_messages(user_id)
    compact_summary = None
    try:
        from .memory import compact_context

        compacted = await compact_context(user_id, mock=mock)
        if compacted is not None:
            compact_summary, ctx = compacted
    except Exception:
        logger.exception("[pipeline] 长会话压缩失败，保持原上下文")

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
        affection=user["affection"],
        user_id=user_id,
    )
    messages = [{"role": "system", "content": system}]

    # 4.0.5) 网络热梗：让菟菚熟知近期热梗，能在对话里自然使用
    try:
        from .memes import get_current_memes, has_memes, schedule_refresh

        schedule_refresh()  # 缓存过期则后台刷新（同 key 去重）
        current_memes = get_current_memes()
    except Exception:
        logger.exception("[pipeline] 热梗读取失败")
        current_memes = []
    if current_memes:
        lines = "\n".join(
            f"- {m['term']}：{m['meaning']}（例：{m['example']}）" for m in current_memes
        )
        messages.append(
            {
                "role": "system",
                "content": (
                    "你最近了解的这些网络热梗（供你在合适的时机自然使用）：\n"
                    + lines
                    + "\n要真正理解它们的含义和语境再用，别生硬堆砌；"
                    "只在对方的话或话题让你觉得合适时，自然地用上一两个，"
                    "营造『你也是网上冲浪的人』的同频感；用得不顺就别用，别为玩梗而玩梗。"
                ),
            }
        )

    # 4.0) 日常对话里的特殊日子识别：用户这句若在告知/约定某个日子，自动记住
    try:
        from .date_memory import extract_from_message
        from .userdb import get_today_important_dates

        newly_saved = await extract_from_message(user_id, text, mock=mock)
    except Exception:
        logger.exception("[pipeline] 特殊日子识别失败")
        newly_saved = []

    # 4.1) 情感记忆：今天有没有特殊日子（生日/纪念日等）
    try:
        today_dates = get_today_important_dates(user_id)
    except Exception:
        logger.exception("[pipeline] 特殊日子查询失败")
        today_dates = []
    if today_dates:
        labels = "、".join(d["label"] for d in today_dates)
        messages.append(
            {
                "role": "system",
                "content": (
                    f"今天是特殊的日子：{labels}。你心里记着，如果话题合适就自然带一句祝福/提起，"
                    "别刻意、别突然转移话题；如果对方在聊别的，就顺着聊，不用硬提。"
                ),
            }
        )

    if compact_summary:
        messages.append(
            {
                "role": "system",
                "content": (
                    "以下是你们之前聊过的一段更早的对话的摘要（作为长期背景，自然融入，不用复述）：\n"
                    + compact_summary
                ),
            }
        )

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

    # 不让 LLM 仿冒 QQ 表情标记：它常从历史消息里学 [face:N] 写出未定义的表情，
    # 这些 NapCat 大多不支持会导致发送失败。明确的指令比事后过滤更干净。
    messages.append(
        {
            "role": "system",
            "content": (
                "重要：不要输出任何 `[face:数字]` 这类 QQ 表情标记或方括号格式，"
                "也不要使用[表情]表情包等方括号填充词。想表达情绪就自然说出口，"
                "或用文字描述（如「我笑了」「噗」），只写正常的中文文字。"
            ),
        }
    )

    # 对方连发多条合并成一段话 → 提示整体理解，只回一句精简的话
    if merged_msg:
        messages.append(
            {
                "role": "system",
                "content": (
                    "对方刚才连着发了好几条，已合并成上面一段话（用换行分隔）。"
                    "请把它当成对方一次性说的一段完整的话，抓住其中真正想表达的核心，"
                    "**用一句精简的话回应整体的意思**，不要逐条复读、不要对应每一条分别回应，"
                    "保持慵懒自然、说重点。"
                ),
            }
        )

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
                "【回复】你实际发给对方的话（保持你的风格：短句、慵懒温柔、像发消息一截一截）。\n"
                "条数完全看内容：接得住就一句，需要铺开就两句三句，别为了凑数或开头就固定成几段。\n"
                "特别地，要会看语境判断「该不该继续说」：\n"
                "- 对方说晚安/再见/结束话题/要睡觉去 → 你已经道过别或话已说到位，就**简短收尾，1 条最多**（如『晚安』『明天见』），"
                "别接着发多条、别找新话题、别追问；对方已经说了『明天见』，你就别再重复一遍『明天见』。\n"
                "- 对方的话你已经接住了、没有可延续的 → 回一句就够，不要为了显得热情而硬凑第二句。\n"
                "- 真正值得展开的话题（对方在倾诉、问问题、抛梗、求安慰）→ 才多说几句。\n"
                "另外，当你聊到或想到某个**具体的画面/景象**（眼前的花田、窗外的雨、桌上的猫、夕阳、星空…）时，"
                "可以用一两句话把这个画面描述得生动、鲜活一点，然后自然地问对方『要不要看看』『想不想看』——"
                "像是在分享你眼前的美好。但只在真的合适、你能自然地想到画面时才这样，别为了触发而硬编画面。\n"
                "两段都要写，【回复】才是对方会看到的。"
            ),
        }
    )
    raw = await chat(messages, mock=mock)
    reply = strip_actions(_extract_reply(raw))
    reply = trim_farewell(text, reply)

    # 6) 存档
    db.add_message(user_id, "user", text)
    db.add_message(user_id, "assistant", reply)
    lm1_id = db.add_long_memory(user_id, f"用户说：{text}")
    lm2_id = db.add_long_memory(user_id, f"菟菚说：{reply}")
    db.set_first_chat_done(user_id)

    # 6.1) 给新长期记忆建稠密向量索引（失败静默，不影响回复）
    try:
        from .vector_store import index as vec_index

        vec_index(user_id, lm1_id, f"用户说：{text}")
        vec_index(user_id, lm2_id, f"菟菚说：{reply}")
    except Exception:
        pass
    return reply
