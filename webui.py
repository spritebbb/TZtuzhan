# -*- coding: utf-8 -*-
"""菟菚 Web UI 管理面板。

独立进程（python webui.py），FastAPI + 纯 Python HTML 渲染。
零新依赖（fastapi/uvicorn 已由 nonebot2 依赖链提供）。
端口 8800（避开 NapCat 6099 / Maibot 8001 / WS 3001）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

# 确保能找到 core 模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.config import config
from core.features import all_flags, set_flag, FLAG_DEFAULTS

# ---- 数据库（WAL 模式支持 bot 与 webui 多进程并发读写）----
_db_path = config.data_dir / "bot.db"
_conn: sqlite3.Connection | None = None


def _get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_db_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA busy_timeout = 5000")
    return _conn


def _q(sql: str, params=()) -> list[dict]:
    return [dict(r) for r in _get_db().execute(sql, params).fetchall()]


def _q1(sql: str, params=()) -> dict | None:
    r = _get_db().execute(sql, params).fetchone()
    return dict(r) if r else None


def _first_uid() -> str:
    r = _q1("SELECT user_id FROM users LIMIT 1")
    return r["user_id"] if r else ""


# ---- 好感度阶段（轻度复用 affection 逻辑，避免依赖）----
_AFFECTION_STAGES = [
    (0, "初识", "#9ca3af"),
    (20, "熟悉", "#60a5fa"),
    (45, "亲密", "#f472b6"),
    (75, "恋人", "#ef4444"),
]


def _stage_of(affection: int) -> tuple[str, str]:
    for threshold, name, color in reversed(_AFFECTION_STAGES):
        if affection >= threshold:
            return name, color
    return "初识", "#9ca3af"


# ---- HTML 模板 ----
_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>菟菚管理面板</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;padding:20px;}}
h1{{font-size:1.5rem;color:#a78bfa;margin-bottom:20px;}}
h2{{font-size:1.1rem;color:#c4b5fd;margin-bottom:12px;}}
.nav{{display:flex;gap:8px;margin-bottom:24px;flex-wrap:wrap;}}
.nav a{{padding:6px 16px;border-radius:8px;background:#1e293b;color:#94a3b8;text-decoration:none;font-size:0.9rem;}}
.nav a:hover{{background:#334155;color:#e2e8f0;}}
.nav a.active{{background:#7c3aed;color:#fff;}}
.card{{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:16px;}}
.stats{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;}}
.stat-item{{background:#334155;border-radius:8px;padding:12px;text-align:center;}}
.stat-item .val{{font-size:1.5rem;font-weight:bold;color:#a78bfa;}}
.stat-item .lbl{{font-size:0.8rem;color:#94a3b8;margin-top:4px;}}
table{{width:100%;border-collapse:collapse;font-size:0.9rem;}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #334155;}}
th{{color:#94a3b8;font-weight:normal;}}
tr:hover{{background:#1e293b;}}
.del-btn{{padding:2px 10px;border-radius:4px;background:#dc2626;color:#fff;border:none;cursor:pointer;font-size:0.8rem;}}
.btn{{padding:6px 16px;border-radius:6px;border:none;cursor:pointer;font-size:0.9rem;}}
.btn-primary{{background:#7c3aed;color:#fff;}}
.btn-primary:hover{{background:#6d28d9;}}
.toggle{{position:relative;display:inline-block;width:44px;height:24px;}}
.toggle input{{opacity:0;width:0;height:0;}}
.slider{{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#475569;border-radius:12px;transition:.3s;}}
.slider::before{{content:"";position:absolute;height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;}}
.toggle input:checked+.slider{{background:#7c3aed;}}
.toggle input:checked+.slider::before{{transform:translateX(20px);}}
.flag-row{{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #334155;}}
.flag-row:last-child{{border:none;}}
textarea{{width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:8px;font-family:monospace;font-size:0.85rem;}}
.logs{{background:#0f172a;border-radius:6px;padding:12px;font-family:monospace;font-size:0.8rem;line-height:1.5;white-space:pre-wrap;word-break:break-all;max-height:500px;overflow-y:auto;}}
.msg{{padding:6px 10px;border-radius:6px;margin-bottom:6px;font-size:0.85rem;}}
.msg-user{{background:#1e3a5f;}}
.msg-bot{{background:#3b1f4e;}}
.tag{{display:inline-block;padding:1px 8px;border-radius:4px;font-size:0.75rem;margin-right:4px;}}
.tag-likes{{background:#166534;color:#bbf7d0;}}
.tag-dislikes{{background:#7f1d1d;color:#fecaca;}}
.tag-habits{{background:#1e3a8a;color:#bfdbfe;}}
.tag-personality{{background:#5b21b6;color:#ddd6fe;}}
.tag-basic{{background:#1e3a5f;color:#bfdbfe;}}
.footer{{text-align:center;color:#475569;font-size:0.8rem;margin-top:24px;}}
</style>
</head>
<body>
<h1>🌿 菟菚管理面板</h1>
<div class="nav">
  <a href="/" class="{active_dash}">📊 仪表盘</a>
  <a href="/features" class="{active_feat}">🔧 功能开关</a>
  <a href="/profile" class="{active_prof}">👤 画像</a>
  <a href="/terms" class="{active_term}">🗣️ 口头禅</a>
  <a href="/style" class="{active_style}">🎨 风格</a>
  <a href="/stickers" class="{active_stick}">😂 表情</a>
  <a href="/logs" class="{active_logs}">📋 日志</a>
  <a href="/chat" class="{active_chat}">💬 对话</a>
</div>
{content}
<div class="footer">菟菚 v1.1.1 · data/bot.db · uvicorn :8800</div>
</body>
</html>"""


