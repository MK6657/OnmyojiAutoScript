from __future__ import annotations

from typing import Any


async def authorize_websocket(websocket: Any) -> bool:
    """Require the Core key before accepting a remotely exposed WebSocket."""
    app = getattr(websocket, "app", None)
    if app is None:
        scope = getattr(websocket, "scope", {}) or {}
        app = scope.get("app")
    state = getattr(app, "state", None)
    if not getattr(state, "remote_access", False):
        return True
    configured_key = getattr(state, "api_key", None)
    if configured_key and websocket.headers.get("x-oas-key") == configured_key:
        return True
    await websocket.close(code=1008, reason="OAS key required")
    return False
