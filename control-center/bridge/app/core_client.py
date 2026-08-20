from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import quote

import httpx


class CoreUnavailable(RuntimeError):
    pass


class CoreError(RuntimeError):
    pass


class CoreConflict(CoreError):
    pass


class OasCoreClient:
    """OAS Core 的 HTTP 客户端。

    Core 是单进程 FastAPI，`/{config}/{task}/args` 会现场生成 pydantic schema，
    并发打满会把 Core 的事件循环拖垮，所以这里统一加了并发闸门。
    """

    def __init__(self, base_url: str, timeout: float = 10.0, max_concurrency: int = 8):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = os.getenv("OAS_CORE_KEY", "").strip() or None
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            limits=httpx.Limits(max_connections=max_concurrency + 4, max_keepalive_connections=max_concurrency),
        )
        self._gate = asyncio.Semaphore(max_concurrency)

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self.api_key:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-OAS-Key", self.api_key)
            kwargs["headers"] = headers
        try:
            async with self._gate:
                response = await self._client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            raise CoreUnavailable(f"OAS Core 不可用: {self.base_url}") from exc
        if response.status_code >= 400:
            detail = response.text[:500]
            if response.status_code == 409:
                raise CoreConflict(f"OAS Core revision conflict: {detail}")
            raise CoreError(f"OAS Core 返回 {response.status_code}: {detail}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            # Core 偶尔返回纯文本，不应当因此报错。
            return response.text

    async def health(self) -> bool:
        try:
            return (await self._request("GET", "/test")) == "success"
        except (CoreUnavailable, CoreError):
            return False

    async def accounts(self) -> list[str]:
        return list(await self._request("GET", "/config_list"))

    async def menu(self) -> dict[str, list[str]]:
        return dict(await self._request("GET", "/script_menu"))

    async def task_args(self, account_id: str, task_id: str) -> dict[str, list[dict[str, Any]]]:
        account = quote(account_id, safe="")
        task = quote(task_id, safe="")
        result = await self._request("GET", f"/{account}/{task}/args")
        return dict(result) if isinstance(result, dict) else {}

    @staticmethod
    def normalize_value(value: Any, value_type: str) -> str:
        """把前端传来的值整理成 Core 的 script_task 能解析的字符串。

        Core 对格式非常敏感：
          date_time  必须是 %Y-%m-%d %H:%M:%S
          time       必须是 %H:%M:%S
          time_delta 必须是 DD HH:MM:SS
        少一位秒就会被 Core 判成 400。
        """
        if value_type == "boolean":
            return "true" if bool(value) else "false"
        if not isinstance(value, str):
            return str(value)

        text = value.strip()
        if value_type == "date_time":
            text = text.replace("T", " ")
            if len(text) == 16:
                text += ":00"
            return text
        if value_type == "time":
            parts = text.split(":")
            if len(parts) == 2:
                return f"{parts[0]:0>2}:{parts[1]:0>2}:00"
            if len(parts) == 3:
                return f"{parts[0]:0>2}:{parts[1]:0>2}:{parts[2]:0>2}"
            return text
        if value_type == "time_delta":
            # 兼容 "0 6:0:0"、"06:00:00" 这类不规范写法
            head, _, tail = text.partition(" ")
            if not tail:
                head, tail = "00", text
            parts = tail.split(":")
            while len(parts) < 3:
                parts.append("0")
            try:
                return f"{int(head or 0):02d} {int(parts[0] or 0):02d}:{int(parts[1] or 0):02d}:{int(parts[2] or 0):02d}"
            except ValueError:
                return text
        return text

    async def set_value(self, account_id: str, task_id: str, group: str, name: str, value: Any, value_type: str) -> Any:
        account = quote(account_id, safe="")
        task = quote(task_id, safe="")
        group_path = quote(group, safe="")
        name_path = quote(name, safe="")
        normalized = self.normalize_value(value, value_type)
        # Core 对 time_delta 的解析是 day = int(value[1])——只取第二个字符，
        # 天数 >=10 会被静默解析成个位数（"10"->0）。线格式表达不了两位天数，
        # 与其让配置悄悄存错，不如在这里明确拒绝。（上游修法见 handoff/15 C1）
        if value_type == "time_delta":
            try:
                days = int(normalized.split(" ", 1)[0])
            except (ValueError, IndexError):
                days = 0
            # Core 的线格式是两位天数 DD（C1 修复后 int(value[:2]) 可读 00-99）。
            # 99 天以内放行；三位数无法表达，明确拒绝而非静默截断。（handoff/16 C1）
            if days > 99:
                raise CoreError(f"{group}.{name}：时间间隔最多支持 99 天（收到 {days} 天）")
        # DeepSeek-13 2.2 (F-9): send the current config revision so Core can
        # reject stale single-value writes (428 missing / 409 conflict).
        revision = await self.config_revision(account_id)
        response = await self._request(
            "PUT",
            f"/{account}/{task}/{group_path}/{name_path}/value",
            params={"types": value_type, "value": normalized},
            headers={"If-Match": revision},
        )
        # Core 的 script_set_arg 在 pydantic 校验失败（如枚举值不合法、字段不存在）时
        # 返回 false 且 HTTP 200。不检查的话保存会"假成功"：界面提示已保存，
        # 配置文件里却什么都没写。（2026-07-26 联调发现，见 handoff/14）
        if response is False:
            raise CoreError(f"OAS Core 拒绝了 {group}.{name} 的值（返回 false），请检查取值是否在允许范围内")
        return response

    async def config_revision(self, account_id: str) -> str:
        result = await self._request(
            "GET",
            f"/{quote(account_id, safe='')}/config/revision",
        )
        return str((result or {}).get("revision") or "")

    async def patch_values(
        self,
        account_id: str,
        task_id: str,
        fields: list[dict[str, Any]],
        expected_revision: str,
    ) -> dict[str, Any]:
        normalized = []
        for field in fields:
            value_type = str(field.get("type") or "string")
            normalized_value = self.normalize_value(field.get("value"), value_type)
            if value_type == "time_delta":
                try:
                    days = int(normalized_value.split(" ", 1)[0])
                except (ValueError, IndexError):
                    days = 0
                if days > 99:
                    raise CoreError(
                        f"{field['group']}.{field['name']}：时间间隔最多支持 99 天（收到 {days} 天）"
                    )
            normalized.append({
                "group": field["group"],
                "name": field["name"],
                "value": normalized_value,
                "type": value_type,
            })
        result = await self._request(
            "PATCH",
            f"/{quote(account_id, safe='')}/{quote(task_id, safe='')}/values",
            json={
                "expected_revision": expected_revision,
                "fields": normalized,
            },
        )
        if not isinstance(result, dict) or not result.get("saved", False):
            raise CoreError("OAS Core did not confirm atomic config save")
        return result

    async def start_script(self, account_id: str, command_id: str | None = None) -> Any:
        """Core 的 REST 启动入口，作为 WebSocket 命令的兜底。

        DeepSeek-14 B1/A1: carries the SAME command_id as the WS attempt so
        Core's command ledger can replay instead of executing twice."""
        params = {"command_id": command_id} if command_id else None
        return await self._request(
            "POST", f"/{quote(account_id, safe='')}/start", params=params)

    async def stop_script(self, account_id: str, command_id: str | None = None) -> Any:
        params = {"command_id": command_id} if command_id else None
        return await self._request(
            "POST", f"/{quote(account_id, safe='')}/stop", params=params)

    async def copy_account(self, account_id: str, template: str = "template") -> Any:
        return await self._request("POST", "/config_copy", params={"file": account_id, "template": template})

    async def next_account_name(self) -> str:
        return str(await self._request("GET", "/config_new_name"))

    async def delete_account(self, account_id: str) -> Any:
        return await self._request("DELETE", "/config", params={"name": account_id})

    async def rename_account(self, old_name: str, new_name: str) -> Any:
        return await self._request("PUT", "/config", params={"old_name": old_name, "new_name": new_name})

    def websocket_url(self, account_id: str) -> str:
        scheme = "wss" if self.base_url.startswith("https://") else "ws"
        host = self.base_url.split("://", 1)[1]
        return f"{scheme}://{host}/ws/{quote(account_id, safe='')}"
