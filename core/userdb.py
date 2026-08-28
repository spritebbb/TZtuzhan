"""SQLite 数据层：每用户独立数据。

表：
- users         用户状态（好感度、称呼偏好、恋人确认、首次对话、日期标记）
- messages      会话历史（短期上下文的来源）
- long_memory   长期记忆原文片段（关键词检索）
- facts         LLM 提炼的长期事实（喜好/约定等，带去重）
- user_meta     事实提炼游标等元数据
- affection_log 好感度变动流水
"""
import re
import sqlite3
import time
from datetime import date, datetime

from .config import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    affection       INTEGER NOT NULL DEFAULT 0,
    nickname_pref   TEXT,
    lover_confirm   INTEGER NOT NULL DEFAULT 0,
    first_chat_done INTEGER NOT NULL DEFAULT 0,
    last_chat_date  TEXT,
    last_batch_date TEXT,
    style_profile   TEXT,
    last_proactive  TEXT,
    mood_value      INTEGER NOT NULL DEFAULT 60,
    mood_updated_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    role    TEXT NOT NULL,
    content TEXT NOT NULL,
    ts      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS long_memory (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    ts      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS affection_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    delta   INTEGER NOT NULL,
    reason  TEXT NOT NULL,
    ts      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    ts      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_meta (
    user_id          TEXT PRIMARY KEY,
    last_fact_msg_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kv_store (
    user_id TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS important_dates (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    date    TEXT NOT NULL,     -- 'MM-DD'（如 '12-25'；无年份的每年一次）
    label   TEXT NOT NULL,     -- 事件名，如 '你的生日' / '我们认识的日子'
    kind    TEXT NOT NULL DEFAULT 'other',  -- birthday / anniversary / other
    year    INTEGER,           -- 有年份则存具体年份；无年份 NULL = 每年
    ts      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stickers (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  TEXT NOT NULL,    -- 收藏者（哪个用户发的）
    file     TEXT NOT NULL,    -- 本地缓存文件路径
    url      TEXT NOT NULL,    -- 原始图片 URL
    desc     TEXT NOT NULL DEFAULT '',  -- 视觉模型描述（用于话题匹配回发）
    count    INTEGER NOT NULL DEFAULT 1, -- 该表情被看到/收藏的次数
    ts       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
CREATE INDEX IF NOT EXISTS idx_long_memory_user ON long_memory(user_id, id);
CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_id, id);
CREATE INDEX IF NOT EXISTS idx_dates_user ON important_dates(user_id);
CREATE INDEX IF NOT EXISTS idx_stickers_user ON stickers(user_id);
"""


class UserDB:
    def __init__(self) -> None:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(config.data_dir / "bot.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.executescript(_SCHEMA)
        # 兼容旧库：补上 style_profile 列
        try:
            self.conn.execute("ALTER TABLE users ADD COLUMN style_profile TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self.conn.execute("ALTER TABLE users ADD COLUMN last_proactive TEXT")
        except sqlite3.OperationalError:
            pass
        # 心情系统字段（旧库迁移）
        try:
            self.conn.execute("ALTER TABLE users ADD COLUMN mood_value INTEGER NOT NULL DEFAULT 60")
        except sqlite3.OperationalError:
            pass
        try:
            self.conn.execute("ALTER TABLE users ADD COLUMN mood_updated_at TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    # ---- users ----
    def ensure_user(self, user_id: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
        )
        self.conn.commit()
        return self.get_user(user_id)

    def get_user(self, user_id: str):
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row

    def update_affection(self, user_id: str, delta: int, reason: str) -> None:
        self.conn.execute(
            "UPDATE users SET affection = MAX(0, MIN(100, affection + ?)) WHERE user_id = ?",
            (delta, user_id),
        )
        self.conn.execute(
            "INSERT INTO affection_log (user_id, delta, reason, ts) VALUES (?, ?, ?, ?)",
            (user_id, delta, reason, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def set_nickname(self, user_id: str, name: str) -> None:
        self.conn.execute(
            "UPDATE users SET nickname_pref = ? WHERE user_id = ?", (name, user_id)
        )
        self.conn.commit()

    def get_mood(self, user_id: str) -> tuple[int, str | None]:
        """读取心情值与上次更新时间 (mood, updated_at)。"""
        row = self.conn.execute(
            "SELECT mood_value, mood_updated_at FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return 60, None
        return row["mood_value"] or 60, row["mood_updated_at"]

    def set_mood(self, user_id: str, mood: int) -> None:
        """写入心情值（0-100）并更新时间戳。"""
        mood = max(0, min(100, round(mood)))
        self.conn.execute(
            "UPDATE users SET mood_value = ?, mood_updated_at = ? WHERE user_id = ?",
            (mood, datetime.now().isoformat(timespec="seconds"), user_id),
        )
        self.conn.commit()

    def set_style(self, user_id: str, style: str) -> None:
        """记录 LLM 提炼的对方说话风格（随聊天逐渐更新）。"""
        self.conn.execute(
            "UPDATE users SET style_profile = ? WHERE user_id = ?", (style, user_id)
        )
        self.conn.commit()

    def get_style(self, user_id: str) -> str:
        row = self.conn.execute(
            "SELECT style_profile FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return (row["style_profile"] or "") if row else ""

    def get_last_proactive(self, user_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT last_proactive FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return (row["last_proactive"] or None) if row else None

    def set_last_proactive(self, user_id: str) -> None:
        self.conn.execute(
            "UPDATE users SET last_proactive = ? WHERE user_id = ?",
            (datetime.now().isoformat(timespec="seconds"), user_id),
        )
        self.conn.commit()

    def set_affection_absolute(self, user_id: str, value: int) -> None:
        """直接把好感度设为指定值（0-100），用于手动调节/调试。"""
        value = max(0, min(100, int(value)))
        self.ensure_user(user_id)
        cur = self.get_user(user_id)["affection"]
        self.conn.execute(
            "UPDATE users SET affection = ? WHERE user_id = ?", (value, user_id)
        )
        self.conn.execute(
            "INSERT INTO affection_log (user_id, delta, reason, ts) VALUES (?, ?, ?, ?)",
            (user_id, value - cur, "手动设置", datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        u = self.get_user(user_id)
        if u["affection"] >= 75 and not u["lover_confirm"]:
            self.set_lover_confirm(user_id)

    def set_lover_confirm(self, user_id: str) -> None:
        self.conn.execute(
            "UPDATE users SET lover_confirm = 1 WHERE user_id = ?", (user_id,)
        )
        self.conn.commit()

    def set_first_chat_done(self, user_id: str) -> None:
        self.conn.execute(
            "UPDATE users SET first_chat_done = 1 WHERE user_id = ?", (user_id,)
        )
        self.conn.commit()

    def set_chat_date(self, user_id: str, day: str, batch_day: str | None = None) -> None:
        if batch_day is not None:
            self.conn.execute(
                "UPDATE users SET last_chat_date = ?, last_batch_date = ? WHERE user_id = ?",
                (day, batch_day, user_id),
            )
        else:
            self.conn.execute(
                "UPDATE users SET last_chat_date = ? WHERE user_id = ?", (day, user_id)
            )
        self.conn.commit()

    # ---- messages ----
    def add_message(self, user_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages (user_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (user_id, role, content, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def recent_messages(self, user_id: str, limit: int):
        return self.conn.execute(
            "SELECT role, content FROM messages WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()[::-1]

    def messages_between(self, user_id: str, start: date, end: date):
        return self.conn.execute(
            "SELECT id, role, content, ts FROM messages WHERE user_id = ? "
            "AND date(ts) BETWEEN ? AND ? ORDER BY id",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchall()

    # ---- long memory ----
    def add_long_memory(self, user_id: str, content: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO long_memory (user_id, content, ts) VALUES (?, ?, ?)",
            (user_id, content, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return cur.lastrowid

    def search_long_memory(self, user_id: str, query: str, top_k: int):
        """v1 关键词检索：按中文字符二元组重叠打分，取 top_k。

        重叠阈值与 search_long_memory_multi 一致：短查询（≤2 二元组）要求 2 个命中，
        长查询放宽到 1 个（口语措辞差异容忍），噪声由调用方重排过滤。
        """
        q_bigrams = _bigrams(query)
        if not q_bigrams:
            return []
        rows = self.conn.execute(
            "SELECT id, content, ts FROM long_memory WHERE user_id = ? "
            "ORDER BY id DESC LIMIT 500",
            (user_id,),
        ).fetchall()
        scored = []
        min_overlap = 1 if len(q_bigrams) != 2 else 2
        for r in rows:
            content_bigrams = _bigrams(r["content"])
            overlap = len(q_bigrams & content_bigrams)
            if overlap >= min_overlap:
                scored.append((overlap, r["content"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"content": c} for _, c in scored[:top_k]]

    def search_long_memory_multi(self, user_id: str, queries: list[str], top_k: int):
        """多查询词合并检索：每个查询独立打分后按最高分汇总，取 top_k。

        语义检索的落地方式：LLM 把用户问题扩展成若干关键词/短语，逐一检索，
        比单条原文命中更稳（原句里的口语词常常和存档时的措辞对不上）。

        重叠阈值：短查询（≤2 个二元组，如"下雨天"）要求 2 个二元组全命中；
        长查询（整句/长短语）放宽到 1 个，避免因口语措辞差异漏检——放宽带来的
        噪声由调用方后续的 TF-IDF 重排过滤。
        """
        scored: dict[int, tuple[int, str]] = {}
        for query in queries:
            q_bigrams = _bigrams(query)
            if not q_bigrams:
                continue
            # len==1（2字查询）只能要求1个重叠；len==2（3字）要求2个；
            # len>=3（整句/长短语）放宽到1个（口语措辞差异容忍，噪声由重排过滤）
            min_overlap = 1 if len(q_bigrams) != 2 else 2
            rows = self.conn.execute(
                "SELECT id, content, ts FROM long_memory WHERE user_id = ? "
                "ORDER BY id DESC LIMIT 500",
                (user_id,),
            ).fetchall()
            for r in rows:
                content_bigrams = _bigrams(r["content"])
                overlap = len(q_bigrams & content_bigrams)
                if overlap >= min_overlap and overlap > scored.get(r["id"], (0, ""))[0]:
                    scored[r["id"]] = (overlap, r["content"])
        ranked = sorted(scored.values(), key=lambda x: x[0], reverse=True)
        return [{"content": c} for _, c in ranked[:top_k]]

    # ---- facts（LLM 提炼的长期事实）----
    def add_fact(self, user_id: str, content: str) -> int | None:
        """存一条事实；与已有事实二元组重叠≥50% 视为重复则跳过。

        返回新记录 id；重复/跳过返回 None。
        """
        content = content.strip()
        if not content:
            return None
        q = _bigrams(content)
        rows = self.conn.execute(
            "SELECT content FROM facts WHERE user_id = ? ORDER BY id DESC LIMIT 200",
            (user_id,),
        ).fetchall()
        for r in rows:
            existing = _bigrams(r["content"])
            if q and existing:
                overlap = len(q & existing) / min(len(q), len(existing))
                if overlap >= 0.5:
                    return None
        cur = self.conn.execute(
            "INSERT INTO facts (user_id, content, ts) VALUES (?, ?, ?)",
            (user_id, content, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return cur.lastrowid

    def search_facts(self, user_id: str, query: str, top_k: int):
        """按关键词（二元组）检索事实，取 top_k。

        重叠阈值与 long_memory 检索一致：短查询（≤2 二元组）要求 2 个命中，
        长查询放宽到 1 个（口语措辞差异容忍）。
        """
        q_bigrams = _bigrams(query)
        if not q_bigrams:
            return []
        rows = self.conn.execute(
            "SELECT content FROM facts WHERE user_id = ? ORDER BY id DESC LIMIT 500",
            (user_id,),
        ).fetchall()
        min_overlap = 1 if len(q_bigrams) != 2 else 2
        scored = []
        for r in rows:
            content_bigrams = _bigrams(r["content"])
            overlap = len(q_bigrams & content_bigrams)
            if overlap >= min_overlap:
                scored.append((overlap, r["content"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"content": c} for _, c in scored[:top_k]]

    # ---- 事实提炼游标 ----
    def get_last_fact_msg_id(self, user_id: str) -> int:
        row = self.conn.execute(
            "SELECT last_fact_msg_id FROM user_meta WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["last_fact_msg_id"] if row else 0

    def set_last_fact_msg_id(self, user_id: str, msg_id: int) -> None:
        self.conn.execute(
            "INSERT INTO user_meta (user_id, last_fact_msg_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_fact_msg_id = excluded.last_fact_msg_id",
            (user_id, msg_id),
        )
        self.conn.commit()

    def messages_after(self, user_id: str, after_id: int, limit: int):
        return self.conn.execute(
            "SELECT id, role, content FROM messages WHERE user_id = ? AND id > ? ORDER BY id LIMIT ?",
            (user_id, after_id, limit),
        ).fetchall()

    def max_message_id(self, user_id: str) -> int:
        row = self.conn.execute(
            "SELECT MAX(id) AS m FROM messages WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["m"] or 0

    def last_message_ts(self, user_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT ts FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
        return row["ts"] if row else None

    def last_assistant_message(self, user_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT content FROM messages WHERE user_id = ? AND role = 'assistant' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row["content"] if row else None

    def reset(self) -> None:
        """清空所有数据（用于重复测试）。

        优先删除数据库文件重建；若文件被其他进程占用（WinError 32），
        自动退化为用 SQL 清空全部表，保证功能可用。
        """
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.commit()
        self.conn.close()

        path = config.data_dir / "bot.db"
        deleted = False
        for _ in range(3):
            try:
                path.unlink()
                deleted = True
                break
            except PermissionError:
                time.sleep(0.3)

        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        if deleted:
            self.conn.executescript(_SCHEMA)
        else:
            self.conn.execute("PRAGMA busy_timeout = 5000")
            for table in ("affection_log", "long_memory", "facts", "user_meta", "messages", "users"):
                self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()


def _bigrams(text: str) -> set[str]:
    text = text.strip()
    if len(text) < 2:
        return set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


# ---- important_dates（情感记忆：生日/纪念日/特殊日子）----


def save_important_date(user_id: str, date_str: str, label: str, kind: str = "other", year: int | None = None) -> None:
    """保存一个特殊日子。date_str 格式为 'MM-DD'（如 '12-25'）。"""
    db.conn.execute(
        "INSERT INTO important_dates (user_id, date, label, kind, year, ts) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, date_str, label, kind, year, datetime.now().isoformat(timespec="seconds")),
    )
    db.conn.commit()


def get_today_important_dates(user_id: str) -> list[dict]:
    """查询今天有哪些特殊日子（MM-DD 匹配）。"""
    today = date.today().strftime("%m-%d")
    rows = db.conn.execute(
        "SELECT * FROM important_dates WHERE user_id = ? AND date = ? ORDER BY kind",
        (user_id, today),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_important_dates(user_id: str) -> list[dict]:
    """查询该用户所有特殊日子。"""
    rows = db.conn.execute(
        "SELECT * FROM important_dates WHERE user_id = ? ORDER BY date", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def delete_important_date(date_id: int) -> None:
    """删除一条特殊日子记录。"""
    db.conn.execute("DELETE FROM important_dates WHERE id = ?", (date_id,))
    db.conn.commit()


# ---- stickers（表情包收藏）----


def save_sticker(user_id: str, file: str, url: str, desc: str) -> int:
    """收藏一张用户发的表情包；同 URL 已存在则累计 count，返回记录 id。"""
    db.conn.execute("PRAGMA busy_timeout = 5000")
    try:
        row = db.conn.execute(
            "SELECT id FROM stickers WHERE user_id = ? AND url = ?", (user_id, url)
        ).fetchone()
    except sqlite3.OperationalError:
        db.conn.executescript(_SCHEMA)  # 旧库补建表
        row = db.conn.execute(
            "SELECT id FROM stickers WHERE user_id = ? AND url = ?", (user_id, url)
        ).fetchone()
    if row:
        db.conn.execute(
            "UPDATE stickers SET count = count + 1, desc = CASE WHEN desc = '' THEN ? ELSE desc END "
            "WHERE id = ?",
            (desc, row["id"]),
        )
        db.conn.commit()
        return row["id"]
    cur = db.conn.execute(
        "INSERT INTO stickers (user_id, file, url, desc, count, ts) VALUES (?, ?, ?, ?, 1, ?)",
        (user_id, file, url, desc, datetime.now().isoformat(timespec="seconds")),
    )
    db.conn.commit()
    return cur.lastrowid


def get_stickers(user_id: str, limit: int = 50) -> list[dict]:
    """取该用户收藏的表情包（按出现次数排序，热门靠前）。"""
    rows = db.conn.execute(
        "SELECT * FROM stickers WHERE user_id = ? ORDER BY count DESC, id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_sticker_by_desc(user_id: str, keyword: str, limit: int = 30) -> list[dict]:
    """按描述关键词挑表情包（话题匹配回发）。

    用「描述里是否包含关键词的任一词/子串」判断（对中文单字词友好），
    有多词时按命中词数排序。keyword 为空返回热门几张。
    """
    kw = re.split(r"[\s,，。！、/]+", keyword.strip())
    kw = [k for k in kw if k]
    if not kw:
        return []
    rows = db.conn.execute(
        "SELECT * FROM stickers WHERE user_id = ? ORDER BY count DESC LIMIT 300",
        (user_id,),
    ).fetchall()
    scored = []
    for r in rows:
        desc = r["desc"] or ""
        hits = sum(1 for k in kw if k in desc)
        if hits > 0:
            scored.append((hits, dict(r)))
    scored.sort(key=lambda x: (x[0], -x[1].get("count", 0)), reverse=True)
    return [d for _, d in scored[:limit]]


db = UserDB()


# ---- kv_store（通用键值存储，用于每日奖励去重等）----


def kv_get(user_id: str, key: str) -> str | None:
    """读取 kv 值；不存在返回 None。"""
    row = db.conn.execute(
        "SELECT value FROM kv_store WHERE user_id=? AND key=?", (user_id, key)
    ).fetchone()
    return row["value"] if row else None


def kv_set(user_id: str, key: str, value: str) -> None:
    """写入 kv 值（UPSERT）。"""
    db.conn.execute(
        "INSERT OR REPLACE INTO kv_store (user_id, key, value) VALUES (?, ?, ?)",
        (user_id, key, value),
    )
    db.conn.commit()
