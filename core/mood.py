"""心情系统：菟菚的心情值 0-100，随天气、时间、互动自然变化。

- 心情值 mood：0-100，初始 60。映射为情绪状态（低落/平淡/慵懒/开心/雀跃）。
- 天气影响：每日通过搜索/天气 API 获取当日天气，设置当日心情基线。
- 小时波动：心情随时间缓慢漂移（向基线回归 + 随机扰动），模拟真人情绪起伏。
- 互动影响：用户讲趣事/关心 → 回升；冒犯/冷落/刷屏 → 下降。
- 影响好感度：心情好时互动加分更多，心情差时更容易扣分（由 affection 读取）。
"""
import random
import re
from datetime import date, datetime, timedelta

from .log import logger

# ---- 心情映射 ----
MOOD_LEVELS = (
    (0, "低落", "心情很差，有点烦闷，说话会短、懒，容易不耐烦"),
    (25, "平淡", "心情一般，不悲不喜，说话平静、有条理"),
    (45, "慵懒", "安安静静、懒洋洋的，带一点软绵绵的温柔"),
    (65, "开心", "心情不错，说话轻快，偶尔俏皮、爱开玩笑"),
    (85, "雀跃", "心情非常好，活泼、黏人，想找人分享开心的事"),
)

# ---- 天气 → 心情基线映射 ----
_WEATHER_BASE = {
    "晴": 75, "多云": 68, "阴": 52, "雨": 45, "雪": 62,
    "风": 58, "雾": 50, "雷": 40, "沙尘": 38, "霾": 42,
}


def mood_label(mood: int) -> tuple[str, str]:
    """心情值 → (状态名, 描述)。"""
    name, desc = MOOD_LEVELS[0][1], MOOD_LEVELS[0][2]
    for threshold, n, d in MOOD_LEVELS:
        if mood >= threshold:
            name, desc = n, d
    return name, desc


def weather_baseline(weather: str) -> int:
    """天气关键词 → 心情基线（0-100）。未知天气返回 None（用默认基线）。"""
    for kw, base in _WEATHER_BASE.items():
        if kw in weather:
            return base
    return None


# ---- 小时波动：向基线回归 + 随机扰动 ----
def _drift(mood: int, baseline: int, hours_since_update: float) -> int:
    """按经过的小时数让心情向基线回归，并加一点随机扰动。"""
    # 回归力度：每小时向基线靠 8%（越久越靠拢）
    pull = (baseline - mood) * min(1.0, 0.08 * hours_since_update)
    # 随机扰动：每小时 ±3，随时间累积
    noise = random.uniform(-3, 3) * min(1.0, hours_since_update)
    new_mood = mood + pull + noise
    return max(0, min(100, round(new_mood)))


# ---- 互动检测 ----
# 有趣的事/让菟菚开心的内容
_FUN_RE = re.compile(r"(好笑|哈哈|笑死|太逗|有趣|好玩|梗|笑不活|绷不住|乐了|笑鼠|整活)")
# 关心/温暖的话
_CARE_RE = re.compile(r"(你还好吗|你没事吧|累不累|辛苦了|你也要休息|照顾好自己|别太累|担心你|想你|想你了|抱抱|摸摸)")
# 冒犯/让菟菚不舒服的话（辱骂、轻视、命令口吻）
_BAD_RE = re.compile(r"(傻逼|煞笔|沙比|废物|垃圾|去死|贱人|畜生|脑残|智障|滚|sb|SB|cnm|恶心|爬|真没意思|无聊死了)")
# 分享开心的事（好消息、成就、喜欢的东西）
_GOOD_NEWS_RE = re.compile(r"(升职|加薪|考上了|成功|中了|赢|过啦|通过了|第一次|今天好开心|超喜欢|好高兴|太好啦|太好了)")


def mood_delta_from_text(text: str) -> int:
    """根据用户这句话判断心情增减（正=回升，负=下降）。返回调整量。"""
    t = text or ""
    delta = 0
    if _BAD_RE.search(t):
        delta -= 12  # 冒犯/辱骂：骤降
    if _FUN_RE.search(t):
        delta += 4  # 有趣的事：回升
    if _GOOD_NEWS_RE.search(t):
        delta += 5  # 分享好消息：明显回升
    if _CARE_RE.search(t):
        delta += 3  # 关心菟菚：回升
    return delta


