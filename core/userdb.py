"""SQLite 数据层：每用户独立数据。

表：
- users         用户状态（好感度、称呼偏好、恋人确认、首次对话、日期标记）
- messages      会话历史（短期上下文的来源）
- long_memory   长期记忆片段（v1 用关键词检索，可换向量库）
- affection_log 好感度变动流水
"""
import sqlite3
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
    last_batch_date TEXT
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
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
CREATE INDEX IF NOT EXISTS idx_long_memory_user ON long_memory(user_id, id);
"""


class UserDB:
    def __init__(self) -> None:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(config.data_dir / "bot.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
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
            "SELECT role, content, ts FROM messages WHERE user_id = ? "
            "AND date(ts) BETWEEN ? AND ? ORDER BY id",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchall()

    # ---- long memory ----
    def add_long_memory(self, user_id: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO long_memory (user_id, content, ts) VALUES (?, ?, ?)",
            (user_id, content, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def search_long_memory(self, user_id: str, query: str, top_k: int):
        """v1 关键词检索：按中文字符二元组重叠打分，取 top_k。"""
        q_bigrams = _bigrams(query)
        if not q_bigrams:
            return []
        rows = self.conn.execute(
            "SELECT id, content, ts FROM long_memory WHERE user_id = ? "
            "ORDER BY id DESC LIMIT 500",
            (user_id,),
        ).fetchall()
        scored = []
        # 短查询（如 2 字称呼）至少 1 个二元组命中即可，长查询要求 2 个
        min_overlap = min(2, len(q_bigrams))
        for r in rows:
            content_bigrams = _bigrams(r["content"])
            overlap = len(q_bigrams & content_bigrams)
            if overlap >= min_overlap:
                scored.append((overlap, r["content"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"content": c} for _, c in scored[:top_k]]


def _bigrams(text: str) -> set[str]:
    text = text.strip()
    if len(text) < 2:
        return set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


db = UserDB()
