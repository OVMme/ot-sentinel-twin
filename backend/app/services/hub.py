"""WebSocket fan-out with bounded per-client queues (slow clients drop oldest messages).

``publish`` is safe to call from any thread: off-loop callers are marshalled onto the event loop
with ``call_soon_threadsafe`` because ``asyncio.Queue`` itself is not thread-safe.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

CLIENT_QUEUE_SIZE = 512


@dataclass(eq=False)
class Client:
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE))
    dropped: int = 0


class Hub:
    def __init__(self, max_clients: int) -> None:
        self.max_clients = max_clients
        self.clients: set[Client] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def register(self) -> Client | None:
        if len(self.clients) >= self.max_clients:
            return None
        c = Client()
        self.clients.add(c)
        return c

    def unregister(self, c: Client) -> None:
        self.clients.discard(c)

    def publish(self, message: dict[str, Any]) -> None:
        if not self.clients:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self.loop is not None and running is not self.loop:
            self.loop.call_soon_threadsafe(self._deliver, message)
        else:
            self._deliver(message)

    def _deliver(self, message: dict[str, Any]) -> None:
        for c in list(self.clients):
            q = c.queue
            if q.full():
                try:
                    q.get_nowait()
                    c.dropped += 1
                except asyncio.QueueEmpty:  # pragma: no cover
                    pass
            q.put_nowait(message)
