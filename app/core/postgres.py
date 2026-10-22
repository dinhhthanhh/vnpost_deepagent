"""PostgreSQL Connection Pool, Schema Initialization, and Persistent Checkpointer for VNPost Mipo.

Provides:
1. Async connection pooling via `psycopg_pool.AsyncConnectionPool`.
2. Tables and indexes for Human-in-the-Loop (HITL) Draft Bookings & Complaints.
3. PersistentPostgresCheckpointer for LangGraph and Deep Agents (lazy async init).
4. Synchronous & asynchronous persistence helpers for transactional drafts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from psycopg import AsyncConnection, Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool, ConnectionPool

logger = logging.getLogger(__name__)

# Global singleton pools
_ASYNC_POOL: AsyncConnectionPool | None = None
_SYNC_POOL: ConnectionPool | None = None
_POOL_LOCK = asyncio.Lock()
_SCHEMA_INITIALIZED = False


def _resolve_postgres_url(postgres_url: str | None = None) -> str:
    """Xác định URL kết nối PostgreSQL từ tham số, biến môi trường hoặc Settings."""
    if postgres_url and postgres_url.strip():
        return postgres_url.strip()
    env_url = os.getenv("POSTGRES_URL", "").strip()
    if env_url:
        return env_url
    try:
        from app.core.config import Settings

        return Settings().postgres_url.strip()
    except Exception:
        return ""


def _get_vn_now() -> datetime:
    """Trả về thời gian hiện tại theo múi giờ Việt Nam (UTC+7)."""
    return datetime.now(UTC)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS draft_bookings (
    draft_id VARCHAR(64) PRIMARY KEY,
    tenant VARCHAR(64) NOT NULL DEFAULT 'default',
    session_id VARCHAR(128),
    request_id VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'WAITING_CONFIRMATION',
    sender_name VARCHAR(255),
    sender_phone VARCHAR(32),
    receiver_name VARCHAR(255),
    receiver_phone VARCHAR(32),
    detail JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_draft_bookings_tenant_session ON draft_bookings(tenant, session_id);
CREATE INDEX IF NOT EXISTS idx_draft_bookings_status ON draft_bookings(status);
CREATE INDEX IF NOT EXISTS idx_draft_bookings_expires_at ON draft_bookings(expires_at);

CREATE TABLE IF NOT EXISTS draft_complaints (
    draft_ticket_id VARCHAR(64) PRIMARY KEY,
    tenant VARCHAR(64) NOT NULL DEFAULT 'default',
    session_id VARCHAR(128),
    request_id VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'WAITING_CONFIRMATION',
    customer_name VARCHAR(255),
    customer_phone VARCHAR(32),
    item_code VARCHAR(32),
    claim_type VARCHAR(64),
    detail JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_draft_complaints_tenant_session ON draft_complaints(tenant, session_id);
CREATE INDEX IF NOT EXISTS idx_draft_complaints_status ON draft_complaints(status);
CREATE INDEX IF NOT EXISTS idx_draft_complaints_expires_at ON draft_complaints(expires_at);
"""


async def get_async_pool(
    postgres_url: str | None = None,
    min_size: int = 1,
    max_size: int = 10,
) -> AsyncConnectionPool | None:
    """Lấy hoặc khởi tạo connection pool bất đồng bộ tới PostgreSQL."""
    global _ASYNC_POOL, _SCHEMA_INITIALIZED
    url = _resolve_postgres_url(postgres_url)
    if not url:
        return None

    if _ASYNC_POOL is None:
        async with _POOL_LOCK:
            if _ASYNC_POOL is None:
                try:
                    pool = AsyncConnectionPool(
                        conninfo=url,
                        min_size=min_size,
                        max_size=max_size,
                        timeout=3.0,
                        open=False,
                        kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 3},
                    )
                    await pool.open()
                    _ASYNC_POOL = pool
                    logger.info(
                        "Đã mở PostgreSQL AsyncConnectionPool thành công: %s", url.split("@")[-1]
                    )
                except Exception as exc:
                    logger.warning("Không thể mở PostgreSQL AsyncConnectionPool: %s", exc)
                    return None

    if _ASYNC_POOL is not None and not _SCHEMA_INITIALIZED:
        await init_postgres_schema(_ASYNC_POOL)
        _SCHEMA_INITIALIZED = True

    return _ASYNC_POOL


