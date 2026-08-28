"""菟菚的今日日程表：给她一套有生活气息的作息，能自然地说出来。

- 固定作息模板：一天分成几个时段，每个时段有菟菚会做的事
- 心情调剂：开心/慵懒/低落等状态会改变安排（心情好→想找人分享，低落→宅着）
- 天气调剂：晴→想晒太阳，雨→窝着听雨，雪→看雪
- 特殊日子：生日/纪念日等（联动 important_dates）当天有特别安排
- 主动表达：注入 system prompt，让她在合适时机自然说出"我正在做什么"

当日日程缓存到 kv_store（date 作 key），同一天固定，跨天自然更新。
"""
import json
import random
from datetime import date

from .config import config
from .log import logger
from .userdb import db, kv_get, kv_set

# ---- 固定作息模板：时段 → 菟菚会做的事（含慵懒/温柔/菟丝子意象）----
_BASE_SCHEDULE = [
    ("清晨", "慢悠悠醒来，窝在被子里赖一会儿，等太阳暖起来"),
    ("上午", "晒会儿太阳，软软地发发呆，看看窗外"),
    ("中午", "懒洋洋的，随便吃点什么，困了就眯一会儿"),
    ("下午", "安静地待着，翻翻想看的，偶尔想想你"),
    ("傍晚", "天变凉了，缩起来，听点喜欢的音乐"),
    ("晚上", "窝在舒适的角落，想跟你多说会儿话"),
]

# ---- 心情调剂：心情状态 → 给某一段补充的"当日心情基调"（独立短句，不与基础重复）----
_MOOD_FLAVOR = {
    "低落": "不过今天心里有点闷，做什么都提不起劲",
    "平淡": "日子平平淡淡的，慢慢过就好",
    "慵懒": "整个人懒懒的，能躺着就不坐着，舒服最重要",
    "开心": "心里挺高兴的，做什么都有点轻快",
    "雀跃": "今天心情特别好，像裹着一层软绵绵的光",
}

# ---- 天气调剂：天气关键词 → 日程细节 ----
_WEATHER_FLAVOR = {
    "晴": "阳光很好，想多晒一会儿，被晒得暖洋洋的",
    "多云": "云朵慢慢飘，温度正好，适合安静待着",
    "阴": "天阴阴的，整个人也懒懒的，适合窝着",
    "雨": "下雨了，趴在窗边听雨，凉凉的软软的",
    "雪": "下雪啦，想看雪，雪花凉丝丝的很安静",
    "风": "起风了，缩成一团，听着风声发呆",
    "雾": "雾蒙蒙的，整个世界都静下来了",
    "雷": "打雷了，有点怕，缩紧一点，想离你近点",
    "沙尘": "风沙大，门窗关紧，想找个暖和的地方窝着",
    "霾": "天灰灰的，没什么精神，就想安静躺着",
}

# ---- 特殊日子安排：kind → 当天特别做的事 ----
_SPECIAL_FLAVOR = {
    "birthday": "今天是你的生日，我心里记着这个日子，想送你点特别的",
    "anniversary": "今天是我们的纪念日，是个特别的日子，想跟你一起记得",
    "other": "今天是个特别的日子，想做点跟平时不一样的事",
}

# ---- 时段情绪基调偏移：每个时段自带的心情底色（叠加在天气基线上）----
# 键为起始小时（24h 制），区间为 [start, next_start)
_PERIOD_MOOD = [
    (5, 9, 0, "清晨"),      # 清晨：刚醒，慵懒平和
    (9, 11, 2, "上午"),     # 上午：晒太阳发呆，安静舒适
    (11, 14, 0, "中午"),    # 中午：懒洋洋
    (14, 17, 1, "下午"),    # 下午：安静待着，偶尔想想你
    (17, 19, 3, "傍晚"),    # 傍晚：听音乐，放松
    (19, 23, 5, "晚上"),    # 晚上：想陪你，期待/黏人
    (23, 24, 0, "深夜"),    # 深夜：困了，安静
    (0, 5, 0, "凌晨"),      # 凌晨：睡着了/安静
]

# 特殊日子全天额外情绪加成（生日/纪念日当天会更开心）
_SPECIAL_MOOD_BONUS = {
    "birthday": 10,
    "anniversary": 8,
    "other": 6,
}


def period_for_hour(hour: int) -> str:
    """当前小时（0-23）→ 所属日程时段名。"""
    for start, end, _, name in _PERIOD_MOOD:
        if start <= hour < end:
            return name
    return "晚上"


