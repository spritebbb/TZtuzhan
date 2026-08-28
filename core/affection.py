"""好感度系统：阶段映射 + 即时规则（每日首次/陪伴、刷屏、辱骂、恋人达成）。

v2 优化：
- 正向互动奖励：用称呼、关心菟菚、回应主动消息、深度聊天、引用记忆
- 惩罚调优：刷屏阈值放宽、单日扣分上限、辱骂分级
- 恋人羁绊等级：眷恋(75-84) / 热恋(85-94) / 白头(95-100)
- 体验感：进度条、好感变动自然融入对话
"""
from collections import deque
from datetime import date, datetime, timedelta

from .log import logger
from .tasks import schedule
from .userdb import db

# ---- 分值常量（对应 bot-design.md 规则）----
DAY_FIRST_BONUS = 2         # 每天首次聊天
DAILY_COMPANION = 1         # 当日陪伴
HOBBY_BONUS = 1             # 用户聊自己的爱好（每日总结判定）
RESPECT_BONUS = 1           # 尊重菟菚的喜好（每日总结判定）
DISMISS_PENALTY = -3        # 轻视、不重视（每日总结判定）
SPAM_PENALTY = -2           # 刷屏
ABUSE_PENALTY = -5          # 辱骂（严重）
BAD_ADDRESS_PENALTY = -2    # 要求不合适的称呼（轻扣）
EARLY_CONFESSION_PENALTY = -1  # 过早表白/求婚（初识/熟悉阶段，轻扣）

# ---- v2 新增正向奖励 ----
NICKNAME_BONUS = 1            # 用户用菟菚的称呼交流（每日上限1次）
CARE_BONUS = 1                # 用户关心菟菚（每日上限1次）
PROACTIVE_RESPONSE_BONUS = 2  # 回应菟菚的主动消息（每日上限1次）
DEEP_CHAT_BONUS = 2           # 当天有深度/走心对话（每日总结判定）
MEMORY_REFERENCE_BONUS = 1    # 用户提到过去共同经历/菟菚提过的事（每日上限1次）

# ---- 惩罚调优 ----
_SPAM_WINDOW_SECONDS = 8      # 放宽到 8 秒（原10秒）
_SPAM_MAX_COUNT = 4           # 放宽到 4 条（原3条）
DAILY_PENALTY_LIMIT = -10     # 单日扣分不超 -10（防止连续扣负）

# ---- 恋人羁绊等级 ----
BOND_LEVELS = (
    (75, "眷恋", "你们已经是恋人，感情深厚，彼此已经是对方生活的一部分。"),
    (85, "热恋", "你们正处于热恋期，一日不见如隔三秋，黏在一起是最幸福的事。"),
    (95, "白头", "你们已经认定彼此，感情像老酒一样越陈越香，默契十足，一个眼神就懂对方在想什么。"),
)

STAGE_THRESHOLDS = ((0, "初识"), (25, "熟悉"), (50, "亲密"), (75, "恋人"))

# 基础辱骂词库（可扩充）
ABUSE_WORDS = [
    "傻逼", "煞笔", "沙比", "废物", "垃圾", "去死", "贱人", "畜生",
    "脑残", "智障", "滚蛋", "恶心", "爬", "sb", "SB", "cnm", "草泥马", "妈的",
]

# 不合适的称呼（要求菟菚这样称呼会拒绝并扣好感度，可扩充）
BAD_ADDRESS_WORDS = [
    # 辱骂/侮辱类
    "傻逼", "煞笔", "沙比", "骚狗", "母狗", "贱狗", "臭狗", "狗逼", "狗东西", "贱人", "废物", "垃圾",
    # 亲属辈分类（失当）
    "爸爸", "爹", "爹爹", "爷爷", "奶奶", "祖宗",
]

# 过早表白/求婚词（初识/熟悉阶段视为变态行为，拒绝；亲密/恋人阶段不受限）
EARLY_CONFESSION_WORDS = [
    "结婚", "嫁给我", "娶我", "求婚", "当我女朋友", "当我老婆", "当我男朋友", "当我老公",
    "做我女朋友", "做我老婆", "我喜欢你", "我爱你", "永远在一起", "私奔",
]

