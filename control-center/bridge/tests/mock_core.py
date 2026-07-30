# This Python file uses the following encoding: utf-8
"""OAS Core 模拟器（开发/联调用，随项目交付）。

用途：在不启动游戏、模拟器和真实 OAS Core 的情况下，给 Bridge 提供一个
行为逼真的 Core，用于前后端联调、回归测试和界面开发。

接口逐条对齐 `module/server/script_router.py`（2026-07-26 版），包括几个
"特色行为"也一并复刻，因为 Bridge 的防御逻辑正是针对它们写的：
  - `POST /config_copy` 遇到同名文件静默返回（不报错）——验证 Bridge 的 409 查重；
  - `PUT .../value` 类型解析失败返回 400 "Argument type error"；枚举值不合法时
    返回 false（HTTP 200）——对应真实 Core 里 pydantic 校验失败的返回；
  - `WS /ws/{config}` 在该账号没有任何启用任务时：accept → 推送 state → 立即断开
    （真实 Core 在 `config.get_next()` 处抛 RequestHumanTakeover）——验证 Bridge
    的秒断退避，不修会出现每秒重连风暴。

任务字段结构从真实的 config/*.json 派生（自动向上查找项目根的 config 目录），
因此任务名、分组名、字段名与真实环境一致。全部数据在内存里，不写任何文件。

启动（用户机器，Bridge 的虚拟环境即可）：
    cd D:\\OSAyys\\control-center\\bridge
    .venv\\Scripts\\python.exe -m uvicorn tests.mock_core:app --host 127.0.0.1 --port 22268
或使用 launcher/start-dev-stack.ps1 一键拉起 mock Core + Bridge + UI-claude。

调试辅助接口（真实 Core 没有，仅本模拟器提供）：
    GET  /__mock__/stats            各接口调用计数、WS 连接次数
    POST /__mock__/fault?on=true    模拟 Core 故障（/test 失效、args/value 返回 500）
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

# ----------------------------------------------------------------- 数据来源

HERE = Path(__file__).resolve().parent


def discover_config() -> Path | None:
    explicit = os.getenv("OAS_MOCK_CONFIG", "")
    if explicit and Path(explicit).exists():
        return Path(explicit)
    local = HERE / "fixtures" / "oas1.json"
    if local.exists():
        return local
    probe = HERE
    for _ in range(8):
        for name in ("oas1.json", "template.json"):
            candidate = probe / "config" / name
            if candidate.exists():
                return candidate
        if probe.parent == probe:
            break
        probe = probe.parent
    return None


CONFIG_PATH = discover_config()
RAW: dict[str, Any] = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH else {}

# 与 module/config/config_menu.py 的 gui_menu_list 一致（含空的 Overview）
MENU: dict[str, list[str]] = {
    "Overview": [],
    "Script": ["Script", "Restart", "GlobalGame"],
    "Soul Zones": ["Orochi", "Sougenbi", "FallenSun", "EternitySea", "SixRealms"],
    "Daily Task": ["DailyTrifles", "AreaBoss", "GoldYoukai", "ExperienceYoukai", "Nian",
                   "TalismanPass", "DemonEncounter", "Pets", "SoulsTidy", "Delegation",
                   "WantedQuests", "Tako", "AutoCheckinBigGod"],
    "Liver Emperor Exclusive": ["BondlingFairyland", "EvoZone", "GoryouRealm", "Exploration",
                                "Hyakkiyakou", "HeroTest", "FindJade", "MemoryScrolls"],
    "Guild": ["KekkaiUtilize", "KekkaiActivation", "RealmRaid", "RyouToppa", "Dokan",
              "CollectiveMissions", "Hunt", "AbyssShadows", "GuildBanquet", "DemonRetreat",
              "GuildActivityMonitor"],
    "Weekly Task": ["TrueOrochi", "RichMan", "Secret", "WeeklyTrifles", "MysteryShop", "Duel"],
    "Activity Task": ["ActivityShikigami", "MetaDemon", "FrogBoss", "FloatParade", "Quiz",
                      "KittyShop", "DyeTrials"],
}
ALL_TASKS = [task for tasks in MENU.values() for task in tasks]

ENUMS: dict[str, list[str]] = {
    "serial": ["auto", "127.0.0.1:16384", "127.0.0.1:7555", "emulator-5554"],
    "package_name": ["auto", "com.netease.onmyoji", "com.netease.onmyoji.bili",
                     "com.netease.onmyoji.huawei", "com.netease.onmyoji.mi"],
    "screenshot_method": ["auto", "ADB", "ADB_nc", "DroidCast", "DroidCast_raw", "scrcpy",
                          "nemu_ipc", "ldopengl"],
    "control_method": ["minitouch", "maatouch", "MaaTouch", "ADB", "Hermit", "nemu_ipc"],
    "emulatorinfo_type": ["auto", "MuMuPlayer12", "NoxPlayer", "LDPlayer", "BlueStacks"],
    "when_task_queue_empty": ["goto_main", "stay_there", "close_game", "close_game_emulator", "shutdown"],
    "schedule_rule": ["Filter", "Fifo", "Priority"],
    "utilize_rule": ["default", "ap_first", "exp_first"],
    "select_friend_list": ["same_server", "cross_server", "recent_friend"],
    "shikigami_class": ["N", "R", "SR", "SSR", "SP"],
    "green_mark": ["greenmain", "greenleft1", "greenleft2", "greenleft3", "greenleft4", "greenleft5"],
    "group_class": ["leader", "member", "alone"],
    "invite_class": ["autofind", "recent_friend", "wild"],
    "invite_number": ["one", "two"],
}

_snake_1 = re.compile(r"([a-z0-9])([A-Z])")
_snake_2 = re.compile(r"([A-Z]+)([A-Z][a-z])")


def to_snake(value: str) -> str:
    return _snake_2.sub(r"\1_\2", _snake_1.sub(r"\1_\2", value)).lower()


def title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in str(value).split("_") if part)


def infer_type(value: Any, key: str) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
            return "date_time"
        if re.fullmatch(r"\d{2} \d{2}:\d{2}:\d{2}", value):
            return "time_delta"
        if re.fullmatch(r"\d{2}:\d{2}:\d{2}", value):
            return "time"
        if key in ENUMS:
            return "enum"
    return "string"


def build_field(key: str, value: Any) -> dict[str, Any]:
    kind = infer_type(value, key)
    field: dict[str, Any] = {
        "name": key,
        "title": title_case(key),
        "description": f"{title_case(key)} help",
        "default": value,
        "value": value,
        "type": kind,
    }
    if key in ENUMS:
        options = list(ENUMS[key])
        if isinstance(value, str) and value and value not in options:
            options.append(value)
        field["enumEnum"] = options
        field["type"] = "enum"
    return field


def base_groups(task_id: str) -> dict[str, list[dict[str, Any]]]:
    raw = RAW.get(to_snake(task_id))
    if not isinstance(raw, dict):
        return {"scheduler": [
            build_field("enable", False),
            build_field("next_run", "2023-01-01 00:00:00"),
            build_field("priority", 5),
            build_field("success_interval", "00 06:00:00"),
            build_field("failure_interval", "00 06:00:00"),
            build_field("server_update", "09:00:00"),
        ]}
    groups: dict[str, list[dict[str, Any]]] = {}
    for group_name, group_value in raw.items():
        if not isinstance(group_value, dict):
            continue
        fields = [build_field(key, "" if value is None else value)
                  for key, value in group_value.items()
                  if not isinstance(value, (dict, list))]
        if fields:
            groups[group_name] = fields
    return groups or {"scheduler": [build_field("enable", False)]}


# ----------------------------------------------------------------- 内存状态

STATE_INACTIVE, STATE_RUNNING = 0, 1
DEFAULT_ENABLED = {
    "oas1": {"Orochi", "KekkaiUtilize", "WantedQuests"},
    "oas2": {"Pets", "SoulsTidy", "RealmRaid"},
    "oas3": set(),  # 故意留空：复现「无任务账号导致 Core 秒断」的场景
}


class MockCore:
    def __init__(self) -> None:
        self.configs: list[str] = ["oas1", "oas2", "oas3"]
        self.store: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {}
        self.states: dict[str, int] = {name: STATE_INACTIVE for name in self.configs}
        self.sockets: dict[str, list[WebSocket]] = {}
        self.log_tasks: dict[str, asyncio.Task] = {}
        self.stats = {"args_calls": 0, "value_calls": 0, "ws_connects": {}, "fault": False}
        for account, tasks in DEFAULT_ENABLED.items():
            for task in tasks:
                self.set_enable(account, task, True)

    # -------- 配置存取
    def groups_for(self, account: str, task: str) -> dict[str, list[dict[str, Any]]]:
        key = (account, task)
        if key not in self.store:
            self.store[key] = json.loads(json.dumps(base_groups(task)))
        return self.store[key]

    def set_enable(self, account: str, task: str, enabled: bool) -> None:
        scheduler = self.groups_for(account, task).get("scheduler", [])
        for field in scheduler:
            if field["name"] == "enable":
                field["value"] = enabled

    def enabled_tasks(self, account: str) -> list[tuple[str, str]]:
        result = []
        for task in ALL_TASKS:
            key = (account, task)
            groups = self.store.get(key)
            if groups is None:
                continue
            scheduler = {field["name"]: field for field in groups.get("scheduler", [])}
            if scheduler.get("enable", {}).get("value"):
                result.append((task, str(scheduler.get("next_run", {}).get("value", ""))))
        return result

    def schedule_of(self, account: str) -> dict[str, Any]:
        tasks = self.enabled_tasks(account)
        running: dict[str, Any] = {}
        rest = tasks
        if self.states.get(account) == STATE_RUNNING and tasks:
            running = {"name": tasks[0][0], "next_run": tasks[0][1]}
            rest = tasks[1:]
        half = (len(rest) + 1) // 2
        return {
            "running": running,
            "pending": [{"name": name, "next_run": stamp} for name, stamp in rest[:half]],
            "waiting": [{"name": name, "next_run": stamp} for name, stamp in rest[half:]],
        }

    # -------- WebSocket
    async def broadcast(self, account: str, data: dict[str, Any]) -> None:
        for socket in list(self.sockets.get(account, [])):
            try:
                await socket.send_json(data)
            except Exception:
                try:
                    self.sockets[account].remove(socket)
                except ValueError:
                    pass

    async def broadcast_text(self, account: str, text: str) -> None:
        for socket in list(self.sockets.get(account, [])):
            try:
                await socket.send_text(text)
            except Exception:
                try:
                    self.sockets[account].remove(socket)
                except ValueError:
                    pass

    def ensure_log_task(self, account: str) -> None:
        task = self.log_tasks.get(account)
        if task is None or task.done():
            self.log_tasks[account] = asyncio.ensure_future(self.emit_logs(account))

    async def emit_logs(self, account: str) -> None:
        """按真实 OAS 的 loguru 格式产生日志，验证 Bridge 的级别解析。"""
        samples = [
            ("INFO", "tasks.Orochi.orochi:run:112 - 队伍已就绪，开始挑战"),
            ("INFO", "module.device.device:screenshot:88 - 截图耗时 0.31s"),
            ("SUCCESS", "tasks.Orochi.orochi:battle:201 - 战斗胜利，结算中"),
            ("WARNING", "module.device.device:screenshot:88 - 截图耗时 0.82s，高于预期"),
            ("INFO", "script:loop:250 - 下一个任务：KekkaiUtilize"),
            ("ERROR", "tasks.KekkaiUtilize.utilize:harvest:66 - 未找到结界卡，重试第 1 次"),
        ]
        index = 0
        while self.states.get(account) == STATE_RUNNING:
            level, message = samples[index % len(samples)]
            index += 1
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            await self.broadcast_text(account, f"{stamp} | {level:<8} | {message}")
            await asyncio.sleep(0.9)


core = MockCore()
app = FastAPI(title="OAS Mock Core", version="1.0")


# ----------------------------------------------------------------- 与真实 Core 一致的接口

@app.get("/test")
async def core_test():
    if core.stats["fault"]:
        return "fault"
    return "success"


@app.get("/script_menu")
async def script_menu():
    return MENU


@app.get("/config_list")
async def config_list():
    return list(core.configs)


@app.get("/config_new_name")
async def config_new_name():
    numbers = [int(match.group()) for name in core.configs if (match := re.search(r"\d+", name))]
    return f"oas{(max(numbers) + 1) if numbers else 1}"


@app.post("/config_copy")
async def config_copy(file: str, template: str = "template"):
    # 复刻真实行为：同名文件只在日志报错，接口静默返回列表（Bridge 必须自己查重）
    if file not in core.configs:
        core.configs.append(file)
        core.states[file] = STATE_INACTIVE
    return list(core.configs)


@app.put("/config")
async def config_rename(old_name: str = "", new_name: str = ""):
    if old_name == new_name or new_name == "":
        return False
    if old_name not in core.configs or new_name in core.configs:
        raise HTTPException(status_code=400, detail="Rename failed")
    core.configs[core.configs.index(old_name)] = new_name
    core.states[new_name] = core.states.pop(old_name, STATE_INACTIVE)
    for key in [key for key in core.store if key[0] == old_name]:
        core.store[(new_name, key[1])] = core.store.pop(key)
    return True


@app.delete("/config")
async def config_delete(name: str = ""):
    if name == "" or name == "template" or name not in core.configs:
        raise HTTPException(status_code=400, detail="Delete failed")
    core.configs.remove(name)
    core.states.pop(name, None)
    for key in [key for key in core.store if key[0] == name]:
        core.store.pop(key)
    return True


@app.get("/{script_name}/start")
async def script_start(script_name: str):
    if script_name not in core.configs:
        raise HTTPException(status_code=400, detail=f"{script_name}.json not found")
    core.states[script_name] = STATE_RUNNING
    await core.broadcast(script_name, {"state": STATE_RUNNING})
    await core.broadcast(script_name, {"schedule": core.schedule_of(script_name)})
    core.ensure_log_task(script_name)
    return None


@app.get("/{script_name}/stop")
async def script_stop(script_name: str):
    core.states[script_name] = STATE_INACTIVE
    await core.broadcast(script_name, {"state": STATE_INACTIVE})
    return None


@app.get("/{script_name}/{task}/args")
async def script_task_args(script_name: str, task: str):
    core.stats["args_calls"] += 1
    if core.stats["fault"]:
        raise HTTPException(status_code=500, detail="mock core fault")
    if script_name not in core.configs:
        return {}
    if to_snake(task) not in RAW and task not in ALL_TASKS:
        return {}
    return core.groups_for(script_name, task)


@app.put("/{script_name}/{task}/{group}/{argument}/value")
async def script_set_value(script_name: str, task: str, group: str, argument: str, types: str, value: str):
    core.stats["value_calls"] += 1
    if core.stats["fault"]:
        raise HTTPException(status_code=500, detail="mock core fault")
    parsed: Any = value
    try:
        # 与真实 script_router.py 的 match/case 一致（含严格时间格式）
        if types == "integer":
            parsed = int(value)
        elif types == "number":
            parsed = float(value)
        elif types == "boolean":
            parsed = value.lower() in ("true", "1") if isinstance(value, str) else bool(value)
        elif types == "date_time":
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        elif types == "time_delta":
            day = int(value[:2])  # 复刻上游 C1 修复（handoff/16）
            moment = datetime.strptime(value[3:], "%H:%M:%S")
            parsed = timedelta(days=day, hours=moment.hour, minutes=moment.minute, seconds=moment.second)
        elif types == "time":
            parsed = datetime.strptime(value, "%H:%M:%S").time()
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Argument type error: {error}")

    groups = core.groups_for(script_name, task)
    fields = groups.get(group)
    if fields is None:
        return False
    target = next((field for field in fields if field["name"] == argument), None)
    if target is None:
        return False
    # 复刻 pydantic 枚举校验：不在候选里 → 返回 false（HTTP 200）
    options = target.get("enumEnum")
    if options and str(value) not in [str(option) for option in options]:
        return False
    if types == "date_time":
        target["value"] = parsed.strftime("%Y-%m-%d %H:%M:%S")
    elif types == "time":
        target["value"] = parsed.strftime("%H:%M:%S")
    elif types == "time_delta":
        total = int(parsed.total_seconds())
        target["value"] = f"{total // 86400:02d} {total % 86400 // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"
    else:
        target["value"] = parsed
    return True


@app.websocket("/ws/{script_name}")
async def websocket_endpoint(websocket: WebSocket, script_name: str):
    await websocket.accept()
    core.stats["ws_connects"][script_name] = core.stats["ws_connects"].get(script_name, 0) + 1
    if script_name not in core.configs:
        await websocket.close()
        return
    core.sockets.setdefault(script_name, []).append(websocket)
    try:
        await websocket.send_json({"state": core.states.get(script_name, STATE_INACTIVE)})
        if not core.enabled_tasks(script_name):
            # 真实 Core：config.get_next() 抛 RequestHumanTakeover → 连接立即断开
            await websocket.close()
            return
        await websocket.send_json({"schedule": core.schedule_of(script_name)})
        while True:
            command = await websocket.receive_text()
            if command == "get_state":
                await core.broadcast(script_name, {"state": core.states.get(script_name, 0)})
            elif command == "get_schedule":
                await core.broadcast(script_name, {"schedule": core.schedule_of(script_name)})
            elif command == "start":
                core.states[script_name] = STATE_RUNNING
                await core.broadcast(script_name, {"state": STATE_RUNNING})
                await core.broadcast(script_name, {"schedule": core.schedule_of(script_name)})
                core.ensure_log_task(script_name)
            elif command == "stop":
                core.states[script_name] = STATE_INACTIVE
                await core.broadcast(script_name, {"state": STATE_INACTIVE})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            core.sockets.get(script_name, []).remove(websocket)
        except ValueError:
            pass


# ----------------------------------------------------------------- 调试辅助（真实 Core 没有）

@app.get("/__mock__/stats")
async def mock_stats():
    return {
        "config_source": str(CONFIG_PATH) if CONFIG_PATH else None,
        "tasks": len(ALL_TASKS),
        **core.stats,
        "states": dict(core.states),
    }


@app.post("/__mock__/fault")
async def mock_fault(on: bool = True):
    core.stats["fault"] = on
    return {"fault": on}
