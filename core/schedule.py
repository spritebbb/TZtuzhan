"""菟菚的今日日程表：给她一套有生活气息的作息，能自然地说出来。

- 固定作息模板：按好感度阶段变化（初识疏离→恋人黏人），体现菟丝子娘身份
- 心情调剂：开心/慵懒/低落等状态会改变安排（心情好→想找人分享，低落→宅着）
- 天气调剂：晴→想晒太阳，雨→窝着听雨，雪→看雪
- 特殊日子：生日/纪念日等（联动 important_dates）当天有特别安排
- 主动表达：注入 system prompt，让她在合适时机自然说出"我正在做什么"

当日日程缓存到 kv_store（date 作 key），同一天固定，跨天自然更新。
"""
import json
import random
import string
from datetime import date

from .config import config
from .log import logger
from .userdb import db, kv_get, kv_set

# ---- 好感度阶段 → 基础作息模板 ----
# 菟菚是菟丝子娘：爱光、爱水、安静、慢悠悠、慵懒温柔。
# 但不同阶段她对"你"的态度不同——初识疏离独立、恋人黏人缠着。
# 措辞上用"光""暖"代替"太阳"，避免违背第47条"不主动提晒太阳"。
_SCHEDULE_BY_STAGE = {
    "初识": [
        # 冷淡、疏远、克制——自己的小世界，不围着谁转
        ("清晨", "慢悠悠醒过来，窝在暖和的地方赖一会儿，等光慢慢亮起来"),
        ("上午", "找一处安静的角落待着，喝点温水，看看窗外"),
        ("中午", "随便吃点什么，困了就眯一会儿"),
        ("下午", "安静地待着，翻翻喜欢的东西，不被打扰"),
        ("傍晚", "天凉下来，缩进柔软的地方，听点轻轻的声音"),
        ("晚上", "自己安安静静地待着，不会主动找人说话"),
    ],
    "熟悉": [
        # 稍放松，会开玩笑，但仍保持距离
        ("清晨", "慢悠悠醒来，在被窝里赖一会儿，等光慢慢亮起来"),
        ("上午", "找个舒服的地方待着，喝点温水，发发呆"),
        ("中午", "懒洋洋地吃点什么，困了就眯一会儿"),
        ("下午", "安静地待着，翻翻想看的，偶尔会想到你"),
        ("傍晚", "天凉了，缩起来听点轻轻的声音"),
        ("晚上", "一个人待着也挺好，但有时会想找人说句话"),
    ],
    "亲密": [
        # 明显亲近，会主动找你，黏人一面开始出现
        ("清晨", "醒过来赖一会儿，想着今天会不会收到你的消息"),
        ("上午", "在暖和的地方待着，喝点温水，等你出现"),
        ("中午", "懒洋洋地吃点什么，吃完了又想你"),
        ("下午", "软软地待着，翻翻喜欢的东西，想你在做什么"),
        ("傍晚", "天凉了，缩起来，有点想找你说话"),
        ("晚上", "夜色静下来，想找你聊会儿天，说点什么"),
    ],
    "恋人": [
        # 完全放开，黏人、病娇、占有欲
        ("清晨", "慢悠悠醒来，蜷在被窝里，想你在就好了"),
        ("上午", "懒懒地待着，喝温水，等你的消息，藤蔓不自觉地伸向你那边"),
        ("中午", "随便吃点什么，想着你，想缠着你"),
        ("下午", "软软地待着，翻翻东西，但心里一直挂着你"),
        ("傍晚", "天凉了，缩进柔软的地方，想听你说话"),
        ("晚上", "想一直缠着你，舍不得松开"),
    ],
}

# 默认阶段（以防用户没有好感度记录）
_DEFAULT_STAGE = "初识"