# 用户关心菟菚的关键词（关心话检测）
CARE_WORDS = [
    "你还好吗", "你没事吧", "累不累", "辛苦了", "你也要休息", "你也要注意",
    "你冷不冷", "你热不热", "你饿不饿", "照顾好自己", "你也要好好的",
    "别太累", "别熬夜", "你也要睡", "别勉强", "你开心吗", "你心情好吗",
    "怎么了", "你没事", "担心你", "想你", "想你了",
]

# 刷屏判定（每用户最近消息时间戳，内存态）
_timestamps: dict[str, deque[float]] = {}


def stage_of(affection: int) -> str:
    """好感度 → 阶段名称。"""
    label = STAGE_THRESHOLDS[0][1]
    for threshold, name in STAGE_THRESHOLDS:
        if affection >= threshold:
            label = name
    return label


def bond_level(affection: int) -> tuple[str, str] | None:
    """好感度 → 恋人羁绊等级 (名称, 描述)；非恋人阶段返回 None。"""
    if affection < 75:
        return None
    name, desc = BOND_LEVELS[0][1], BOND_LEVELS[0][2]
    for threshold, n, d in BOND_LEVELS:
        if affection >= threshold:
            name, desc = n, d
    return name, desc


def bond_level_name(affection: int) -> str:
    bl = bond_level(affection)
    return bl[0] if bl else ""


def set_affection(user_id: str, value: int) -> None:
    """手动设置好感度（0-100），用于调试/调节。"""
    db.set_affection_absolute(user_id, value)


def describe(user_id: str) -> str:
    """返回该用户好感度与阶段的描述文本（含进度条）。"""
    u = db.get_user(user_id)
    if not u:
        return "尚未有记录"
    aff = u["affection"]
    stage = stage_of(aff)
    # 进度条（10 格）
    bar_amt = aff // 10
    bar = "█" * bar_amt + "░" * (10 - bar_amt)
    # 找下一阶段
    next_threshold = None
    for t, s in STAGE_THRESHOLDS:
        if t > aff:
            next_threshold = t
            break
    line = f"好感度 {aff} · 阶段「{stage}」\n{bar}"
    if next_threshold:
        line += f"\n距离下一阶段还需 {next_threshold - aff} 点"
    bl = bond_level(aff)
    if bl:
        line += f"\n羁绊 · {bl[0]}"
    return line


def check_abuse(text: str) -> bool:
    lowered = text.lower()
    return any(w in lowered for w in ABUSE_WORDS)


def check_bad_address(name: str) -> bool:
    """判断是否为不合适的称呼（侮辱类 / 失当亲属称谓）。"""
    return any(w in name for w in BAD_ADDRESS_WORDS)


def check_early_confession(text: str) -> bool:
    """判断是否为过早的表白/求婚（初识/熟悉阶段触发拒绝）。"""
    return any(w in text for w in EARLY_CONFESSION_WORDS)


def check_care(text: str) -> bool:
    """判断用户是否在关心菟菚。"""
    lowered = text.lower()
    return any(w in lowered for w in CARE_WORDS)


def check_nickname_used(text: str, pref: str | None) -> bool:
    """判断用户是否在当前消息里用了菟菚的称呼（pref）。"""
    if not pref or pref == "你":
        return False
    return pref in text


def _spam_hit(user_id: str) -> bool:
    now = datetime.now().timestamp()
    q = _timestamps.setdefault(user_id, deque())
    while q and now - q[0] > _SPAM_WINDOW_SECONDS:
        q.popleft()
    q.append(now)
    return len(q) >= _SPAM_MAX_COUNT


# ---- 每日奖励去重（用 user_meta 表）----


def _daily_bonus_done(user_id: str, bonus_key: str) -> bool:
    """检查当天该奖励是否已触发过。"""
    from .userdb import kv_get

    today = date.today().isoformat()
    return kv_get(user_id, f"bonus:{today}:{bonus_key}") is not None


def _mark_daily_bonus(user_id: str, bonus_key: str) -> None:
    from .userdb import kv_set

    today = date.today().isoformat()
    kv_set(user_id, f"bonus:{today}:{bonus_key}", "1")


