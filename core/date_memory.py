"""特殊日子记忆：在日常对话里自动识别并记住用户的重要日子（生日/纪念日等）。

识别时机：
- pipeline.process 每轮：检测用户这句是否在告知/约定某个特殊日子，是则提取入库
- daily.extract_facts：复盘当天对话，从整段里识别补录（兜底）

不依赖 /日子 指令；/日子 命令保留为手动查看/删除用。
"""
import json
import re
from datetime import date

from .llm import chat
from .log import logger
from .userdb import save_important_date

# 单句识别：判断用户这句是否在明确定义一个能记住的日子
DETECT_PROMPT = """你是「菟菚」的记忆助手。判断下面这句用户的话，是不是【明确告知或约定了一个值得记住的日子】：
- 明确的日子：生日、纪念日、约定哪天见面/去哪儿、某件重要事情的日子等
- 不算：随口闲聊提到日期、问时间、回忆过去但不指向固定日期的、模糊的"改天/下次/以后"
如果是，提取该日子的信息；如果不是，dates 返回空数组。

只输出 JSON，不要其他文字：
{"dates": [{"date": "MM-DD", "label": "简短名称", "kind": "birthday|anniversary|other", "year": 年份或null}]}

规则：
- date 必须是 "MM-DD" 两位格式（如 "05-20"）
- label 要像菟菚会说的话（如 "你的生日" / "你们认识的日子" / "约好去看海的日子"）
- year：只在用户明确说出完整年份时才填，否则 null（每年都会过）
- 用户说相对日期（如下个月/下周/后天）时，结合「今天日期」推算成具体 MM-DD，但只有含义明确才记
- 一句话最多 2 个日子，没有就 {"dates": []}"""


def _parse_dates(resp: str) -> list[dict]:
    text = resp.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    dates = data.get("dates", []) if isinstance(data, dict) else []
    out = []
    for d in dates:
        if not isinstance(d, dict):
            continue
        mm = re.match(r"^(\d{1,2})[-/](\d{1,2})$", str(d.get("date", "")).strip())
        if not mm:
            continue
        month, day = int(mm.group(1)), int(mm.group(2))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        label = str(d.get("label", "")).strip()[:30]
        if not label:
            continue
        year = d.get("year")
        out.append({
            "date": f"{month:02d}-{day:02d}",
            "label": label,
            "kind": d.get("kind", "other") if d.get("kind") in ("birthday", "anniversary", "other") else "other",
            "year": int(year) if isinstance(year, int) else (int(year) if str(year).isdigit() else None),
        })
    return out


async def extract_from_message(user_id: str, text: str, *, mock: bool = False) -> list[dict]:
    """从一句用户消息里识别特殊日子并入库；返回新存的记录（可能为空）。"""
    if mock or not text.strip():
        return []
    today = date.today().strftime("%Y年%m月%d日")
    try:
        resp = await chat(
            [
                {"role": "system", "content": DETECT_PROMPT},
                {"role": "user", "content": f"今天日期：{today}\n用户的话：{text}"},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        dates = _parse_dates(resp)
    except Exception:
        logger.warning("[日子记忆] 单句识别失败：{}", text)
        return []
    saved = []
    for d in dates:
        save_important_date(user_id, d["date"], d["label"], d["kind"], d["year"])
        saved.append(d)
    return saved


# 复盘提取：从一段对话里提取特殊日子（daily 兜底用）
REVIEW_PROMPT = """你是「菟菚」的记忆助手。看下面这段对话，找出**用户明确告知或约定过的、值得记住的日子**（生日、纪念日、约定哪天见面/去哪儿、重要事情的日子）。
只输出 JSON：{"dates": [{"date": "MM-DD", "label": "简短名称", "kind": "birthday|anniversary|other", "year": 年份或null}]}
- date 必须是两位 "MM-DD"；label 像菟菚会说的话；没有明确的日子就 {"dates": []}
- 最多 3 个，不要臆测，只收明确说出来的"""


async def extract_from_transcript(user_id: str, transcript: str, *, mock: bool = False) -> list[dict]:
    """从一段对话记录里识别特殊日子并入库（每日复盘兜底）。"""
    if mock or not transcript.strip():
        return []
    today = date.today().strftime("%Y年%m月%d日")
    try:
        resp = await chat(
            [
                {"role": "system", "content": REVIEW_PROMPT},
                {"role": "user", "content": f"今天日期：{today}\n对话：\n{transcript[:4000]}"},
            ],
            temperature=0.2,
            max_tokens=300,
        )
        dates = _parse_dates(resp)
    except Exception:
        logger.warning("[日子记忆] 复盘识别失败")
        return []
    saved = []
    for d in dates:
        save_important_date(user_id, d["date"], d["label"], d["kind"], d["year"])
        saved.append(d)
    return saved
