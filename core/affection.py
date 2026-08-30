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

# ---- v3 新增互动触发（好感度深化：更多真实感触发事件）----
APOLOGY_BONUS = 2             # 用户真诚道歉（每日上限1次，抵消前扣分）
SHARING_BONUS = 1             # 用户主动分享心事/烦恼/秘密（每日上限1次）
COMPLIMENT_BONUS = 1          # 用户夸菟菚（每日上限1次）
GAME_PLAY_BONUS = 1           # 用户陪菟菚玩小游戏（每日上限1次）

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
    "傻逼", "煞笔", "沙比", "废物", "去死", "贱人", "畜生",
    "脑残", "智障", "滚蛋", "cnm", "草泥马",
]

# 可能误伤的常用词（如「爬」匹配「爬山」、「垃圾」匹配「垃圾分类」）：命中时需排除
_ABUSE_WORDS_NEED_CONTEXT = {
    "垃圾": ("垃圾分类", "垃圾处理", "垃圾回收", "垃圾袋", "垃圾堆"),
    "恶心": ("吃多了", "有点恶心", "恶心的"),
    "妈的": ("他妈", "你妈"),
}

# 英文辱骂词（词界匹配，避免「asb」「sbxi」等子串误伤）
_ABUSE_EN_WORDS = ("sb", "cnm", "fuck", "shit", "bitch")

# 辱骂词指向"别人"时的对象词：当辱骂词和目标对象词同时出现，判断不是在骂菟菚。
# 例子：「傻逼领导」「妈的，那领导...」「sb同事」——骂的是对方，不该扣菟菚好感。
# 注意：不放单字「他/她/它/这/那」（太常见，会误伤「他妈的」这类真粗口/对菟菚的辱骂）。
_ABUSE_OTHER_TARGET = (
    "领导", "老板", "老师", "同事", "同学", "他们", "她们",
    "主任", "经理", "主管", "组长", "班长", "这货", "那货", "这家伙",
    "学校", "公司", "单位", "客户", "甲方", "客服", "boss", "leader", "sb领导", "sb同事",
)


def check_abuse(text: str) -> bool:
    lowered = text.lower()
    # ① 若辱骂词指向的是"别人"（骂的对象不是菟菚），不判为辱骂菟菚。
    #    规则：整个消息里同时出现了辱骂词 + 其他对象词 → 视为在骂别人，跳过。
    #    注意：不能只看辱骂词后面，因「傻逼领导」「他妈的」顺序可能相反或跨句。
    if any(t in lowered for t in _ABUSE_OTHER_TARGET):
        return False
    # ② 中文多字词：命中即算，但对易误伤词检查上下文白名单
    for w in ABUSE_WORDS:
        if w in lowered and not any(b in lowered for b in _ABUSE_WORDS_NEED_CONTEXT.get(w, ())):
            return True
    # ③ 英文词：词界匹配，避免子串误伤
    import re

    for w in _ABUSE_EN_WORDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", lowered):
            return True
    return False

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
# 刷屏已罚标记：同一突发窗口内只罚一次，避免连续扣分
_spam_triggered: set[str] = set()


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


def check_bad_address(name: str) -> bool:
    """判断是否为不合适的称呼（侮辱类 / 失当亲属称谓）。"""
    return any(w in name for w in BAD_ADDRESS_WORDS)


def check_early_confession(text: str) -> bool:
    """判断是否为过早的表白/求婚（初识/熟悉阶段触发拒绝）。

    排除否定式误判：「我不喜欢你」「别喜欢我」等不应算表白。
    """
    if not any(w in text for w in EARLY_CONFESSION_WORDS):
        return False
    # 命中词前有否定词 → 不是表白（「不/别/没/不想」）
    import re

    for w in EARLY_CONFESSION_WORDS:
        idx = text.find(w)
        if idx < 0:
            continue
        before = text[max(0, idx - 4):idx]
        if any(neg in before for neg in ("不", "别", "没", "不想", "别想", "才不")):
            continue
        return True
    return False


def check_care(text: str) -> bool:
    """判断用户是否在关心菟菚。"""
    lowered = text.lower()
    return any(w in lowered for w in CARE_WORDS)


# 用户道歉/求原谅（修复关系，抵消前扣分）
APOLOGY_WORDS = [
    "对不起", "抱歉", "是我的错", "我错了", "原谅我", "别生气", "我不好",
    "是我不好", "向你道歉", "对不起啦", "别不理我", "我知道错了", "我再也不了",
    "我反省", "我不该", "下次不会了", "别生我的气",
]

# 用户主动分享心事/烦恼/秘密（走心互动）
SHARING_WORDS = [
    "跟你说个事", "告诉你一个秘密", "告诉你个秘密", "跟你讲讲", "我最近有点烦",
    "我心里难受", "悄悄告诉你", "想跟你说说", "跟你倾诉", "跟你说心里话",
    "跟你讲个事", "跟你说说心里话", "跟你说点心里话", "跟你说件", "跟你聊聊最近",
]

