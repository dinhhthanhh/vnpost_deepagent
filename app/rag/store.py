import json
import logging
import sqlite3
import time
from pathlib import Path

from psycopg.types.json import Jsonb

from app.core.postgres import get_sync_pool

logger = logging.getLogger(__name__)


class Store:
    """Enterprise Storage Engine for VNPost Deep Agent.

    Natively uses PostgreSQL in Production (when postgres_url is configured),
    with graceful local SQLite fallback for offline unit tests.
    """

    def __init__(self, root: Path, postgres_url: str | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.postgres_url = (postgres_url or "").strip()
        self.db_path = self.root / "catalog.sqlite3"
        self.pool = get_sync_pool(self.postgres_url) if self.postgres_url else None
        self.use_postgres = self.pool is not None

        if self.use_postgres:
            logger.info("Store đang sử dụng PostgreSQL Database (%s).", self.postgres_url)
            self._migrate_sqlite_to_postgres()
        else:
            self._init_sqlite()

    def _init_sqlite(self):
        with self._connect_sqlite() as db:
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

    def _connect_sqlite(self):
        return sqlite3.connect(self.db_path, timeout=15)

    def _migrate_sqlite_to_postgres(self):
        """Tự động chuyển toàn bộ dữ liệu từ SQLite sang PostgreSQL khi lên Production."""
        if not self.db_path.is_file():
            return
        try:
            sdb = self._connect_sqlite()
            migrated_sessions = 0
            try:
                with self.pool.connection() as pconn:
                    # 1. Migrate sessions
                    cur = sdb.execute("SELECT tenant, id, messages, updated FROM sessions")
                    for tenant, sid, raw_messages, updated in cur.fetchall():
                        try:
                            msgs = (
                                json.loads(raw_messages)
                                if isinstance(raw_messages, str)
                                else raw_messages
                            )
                            pconn.execute(
                                """
                                INSERT INTO sessions (tenant, id, messages, updated)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (tenant, id) DO NOTHING;
                                """,
                                (tenant, sid, Jsonb(msgs), updated),
                            )
                            migrated_sessions += 1
                        except Exception:
                            pass

                    # 2. Migrate replies
                    cur2 = sdb.execute("SELECT tenant, id, payload, created FROM replies")
                    for tenant, req_id, raw_payload, created in cur2.fetchall():
                        try:
                            pld = (
                                json.loads(raw_payload)
                                if isinstance(raw_payload, str)
                                else raw_payload
                            )
                            pconn.execute(
                                """
                                INSERT INTO replies (tenant, id, payload, created)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (tenant, id) DO NOTHING;
                                """,
                                (tenant, req_id, Jsonb(pld), created),
                            )
                        except Exception:
                            pass

                    # 3. Migrate audio
                    cur3 = sdb.execute("SELECT tenant, id, path, created FROM audio")
                    for tenant, aid, apath, created in cur3.fetchall():
                        try:
                            pconn.execute(
                                """
                                INSERT INTO audio (tenant, id, path, created)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (tenant, id) DO NOTHING;
                                """,
                                (tenant, aid, apath, created),
                            )
                        except Exception:
                            pass
            finally:
                sdb.close()

            # Xóa các file SQLite cũ sau khi đã di chuyển thành công vào PostgreSQL
            for ext in ("", "-shm", "-wal"):
                target = Path(str(self.db_path) + ext)
                target.unlink(missing_ok=True)
            logger.info(
                "Đã di chuyển thành công %d phiên từ SQLite sang PostgreSQL và xóa catalog.sqlite3.",
                migrated_sessions,
            )
        except Exception as exc:
            logger.warning("Không thể di chuyển SQLite sang PostgreSQL: %s", exc)

    def history(self, tenant: str, session_id: str) -> list[dict]:
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    cur = conn.execute(
                        "SELECT messages FROM sessions WHERE tenant = %s AND id = %s LIMIT 1;",
                        (tenant, session_id),
                    )
                    row = cur.fetchone()
                    if row and "messages" in row:
                        val = row["messages"]
                        return val if isinstance(val, list) else json.loads(val)
                return []
            except Exception as exc:
                logger.error("Postgres error in history: %s", exc)
                return []
        with self._connect_sqlite() as db:
            row = db.execute(
                "SELECT messages FROM sessions WHERE tenant=? AND id=?", (tenant, session_id)
            ).fetchone()
        return json.loads(row[0]) if row else []

    def save_turn(
        self,
        tenant: str,
        session_id: str,
        user: str,
        answer: str,
        max_messages: int,
        details: dict | None = None,
    ):
        history = self.history(tenant, session_id)
        now = time.time()
        history.extend(
            [
                {"role": "user", "content": user, "created": now},
                {"role": "assistant", "content": answer, "created": now, **(details or {})},
            ]
        )
        limit = max_messages // 2 * 2
        trimmed = history[-limit:]

        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO sessions (tenant, id, messages, updated)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (tenant, id) DO UPDATE SET
                            messages = EXCLUDED.messages,
                            updated = EXCLUDED.updated;
                        """,
                        (tenant, session_id, Jsonb(trimmed), now),
                    )
                return
            except Exception as exc:
                logger.error("Postgres error in save_turn: %s", exc)

        with self._connect_sqlite() as db:
            db.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)",
                (tenant, session_id, json.dumps(trimmed, ensure_ascii=False), now),
            )

    def truncate_session(self, tenant: str, session_id: str, index: int) -> list[dict]:
        """Cắt tỉa lịch sử hội thoại, chỉ giữ lại các tin nhắn trước index chỉ định (0-indexed)."""
        history = self.history(tenant, session_id)
        trimmed = history[:max(0, index)]
        now = time.time()
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    conn.execute(
                        """
                        UPDATE sessions
                        SET messages = %s, updated = %s
                        WHERE tenant = %s AND id = %s;
                        """,
                        (Jsonb(trimmed), now, tenant, session_id),
                    )
                return trimmed
            except Exception as exc:
                logger.error("Postgres error in truncate_session: %s", exc)
                return history

        with self._connect_sqlite() as db:
            db.execute(
                "UPDATE sessions SET messages = ?, updated = ? WHERE tenant = ? AND id = ?",
                (json.dumps(trimmed, ensure_ascii=False), now, tenant, session_id),
            )
        return trimmed

    def list_sessions(self, tenant: str, limit: int = 50) -> list[dict]:
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    cur = conn.execute(
                        "SELECT id, messages, updated FROM sessions WHERE tenant = %s ORDER BY updated DESC LIMIT %s;",
                        (tenant, limit),
                    )
                    rows = cur.fetchall()
                results = []
                for row in rows:
                    sid = row["id"]
                    msgs = row["messages"]
                    if isinstance(msgs, str):
                        try:
                            msgs = json.loads(msgs)
                        except Exception:
                            msgs = []
                    first_user = next(
                        (m.get("content", "") for m in msgs if m.get("role") == "user"), ""
                    )
                    title = first_user[:60] if first_user else "Cuộc trò chuyện mới"
                    results.append(
                        {
                            "id": sid,
                            "title": title or "Cuộc trò chuyện mới",
                            "message_count": len(msgs),
                            "updated": row["updated"],
                        }
                    )
                return results
            except Exception as exc:
                logger.error("Postgres error in list_sessions: %s", exc)
                return []

        with self._connect_sqlite() as db:
            rows = db.execute(
                "SELECT id, messages, updated FROM sessions WHERE tenant=? ORDER BY updated DESC LIMIT ?",
                (tenant, limit),
            ).fetchall()
        results = []
        for sid, raw_messages, updated in rows:
            try:
                msgs = json.loads(raw_messages)
                first_user = next(
                    (m.get("content", "") for m in msgs if m.get("role") == "user"), ""
                )
                title = first_user[:60] if first_user else "Cuộc trò chuyện mới"
            except Exception:
                title, msgs = "Cuộc trò chuyện mới", []
            results.append(
                {
                    "id": sid,
                    "title": title or "Cuộc trò chuyện mới",
                    "message_count": len(msgs),
                    "updated": updated,
                }
            )
        return results

    def delete_session(self, tenant: str, session_id: str):
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    conn.execute(
                        "DELETE FROM sessions WHERE tenant = %s AND id = %s;", (tenant, session_id)
                    )
                    conn.execute(
                        "DELETE FROM replies WHERE tenant = %s AND payload->>'session_id' = %s;",
                        (tenant, session_id),
                    )
                    from app.core.postgres import purge_session_from_postgres

                    purge_session_from_postgres(tenant, session_id, self.postgres_url)
                return
            except Exception as exc:
                logger.error("Postgres error in delete_session: %s", exc)

        with self._connect_sqlite() as db:
            db.execute("DELETE FROM sessions WHERE tenant=? AND id=?", (tenant, session_id))
            try:
                db.execute(
                    "DELETE FROM replies WHERE tenant=? AND json_extract(payload, '$.session_id')=?",
                    (tenant, session_id),
                )
            except Exception:
                pass
        checkpoints_path = self.root / "checkpoints.sqlite3"
        if checkpoints_path.is_file():
            try:
                with sqlite3.connect(checkpoints_path, timeout=5) as cdb:
                    pattern = f"{tenant}:{session_id}%"
                    cdb.execute("DELETE FROM checkpoints WHERE thread_id LIKE ?", (pattern,))
                    cdb.execute("DELETE FROM checkpoint_blobs WHERE thread_id LIKE ?", (pattern,))
                    cdb.execute("DELETE FROM checkpoint_writes WHERE thread_id LIKE ?", (pattern,))
            except Exception:
                pass

    def save_reply(self, tenant: str, request_id: str, payload: dict):
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO replies (tenant, id, payload, created)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (tenant, id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            created = EXCLUDED.created;
                        """,
                        (tenant, request_id, Jsonb(payload), time.time()),
                    )
                return
            except Exception as exc:
                logger.error("Postgres error in save_reply: %s", exc)

        with self._connect_sqlite() as db:
            db.execute(
                "INSERT OR REPLACE INTO replies VALUES (?,?,?,?)",
                (tenant, request_id, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def reply(self, tenant: str, request_id: str) -> dict | None:
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    cur = conn.execute(
                        "SELECT payload FROM replies WHERE tenant = %s AND id = %s LIMIT 1;",
                        (tenant, request_id),
                    )
                    row = cur.fetchone()
                    if row and "payload" in row:
                        val = row["payload"]
                        return val if isinstance(val, dict) else json.loads(val)
                return None
            except Exception as exc:
                logger.error("Postgres error in reply: %s", exc)
                return None

        with self._connect_sqlite() as db:
            row = db.execute(
                "SELECT payload FROM replies WHERE tenant=? AND id=?", (tenant, request_id)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_audio(self, tenant: str, audio_id: str, path: Path):
        resolved_path = str(path.resolve())
        now = time.time()
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO audio (tenant, id, path, created)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (tenant, id) DO UPDATE SET
                            path = EXCLUDED.path,
                            created = EXCLUDED.created;
                        """,
                        (tenant, audio_id, resolved_path, now),
                    )
                return
            except Exception as exc:
                logger.error("Postgres error in save_audio: %s", exc)

        with self._connect_sqlite() as db:
            db.execute(
                "INSERT OR REPLACE INTO audio VALUES (?,?,?,?)",
                (tenant, audio_id, resolved_path, now),
            )

    def audio_path(self, tenant: str, audio_id: str, ttl: int) -> Path | None:
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    cur = conn.execute(
                        "SELECT path, created FROM audio WHERE tenant = %s AND id = %s LIMIT 1;",
                        (tenant, audio_id),
                    )
                    row = cur.fetchone()
                    if not row or time.time() - row["created"] > ttl:
                        return None
                    path = Path(row["path"])
                    return path if path.is_file() and path.is_relative_to(self.root) else None
            except Exception as exc:
                logger.error("Postgres error in audio_path: %s", exc)
                return None

        with self._connect_sqlite() as db:
            row = db.execute(
                "SELECT path,created FROM audio WHERE tenant=? AND id=?", (tenant, audio_id)
            ).fetchone()
        if not row or time.time() - row[1] > ttl:
            return None
        path = Path(row[0])
        return path if path.is_file() and path.is_relative_to(self.root) else None

    def prune_audio(self, ttl: int):
        cutoff = time.time() - ttl
        if self.use_postgres:
            try:
                with self.pool.connection() as conn:
                    cur = conn.execute("SELECT path FROM audio WHERE created < %s;", (cutoff,))
                    for row in cur.fetchall():
                        path = Path(row["path"])
                        if path.is_relative_to(self.root):
                            path.unlink(missing_ok=True)
                    conn.execute("DELETE FROM audio WHERE created < %s;", (cutoff,))
                return
            except Exception as exc:
                logger.error("Postgres error in prune_audio: %s", exc)

        with self._connect_sqlite() as db:
            rows = db.execute("SELECT path FROM audio WHERE created<?", (cutoff,)).fetchall()
            for (value,) in rows:
                path = Path(value)
                if path.is_relative_to(self.root):
                    path.unlink(missing_ok=True)
            db.execute("DELETE FROM audio WHERE created<?", (cutoff,))