def try_daily_bonus(user_id: str, bonus_key: str, delta: int, reason: str) -> bool:
    """尝试给一次每日上限奖励；当天已给过则跳过。返回是否执行。"""
    if _daily_bonus_done(user_id, bonus_key):
        return False
    db.update_affection(user_id, delta, reason)
    _mark_daily_bonus(user_id, bonus_key)
    return True


# ---- 单日扣分累计 ----

def _daily_penalty_total(user_id: str) -> int:
    """当天已累计扣分总和（负值）。"""
    today = date.today().isoformat()
    rows = db.conn.execute(
        "SELECT delta FROM affection_log WHERE user_id=? AND ts LIKE ? AND delta < 0",
        (user_id, f"{today}%"),
    ).fetchall()
    return sum(r["delta"] for r in rows)


def _penalty_ok(user_id: str, delta: int) -> bool:
    """检查这一笔扣分是否会导致当天扣分超限。"""
    if delta >= 0:
        return True
    total = _daily_penalty_total(user_id) + delta
    return total >= DAILY_PENALTY_LIMIT


async def on_message(user_id: str, text: str) -> None:
    """每次收到用户消息时调用：处理好感度即时规则与日期回滚。"""
    user = db.ensure_user(user_id)
    today = date.today()

    # ---- 心情更新：用户消息影响菟菚心情（有趣→升，冒犯→降）----
    from .mood import on_user_message as _mood_on_msg, mood_bonus_multiplier
    from .config import config

    mood = _mood_on_msg(user_id, text, city=config.mood_city)
    # 心情 → 好感度变动倍率（心情好加分多、扣分少；心情差反之）
    mult = mood_bonus_multiplier(mood)

    def _scaled(delta: int, reason: str) -> None:
        """按心情倍率缩放好感度变动（正数×mult，负数用补偿倍率）。"""
        if delta >= 0:
            scaled = round(delta * mult)
        else:
            # 心情差时扣分更狠：低落(0.6) → 扣分×1.4；雀跃(1.5) → 扣分×0.5
            scaled = round(delta * (2.0 - mult))
        if scaled != 0:
            db.update_affection(user_id, scaled, reason)

    # ---- 基础聊天奖励：每次消息 +1，每日上限 10 次 ----
    # 让日常聊天就能涨好感度，不依赖特定关键词或后台任务
    from .userdb import kv_get as _kv_get, kv_set as _kv_set

    chat_count_key = f"bonus:{today.isoformat()}:chat_count"
    chat_count = int(_kv_get(user_id, chat_count_key) or "0")
    if chat_count < 10:
        _scaled(1, "日常聊天")
        _kv_set(user_id, chat_count_key, str(chat_count + 1))

    # ---- 跨天回滚：昨日每日总结 + 新一天首次聊天/陪伴 ----
    last_day = user["last_chat_date"]
    if last_day != today.isoformat():
        if last_day:
            yesterday = today - timedelta(days=1)
            if user["last_batch_date"] != yesterday.isoformat():
                # 后台执行昨日 LLM 每日总结（不阻塞本轮回复）
                from .daily import run_daily_batch  # 延迟导入避免循环

                schedule(f"daily:{user_id}:{yesterday}", lambda uid=user_id, d=yesterday: run_daily_batch(uid, d))
                db.set_chat_date(user_id, today.isoformat(), yesterday.isoformat())
            else:
                db.set_chat_date(user_id, today.isoformat())
        else:
            db.set_chat_date(user_id, today.isoformat())

        # 每日首次和陪伴奖励：用 kv_store 防重复
        if not _daily_bonus_done(user_id, "first_chat"):
            _scaled(DAY_FIRST_BONUS, "每日首次聊天")
            _scaled(DAILY_COMPANION, "当日陪伴")
            _mark_daily_bonus(user_id, "first_chat")

    # ---- 即时扣分（含每日上限检查）----
    if _spam_hit(user_id):
        if _penalty_ok(user_id, SPAM_PENALTY):
            _scaled(SPAM_PENALTY, "刷屏")
    if check_abuse(text):
        if _penalty_ok(user_id, ABUSE_PENALTY):
            _scaled(ABUSE_PENALTY, "辱骂")

    # ---- 恋人达成（首次）→ 触发第二次称呼确认 ----
    user = db.get_user(user_id)
    if user["affection"] >= 75 and not user["lover_confirm"]:
        db.set_lover_confirm(user_id)
