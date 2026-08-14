from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import websockets

from .events import EventHub


class CommandExecutionError(RuntimeError):
    """Core acknowledged a command but reported execution failure."""


class CommandInProgress(RuntimeError):
    """Core acknowledged the command (command_ack) but the completion receipt
    has not arrived within the wait window. Callers must surface 202/in_progress
    and retrieve the result from the query/event channel instead of failing or
    re-issuing via REST."""

    def __init__(self, command_id: str) -> None:
        super().__init__(f"command in progress: command_id={command_id}")
        self.command_id = command_id


class CommandNotAccepted(RuntimeError):
    """No command_ack and no completion receipt arrived; Core never took the
    command. A REST fallback carrying the SAME command_id is safe."""

    def __init__(self, command_id: str) -> None:
        super().__init__(f"command not accepted: command_id={command_id}")
        self.command_id = command_id


STATE_LABELS = {
    0: ("offline", "已停止"),
    1: ("running", "运行中"),
    2: ("warning", "异常"),
    3: ("updating", "更新中"),
}

# OAS 的日志行形如：
#   2026-07-26 11:44:12.123 │ INFO     │ module:func:12 - 消息
# 也可能只有级别关键字。把级别解析出来，前端才能按级别过滤和高亮。
_LEVEL_PATTERN = re.compile(
    r"\|\s*(TRACE|DEBUG|INFO|SUCCESS|WARNING|WARN|ERROR|CRITICAL)\s*\|"
    r"|(?:^|\s)(TRACE|DEBUG|INFO|SUCCESS|WARNING|WARN|ERROR|CRITICAL)\s*[:\-\|]",
    re.IGNORECASE,
)
_LEVEL_MAP = {
    "trace": "info", "debug": "info", "info": "info", "success": "info",
    "warning": "warn", "warn": "warn",
    "error": "error", "critical": "error",
}
_TIMESTAMP_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")


def parse_log_level(message: str) -> str:
    match = _LEVEL_PATTERN.search(message)
    if match:
        token = (match.group(1) or match.group(2) or "").lower()
        return _LEVEL_MAP.get(token, "info")
    lowered = message.lower()
    if "traceback" in lowered or "exception" in lowered:
        return "error"
    return "info"


def parse_log_timestamp(message: str) -> str | None:
    match = _TIMESTAMP_PATTERN.match(message.strip())
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1).replace(" ", "T")).astimezone().isoformat()
    except ValueError:
        return None


