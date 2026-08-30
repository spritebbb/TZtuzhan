# -*- coding: utf-8 -*-
"""菟菚 Web UI 管理面板 —— 覆盖菟菚全部功能。

独立进程（python webui.py），FastAPI + 纯 Python HTML 渲染。
零新依赖（fastapi/uvicorn 已由 nonebot2 依赖链提供）。
端口 8800（避开 NapCat 6099 / Maibot 8001 / WS 3001）。

页面：
- 📊 仪表盘：好感度/心情/阶段/羁绊/画像/口头禅/风格/表情/今日消息/特殊日子统计
- 🔧 功能开关：全部功能即时开关
- 💕 好感度：当前值+阶段+羁绊+进度条+好感度日志+调节
- 🎭 心情：当前心情+描述+调节
- 📅 特殊日子：查看/添加/删除
- 🧠 记忆：长期记忆+事实 查看/删除
- 👤 画像 / 🗣️ 口头禅 / 🎨 风格 / 😂 表情：管理
- 💬 对话：最近聊天记录
- 📋 日志：bot/watchdog 日志尾部
- ⚙️ 系统：配置状态（LLM/识图/生图/搜索/天气/主动）与运行信息
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
from datetime import date, datetime
from pathlib import Path

# 确保能找到 core 模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.config import config
from core.features import all_flags, set_flag, FLAG_DEFAULTS

# ---- 数据库（WAL 模式支持 bot 与 webui 多进程并发读写）----
# FastAPI 是多线程服务器，用线程本地连接避免同一连接跨线程竞态。
_db_path = config.data_dir / "bot.db"
_tls = threading.local()


def _get_db() -> sqlite3.Connection:
    conn = getattr(_tls, "conn", None)
    if conn is None:
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        _tls.conn = conn
    return conn


def _q(sql: str, params=()) -> list[dict]:
    return [dict(r) for r in _get_db().execute(sql, params).fetchall()]


def _q1(sql: str, params=()) -> dict | None:
    r = _get_db().execute(sql, params).fetchone()
    return dict(r) if r else None


def _first_uid() -> str:
    r = _q1("SELECT user_id FROM users LIMIT 1")
    return r["user_id"] if r else ""


# ---- 好感度阶段 / 羁绊（与 core.affection 同阈值，避免引入运行期依赖）----
_AFF_STAGES = [(0, "初识"), (20, "熟悉"), (45, "亲密"), (75, "恋人")]
_AFF_BONDS = [(75, "青涩", "刚刚开始的心动"), (85, "热恋", "浓烈的甜蜜与占有欲"), (95, "挚爱", "认定彼此的唯一")]


def _stage_of(aff: int) -> str:
    label = _AFF_STAGES[0][1]
    for t, n in _AFF_STAGES:
        if aff >= t:
            label = n
    return label


def _bond_of(aff: int) -> tuple[str, str] | None:
    if aff < 75:
        return None
    name, desc = _AFF_BONDS[0][1], _AFF_BONDS[0][2]
    for t, n, d in _AFF_BONDS:
        if aff >= t:
            name, desc = n, d
    return name, desc


def _next_stage(aff: int) -> str | None:
    for t, n in _AFF_STAGES:
        if aff < t:
            return f"{n}（{t}）"
    return None


# ---- HTML 模板（@@ 占位符避免花括号转义）----
_CSS = """*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;background:#0f172a;color:#e2e8f0;padding:20px;}
h1{font-size:1.5rem;color:#a78bfa;margin-bottom:20px;}
h2{font-size:1.1rem;color:#c4b5fd;margin-bottom:12px;}
.nav{display:flex;gap:8px;margin-bottom:24px;flex-wrap:wrap;}
.nav a{padding:6px 14px;border-radius:8px;background:#1e293b;color:#94a3b8;text-decoration:none;font-size:0.85rem;}
.nav a:hover{background:#334155;color:#e2e8f0;}
.nav a.active{background:#7c3aed;color:#fff;}
.card{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:16px;}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;}
.stat-item{background:#334155;border-radius:8px;padding:12px;text-align:center;}
.stat-item .val{font-size:1.4rem;font-weight:bold;color:#a78bfa;}
.stat-item .lbl{font-size:0.78rem;color:#94a3b8;margin-top:4px;}
table{width:100%;border-collapse:collapse;font-size:0.88rem;}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid #334155;vertical-align:top;}
th{color:#94a3b8;font-weight:normal;white-space:nowrap;}
tr:hover{background:#1e293b;}
.del-btn{padding:2px 10px;border-radius:4px;background:#dc2626;color:#fff;border:none;cursor:pointer;font-size:0.78rem;}
.btn{padding:6px 16px;border-radius:6px;border:none;cursor:pointer;font-size:0.88rem;}
.btn-primary{background:#7c3aed;color:#fff;}
.btn-primary:hover{background:#6d28d9;}
.btn-green{background:#16a34a;color:#fff;}
.toggle{position:relative;display:inline-block;width:44px;height:24px;vertical-align:middle;}
.toggle input{opacity:0;width:0;height:0;}
.slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#475569;border-radius:12px;transition:.3s;}
.slider::before{content:"";position:absolute;height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;}
.toggle input:checked+.slider{background:#7c3aed;}
.toggle input:checked+.slider::before{transform:translateX(20px);}
.flag-row{display:flex;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid #334155;gap:10px;}
.flag-row:last-child{border:none;}
.flag-row .fname{flex:1;}
.flag-row .fdesc{color:#64748b;font-size:0.78rem;flex:2;}
textarea,select{width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:8px;font-family:inherit;font-size:0.85rem;}
select{width:auto;}
.logs{background:#0f172a;border-radius:6px;padding:12px;font-family:Consolas,monospace;font-size:0.78rem;line-height:1.5;white-space:pre-wrap;word-break:break-all;max-height:520px;overflow-y:auto;}
.msg{padding:6px 10px;border-radius:6px;margin-bottom:6px;font-size:0.85rem;}
.msg-user{background:#1e3a5f;}
.msg-bot{background:#3b1f4e;}
.msg .meta{color:#64748b;font-size:0.75rem;margin-bottom:2px;}
.tag{display:inline-block;padding:1px 8px;border-radius:4px;font-size:0.72rem;margin-right:4px;}
.tag-likes{background:#166534;color:#bbf7d0;}
.tag-dislikes{background:#7f1d1d;color:#fecaca;}
.tag-habits{background:#1e3a8a;color:#bfdbfe;}
.tag-personality{background:#5b21b6;color:#ddd6fe;}
.tag-basic{background:#1e3a5f;color:#bfdbfe;}
.tag-other{background:#334155;color:#cbd5e1;}
.bar{background:#334155;border-radius:6px;height:16px;overflow:hidden;margin:6px 0;}
.bar>div{height:100%;border-radius:6px;background:linear-gradient(90deg,#7c3aed,#ec4899);transition:width .4s;}
.hint{color:#64748b;font-size:0.8rem;margin:4px 0;}
.warn{color:#fbbf24;font-size:0.85rem;}
.ok{color:#4ade80;font-size:0.85rem;}
.form-row{display:flex;gap:8px;margin:8px 0;align-items:center;flex-wrap:wrap;}
.form-row input, .form-row select{background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:7px 10px;}
.footer{text-align:center;color:#475569;font-size:0.78rem;margin-top:24px;}
.code{font-family:Consolas,monospace;background:#0f172a;padding:2px 6px;border-radius:4px;font-size:0.8rem;}
"""

_NAV = [
    ("/", "dash", "📊 仪表盘"),
    ("/features", "feat", "🔧 开关"),
    ("/affection", "aff", "💕 好感度"),
    ("/mood", "mood", "🎭 心情"),
    ("/dates", "dates", "📅 日子"),
    ("/memory", "mem", "🧠 记忆"),
    ("/profile", "prof", "👤 画像"),
    ("/terms", "term", "🗣️ 口头禅"),
    ("/style", "style", "🎨 风格"),
    ("/stickers", "stick", "😂 表情"),
    ("/chat", "chat", "💬 对话"),
    ("/logs", "logs", "📋 日志"),
    ("/config", "cfg", "🔑 配置"),
    ("/system", "sys", "⚙️ 系统"),
]


def _page(title: str, content: str, active: str) -> HTMLResponse:
    nav_parts = []
    for href, a, label in _NAV:
        cls = ' class="active"' if a == active else ""
        nav_parts.append(f'<a href="{href}"{cls}>{label}</a>')
    nav = "".join(nav_parts)
    html = (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        f"<title>菟菚管理面板 · {title}</title><style>{_CSS}</style></head><body>"
        f"<h1>🌿 菟菚管理面板</h1><div class='nav'>{nav}</div>{content}"
        "<div class='footer'>菟菚 · data/bot.db · 独立进程 :8800（仅本机）</div></body></html>"
    )
    return HTMLResponse(html)


def _esc(s) -> str:
    """HTML 转义用户数据，防止面板 XSS。"""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# ---- FastAPI ----
app = FastAPI(title="菟菚管理面板")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    uid = _first_uid()
    if not uid:
        return _page("仪表盘", "<p>暂无用户数据</p>", "dash")
    u = _q1("SELECT * FROM users WHERE user_id=?", (uid,))
    aff = u["affection"]
    stage = _stage_of(aff)
    bond = _bond_of(aff)
    mood_val = u.get("mood_value", 60)

    def cnt(tbl):
        return _q1(f"SELECT COUNT(*) c FROM {tbl} WHERE user_id=?", (uid,))["c"]

    stats = {
        "好感度": (f"{aff}", f"阶段：{stage}"),
        "羁绊": (bond[0] if bond else "—", bond[1] if bond else f"到恋人还需 {75-aff}"),
        "心情": (f"{mood_val}", "0-100"),
        "画像": (str(cnt("user_profile")), "LLM 提炼"),
        "口头禅": (str(cnt("user_terms")), "含黑话"),
        "风格": (str(cnt("user_style_map")), "场景风格"),
        "表情": (str(cnt("stickers")), "收藏"),
        "特殊日子": (str(cnt("important_dates")), "纪念日"),
        "事实": (str(cnt("facts")), "长期事实"),
        "长期记忆": (str(cnt("long_memory")), "条"),
        "今日消息": (str(_q1("SELECT COUNT(*) c FROM messages WHERE user_id=? AND date(ts)=date('now')", (uid,))["c"]), "条"),
        "总消息": (str(_q1("SELECT COUNT(*) c FROM messages WHERE user_id=?", (uid,))["c"]), "条"),
    }
    stat_html = "".join(
        f'<div class="stat-item"><div class="val">{v}</div><div class="lbl">{k} · {d}</div></div>'
        for k, (v, d) in stats.items()
    )
    next_s = _next_stage(aff)
    bar_w = max(3, min(100, aff))
    content = f"""
    <div class="card">
        <h2>👤 {_esc(uid)} · {_esc((u.get('nickname_pref') or '') or '未设置称呼')} · {_esc((u.get('style_profile') or '')[:40])}</h2>
        <div class="stats">{stat_html}</div>
        <div class="bar"><div style="width:{bar_w}%"></div></div>
        <div class="hint">好感度 {aff}/100{(' · 下一阶段：' + next_s) if next_s else ' · 已到最高阶段'}</div>
    </div>
    """
    return _page("仪表盘", content, "dash")


@app.get("/features", response_class=HTMLResponse)
async def features_page():
    flags = all_flags()
    _DESC = {
        "profile_enabled": "LLM 从对话提炼结构化画像并自然引用",
        "terms_enabled": "记住口头禅/黑话并自然使用",
        "style_enabled": "场景化表达风格贴合",
        "emotion_sticker_enabled": "表情按情绪匹配回发",
    }
    rows = "".join(
        f"""
        <div class="flag-row">
            <span class="fname">{_FLAG_NAMES.get(k, k)}</span>
            <span class="fdesc">{_DESC.get(k, '')}</span>
            <label class="toggle">
                <input type="checkbox" {"checked" if v else ""} onchange="fetch('/api/flag/{k}/' + (this.checked?1:0)).then(()=>location.reload())">
                <span class="slider"></span>
            </label>
        </div>
        """
        for k, v in flags.items()
    )
    content = f"""
    <div class="card"><h2>🔧 功能开关 · 点击即时切换（写入 data/feature_flags.json）</h2>{rows}</div>
    """
    return _page("功能开关", content, "feat")


_FLAG_NAMES = {
    "profile_enabled": "👤 用户画像系统",
    "terms_enabled": "🗣️ 口头禅/黑话学习",
    "style_enabled": "🎨 场景化表达风格",
    "emotion_sticker_enabled": "😂 表情包情绪匹配",
}


@app.get("/api/flag/{name}/{value}")
async def toggle_flag(name: str, value: int):
    if name in FLAG_DEFAULTS:
        set_flag(name, bool(value))
    return JSONResponse({"ok": True})


# ---- 💕 好感度 ----
@app.get("/affection", response_class=HTMLResponse)
async def affection_page():
    uid = _first_uid()
    if not uid:
        return _page("好感度", "<p>暂无用户数据</p>", "aff")
    u = _q1("SELECT * FROM users WHERE user_id=?", (uid,))
    aff = u["affection"]
    stage = _stage_of(aff)
    bond = _bond_of(aff)
    logs = _q("SELECT * FROM affection_log WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,))
    bar_w = max(3, min(100, aff))
    log_rows = "".join(
        f'<tr><td>{_esc(r["ts"])}</td><td>{"+" if r["delta"]>0 else ""}{r["delta"]}</td><td>{_esc(r["reason"])}</td></tr>'
        for r in logs
    )
    bond_html = f'<div class="hint">💍 羁绊：{bond[0]} —— {bond[1]}</div>' if bond else ""
    content = f"""
    <div class="card">
        <h2>💕 好感度 · {uid}</h2>
        <div class="stat-item" style="display:inline-block;min-width:120px"><div class="val">{aff}</div><div class="lbl">{stage}</div></div>
        {bond_html}
        <div class="bar"><div style="width:{bar_w}%"></div></div>
        <form action="/affection/set" method="post" class="form-row">
            <input type="number" name="value" min="0" max="100" value="{aff}" style="width:90px">
            <input type="text" name="reason" placeholder="原因（记入日志）" style="width:280px">
            <button class="btn btn-primary" type="submit">设置</button>
        </form>
    </div>
    <div class="card"><h2>📜 好感度变动日志（最近 50 条）</h2>
        <table><tr><th>时间</th><th>变动</th><th>原因</th></tr>{log_rows}</table>
    </div>
    """
    return _page("好感度", content, "aff")


@app.post("/affection/set")
async def affection_set(value: int = Form(...), reason: str = Form("")):
    uid = _first_uid()
    if uid:
        value = max(0, min(100, int(value)))
        old = _q1("SELECT affection FROM users WHERE user_id=?", (uid,))["affection"]
        delta = value - old
        _get_db().execute("UPDATE users SET affection=? WHERE user_id=?", (value, uid))
        if delta != 0:
            _get_db().execute(
                "INSERT INTO affection_log (user_id, delta, reason, ts) VALUES (?,?,?,?)",
                (uid, delta, (reason or "面板手动调节")[:100], datetime.now().isoformat(timespec="seconds")),
            )
        _get_db().commit()
    return RedirectResponse("/affection", status_code=302)


# ---- 🎭 心情 ----
@app.get("/mood", response_class=HTMLResponse)
async def mood_page():
    uid = _first_uid()
    if not uid:
        return _page("心情", "<p>暂无用户数据</p>", "mood")
    u = _q1("SELECT * FROM users WHERE user_id=?", (uid,))
    mood_val = u.get("mood_value", 60)
    updated = u.get("mood_updated_at", "")
    bar_w = max(3, min(100, mood_val))
    content = f"""
    <div class="card">
        <h2>🎭 心情 · {uid}</h2>
        <div class="stat-item" style="display:inline-block;min-width:120px"><div class="val">{mood_val}</div><div class="lbl">0-100</div></div>
        <div class="hint">最近更新：{updated or '从未更新'}</div>
        <div class="bar"><div style="width:{bar_w}%"></div></div>
        <form action="/mood/set" method="post" class="form-row">
            <input type="number" name="value" min="0" max="100" value="{mood_val}" style="width:90px">
            <button class="btn btn-primary" type="submit">设置心情</button>
            <button class="btn btn-green" type="submit" name="reset" value="1">重置为 60</button>
        </form>
        <div class="hint">心情受天气/时段/互动影响自动变化；这里手动覆盖。</div>
    </div>
    """
    return _page("心情", content, "mood")


@app.post("/mood/set")
async def mood_set(value: int = Form(60), reset: str = Form("")):
    uid = _first_uid()
    if uid:
        v = 60 if reset else max(0, min(100, int(value)))
        _get_db().execute(
            "UPDATE users SET mood_value=?, mood_updated_at=? WHERE user_id=?",
            (v, datetime.now().isoformat(timespec="seconds"), uid),
        )
        _get_db().commit()
    return RedirectResponse("/mood", status_code=302)


# ---- 📅 特殊日子 ----
@app.get("/dates", response_class=HTMLResponse)
async def dates_page():
    uid = _first_uid()
    if not uid:
        return _page("日子", "<p>暂无用户数据</p>", "dates")
    rows = _q("SELECT * FROM important_dates WHERE user_id=? ORDER BY date", (uid,))
    _K = {"birthday": "🎂 生日", "anniversary": "💞 纪念日", "other": "📌 其他"}
    items = "".join(
        f'<tr><td>{r["date"]}</td><td>{_esc(r["label"])}</td>'
        f'<td>{_K.get(r["kind"], _esc(r["kind"]))}</td>'
        f'<td>{r["year"] if r["year"] else "每年"}</td>'
        f'<td><form action="/dates/delete/{r["id"]}" method="post" style="display:inline"><button class="del-btn">删除</button></form></td></tr>'
        for r in rows
    )
    today = date.today().strftime("%m-%d")
    content = f"""
    <div class="card">
        <h2>📅 特殊日子 · 共 {len(rows)} 条（今天 {today}）</h2>
        <table><tr><th>日期(MM-DD)</th><th>名称</th><th>类型</th><th>年份</th><th></th></tr>{items}</table>
        <form action="/dates/add" method="post" class="form-row" style="margin-top:12px">
            <input type="text" name="date" placeholder="MM-DD 如 12-25" style="width:110px" required>
            <input type="text" name="label" placeholder="名称 如：我们的纪念日" style="width:200px" required>
            <select name="kind">
                <option value="other">📌 其他</option>
                <option value="birthday">🎂 生日</option>
                <option value="anniversary">💞 纪念日</option>
            </select>
            <input type="number" name="year" placeholder="年份(可选)" style="width:110px">
            <button class="btn btn-primary" type="submit">添加</button>
        </form>
    </div>
    """
    return _page("特殊日子", content, "dates")


@app.post("/dates/add")
async def dates_add(date: str = Form(...), label: str = Form(...), kind: str = Form("other"), year: int = Form(None)):
    uid = _first_uid()
    d = date.strip()
    valid = False
    if len(d) == 5 and d[2] == "-":
        try:
            mm, dd = int(d[:2]), int(d[3:])
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                valid = True
        except ValueError:
            valid = False
    if uid and valid:
        _get_db().execute(
            "INSERT INTO important_dates (user_id, date, label, kind, year, ts) VALUES (?,?,?,?,?,?)",
            (uid, d, label.strip()[:50], kind, year, datetime.now().isoformat(timespec="seconds")),
        )
        _get_db().commit()
    return RedirectResponse("/dates", status_code=302)


@app.post("/dates/delete/{did}")
async def dates_delete(did: int):
    _get_db().execute("DELETE FROM important_dates WHERE id=?", (did,))
    _get_db().commit()
    return RedirectResponse("/dates", status_code=302)


# ---- 🧠 记忆 ----
@app.get("/memory", response_class=HTMLResponse)
async def memory_page():
    uid = _first_uid()
    if not uid:
        return _page("记忆", "<p>暂无用户数据</p>", "mem")
    lmem = _q("SELECT * FROM long_memory WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid,))
    facts = _q("SELECT * FROM facts WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid,))
    lm_rows = "".join(
        f'<tr><td>{_esc(r["ts"])}</td><td>{_esc(r["content"])}</td>'
        f'<td><form action="/memory/lm/delete/{r["id"]}" method="post" style="display:inline"><button class="del-btn">删</button></form></td></tr>'
        for r in lmem
    )
    f_rows = "".join(
        f'<tr><td>{_esc(r["ts"])}</td><td>{_esc(r["content"])}</td>'
        f'<td><form action="/memory/fact/delete/{r["id"]}" method="post" style="display:inline"><button class="del-btn">删</button></form></td></tr>'
        for r in facts
    )
    content = f"""
    <div class="card"><h2>🧠 长期记忆 · 共 {len(lmem)} 条</h2>
        <table><tr><th>时间</th><th>内容</th><th></th></tr>{lm_rows}</table>
    </div>
    <div class="card"><h2>📌 长期事实 · 共 {len(facts)} 条</h2>
        <table><tr><th>时间</th><th>内容</th><th></th></tr>{f_rows}</table>
    </div>
    """
    return _page("记忆", content, "mem")


@app.post("/memory/lm/delete/{mid}")
async def lm_delete(mid: int):
    _get_db().execute("DELETE FROM long_memory WHERE id=?", (mid,))
    _get_db().commit()
    return RedirectResponse("/memory", status_code=302)


@app.post("/memory/fact/delete/{fid}")
async def fact_delete(fid: int):
    _get_db().execute("DELETE FROM facts WHERE id=?", (fid,))
    _get_db().commit()
    return RedirectResponse("/memory", status_code=302)


# ---- 👤 画像 ----
@app.get("/profile", response_class=HTMLResponse)
async def profile_page():
    uid = _first_uid()
    if not uid:
        return _page("画像管理", "<p>暂无用户数据</p>", "prof")
    rows = _q("SELECT * FROM user_profile WHERE user_id=? ORDER BY id", (uid,))
    _CAT = {"basic": "基本信息", "likes": "喜好", "dislikes": "厌恶", "habits": "习惯", "personality": "性格", "other": "其他"}
    _COLORS = {"likes": "tag-likes", "dislikes": "tag-dislikes", "habits": "tag-habits", "personality": "tag-personality", "basic": "tag-basic", "other": "tag-other"}
    items = "".join(
        f'<tr><td><span class="tag {_COLORS.get(r["category"],"tag-other")}">{_CAT.get(r["category"], _esc(r["category"]))}</span></td>'
        f'<td>{_esc(r["content"])}</td>'
        f'<td>{_esc(r["source"])}</td>'
        f'<td><form action="/profile/delete/{r["id"]}" method="post" style="display:inline">'
        f'<button class="del-btn">删除</button></form></td></tr>'
        for r in rows
    )
    content = f"""
    <div class="card"><h2>👤 用户画像 · 共 {len(rows)} 条</h2>
        <table><tr><th>分类</th><th>内容</th><th>来源</th><th></th></tr>{items}</table>
    </div>
    """
    return _page("画像管理", content, "prof")


@app.post("/profile/delete/{pid}")
async def profile_delete(pid: int):
    uid = _first_uid()
    if uid:
        _get_db().execute("DELETE FROM user_profile WHERE user_id=? AND id=?", (uid, pid))
        _get_db().commit()
    return RedirectResponse("/profile", status_code=302)


# ---- 🗣️ 口头禅 ----
@app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    uid = _first_uid()
    if not uid:
        return _page("口头禅管理", "<p>暂无用户数据</p>", "term")
    rows = _q("SELECT * FROM user_terms WHERE user_id=? ORDER BY count DESC, id DESC", (uid,))
    items = "".join(
        f'<tr><td>{"🧊 黑话" if r["category"]=="slang" else "💬 口头禅"}</td>'
        f'<td>{_esc(r["term"])}</td>'
        f'<td>{_esc(r["meaning"] or "-")}</td>'
        f'<td>{r["count"]}</td>'
        f'<td><form action="/terms/delete/{r["id"]}" method="post" style="display:inline">'
        f'<button class="del-btn">删除</button></form></td></tr>'
        for r in rows
    )
    content = f"""
    <div class="card"><h2>🗣️ 口头禅/黑话 · 共 {len(rows)} 条</h2>
        <table><tr><th>类型</th><th>词</th><th>含义</th><th>次数</th><th></th></tr>{items}</table>
    </div>
    """
    return _page("口头禅管理", content, "term")


@app.post("/terms/delete/{tid}")
async def terms_delete(tid: int):
    uid = _first_uid()
    if uid:
        _get_db().execute("DELETE FROM user_terms WHERE user_id=? AND id=?", (uid, tid))
        _get_db().commit()
    return RedirectResponse("/terms", status_code=302)


# ---- 🎨 风格 ----
@app.get("/style", response_class=HTMLResponse)
async def style_page():
    uid = _first_uid()
    if not uid:
        return _page("风格管理", "<p>暂无用户数据</p>", "style")
    rows = _q("SELECT * FROM user_style_map WHERE user_id=? ORDER BY count DESC, id DESC", (uid,))
    style_desc = _q1("SELECT style_profile FROM users WHERE user_id=?", (uid,)) or {}
    sp = (style_desc.get("style_profile") or "") if style_desc else ""
    items = "".join(
        f'<tr><td>{_esc(r["situation"])}</td><td>{_esc(r["style"])}</td><td>{r["count"]}</td>'
        f'<td><form action="/style/delete/{r["id"]}" method="post" style="display:inline">'
        f'<button class="del-btn">删除</button></form></td></tr>'
        for r in rows
    )
    content = f"""
    <div class="card"><h2>🎨 场景化表达风格 · 共 {len(rows)} 条</h2>
        <table><tr><th>场景</th><th>表达方式</th><th>次数</th><th></th></tr>{items}</table>
    </div>
    <div class="card"><h2>📝 整体风格描述（style_profile）</h2>
        <div class="hint">{_esc(sp) or '（暂无）'}</div>
    </div>
    """
    return _page("风格管理", content, "style")


@app.post("/style/delete/{sid}")
async def style_delete(sid: int):
    uid = _first_uid()
    if uid:
        _get_db().execute("DELETE FROM user_style_map WHERE user_id=? AND id=?", (uid, sid))
        _get_db().commit()
    return RedirectResponse("/style", status_code=302)


# ---- 😂 表情 ----
@app.get("/stickers", response_class=HTMLResponse)
async def stickers_page():
    uid = _first_uid()
    if not uid:
        return _page("表情管理", "<p>暂无用户数据</p>", "stick")
    rows = _q("SELECT * FROM stickers WHERE user_id=? ORDER BY count DESC, id DESC", (uid,))
    items = "".join(
        f'<tr><td>{r["id"]}</td><td style="max-width:260px;overflow:hidden;text-overflow:ellipsis">{_esc(r["desc"][:80])}</td>'
        f'<td>{_esc(r["emotion"] or "-")}</td><td>{r["count"]}</td></tr>'
        for r in rows
    )
    content = f"""
    <div class="card"><h2>😂 表情收藏 · 共 {len(rows)} 张</h2>
        <table><tr><th>ID</th><th>描述</th><th>情绪标签</th><th>次数</th></tr>{items}</table>
    </div>
    """
    return _page("表情管理", content, "stick")


# ---- 💬 对话 ----
@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    uid = _first_uid()
    if not uid:
        return _page("对话记录", "<p>暂无用户数据</p>", "chat")
    rows = _q("SELECT * FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid,))
    rows.reverse()
    msgs = "".join(
        f'<div class="msg {"msg-user" if r["role"]=="user" else "msg-bot"}">'
        f'<div class="meta">{"你" if r["role"]=="user" else "菟菚"} · {_esc(r["ts"])}</div>{_esc(r["content"])}</div>'
        for r in rows
    )
    content = f"""
    <div class="card"><h2>💬 最近对话（最近 100 条）</h2>{msgs}</div>
    """
    return _page("对话记录", content, "chat")


# ---- 📋 日志 ----
@app.get("/logs", response_class=HTMLResponse)
async def logs_page():
    lines = []
    for name in ("bot.log", "bot.err.log", "bot.out.log", "watchdog.log"):
        p = config.data_dir / name
        if p.exists():
            try:
                tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
                lines.append(f"──── {name} ────\n" + "\n".join(tail))
            except Exception:
                pass
    content = f"""
    <div class="card"><h2>📋 日志（最近 60 行）</h2>
        <div class="logs">{_esc(chr(10).join(lines))}</div>
    </div>
    """
    return _page("日志", content, "logs")


# ---- ⚙️ 系统 ----
@app.get("/system", response_class=HTMLResponse)
async def system_page():
    uid = _first_uid()
    u = _q1("SELECT * FROM users WHERE user_id=?", (uid,)) if uid else None
    # 配置状态（不暴露 key 值，只显示是否配置）
    checks = [
        ("对话 LLM", bool(config.llm_api_key), f"模型 {config.llm_model}"),
        ("识图 Vision", bool(config.vision_api_key), "配置了才识别图片"),
        ("图像生成", bool(config.image_api_key), "配置了才有 /画"),
        ("联网搜索", config.search_enabled and bool(config.search_api_key), f"引擎 {config.search_engine}"),
        ("心情天气", bool(config.mood_city), f"城市 {config.mood_city or '未配置'}"),
        ("主动消息", bool(config.proactive_user_ids), "已配置触发对象"),
        ("语义记忆", config.memory_semantic, "MEMORY_SEMANTIC"),
    ]
    cfg_rows = "".join(
        f'<tr><td>{name}</td><td>{"✅" if ok else "❌"}</td><td>{desc}</td></tr>'
        for name, ok, desc in checks
    )
    user_rows = ""
    if u:
        user_rows = "".join(
            f"<tr><td>{_esc(k)}</td><td>{_esc(v) if v is not None else '—'}</td></tr>"
            for k, v in u.items() if k not in ("user_id",)
        )
    version = "v1.3.0"
    content = f"""
    <div class="card"><h2>⚙️ 系统 · 菟菚 {version}</h2>
        <table><tr><th>项目</th><th>状态</th><th>说明</th></tr>{cfg_rows}</table>
    </div>
    <div class="card"><h2>👤 用户数据（users 表）</h2>
        <table><tr><th>字段</th><th>值</th></tr>{user_rows}</table>
    </div>
    <div class="card"><h2>📁 数据位置</h2>
        <div class="hint">数据库：<span class="code">{_db_path}</span></div>
        <div class="hint">功能开关：<span class="code">{config.data_dir / 'feature_flags.json'}</span></div>
        <div class="hint">表情收藏：<span class="code">{config.data_dir / 'stickers'}</span></div>
    </div>
    """
    return _page("系统", content, "sys")


# ---- 🔑 配置 API（查看 / 编辑 .env）----
# 仅暴露白名单内配置项（含 API key 等），避免把全部环境变量暴露给面板。
# key 值一律掩码显示（sk-****abcd），防止面板内容泄露密钥。
_CONFIG_ENV_PATH = Path(__file__).resolve().parent / ".env"

# (env键, 显示名, 分组, 类型: str/bool/secret, 说明)
_CONFIG_SCHEMA = [
    ("LLM_BASE_URL", "对话接口地址", "对话 LLM", "str", "OpenAI 兼容端点，如 https://api.deepseek.com/v1"),
    ("LLM_API_KEY", "对话 API Key", "对话 LLM", "secret", "核心必填；sk- 开头"),
    ("LLM_MODEL", "对话模型", "对话 LLM", "str", "如 deepseek-chat"),
    ("LLM_TEMPERATURE", "采样温度", "对话 LLM", "str", "0~1，越大越随机；默认 0.8"),
    ("LLM_MAX_TOKENS", "单次最大 token", "对话 LLM", "str", "默认 500"),
    ("VISION_BASE_URL", "识图接口地址", "识图 Vision", "str", "独立视觉模型端点；留空沿用对话端点"),
    ("VISION_API_KEY", "识图 API Key", "识图 Vision", "secret", "不配置则识图关闭"),
    ("VISION_MODEL", "识图模型", "识图 Vision", "str", "如 qwen-vl-max；留空关闭识图"),
    ("IMAGE_BASE_URL", "生图接口地址", "图像生成", "str", "默认 SiliconFlow"),
    ("IMAGE_API_KEY", "生图 API Key", "图像生成", "secret", "不配置则 /画 不可用"),
    ("IMAGE_MODEL", "生图模型", "图像生成", "str", "如 Qwen/Qwen-Image"),
    ("SEARCH_ENABLED", "联网搜索开关", "联网搜索", "bool", "1 开 / 0 关"),
    ("SEARCH_ENGINE", "搜索引擎", "联网搜索", "str", "bing / ddg / bocha"),
    ("SEARCH_API_KEY", "搜索 API Key", "联网搜索", "secret", "博查 key（可选，填了优先用）"),
    ("MOOD_CITY", "心情天气城市", "心情系统", "str", "填城市如「北京」；留空按时间段兜底"),
    ("MEMORY_SEMANTIC", "语义记忆检索", "记忆", "bool", "1 开 / 0 关（回退关键词检索）"),
    ("DEBOUNCE_SECONDS", "消息去抖（秒）", "回复节奏", "str", "连发合并窗口；默认 4.0"),
    ("DELAY_JITTER", "延迟抖动", "回复节奏", "str", "真人感随机延迟比例；默认 0.4"),
    ("THINK_DELAY", "酝酿延迟（秒）", "回复节奏", "str", "默认 2.0"),
    ("SEND_INTERVAL", "发送间隔（秒）", "回复节奏", "str", "默认 3.0"),
    ("PROACTIVE_USER_ID", "主动消息对象", "主动消息", "str", "逗号分隔多个 QQ；留空对最后说话的人发"),
    ("PROACTIVE_CHECK_MINUTES", "检查间隔（分）", "主动消息", "str", "默认 15"),
    ("PROACTIVE_IDLE_HOURS", "久别阈值（时）", "主动消息", "str", "默认 4"),
    ("PROACTIVE_COOLDOWN_HOURS", "冷却（时）", "主动消息", "str", "默认 8"),
]


def _is_secret_key(key: str) -> bool:
    """判断配置项是否为密钥（掩码显示/保存）。"""
    for k, _, _, typ, _ in _CONFIG_SCHEMA:
        if k == key:
            return typ == "secret"
    return "KEY" in key.upper() or "TOKEN" in key.upper()


def _read_env_map() -> dict[str, str]:
    """读取 .env 的 KEY=VALUE 映射（忽略注释与空行）。"""
    if not _CONFIG_ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for line in _CONFIG_ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    except Exception:
        pass
    return out


def _mask_secret(v: str) -> str:
    """掩码密钥：sk-****abcd。空值显示为空。"""
    if not v:
        return ""
    if len(v) <= 8:
        return "****"
    return v[:3] + "****" + v[-4:]


def _write_env_updates(updates: dict[str, str]) -> tuple[int, str]:
    """把 {KEY: value} 写回 .env（保留注释与顺序；缺失键追加到末尾）。

    返回 (写入条数, 错误消息)。
    """
    try:
        lines = _CONFIG_ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return 0, f"读取 .env 失败：{e}"
    if not lines:
        lines = []
    written = 0
    seen: set[str] = set()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k = s.partition("=")[0].strip()
        if k in updates:
            lines[i] = f"{k}={updates[k]}"
            seen.add(k)
            written += 1
    # 文件里没有的键追加到末尾（自动补充分组）
    missing = [k for k in updates if k not in seen]
    for k in missing:
        lines.append(f"{k}={updates[k]}")
        written += 1
    try:
        _CONFIG_ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        return 0, f"写入 .env 失败：{e}"
    return written, ""


@app.get("/api/config")
async def api_config():
    """返回可配置项当前值（密钥掩码）。"""
    env = _read_env_map()
    items = []
    for key, label, group, typ, desc in _CONFIG_SCHEMA:
        val = env.get(key, "")
        shown = _mask_secret(val) if typ == "secret" else val
        items.append({
            "key": key, "label": label, "group": group, "type": typ,
            "desc": desc, "value": shown, "configured": bool(val),
        })
    return JSONResponse({"ok": True, "items": items, "env_path": str(_CONFIG_ENV_PATH)})


@app.post("/api/config")
async def api_config_save(request: Request):
    """保存配置到 .env（密钥为空/掩码不变则保留原值）。

    支持 JSON body（{key: value}）与表单（application/x-www-form-urlencoded）。
    """
    updates: dict[str, str] = {}
    raw = await request.body()
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            data = json.loads(raw)
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON 解析失败"}, status_code=400)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    updates[k] = v.strip()
    else:
        # 表单：解析 urlencoded body（键=值 对）
        from urllib.parse import parse_qs

        for k, vals in parse_qs(raw.decode("utf-8", "replace")).items():
            updates[k] = (vals[0] or "").strip()

    if not updates:
        return JSONResponse({"ok": False, "error": "没有收到配置项"}, status_code=400)

    env = _read_env_map()
    final: dict[str, str] = {}
    schema_keys = {k for k, *_ in _CONFIG_SCHEMA}
    for key, val in updates.items():
        if key not in schema_keys:
            continue  # 只允许白名单键
        if val == "":
            continue  # 空值 = 不修改
        # 密钥：若提交的是掩码串（用户没改），保留原值
        old = env.get(key, "")
        if _is_secret_key(key) and val == _mask_secret(old) and old:
            continue
        final[key] = val
    if not final:
        return JSONResponse({"ok": True, "updated": 0, "msg": "没有需要保存的修改"})
    n, err = _write_env_updates(final)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=500)
    return JSONResponse({"ok": True, "updated": n, "msg": f"已写入 {n} 项配置"})


@app.get("/config", response_class=HTMLResponse)
async def config_page():
    """🔑 配置页：分组展示可编辑的 .env 配置（密钥掩码）。"""
    env = _read_env_map()
    groups: dict[str, list] = {}
    for key, label, group, typ, desc in _CONFIG_SCHEMA:
        val = env.get(key, "")
        groups.setdefault(group, []).append((key, label, typ, desc, val))

    blocks = []
    for group, items in groups.items():
        rows = []
        for key, label, typ, desc, val in items:
            shown = _mask_secret(val) if typ == "secret" else val
            placeholder = ("（已配置，留空保留）" if val else "未配置")
            if typ == "bool":
                checked = 'checked' if val in ("1", "true", "True", "on") else ''
                ctrl = (
                    f'<select name="{key}" style="max-width:220px">'
                    f'<option value="1"{" selected" if checked else ""}>开</option>'
                    f'<option value="0"{" selected" if not checked else ""}>关</option>'
                    f'</select>'
                )
            else:
                ph = f' placeholder="{placeholder}"' if (typ == "secret" and val) else f' placeholder="{placeholder}"'
                ctrl = (
                    f'<input type="text" name="{key}" value="{_esc(shown) if not (typ == "secret" and val) else ""}"'
                    f'{ph} style="max-width:340px">'
                )
            rows.append(
                f'<tr><td style="white-space:nowrap">{label}<div class="hint">{_esc(desc)}</div></td>'
                f'<td style="width:60%">{ctrl}</td>'
                f'<td>{"✅" if val else "❌"}<div class="hint">{("已配置" if val else "未配置")}</div></td></tr>'
            )
        blocks.append(
            f'<div class="card"><h2>{group}</h2>'
            f'<table>{"" .join(rows)}</table></div>'
        )

    content = f"""
    <div class="card">
        <h2>🔑 配置 API · <span class="code">.env</span></h2>
        <div class="hint">密钥只显示掩码（sk-****abcd）；留空表示不修改该项。保存后写入 <span class="code">{_esc(str(_CONFIG_ENV_PATH))}</span>，<b>重启 bot 后生效</b>。</div>
        <form id="cfgform">
            {'' .join(blocks)}
            <div class="form-row">
                <button class="btn btn-primary" type="submit">💾 保存配置</button>
                <button class="btn" type="button" onclick="location.reload()">↻ 刷新</button>
            </div>
        </form>
        <div id="result" class="hint"></div>
    </div>
    <script>
    document.getElementById('cfgform').addEventListener('submit', async (e) => {{
        e.preventDefault();
        const fd = new FormData(e.target);
        const data = {{}};
        fd.forEach((v, k) => {{ if (String(v).trim() !== '') data[k] = String(v).trim(); }});
        const res = await fetch('/api/config', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(data)}});
        const r = await res.json();
        const box = document.getElementById('result');
        box.textContent = r.ok ? '✅ ' + r.msg + '（重启 bot 生效）' : '❌ ' + (r.error || '保存失败');
        box.style.color = r.ok ? '#4ade80' : '#f87171';
    }});
    </script>
    """
    return _page("配置", content, "cfg")



if __name__ == "__main__":
    port = int(os.getenv("WEBUI_PORT", "8800"))
    print(f"🌿 菟菚管理面板 → http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")