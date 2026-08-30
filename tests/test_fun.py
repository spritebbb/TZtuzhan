"""互动玩法（日记/小游戏/睡前故事）的纯逻辑测试。

覆盖：
- 日记：生成/读取/去重
- 猜数字：开始/猜/提示/结束
- 石头剪刀布：出拳/结果
- 睡前故事：mock 模式生成
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import fun, userdb

db = userdb.db

UID = "pytest-fun"


def _clean():
    db.ensure_user(UID)
    db.conn.execute("DELETE FROM diary WHERE user_id=?", (UID,))
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (UID,))
    db.conn.commit()


# ---- 日记 ----

def test_diary_table_created():
    _clean()
    fun._ensure_diary_table()
    tables = [r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "diary" in tables


def test_diary_generate_mock():
    _clean()
    import asyncio
    diary = asyncio.run(fun.generate_diary(UID, mock=True))
    assert diary is not None
    assert len(diary) >= 4


def test_diary_reuse_existing():
    _clean()
    import asyncio
    d1 = asyncio.run(fun.generate_diary(UID, mock=True))
    d2 = asyncio.run(fun.generate_diary(UID, mock=True))
    assert d1 == d2  # 不重复生成


def test_diary_text():
    _clean()
    import asyncio
    asyncio.run(fun.generate_diary(UID, mock=True))
    text = fun.diary_text(UID)
    assert text and len(text) >= 4
    assert fun.diary_text("no-such-user") == "（今天还没写日记呢……）"


def test_list_diary_dates():
    _clean()
    import asyncio
    asyncio.run(fun.generate_diary(UID, mock=True))
    dates = fun.list_diary_dates(UID)
    assert len(dates) >= 1
    assert "date" in dates[0] and "mood" in dates[0]


# ---- 猜数字 ----

def test_guess_game_start():
    _clean()
    msg = fun.start_guess_game(UID)
    assert "猜是多少" in msg
    state = fun._game_state(UID)
    assert state is not None
    assert 1 <= state["answer"] <= 100


def test_guess_game_play():
    _clean()
    fun.start_guess_game(UID)
    state = fun._game_state(UID)
    answer = state["answer"]
    # 猜错
    wrong = 101 if answer < 50 else -1
    msg = fun.guess_number(UID, wrong)
    assert "高了" in msg or "低了" in msg
    # 猜对
    msg2 = fun.guess_number(UID, answer)
    assert "对啦" in msg2 or "猜中了" in msg2
    # 游戏结束
    assert fun._game_state(UID) is None or fun._game_state(UID).get("game") != "guess"


def test_guess_game_no_game():
    _clean()
    msg = fun.guess_number(UID, 42)
    assert "还没开始" in msg


# ---- 石头剪刀布 ----

def test_rps_play():
    _clean()
    for choice in ("石头", "剪刀", "布"):
        msg = fun.rps_play(UID, choice)
        assert "平手" in msg or "赢了" in msg or "输了" in msg


def test_rps_invalid_choice():
    _clean()
    msg = fun.rps_play(UID, "手枪")
    assert "接不住" in msg


# ---- 睡前故事 ----

def test_bedtime_story_mock():
    _clean()
    import asyncio
    story = asyncio.run(fun.bedtime_story(UID, mock=True))
    assert story is not None
    assert len(story) >= 4