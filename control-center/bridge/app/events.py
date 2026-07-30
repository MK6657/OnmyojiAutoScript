from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


class EventHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._seq = 0
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            seq = self._seq
        await websocket.send_json(
            {
                "version": 1,
                "seq": seq,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "bridge.ready",
                "level": "info",
                "payload": {},
            }
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def emit(self, event_type: str, account_id: str | None = None, task_id: str | None = None,
                   level: str = "info", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._lock:
            self._seq += 1
            event = {
                "version": 1,
                "seq": self._seq,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "accountId": account_id,
                "taskId": task_id,
                "level": level,
                "payload": payload or {},
            }
            connections = list(self._connections)
        dead: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_text(json.dumps(event, ensure_ascii=False))
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            await self.disconnect(websocket)
        return event

