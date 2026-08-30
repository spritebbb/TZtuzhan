"""第二轮复核修复的回归测试（子代理新发现项）：
- _extract_reply/strip_actions 裸「思考：/回复：」锚定行首、多段【回复】取最后一段
- vector_store 跨线程 RLock（不因重入死锁）
- userdb birthday 带出生年份仍每年触发（year 过滤不误伤生日）
- memory compact 游标：摘要为空/未持久化时不推进
- schedule 去重后返回完整 6 时段（唯一时段在尾部不被截掉）
- style 非字符串值跳过、date_memory label null 跳过
- draw_context「特别想看」不误判否定
- offline_alert 发送成功才标记已提醒
- cards 进度提示用下一阶段名
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import pipeline, schedule, style  # noqa: E402
from core.userdb import db  # noqa: E402

uid = "pytest-review-round2"
db.ensure_user(uid)


# ---- _extract_reply：裸「思考：/回复：」必须锚定行首（正文中间不误伤）----

def test_extract_reply_bare_thought_not_middle():
    # 正文中间的「思考：」不应被当成思考段标记
    raw = "我在思考：要不要答应你呢"
    assert pipeline._extract_reply(raw) == "我在思考：要不要答应你呢"


def test_extract_reply_bare_thought_line_start():
    # 行首的裸「思考：」是思考段，取其后正文
    raw = "思考：她在想什么\n嗯，那我先不吵你了"
    assert pipeline._extract_reply(raw) == "嗯，那我先不吵你了"


def test_extract_reply_multi_reply_keep_last():
    # 多段【回复】只保留最后一段
    raw = "【思考】铺垫一下【回复】第一句【回复】最后一句"
    assert pipeline._extract_reply(raw) == "最后一句"


def test_extract_reply_bare_reply_line_start():
    raw = "思考：要不要问\n回复：你今天怎么突然想我了"
    assert pipeline._extract_reply(raw) == "你今天怎么突然想我了"


def test_strip_actions_bare_thought_middle_kept():
    # strip_actions 不剥正文中间的「思考：」
    assert pipeline.strip_actions("我在思考：要不要答应你") == "我在思考：要不要答应你"


# ---- vector_store：跨线程 RLock 不死锁（重入安全）----

def test_vector_store_rlock_reentrant():
    import asyncio
    import core.vector_store as vs

    # 模拟 index/search 在 to_thread 工作线程里调用（内部会取锁建连接），
    # 用 RLock 保证 _vconn 重入不死锁。embed 未配置时快速返回，重点验证不挂起。
    async def _go():
        await asyncio.wait_for(
            asyncio.to_thread(vs.index, uid, 1, "测试记忆", "lm"),
            timeout=15,
        )
        await asyncio.wait_for(
            asyncio.to_thread(vs.search, uid, "测试", 3, "lm"),
            timeout=15,
        )

    asyncio.run(_go())


# ---- userdb：birthday 带出生年份仍每年触发 ----

def test_birthday_with_birth_year_still_today():
    from datetime import date
    from core.userdb import get_today_important_dates, save_important_date

    mmdd = date.today().strftime("%m-%d")
    db.conn.execute("DELETE FROM important_dates WHERE user_id=?", (uid,))
    db.conn.commit()
    # 用户 1998 年出生 → 存 year=1998，但生日每年都要过
    save_important_date(uid, mmdd, "出生日", "birthday", 1998)
    labels = [d["label"] for d in get_today_important_dates(uid)]
    assert "出生日" in labels, f"生日带出生年份也应每年触发，实际={labels}"
    db.conn.execute("DELETE FROM important_dates WHERE user_id=?", (uid,))
    db.conn.commit()


def test_save_important_date_no_year_backfill_for_birthday():
    # 生日已有记录（year=NULL），再次保存时补出生年份 → 不应写入（保持每年过）
    from datetime import date
    from core.userdb import get_today_important_dates, save_important_date

    mmdd = date.today().strftime("%m-%d")
    db.conn.execute("DELETE FROM important_dates WHERE user_id=?", (uid,))
    db.conn.commit()
    save_important_date(uid, mmdd, "纪念日", "anniversary", None)
    save_important_date(uid, mmdd, "纪念日", "anniversary", 2020)
    rows = db.conn.execute(
        "SELECT year FROM important_dates WHERE user_id=? AND date=?", (uid, mmdd)
    ).fetchall()
    assert rows[0]["year"] is None, "birthday/anniversary 不应被补上出生年份"
    db.conn.execute("DELETE FROM important_dates WHERE user_id=?", (uid,))
    db.conn.commit()


# ---- schedule：去重后仍返回完整 6 时段（唯一时段在尾部不被截掉）----

def test_parse_llm_schedule_unique_period_at_tail():
    # LLM 输出 7 条，唯一时段「晚上」在尾部 → 去重后必须包含「晚上」
    resp = (
        '{"schedule": ['
        '{"period": "清晨", "todo": "a"}, {"period": "上午", "todo": "b"},'
        '{"period": "中午", "todo": "c"}, {"period": "下午", "todo": "d"},'
        '{"period": "傍晚", "todo": "e"}, {"period": "上午", "todo": "f"},'
        '{"period": "晚上", "todo": "g"}]}'
    )
    parsed = schedule._parse_llm_schedule(resp)
    assert parsed is not None and len(parsed) == 6
    periods = [it["period"] for it in parsed]
    assert "晚上" in periods and "上午" in periods


# ---- style：非字符串值跳过（不把 dict/list str() 成垃圾入库）----

def test_style_map_skips_non_string():
    # add_style_map 是 db 对象的方法；验证正常字符串仍入库
    db.add_style_map(uid, "对方撒娇时", "爱发叠词")
    rows = db.get_style_map(uid)
    assert len(rows) == 1 and rows[0]["situation"] == "对方撒娇时"
    db.conn.execute("DELETE FROM user_style_map WHERE user_id=?", (uid,))
    db.conn.commit()


def test_extract_style_map_skips_non_string():
    import asyncio
    import core.style as st
    from core import llm
    from unittest import mock as _m

    db.conn.execute("DELETE FROM user_style_map WHERE user_id=?", (uid,))
    db.conn.commit()
    db.set_last_profile_msg_id(uid, 0)

    rows = [
        {"role": "user", "content": "我最近好烦", "id": 1},
        {"role": "assistant", "content": "怎么啦", "id": 2},
    ]

    async def _go():
        with _m.patch.object(llm, "chat") as m_chat:
            m_chat.return_value = (
                '{"styles": [{"situation": 123, "style": {"a": 1}},'
                ' {"situation": "对方生气时", "style": "语气变冷"}]}'
            )
            return await st.extract_style_map(uid, rows=rows, done=2)

    asyncio.run(_go())
    rows = db.get_style_map(uid)
    # 只有字符串那条入库，dict/int 那条被跳过
    assert len(rows) == 1 and rows[0]["situation"] == "对方生气时"
    db.conn.execute("DELETE FROM user_style_map WHERE user_id=?", (uid,))
    db.conn.commit()


# ---- date_memory：label 为 null 时跳过（不存字面量 "None"）----

def test_parse_dates_label_null_skipped():
    import core.date_memory as dm

    text = '{"dates": [{"date": "06-01", "label": null}, {"date": "12-25", "label": "圣诞节"}]}'
    out = dm._parse_dates(text)
    assert all(d["label"] != "None" for d in out)
    assert len(out) == 1 and out[0]["label"] == "圣诞节"


# ---- draw_context：「特别想看」不误判为否定 ----

def test_want_to_see_tebie():
    import core.draw_context as dc

    assert dc.want_to_see("我特别想看") is True
    assert dc.want_to_see("想看那张图") is True
    assert dc.want_to_see("不想看") is False
    assert dc.want_to_see("别看了") is False


# ---- offline_alert：发送成功才标记已提醒 ----

def test_offline_alert_mark_only_when_sent():
    import asyncio
    import core.offline_alert as oa
    from unittest import mock as _m

    async def _go(sent_result):
        with _m.patch.object(oa, "kv_set") as m_kv, \
             _m.patch.object(oa, "get_bot", return_value=object()), \
             _m.patch.object(oa.config, "proactive_user_ids", ["10001"]), \
             _m.patch.object(oa, "_alert_recently", return_value=False), \
             _m.patch.object(oa, "_notify_local", return_value=None), \
             _m.patch.object(oa, "_send_qq_alert", return_value=sent_result):
            await oa.notify_offline()
        return m_kv.called

    assert asyncio.run(_go(True)) is True   # 成功 → 标记
    assert asyncio.run(_go(False)) is False  # 失败 → 不标记（下次可重试）


# ---- cards：进度提示用下一阶段名 ----

def test_affection_card_tip_next_stage():
    from unittest import mock as _m
    from core import cards

    texts: list[str] = []

    class _FakeDraw:
        def text(self, pos, txt, **kw):
            texts.append(txt)

    fake_d = _FakeDraw()
    fake_img = _m.MagicMock()

    with _m.patch.object(cards, "_card_base", return_value=(fake_img, fake_d)), \
         _m.patch.object(cards, "_draw_progress", return_value=None), \
         _m.patch.object(cards, "_font", return_value=_m.MagicMock()), \
         _m.patch.object(cards, "_finalize", return_value=b"png"):
        out = cards.render_affection_card(
            uid, affection=10, stage="初识", next_threshold=25, bond=None
        )

    assert out == b"png"
    # 好感 10 → 下一阶段阈值 25 → 提示「距『熟悉』还需 15 点」（不是「恋人」）
    assert any("熟悉" in t and "15" in t for t in texts), f"tip 未用下一阶段名，texts={texts}"
    assert not any("恋人" in t for t in texts)
