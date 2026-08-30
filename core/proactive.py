"""主动发消息：菟菚在与你久别后主动找你。

- 记录最近和她私聊过的用户（set_active_user）
- run_scheduler() 定时检查：距你上次说话超过 PROACTIVE_IDLE_HOURS，且超过冷却期，就主动发一条
- proactive_message() 让菟菚"自己想到你"地生成一条发起消息（不是机械问候）
- 主动消息会写入 messages 表存档（用户回复时上下文能接上）；按时段、近期话题、
  关系阶段调整语气与频率
"""
import asyncio
import random
from .rhythm import jitter as _jitter
from datetime import datetime

from . import affection
from .config import config
from .llm import chat
from .log import logger
from .memory import short_term_messages
from .message_build import image_file
from .persona import build_system_prompt
from .pipeline import _extract_reply, strip_actions
from .userdb import db

_active_user = {"id": None}

# 各关系阶段相对默认冷却的倍率：越熟越愿意主动找你
_STAGE_COOLDOWN_MULTIPLIER = {
    "初识": 2.0,
    "熟悉": 1.0,
    "亲密": 0.7,
    "恋人": 0.5,
}

# 时段 → 语气提示（菟菚主动发消息时的"由头"）
_PERIOD_HINT = (
    ("凌晨", 0, 5, "凌晨了，你还醒着吗？声音轻轻软软的，像怕吵醒谁"),
    ("早晨", 5, 9, "刚醒没多久，声音还带着点起床气，随口说一句"),
    ("上午", 9, 12, "上午，慵慵懒懒的，像在发呆时想起你"),
    ("中午", 12, 14, "中午，像吃完饭消食时随口提一句"),
    ("下午", 14, 18, "下午，懒洋洋的，像晒着太阳想起你"),
    ("傍晚", 18, 21, "傍晚，像忙完一天松口气时想找你说话"),
    ("晚上", 21, 24, "晚上，安安静静的，像睡前想跟你说句话"),
)


def _period_hint() -> str:
    """当前时段的中文提示（含语气），用于让主动消息有"时间感"。"""
    h = datetime.now().hour
    for name, start, end, hint in _PERIOD_HINT:
        if start <= h < end:
            return f"现在是{name}（{h}点前后）。{hint}。"
    return ""


# ---- 多场景主动：节日 / 特殊日子 / 天气 / 深夜安慰 ----

def _festival_hint() -> str:
    """今天是中国节日时返回节日提示（否则空）。"""
    try:
        from .holidays import today_holidays

        names = today_holidays()
        if names:
            return "、".join(names)
    except Exception:
        pass
    return ""


def _special_date_hint(user_id: str) -> str:
    """今天是用户设定的特殊日子（生日/纪念日等）时返回提示（否则空）。"""
    try:
        from .userdb import get_today_important_dates

        today_dates = get_today_important_dates(user_id)
        if today_dates:
            return "、".join(d["label"] for d in today_dates)
    except Exception:
        pass
    return ""


def _weather_hint(city: str) -> str:
    """今日天气与心情提示（有天气时返回，否则空）。"""
    try:
        from .mood import today_weather

        weather, base = today_weather(city)
        if weather and weather != "未知":
            if "雨" in weather:
                return f"今天天气：{weather}。下雨了，这样的天气你会想赖在家里吧。"
            if "雪" in weather:
                return f"今天天气：{weather}。下雪了，很适合窝在一起说点暖的话。"
            return f"今天天气：{weather}。天气会悄悄影响心情，可以轻轻提一句。"
    except Exception:
        pass
    return ""


def _late_night_hint() -> str:
    """深夜时段（23-5点）返回安慰提示（否则空）。"""
    h = datetime.now().hour
    if h >= 23 or h < 5:
        return "现在是深夜。如果你还醒着，大概是心里有事或者睡不着，可以温柔地陪一会儿。"
    return ""


def _scenario_hint(user_id: str, city: str) -> str:
    """组合各场景提示，用于主动消息生成：节日/特殊日子优先，其次是深夜安慰/天气。"""
    parts = []
    festival = _festival_hint()
    if festival:
        parts.append(f"今天是中国节日：{festival}。如果合适，可以从节日由头开始（轻轻祝福一句，别太隆重）。")
    special = _special_date_hint(user_id)
    if special:
        parts.append(f"今天是对方重要的日子：{special}。记得要提一提，这是你心里有ta的证明（自然、别刻意）。")
    late = _late_night_hint()
    if late:
        parts.append(late)
    weather = _weather_hint(city)
    if weather:
        parts.append(weather)
    return "\n".join(parts)


