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

# 话题记忆：跨会话延续上次话题的兜底判定（与 _IDLE_SESSION_MINUTES 一致）
_TOPIC_IDLE_MINUTES = 30


def _long_gap(ts: str | None) -> bool:
    """判断某时间戳是否距现在超过空闲阈值。"""
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (datetime.now() - t).total_seconds() >= _IDLE_SESSION_MINUTES * 60


async def _extract_topic_lazy(user_id: str) -> None:
    """后台惰性提炼话题记忆（失败静默，不阻塞对话）。"""
    try:
        from .topic_memory import extract_topic

        await extract_topic(user_id)
    except Exception:
        pass


async def _extract_triples_lazy(user_id: str) -> None:
    """后台惰性提取结构化事实五元组（失败静默）。"""
    try:
        from .triple_memory import extract_triples, save_triples
        from .userdb import db as _db

        # 提取最近 30 条消息（去重交给 save_triples）
        rows = _db.recent_messages(user_id, 30)
        text = "\n".join(
            f"{'用户' if r['role'] == 'user' else '菟菚'}：{r['content']}"
            for r in rows
        )
        if len(text) < 10:
            return
        triples = await extract_triples(text)
        if triples:
            save_triples(user_id, triples, source_msg=text[:200])
    except Exception:
        pass


_ADDRESS_ASK_WORDS = ("称呼你", "怎么称", "怎么叫", "叫你什么", "想让你怎么称呼", "叫法")


def _asked_address(last_assistant: str | None) -> bool:
    """判断菟菚上一句是否在问称呼（用于捕捉用户直接报名字的情况）。"""
    return bool(last_assistant) and any(w in last_assistant for w in _ADDRESS_ASK_WORDS)


_SEARCH_KEYS = ("搜索", "搜一下", "查一下", "帮我查", "查查", "新闻", "天气", "多少钱", "价格", "汇率", "现在几点", "最新", "今天有", "今天有没有")


def _needs_search(text: str) -> bool:
    """是否命中需要联网搜索的内容。"""
    return any(k in text for k in _SEARCH_KEYS)

# 称呼意图检测：判断「这句是否在设置称呼」（正则精确匹配，避免无关句误触）
# 注意：只用完整意图短语，不用裸「叫我」「你叫我」「喊我」——它们会误配「叫我去吃饭」等无关句。
ADDRESS_RE = re.compile(
    r"(?:你可以叫我|可以叫我|以后叫我|以后就叫我|以后都叫我|叫我一声|称呼我)[:：]?\s*"
    r"[「『\"'“”《〈]*([^吧呀嘛啊呢哦啦呗哈咯～~。，,、!！?？…\s]{1,8})"
)
# 称呼候选词黑名单：含这些词的不是真正要设置的称呼
_ADDRESS_BLACKLIST = ("帮", "给", "去", "来", "拿", "做", "让", "是", "有", "要", "走", "放", "买", "吃", "喝")
_TRAIL_CHARS = "吧呀嘛啊呢哦啦呗哈咯～~。，,、!！?？…"


def clean_address(name: str) -> str:
    """清理称呼：去掉引号包裹与尾部语气词，如「以实玛利吧」→「以实玛利」。"""
    name = name.strip(" \t「」『』\"'“”《〈》〉")
    return name.rstrip(_TRAIL_CHARS)


def _extract_reply(text: str) -> str:
    """从「先思考后发言」的输出里提取回复正文；无标记则裁剪掉思考段。

    LLM 输出可能用不同的括号/标注来分隔思考与实际发言：
      【思考】…【回复】…      〔思考〕…〔回复〕…      思考:…回复:…
    优先找「回复」段（兼容多种写法，取最后一个避免思考段误命中）；
    找不到则把「思考」段及其后的内容裁掉，只留最终要发的部分。
    """
    # 先尝试各类「回复」标注，取最后一个匹配（正文可能跨行）
    for pat in (
        r"【回复】\s*(.*)",
        r"〔回复〕\s*(.*)",
        r"\[回复\]\s*(.*)",
        r"回复[：:]\s*(.*)",
    ):
        m = re.search(pat, text, re.S)
        if m and m.group(1).strip():
            return m.group(1).strip()
    # 没有「回复」标注：如果有「思考」段且其与被标注的正文之间有清晰分隔，
    # 取思考段之后的内容；思考段往往是一整行，正文从下一行开始——
    # 只保留思考段第一行之后的部分，避免把内心思考发给对方（思考泄漏）。
    thought_pat = re.compile(
        r"(?:【思考】|〔思考〕|思考[：:])\s*[^\n]*(?:\n(?P<body>[\s\S]*))?",
    )
    m = thought_pat.search(text)
    if m:
        body = (m.group("body") or "").strip()
        if body:
            return body
        # 思考段后无正文（整句都是思考）→ 保守返回空，由调用方兜底
        return ""
    # 无思考标注 → 整段当回复
    return text.strip()