def _page(title: str, content: str, active: str) -> HTMLResponse:
    html = _HTML.replace("{content}", content)
    # CSS 里的双花括号（{{ }}）还原为单花括号（{ }）
    html = html.replace("{{", "{").replace("}}", "}")
    for a in ("dash", "feat", "prof", "term", "style", "stick", "logs", "chat"):
        html = html.replace(f"{{active_{a}}}", "active" if a == active else "")
    return HTMLResponse(html)


# ---- FastAPI ----
app = FastAPI(title="菟菚管理面板")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    uid = _first_uid()
    if not uid:
        return _page("仪表盘", "<p>暂无用户数据</p>", "dash")
    user = _q1("SELECT * FROM users WHERE user_id=?", (uid,))
    if not user:
        return _page("仪表盘", "<p>暂无用户数据</p>", "dash")

    stage, scolor = _stage_of(user["affection"])
    profile_count = _q1("SELECT COUNT(*) as c FROM user_profile WHERE user_id=?", (uid,))["c"]
    terms_count = _q1("SELECT COUNT(*) as c FROM user_terms WHERE user_id=?", (uid,))["c"]
    style_count = _q1("SELECT COUNT(*) as c FROM user_style_map WHERE user_id=?", (uid,))["c"]
    sticker_count = _q1("SELECT COUNT(*) as c FROM stickers WHERE user_id=?", (uid,))["c"]
    msg_today = _q1("SELECT COUNT(*) as c FROM messages WHERE user_id=? AND date(ts)=date('now')", (uid,))["c"]
    flags = all_flags()

    content = f"""
    <div class="card">
        <h2>👤 {uid} · {user.get('nickname_pref', '') or '未设置称呼'}</h2>
        <div class="stats">
            <div class="stat-item"><div class="val">{user['affection']}</div><div class="lbl">好感度</div></div>
            <div class="stat-item"><div class="val" style="color:{scolor}">{stage}</div><div class="lbl">阶段</div></div>
            <div class="stat-item"><div class="val">{user.get('mood_value', 60)}</div><div class="lbl">心情</div></div>
            <div class="stat-item"><div class="val">{profile_count}</div><div class="lbl">画像条目</div></div>
            <div class="stat-item"><div class="val">{terms_count}</div><div class="lbl">口头禅</div></div>
            <div class="stat-item"><div class="val">{style_count}</div><div class="lbl">风格条目</div></div>
            <div class="stat-item"><div class="val">{sticker_count}</div><div class="lbl">表情收藏</div></div>
            <div class="stat-item"><div class="val">{msg_today}</div><div class="lbl">今日消息</div></div>
        </div>
    </div>
    <div class="card">
        <h2>🔧 功能开关状态</h2>
        <table>
            <tr><th>功能</th><th>状态</th></tr>
            <tr><td>👤 用户画像</td><td>{"✅ 开" if flags["profile_enabled"] else "❌ 关"}</td></tr>
            <tr><td>🗣️ 口头禅/黑话</td><td>{"✅ 开" if flags["terms_enabled"] else "❌ 关"}</td></tr>
            <tr><td>🎨 场景风格</td><td>{"✅ 开" if flags["style_enabled"] else "❌ 关"}</td></tr>
            <tr><td>😂 表情情绪匹配</td><td>{"✅ 开" if flags["emotion_sticker_enabled"] else "❌ 关"}</td></tr>
        </table>
    </div>
    """
    return _page("仪表盘", content, "dash")


