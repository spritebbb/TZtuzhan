"""复核修复的回归测试：date year 过滤、schedule 时段去重、style 场景去重、llm mock 回显、memes 代理回退。"""
import sys
from datetime import date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import llm, schedule, style, userdb
from core.userdb import db

uid = "pytest-review-fixes"
db.ensure_user(uid)
for t in ("kv_store", "messages", "user_style_map", "important_dates"):
    db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
db.conn.commit()
db.ensure_user(uid)


# ---- date year 过滤：有 year 的只在当年匹配，无 year 的每年过 ----

def test_today_important_dates_respects_year():
    from core.userdb import get_today_important_dates, save_important_date

    today = date.today()
    mmdd = today.strftime("%m-%d")
    db.conn.execute("DELETE FROM important_dates WHERE user_id=?", (uid,))
    db.conn.commit()
    # 无 year → 每年都过，今天应命中
    save_important_date(uid, mmdd, "每年生日", "birthday", None)
    assert any(d["label"] == "每年生日" for d in get_today_important_dates(uid))
    # 带今年 year → 命中
    save_important_date(uid, mmdd, "今年纪念日", "anniversary", today.year)
    assert any(d["label"] == "今年纪念日" for d in get_today_important_dates(uid))
    # 带过去 year（如去年）→ 今天不应命中（一次性日子已过）
    save_important_date(uid, mmdd, "过期日子", "other", today.year - 1)
    labels = [d["label"] for d in get_today_important_dates(uid)]
    assert "过期日子" not in labels
    db.conn.execute("DELETE FROM important_dates WHERE user_id=?", (uid,))
    db.conn.commit()


# ---- schedule 时段去重：6 条但时段重复 → 判为不合格 ----

def test_parse_llm_schedule_rejects_duplicate_periods():
    resp = '{"schedule": [{"period": "清晨", "todo": "a"}, {"period": "清晨", "todo": "b"}, {"period": "上午", "todo": "c"}, {"period": "中午", "todo": "d"}, {"period": "下午", "todo": "e"}, {"period": "晚上", "todo": "f"}]}'
    # 缺「傍晚」且「清晨」重复 → 拒绝
    assert schedule._parse_llm_schedule(resp) is None
    good = '{"schedule": [{"period": "清晨", "todo": "a"}, {"period": "上午", "todo": "b"}, {"period": "中午", "todo": "c"}, {"period": "下午", "todo": "d"}, {"period": "傍晚", "todo": "e"}, {"period": "晚上", "todo": "f"}]}'
    parsed = schedule._parse_llm_schedule(good)
    assert parsed is not None and len(parsed) == 6


# ---- style 按场景去重：同场景只更新 style/累加，不再新增行 ----

def test_style_map_dedup_by_situation():
    db.conn.execute("DELETE FROM user_style_map WHERE user_id=?", (uid,))
    db.conn.commit()
    from core.userdb import db as udb

    udb.add_style_map(uid, "对方倾诉烦恼时", "喜欢用短句")
    udb.add_style_map(uid, "对方倾诉烦恼时", "爱用语气词")
    rows = udb.get_style_map(uid)
    assert len(rows) == 1
    assert rows[0]["count"] == 2
    assert rows[0]["style"] == "爱用语气词"  # 最新 style 覆盖


# ---- llm mock 回显最后一条 user 消息（不把末尾 system 当回复）----

def test_llm_mock_echoes_user_not_system():
    from core.llm import chat

    async def _go():
        return await chat(
            [
                {"role": "system", "content": "你是菟菚"},
                {"role": "user", "content": "今天天气不错呢"},
                {"role": "system", "content": "重要：不要输出 [face:数字]"},
            ],
            mock=True,
        )

    import asyncio

    resp = asyncio.run(_go())
    assert "今天天气不错呢" in resp
    assert "不要输出" not in resp


# ---- memes 代理回退：无环境代理时仍能构造 opener（不硬编码死代理）----

def test_memes_proxy_fallback():
    import core.memes as memes

    with mock.patch.dict("os.environ", {}, clear=True):
        from unittest import mock as _m

        captured = {}

        def _fake_build_opener(handler):
            captured["proxy"] = handler.proxies
            return mock.MagicMock()

        with _m.patch("urllib.request.build_opener", side_effect=_fake_build_opener), \
             _m.patch("urllib.request.getproxies", return_value={}):
            fn = None
            # 直接测 _sync_fetch 里的 opener 构造：抓 weibo 失败也静默返回 []
            result = asyncio_run_weibo(memes)
            assert result == []
            # 无环境代理时直连（空代理表，不硬编码本地 mihomo）——GitHub 用户无代理也能用
            assert captured["proxy"] == {}


def asyncio_run_weibo(memes):
    import asyncio

    return asyncio.run(memes._fetch_weibo_hot())


# ---- mood 天气缓存：失败兜底只缓存 30 分钟，之后允许重试 ----

def test_weather_cache_retries_after_unknown():
    import core.mood as mood
    from datetime import timedelta

    city = "pytest-weather-city"
    mood._WEATHER_CACHE.pop(city, None)

    # 第一次：天气获取失败 → 缓存「未知」兜底
    with mock.patch.object(mood, "_weather_via_search", return_value=None), \
         mock.patch.object(mood, "_weather_via_wttr", return_value=None):
        w, base = mood.today_weather(city)
        assert w == "未知"

    # 30 分钟内：即使天气已可用，仍返回缓存的「未知」（不频繁重试）
    with mock.patch.object(mood, "_weather_via_search", return_value="晴"), \
         mock.patch.object(mood, "_weather_via_wttr", return_value=None):
        w2, _ = mood.today_weather(city)
        assert w2 == "未知"

    # 超过 30 分钟：允许重试 → 这次能拿到「晴」
    fetched = mood._WEATHER_CACHE[city][3] - timedelta(minutes=31)
    mood._WEATHER_CACHE[city] = (
        mood._WEATHER_CACHE[city][0], mood._WEATHER_CACHE[city][1],
        mood._WEATHER_CACHE[city][2], fetched,
    )
    with mock.patch.object(mood, "_weather_via_search", return_value="晴"), \
         mock.patch.object(mood, "_weather_via_wttr", return_value=None):
        w3, _ = mood.today_weather(city)
        assert w3 == "晴"
    mood._WEATHER_CACHE.pop(city, None)