_PAREN_RE = re.compile(r"（[^）]*）|\([^)]*\)", re.S)


def strip_actions(text: str) -> str:
    """移除模型输出里的任何括号旁白（动作/语气/屏幕提示），只留台词。

    覆盖全角（）/半角()/六角〔〕；全角方头【】作为残留思考标记也一并清理。
    """
    # 若还有思考/回复标记对，先丢弃思考段、保留回复段（应对未经 _extract_reply 的情况）
    for reply_pat in (r"【回复】\s*", r"〔回复〕\s*", r"\[回复\]\s*", r"回复[：:]\s*"):
        m = re.search(reply_pat, text, re.S)
        if m:
            # 取最后一个回复标记之后的内容作为正文
            tail = text[m.end():]
            text = tail
            break
    # 剥掉一个完整思考段（若无回复标记，思考内容跟着正文也不理想，但保留正文优先）
    text = re.sub(r"(?:【思考】|〔思考〕|思考[：:])\s*[^【】〔〕]*", "", text)
    text = re.sub(r"〔[^〕]*〕", "", text)     # 六角旁白/思考残留
    text = re.sub(r"【[^】]*】", "", text)     # 全角方头（思考/标注残留）
    text = _PAREN_RE.sub("", text)             # 圆括号旁白
    return text.strip()


# 告别场景：用户说了这些，菟菚只需一句简短道别，不复读、不刷屏
# 注意：不用裸「睡了」（会误伤「睡不着/睡了吗/还没睡」），只用明确的道别短语
_FAREWELL_RE = re.compile(r"(晚安|再见|拜拜|明天见|睡啦|先睡了|我睡了|我去睡了|睡了睡了|睡觉了|该睡了|告辞|886)")
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


async def _extract_profile_and_terms(user_id: str) -> None:
    """画像 + 口头禅 + 场景风格同批提炼（共用游标，一次取消息、LLM 并行、一次推进游标）。

    各功能按开关独立控制：关掉的就不提炼（省 LLM 调用，也不积累数据）。
    """
    from .features import flag
    from .profile import extract_profile
    from .style import extract_style_map
    from .terms import extract_terms

    tasks = []
    if flag("profile_enabled"):
        tasks.append(extract_profile)
    if flag("terms_enabled"):
        tasks.append(extract_terms)
    if flag("style_enabled"):
        tasks.append(extract_style_map)
    if not tasks:
        return

    # 取一次消息（画像/口头禅/风格共享）
    last_id = db.get_last_profile_msg_id(user_id)
    rows = db.messages_after(user_id, last_id, 60)
    if len(rows) < 8:
        return
    done = rows[-1]["id"]
    import asyncio

    await asyncio.gather(*[fn(user_id, rows=rows, done=done) for fn in tasks])


# 同用户串行锁：pipeline 会写好感度/记忆/消息表，若两条消息并发处理会竞态
# （好感度计数错乱、消息顺序颠倒）。按 user_id 加锁，天然串行。
_user_locks: dict[str, "asyncio.Lock"] = {}


def _user_lock(user_id: str) -> "asyncio.Lock":
    import asyncio

    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


async def process(user_id: str, text: str, *, mock: bool = False, merged_msg: bool = False) -> str:
    """处理一条用户消息，返回菟菚的回复。

    merged_msg=True 表示 text 是用户连续发送的多条消息合并成的一段话，
    提示模型把这段当成对方一次性的完整表达，用一句精简的话回应整体，不逐条复读。
    """
    async with _user_lock(user_id):
        return await _process_locked(user_id, text, mock=mock, merged_msg=merged_msg)


