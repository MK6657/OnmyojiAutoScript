from __future__ import annotations

import asyncio
import atexit
import ctypes
import json
import os
import re
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .core_client import CoreConflict, CoreError, CoreUnavailable, OasCoreClient
from .events import EventHub
from .models import (
    AccountAction,
    AccountCreate,
    AccountMetadata,
    AccountPatch,
    AccountView,
    ConfigPatch,
    ConfigField,
    TaskConfig,
    TaskOrderPatch,
    TaskSummary,
    TemplatePayload,
)
from .repository import MetadataRepository
from .runtime import (
    AccountRuntime,
    CommandExecutionError,
    CommandInProgress,
    CommandNotAccepted,
    RuntimeRegistry,
)


BRIDGE_VERSION = "1.1.5"  # 1.1.5: fail-closed emulator identity binding
ROOT = Path(os.getenv("OAS_CONTROL_CENTER_ROOT", str(Path(__file__).resolve().parents[2])))
DEFAULT_DATA_DIR = ROOT / "data"
DATA_DIR = Path(os.getenv("OAS_CONTROL_CENTER_DATA_DIR", str(DEFAULT_DATA_DIR)))
CORE_URL = os.getenv("OAS_CORE_URL", "http://127.0.0.1:22267")
INTEGRATION_TEST_MODE = os.getenv("OAS_INTEGRATION_TEST", "").strip().lower() in {"1", "true", "yes"}
INTEGRATION_DATA_ISOLATED = DATA_DIR.resolve() != DEFAULT_DATA_DIR.resolve()
# 已启用任务的缓存时长。任何写操作都会立刻失效对应账号的缓存，
# 所以这个值只影响「别处改了配置文件」这类外部变更的感知延迟。
TASK_CACHE_TTL = float(os.getenv("OAS_TASK_CACHE_TTL", "45"))


TASK_LABELS = {
    "Script": "运行设置", "Restart": "自动重启", "GlobalGame": "全局游戏设置",
    "Orochi": "御魂", "OrochiMoans": "御魂呻吟", "Sougenbi": "业原火", "FallenSun": "日轮之城",
    "EternitySea": "永生之海", "SixRealms": "六道之门",
    "DailyTrifles": "每日琐事", "AreaBoss": "地狱鬼王", "GoldYoukai": "金币妖怪",
    "ExperienceYoukai": "经验妖怪", "Nian": "年兽", "TalismanPass": "花合战",
    "DemonEncounter": "封魔之时", "Pets": "小猫咪", "SoulsTidy": "御魂整理",
    "Delegation": "式神委派", "WantedQuests": "悬赏封印", "Tako": "石距",
    "AutoCheckinBigGod": "大神签到",
    "BondlingFairyland": "契灵之境", "EvoZone": "觉醒副本", "GoryouRealm": "御灵之境",
    "Exploration": "探索", "Hyakkiyakou": "百鬼夜行", "HeroTest": "英雄试炼",
    "FindJade": "寻找勾玉", "MemoryScrolls": "绫卷",
    "KekkaiUtilize": "结界蹭卡", "KekkaiActivation": "结界挂卡", "RealmRaid": "个人突破",
    "RyouToppa": "寮突破", "Dokan": "道馆", "CollectiveMissions": "集体任务", "Hunt": "狩猎战",
    "AbyssShadows": "暗影迷宫", "GuildBanquet": "寮宴会", "DemonRetreat": "退治恶鬼",
    "GuildActivityMonitor": "寮活动监控",
    "TrueOrochi": "真·八岐大蛇", "RichMan": "大富翁", "Secret": "秘闻之境",
    "WeeklyTrifles": "每周琐事", "MysteryShop": "神秘商店", "Duel": "自动斗技",
    "ActivityShikigami": "当期式神爬塔", "MetaDemon": "超鬼王", "FrogBoss": "青蛙瓷器",
    "FloatParade": "花车巡游", "Quiz": "智力问答", "KittyShop": "小猫の店", "DyeTrials": "染色试炼",
    "XiuxingHexun": "修行合训",
    "XiuxingHexunClimb": "修行合训爬塔",
}

