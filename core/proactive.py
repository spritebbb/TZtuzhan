"""主动发消息：菟菚在与你久别后主动找你。

- 记录最近和她私聊过的用户（set_active_user）
- run_scheduler() 定时检查：距你上次说话超过 PROACTIVE_IDLE_HOURS，且超过冷却期，就主动发一条
- proactive_message() 让菟菚"自己想到你"地生成一条发起消息（不是机械问候）
"""
import asyncio
from datetime import datetime

from . import affection
from .config import config
from .llm import chat
from .persona import build_system_prompt
from .pipeline import _extract_reply, strip_actions
from .userdb import db

_active_user = {"id": None}


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
                "随口说一句；声音懒懒的、短一点（一两截），别太多。结合你们现在的关系阶段和称呼。"
            ),
        }
    )
    raw = await chat(messages)
    return strip_actions(_extract_reply(raw))


async def _send_burst(bot, user_id: str, text: str) -> None:
    """像网友一样把主动消息拆成几条短消息发送。"""
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        parts = [text]
    for i, p in enumerate(parts[:5]):
        if i > 0:
            await asyncio.sleep(config.send_interval)
        await bot.send_private_msg(user_id=int(user_id), message=p)


async def send_proactive_now(bot, user_id: str) -> bool:
    """立即给 user_id 主动发一条（用于 /主动 测试或定时触发）。"""
    try:
        msg_text = await proactive_message(user_id)
        await _send_burst(bot, user_id, msg_text)
        db.set_last_proactive(user_id)
        return True
    except Exception:
        return False


async def run_scheduler() -> None:
    """后台定时任务：久别后主动发消息。"""
    while True:
        await asyncio.sleep(config.proactive_check_minutes * 60)
        user_id = get_active_user()
        if not user_id:
            continue

        age = _age_hours(db.last_message_ts(user_id))
        if age is None or age < config.proactive_idle_hours:
            continue

        last_pro = db.get_last_proactive(user_id)
        if last_pro:
            hours_since = _age_hours(last_pro)
            if hours_since is not None and hours_since < config.proactive_cooldown_hours:
                continue

        try:
            from nonebot import get_bot

            await send_proactive_now(get_bot(), user_id)
        except Exception:
            pass
