"""Serialized async memory writer (PLAN-WEB §7.3).

Every memory write / ledger append in the web process passes through one
`asyncio.Queue` drained by a single worker task, preserving strict hash-chain
ordering on `memory_ledger` without blocking unrelated request handlers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class MemoryWriter:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[Callable[[], Any], asyncio.Future] | None] | None = None
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_started(self) -> asyncio.Queue[tuple[Callable[[], Any], asyncio.Future] | None]:
        loop = asyncio.get_running_loop()
        if self._queue is None or self._loop is not loop or self._task is None or self._task.done():
            self._loop = loop
            self._queue = asyncio.Queue()
            self._task = loop.create_task(self._drain(self._queue))
        return self._queue

    async def _drain(
        self, queue: asyncio.Queue[tuple[Callable[[], Any], asyncio.Future] | None]
    ) -> None:
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                return
            fn, fut = item
            try:
                res = fn()
                if isinstance(res, Awaitable):
                    res = await res
                if not fut.done():
                    fut.set_result(res)
            except BaseException as exc:  # noqa: BLE001 - propagate to caller
                if not fut.done():
                    fut.set_exception(exc)
            finally:
                queue.task_done()

    async def submit(self, fn: Callable[[], Any]) -> Any:
        """Execute a sync or async memory mutation strictly serially."""
        queue = self._ensure_started()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await queue.put((fn, fut))
        return await fut

    async def close(self) -> None:
        if self._queue is not None and self._task is not None and not self._task.done():
            await self._queue.put(None)
            await self._task
        self._queue = None
        self._task = None