CATEGORY_LABELS = {
    "Overview": "概览",
    "Script": "运行与设备",
    "Soul Zones": "御魂副本",
    "Daily Task": "日常任务",
    "Liver Emperor Exclusive": "肝帝专属",
    "Guild": "阴阳寮",
    "Weekly Task": "每周任务",
    "Activity Task": "限时活动",
    "Other": "其他",
}


def task_label(task_id: str) -> str:
    return TASK_LABELS.get(task_id, task_id)


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def state_view(runtime: Any) -> tuple[str, str, bool]:
    if runtime is None:
        return "offline", "未连接", False
    return runtime.state, runtime.state_label, runtime.connected


def infer_window_serial(process: str, command_line: str, connected_serials: set[str]) -> str | None:
    """只在映射有确定证据时返回 ADB serial，避免把账号绑定到另一台模拟器。"""
    process_lower = str(process or "").lower()
    command_line = str(command_line or "")

    if ("mumu" in process_lower or "nemu" in process_lower) and command_line:
        match = re.search(r"(?:^|\s)-v\s+(\d+)(?:\s|$)", command_line)
        instance_index = int(match.group(1)) if match else 0
        # MuMu 12 的 OAS/NemuIpc 实例表使用 16384 + 32*N，不使用 adb devices
        # 里可能同时出现的 emulator-5554/5556 别名。
        expected = f"127.0.0.1:{16384 + instance_index * 32}"
        return expected if expected in connected_serials else None

    # Other emulator brands do not expose one shared, verified mapping contract here.
    # A single online ADB device is not evidence that it belongs to this window.
    return None


def _process_command_lines(process_ids: set[int]) -> dict[int, str]:
    if os.name != "nt" or not process_ids:
        return {}
    ids = ",".join(str(value) for value in sorted(process_ids))
    command = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        f"$ids=@({ids}); Get-CimInstance Win32_Process | "
        "Where-Object { $ids -contains [int]$_.ProcessId } | "
        "ForEach-Object { \"{0}`t{1}\" -f $_.ProcessId,$_.CommandLine }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    lines: dict[int, str] = {}
    for line in result.stdout.splitlines():
        pid, separator, value = line.partition("\t")
        if separator and pid.strip().isdigit():
            lines[int(pid.strip())] = value.strip()
    return lines