async def _process_locked(user_id: str, text: str, *, mock: bool = False, merged_msg: bool = False) -> str:
    user = db.ensure_user(user_id)
    first_chat = not user["first_chat_done"]

    # 0.5) 口头禅即时捕获（正则快筛，后台累计；不阻塞对话）
    try:
        from .terms import note_message

        note_message(user_id, text)
    except Exception:
        pass

    # 1) 好感度即时规则（含跨天回滚）
    await affection.on_message(user_id, text)
    # 好感度可能已变：刷新快照，后续 system prompt / 阶段判定用最新值
    user = db.get_user(user_id)

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
        # 道歉（修复关系，抵消前扣分）
        if affection.check_apology(text):
            affection.try_daily_bonus(user_id, "apology", affection.APOLOGY_BONUS, "真诚道歉")
        # 分享心事/秘密（走心互动）
        if affection.check_sharing(text):
            affection.try_daily_bonus(user_id, "sharing", affection.SHARING_BONUS, "分享心事/秘密")
        # 夸菟菚
        if affection.check_compliment(text):
            affection.try_daily_bonus(user_id, "compliment", affection.COMPLIMENT_BONUS, "夸菟菚")
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

    # 1.6) 惰性画像 + 口头禅提炼（共用独立游标 last_profile_msg_id，与 facts 并行）
    # → 后台执行，不阻塞回复
    try:
        from .features import flag
        from .tasks import schedule

        if flag("profile_enabled") or flag("terms_enabled") or flag("style_enabled"):
            p_unseen = db.max_message_id(user_id) - db.get_last_profile_msg_id(user_id)
            if p_unseen >= 10:
                schedule(f"profile:{user_id}", lambda: _extract_profile_and_terms(user_id))
            elif p_unseen >= _IDLE_MIN_NEW and _long_gap(db.last_message_ts(user_id)):
                schedule(f"profile:{user_id}", lambda: _extract_profile_and_terms(user_id))
    except Exception:
        logger.exception("[pipeline] 惰性画像提炼调度失败")

    # 1.7) 惰性话题记忆：长时间没聊（新会话开场前）提炼"上次聊到哪"，让菟菚能接着聊
    try:
        from .tasks import schedule

        if _long_gap(db.last_message_ts(user_id)):
            schedule(f"topic:{user_id}", lambda: _extract_topic_lazy(user_id))
    except Exception:
        logger.exception("[pipeline] 惰性话题提炼调度失败")

    # 1.8) 惰性结构化事实提取：跨场（新会话）时从最近消息提取五元组。
    # 只在新会话触发，避免每条消息都打一次 LLM（同 key 去重）
    try:
        from .tasks import schedule as _schedule2

        if _long_gap(db.last_message_ts(user_id)):
            _schedule2(f"triples:{user_id}", lambda: _extract_triples_lazy(user_id))
    except Exception:
        logger.exception("[pipeline] 惰性三元组提取调度失败")

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
            try:
                candidate = await extract_address(text)
            except Exception:
                logger.exception("[pipeline] 称呼提取失败")
                candidate = None
    elif address_intent:
        # 已设称呼：仅在用户主动设置/更改称呼时检测（过分称呼同样扣分）
        if mock:
            m = ADDRESS_RE.search(text)
            candidate = clean_address(m.group(1)) if m else None
        else:
            try:
                candidate = await extract_address(text)
            except Exception:
                logger.exception("[pipeline] 称呼提取失败")
                candidate = None
    if candidate:
        # 黑名单过滤：含动词/功能词的候选不是真正要设置的称呼
        if any(b in candidate for b in _ADDRESS_BLACKLIST):
            candidate = None
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
        import asyncio as _asyncio

        # web_search 是同步 urllib 阻塞 → 放线程池，避免卡事件循环
        search_hits = await _asyncio.to_thread(web_search, text)

    # 4) 组装 prompt
    # 4.0) 意图路由：判断这条消息是闲聊还是需要工具/回忆/情感注入。
    # 闲聊时跳过最大的堆砌源（热梗 + 对对方的了解），只保留 persona + 短上下文，
    # 让回复更自然轻快；需要工具/回忆/情感时仍全量注入（安全优先）。
    intent = None
    try:
        from .intent import classify as _classify_intent

        intent = _classify_intent(text)
    except Exception:
        logger.exception("[pipeline] 意图路由失败，按全量注入")
    is_chitchat = bool(intent and intent.get("chitchat"))

    # 4.0) 确保今日日程已由 LLM 生成（LLM 优先，规则兜底；同一天缓存）
    try:
        from .config import config as _config
        from .schedule import ensure_schedule

        await ensure_schedule(user_id, city=_config.mood_city)
    except Exception:
        logger.exception("[pipeline] 日程生成失败（不影响回复）")

    system = build_system_prompt(
        stage=affection.stage_of(user["affection"]),
        address=pref,
        lover_confirm=bool(user["lover_confirm"]),
        first_chat=first_chat,
        affection=user["affection"],
        user_id=user_id,
    )
    messages = [{"role": "system", "content": system}]

    # 4.0.2) 新会话开场：距离上一场聊完较久（跨场）且有记录的上次话题时，
    # 让菟菚像记得似的自然接上，而不是每次都像重新认识。只在真正开场时提一次。
    try:
        if _long_gap(db.last_message_ts(user_id)):
            from .topic_memory import build_continuation

            continuation = build_continuation(user_id)
            if continuation:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "这是隔了一阵子后你们又开始聊（对方发来新消息，是新一轮的开场）。"
                            "你隐约记得上次你们聊到："
                            + continuation
                            + "。可以自然地接上一句（像还记得、随口一提），"
                            "但别生硬地翻旧账、别追问个没完；如果对方开启的是新话题，就跟新话题走，"
                            "旧话题只是你心里的背景，不是开场白。"
                        ),
                    }
                )
    except Exception:
        logger.exception("[pipeline] 话题延续注入失败")

    # 4.0.5) 网络热梗：让菟菚熟知近期热梗，能在对话里自然使用
    # 闲聊短句时跳过，避免堆砌（意图路由判定）
    if not is_chitchat:
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

    # 4.1.5) 中国节日：今天若是节日（公历/农历），自然融入对话
    try:
        from .holidays import holiday_prompt

        festival = holiday_prompt(user_id)
        if festival:
            messages.append({"role": "system", "content": festival})
    except Exception:
        logger.exception("[pipeline] 节日注入失败")

    # 4.1) 记忆相关：压缩摘要 + 记忆原文 + 长期事实，合并成一个「记得的过去」块，
    # 减少堆砌：把三条独立 system 消息合成一段，LLM 更容易当背景吸收而不是逐条服从。
    memory_lines: list[str] = []
    if compact_summary:
        memory_lines.append(
            "（更早的对话摘要，作为长期背景，自然融入，不用复述）\n" + compact_summary
        )
    else:
        # 跨会话滚动继承：本轮没触发压缩，但上次会话持久化过 6 分区摘要 → 带进来
        try:
            from .memory import load_compact_summary

            prev_summary = load_compact_summary(user_id)
            if prev_summary:
                memory_lines.append(
                    "（你记得的关于你们过去的事，作为长期背景，自然融入，不用复述）\n" + prev_summary
                )
        except Exception:
            pass
    if remembered:
        memory_lines.append(
            "（你记得的这些过去的事）\n" + "\n".join(f"- {t}" for t in remembered)
        )
    if facts:
        memory_lines.append(
            "（你记住的关于对方的事）\n" + "\n".join(f"- {f}" for f in facts)
        )
    # 结构化事实三元组：疑似回忆时做 RAG 检索（纯 TF-IDF，无额外 LLM 成本）
    try:
        from .triple_memory import format_triples as _fmt_triples, query_triples

        triples = query_triples(user_id, text)
        if triples:
            memory_lines.append(_fmt_triples(triples))
    except Exception:
        pass
    if memory_lines:
        messages.append(
            {
                "role": "system",
                "content": (
                    "你记得的关于你们和对方的过去：\n"
                    + "\n\n".join(memory_lines)
                    + "\n这些都只是你的记忆背景：想起来就自然融入，想不起来就别硬凑；"
                    "不要逐条汇报、不要『我记得你说过…』式开场白刷屏。"
                ),
            }
        )

    # 4.2) 对对方的了解：画像 + 口头禅/黑话 + 场景风格 + 说话风格，合成一条注入。
    # 闲聊时跳过，避免堆砌额外信息（意图路由判定）。
    if not is_chitchat:
        # 各功能仍按开关独立收集（关掉的不注入），但合成一条 system 消息：
        # 避免一堆并列指令压着模型（堆砌），而是像"你心里对这个人越摸越清"一样自然。
        understanding_parts: list[str] = []
        try:
            from .features import flag
            from .profile import profile_prompt_text

            if flag("profile_enabled"):
                profile = profile_prompt_text(user_id)
                if profile:
                    understanding_parts.append(f"【对方的画像】\n{profile}")
        except Exception:
            logger.exception("[pipeline] 用户画像注入失败")
        try:
            from .features import flag
            from .terms import terms_prompt_text

            if flag("terms_enabled"):
                terms = terms_prompt_text(user_id)
                if terms:
                    understanding_parts.append(f"【对方爱用的词】\n{terms}")
        except Exception:
            logger.exception("[pipeline] 口头禅注入失败")
        try:
            from .features import flag
            from .style import style_map_prompt_text

            if flag("style_enabled"):
                style_map = style_map_prompt_text(user_id)
                if style_map:
                    understanding_parts.append(f"【对方不同场景的表达方式】\n{style_map}")
        except Exception:
            logger.exception("[pipeline] 场景风格注入失败")
        style = db.get_style(user_id)
        if style:
            understanding_parts.append(f"【你逐渐观察到的对方说话风格】\n{style}")
        if understanding_parts:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "这是你渐渐对这个人摸清的样子（是你心里知道的，不是要你背出来的列表）：\n"
                        + "\n\n".join(understanding_parts)
                        + "\n相处久了自然记得这些：合适的时候随口体现一两点（他提到吃的你记得他爱吃什么、"
                        "他低落时你记得他讨厌什么、他开玩笑时你用他习惯的节奏），"
                        "千万别一口气全倒出来、别『我了解到你…』式汇报。宁可用不上，也别堆砌。"
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
    think_block = (
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
    )

    # 5.0) 话题锚定：明确"当前在聊什么"，避免回复被旧上下文带偏/跑题/串话题
    topic_block = None
    try:
        from .context import build_topic_system

        # 取上下文里"对方（user）最近几句"用于判断话题切换；ctx 是 role/content 列表
        recent_user_texts = [m["content"] for m in ctx if m.get("role") == "user"]
        hint = build_topic_system(text, recent_user_texts, len(ctx))
        if hint:
            topic_block = (
                "关于当前这轮的上下文要点：\n" + hint
                + "\n注意：只把它当作把握方向用的提醒，回复仍要自然、口语化，"
                "不要复述这些提醒本身。"
            )
    except Exception:
        logger.exception("[pipeline] 话题锚定失败（不影响回复）")

    # 5.1) 工具调用循环：意图路由判定需要搜索时，让 LLM 用 ```tool``` 代码块自主调工具
    # （web_search / get_weather），结果注入下一轮，最多 N 轮；失败/闲聊一律回退普通对话。
    use_tool_loop = False
    try:
        use_tool_loop = (
            not mock
            and intent is not None
            and intent.get("need_search")
            and not search_hits  # 规则搜索已提前注入结果 → 不再走工具循环，避免重复搜索
        )
    except Exception:
        pass

    if use_tool_loop:
        from .tool_loop import run_tool_loop

        final_instruction = [{"role": "system", "content": think_block}]
        if topic_block:
            final_instruction.append({"role": "system", "content": topic_block})
        raw = await run_tool_loop(
            messages,
            lambda ms: chat(ms, mock=mock),
            max_loops=2,
            final_instruction=final_instruction,
        )
    else:
        messages.append({"role": "system", "content": think_block})
        if topic_block:
            messages.append({"role": "system", "content": topic_block})
        raw = await chat(messages, mock=mock)
    reply = strip_actions(_extract_reply(raw))
    reply = trim_farewell(text, reply)
    # 兜底：回复为空/只剩思考（LLM 输出异常）时，给一句不冷场的默认回复
    if not reply.strip():
        reply = "嗯……我想想怎么回你。"

    # 6) 存档
    db.add_message(user_id, "user", text)
    db.add_message(user_id, "assistant", reply)
    lm1_id = db.add_long_memory(user_id, f"用户说：{text}")
    lm2_id = db.add_long_memory(user_id, f"菟菚说：{reply}")
    db.set_first_chat_done(user_id)

    # 6.1) 给新长期记忆建稠密向量索引（失败静默，不影响回复）
    try:
        import asyncio as _asyncio
        from .vector_store import index as vec_index

        # embedding 走网络（同步 urllib）→ 放线程池避免阻塞事件循环
        await _asyncio.to_thread(vec_index, user_id, lm1_id, f"用户说：{text}", "lm")
        await _asyncio.to_thread(vec_index, user_id, lm2_id, f"菟菚说：{reply}", "lm")
    except Exception:
        pass
    return reply