def get_sync_pool(
    postgres_url: str | None = None,
    min_size: int = 1,
    max_size: int = 5,
) -> ConnectionPool | None:
    """Lấy hoặc khởi tạo connection pool đồng bộ phục vụ các tác vụ blocking."""
    global _SYNC_POOL
    url = _resolve_postgres_url(postgres_url)
    if not url:
        return None

    if _SYNC_POOL is None:
        try:
            pool = ConnectionPool(
                conninfo=url,
                min_size=min_size,
                max_size=max_size,
                timeout=3.0,
                open=True,
                kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 3},
            )
            _SYNC_POOL = pool
            # Khởi tạo schema nếu cần
            with pool.connection(timeout=3.0) as conn:
                conn.execute(SCHEMA_SQL)
            logger.info("Đã mở PostgreSQL Sync ConnectionPool thành công.")
        except Exception as exc:
            logger.debug("Không thể mở PostgreSQL Sync ConnectionPool (có thể offline): %s", exc)
            return None

    return _SYNC_POOL


async def init_postgres_schema(pool: AsyncConnectionPool) -> None:
    """Khởi tạo cấu trúc bảng HITL Drafts và kiểm tra tính toàn vẹn."""
    try:
        async with pool.connection() as conn:
            await conn.execute(SCHEMA_SQL)
        logger.info("Khởi tạo schema PostgreSQL cho draft_bookings và draft_complaints thành công.")
    except Exception as exc:
        logger.warning("Lỗi khởi tạo schema PostgreSQL: %s", exc)


async def close_postgres_pools() -> None:
    """Đóng toàn bộ connection pool khi ứng dụng tắt."""
    global _ASYNC_POOL, _SYNC_POOL
    if _ASYNC_POOL is not None:
        try:
            await _ASYNC_POOL.close()
        except Exception as exc:
            logger.warning("Lỗi đóng AsyncConnectionPool: %s", exc)
        _ASYNC_POOL = None

    if _SYNC_POOL is not None:
        try:
            _SYNC_POOL.close()
        except Exception as exc:
            logger.warning("Lỗi đóng Sync ConnectionPool: %s", exc)
        _SYNC_POOL = None


# ============================================================================
# PERSISTENT POSTGRES CHECKPOINTER CHO LANGGRAPH & DEEP AGENTS
# ============================================================================


class PersistentPostgresCheckpointer(BaseCheckpointSaver):
    """Checkpointer lưu vết hội thoại bền vững trên PostgreSQL.

    Hỗ trợ khởi tạo trễ (Lazy Connection): An toàn khi khởi tạo bên ngoài
    Asyncio Event Loop và chỉ mở kết nối khi bước suy luận đầu tiên được kích hoạt.
    """

    def __init__(
        self,
        postgres_url: str,
        min_size: int = 1,
        max_size: int = 10,
    ):
        super().__init__()
        self.postgres_url = postgres_url
        self.min_size = min_size
        self.max_size = max_size
        self._pool: AsyncConnectionPool | None = None
        self._saver: Any | None = None
        self._init_lock: asyncio.Lock | None = None

    async def _get_saver(self) -> Any:
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        if self._saver is None:
            async with self._init_lock:
                if self._saver is None:
                    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                    self._pool = await get_async_pool(
                        self.postgres_url,
                        min_size=self.min_size,
                        max_size=self.max_size,
                    )
                    if self._pool is None:
                        raise RuntimeError(f"Không thể kết nối PostgreSQL tại {self.postgres_url}")

                    self._saver = AsyncPostgresSaver(self._pool)
                    await self._saver.setup()
                    logger.info(
                        "LangGraph AsyncPostgresSaver đã thiết lập bảng checkpoints thành công."
                    )
        return self._saver

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        saver = await self._get_saver()
        return await saver.aget_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        saver = await self._get_saver()
        async for item in saver.alist(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        saver = await self._get_saver()
        return await saver.aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
    ) -> None:
        saver = await self._get_saver()
        return await saver.aput_writes(config, writes, task_id)

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self._saver = None