def set_active_user(user_id: str) -> None:
    _active_user["id"] = user_id


def get_active_user() -> str | None:
    return _active_user["id"]


def _age_hours(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
    except ValueError:
        return None


async def proactive_message(user_id: str) -> str:
    """生成一条菟菚主动发出的消息（像自己想到你、随口说一句）。"""
    user = db.ensure_user(user_id)
    system = build_system_prompt(
        stage=affection.stage_of(user["affection"]),
        address=user["nickname_pref"],
        lover_confirm=bool(user["lover_confirm"]),
        first_chat=not user["first_chat_done"],
        affection=user["affection"],
        user_id=user_id,
    )
    messages = [{"role": "system", "content": system}]
    messages.append(
        {
            "role": "system",
            "content": (
                "现在是你在主动给对方发消息（对方还没说话）。就像平时想到对方了、或想起一件小事，"
                "随口说一句；声音懒懒的、短一点（一两截），别太多。结合你们现在的关系阶段和称呼。\n"
                f"{_period_hint()}"
            ),
        }
    )
    # 场景由头（节日/特殊日子/天气）——天气首次获取走网络，预热到线程池再主线程调
    #（_scenario_hint 内部访问 db，整函数丢线程会跨线程 sqlite 崩溃）
    import asyncio as _asyncio
    from .mood import today_weather as _today_weather

    try:
        if config.mood_city:
            await _asyncio.to_thread(_today_weather, config.mood_city)
    except Exception:
        pass

    scenario = _scenario_hint(user_id, config.mood_city)
    if scenario:
        messages.append(
            {
                "role": "system",
                "content": (
                    "今天/此刻有这些特别之处，可以在主动消息里自然带上（挑最合适的一个就够，别全塞）：\n"
                    + scenario
                ),
            }
        )
    # 关联近期话题：从最近的对话里找 1-2 个由头，让主动消息像"接着上次聊"而不是凭空搭话
    recent = short_term_messages(user_id)
    if recent:
        tail = " ".join(
            f"{'对方' if m['role'] == 'user' else '你'}说：{m['content'][:40]}"
            for m in recent[-4:]
        )
        messages.append(
            {
                "role": "system",
                "content": (
                    f"你们最近的对话大致是：{tail}\n"
                    "可以从中挑一个自然的话题开头（比如对方上次提到的某件事），"
                    "但别复述原文、别像汇报，就像突然想起随口一提。"
                ),
            }
        )
    raw = await chat(messages)
    return strip_actions(_extract_reply(raw))


# 发送重试：QQ 网络抖动时补发，避免主动消息丢失
_SEND_MAX_RETRIES = 2


async def _send_with_retry(bot, user_id: str, message) -> None:
    """发送一条私聊消息，失败重试（指数退避），全部失败抛异常。"""
    last_exc: Exception | None = None
    for attempt in range(_SEND_MAX_RETRIES + 1):
        try:
            await bot.send_private_msg(user_id=int(user_id), message=message)
            return
        except Exception as e:
            last_exc = e
            if attempt < _SEND_MAX_RETRIES:
                await asyncio.sleep(1.0 * (2**attempt))
    raise last_exc


async def _send_burst(bot, user_id: str, text: str) -> int:
    """像网友一样把主动消息拆成几条短消息发送（也不带句号）。

    返回成功发出的条数（>=1 表示已部分发出；0 表示一条都没发出去）。
    中途失败即停止剩余部分：避免"前几条已发出、整批却未标记，
    下轮调度整批重发"造成用户收到重复消息。
    """
    parts = [p.strip().rstrip("。").strip() or p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        parts = [text.rstrip("。")]
    sent = 0
    for i, p in enumerate(parts[:5]):
        if i > 0:
            await asyncio.sleep(_jitter(config.send_interval))
        try:
            await _send_with_retry(bot, user_id, p)
            sent += 1
        except Exception:
            logger.warning("[主动] 发送中途失败（已发出 {} 条，剩余放弃，避免整批重发重复）", sent)
            break
    return sent


async def send_proactive_now(bot, user_id: str) -> bool:
    """立即给 user_id 主动发一条（用于 /主动 测试或定时触发）。"""
    try:
        msg_text = await proactive_message(user_id)
        sent = await _send_burst(bot, user_id, msg_text)
        # 一条都没发出去 → 返回 False，不标记，下轮可重试整批
        if sent < 1:
            return False
        # 至少发出 1 条即视为"已主动"：标记 last_proactive（同日去重），
        # 避免发送中途失败后下轮整批重发、用户重复收到已发部分。
        db.add_message(user_id, "assistant", msg_text)
        db.set_last_proactive(user_id)
        # 记录本次主动消息时间戳（供「回应主动消息」好感度奖励检测）
        try:
            from .userdb import kv_set
            import datetime

            kv_set(user_id, "last_proactive_ts", datetime.datetime.now().isoformat(timespec="seconds"))
        except Exception:
            pass
        # ⑥ 表情包主动推荐：用户有收藏时，约 1/4 概率在主动消息后带一张收藏的表情包
        try:
            if random.random() < 0.25:
                from .sticker import get_recent_sticker
                from nonebot.adapters.onebot.v11 import Message, MessageSegment

                sticker = get_recent_sticker(user_id)
                if sticker:
                    # 配一句自然话，不让表情包显得突兀
                    try:
                        from .speak import with_sticker

                        talk = await with_sticker("菟菚想起你了")
                        if talk:
                            await asyncio.sleep(_jitter(config.send_interval))
                            await _send_with_retry(bot, user_id, talk)
                    except Exception:
                        logger.warning("[主动] 表情话术失败（不影响发图）")
                    await asyncio.sleep(_jitter(config.send_interval))
                    await _send_with_retry(
                        bot, user_id, Message(MessageSegment.image(file=image_file(sticker)))
                    )
        except Exception:
            logger.warning("[主动] 表情包推荐失败（不影响主动消息）")
        return True
    except Exception:
        logger.exception("[主动] 给 {} 发主动消息失败", user_id)
        return False


def _stage_cooldown_hours(user_id: str) -> float:
    """按关系阶段缩放冷却时间：越熟越愿意主动找你。

    用户可能尚无记录（get_user 返回 None），用 ensure_user 兜底拿默认阶段。
    """
    user = db.ensure_user(user_id)
    stage = affection.stage_of(user["affection"])
    return config.proactive_cooldown_hours * _STAGE_COOLDOWN_MULTIPLIER.get(stage, 1.0)


def _target_user_ids() -> list[str]:
    """主动消息目标：配置的多个 QQ 号；没配置则用最后说话的人。"""
    if config.proactive_user_ids:
        return list(config.proactive_user_ids)
    au = get_active_user()
    return [au] if au else []


async def run_scheduler() -> None:
    """后台定时任务：久别后主动发消息。

    - ⑨ 支持多个 PROACTIVE_USER_ID（逗号分隔）
    - ④ 频率控制：对方刚回复后进入冷静期不打扰；检查间隔带随机抖动避免死板节奏
    - ④ 同日去重：一天内对同一用户只主动一次（避免多次打扰）
    """
    while True:
        try:
            # ④ 随机抖动：在基准间隔上 ±30%，避免"每 15 分钟整点"的机械感
            base = config.proactive_check_minutes * 60
            await asyncio.sleep(base * random.uniform(0.7, 1.3))

            today = datetime.now().date().isoformat()
            for user_id in _target_user_ids():
                try:
                    age = _age_hours(db.last_message_ts(user_id))
                    # 特殊日子（节日/用户的生日/纪念日）：当天即使刚聊过也要主动一次，
                    # 不因"离上次说话太近"而错过该说的祝福。其余日子仍按久别阈值。
                    is_special_day = bool(_festival_hint() or _special_date_hint(user_id))
                    if not is_special_day and (age is None or age < config.proactive_idle_hours):
                        continue

                    last_pro = db.get_last_proactive(user_id)
                    if last_pro:
                        # 同日去重：今天已主动过 → 跳过
                        try:
                            if last_pro[:10] == today:
                                continue
                        except Exception:
                            pass
                        hours_since = _age_hours(last_pro)
                        if hours_since is not None and hours_since < _stage_cooldown_hours(user_id):
                            continue

                    try:
                        from nonebot import get_bot

                        await send_proactive_now(get_bot(), user_id)
                    except Exception:
                        logger.exception("[主动] 定时主动发消息失败：{}", user_id)
                except Exception:
                    logger.exception("[主动] 检查用户 {} 时异常（跳过，不影响其他用户）", user_id)
        except Exception:
            logger.exception("[主动] 调度器循环异常（已恢复，继续运行）")