class AccountRuntime:
    """一个账号对应一条到 Core 的 WebSocket，负责状态、调度快照和日志。"""

    def __init__(self, account_id: str, websocket_url: str, events: EventHub) -> None:
        self.account_id = account_id
        self.websocket_url = websocket_url
        self.events = events
        self.state = "offline"
        self.state_label = "已停止"
        self.connected = False
        self.last_schedule: dict[str, Any] = {}
        self.last_schedule_at: float = 0.0
        self.last_error: str = ""
        self.logs: deque[dict[str, Any]] = deque(maxlen=300)
        self._websocket: Any = None
        self._watch_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._pending_commands: dict[str, asyncio.Future] = {}
        self._last_command_id: str | None = None
        self._acked_commands: set[str] = set()
        self._late_results: dict[str, dict[str, Any]] = {}
        # Serialize start/stop/restart per account; different accounts remain independent.
        self.action_lock = asyncio.Lock()
        self._closed = False
        self._short_sessions = 0

    def start_watching(self) -> None:
        if self._watch_task is None or self._watch_task.done():
            self._closed = False
            self._watch_task = asyncio.create_task(self._watch_loop(), name=f"oas-watch-{self.account_id}")

    async def close(self) -> None:
        self._closed = True
        if self._websocket is not None:
            try:
                await self._websocket.close()
            except Exception:
                pass
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            await asyncio.gather(self._watch_task, return_exceptions=True)
        self._watch_task = None
        self._websocket = None
        self.connected = False
        self._fail_pending_commands("runtime_closed")

    async def wait_connected(self, timeout: float = 2.0) -> bool:
        self.start_watching()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._websocket is not None:
                return True
            await asyncio.sleep(0.05)
        return self._websocket is not None

    async def command(self, command: str, timeout: float = 5.0) -> dict[str, Any]:
        if not await self.wait_connected():
            raise RuntimeError(f"Account {self.account_id} Core WebSocket is unavailable")
        command_id = f"cmd_{uuid4().hex}"
        future = asyncio.get_running_loop().create_future()
        self._pending_commands[command_id] = future
        self._last_command_id = command_id
        async with self._send_lock:
            await self._websocket.send(json.dumps({
                "command_id": command_id,
                "command": command,
            }))
        try:
            # DeepSeek-14 B1/A1: wait on a shielded future so a late receipt can
            # still be adopted; triage on timeout by whether Core acked.
            result = await asyncio.wait_for(
                asyncio.shield(future), timeout=max(timeout, 0.1)
            )
        except asyncio.TimeoutError as error:
            acked = command_id in self._acked_commands
            async def _reap_late() -> None:
                await asyncio.sleep(60)
                self._pending_commands.pop(command_id, None)
                self._acked_commands.discard(command_id)

            asyncio.get_running_loop().create_task(_reap_late())
            if acked:
                raise CommandInProgress(command_id) from error
            raise CommandNotAccepted(command_id) from error
        self._pending_commands.pop(command_id, None)
        self._acked_commands.discard(command_id)
        self._late_results[command_id] = result
        if len(self._late_results) > 128:
            oldest = next(iter(self._late_results))
            self._late_results.pop(oldest, None)
        if not result.get("success", False):
            raise CommandExecutionError(
                f"Core command failed: command_id={command_id}, "
                f"reason={result.get('reason', 'unknown')}"
            )
        await self.events.emit(
            "task.commanded",
            self.account_id,
            level="info",
            payload={"command": command, "command_id": command_id, "result": result},
        )
        return result

    async def _legacy_command_without_receipt(self, command: str) -> None:
        if not await self.wait_connected():
            raise RuntimeError(f"账号 {self.account_id} 的 OAS WebSocket 未连接")
        async with self._send_lock:
            await self._websocket.send(command)
        await self.events.emit("task.commanded", self.account_id, level="info", payload={"command": command})

    async def try_command(self, command: str) -> dict[str, Any] | None:
        """尽力通过 WebSocket 下发命令；失败返回 False，让调用方走 REST 兜底。"""
        try:
            return await self.command(command)
        except (CommandExecutionError, CommandInProgress, CommandNotAccepted):
            raise
        except Exception as exc:
            reason = f'{type(exc).__name__}: {exc}'
            self.last_error = reason
            try:
                await self.events.emit(
                    "task.command.fallback",
                    self.account_id,
                    level="warn",
                    payload={"command": command, "reason": reason},
                )
            except Exception:
                pass
            return None

    async def wait_last_command_result(
        self, timeout: float = 2.0
    ) -> dict[str, Any] | None:
        """DeepSeek-13 2.4 (F-14): briefly await the receipt of the last WS
        command after a timeout so the REST fallback never double-issues
        start/stop. Returns None immediately when nothing is in flight."""
        command_id = self._last_command_id
        future = self._pending_commands.get(command_id) if command_id else None
        if future is None or future.done():
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "state_label": self.state_label,
            "connected": self.connected,
            "schedule": self.last_schedule,
            "last_error": self.last_error,
        }

    def invalidate_schedule(self) -> None:
        """Discard a schedule snapshot after a scheduler field changes via Bridge."""
        self.last_schedule = {}
        self.last_schedule_at = 0.0

    def scheduled_tasks(self) -> dict[str, str | None] | None:
        """从 Core 的调度快照里推导「已启用的任务」。

        Core 的 schedule 由 running / pending / waiting 三段组成，合起来正好是
        这个账号所有启用中的任务。用它替代逐个任务查询 `/args`，
        可以把账号列表的 Core 请求数从「账号数 × 任务数」降到 0。
        """
        if not self.last_schedule:
            return None
        result: dict[str, str | None] = {}
        running = self.last_schedule.get("running") or {}
        if isinstance(running, dict) and running.get("name"):
            result[str(running["name"])] = running.get("next_run")
        for bucket in ("pending", "waiting"):
            for item in self.last_schedule.get(bucket) or []:
                if isinstance(item, dict) and item.get("name"):
                    result.setdefault(str(item["name"]), item.get("next_run"))
        return result or None

    async def _watch_loop(self) -> None:
        retry = 0
        while not self._closed:
            opened_at = time.monotonic()
            try:
                async with websockets.connect(self.websocket_url, open_timeout=5, ping_interval=20, ping_timeout=20) as websocket:
                    self._websocket = websocket
                    self.connected = True
                    self.last_error = ""
                    retry = 0
                    await self.events.emit("account.connected", self.account_id)
                    await websocket.send("get_state")
                    await websocket.send("get_schedule")
                    async for message in websocket:
                        await self._handle_message(message)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self.last_error = str(exc)
                if self.connected:
                    await self.events.emit("account.disconnected", self.account_id, level="warn", payload={"reason": str(exc)})
                retry = min(retry + 1, 6)
            finally:
                self._websocket = None
                self.connected = False
                self._fail_pending_commands("core_disconnected")

            if self._closed:
                return

            # 一个账号如果一项任务都没启用，Core 在 WebSocket 握手阶段的 get_next() 里
            # 会抛 RequestHumanTakeover：先推一条 state，然后立刻断开。
            # 判据必须只看「存活时长」——不能看有没有收到过消息，因为这种秒断
            # 恰恰每次都能收到一条 state（2026-07-26 真实联调实测：按消息判断时
            # 15 秒内重连 12 次）。健康的空闲连接会保持在线几分钟以上，
            # 所以「存活不足 3 秒」本身就足以判定为失败循环。
            if time.monotonic() - opened_at < 3:
                self._short_sessions += 1
            else:
                self._short_sessions = 0
            if self._short_sessions >= 3:
                await asyncio.sleep(30)
            else:
                await asyncio.sleep(min(1 + retry, 5))

    async def _handle_message(self, message: Any) -> None:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        text = str(message)
        try:
            data = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            await self._append_log(text)
            return
        # Core 用 send_text 广播日志，内容有可能刚好是合法 JSON（纯数字、被引号包住的串）。
        # 只有 dict 才是状态/调度消息，其余一律当日志，否则日志会被静默吞掉。
        if not isinstance(data, dict):
            await self._append_log(text)
            return
        message_type = data.get("type")
        if message_type == "command_ack":
            # DeepSeek-14 B1/A1: record that Core took the command so the
            # command() timeout path can triage ack-vs-never-received.
            ack_id = str(data.get("command_id") or "")
            if ack_id:
                self._acked_commands.add(ack_id)
            await self.events.emit(
                "task.command.accepted",
                self.account_id,
                payload={
                    "command": data.get("command"),
                    "command_id": ack_id,
                },
            )
            return
        if message_type == "command_result":
            command_id = str(data.get("command_id") or "")
            future = self._pending_commands.get(command_id)
            if future is not None and not future.done():
                future.set_result(data)
            else:
                # DeepSeek-14 B1/A1: receipt arrived after the HTTP request
                # ended; park it for the query channel.
                self._late_results[command_id] = data
            return
        if "state" in data:
            raw_state = data["state"]
            try:
                raw_state = int(raw_state)
            except (ValueError, TypeError):
                raw_state = 0
            self.state, self.state_label = STATE_LABELS.get(raw_state, ("offline", "未知"))
            event_type = "task.started" if self.state == "running" else "task.stopped" if self.state == "offline" else "task.state"
            await self.events.emit(
                event_type, self.account_id,
                level="warn" if self.state == "warning" else "info",
                payload={"state": self.state, "stateLabel": self.state_label},
            )
        if "schedule" in data:
            self.last_schedule = data["schedule"] or {}
            self.last_schedule_at = time.time()
            await self.events.emit("schedule.updated", self.account_id, payload={"schedule": self.last_schedule})

    def _fail_pending_commands(self, reason: str) -> None:
        for command_id, future in list(self._pending_commands.items()):
            if not future.done():
                future.set_exception(
                    RuntimeError(
                        f"Core command interrupted: command_id={command_id}, reason={reason}"
                    )
                )
        self._pending_commands.clear()

    async def _append_log(self, message: str, level: str | None = None) -> None:
        resolved = level or parse_log_level(message)
        item = {
            "timestamp": parse_log_timestamp(message) or datetime.now(timezone.utc).isoformat(),
            "level": resolved,
            "message": message,
        }
        self.logs.append(item)
        await self.events.emit("log.appended", self.account_id, level=resolved, payload={"log": item})


class RuntimeRegistry:
    def __init__(self, core: Any, events: EventHub) -> None:
        self.core = core
        self.events = events
        self._items: dict[str, AccountRuntime] = {}

    def get(self, account_id: str) -> AccountRuntime:
        runtime = self._items.get(account_id)
        if runtime is None:
            runtime = AccountRuntime(account_id, self.core.websocket_url(account_id), self.events)
            self._items[account_id] = runtime
        runtime.start_watching()
        return runtime

    def peek(self, account_id: str) -> AccountRuntime | None:
        return self._items.get(account_id)

    async def drop(self, account_id: str) -> None:
        runtime = self._items.pop(account_id, None)
        if runtime is not None:
            await runtime.close()

    async def close(self) -> None:
        await asyncio.gather(*(runtime.close() for runtime in self._items.values()), return_exceptions=True)
        self._items.clear()