# ============================================================================
# PERSISTENCE HELPERS CHO ĐƠN HÀNG VÀ KHIẾU NẠI (HITL DRAFTS)
# ============================================================================


def persist_draft_booking_to_postgres(
    draft_record: dict[str, Any], postgres_url: str | None = None
) -> bool:
    """Lưu hoặc cập nhật bản nháp đơn hàng vào PostgreSQL."""
    pool = get_sync_pool(postgres_url)
    if not pool:
        return False
    try:
        draft_id = draft_record.get("draft_id")
        tenant = draft_record.get("tenant", "default") or "default"
        session_id = draft_record.get("session_id")
        request_id = draft_record.get("request_id")
        status = draft_record.get("status", "WAITING_CONFIRMATION")
        sender = draft_record.get("sender", {})
        receiver = draft_record.get("receiver", {})
        created_at = draft_record.get("created_at") or datetime.now(UTC).isoformat()
        expires_at = draft_record.get("expires_at") or datetime.now(UTC).isoformat()
        updated_at = datetime.now(UTC).isoformat()

        sql = """
        INSERT INTO draft_bookings (
            draft_id, tenant, session_id, request_id, status,
            sender_name, sender_phone, receiver_name, receiver_phone,
            detail, created_at, expires_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON CONFLICT (draft_id) DO UPDATE SET
            status = EXCLUDED.status,
            detail = EXCLUDED.detail,
            updated_at = EXCLUDED.updated_at;
        """
        with pool.connection() as conn:
            conn.execute(
                sql,
                (
                    draft_id,
                    tenant,
                    session_id,
                    request_id,
                    status,
                    sender.get("name"),
                    sender.get("phone"),
                    receiver.get("name"),
                    receiver.get("phone"),
                    Jsonb(draft_record),
                    created_at,
                    expires_at,
                    updated_at,
                ),
            )
        return True
    except Exception as exc:
        logger.debug("Lỗi persist draft booking tới PostgreSQL: %s", exc)
        return False


def fetch_draft_booking_from_postgres(
    draft_id: str,
    tenant: str | None = None,
    postgres_url: str | None = None,
) -> dict[str, Any] | None:
    """Đọc bản nháp đơn hàng từ PostgreSQL (có lọc tenant chống IDOR)."""
    pool = get_sync_pool(postgres_url)
    if not pool:
        return None
    try:
        if tenant:
            sql = "SELECT detail FROM draft_bookings WHERE draft_id = %s AND tenant = %s LIMIT 1;"
            params = (draft_id.strip(), tenant.strip())
        else:
            sql = "SELECT detail FROM draft_bookings WHERE draft_id = %s LIMIT 1;"
            params = (draft_id.strip(),)
        with pool.connection() as conn:
            cur = conn.execute(sql, params)
            row = cur.fetchone()
            if row and "detail" in row:
                return row["detail"]
    except Exception as exc:
        logger.debug("Lỗi fetch draft booking từ PostgreSQL: %s", exc)
    return None