def idle_decay(hours_idle: float) -> int:
    """被冷落的时间越长，心情越低落（每小时 -0.5，封顶 -15）。"""
    return -min(15, round(hours_idle * 0.5))


# ---- 天气获取（搜索优先，免费 API 备用）----
_WEATHER_CACHE: dict[str, tuple[date, str, int]] = {}  # user_id → (date, weather, baseline)


def _weather_via_search(city: str) -> str | None:
    """用现成搜索查今日天气，返回天气描述（如「晴」）；失败返回 None。"""
    try:
        from .search import web_search

        results = web_search(f"{city} 今天 天气", max_results=3)
        for r in results:
            text = (r.get("snippet") or "") + " " + (r.get("title") or "")
            for kw in _WEATHER_BASE:
                if kw in text:
                    return kw
    except Exception:
        pass
    return None


def _weather_via_wttr(city: str) -> str | None:
    """备用：用免费 wttr.in 天气 API 拉当日天气（无需 key）。"""
    try:
        import urllib.parse
        import urllib.request

        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=3&lang=zh"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            line = resp.read().decode("utf-8", "ignore")
        # 形如 "北京: ⛅ 多云, +25°C" 或 "襄阳: 🌦️  +31°C"
        for kw in _WEATHER_BASE:
            if kw in line:
                return kw
        # emoji 映射（wttr.in 常用）
        emoji_map = {
            "☀": "晴", "🌞": "晴", "🌤": "晴", "🌣": "晴",
            "⛅": "多云", "🌥": "多云", "☁": "多云", "🌦": "雨",
            "🌧": "雨", "⛈": "雷", "🌨": "雪", "❄": "雪", "🌬": "风",
            "🌫": "雾", "🌪": "风", "☔": "雨",
        }
        for emoji, kw in emoji_map.items():
            if emoji in line:
                return kw
        # 英文关键词兜底
        low = line.lower()
        if "sunny" in low or "clear" in low:
            return "晴"
        if "cloud" in low or "overcast" in low:
            return "多云"
        if "rain" in low or "drizzle" in low or "shower" in low:
            return "雨"
        if "snow" in low or "blizzard" in low:
            return "雪"
        if "thunder" in low or "storm" in low:
            return "雷"
        if "fog" in low or "mist" in low:
            return "雾"
        if "wind" in low:
            return "风"
    except Exception:
        pass
    return None


def today_weather(city: str) -> tuple[str, int]:
    """获取今日天气与心情基线：搜索优先 → wttr.in 备用 → 时间基线兜底。

    返回 (天气描述, 心情基线)。结果缓存当天，避免反复请求。
    """
    today = date.today()
    cached = _WEATHER_CACHE.get(city)
    if cached and cached[0] == today:
        return cached[1], cached[2]

    weather = _weather_via_search(city) or _weather_via_wttr(city)
    if weather:
        base = weather_baseline(weather)
        if base is not None:
            _WEATHER_CACHE[city] = (today, weather, base)
            return weather, base

    # 兜底：按时间段/季节给一个温和基线
    hour = datetime.now().hour
    if 5 <= hour < 11:
        base = 62
    elif 11 <= hour < 14:
        base = 68
    elif 14 <= hour < 18:
        base = 70
    elif 18 <= hour < 23:
        base = 66
    else:
        base = 55
    _WEATHER_CACHE[city] = (today, "未知", base)
    return "未知", base


# ---- 心情状态机：连接天气基线 / 日程情绪 / 小时漂移 / 互动 / 好感度联动 ----
def _baseline_for(city: str, user_id: str = "") -> int:
    """当日心情基线（天气 + 今日日程时段情绪 + 特殊日子加成）。"""
    _, base = today_weather(city)
    # 叠加上今日日程带来的情绪偏移（时段 + 特殊日子），让"日程影响心情"
    if user_id:
        try:
            from .schedule import schedule_mood_offset

            base += schedule_mood_offset(user_id, city=city)
        except Exception:
            pass
    return max(0, min(100, base))