def schedule_mood_offset(user_id: str, *, city: str = "", hour: int | None = None) -> int:
    """今日日程带来的心情偏移：时段情绪 + 特殊日子加成。

    用于 mood 模块把日程影响叠进心情基线。纯规则、失败返回 0，不影响对话。
    """
    if hour is None:
        from datetime import datetime

        hour = datetime.now().hour
    try:
        # 特殊日子加成（全天有效）
        special = _special_kind(user_id)
        bonus = _SPECIAL_MOOD_BONUS.get(special, 0) if special else 0
        # 当前时段情绪
        period_offset = 0
        for start, end, offset, _name in _PERIOD_MOOD:
            if start <= hour < end:
                period_offset = offset
                break
        return bonus + period_offset
    except Exception:
        return 0


def _weather_kind(city: str) -> str:
    """取当日天气关键词（用于调剂），无城市返回空。"""
    if not city:
        return ""
    try:
        from .mood import today_weather

        weather, _ = today_weather(city)
        return weather
    except Exception:
        return ""


def _special_kind(user_id: str) -> str | None:
    """今日若是特殊日子，返回 kind（birthday/anniversary/other）；无则 None。"""
    try:
        from .userdb import get_today_important_dates

        today = date.today().strftime("%m-%d")
        rows = get_today_important_dates(user_id)
        if rows:
            return rows[0]["kind"] or "other"
    except Exception:
        pass
    return None


def build_schedule(user_id: str, *, city: str = "") -> list[dict]:
    """生成菟菚今天的日程表：[(时段, 事项)]，一次性生成并缓存。"""
    today = date.today()
    cache_key = f"schedule:{today.isoformat()}"
    cached = kv_get(user_id, cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    # 读取当天心情（用于调剂）
    mood_val = 60
    mood_label = ""
    try:
        from .mood import current_mood

        mood_val, mood_label = current_mood(user_id, city=city)
    except Exception:
        pass

    weather = _weather_kind(city)
    special = _special_kind(user_id)

    schedule: list[dict] = []
    for period, base in _BASE_SCHEDULE:
        # 基础作息本身每段就不同（清晨/上午/中午…各有安排），这是"固定模板"
        parts = [base]
        # 特殊日子优先（当天最有意义，替换/强化整天的基调）
        if special:
            parts.insert(0, _SPECIAL_FLAVOR.get(special, ""))
            parts.append("今天这份特别，我想只跟你分享。")
        # 天气调剂：全天都有同一种天气氛围（如下雨→都听着雨），叠在后
        elif weather:
            parts.append(_WEATHER_FLAVOR.get(weather, ""))
        # 心情调剂：只在最后一段点缀一句（避免每段重复，保留日常差异感）
        desc = "，".join(p for p in parts if p)
        schedule.append({"period": period, "todo": desc})

    # 心情调剂：在无特殊/无天气时，给某一段（随机挑）加一句心情点缀，其余保留日常
    if not special and not weather and mood_label and schedule:
        idx = random.randrange(len(schedule))
        note = _MOOD_FLAVOR.get(mood_label, "")
        if note:
            schedule[idx]["todo"] += "，" + note

    try:
        kv_set(user_id, cache_key, json.dumps(schedule, ensure_ascii=False))
    except Exception:
        pass
    return schedule


def describe(user_id: str, *, city: str = "") -> str:
    """返回今日日程表的自然描述（供 /日程 命令与调试）。"""
    schedule = build_schedule(user_id, city=city)
    lines = []
    weather = _weather_kind(city)
    head = "今天我是这样安排哒"
    if weather:
        head += f"（外面：{weather}）"
    lines.append(head)
    for s in schedule:
        lines.append(f"{s['period']}：{s['todo']}")
    return "\n".join(lines)


def schedule_prompt(user_id: str, *, city: str = "") -> str:
    """生成注入 system prompt 的日程描述（简短、自然，让菟菚能随口提到）。"""
    schedule = build_schedule(user_id, city=city)
    if not schedule:
        return ""
    # 挑 1-2 个特别点的时段提一句，其余概述，别太长
    picks = schedule[:3]
    seg = "；".join(f"{s['period']}想{s['todo'][:30]}" for s in picks)
    return (
        "**你今天的日常（心里有数就行，别主动逐条汇报）**："
        f"{seg}……后面的随心情来。"
        "只在这几句里自然带出：对方问你在干嘛、或话题合适时，可以随口说「我刚在晒太阳」「刚发完呆」这类；"
        "没事别主动报日程。"
    )
