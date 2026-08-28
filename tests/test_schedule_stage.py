"""日程按好感度阶段变化：初识疏离 → 恋人黏人，体现菟菚身份与性格。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schedule import (
    _SCHEDULE_BY_STAGE,
    _stage_of,
    build_schedule,
    schedule_mood_offset,
)
from core.userdb import db

uid = "pytest-stage-sched"
db.ensure_user(uid)
for t in ("kv_store", "messages", "affection_log", "important_dates"):
    db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
db.conn.execute("DELETE FROM users WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)


def _set_affection(value: int):
    db.conn.execute("UPDATE users SET affection=? WHERE user_id=?", (value, uid))
    db.conn.commit()


def test_stage_mapping():
    """好感度阈值应映射到正确阶段。"""
    _set_affection(10)
    assert _stage_of(uid) == "初识"
    _set_affection(30)
    assert _stage_of(uid) == "熟悉"
    _set_affection(60)
    assert _stage_of(uid) == "亲密"
    _set_affection(90)
    assert _stage_of(uid) == "恋人"


def test_schedule_differs_by_stage():
    """不同阶段应生成不同的日程（初识独立 vs 恋人黏人）。"""
    _set_affection(10)
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
    db.conn.commit()
    s1 = build_schedule(uid)
    _set_affection(90)
    db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (uid,))
    db.conn.commit()
    s2 = build_schedule(uid)
    assert s1 != s2
    # 恋人晚上应包含"缠着"
    night_lover = [x for x in s2 if x["period"] == "晚上"][0]["todo"]
    assert "缠" in night_lover
    # 初识晚上不应主动找人
    night_new = [x for x in s1 if x["period"] == "晚上"][0]["todo"]
    assert "自己" in night_new


def test_night_offset_rises_with_stage():
    """晚上时段的心情偏移应随阶段上升（初识低、恋人高）。"""
    _set_affection(10)
    assert schedule_mood_offset(uid, hour=21) == 1  # 初识晚上 +1
    _set_affection(90)
    assert schedule_mood_offset(uid, hour=21) == 5  # 恋人晚上 +5


def test_all_stages_have_six_periods():
    """每个阶段都应有完整的一天六时段。"""
    from core.schedule import _SCHEDULE_BY_STAGE

    for stage, sched in _SCHEDULE_BY_STAGE.items():
        periods = [p for p, _ in sched]
        assert len(periods) == 6
        assert "清晨" in periods and "晚上" in periods


def test_parse_llm_schedule_valid():
    """LLM 输出完整 6 时段 JSON 时应正确解析。"""
    from core.schedule import _parse_llm_schedule

    resp = (
        '{"schedule": [{"period": "清晨", "todo": "a"}, {"period": "上午", "todo": "b"}, '
        '{"period": "中午", "todo": "c"}, {"period": "下午", "todo": "d"}, '
        '{"period": "傍晚", "todo": "e"}, {"period": "晚上", "todo": "f"}]}'
    )
    out = _parse_llm_schedule(resp)
    assert out is not None and len(out) == 6


def test_parse_llm_schedule_missing_period():
    """LLM 输出缺时段时应返回 None（触发规则兜底）。"""
    from core.schedule import _parse_llm_schedule

    resp = '{"schedule": [{"period": "清晨", "todo": "a"}, {"period": "上午", "todo": "b"}]}'
    assert _parse_llm_schedule(resp) is None


def test_parse_llm_schedule_fences():
    """LLM 输出带 markdown 围栏/json 前缀时也应解析。"""
    from core.schedule import _parse_llm_schedule

    resp = (
        '```json\n{"schedule": [{"period": "清晨", "todo": "a"}, {"period": "上午", "todo": "b"}, '
        '{"period": "中午", "todo": "c"}, {"period": "下午", "todo": "d"}, '
        '{"period": "傍晚", "todo": "e"}, {"period": "晚上", "todo": "f"}]}\n```'
    )
    out = _parse_llm_schedule(resp)
    assert out is not None and len(out) == 6
