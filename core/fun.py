"""互动玩法：日记系统、小游戏、睡前故事。

功能：
- 日记：菟菚写日记记录当天的对话，手动/自动生成，/日记 查看
- 猜数字：/猜数字 开始，菟菚心里想一个 1-100 的数，用户猜
- 石头剪刀布：/石头剪刀布 [石头/剪刀/布]
- 睡前故事：/故事 生成适合当前阶段/心情的晚安小故事

数据存在 userdb 的 kv_store 和设想的 diary 表（在 userdb 里建表）。
"""
import json
import random
from datetime import date, datetime, timedelta

from . import affection
from .config import config
from .llm import chat
from .log import logger
from .userdb import db, kv_get, kv_set

# ====== 日记系统 ======

DIARY_PROMPT = """你是菟菚（坚强独立、带点腹黑毒舌的菟丝子娘），在写私人日记。
根据下面你和对方的对话记录，写一段日记（菟菚的视角，第一人称）。
日记要自然、细腻、像是在心里跟自己说话：
- 今天发生了什么、聊了什么
- 你对对方的感觉（按好感度阶段）
- 你心里的小情绪（直白的、偶尔淡淡的在意）
- 语气像你平时说话一样：短句、自然、偶尔带点毒舌
- 不要复述对话，不要列清单，就像你合上本子时随口写的三两句话
- 100-200 字左右
"""


def _ensure_diary_table():
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS diary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            content TEXT NOT NULL,
            mood TEXT NOT NULL DEFAULT '',
            ts TEXT NOT NULL,
            UNIQUE(user_id, date)
        )
    """)
    db.conn.commit()


def _diary_for_date(user_id: str, d: date) -> str | None:
    _ensure_diary_table()
    row = db.conn.execute(
        "SELECT content FROM diary WHERE user_id=? AND date=?", (user_id, d.isoformat())
    ).fetchone()
    return row[0] if row else None


def _save_diary(user_id: str, d: date, content: str, mood: str = "") -> None:
    _ensure_diary_table()
    now = datetime.now().isoformat(timespec="seconds")
    db.conn.execute(
        "INSERT OR REPLACE INTO diary (user_id, date, content, mood, ts) VALUES (?,?,?,?,?)",
        (user_id, d.isoformat(), content, mood, now),
    )
    db.conn.commit()


def list_diary_dates(user_id: str, limit: int = 10) -> list[dict]:
    """返回最近 N 篇日记的日期列表（不含内容，供 Web UI 用）。"""
    _ensure_diary_table()
    rows = db.conn.execute(
        "SELECT date, mood, ts FROM diary WHERE user_id=? ORDER BY date DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [{"date": r[0], "mood": r[1], "ts": r[2]} for r in rows]


async def generate_diary(user_id: str, *, mock: bool = False) -> str | None:
    """为今天生成一篇日记（LLM 生成）。已存在则直接返回，不重复生成。"""
    today = date.today()
    existing = _diary_for_date(user_id, today)
    if existing:
        return existing
    # 取今天对话汇总
    rows = db.messages_between(user_id, today, today)
    if not rows:
        # 如果今天还没对话，也写一篇浅浅的（天气/心情/期待）
        rows = []
    transcript = "\n".join(f"{r['role']}: {r['content']}" for r in rows[-30:])
    user = db.ensure_user(user_id)
    # 心情
    try:
        from .mood import current_mood as _mood
        mood_val, mood_label = _mood(user_id, city=config.mood_city)
    except Exception:
        mood_val, mood_label = 60, "平淡"
    stage = affection.stage_of(user["affection"])
    pref = user["nickname_pref"] or "你"

    if mock:
        diary = f"今天的心情是{mood_label}，{stage}阶段。和{pref}聊了一些日常。"
    else:
        try:
            diary = await chat(
                [
                    {"role": "system", "content": DIARY_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"今天日期：{today.isoformat()}\n"
                            f"当前心情：{mood_label}（{mood_val}）\n"
                            f"好感度阶段：{stage}\n"
                            f"对方称呼：{pref}\n"
                            f"今天的对话：\n{transcript if transcript else '（今天还没说上话…）'}"
                        ),
                    },
                ],
                temperature=0.7,
                max_tokens=300,
            )
        except Exception:
            logger.exception("[日记] LLM 生成失败")
            return None
    diary = diary.strip().strip('"').strip()
    if diary:
        _save_diary(user_id, today, diary, mood_label)
    return diary


def diary_text(user_id: str) -> str:
    """返回今天的日记（纯文本，不存在则告知）。"""
    today = date.today()
    d = _diary_for_date(user_id, today)
    return d if d else "（今天还没写日记呢……）"


# ====== 小游戏：猜数字 ======

_GAME_KEY = "game:guess"

def _game_state(user_id: str) -> dict | None:
    raw = kv_get(user_id, _GAME_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _save_game(user_id: str, state: dict) -> None:
    kv_set(user_id, _GAME_KEY, json.dumps(state, ensure_ascii=False))


def _clear_game(user_id: str) -> None:
    kv_set(user_id, _GAME_KEY, "")


def start_guess_game(user_id: str, force: bool = False) -> str:
    """开始一轮猜数字，菟菚心里想一个 1-100 的数。

    force=False 且已有进行中的游戏时，不静默覆盖，提示继续（避免误触丢进度）。
    """
    state = _game_state(user_id)
    if state and state.get("game") == "guess" and not force:
        return "上一轮还没猜完呢（已猜 {} 次），继续猜吧；想重开就说「重新猜数字」～".format(
            state.get("attempts", 0)
        )
    answer = random.randint(1, 100)
    state = {"game": "guess", "answer": answer, "attempts": 0, "hints": []}
    _save_game(user_id, state)
    return "我想了一个 1 到 100 之间的数，你猜是多少？"


def restart_guess_game(user_id: str) -> str:
    """强制重开一轮猜数字（丢弃旧进度）。"""
    return start_guess_game(user_id, force=True)


def guess_number(user_id: str, guess: int) -> str:
    """猜数字：返回菟菚的提示。"""
    state = _game_state(user_id)
    if not state or state.get("game") != "guess":
        return "还没开始呢，说「猜数字」我就想一个数～"
    answer = state["answer"]
    state["attempts"] += 1
    if guess == answer:
        _clear_game(user_id)
        return f"对啦！就是 {answer}，你猜了 {state['attempts']} 次猜中的～"
    elif guess < answer:
        state["hints"].append(f"低了（{guess}）")
        _save_game(user_id, state)
        return f"嗯……低了，再往大猜"
    else:
        state["hints"].append(f"高了（{guess}）")
        _save_game(user_id, state)
        return f"高了，往小猜"


# ====== 小游戏：石头剪刀布 ======

_RPS_CHOICES = ("石头", "剪刀", "布")

def _rps_winner(user: str, bot: str) -> str:
    if user == bot:
        return "平"
    if (user == "石头" and bot == "剪刀") or \
       (user == "剪刀" and bot == "布") or \
       (user == "布" and bot == "石头"):
        return "用户"
    return "菟菚"


def rps_play(user_id: str, choice: str) -> str:
    """石头剪刀布：菟菚出拳，返回结果。"""
    if choice not in _RPS_CHOICES:
        return f"要出：石头、剪刀、布。你说 '{choice}' 我接不住呀"
    bot_choice = random.choice(_RPS_CHOICES)
    winner = _rps_winner(choice, bot_choice)
    if winner == "平":
        return f"我出的{bot_choice}，你也是{choice}，平手～再来？"
    elif winner == "用户":
        return f"我出的{bot_choice}，你赢了……哼，再来一局！"
    else:
        return f"我出的{bot_choice}，你输了哦～再来？"


# ====== 睡前故事 ======

STORY_PROMPT = """你是菟菚（坚强独立、带点腹黑毒舌的菟丝子娘），在给一个你亲近的人讲睡前故事。