@app.get("/features", response_class=HTMLResponse)
async def features_page():
    flags = all_flags()
    rows = "".join(
        f"""
        <div class="flag-row">
            <span>{_FLAG_NAMES.get(k, k)}</span>
            <label class="toggle">
                <input type="checkbox" {"checked" if v else ""} onchange="fetch('/api/flag/{k}/' + (this.checked?1:0)).then(()=>location.reload())">
                <span class="slider"></span>
            </label>
        </div>
        """
        for k, v in flags.items()
    )
    content = f"""
    <div class="card">
        <h2>🔧 功能开关 · 点击即时切换</h2>
        {rows}
    </div>
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


@app.get("/api/affection/{uid}/{value}")
async def set_affection_api(uid: str, value: int):
    """REST API 设置好感度（供 Web UI 调用）。"""
    _get_db().execute(
        "UPDATE users SET affection = MAX(0, MIN(100, ?)) WHERE user_id = ?",
        (value, uid),
    )
    _get_db().commit()
    return JSONResponse({"ok": True})


@app.get("/profile", response_class=HTMLResponse)
async def profile_page():
    uid = _first_uid()
    if not uid:
        return _page("画像管理", "<p>暂无用户数据</p>", "prof")
    rows = _q("SELECT * FROM user_profile WHERE user_id=? ORDER BY id", (uid,))
    _CAT = {"basic": "基本信息", "likes": "喜好", "dislikes": "厌恶", "habits": "习惯", "personality": "性格", "other": "其他"}
    _COLORS = {"likes": "tag-likes", "dislikes": "tag-dislikes", "habits": "tag-habits", "personality": "tag-personality", "basic": "tag-basic"}
    items = "".join(
        f'<tr><td><span class="tag {_COLORS.get(r["category"],"")}">{_CAT.get(r["category"],r["category"])}</span></td>'
        f'<td>{r["content"]}</td>'
        f'<td>{r["source"]}</td>'
        f'<td><form action="/profile/delete/{r["id"]}" method="post" style="display:inline">'
        f'<button class="del-btn">删除</button></form></td></tr>'
        for r in rows
    )
    content = f"""
    <div class="card">
        <h2>👤 用户画像 · 共 {len(rows)} 条</h2>
        <table><tr><th>分类</th><th>内容</th><th>来源</th><th></th></tr>{items}</table>
    </div>
    """
    return _page("画像管理", content, "prof")


@app.post("/profile/delete/{pid}")
async def profile_delete(pid: int):
    uid = _first_uid()
    if not uid:
        return RedirectResponse("/profile", status_code=302)
    _get_db().execute("DELETE FROM user_profile WHERE user_id=? AND id=?", (uid, pid))
    _get_db().commit()
    return RedirectResponse("/profile", status_code=302)


@app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    uid = _first_uid()
    if not uid:
        return _page("口头禅管理", "<p>暂无用户数据</p>", "term")
    rows = _q("SELECT * FROM user_terms WHERE user_id=? ORDER BY count DESC, id DESC", (uid,))
    items = "".join(
        f'<tr><td>{"🧊 黑话" if r["category"]=="slang" else "💬 口头禅"}</td>'
        f'<td>{r["term"]}</td>'
        f'<td>{r["meaning"] or "-"}</td>'
        f'<td>{r["count"]}</td>'
        f'<td><form action="/terms/delete/{r["id"]}" method="post" style="display:inline">'
        f'<button class="del-btn">删除</button></form></td></tr>'
        for r in rows
    )
    content = f"""
    <div class="card">
        <h2>🗣️ 口头禅/黑话 · 共 {len(rows)} 条</h2>
        <table><tr><th>类型</th><th>词</th><th>含义</th><th>次数</th><th></th></tr>{items}</table>
    </div>
    """
    return _page("口头禅管理", content, "term")


@app.post("/terms/delete/{tid}")
async def terms_delete(tid: int):
    uid = _first_uid()
    if not uid:
        return RedirectResponse("/terms", status_code=302)
    _get_db().execute("DELETE FROM user_terms WHERE user_id=? AND id=?", (uid, tid))
    _get_db().commit()
    return RedirectResponse("/terms", status_code=302)


@app.get("/style", response_class=HTMLResponse)
async def style_page():
    uid = _first_uid()
    if not uid:
        return _page("风格管理", "<p>暂无用户数据</p>", "style")
    rows = _q("SELECT * FROM user_style_map WHERE user_id=? ORDER BY count DESC, id DESC", (uid,))
    items = "".join(
        f'<tr><td>{r["situation"]}</td><td>{r["style"]}</td><td>{r["count"]}</td>'
        f'<td><form action="/style/delete/{r["id"]}" method="post" style="display:inline">'
        f'<button class="del-btn">删除</button></form></td></tr>'
        for r in rows
    )
    content = f"""
    <div class="card">
        <h2>🎨 场景化表达风格 · 共 {len(rows)} 条</h2>
        <table><tr><th>场景</th><th>表达方式</th><th>次数</th><th></th></tr>{items}</table>
    </div>
    """
    return _page("风格管理", content, "style")


@app.post("/style/delete/{sid}")
async def style_delete(sid: int):
    uid = _first_uid()
    if not uid:
        return RedirectResponse("/style", status_code=302)
    _get_db().execute("DELETE FROM user_style_map WHERE user_id=? AND id=?", (uid, sid))
    _get_db().commit()
    return RedirectResponse("/style", status_code=302)


@app.get("/stickers", response_class=HTMLResponse)
async def stickers_page():
    uid = _first_uid()
    if not uid:
        return _page("表情管理", "<p>暂无用户数据</p>", "stick")
    rows = _q("SELECT * FROM stickers WHERE user_id=? ORDER BY count DESC, id DESC", (uid,))
    items = "".join(
        f'<tr><td>{r["id"]}</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">{r["desc"][:50]}</td>'
        f'<td>{r["emotion"] or "-"}</td><td>{r["count"]}</td></tr>'
        for r in rows
    )
    content = f"""
    <div class="card">
        <h2>😂 表情收藏 · 共 {len(rows)} 张</h2>
        <table><tr><th>ID</th><th>描述</th><th>情绪标签</th><th>次数</th></tr>{items}</table>
    </div>
    """
    return _page("表情管理", content, "stick")


@app.get("/logs", response_class=HTMLResponse)
async def logs_page():
    lines = []
    for name in ("bot.out.log", "bot.err.log", "watchdog.log"):
        p = config.data_dir / name
        if p.exists():
            try:
                tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
                lines.append(f"── {name} ──\n" + "\n".join(tail))
            except Exception:
                pass
    content = f"""
    <div class="card">
        <h2>📋 日志（最近 50 行）</h2>
        <div class="logs">{chr(10).join(lines)}</div>
    </div>
    """
    return _page("日志", content, "logs")


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    uid = _first_uid()
    if not uid:
        return _page("对话记录", "<p>暂无用户数据</p>", "chat")
    rows = _q("SELECT * FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,))
    rows.reverse()
    msgs = "".join(
        f'<div class="msg {"msg-user" if r["role"]=="user" else "msg-bot"}">'
        f'{"<b>你</b>" if r["role"]=="user" else "<b>菟菚</b>"} · {r["ts"]}<br>{r["content"]}</div>'
        for r in rows
    )
    content = f"""
    <div class="card">
        <h2>💬 最近对话（最近 50 条）</h2>
        {msgs}
    </div>
    """
    return _page("对话记录", content, "chat")


if __name__ == "__main__":
    port = int(os.getenv("WEBUI_PORT", "8800"))
    print(f"🌿 菟菚管理面板 → http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")