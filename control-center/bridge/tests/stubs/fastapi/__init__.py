"""开发沙箱用的最小 FastAPI 替身。

仅用于在没有 FastAPI 的环境里 import Bridge 并直接调用路由函数做逻辑回归，
不参与任何真实部署。
"""
from __future__ import annotations

from typing import Any, Callable


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: Any = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class WebSocketDisconnect(Exception):
    pass


class WebSocket:  # pragma: no cover - 测试里不需要真实实现
    async def accept(self) -> None: ...
    async def send_json(self, data: Any) -> None: ...
    async def send_text(self, data: str) -> None: ...
    async def receive_text(self) -> str: return ""


def _decorator(*_args: Any, **_kwargs: Any) -> Callable[[Callable], Callable]:
    def wrap(func: Callable) -> Callable:
        return func
    return wrap


class FastAPI:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.routes: list[tuple[str, str]] = []
        self.middleware: list[Any] = []

    def add_middleware(self, cls: Any, **kwargs: Any) -> None:
        self.middleware.append((cls, kwargs))

    def _record(self, method: str):
        def register(path: str, **_kwargs: Any):
            self.routes.append((method, path))
            def wrap(func):
                return func
            return wrap
        return register

    def __getattr__(self, name: str):
        if name in {"get", "post", "put", "patch", "delete", "websocket", "head", "options"}:
            return self._record(name)
        raise AttributeError(name)