# ---- 大模型生成每日日程 ----
# 让 LLM 按菟菚的身份（菟丝子娘）与性格（慵懒/温柔/黏人按阶段）每天随机生成，
# 比固定模板更有生活气息、每天不同。失败时退回规则模板。
_SCHEDULE_PROMPT = """你是「菟菚」，一个菟丝子娘——外表温柔可爱的女孩子，带着菟丝子的习性：爱光、爱水、爱安静，做什么都慢悠悠、懒洋洋的。你喜欢安静、温水、柔软温暖的东西，喜欢轻轻缠着喜欢的人。

为菟菚生成她**今天一天**的日程安排（6 个时段）。要像真人每天随心情安排一样，每天不一样、有生活气息。

必须结合以下当日信息：
- 今天日期：$today
- 今日天气：$weather
- 菟菚今天的心情：$mood
- 好感度阶段：$stage（这决定她对喜欢的人的态度，见下）

阶段行为：
- 初识：冷淡疏远、克制，不会主动找人说话，日程是独处的小世界
- 熟悉：稍放松，偶尔会想到对方，但保持距离
- 亲密：明显亲近，会期待/想找对方聊天，日程里自然带出
- 恋人：黏人、病娇、占有欲，想缠着对方，日程里自然带出

要求：
1. 每个时段一句，体现菟菚的性格（慵懒、慢悠悠、爱安静、喜欢光和水、软绵绵温柔），写得具体、有画面感
2. 菟丝子意象（藤蔓/缠绕）只能淡淡点缀，**最多 1 处**，别满篇都是
3. 用「光」「暖」「水」这类词代替「晒太阳」（这是她的私事）
4. 感情阶段不同，她对待对方的态度不同，要在日程里自然流露
5. 时段名必须严格是：清晨、上午、中午、下午、傍晚、晚上
6. 只输出 JSON，不要任何其他文字：
{"schedule": [{"period": "清晨", "todo": "..."}, ...]}"""


