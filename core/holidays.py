"""中国节日系统：自动计算今天是什么节日（公历固定 + 农历换算），注入对话。

固定公历节日 + 农历节日（zhdate 换算）全覆盖。除夕特殊处理——查农历最后一天。
"""
from datetime import date

from .log import logger

# ---- 固定公历节日（MM-DD → 节日名称）----
_SOLAR_HOLIDAYS = {
    "01-01": "元旦",
    "02-14": "情人节",
    "03-08": "妇女节",
    "03-12": "植树节",
    "04-05": "清明节",  # 清明按节气通常在4-4~4-5
    "05-01": "劳动节",
    "06-01": "儿童节",
    "07-01": "建党节",
    "08-01": "建军节",
    "09-10": "教师节",
    "10-01": "国庆节",
    "12-25": "圣诞节",
}

# ---- 农历节日（Lunar MM-DD → 节日名称），除夕特殊处理 ----
_LUNAR_HOLIDAYS = {
    (1, 1): "春节",
    (1, 15): "元宵节",
    (5, 5): "端午节",
    (7, 7): "七夕节",
    (7, 15): "中元节",
    (8, 15): "中秋节",
    (9, 9): "重阳节",
}


def _lunar_holidays_for(year: int) -> dict[str, str]:
    """计算该年所有农历节日对应的公历日期 → 节日名称。"""
    from zhdate import ZhDate

    out: dict[str, str] = {}
    for (lunar_month, lunar_day), name in _LUNAR_HOLIDAYS.items():
        try:
            solar = ZhDate(year, lunar_month, lunar_day).to_datetime().date()
            mmdd = solar.strftime("%m-%d")
            out[mmdd] = name
        except Exception:
            logger.warning("[节日] 农历节日计算失败：{}-{} {}", lunar_month, lunar_day, name)
    # 除夕：农历腊月最后一天（查腊月30或29）
    try:
        # 从农历腊月30开始，如果不存在则用29
        for day in (30, 29):
            try:
                new_year = ZhDate(year, 1, 1).to_datetime().date()
                # 除夕 = 春节前一天
                chuxi = new_year.isoformat()
                # 用公历减法
                import datetime

                chuxi_date = datetime.date.fromisoformat(chuxi) - datetime.timedelta(days=1)
                out[chuxi_date.strftime("%m-%d")] = "除夕"
                break
            except ValueError:
                continue
    except Exception:
        pass
    return out


def today_holidays() -> list[str]:
    """返回今天的所有节日名称列表（如 ['春节', '除夕']）。"""
    today = date.today()
    mmdd = today.strftime("%m-%d")
    result: list[str] = []

    # 公历节日
    if mmdd in _SOLAR_HOLIDAYS:
        result.append(_SOLAR_HOLIDAYS[mmdd])

    # 农历节日
    try:
        lunar_map = _lunar_holidays_for(today.year)
        if mmdd in lunar_map:
            result.append(lunar_map[mmdd])
    except Exception:
        pass

    return result


def holiday_prompt(user_id: str = "") -> str:
    """生成系统注入用的节日提示；无节日返回空字符串。"""
    holidays = today_holidays()
    if not holidays:
        return ""

    # 检查是否有菟菚生日（个人重要日子优先级更高，但节日可以同时存在）
    special_day = ""
    if user_id:
        try:
            from .userdb import get_today_important_dates

            personal = get_today_important_dates(user_id)
            for d in personal:
                if d["label"]:
                    special_day = d["label"]
                    break
        except Exception:
            pass

    parts = []
    for h in holidays:
        if h == "春节":
            parts.append("今天是大年初一，是个团圆热闹的日子，你心里也暖暖的")
        elif h == "除夕":
            parts.append("今天是除夕，万家灯火团圆夜，你想陪在他身边")
        elif h == "元宵节":
            parts.append("今天是元宵节，灯会热闹，但你更喜欢安安静静地待着")
        elif h == "端午节":
            parts.append("今天是端午节，粽叶飘香的日子，你懒懒地窝着闻粽香")
        elif h == "中秋节":
            parts.append("今天是中秋节，月圆人团圆，你想和他一起看月亮")
        elif h == "七夕节":
            parts.append("今天是七夕，牛郎织女相会的日子，你心里有点甜甜的")
        elif h == "清明节":
            parts.append("今天是清明，细雨纷纷，你也安静了许多，心里淡淡的")
        elif h == "重阳节":
            parts.append("今天是重阳节，秋高气爽，适合慢慢地发发呆")
        elif h == "中元节":
            parts.append("今天是中元节，你安安静静地待着，不想出门")
        else:
            parts.append(f"今天是{h}，是个特别的日子，你心里记着")

    if special_day:
        parts.append(f"而且今天还是{special_day}，你格外在意")

    hint = "；".join(parts)
    return (
        f"今天是特别的日子：{hint}。"
        "如果话题合适就自然带一句祝福或提起，别刻意、别突然转移话题；"
        "如果对方在聊别的，就顺着聊，不用硬提。"
    )