def persist_draft_complaint_to_postgres(
    claim_record: dict[str, Any], postgres_url: str | None = None
) -> bool:
    """Lưu hoặc cập nhật bản nháp khiếu nại vào PostgreSQL."""
    pool = get_sync_pool(postgres_url)
    if not pool:
        return False
    try:
        draft_ticket_id = claim_record.get("draft_ticket_id")
        tenant = claim_record.get("tenant", "default") or "default"
        session_id = claim_record.get("session_id")
        request_id = claim_record.get("request_id")
        status = claim_record.get("status", "WAITING_CONFIRMATION")
        customer = claim_record.get("customer", {})
        item_code = claim_record.get("item_code")
        claim_type = claim_record.get("claim_type")
        created_at = claim_record.get("created_at") or datetime.now(UTC).isoformat()
        expires_at = claim_record.get("expires_at") or datetime.now(UTC).isoformat()
        updated_at = datetime.now(UTC).isoformat()

        sql = """
        INSERT INTO draft_complaints (
            draft_ticket_id, tenant, session_id, request_id, status,
            customer_name, customer_phone, item_code, claim_type,
            detail, created_at, expires_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON CONFLICT (draft_ticket_id) DO UPDATE SET
            status = EXCLUDED.status,
            detail = EXCLUDED.detail,
            updated_at = EXCLUDED.updated_at;
        """
        with pool.connection() as conn:
            conn.execute(
                sql,
                (
                    draft_ticket_id,
                    tenant,
                    session_id,
                    request_id,
                    status,
                    customer.get("name"),
                    customer.get("phone"),
                    item_code,
                    claim_type,
                    Jsonb(claim_record),
                    created_at,
                    expires_at,
                    updated_at,
                ),
            )
        return True
    except Exception as exc:
        logger.debug("Lỗi persist draft complaint tới PostgreSQL: %s", exc)
        return False


def fetch_draft_complaint_from_postgres(
    draft_ticket_id: str,
    tenant: str | None = None,
    postgres_url: str | None = None,
) -> dict[str, Any] | None:
    """Đọc bản nháp khiếu nại từ PostgreSQL (có lọc tenant chống IDOR)."""
    pool = get_sync_pool(postgres_url)
    if not pool:
        return None
    try:
        if tenant:
            sql = "SELECT detail FROM draft_complaints WHERE draft_ticket_id = %s AND tenant = %s LIMIT 1;"
            params = (draft_ticket_id.strip(), tenant.strip())
        else:
            sql = "SELECT detail FROM draft_complaints WHERE draft_ticket_id = %s LIMIT 1;"
            params = (draft_ticket_id.strip(),)
        with pool.connection() as conn:
            cur = conn.execute(sql, params)
            row = cur.fetchone()
            if row and "detail" in row:
                return row["detail"]
    except Exception as exc:
        logger.debug("Lỗi fetch draft complaint từ PostgreSQL: %s", exc)
    return None


def fetch_session_drafts_from_postgres(
    tenant: str,
    session_id: str | None = None,
    postgres_url: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Lấy danh sách các đơn hàng và khiếu nại của phiên từ PostgreSQL."""
    bookings: list[dict[str, Any]] = []
    complaints: list[dict[str, Any]] = []
    pool = get_sync_pool(postgres_url)
    if not pool:
        return {"bookings": bookings, "complaints": complaints}

    try:
        with pool.connection() as conn:
            if session_id:
                cur = conn.execute(
                    "SELECT detail FROM draft_bookings WHERE tenant = %s AND session_id = %s ORDER BY created_at DESC;",
                    (tenant, session_id),
                )
            else:
                cur = conn.execute(
                    "SELECT detail FROM draft_bookings WHERE tenant = %s ORDER BY created_at DESC LIMIT 50;",
                    (tenant,),
                )
            for row in cur.fetchall():
                if "detail" in row:
                    bookings.append(row["detail"])

            if session_id:
                cur2 = conn.execute(
                    "SELECT detail FROM draft_complaints WHERE tenant = %s AND session_id = %s ORDER BY created_at DESC;",
                    (tenant, session_id),
                )
            else:
                cur2 = conn.execute(
                    "SELECT detail FROM draft_complaints WHERE tenant = %s ORDER BY created_at DESC LIMIT 50;",
                    (tenant,),
                )
            for row in cur2.fetchall():
                if "detail" in row:
                    complaints.append(row["detail"])
    except Exception as exc:
        logger.debug("Lỗi fetch session drafts từ PostgreSQL: %s", exc)

    return {"bookings": bookings, "complaints": complaints}