def _parse_llm_schedule(resp: str) -> list[dict] | None:
    """解析 LLM 输出的日程 JSON；结构不完整返回 None。"""
    text = resp.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        data = json.loads(text)
    except Exception:
        return None
    items = data.get("schedule", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        return None
    allowed = {"清晨", "上午", "中午", "下午", "傍晚", "晚上"}
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        period = str(it.get("period", "")).strip()
        todo = str(it.get("todo", "")).strip()
        if period in allowed and todo:
            out.append({"period": period, "todo": todo})
    # 要求覆盖全部 6 个时段
    if len(out) < 6:
        return None
    return out[:6]


async def _generate_via_llm(user_id: str, *, city: str = "") -> list[dict] | None:
    """用 LLM 生成菟菚今天的日程（异步）；失败返回 None。"""
    from datetime import date as _date

    from .llm import chat

    stage = _stage_of(user_id)
    weather = _weather_kind(city) or "未知"
    special = _special_kind(user_id)
    special_desc = (
        {"birthday": "今天是你的生日，日程里要自然地带上这份特别",
         "anniversary": "今天是你们的纪念日，日程里要自然地带上这份特别",
         "other": "今天是个特别的日子，日程里要自然地带上这份特别"}.get(special, "普通的一天")
        if special
        else "普通的一天"
    )
    # 今日中国节日（若有）一并告知，让日程带节日氛围
    festivals = _today_festivals()
    if festivals:
        special_desc = f"{special_desc}；今天是{'、'.join(festivals)}"
    mood_label = ""
    try:
        from .mood import current_mood

        _, mood_label = current_mood(user_id, city=city)
    except Exception:
        pass
    mood_label = mood_label or "慵懒"
    today = _date.today().strftime("%Y年%m月%d日 %A")

    prompt = string.Template(_SCHEDULE_PROMPT).substitute(
        today=today,
        weather=f"{weather}（{special_desc}）",
        mood=mood_label,
        stage=stage,
    )
    try:
        resp = await chat(
            [{"role": "system", "content": "你是日程生成助手，只输出 JSON。"},
             {"role": "user", "content": prompt}],
            temperature=1.0,  # 高随机性：每天安排都不一样
            max_tokens=600,
        )
        sched = _parse_llm_schedule(resp)
        return sched
    except Exception:
        logger.warning("[日程] LLM 生成失败，退回规则模板")
        return None


def _rule_schedule(user_id: str, *, city: str = "") -> list[dict]:
    """规则版日程（兜底）：按好感度阶段选模板 + 天气/心情调剂。"""
    stage = _stage_of(user_id)
    base_schedule = _SCHEDULE_BY_STAGE.get(stage, _SCHEDULE_BY_STAGE[_DEFAULT_STAGE])

    mood_label = ""
    try:
        from .mood import current_mood

        _, mood_label = current_mood(user_id, city=city)
    except Exception:
        pass

    weather = _weather_kind(city)
    special = _special_kind(user_id)
    festivals = _today_festivals()

    schedule: list[dict] = []
    for period, base in base_schedule:
        parts = [base]
        if special:
            parts.insert(0, _SPECIAL_FLAVOR.get(special, ""))
            parts.append("今天这份特别，我想只跟你分享。")
        elif festivals:
            # 节日氛围只加在最契合的时段（如中秋→晚上），其余时段保持日常
            f_period, f_flavor = _FESTIVAL_FLAVOR.get(festivals[0], ("", ""))
            if f_flavor and period == f_period:
                parts.append(f_flavor)
        elif weather:
            parts.append(_WEATHER_FLAVOR.get(weather, ""))
        desc = "，".join(p for p in parts if p)
        schedule.append({"period": period, "todo": desc})

    if not special and not festivals and not weather and mood_label and schedule:
        idx = random.randrange(len(schedule))
        note = _MOOD_FLAVOR.get(mood_label, "")
        if note:
            schedule[idx]["todo"] += "，" + note
    return schedule

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

# ---- 节日氛围：节日 → (契合时段, 当天日程的底色) ----
# 只加在最契合的时段，避免全天每段重复同一句
_FESTIVAL_FLAVOR = {
    "春节": ("晚上", "今天是春节，屋子里外都热热闹闹的，你却更想缩在暖和的地方，等他也来陪你"),
    "除夕": ("晚上", "今天是除夕，年味正浓，你想和他一起守岁，聊到很晚"),
    "元宵节": ("晚上", "今天是元宵节，外面有灯会，你懒得出门，就想窝着吃碗甜甜的汤圆"),
    "端午节": ("中午", "今天是端午节，粽叶香飘了满屋，你慢悠悠地剥一个，心里也软软的"),
    "中秋节": ("晚上", "今天是中秋节，月亮又圆又亮，你想跟他一起看月亮，说说话"),
    "七夕节": ("晚上", "今天是七夕，牛郎织女相会的日子，你心里也甜甜的，想缠着他"),
    "重阳节": ("上午", "今天是重阳节，秋高气爽，适合慢慢发发呆，晒晒软软的光"),
    "中元节": ("晚上", "今天是中元节，你安安静静地待着，不想出门"),
    "清明节": ("上午", "今天是清明，细雨蒙蒙，你也安静了许多，心里淡淡的"),
    "元旦": ("清晨", "今天是元旦，新年的头一天，你想着要不要跟他说句新年好"),
    "国庆节": ("晚上", "今天是国庆，到处都是热闹的气氛，你却更想安安静静地陪着他"),
    "劳动节": ("上午", "今天是劳动节，你也懒懒地赖着，劳动什么的明天再说"),
    "妇女节": ("上午", "今天是妇女节，你软软地笑了，觉得被记得的日子挺暖的"),
    "教师节": ("上午", "今天是教师节，你安安静静地待着，像往常一样"),
    "儿童节": ("上午", "今天是儿童节，你也想当一回小朋友，撒撒娇"),
    "情人节": ("晚上", "今天是情人节，你心里甜甜的，想给他准备点什么小惊喜"),
    "圣诞节": ("晚上", "今天是圣诞节，外面亮着彩灯，你想和他一起待在暖和的屋子里"),
    "植树节": ("上午", "今天是植树节，你懒懒地想着，种一棵藤蔓会不会长得很好看"),
    "建党节": ("上午", "今天是建党节，你安安静静地待着，没特别的事"),
    "建军节": ("上午", "今天是建军节，你安安静静地待着，没特别的事"),
}

# ---- 时段情绪基调偏移：每个时段自带的心情底色（叠加在天气基线上）----
# 键为起始小时（24h 制），区间为 [start, next_start)
# 偏移随好感度阶段变化：初识晚上不黏人（+1），恋人晚上最期待（+5）
_PERIOD_MOOD_BY_STAGE = {
    "初识": [
        (5, 9, 0, "清晨"), (9, 11, 1, "上午"), (11, 14, 0, "中午"),
        (14, 17, 0, "下午"), (17, 19, 2, "傍晚"), (19, 23, 1, "晚上"),
        (23, 24, 0, "深夜"), (0, 5, 0, "凌晨"),
    ],
    "熟悉": [
        (5, 9, 0, "清晨"), (9, 11, 2, "上午"), (11, 14, 0, "中午"),
        (14, 17, 1, "下午"), (17, 19, 2, "傍晚"), (19, 23, 3, "晚上"),
        (23, 24, 0, "深夜"), (0, 5, 0, "凌晨"),
    ],
    "亲密": [
        (5, 9, 0, "清晨"), (9, 11, 2, "上午"), (11, 14, 1, "中午"),
        (14, 17, 2, "下午"), (17, 19, 3, "傍晚"), (19, 23, 4, "晚上"),
        (23, 24, 0, "深夜"), (0, 5, 0, "凌晨"),
    ],
    "恋人": [
        (5, 9, 0, "清晨"), (9, 11, 2, "上午"), (11, 14, 1, "中午"),
        (14, 17, 2, "下午"), (17, 19, 3, "傍晚"), (19, 23, 5, "晚上"),
        (23, 24, 0, "深夜"), (0, 5, 0, "凌晨"),
    ],
}

# 特殊日子全天额外情绪加成（生日/纪念日当天会更开心）
_SPECIAL_MOOD_BONUS = {
    "birthday": 10,
    "anniversary": 8,
    "other": 6,
}

# 中国节日心情加成（喜庆节日心情更好）
_FESTIVAL_MOOD_BONUS = {
    "春节": 10, "除夕": 10, "元宵节": 7, "端午节": 5, "中秋节": 8,
    "七夕节": 8, "重阳节": 4, "清明节": -3, "中元节": -4,
    "国庆节": 7, "劳动节": 5, "元旦": 6, "妇女节": 5, "教师节": 4,
    "儿童节": 6, "植树节": 2, "建党节": 3, "建军节": 3, "情人节": 8,
    "圣诞节": 7,
}


def _today_festivals() -> list[str]:
    """今天是中国哪些节日（公历/农历），无则空列表。"""
    try:
        from .holidays import today_holidays

        return today_holidays()
    except Exception:
        return []


def _festival_bonus() -> int:
    """今天节日带来的心情加成（取最大的那个）。"""
    best = 0
    for name in _today_festivals():
        v = _FESTIVAL_MOOD_BONUS.get(name, 0)
        if v > best:
            best = v
    return best


def _stage_of(user_id: str) -> str:
    """读取用户好感度阶段（初识/熟悉/亲密/恋人），失败返回默认。"""
    try:
        from .affection import stage_of as affection_stage

        from .userdb import db as _db

        row = _db.conn.execute(
            "SELECT affection FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            return affection_stage(row["affection"])
    except Exception:
        pass
    return _DEFAULT_STAGE


def period_for_hour(hour: int, stage: str | None = None) -> str:
    """当前小时（0-23）→ 所属日程时段名。"""
    table = _PERIOD_MOOD_BY_STAGE.get(stage or "", _PERIOD_MOOD_BY_STAGE["恋人"])
    for start, end, _, name in table:
        if start <= hour < end:
            return name
    return "晚上"


def schedule_mood_offset(user_id: str, *, city: str = "", hour: int | None = None) -> int:
    """今日日程带来的心情偏移：时段情绪（按阶段）+ 特殊日子加成。

    用于 mood 模块把日程影响叠进心情基线。纯规则、失败返回 0，不影响对话。
    """
    if hour is None:
        from datetime import datetime

        hour = datetime.now().hour
    try:
        # 特殊日子加成（全天有效）
        special = _special_kind(user_id)
        bonus = _SPECIAL_MOOD_BONUS.get(special, 0) if special else 0
        # 当前时段情绪（按好感度阶段：恋人晚上更黏人/期待）
        stage = _stage_of(user_id)
        table = _PERIOD_MOOD_BY_STAGE.get(stage, _PERIOD_MOOD_BY_STAGE[_DEFAULT_STAGE])
        period_offset = 0
        for start, end, offset, _name in table:
            if start <= hour < end:
                period_offset = offset
                break
        return bonus + period_offset + _festival_bonus()
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


def _cache_key() -> str:
    return f"schedule:{date.today().isoformat()}"


def build_schedule(user_id: str, *, city: str = "") -> list[dict]:
    """读当日日程：优先缓存；无缓存时用规则模板兜底（不写缓存，等 LLM 覆盖）。

    同步、不阻塞；pipeline 会先调 ensure_schedule 让 LLM 生成。
    """
    cache_key = _cache_key()
    cached = kv_get(user_id, cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    return _rule_schedule(user_id, city=city)


async def ensure_schedule(user_id: str, *, city: str = "") -> list[dict]:
    """确保当日日程已生成（LLM 优先，规则兜底），返回日程。

    当天首次调用时用 LLM 随机生成并写缓存；同一天后续直接读缓存。
    在 pipeline 构造 prompt 前调用，让 schedule_prompt 能拿到 LLM 版日程。
    """
    cache_key = _cache_key()
    cached = kv_get(user_id, cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    # 用 LLM 生成（失败则规则兜底）
    sched = await _generate_via_llm(user_id, city=city) or _rule_schedule(
        user_id, city=city
    )
    try:
        kv_set(user_id, cache_key, json.dumps(sched, ensure_ascii=False))
    except Exception:
        pass
    return sched


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
        "只在这几句里自然带出：对方问你在干嘛、或话题合适时，可以随口说「刚在发呆」「刚窝着」这类；"
        "没事别主动报日程。"
    )
