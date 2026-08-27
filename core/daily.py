"""每日总结任务：用 LLM 判定昨日对话的好感度调整项 + 提取称呼偏好。

对应 bot-design.md 第 5 节的「每日一次 LLM 批量判定」。
由 affection.on_message 在跨天回滚时惰性触发，无需定时任务。
"""
import json
from datetime import date

from . import affection
from .llm import chat
from .userdb import db

JUDGE_PROMPT = """你是「菟菚」的好感度管理员。根据以下某用户与菟菚昨天的对话记录，判断并只输出 JSON：
1) hobby：用户是否聊了自己的爱好？（是→1，否→0）
2) respect：用户是否尊重菟菚的喜好（如避开火、回应植物意象、不强迫）？（是→1，否→0）
3) dismiss：用户是否有轻视、不重视菟菚的态度？（是→1，否→0）
4) address：如果用户明确表达了想被怎么称呼，给出该称呼；否则留空字符串。

输出格式（不要任何其他内容）：
{"hobby": 0, "respect": 0, "dismiss": 0, "address": ""}
"""


def run_daily_batch(user_id: str, day: date) -> None:
    """读取某日对话，LLM 判定后写入好感度调整与称呼偏好。"""
    rows = db.messages_between(user_id, day, day)
    if not rows:
        return

    transcript = "\n".join(f"{r['role']}: {r['content']}" for r in rows[-60:])
    try:
        resp = chat(
            [
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": f"昨天的对话：\n{transcript}"},
            ]
        )
        data = json.loads(resp)
    except Exception:
        return

    delta = 0
    if data.get("hobby"):
        delta += affection.HOBBY_BONUS
        db.update_affection(user_id, affection.HOBBY_BONUS, "用户聊自己的爱好")
    if data.get("respect"):
        delta += affection.RESPECT_BONUS
        db.update_affection(user_id, affection.RESPECT_BONUS, "尊重菟菚的喜好")
    if data.get("dismiss"):
        delta += affection.DISMISS_PENALTY
        db.update_affection(user_id, affection.DISMISS_PENALTY, "轻视/不重视")

    addr = (data.get("address") or "").strip()
    if addr and not db.get_user(user_id)["nickname_pref"] and not affection.check_bad_address(addr):
        db.set_nickname(user_id, addr[:12])
