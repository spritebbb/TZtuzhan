"""每日总结任务 + 长期事实提炼。

- 好感度每日判定（聊爱好/尊重/轻视 + 称呼提取）
- 长期记忆的事实提炼（facts 表，带去重）
由 affection.on_message 跨天回滚或 pipeline 惰性触发。
"""
import json
from datetime import date

from . import affection
from .llm import chat
from .pipeline import clean_address
from .userdb import db

JUDGE_PROMPT = """你是「菟菚」的好感度管理员。根据以下某用户与菟菚昨天的对话记录，判断并只输出 JSON：
1) hobby：用户是否聊了自己的爱好？（是→1，否→0）
2) respect：用户是否尊重菟菚的喜好（如避开火、回应植物意象、不强迫）？（是→1，否→0）
3) dismiss：用户是否有轻视、不重视菟菚的态度？（是→1，否→0）
4) address：如果用户明确表达了想被怎么称呼，给出该称呼；否则留空字符串。

输出格式（不要任何其他内容）：
{"hobby": 0, "respect": 0, "dismiss": 0, "address": ""}
"""

FACT_PROMPT = """你是记忆提取员。根据下面的对话，提取值得长期记住的事实——关于用户这个人的：喜好、习惯、工作/生活情况、重要约定、关系进展、对菟菚的看法等。
要求：
- 每一条用一句简短、客观的话，以「用户」开头；
- 忽略寒暄、天气闲聊（除非表达了明确喜好）、无关内容；
- 最多 5 条，宁缺毋滥。
只输出 JSON 数组，不要其他任何内容：
["用户喜欢下雨天", "用户和菟菚约好每周五晚上视频"]
没有值得记的就输出 []。
"""


def _parse_json(resp: str):
    text = resp.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(text)


async def run_daily_batch(user_id: str, day: date) -> None:
    """昨日好感度判定 + 事实提炼。"""
    rows = db.messages_between(user_id, day, day)
    if not rows:
        return
    transcript = "\n".join(f"{r['role']}: {r['content']}" for r in rows[-60:])
    data = {}
    try:
        resp = await chat(
            [
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": f"昨天的对话：\n{transcript}"},
            ]
        )
        data = _parse_json(resp)
    except Exception:
        pass

    if data.get("hobby"):
        db.update_affection(user_id, affection.HOBBY_BONUS, "用户聊自己的爱好")
    if data.get("respect"):
        db.update_affection(user_id, affection.RESPECT_BONUS, "尊重菟菚的喜好")
    if data.get("dismiss"):
        db.update_affection(user_id, affection.DISMISS_PENALTY, "轻视/不重视")

    addr = (data.get("address") or "").strip()
    if addr and not db.get_user(user_id)["nickname_pref"] and not affection.check_bad_address(addr):
        db.set_nickname(user_id, clean_address(addr)[:12])

    await extract_facts(user_id, day)


async def extract_facts(user_id: str, day: date | None = None) -> None:
    """把值得记住的事实提炼进 facts 表（带去重）。

    day 非空：提炼该日全部对话（每日模式）；
    day 为空：提炼 last_fact_msg_id 之后的新消息（惰性模式，消息太少会跳过）。
    """
    last_id = db.get_last_fact_msg_id(user_id)

    if day is not None:
        rows = db.messages_between(user_id, day, day)
        if not rows:
            return
        transcript = "\n".join(f"{r['role']}: {r['content']}" for r in rows[-60:])
        done = db.max_message_id(user_id)
    else:
        rows = db.messages_after(user_id, last_id, 60)
        if len(rows) < 8:  # 太少不值得提炼，省一次调用
            return
        transcript = "\n".join(f"{r['role']}: {r['content']}" for r in rows)
        done = rows[-1]["id"]

    try:
        resp = await chat(
            [
                {"role": "system", "content": FACT_PROMPT},
                {"role": "user", "content": f"对话记录：\n{transcript}"},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        facts = _parse_json(resp)
    except Exception:
        db.set_last_fact_msg_id(user_id, done)  # 失败也推进游标，避免反复重试同一批
        return

    if isinstance(facts, list):
        for f in facts:
            db.add_fact(user_id, str(f).strip()[:100])
    db.set_last_fact_msg_id(user_id, done)
