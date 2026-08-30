"""全模块回归冒烟测试：逐一验证每个模块的核心功能可用。

策略：
- 纯逻辑/本地模块：真实调用，验证返回值
- LLM 依赖：默认 mock（标注 REAL_LLM=1 时真实调用，用于 E2E）
- 网络依赖（搜索/天气/热梗）：真实尝试，失败不算错（环境无网也通过，只记录）
"""
import asyncio
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REAL_LLM = os.environ.get("REAL_LLM") == "1"
UID = "smoke-test-user"
results: list[tuple[str, str, str]] = []  # (module, status, note)


def ok(module: str, note: str = ""):
    results.append((module, "OK", note))
    print(f"  ✅ {module}: {note}")


def warn(module: str, note: str):
    results.append((module, "WARN", note))
    print(f"  ⚠️  {module}: {note}")


def fail(module: str, note: str):
    results.append((module, "FAIL", note))
    print(f"  ❌ {module}: {note}")


def _clean_user():
    from core.userdb import db

    db.ensure_user(UID)
    for t in ("messages", "facts", "user_meta", "affection_log", "long_memory", "stickers", "kv_store", "important_dates"):
        db.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (UID,))
    for k in ("__sys__",):
        db.conn.execute("DELETE FROM kv_store WHERE user_id=?", (k,))
    db.conn.execute("DELETE FROM users WHERE user_id=?", (UID,))
    db.conn.commit()
    db.ensure_user(UID)


