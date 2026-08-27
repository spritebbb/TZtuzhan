"""SQLite 数据层：每用户独立数据。

表：
- users         用户状态（好感度、称呼偏好、恋人确认、首次对话、日期标记）
- messages      会话历史（短期上下文的来源）
- long_memory   长期记忆原文片段（关键词检索）
- facts         LLM 提炼的长期事实（喜好/约定等，带去重）
- user_meta     事实提炼游标等元数据
- affection_log 好感度变动流水
"""
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
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
CREATE INDEX IF NOT EXISTS idx_long_memory_user ON long_memory(user_id, id);
CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_id, id);
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

    # ---- facts（LLM 提炼的长期事实）----
    def add_fact(self, user_id: str, content: str) -> bool:
        """存一条事实；与已有事实二元组重叠≥50% 视为重复则跳过。"""
        content = content.strip()
        if not content:
            return False
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
                    return False
        self.conn.execute(
            "INSERT INTO facts (user_id, content, ts) VALUES (?, ?, ?)",
            (user_id, content, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return True

    def search_facts(self, user_id: str, query: str, top_k: int):
        """按关键词（二元组）检索事实，取 top_k。"""
        q_bigrams = _bigrams(query)
        if not q_bigrams:
            return []
        rows = self.conn.execute(
            "SELECT content FROM facts WHERE user_id = ? ORDER BY id DESC LIMIT 500",
            (user_id,),
        ).fetchall()
        min_overlap = min(2, len(q_bigrams))
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


db = UserDB()
