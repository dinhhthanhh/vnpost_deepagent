"""Persistent Async SQLite Checkpointer for LangGraph and Deep Agents.

Provides lazy-connecting, thread-safe asynchronous checkpoint persistence
without requiring an active asyncio event loop at instantiation time.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


class PersistentSqliteCheckpointer(BaseCheckpointSaver):
    """Async SQLite Checkpointer that lazily connects on first use.

    Compatible with both synchronous framework initialization and async runtime execution.
    """

    def __init__(self, db_path: str | Path):
        super().__init__()
        self.db_path = str(Path(db_path).resolve())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._saver: AsyncSqliteSaver | None = None
        self._conn: aiosqlite.Connection | None = None
        self._init_lock: asyncio.Lock | None = None

    async def _get_saver(self) -> AsyncSqliteSaver:
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        if self._saver is None:
            async with self._init_lock:
                if self._saver is None:
                    self._conn = await aiosqlite.connect(self.db_path)
                    self._saver = AsyncSqliteSaver(self._conn)
                    await self._saver.setup()
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
        if self._conn:
            await self._conn.close()
            self._conn = None
            self._saver = None
