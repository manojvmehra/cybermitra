"""Server-sent events for the operator screen: packet_created, packet_updated, queue_reordered, live_fields.

Each subscriber gets a bounded queue; a slow subscriber drops its oldest events instead of blocking a call."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

KEEPALIVE_S = 15
QUEUE_MAX = 200


class Broadcaster:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[tuple[str, str]]] = set()
        self.sent: list[str] = []  # event names, for tests and /api/metrics (no payloads)

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def publish(self, event: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str)
        self.sent.append(event)
        del self.sent[:-1000]
        for q in list(self._subs):
            if q.full():
                q.get_nowait()
            q.put_nowait((event, payload))

    async def stream(self, max_events: int | None = None) -> AsyncIterator[str]:
        q: asyncio.Queue[tuple[str, str]] = asyncio.Queue(QUEUE_MAX)
        self._subs.add(q)
        n = 0
        try:
            yield ": connected\n\n"
            while max_events is None or n < max_events:
                try:
                    event, payload = await asyncio.wait_for(q.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                n += 1
                yield f"event: {event}\ndata: {payload}\n\n"
        finally:
            self._subs.discard(q)


bus = Broadcaster()
