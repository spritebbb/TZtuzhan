"""话题记忆：记住上次聊了什么，新会话能自然延续。

原理：
- 会话空闲（离上一条消息超过阈值）时，由 LLM 把最近的对话提炼成一句话话题，
  存进 kv_store（key: last_topic）。
- 新会话开场（用户在新的一场里说第一句）时，注入"你们上次聊到…"，
  让菟菚像记得似的自然接上，而不是每次重新开始。
- 话题提炼失败/无数据时静默返回空，不影响对话。

数据落点（kv_store）：
- last_topic      最近一次提炼的上次话题（文本）
- last_topic_ts   提炼时间（ISO）
- last_topic_msg_id  提炼所基于的最后一条消息 id（避免重复提炼同一段）
"""
from datetime import datetime

from .llm import chat
from .log import logger
from .userdb import db

# 会话空闲判定：离上一条消息超过该分钟数，视为上一场聊完（可提炼话题）
TOPIC_IDLE_MINUTES = 30
# 提炼需要的最少消息条数
TOPIC_MIN_MESSAGES = 4


def _strip_parens(text: str) -> str:
    import re

    return re.sub(r"（[^）]*）|\([^)]*\)", "", text).strip()


def _kv_get(user_id: str, key: str) -> str | None:
    from .userdb import kv_get

    return kv_get(user_id, key)


def _kv_set(user_id: str, key: str, value: str) -> None:
    from .userdb import kv_set

    kv_set(user_id, key, value)


def last_topic(user_id: str) -> str | None:
    """读取上次提炼的话题（无则 None）。"""
    return _kv_get(user_id, "last_topic")


def last_topic_ts(user_id: str) -> str | None:
    return _kv_get(user_id, "last_topic_ts")


def _recent_transcript(user_id: str, limit: int = 12) -> list[dict]:
    """最近若干条消息（role/content），供提炼。"""
    rows = db.recent_messages(user_id, limit)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


async def extract_topic(user_id: str, *, mock: bool = False) -> str | None:
    """把最近的对话提炼成一句话『上次聊到什么』；失败返回 None（不阻塞对话）。

    用独立的 last_topic_msg_id 游标避免反复提炼同一段对话。
    """
    try:
        # 游标：只从最新消息里提炼，确保概括的是最近对话
        last_base = int(_kv_get(user_id, "last_topic_msg_id") or "0")
        # 用 messages_after 取游标之后的消息（不限批次上限），避免突发连发时
        # 最早超出窗口的消息被游标永久跳过。取 50 条覆盖大部分突发场景。
        rows = db.messages_after(user_id, last_base, 50)
        if len(rows) < TOPIC_MIN_MESSAGES:
            return None
        max_id = rows[-1]["id"]
        transcript = "\n".join(
            f"{'对方' if r['role'] == 'user' else '菟菚'}：{r['content'][:100]}"
            for r in rows[-TOPIC_MIN_MESSAGES:]
        )
        if mock:
            topic = "上次聊了一些日常"
        else:
            topic = await chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "下面是一段 AI 女友和一个朋友的聊天记录（按时间顺序）。"
                            "请用**一句话**概括『他们上次主要聊了什么/正聊到哪』，"
                            "像是给下一个会话准备的记忆便签。要求："
                            "①口语、自然（比如『他上次说想换台新电脑』『上次在聊周末要不要去看电影』）；"
                            "②突出还没聊完、可以接着聊的钩子；③不要复述对话、不要评价、不要『他们聊了』这种报告腔；"
                            "④只说最重要的一件/一个话题，不超过 40 字。"
                        ),
                    },
                    {"role": "user", "content": transcript},
                ],
                temperature=0.4,
                max_tokens=80,
            )
        topic = _strip_parens(topic).strip().strip("。")
        if not topic or len(topic) < 2:
            return None
        _kv_set(user_id, "last_topic", topic)
        _kv_set(user_id, "last_topic_ts", datetime.now().isoformat(timespec="seconds"))
        _kv_set(user_id, "last_topic_msg_id", str(max_id))
        return topic
    except Exception:
        logger.exception("[话题记忆] 提炼失败（不影响对话）")
        return None


def build_continuation(user_id: str) -> str | None:
    """新会话开场时生成『接着上次』的提示文本；无话题返回 None。"""
    topic = last_topic(user_id)
    if not topic:
        return None
    # 话题太旧（超过 3 天）就不再主动提，避免生硬翻旧账
    ts = last_topic_ts(user_id)
    if ts:
        try:
            age_days = (datetime.now() - datetime.fromisoformat(ts)).days
            if age_days >= 3:
                return None
        except ValueError:
            pass
    return topic
