"""好感度系统：阶段映射 + 即时规则（每日首次/陪伴、刷屏、辱骂、恋人达成）。"""
from collections import deque
from datetime import date, datetime, timedelta

from .userdb import db

# ---- 分值常量（对应 bot-design.md 规则）----
DAY_FIRST_BONUS = 2     # 每天首次聊天
DAILY_COMPANION = 1     # 当日陪伴
HOBBY_BONUS = 1         # 用户聊自己的爱好（每日总结判定，封顶见 daily.py）
RESPECT_BONUS = 1       # 尊重菟菚的喜好（每日总结判定）
DISMISS_PENALTY = -3    # 轻视、不重视（每日总结判定）
SPAM_PENALTY = -2       # 刷屏
ABUSE_PENALTY = -5      # 辱骂

STAGE_THRESHOLDS = ((0, "初识"), (25, "熟悉"), (50, "亲密"), (75, "恋人"))

# 基础辱骂词库（可扩充）
ABUSE_WORDS = [
    "傻逼", "煞笔", "沙比", "废物", "垃圾", "去死", "贱人", "畜生",
    "脑残", "智障", "滚蛋", "恶心", "爬", "sb", "SB", "cnm", "草泥马", "妈的",
]

_SPAM_WINDOW_SECONDS = 10
_SPAM_MAX_COUNT = 3

# 每用户最近消息时间戳（内存态）
_timestamps: dict[str, deque[float]] = {}


def stage_of(affection: int) -> str:
    label = STAGE_THRESHOLDS[0][1]
    for threshold, name in STAGE_THRESHOLDS:
        if affection >= threshold:
            label = name
    return label


def check_abuse(text: str) -> bool:
    lowered = text.lower()
    return any(w in lowered for w in ABUSE_WORDS)


def _spam_hit(user_id: str) -> bool:
    now = datetime.now().timestamp()
    q = _timestamps.setdefault(user_id, deque())
    while q and now - q[0] > _SPAM_WINDOW_SECONDS:
        q.popleft()
    q.append(now)
    return len(q) >= _SPAM_MAX_COUNT


def on_message(user_id: str, text: str) -> None:
    """每次收到用户消息时调用：处理好感度即时规则与日期回滚。"""
    user = db.ensure_user(user_id)
    today = date.today()

    # ---- 跨天回滚：昨日每日总结 + 新一天首次聊天/陪伴 ----
    last_day = user["last_chat_date"]
    if last_day != today.isoformat():
        if last_day:
            yesterday = today - timedelta(days=1)
            if user["last_batch_date"] != yesterday.isoformat():
                # 惰性执行昨日 LLM 每日总结（聊爱好/尊重/轻视判定）
                from .daily import run_daily_batch  # 延迟导入避免循环

                try:
                    run_daily_batch(user_id, yesterday)
                except Exception:
                    pass  # 总结失败不阻塞对话
                db.set_chat_date(user_id, today.isoformat(), yesterday.isoformat())
            else:
                db.set_chat_date(user_id, today.isoformat())
        else:
            db.set_chat_date(user_id, today.isoformat())

        db.update_affection(user_id, DAY_FIRST_BONUS, "每日首次聊天")
        db.update_affection(user_id, DAILY_COMPANION, "当日陪伴")

    # ---- 即时扣分 ----
    if _spam_hit(user_id):
        db.update_affection(user_id, SPAM_PENALTY, "刷屏")
    if check_abuse(text):
        db.update_affection(user_id, ABUSE_PENALTY, "辱骂")

    # ---- 恋人达成（首次）→ 触发第二次称呼确认 ----
    user = db.get_user(user_id)
    if user["affection"] >= 75 and not user["lover_confirm"]:
        db.set_lover_confirm(user_id)
