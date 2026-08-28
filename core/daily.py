"""每日总结任务 + 长期事实提炼。

- 好感度每日判定（聊爱好/尊重/轻视 + 称呼提取）
- 长期记忆的事实提炼（facts 表，带去重）
由 affection.on_message 跨天回滚或 pipeline 惰性触发。
"""
import json
from datetime import date

from . import affection
from .llm import chat
from .log import logger
from .pipeline import clean_address
from .userdb import db

JUDGE_PROMPT = """你是「菟菚」的好感度管理员。根据以下某用户与菟菚昨天的对话记录，判断并只输出 JSON：
1) hobby：用户是否聊了自己的爱好？（是→1，否→0）
2) respect：用户是否尊重菟菚的喜好（如避开火、回应植物意象、不强迫）？（是→1，否→0）
3) dismiss：用户是否有轻视、不重视菟菚的态度？（是→1，否→0）
4) address：如果用户明确表达了想被怎么称呼，给出该称呼；否则留空字符串。
5) care：用户是否有关心菟菚的言行（如问她累不累、注意休息、担心她等）？（是→1，否→0）
6) deep_chat：昨天是否有深度/走心的对话（如倾诉心事、分享感受、坦诚交流）？（是→1，否→0）

输出格式（不要任何其他内容）：
{"hobby": 0, "respect": 0, "dismiss": 0, "address": "", "care": 0, "deep_chat": 0}
"""

FACT_PROMPT = """你是记忆提取员。根据下面的对话，提取两样东西，只输出一个 JSON：
1) facts：值得**长期记住**的关于用户的事实——喜好、习惯、工作/生活状态、约定承诺、关系进展、重要经历、家人朋友等。**不要**把一次性话题记进去（比如"今天吃了饺子"这种只聊一次的琐事，除非它反映长期习惯）。每条一句短话，以「用户」开头，最多 5 条。
2) style：对「用户说话风格」的简要描述（1-2 句），包括：句子长短、是否爱用语气词/表情、常用口头禅、语气是直接还是委婉、爱不爱开玩笑等。

输出格式（不要任何其他内容）：
{"facts": ["用户喜欢下雨天", "用户和菟菚约好每周五晚上视频"], "style": "对方说话简短直接，常用'啊'和'哈'，喜欢发短句和表情。"}
没有值得记的事实就输出 {"facts": [], "style": "..."}
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
        logger.exception("[每日总结] {} 的好感度判定失败", user_id)

    if data.get("hobby"):
        db.update_affection(user_id, affection.HOBBY_BONUS, "用户聊自己的爱好")
    if data.get("respect"):
        db.update_affection(user_id, affection.RESPECT_BONUS, "尊重菟菚的喜好")
    if data.get("dismiss"):
        db.update_affection(user_id, affection.DISMISS_PENALTY, "轻视/不重视")
    if data.get("care"):
        db.update_affection(user_id, affection.CARE_BONUS, "关心菟菚")
    if data.get("deep_chat"):
        db.update_affection(user_id, affection.DEEP_CHAT_BONUS, "深度/走心对话")

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
        # 用该日最后一条消息的 id 推进游标，避免吞掉今天的新消息
        done = rows[-1]["id"] if rows else 0
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
            max_tokens=400,
        )
        data = _parse_json(resp)
    except Exception:
        logger.exception("[事实提炼] {} 的事实提炼失败（游标已推进，避免反复重试）", user_id)
        db.set_last_fact_msg_id(user_id, done)  # 失败也推进游标，避免反复重试同一批
        return

    if isinstance(data, dict):
        facts = data.get("facts") or []
        style = (data.get("style") or "").strip()
    else:
        facts = data if isinstance(data, list) else []
        style = ""
    if isinstance(facts, list):
        for f in facts:
            fid = db.add_fact(user_id, str(f).strip()[:100])
            # 给新事实建稠密向量索引（失败静默）
            if fid is not None:
                try:
                    from .vector_store import index as vec_index

                    vec_index(user_id, fid, str(f).strip()[:100])
                except Exception:
                    pass
    if style:
        db.set_style(user_id, style[:200])  # 逐渐学习对方说话风格
    db.set_last_fact_msg_id(user_id, done)

    # 复盘识别特殊日子（每天兜底：从这段对话里补录用户明确说过的日子）
    try:
        from .date_memory import extract_from_transcript

        await extract_from_transcript(user_id, transcript)
    except Exception:
        logger.exception("[日子记忆] {} 复盘识别失败", user_id)
