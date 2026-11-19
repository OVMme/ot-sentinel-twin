"""Live telemetry WebSocket with origin validation and bounded client queues."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.runtime import SimulationRuntime

router = APIRouter()
HELLO_SAMPLES = 300
MAX_INCOMING_BYTES = 1024


def origin_allowed(origin: str | None, host: str | None, allowed: list[str]) -> bool:
    """Browsers always send Origin; reject cross-site origins (CSWSH). Non-browser clients send none."""
    if not origin:
        return True
    if origin in allowed:
        return True
    parsed = urlparse(origin)
    return bool(host) and parsed.netloc == host  # same-origin (e.g. served through the nginx proxy)


async def _drain_incoming(ws: WebSocket) -> None:
    """Consume client messages (only small keep-alives are expected) until disconnect."""
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            return
        data = msg.get("text") or msg.get("bytes") or ""
        if len(data) > MAX_INCOMING_BYTES:
            await ws.close(code=1009)
            return


@router.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket) -> None:
    rt: SimulationRuntime = ws.app.state.runtime
    if not origin_allowed(ws.headers.get("origin"), ws.headers.get("host"), rt.settings.cors_origins):
        await ws.close(code=1008)
        return
    client = rt.hub.register()
    if client is None:
        await ws.close(code=1013)
        return
    recv_task: asyncio.Task | None = None
    try:
        await ws.accept()
        await ws.send_json(
            {
                "type": "hello",
                "data": {
                    "state": rt.state(),
                    "recent": list(rt.buffer)[-HELLO_SAMPLES:],
                    "active_alerts": rt.active_alerts(),
                    # recent alerts incl. cleared ones, so a freshly opened view can compare outcomes
                    "recent_alerts": list(rt.recent_alerts.values())[-200:],
                    "synthetic_data_only": True,
                },
            }
        )
        recv_task = asyncio.create_task(_drain_incoming(ws))
        while True:
            get_task = asyncio.create_task(client.queue.get())
            done, _ = await asyncio.wait({get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
            if recv_task in done:
                get_task.cancel()
                break
            await ws.send_json(get_task.result())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        rt.hub.unregister(client)
        if recv_task is not None:
            recv_task.cancel()