def current_mood(user_id: str, *, city: str = "") -> tuple[int, str]:
    """读取用户当前心情（应用小时漂移 + 日程时段切换校正 + 特殊日子加成后），返回 (心情值, 状态名)。

    自动按上次更新时间做漂移回归；若跨了日程时段（如下午→晚上），
    按时段情绪差即时校正心情；今日有特殊日子（生日/纪念日）且上次心情
    更新不在今天时，一次性加上当日加成——让"日程影响心情"立即可感。
    """
    from .userdb import db

    mood, updated = db.get_mood(user_id)
    baseline = _baseline_for(city, user_id) if city else 60

    # 特殊日子/节日当日加成：今日有特殊日子或节日且上次心情更新不是今天 → 一次性加上
    if city:
        try:
            from .schedule import _FESTIVAL_MOOD_BONUS, _SPECIAL_MOOD_BONUS, _special_kind
            from .holidays import today_holidays

            special = _special_kind(user_id)
            bonus = _SPECIAL_MOOD_BONUS.get(special, 0) if special else 0
            # 节日加成：取今天节日里心情加成最大的那个
            for name in today_holidays():
                v = _FESTIVAL_MOOD_BONUS.get(name, 0)
                if v > bonus:
                    bonus = v
            if bonus:
                last_date = None
                if updated:
                    try:
                        last_date = datetime.fromisoformat(updated).date()
                    except Exception:
                        pass
                if last_date != date.today():
                    mood = max(0, min(100, mood + bonus))
                    db.set_mood(user_id, mood)
        except Exception:
            pass

    if updated:
        try:
            last = datetime.fromisoformat(updated)
            now = datetime.now()
            hours = (now - last).total_seconds() / 3600

            # 日程时段切换校正：上次更新的时段 ≠ 现在时段 → 按情绪差即时调整
            if city:
                try:
                    from .schedule import schedule_mood_offset

                    old_off = schedule_mood_offset(user_id, city=city, hour=last.hour)
                    new_off = schedule_mood_offset(user_id, city=city, hour=now.hour)
                    if new_off != old_off:
                        mood = max(0, min(100, mood + (new_off - old_off)))
                        db.set_mood(user_id, mood)
                except Exception:
                    pass

            if hours > 0.25:  # 超过 15 分钟才漂移
                mood = _drift(mood, baseline, hours)
                db.set_mood(user_id, mood)
        except Exception:
            pass
    label, _ = mood_label(mood)
    return mood, label


def update_mood(user_id: str, delta: int, *, city: str = "") -> int:
    """按互动结果增减心情值，返回更新后的心情值。"""
    from .userdb import db

    mood, _ = current_mood(user_id, city=city)
    new_mood = max(0, min(100, mood + delta))
    db.set_mood(user_id, new_mood)
    return new_mood


def on_user_message(user_id: str, text: str, *, city: str = "") -> int:
    """用户每发一条消息时更新心情：应用互动检测 + 自然波动，返回新心情值。

    先按"上次聊天距今多久"算冷落衰减（长时间没聊 → 心情先降），
    再叠加本条消息的互动影响（有趣→升、冒犯→降）。
    """
    # 冷落衰减：距上次消息超过 12 小时开始掉心情
    from .userdb import db

    try:
        last_ts = db.last_message_ts(user_id)
        if last_ts:
            last = datetime.fromisoformat(last_ts)
            hours_idle = (datetime.now() - last).total_seconds() / 3600
            if hours_idle > 12:
                update_mood(user_id, idle_decay(hours_idle), city=city)
    except Exception:
        pass
    delta = mood_delta_from_text(text)
    return update_mood(user_id, delta, city=city)


def describe(user_id: str, *, city: str = "") -> str:
    """返回心情状态描述（含天气基线说明），供 /心情 命令与调试。"""
    from .userdb import db

    mood, _ = current_mood(user_id, city=city)
    label, desc = mood_label(mood)
    weather = ""
    if city:
        w, base = today_weather(city)
        weather = f"（今日天气：{w}，基线 {base}）"
    bar_amt = mood // 10
    bar = "█" * bar_amt + "░" * (10 - bar_amt)
    return f"心情 {mood} · {label}{weather}\n{bar}\n{desc}"


def mood_bonus_multiplier(mood: int) -> float:
    """心情 → 好感度增减倍率：心情好加分更多，心情差更容易扣分。

    - 雀跃(85+)：好感度变动 ×1.5（加多扣少）
    - 开心(65+)：×1.2
    - 正常(45+)：×1.0
    - 平淡(25+)：×0.8
    - 低落(<25)：×0.6（加分少，且容易触发额外扣分）
    """
    if mood >= 85:
        return 1.5
    if mood >= 65:
        return 1.2
    if mood >= 45:
        return 1.0
    if mood >= 25:
        return 0.8
    return 0.6