def _connected_adb_serials() -> set[str]:
    project_root = ROOT.parent
    candidates = [
        os.getenv("ADB_PATH"),
        shutil.which("adb"),
        str(project_root / ".venv" / "Lib" / "site-packages" / "adbutils" / "binaries" / "adb.exe"),
    ]
    adb = next((candidate for candidate in candidates if candidate and Path(candidate).exists()), None)
    if not adb:
        return set()
    try:
        result = subprocess.run(
            [adb, "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    serials = set()
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device":
            serials.add(fields[0])
    return serials


def visible_windows() -> list[dict[str, Any]]:
    """列出 Windows 上的可见顶层窗口，供设备绑定选择。非 Windows 返回空列表。"""
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    windows: list[dict[str, Any]] = []

    @enum_windows_proc
    def callback(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        title = title_buffer.value.strip()
        if not title:
            return True

        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        process_name = ""
        process_handle = kernel32.OpenProcess(0x1000, False, process_id.value)
        if process_handle:
            try:
                size = ctypes.c_ulong(260)
                path_buffer = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(process_handle, 0, path_buffer, ctypes.byref(size)):
                    process_name = Path(path_buffer.value).name
            finally:
                kernel32.CloseHandle(process_handle)

        windows.append({
            "handle": int(hwnd),
            "title": title,
            "pid": int(process_id.value),
            "process": process_name,
        })
        return True

    user32.EnumWindows(callback, 0)
    emulator_windows = [
        item for item in windows
        if re.search(r"mumu|nemu|dnplayer|ldplayer|nox|hd-player|bluestacks|memu",
                     item["process"], re.IGNORECASE)
    ]
    command_lines = _process_command_lines({item["pid"] for item in emulator_windows})
    connected_serials = _connected_adb_serials()
    for item in emulator_windows:
        serial = infer_window_serial(
            item["process"], command_lines.get(item["pid"], ""), connected_serials
        )
        if serial:
            item["serial"] = serial
            item["serial_source"] = "verified_adb_mapping"
    return sorted(windows, key=lambda item: (item["title"].casefold(), item["handle"]))


class TaskStateCache:
    """账号 -> {任务ID: 下次运行时间} 的缓存。

    背景：原实现每次 `GET /accounts` 都会对每个账号的每个任务调用一次
    Core 的 `/{config}/{task}/args`（3 个账号 × 53 个任务 = 159 次请求，
    而每次请求 Core 都要现场生成 pydantic schema），界面因此明显卡顿。

    现在有三级来源，从便宜到贵：
      1. Core 通过 WebSocket 推送的 schedule 快照（0 次 HTTP 请求）；
      2. 本地缓存（0 次请求）；
      3. 全量扫描（仅在前两者都没有时执行，且带并发闸门）。
    """

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, dict[str, str | None]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def peek(self, account_id: str) -> dict[str, str | None] | None:
        entry = self._items.get(account_id)
        if entry is None:
            return None
        stamp, value = entry
        if time.monotonic() - stamp > TASK_CACHE_TTL:
            return None
        return value

    def put(self, account_id: str, value: dict[str, str | None]) -> None:
        self._items[account_id] = (time.monotonic(), value)

    def invalidate(self, account_id: str | None = None) -> None:
        if account_id is None:
            self._items.clear()
        else:
            self._items.pop(account_id, None)

    def lock(self, account_id: str) -> asyncio.Lock:
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]


class Bridge:
    def __init__(self) -> None:
        self._instance_lock_handle = self._acquire_instance_lock()
        self.core = OasCoreClient(CORE_URL)
        self.events = EventHub()
        try:
            self.repository = MetadataRepository(DATA_DIR / "control_center.db")
        except Exception:
            self._release_instance_lock()
            raise
        atexit.register(self._release_instance_lock)
        self.runtimes = RuntimeRegistry(self.core, self.events)
        self.task_cache = TaskStateCache()
        self._catalog: list[TaskSummary] | None = None

    @staticmethod
    def _acquire_instance_lock():
        """Prevent two Bridge processes from sharing one SQLite data directory."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        lock_path = DATA_DIR / "bridge.instance.lock"
        handle = lock_path.open("a+", encoding="utf-8")
        handle.seek(0)
        handle.write("0")
        handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError) as exc:
            handle.close()
            raise RuntimeError(
                f"Bridge data directory is already in use: {DATA_DIR.resolve()}"
            ) from exc
        return handle

    def _release_instance_lock(self) -> None:
        handle = getattr(self, "_instance_lock_handle", None)
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (OSError, ImportError):
            pass
        finally:
            handle.close()
            self._instance_lock_handle = None

    async def close(self) -> None:
        try:
            await self.runtimes.close()
            await self.core.close()
        finally:
            self._release_instance_lock()

    async def require_core(self) -> None:
        if not await self.core.health():
            raise HTTPException(status_code=503, detail="OAS Core 未启动，请先启动原项目服务")

    async def catalog(self, force: bool = False) -> list[TaskSummary]:
        """Read the current Core catalog so activity teardown cannot stay stale."""
        menu = await self.core.menu()
        result: list[TaskSummary] = []
        for category, tasks in menu.items():
            for task_id in tasks:
                result.append(TaskSummary(id=task_id, title=task_label(task_id), category=category_label(category)))
        self._catalog = result
        return result

    async def account_ids(self) -> list[str]:
        await self.require_core()
        return await self.core.accounts()

    async def _scan_enabled(self, account_id: str, catalog: list[TaskSummary]) -> dict[str, str | None]:
        async def inspect(task: TaskSummary) -> tuple[str, str | None] | None:
            try:
                args = await self.core.task_args(account_id, task.id)
            except (CoreError, CoreUnavailable):
                return None
            fields = {field.get("name"): field for field in args.get("scheduler", [])}
            enable = fields.get("enable")
            if enable is None or not enable.get("value"):
                return None
            if task.id in {"XiuxingHexun", "XiuxingHexunClimb"}:
                activity_fields = {
                    field.get("name"): field
                    for field in args.get("activity_enabled", [])
                }
                activity_enabled = activity_fields.get("activity_enabled")
                if activity_enabled is not None and not activity_enabled.get("value"):
                    return None
            next_run = fields.get("next_run", {}).get("value")
            return task.id, str(next_run) if next_run else None

        checked = await asyncio.gather(*(inspect(task) for task in catalog))
        return {item[0]: item[1] for item in checked if item is not None}

    async def enabled_map(self, account_id: str, catalog: list[TaskSummary], force: bool = False) -> dict[str, str | None]:
        if not force:
            runtime = self.runtimes.peek(account_id)
            if runtime is not None:
                scheduled = runtime.scheduled_tasks()
                if scheduled is not None:
                    self.task_cache.put(account_id, scheduled)
                    return scheduled
            cached = self.task_cache.peek(account_id)
            if cached is not None:
                return cached

        async with self.task_cache.lock(account_id):
            if not force:
                cached = self.task_cache.peek(account_id)
                if cached is not None:
                    return cached
            scanned = await self._scan_enabled(account_id, catalog)
            self.task_cache.put(account_id, scanned)
            return scanned

    async def enabled_tasks(
        self, account_id: str, catalog: list[TaskSummary] | None = None, force: bool = False
    ) -> list[TaskSummary]:
        catalog = catalog or await self.catalog()
        enabled = await self.enabled_map(account_id, catalog, force=force)
        by_id = {task.id: task for task in catalog}
        result: list[TaskSummary] = []
        for task_id, next_run in enabled.items():
            base = by_id.get(task_id)
            if base is None:
                continue
            result.append(base.model_copy(update={"enabled": True, "next_run": next_run}))
        order = {task.id: index for index, task in enumerate(catalog)}
        result.sort(key=lambda task: order.get(task.id, len(order)))
        return result

    async def account_view(self, metadata: AccountMetadata, catalog: list[TaskSummary] | None = None) -> AccountView:
        runtime = self.runtimes.peek(metadata.id)
        state, state_label, connected = state_view(runtime)
        selected = await self.enabled_tasks(metadata.id, catalog)
        return AccountView(
            **metadata.model_dump(),
            state=state,
            state_label=state_label,
            connected=connected,
            selected_count=len(selected),
            selected_tasks=[task.id for task in selected],
            next_run=selected[0].next_run if selected else None,
        )


bridge = Bridge()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await bridge.close()


app = FastAPI(title="OAS Control Center Bridge", version=BRIDGE_VERSION, lifespan=lifespan)
# 白名单写死端口会让任何新的本地前端（对比版、自定义端口）直接被浏览器拦掉，
# 这里改成放行本机任意端口；Bridge 本来就只监听 127.0.0.1，不对外提供服务。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def translate_core_error(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, CoreUnavailable):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(error, CoreConflict):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, CoreError):
        return HTTPException(status_code=502, detail=str(error))
    return HTTPException(status_code=500, detail=str(error))


def _confirmed_command_result(command: str, result: Any) -> dict[str, Any]:
    if not isinstance(result, dict) or not result.get("success", False):
        reason = result.get("reason", "missing_completion_receipt") if isinstance(result, dict) else "missing_completion_receipt"
        raise CoreError(f"Core command failed: command={command}, reason={reason}")
    return result


async def _send_account_command(
    account_id: str,
    command: str,
    runtime: AccountRuntime | None,
) -> dict[str, Any]:
    if runtime is not None:
        try:
            result = await runtime.try_command(command)
        except CommandInProgress as error:
            # DeepSeek-14 B1/A1: Core acked but the receipt is still in flight.
            # Surface 202/in_progress; never re-issue and never report failure.
            raise HTTPException(
                status_code=202,
                detail={"status": "in_progress", "command_id": error.command_id},
            ) from error
        except CommandNotAccepted as error:
            # WS never accepted the command (no ack, no receipt): REST fallback
            # carries the SAME command_id so Core can replay instead of
            # double-run.
            fallback_id = error.command_id
        except CommandExecutionError as error:
            raise CoreError(str(error)) from error
        else:
            if result:
                return _confirmed_command_result(command, result)
            fallback_id = getattr(runtime, "_last_command_id", None)
    else:
        fallback_id = None
    if command == "start":
        result = await bridge.core.start_script(account_id, command_id=fallback_id)
    elif command == "stop":
        result = await bridge.core.stop_script(account_id, command_id=fallback_id)
    else:
        raise HTTPException(status_code=503, detail=f"账号 {account_id} 的 OAS WebSocket 未连接")
    if isinstance(result, dict) and result.get("status") == "in_progress":
        # DeepSeek-14 B1 v2: Core is still executing the WS-side command; the
        # REST fallback must surface 202 instead of a failure.
        raise HTTPException(
            status_code=202,
            detail={"status": "in_progress", "command_id": fallback_id},
        )
    return _confirmed_command_result(command, result)


@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    core_ok = await bridge.core.health()
    return {
        "status": "ok",
        "bridge": "ok",
        "core": "ok" if core_ok else "offline",
        "core_url": CORE_URL,
        "integration_test": INTEGRATION_TEST_MODE,
        "data_dir": str(DATA_DIR.resolve()) if INTEGRATION_TEST_MODE else None,
        "data_isolated": INTEGRATION_TEST_MODE and INTEGRATION_DATA_ISOLATED,
        "version": BRIDGE_VERSION,
    }


@app.get("/api/v1/accounts", response_model=list[AccountView])
async def list_accounts() -> list[AccountView]:
    try:
        ids = await bridge.account_ids()
        metadata = bridge.repository.sync_accounts(ids)
        catalog = await bridge.catalog()
        return await asyncio.gather(*(bridge.account_view(item, catalog) for item in metadata))
    except Exception as error:
        raise translate_core_error(error) from error


@app.post("/api/v1/accounts", response_model=AccountView)
async def create_account(payload: AccountCreate) -> AccountView:
    try:
        existing = await bridge.account_ids()
        account_id = payload.name.strip() if payload.name and payload.name.strip() else await bridge.core.next_account_name()
        if not account_id or account_id == "template" or "/" in account_id or "\\" in account_id:
            raise HTTPException(status_code=400, detail="账号名称不可用")
        # Core 的 config_copy 遇到同名文件只会在日志里报错并静默返回，
        # 不先检查的话前端会以为创建成功，实际拿到的是别人的配置。
        if account_id in existing:
            raise HTTPException(status_code=409, detail=f"账号 {account_id} 已存在")
        await bridge.core.copy_account(account_id)
        if account_id not in await bridge.core.accounts():
            raise HTTPException(status_code=502, detail=f"Core 没有创建出配置文件 {account_id}.json")
        metadata = bridge.repository.upsert(AccountMetadata(
            id=account_id, name=account_id, avatar=payload.avatar,
            tags=payload.tags, device_label=payload.device_label,
        ))
        bridge.task_cache.invalidate(account_id)
        await bridge.events.emit("account.created", account_id)
        return await bridge.account_view(metadata, await bridge.catalog())
    except Exception as error:
        raise translate_core_error(error) from error


@app.patch("/api/v1/accounts/{account_id}", response_model=AccountView)
async def patch_account(account_id: str, payload: AccountPatch) -> AccountView:
    metadata = bridge.repository.get(account_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    data = metadata.model_dump()
    patch = payload.model_dump(exclude_unset=True)
    renamed = False
    if "name" in patch and patch["name"] and patch["name"] != account_id:
        new_id = patch["name"].strip()
        if not new_id or new_id == "template" or "/" in new_id or "\\" in new_id:
            raise HTTPException(status_code=400, detail="账号名称不可用")
        # 改名前必须拿到 Core 的完成回执。停止失败时保留运行时和元数据，
        # 不能把仍在运行的 worker 变成脱管进程。
        try:
            runtime = bridge.runtimes.peek(account_id)
            if runtime is None:
                await _send_account_command(account_id, "stop", None)
            else:
                async with runtime.action_lock:
                    await _send_account_command(account_id, "stop", runtime)
            await bridge.core.rename_account(account_id, new_id)
        except Exception as error:
            raise translate_core_error(error) from error
        data["id"] = new_id
        renamed = True
    data.update({key: value for key, value in patch.items() if value is not None})

    if renamed:
        updated = bridge.repository.rename(account_id, AccountMetadata(**data))
        await bridge.runtimes.drop(account_id)
        bridge.task_cache.invalidate(account_id)
        bridge.task_cache.invalidate(updated.id)
    else:
        updated = bridge.repository.upsert(AccountMetadata(**data))
    return await bridge.account_view(updated, await bridge.catalog())


@app.delete("/api/v1/accounts/{account_id}")
async def delete_account(account_id: str) -> dict[str, bool]:
    if account_id == "template":
        raise HTTPException(status_code=400, detail="不能删除模板账号")
    runtime = bridge.runtimes.peek(account_id)
    try:
        if runtime is None:
            await _send_account_command(account_id, "stop", None)
        else:
            async with runtime.action_lock:
                await _send_account_command(account_id, "stop", runtime)
        await bridge.core.delete_account(account_id)
    except Exception as error:
        raise translate_core_error(error) from error
    await bridge.runtimes.drop(account_id)
    bridge.repository.delete(account_id)
    bridge.task_cache.invalidate(account_id)
    await bridge.events.emit("account.deleted", account_id)
    return {"deleted": True}


@app.get("/api/v1/tasks/catalog", response_model=list[TaskSummary])
async def task_catalog(refresh: bool = False) -> list[TaskSummary]:
    try:
        return await bridge.catalog(force=refresh)
    except Exception as error:
        raise translate_core_error(error) from error


@app.get("/api/v1/windows")
async def windows() -> list[dict[str, Any]]:
    return visible_windows()


@app.get("/api/v1/accounts/{account_id}/tasks", response_model=list[TaskSummary])
async def account_tasks(account_id: str, refresh: bool = False) -> list[TaskSummary]:
    try:
        if account_id not in await bridge.account_ids():
            raise HTTPException(status_code=404, detail="账号不存在")
        return await bridge.enabled_tasks(account_id, force=refresh)
    except Exception as error:
        raise translate_core_error(error) from error


@app.get("/api/v1/accounts/{account_id}/schedule")
async def account_schedule(account_id: str) -> dict[str, Any]:
    """Core 的调度快照：正在执行 / 待执行 / 等待时间到达。

    旧版界面完全没有暴露这份数据，用户看不到「下一个跑什么、什么时候跑」。
    """
    runtime = bridge.runtimes.get(account_id)
    await runtime.wait_connected(timeout=2.5)
    if runtime.connected:
        try:
            await runtime.command("get_schedule")
            await asyncio.sleep(0.35)
        except Exception:
            pass
    schedule = runtime.last_schedule or {}
    return {
        "account_id": account_id,
        "running": schedule.get("running") or {},
        "pending": schedule.get("pending") or [],
        "waiting": schedule.get("waiting") or [],
        "state": runtime.state,
        "state_label": runtime.state_label,
        "connected": runtime.connected,
    }


@app.put("/api/v1/accounts/{account_id}/tasks/{task_id}/enabled", response_model=TaskSummary)
async def set_task_enabled(account_id: str, task_id: str, enabled: bool) -> TaskSummary:
    try:
        catalog = await bridge.catalog(force=True)
        match = next((item for item in catalog if item.id == task_id), None)
        if enabled and match is None:
            raise HTTPException(status_code=409, detail=f"任务 {task_id} 当前已下架，不能启用")
        revision = await bridge.core.config_revision(account_id)
        await bridge.core.patch_values(
            account_id,
            task_id,
            [{
                "group": "scheduler",
                "name": "enable",
                "value": enabled,
                "type": "boolean",
            }],
            revision,
        )
        bridge.task_cache.invalidate(account_id)
        if match is None:
            match = TaskSummary(id=task_id, title=task_label(task_id), category=category_label("Other"))
        args = await bridge.core.task_args(account_id, task_id)
        fields = {field.get("name"): field for field in args.get("scheduler", [])}
        next_run = fields.get("next_run", {}).get("value")
        runtime = bridge.runtimes.peek(account_id)
        if runtime is not None:
            # Core 可能已经离线；先丢弃旧快照，避免它覆盖刚写入的真实配置。
            runtime.invalidate_schedule()
            if runtime.connected:
                # 让 Core 重算调度，否则概览里的排期会停留在旧数据上。
                await runtime.try_command("get_schedule")
        await bridge.events.emit("task.state", account_id, task_id, payload={"enabled": enabled})
        return match.model_copy(update={"enabled": enabled, "next_run": str(next_run) if next_run else None})
    except Exception as error:
        raise translate_core_error(error) from error


@app.get("/api/v1/accounts/{account_id}/tasks/{task_id}/config", response_model=TaskConfig)
async def task_config(account_id: str, task_id: str) -> TaskConfig:
    try:
        raw = await bridge.core.task_args(account_id, task_id)
        if not raw:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 在账号 {account_id} 中不存在")
        groups: dict[str, list[ConfigField]] = {}
        for group, fields in raw.items():
            groups[group] = [
                ConfigField(
                    name=field.get("name", ""),
                    title=field.get("title") or field.get("name", ""),
                    description=field.get("description") or "",
                    default=field.get("default"),
                    value=field.get("value"),
                    type=field.get("type", "string"),
                    options=field.get("enumEnum", field.get("enum", [])) or [],
                )
                for field in fields
            ]
        revision = await bridge.core.config_revision(account_id)
        return TaskConfig(
            task_id=task_id,
            title=task_label(task_id),
            groups=groups,
            revision=revision,
        )
    except Exception as error:
        raise translate_core_error(error) from error


@app.patch("/api/v1/accounts/{account_id}/tasks/{task_id}/config")
async def patch_task_config(
    account_id: str,
    task_id: str,
    payload: ConfigPatch,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    try:
        expected_revision = payload.revision or (if_match or "").strip().strip('"')
        if not expected_revision:
            raise HTTPException(status_code=428, detail="配置已过期：保存请求缺少 revision，请重新加载后再试")
        # 只在真的缺类型时读一次 schema。原实现是「每个缺类型的字段读一次」，
        # 保存一张大表单能把同一份几十 KB 的 schema 反复拉几十遍。
        schema: dict[str, list[dict[str, Any]]] | None = None
        prepared_fields = []
        touched_scheduler = False
        for field in payload.fields:
            value_type = field.type
            if value_type is None:
                if schema is None:
                    schema = await bridge.core.task_args(account_id, task_id)
                entry = next((item for item in schema.get(field.group, []) if item.get("name") == field.name), None)
                value_type = (entry or {}).get("type", "string")
            prepared_fields.append({
                "group": field.group,
                "name": field.name,
                "value": field.value,
                "type": value_type,
            })
            if field.group == "scheduler":
                touched_scheduler = True

        result = await bridge.core.patch_values(
            account_id,
            task_id,
            prepared_fields,
            expected_revision,
        )
        updated = int(result.get("updated", len(prepared_fields)))

        if touched_scheduler:
            bridge.task_cache.invalidate(account_id)
            runtime = bridge.runtimes.peek(account_id)
            if runtime is not None:
                runtime.invalidate_schedule()
                if runtime.connected:
                    await runtime.try_command("get_schedule")
        await bridge.events.emit("task.configured", account_id, task_id, payload={"fields": updated})
        return {
            "saved": True,
            "updated": updated,
            "revision": result.get("revision"),
        }
    except Exception as error:
        raise translate_core_error(error) from error


@app.post("/api/v1/accounts/{account_id}/actions")
async def account_action(account_id: str, payload: AccountAction) -> dict[str, Any]:
    try:
        if account_id not in await bridge.account_ids():
            raise HTTPException(status_code=404, detail="账号不存在")
        runtime = bridge.runtimes.get(account_id)

        async def send(command: str) -> dict[str, Any]:
            """先走 WebSocket；连不上时退回 Core 的 REST 入口，
            这样「Core 在跑但 WS 刚断」不会直接变成一次失败的启动。"""
            return await _send_account_command(account_id, command, runtime)

        async def execute_action() -> list[dict[str, Any]]:
            command_results = []
            if payload.action == "refresh":
                await runtime.wait_connected(timeout=2.0)
                for command in ("get_state", "get_schedule"):
                    result = await runtime.try_command(command)
                    if result:
                        command_results.append(result)
            elif payload.action == "restart":
                command_results.append(await send("stop"))
                await asyncio.sleep(0.4)
                command_results.append(await send("start"))
            else:
                command_results.append(await send(payload.action))
            return command_results

        async with runtime.action_lock:
            command_results = await execute_action()
        return {
            "accepted": True,
            "status": "completed",
            "account_id": account_id,
            "action": payload.action,
            "commands": command_results,
            "state": runtime.snapshot(),
        }
    except Exception as error:
        raise translate_core_error(error) from error


@app.get("/api/v1/accounts/{account_id}/commands/{command_id}")
async def account_command_result(account_id: str, command_id: str) -> dict[str, Any]:
    """DeepSeek-14 B1/A1: query channel for a command whose receipt arrived
    after the original HTTP request returned 202/in_progress."""
    runtime = bridge.runtimes.get(account_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    late = runtime._late_results.get(command_id)
    if late is not None:
        return {"status": "completed", **late}
    future = runtime._pending_commands.get(command_id)
    if future is not None and future.done() and not future.cancelled():
        return {"status": "completed", **future.result()}
    if command_id in runtime._acked_commands or (future is not None and not future.done()):
        return {"status": "in_progress", "command_id": command_id}
    return {"status": "unknown", "command_id": command_id}


@app.get("/api/v1/accounts/{account_id}/logs")
async def account_logs(account_id: str, limit: int = 100) -> list[dict[str, Any]]:
    runtime = bridge.runtimes.get(account_id)
    return list(runtime.logs)[-max(1, min(limit, 300)):]


# --------------------------------------------------------------- UI 元数据

@app.get("/api/v1/templates")
async def list_templates() -> list[dict[str, Any]]:
    return bridge.repository.templates()


@app.post("/api/v1/templates")
async def save_template(payload: TemplatePayload) -> dict[str, Any]:
    return bridge.repository.save_template(payload.model_dump())


@app.delete("/api/v1/templates/{template_id}")
async def delete_template(template_id: str) -> dict[str, bool]:
    bridge.repository.delete_template(template_id)
    return {"deleted": True}


@app.get("/api/v1/accounts/{account_id}/task-order")
async def get_task_order(account_id: str) -> list[str]:
    return bridge.repository.task_order(account_id)


@app.put("/api/v1/accounts/{account_id}/task-order")
async def put_task_order(account_id: str, payload: TaskOrderPatch) -> dict[str, Any]:
    bridge.repository.save_task_order(account_id, payload.order)
    return {"saved": True, "order": payload.order}


@app.websocket("/api/v1/events")
async def events(websocket: WebSocket) -> None:
    await bridge.events.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await bridge.events.disconnect(websocket)
    except Exception:
        await bridge.events.disconnect(websocket)
