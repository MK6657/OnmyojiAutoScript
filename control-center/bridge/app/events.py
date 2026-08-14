from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


class EventHub:
    HEARTBEAT_INTERVAL = 30.0

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._seq = 0
        self._lock = asyncio.Lock()
        self._heartbeats: dict[int, asyncio.Task] = {}

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
        # DeepSeek-13 2.3 (F-13): application-level heartbeat so half-open
        # connections are reaped server-side within ~2 intervals instead of
        # waiting for TCP timeouts.
        task = asyncio.get_running_loop().create_task(self._heartbeat_loop(websocket))
        self._heartbeats[id(websocket)] = task

    async def _heartbeat_loop(self, websocket: WebSocket) -> None:
        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                await websocket.send_text(
                    json.dumps(
                        {
                            "version": 1,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "type": "bridge.ping",
                            "level": "info",
                            "payload": {},
                        },
                        ensure_ascii=False,
                    )
                )
        except Exception:
            pass
        finally:
            # DeepSeek-14 O14-6: clean up inline instead of calling disconnect(),
            # which would cancel the CURRENT task from its own finally and end
            # the task in a cancelled state.
            self._heartbeats.pop(id(websocket), None)
            async with self._lock:
                self._connections.discard(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        task = self._heartbeats.pop(id(websocket), None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
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