# 用户夸菟菚
COMPLIMENT_WORDS = [
    "你好可爱", "你好温柔", "你真棒", "你好漂亮", "你真贴心", "喜欢你这样",
    "你真好", "你最好了", "你好懂我", "你太会了", "被你暖到", "你治愈",
    "你好乖", "你好香", "你好会说话",
]


def check_apology(text: str) -> bool:
    """判断用户是否在道歉/求原谅。"""
    lowered = text.lower()
    return any(w in lowered for w in APOLOGY_WORDS)


def check_sharing(text: str) -> bool:
    """判断用户是否在主动分享心事/秘密。"""
    lowered = text.lower()
    return any(w in lowered for w in SHARING_WORDS)


def check_compliment(text: str) -> bool:
    """判断用户是否在夸菟菚。"""
    lowered = text.lower()
    return any(w in lowered for w in COMPLIMENT_WORDS)


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
    if len(q) >= _SPAM_MAX_COUNT:
        if user_id in _spam_triggered:
            return False  # 同一突发窗口内已罚过，不再重复扣
        _spam_triggered.add(user_id)
        return True
    # 窗口已清 → 清除标记，下次突发可重新触发
    _spam_triggered.discard(user_id)
    return False


def _cleanup_timestamps() -> None:
    """定期清理不活跃用户的刷屏时间戳（避免内存无界增长）。"""
    now = datetime.now().timestamp()
    stale = [uid for uid, q in list(_timestamps.items()) if not q or now - q[-1] > 3600]
    for uid in stale:
        _timestamps.pop(uid, None)
        _spam_triggered.discard(uid)


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

    # 定期清理不活跃用户的时间戳（每 50 条消息检查一次）
    if len(_timestamps) > 1000:
        _cleanup_timestamps()

    # ---- 心情更新：用户消息影响菟菚心情（有趣→升，冒犯→降）----
    # 注意：_mood_on_msg 内部会访问 db（主线程创建的连接），不能整函数丢进线程池
    #（否则跨线程 sqlite 崩溃）。只把网络部分（天气获取）预热到线程池，命中日缓存后
    # 主线程调用 _mood_on_msg 不再阻塞事件循环。
    import asyncio as _asyncio
    from .mood import on_user_message as _mood_on_msg, mood_bonus_multiplier, today_weather as _today_weather
    from .config import config

    _mood_city = config.mood_city
    try:
        if _mood_city:
            await _asyncio.to_thread(_today_weather, _mood_city)  # 预热天气（日缓存，通常已命中）
    except Exception:
        pass

    mood = _mood_on_msg(user_id, text, city=_mood_city)
    # 心情 → 好感度变动倍率（心情好加分多、扣分少；心情差反之）
    mult = mood_bonus_multiplier(mood)

    def _scale_delta(delta: int) -> int:
        """按心情倍率缩放一个变动值（不落库，供检查/落库复用）。"""
        if delta >= 0:
            return round(delta * mult)
        # 心情差时扣分更狠：低落(0.6) → 扣分×1.4；雀跃(1.5) → 扣分×0.5
        return round(delta * (2.0 - mult))

    def _scaled(delta: int, reason: str) -> int:
        """按心情倍率缩放好感度变动并落库，返回实际 delta（0 表示不变动）。"""
        scaled = _scale_delta(delta)
        if scaled != 0:
            db.update_affection(user_id, scaled, reason)
        return scaled

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
                db.set_chat_date(user_id, today.isoformat())  # 只设 last_chat_date，batch 标记由 run_daily_batch 执行后完成
            else:
                db.set_chat_date(user_id, today.isoformat())
        else:
            db.set_chat_date(user_id, today.isoformat())

        # 每日首次和陪伴奖励：用 kv_store 防重复
        if not _daily_bonus_done(user_id, "first_chat"):
            _scaled(DAY_FIRST_BONUS, "每日首次聊天")
            _scaled(DAILY_COMPANION, "当日陪伴")
            _mark_daily_bonus(user_id, "first_chat")

    # ---- 即时扣分（含每日上限检查；用缩放后的实际 delta 判断，避免心情差时超限）----
    if _spam_hit(user_id):
        actual = _scale_delta(SPAM_PENALTY)
        if _penalty_ok(user_id, actual):
            _scaled(SPAM_PENALTY, "刷屏")
    if check_abuse(text):
        actual = _scale_delta(ABUSE_PENALTY)
        if _penalty_ok(user_id, actual):
            _scaled(ABUSE_PENALTY, "辱骂")

    # ---- 恋人达成（首次）→ 触发第二次称呼确认 ----
    user = db.get_user(user_id)
    if user["affection"] >= 75 and not user["lover_confirm"]:
        db.set_lover_confirm(user_id)