写一个温暖、治愈的短篇睡前故事（200-300 字左右）。
故事要温柔、细腻，但不要矫情，可以带一点点俏皮和意外的小转折。
可以用你喜欢的意象（月光、花开、风、星星、猫咪），
但别太阴暗或惊险，这是睡前故事。
按照当前好感度阶段和对方的心情来调整语气：
- 初识/熟悉：温暖但保持距离，像讲给一个朋友
- 亲密：柔软、信赖，像讲给亲近的人
- 恋人：亲昵但克制，带着一点默契和温暖
"""


async def bedtime_story(user_id: str, *, mock: bool = False) -> str:
    """生成一篇睡前故事（LLM 生成，带人设和阶段感知）。"""
    user = db.ensure_user(user_id)
    stage = affection.stage_of(user["affection"])
    pref = user["nickname_pref"] or "你"
    bl = affection.bond_level_name(user["affection"])
    try:
        from .mood import current_mood as _mood
        mood_val, mood_label = _mood(user_id, city=config.mood_city)
    except Exception:
        mood_val, mood_label = 60, "平淡"

    if mock:
        return f"从前，有一株藤蔓，她慢慢地向{pref}的方向生长，一天又一天……晚安。"

    try:
        story = await chat(
            [
                {"role": "system", "content": STORY_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"好感度阶段：{stage}\n"
                        f"羁绊：{bl}\n"
                        f"对方称呼：{pref}\n"
                        f"当前心情：{mood_label}（{mood_val}）\n"
                        f"请讲一个睡前故事。"
                    ),
                },
            ],
            temperature=0.7,
            max_tokens=500,
        )
    except Exception:
        logger.exception("[故事] LLM 生成失败")
        return "……今晚的故事，在风里飘走了，改天再讲给你听吧。"
    return story.strip().strip('"').strip()