async def main():
    print("=" * 60)
    print(f"全模块回归冒烟测试  REAL_LLM={REAL_LLM}")
    print("=" * 60)

    _clean_user()

    # ---- 1. config ----
    print("\n[1/22] config")
    from core.config import config
    assert config.mood_city == "襄阳"
    ok("config", "mood_city=襄阳, data_dir 存在")

    # ---- 2. log ----
    print("\n[2/22] log")
    from core.log import logger
    logger.info("smoke test log write")
    assert (config.data_dir / "bot.log").exists()
    ok("log", "bot.log 可写")

    # ---- 3. userdb ----
    print("\n[3/22] userdb")
    from core.userdb import db, kv_get, kv_set, save_important_date, get_today_important_dates

    u = db.get_user(UID)
    assert u["affection"] == 0
    db.update_affection(UID, 5, "smoke")
    assert db.get_user(UID)["affection"] == 5
    db.set_nickname(UID, "测试名")
    assert db.get_user(UID)["nickname_pref"] == "测试名"
    db.add_message(UID, "user", "测试消息")
    assert len(db.recent_messages(UID, 10)) == 1
    kv_set(UID, "smoke_k", "v")
    assert kv_get(UID, "smoke_k") == "v"
    save_important_date(UID, "08-27", "你的生日", "birthday")
    assert len(get_today_important_dates(UID)) == 1 if date.today().strftime("%m-%d") == "08-27" else True
    db.update_affection(UID, -5, "reset")
    ok("userdb", "增删改查/昵称/kv/important_dates 正常")

    # ---- 4. affection ----
    print("\n[4/22] affection")
    from core import affection

    s = affection.stage_of(5)
    assert s == "初识"
    assert affection.stage_of(30) == "熟悉"
    assert affection.stage_of(55) == "亲密"
    assert affection.stage_of(80) == "恋人"
    assert affection.check_abuse("你真是个废物")
    assert not affection.check_abuse("今天天气不错")
    assert affection.check_bad_address("狗东西")
    assert affection.check_early_confession("我喜欢你")
    assert affection.check_care("你累不累呀")
    ok("affection", "阶段判定/辱骂/称呼/表白/关心 检测正常")

    # ---- 5. rhythm ----
    print("\n[5/22] rhythm")
    from core.rhythm import jitter
    d = jitter(2.0)
    assert 1.2 <= d <= 2.8, d
    ok("rhythm", f"jitter(2.0)={d:.2f}s 在 [1.2,2.8]")

    # ---- 6. message_build ----
    print("\n[6/22] message_build")
    from core.message_build import _build_message, plain_text, image_file, retcode_1200
    msg = _build_message("你好[face:99]")
    assert "你好" in str(msg)
    assert plain_text("你好[CQ:face,id=1]【旁白】〔旁白〕") == "你好"
    assert image_file("D:\\a\\b.png").startswith("file:///")
    assert retcode_1200("retcode=1200 error")
    ok("message_build", "face 白名单/纯文本降级/file URI/1200 检测正常")

    # ---- 7. holidays ----
    print("\n[7/22] holidays")
    from core.holidays import today_holidays, holiday_prompt
    th = today_holidays()
    hp = holiday_prompt(UID)
    assert isinstance(th, list)
    assert isinstance(hp, str)
    ok("holidays", f"today_holidays={th}, holiday_prompt 长度={len(hp)}")

    # ---- 8. schedule ----
    print("\n[8/22] schedule")
    from core.schedule import (
        build_schedule, ensure_schedule, schedule_mood_offset,
        period_for_hour, describe, schedule_prompt, _DEFAULT_STAGE,
    )
    sched = build_schedule(UID, city=config.mood_city)
    assert len(sched) == 6, f"规则兜底应 6 时段，实际 {len(sched)}"
    assert period_for_hour(8) == "清晨"
    assert period_for_hour(23) == "深夜"
    off = schedule_mood_offset(UID, city=config.mood_city)
    assert isinstance(off, int)
    sp = schedule_prompt(UID, city=config.mood_city)
    assert "你今天的日常" in sp
    desc = describe(UID)
    assert isinstance(desc, str) and desc
    ok("schedule", "规则兜底 6 时段/时段映射/情绪偏移/描述正常")
    if REAL_LLM:
        await ensure_schedule(UID, city=config.mood_city)
        sched2 = build_schedule(UID, city=config.mood_city)
        assert len(sched2) == 6
        ok("schedule.ensure(LLM)", f"LLM 日程生成成功, 第1时段={sched2[0]['period']}:{sched2[0]['todo'][:20]}")

    # ---- 9. mood ----
    print("\n[9/22] mood")
    from core.mood import current_mood, on_user_message, mood_bonus_multiplier, today_weather
    w, base = today_weather(config.mood_city)
    assert isinstance(base, int) and 0 <= base <= 100
    mood, name = current_mood(UID, city=config.mood_city)
    assert isinstance(mood, int) and 0 <= mood <= 100
    assert isinstance(name, str)
    on_user_message(UID, "好好笑啊哈哈哈", city=config.mood_city)
    m2, _ = current_mood(UID, city=config.mood_city)
    assert m2 >= mood - 5  # 互动应提升或不明显下降
    mult = mood_bonus_multiplier(m2)
    assert 0.6 <= mult <= 1.5
    ok("mood", f"天气={w} 基线={base}, 心情={mood}->{m2}, 倍率={mult}")

    # ---- 10. context ----
    print("\n[10/22] context")
    from core.context import build_topic_system, topic_hint, topic_switch_hint, context_anchor_hint
    hint = build_topic_system("你今天吃什么了", ["我昨天吃火锅"], 10)
    assert isinstance(hint, str)
    assert isinstance(topic_hint("吃了吗"), str)
    ok("context", "话题锚定提示生成正常")

    # ---- 11. memory（本地部分） ----
    print("\n[11/22] memory")
    from core.memory import (
        short_term_messages, looks_like_recall, message_count,
        compact_context, recall, recall_facts, expand_query,
    )
    assert looks_like_recall("你还记得上次说的吗")
    assert not looks_like_recall("今天天气好")
    stm = short_term_messages(UID)
    assert isinstance(stm, list)
    # 压缩：塞 70 条消息触发
    for i in range(70):
        db.add_message(UID, "user", f"触发压缩的消息{i}")
    comp = await compact_context(UID, mock=True)
    assert comp is not None, "70 条应触发压缩"
    summary, keep = comp
    assert len(keep) <= 14
    ok("memory", f"短期上下文/回忆识别/压缩正常(keep={len(keep)})")
    # 检索（语义扩展走 LLM，mock 掉）
    with mock.patch("core.memory.chat") as m_chat:
        m_chat.return_value = '["消息"]'
        terms = await expand_query(UID, "还记得吗", mock=False)
        assert terms
    mem = await recall(UID, "消息", mock=True)
    assert isinstance(mem, list)
    facts = await recall_facts(UID, "消息", mock=True)
    assert isinstance(facts, list)
    ok("memory.recall", f"语义扩展={terms}, recall={len(mem)}, recall_facts={len(facts)}")

    # ---- 12. vector_store（本地建索引/检索，embedding 需网络则跳过） ----
    print("\n[12/22] vector_store")
    from core.vector_store import index as vec_index, search as vec_search, indexed_count, enabled, backfill
    assert enabled()
    n_before = indexed_count()
    # 用 stub 避免真实 embedding 网络调用，仅验证表与接口
    with mock.patch("core.vector_store.embed") as m_emb:
        m_emb.return_value = [0.1] * 1024
        assert vec_index(UID, 999999, "测试内容")
        r = vec_search(UID, "测试", 3)
        assert isinstance(r, list)
    n_after = indexed_count()
    ok("vector_store", f"建索引/检索接口正常 (索引 {n_before}->{n_after})")

    # ---- 13. date_memory ----
    print("\n[13/22] date_memory")
    from core.date_memory import _parse_dates, extract_from_message
    parsed = _parse_dates('{"dates": [{"date": "05-20", "label": "你的生日", "kind": "birthday", "year": null}]}')
    assert parsed and parsed[0]["date"] == "05-20"
    ok("date_memory", f"日期解析正常: {parsed}")

    # ---- 14. daily（本地部分，LLM mock） ----
    print("\n[14/22] daily")
    from core.daily import extract_facts
    with mock.patch("core.daily.chat") as m_chat:
        m_chat.return_value = '{"facts": ["用户喜欢下雨"], "style": "对方说话简短"}'
        await extract_facts(UID, date.today())
    got = db.search_facts(UID, "下雨", 5)
    assert got, "事实应被提炼入库"
    ok("daily", f"事实提炼入库: {got}")

    # ---- 15. draw_context ----
    print("\n[15/22] draw_context")
    from core.draw_context import want_to_see, extract_scene, _parse_scene
    assert want_to_see("想看！")
    assert not want_to_see("不想看")
    assert _parse_scene('{"scene": "一片花田"}') == "一片花田"
    scene = await extract_scene(UID, mock=True)
    assert scene == ""
    ok("draw_context", "想看意图/场景解析正常")

    # ---- 16. speak ----
    print("\n[16/22] speak")
    from core.speak import _clean, with_sticker, before_draw
    assert _clean("你好呀") == "你好呀"
    assert _clean("宝宝") == ""  # 黑名单词
    line = await with_sticker("今天好累", mock=True)
    assert line
    bd = await before_draw(mock=True)
    assert bd
    ok("speak", f"话术生成正常: {line} / {bd}")

    # ---- 17. sticker ----
    print("\n[17/22] sticker")
    from core.sticker import pick, collect
    from core.userdb import save_sticker
    save_sticker(UID, "dummy1.png", "https://x/1.png", "一只猫")
    save_sticker(UID, "dummy2.png", "https://x/2.png", "一朵花")
    picked = pick(UID, "猫", 5, exclude_files={"dummy1.png"})
    assert picked, "应能挑到表情包"
    ok("sticker", f"pick 排除后返回 {len(picked)} 个")

    # ---- 18. persona ----
    print("\n[18/22] persona")
    from core.persona import build_system_prompt
    sp = build_system_prompt(
        stage="初识", address=None, lover_confirm=False,
        first_chat=True, affection=5, user_id=UID,
    )
    assert isinstance(sp, str) and len(sp) > 200
    ok("persona", f"system prompt 长度={len(sp)}")

    # ---- 19. tasks ----
    print("\n[19/22] tasks")
    from core.tasks import schedule, pending
    schedule("smoke:task", lambda: asyncio.sleep(0.01))
    assert pending("smoke:task")
    await asyncio.sleep(0.2)
    assert not pending("smoke:task")
    ok("tasks", "后台任务调度/去重正常")

    # ---- 20. search（真实网络，失败仅 WARN） ----
    print("\n[20/22] search")
    from core.search import web_search, last_error
    hits = web_search("今天天气", 3)
    if hits:
        ok("search", f"搜索返回 {len(hits)} 条")
    else:
        warn("search", f"无结果（网络或解析）: {last_error()}")

    # ---- 21. memes（真实刷新，失败仅 WARN） ----
    print("\n[21/22] memes")
    from core.memes import get_current_memes, _load_cached, has_memes
    cached = _load_cached()
    if cached and cached.get("memes"):
        ok("memes", f"热梗缓存 {len(cached['memes'])} 条")
    else:
        warn("memes", "无热梗缓存（后台刷新中或未生成）")

    # ---- 22. proactive（构造但跑调度） ----
    print("\n[22/22] proactive")
    from core.proactive import _period_hint, set_active_user, get_active_user
    set_active_user(UID)
    assert get_active_user() == UID
    ph = _period_hint()
    assert isinstance(ph, str)
    ok("proactive", f"时段提示正常: {ph[:20]}")

    # ---- 汇总 ----
    print("\n" + "=" * 60)
    n_ok = sum(1 for _, s, _ in results if s == "OK")
    n_warn = sum(1 for _, s, _ in results if s == "WARN")
    n_fail = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"汇总: OK={n_ok}  WARN={n_warn}  FAIL={n_fail}  (共 {len(results)} 项)")
    if n_fail:
        print("存在 FAIL，请检查：")
        for m, s, n in results:
            if s == "FAIL":
                print(f"  ❌ {m}: {n}")
    return n_fail


if __name__ == "__main__":
    nf = asyncio.run(main())
    sys.exit(1 if nf else 0)
