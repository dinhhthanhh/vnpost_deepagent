import json
import sqlite3
import time
from pathlib import Path


class Store:
    """Single SQLite catalog; every conversation/audio query is tenant-scoped."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "catalog.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    tenant TEXT, id TEXT, messages TEXT NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY (tenant, id));
                CREATE TABLE IF NOT EXISTS replies (
                    tenant TEXT, id TEXT, payload TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY (tenant, id));
                CREATE TABLE IF NOT EXISTS audio (
                    tenant TEXT, id TEXT, path TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY (tenant, id));
            """)

    def connect(self):
        return sqlite3.connect(self.db_path, timeout=15)

    def history(self, tenant: str, session_id: str) -> list[dict]:
        with self.connect() as db:
            row = db.execute("SELECT messages FROM sessions WHERE tenant=? AND id=?",
                             (tenant, session_id)).fetchone()
        return json.loads(row[0]) if row else []

    def save_turn(self, tenant: str, session_id: str, user: str, answer: str, max_messages: int, details: dict | None = None):
        history = self.history(tenant, session_id)
        history.extend([{"role": "user", "content": user},
                        {"role": "assistant", "content": answer, **(details or {})}])
        # Preserve complete user/assistant pairs even if the configured limit is odd.
        limit = max_messages // 2 * 2
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)",
                       (tenant, session_id, json.dumps(history[-limit:], ensure_ascii=False), time.time()))

    def save_reply(self, tenant: str, request_id: str, payload: dict):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO replies VALUES (?,?,?,?)",
                       (tenant, request_id, json.dumps(payload, ensure_ascii=False), time.time()))

    def reply(self, tenant: str, request_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM replies WHERE tenant=? AND id=?",
                             (tenant, request_id)).fetchone()
        return json.loads(row[0]) if row else None

    def save_audio(self, tenant: str, audio_id: str, path: Path):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO audio VALUES (?,?,?,?)",
                       (tenant, audio_id, str(path.resolve()), time.time()))

    def audio_path(self, tenant: str, audio_id: str, ttl: int) -> Path | None:
        with self.connect() as db:
            row = db.execute("SELECT path,created FROM audio WHERE tenant=? AND id=?",
                             (tenant, audio_id)).fetchone()
        if not row or time.time() - row[1] > ttl:
            return None
        path = Path(row[0])
        return path if path.is_file() and path.is_relative_to(self.root) else None

    def prune_audio(self, ttl: int):
        with self.connect() as db:
            rows = db.execute("SELECT path FROM audio WHERE created<?", (time.time() - ttl,)).fetchall()
            for (value,) in rows:
                path = Path(value)
                if path.is_relative_to(self.root):
                    path.unlink(missing_ok=True)
            db.execute("DELETE FROM audio WHERE created<?", (time.time() - ttl,))
