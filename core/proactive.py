"""主动发消息：菟菚在与你久别后主动找你。

- 记录最近和她私聊过的用户（set_active_user）
- run_scheduler() 定时检查：距你上次说话超过 PROACTIVE_IDLE_HOURS，且超过冷却期，就主动发一条
- proactive_message() 让菟菚"自己想到你"地生成一条发起消息（不是机械问候）
- 主动消息会写入 messages 表存档（用户回复时上下文能接上）；按时段、近期话题、
  关系阶段调整语气与频率
"""
import asyncio
from datetime import datetime

from . import affection
from .config import config
from .llm import chat
from .log import logger
from .memory import short_term_messages
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
    # 情感记忆：今天有特殊日子（生日/纪念日）时，优先用这个由头
    try:
        from .userdb import get_today_important_dates

        today_dates = get_today_important_dates(user_id)
    except Exception:
        logger.exception("[主动] 特殊日子查询失败")
        today_dates = []
    if today_dates:
        labels = "、".join(d["label"] for d in today_dates)
        messages.append(
            {
                "role": "system",
                "content": (
                    f"今天是特殊的日子：{labels}。"
                    "如果合适，主动消息就从这个由头开始（比如轻轻说一句今天是你的生日/纪念日），"
                    "自然一点，别太隆重，保持你的慵懒温柔。"
                ),
            }
        )
    raw = await chat(messages)
    return strip_actions(_extract_reply(raw))


async def _send_burst(bot, user_id: str, text: str) -> None:
    """像网友一样把主动消息拆成几条短消息发送（也不带句号）。"""
    parts = [p.strip().rstrip("。").strip() or p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        parts = [text.rstrip("。")]
    for i, p in enumerate(parts[:5]):
        if i > 0:
            await asyncio.sleep(config.send_interval)
        await bot.send_private_msg(user_id=int(user_id), message=p)


async def send_proactive_now(bot, user_id: str) -> bool:
    """立即给 user_id 主动发一条（用于 /主动 测试或定时触发）。"""
    try:
        msg_text = await proactive_message(user_id)
        await _send_burst(bot, user_id, msg_text)
        # 主动消息也存档：用户回复时上下文能接上（修复此前不写 messages 的断档）
        db.add_message(user_id, "assistant", msg_text)
        db.set_last_proactive(user_id)
        return True
    except Exception:
        logger.exception("[主动] 给 {} 发主动消息失败", user_id)
        return False


def _stage_cooldown_hours(user_id: str) -> float:
    """按关系阶段缩放冷却时间：越熟越愿意主动找你。"""
    stage = affection.stage_of(db.get_user(user_id)["affection"])
    return config.proactive_cooldown_hours * _STAGE_COOLDOWN_MULTIPLIER.get(stage, 1.0)


async def run_scheduler() -> None:
    """后台定时任务：久别后主动发消息（只给 PROACTIVE_USER_ID 或最后说话的人）。"""
    while True:
        await asyncio.sleep(config.proactive_check_minutes * 60)
        # 限定只给配置的 QQ 号发；没配就用最后说话的人
        user_id = config.proactive_user_id or get_active_user()
        if not user_id:
            continue

        age = _age_hours(db.last_message_ts(user_id))
        if age is None or age < config.proactive_idle_hours:
            continue

        last_pro = db.get_last_proactive(user_id)
        if last_pro:
            hours_since = _age_hours(last_pro)
            if hours_since is not None and hours_since < _stage_cooldown_hours(user_id):
                continue

        try:
            from nonebot import get_bot

            await send_proactive_now(get_bot(), user_id)
        except Exception:
            logger.exception("[主动] 定时主动发消息失败")
