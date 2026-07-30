# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import asyncio
from typing import Iterable

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState


class ScriptWSManager:

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        # 等待连接
        await ws.accept()
        if ws not in self.active_connections:
            self.active_connections.append(ws)

    async def disconnect(self, ws: WebSocket):
        # 关闭时移除 ws 对象，重复调用也应安全
        if ws in self.active_connections:
            self.active_connections.remove(ws)
        if ws.client_state == WebSocketState.DISCONNECTED:
            return
        try:
            # 给前端发送最后一次关闭信号
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            return
        except Exception:
            return

    async def send_text(self, ws: WebSocket, message: str) -> bool:
        return await self._send(ws, ws.send_text, message)

    async def send_json(self, ws: WebSocket, data: dict) -> bool:
        return await self._send(ws, ws.send_json, data)

    async def broadcast(self, message: str):
        # 广播消息
        await self._broadcast(self.active_connections, lambda connection: connection.send_text(message))

    async def broadcast_state(self, data: dict):
        # 广播自身的状态
        await self._broadcast(self.active_connections, lambda connection: connection.send_json(data))

    async def broadcast_log(self, log: str):
        # 广播日志
        await self._broadcast(self.active_connections, lambda connection: connection.send_text(log))

    @staticmethod
    async def _run_on_main(make_coro) -> None:
        """把一次实际发送调度到 WebSocket 所属的主事件循环执行。

        上游把状态/日志推送放在独立线程的独立事件循环里(main_manager)，却直接向
        uvicorn 主循环 accept 的 WebSocket 调用 send —— starlette 的 WebSocket 不是
        跨循环安全的，会偶发丢消息/断连(handoff/16 C2)。若当前不在主循环，则用
        run_coroutine_threadsafe 把这次发送定向回主循环；主循环未记录时按原样直接执行。
        """
        from module.server.setting import State
        main_loop = State.main_loop
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if main_loop is not None and current is not None and main_loop is not current:
            future = asyncio.run_coroutine_threadsafe(make_coro(), main_loop)
            await asyncio.wrap_future(future)
        else:
            await make_coro()

    async def _send(self, ws: WebSocket, sender, payload) -> bool:
        if ws.client_state == WebSocketState.DISCONNECTED:
            await self.disconnect(ws)
            return False
        try:
            await self._run_on_main(lambda: sender(payload))
            return True
        except (RuntimeError, WebSocketDisconnect):
            await self.disconnect(ws)
            return False
        except Exception:
            await self.disconnect(ws)
            return False

    async def _broadcast(self, connections: Iterable[WebSocket], sender_factory) -> None:
        dead_connections: list[WebSocket] = []
        for connection in list(connections):
            if connection.client_state == WebSocketState.DISCONNECTED:
                dead_connections.append(connection)
                continue
            try:
                await self._run_on_main(lambda conn=connection: sender_factory(conn))
            except (RuntimeError, WebSocketDisconnect):
                dead_connections.append(connection)
            except Exception:
                dead_connections.append(connection)
        for connection in dead_connections:
            await self.disconnect(connection)




