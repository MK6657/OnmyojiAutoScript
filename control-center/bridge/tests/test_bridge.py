"""Bridge 逻辑回归。

不依赖真实 OAS Core：用一个会统计请求次数的假 Core 直接调用路由函数，
重点验证「账号列表不再对 Core 发起成百上千次请求」这类不看数字就发现不了的问题。

运行：python3 tests/test_bridge.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "stubs"))
sys.path.insert(0, str(HERE.parent))

TEMP = tempfile.mkdtemp(prefix="oas-bridge-test-")
os.environ["OAS_CONTROL_CENTER_DATA_DIR"] = TEMP

from app import main as bridge_main  # noqa: E402
from app.core_client import CoreError, OasCoreClient  # noqa: E402
from app.models import AccountAction, AccountCreate, AccountPatch, ConfigPatch  # noqa: E402
from app.runtime import parse_log_level, parse_log_timestamp  # noqa: E402


MENU = {
    "Script": ["Script", "Restart", "GlobalGame"],
    "Soul Zones": ["Orochi", "Sougenbi", "FallenSun", "EternitySea", "SixRealms"],
    "Daily Task": ["DailyTrifles", "Pets", "SoulsTidy", "WantedQuests"],
    "Guild": ["KekkaiUtilize", "RealmRaid"],
    "Weekly Task": ["Duel"],
    "Activity Task": ["Quiz"],
}
ALL_TASKS = [task for tasks in MENU.values() for task in tasks]


class FakeCore:
    """记录调用次数的假 Core。接口与 OasCoreClient 保持一致。"""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.accounts_list = ["oas1", "oas2", "oas3"]
        self.enabled = {
            "oas1": {"Script", "KekkaiUtilize", "Orochi"},
            "oas2": {"Script", "Pets"},
            "oas3": set(),
        }
        self.values: list[tuple] = []
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.fail_next_set = False

    def _hit(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    async def health(self) -> bool:
        self._hit("health")
        return True

    async def accounts(self) -> list[str]:
        self._hit("accounts")
        return list(self.accounts_list)

    async def menu(self):
        self._hit("menu")
        return MENU

    async def task_args(self, account_id: str, task_id: str):
        self._hit("task_args")
        enabled = task_id in self.enabled.get(account_id, set())
        return {
            "scheduler": [
                {"name": "enable", "title": "Enable", "default": False, "value": enabled, "type": "boolean"},
                {"name": "next_run", "title": "Next Run", "default": "2023-01-01 00:00:00",
                 "value": "2026-07-26 09:00:00", "type": "date_time"},
                {"name": "success_interval", "title": "Success Interval", "default": "00 06:00:00",
                 "value": "00 06:00:00", "type": "time_delta"},
            ],
            "device": [
                {"name": "handle", "title": "Handle", "default": "", "value": "", "type": "string"},
            ],
        }

    async def set_value(self, account_id, task_id, group, name, value, value_type):
        self._hit("set_value")
        if self.fail_next_set:
            self.fail_next_set = False
            raise CoreError("OAS Core 返回 400: Argument type error")
        self.values.append((account_id, task_id, group, name, OasCoreClient.normalize_value(value, value_type), value_type))
        if group == "scheduler" and name == "enable":
            bucket = self.enabled.setdefault(account_id, set())
            bucket.add(task_id) if value else bucket.discard(task_id)
        return True

    async def copy_account(self, account_id, template="template"):
        self._hit("copy_account")
        if account_id not in self.accounts_list:
            self.accounts_list.append(account_id)
            self.enabled[account_id] = set()
        return True

    async def next_account_name(self):
        return f"oas{len(self.accounts_list) + 1}"

    async def delete_account(self, account_id):
        self._hit("delete_account")
        self.accounts_list = [item for item in self.accounts_list if item != account_id]
        return True

    async def rename_account(self, old_name, new_name):
        self._hit("rename_account")
        self.accounts_list = [new_name if item == old_name else item for item in self.accounts_list]
        self.enabled[new_name] = self.enabled.pop(old_name, set())
        return True

    async def start_script(self, account_id):
        self._hit("start_script")
        self.started.append(account_id)

    async def stop_script(self, account_id):
        self._hit("stop_script")
        self.stopped.append(account_id)

    def websocket_url(self, account_id):
        return f"ws://fake/ws/{account_id}"

    async def close(self):
        return None


results: list[tuple[str, str, str]] = []


def check(name: str):
    def wrap(fn):
        async def run():
            try:
                await fn()
                results.append(("PASS", name, ""))
            except Exception as error:  # noqa: BLE001 - 汇总输出
                results.append(("FAIL", name, f"{type(error).__name__}: {error}"))
        run.__name__ = fn.__name__
        return run
    return wrap


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def reset() -> FakeCore:
    core = FakeCore()
    bridge_main.bridge.core = core
    bridge_main.bridge.runtimes.core = core
    bridge_main.bridge._catalog = None
    bridge_main.bridge.task_cache.invalidate()
    return core


@check("账号列表首次加载的 Core 请求数在合理范围内")
async def test_first_load_cost():
    core = reset()
    accounts = await bridge_main.list_accounts()
    expect(len(accounts) == 3, f"账号数不对：{len(accounts)}")
    hits = core.calls.get("task_args", 0)
    # 首次没有缓存，只能全量扫描：3 个账号 × 16 个任务 = 48
    expect(hits == 3 * len(ALL_TASKS), f"首次扫描次数异常：{hits}")


@check("再次加载账号列表不再请求 Core（缓存生效）")
async def test_second_load_is_cached():
    core = reset()
    await bridge_main.list_accounts()
    before = core.calls.get("task_args", 0)
    await bridge_main.list_accounts()
    await bridge_main.list_accounts()
    after = core.calls.get("task_args", 0)
    expect(after == before, f"缓存没生效，多打了 {after - before} 次 task_args")


@check("有调度快照时账号列表完全不查 task_args")
async def test_schedule_snapshot_beats_scan():
    core = reset()
    for account_id in ("oas1", "oas2", "oas3"):
        runtime = bridge_main.bridge.runtimes.get(account_id)
        runtime.last_schedule = {
            "running": {"name": "Script", "next_run": "2026-07-26 09:00:00"},
            "pending": [{"name": "Orochi", "next_run": "2026-07-26 10:00:00"}],
            "waiting": [],
        }
    accounts = await bridge_main.list_accounts()
    expect(core.calls.get("task_args", 0) == 0, f"仍然调用了 task_args {core.calls.get('task_args')} 次")
    expect(all(item.selected_count == 2 for item in accounts), "没有从调度快照推导出已启用任务")
    await bridge_main.bridge.runtimes.close()


@check("启用任务后缓存立刻失效，列表能看到新状态")
async def test_toggle_invalidates_cache():
    core = reset()
    before = await bridge_main.account_tasks("oas1")
    expect(len(before) == 3, f"初始启用任务数不对：{len(before)}")
    await bridge_main.set_task_enabled("oas1", "Duel", True)
    after = await bridge_main.account_tasks("oas1")
    expect(len(after) == 4, f"启用后应为 4 项，实际 {len(after)}")
    expect(any(task.id == "Duel" for task in after), "新启用的任务没有出现在列表里")


@check("保存配置只对改动字段调用 Core，且不重复拉 schema")
async def test_patch_only_touches_given_fields():
    core = reset()
    payload = ConfigPatch(fields=[
        {"group": "scheduler", "name": "priority", "value": 3, "type": "integer"},
        {"group": "device", "name": "handle", "value": "132456"},   # 故意不给 type
        {"group": "device", "name": "handle", "value": "132456"},   # 再来一个缺 type 的
    ])
    result = await bridge_main.patch_task_config("oas1", "Orochi", payload)
    expect(result["updated"] == 3, f"更新字段数不对：{result}")
    expect(core.calls.get("set_value") == 3, f"set_value 次数不对：{core.calls.get('set_value')}")
    expect(core.calls.get("task_args", 0) == 1, f"schema 应只读一次，实际 {core.calls.get('task_args')} 次")


@check("set_value 护栏：Core 返回 false 抛错、time_delta 超 9 天拒绝")
async def test_set_value_guards():
    class Probe(OasCoreClient):
        def __init__(self, reply):
            self.reply = reply
        async def _request(self, *args, **kwargs):
            return self.reply

    ok = Probe(True)
    await ok.set_value("a", "T", "scheduler", "success_interval", "09 00:00:00", "time_delta")  # 9 天
    await ok.set_value("a", "T", "scheduler", "success_interval", "30 00:00:00", "time_delta")  # 30 天（Core C1 修复后可用）
    try:
        await ok.set_value("a", "T", "scheduler", "success_interval", "100 00:00:00", "time_delta")
        raise AssertionError("100 天应当被拒绝")
    except CoreError as error:
        expect("99 天" in str(error), f"错误文案不对: {error}")

    refuse = Probe(False)
    try:
        await refuse.set_value("a", "T", "scheduler", "enable", True, "boolean")
        raise AssertionError("Core 返回 false 应当抛错")
    except CoreError as error:
        expect("拒绝" in str(error), f"错误文案不对: {error}")


@check("时间类型会被补成 Core 能解析的格式")
async def test_value_normalization():
    normalize = OasCoreClient.normalize_value
    expect(normalize("2026-07-26T09:30", "date_time") == "2026-07-26 09:30:00", "date_time 补秒失败")
    expect(normalize("2026-07-26 09:30:15", "date_time") == "2026-07-26 09:30:15", "date_time 被改坏了")
    expect(normalize("9:5", "time") == "09:05:00", "time 补零失败")
    expect(normalize("09:05:07", "time") == "09:05:07", "time 被改坏了")
    expect(normalize("0 6:0:0", "time_delta") == "00 06:00:00", "time_delta 规范化失败")
    expect(normalize("06:00:00", "time_delta") == "00 06:00:00", "缺天数的 time_delta 规范化失败")
    expect(normalize(True, "boolean") == "true", "boolean 转换失败")
    expect(normalize(False, "boolean") == "false", "boolean 转换失败")
    expect(normalize(3, "integer") == "3", "integer 转换失败")


@check("保存失败时向前端返回 502 而不是 500")
async def test_save_error_maps_to_502():
    core = reset()
    core.fail_next_set = True
    try:
        await bridge_main.patch_task_config("oas1", "Orochi", ConfigPatch(fields=[
            {"group": "device", "name": "handle", "value": "999", "type": "string"},
        ]))
        raise AssertionError("应当抛出 HTTPException")
    except Exception as error:
        expect(getattr(error, "status_code", None) == 502, f"状态码不对：{getattr(error, 'status_code', error)}")


@check("创建重名账号会被拒绝而不是静默复用别人的配置")
async def test_duplicate_account_rejected():
    reset()
    try:
        await bridge_main.create_account(AccountCreate(name="oas1"))
        raise AssertionError("应当抛出 HTTPException")
    except Exception as error:
        expect(getattr(error, "status_code", None) == 409, f"状态码不对：{getattr(error, 'status_code', error)}")


@check("新建账号会真正落到 Core 并出现在列表里")
async def test_create_account():
    core = reset()
    created = await bridge_main.create_account(AccountCreate(name="oas-new"))
    expect(created.id == "oas-new", f"返回的账号 id 不对：{created.id}")
    expect("oas-new" in core.accounts_list, "Core 里没有这个账号")
    accounts = await bridge_main.list_accounts()
    expect(any(item.id == "oas-new" for item in accounts), "账号列表里看不到新账号")


@check("重命名账号不会在数据库里留下孤儿记录")
async def test_rename_cleans_metadata():
    reset()
    await bridge_main.list_accounts()
    bridge_main.bridge.repository.save_task_order("oas2", ["Script", "Pets"])
    await bridge_main.patch_account("oas2", AccountPatch(name="oas2-renamed"))
    expect(bridge_main.bridge.repository.get("oas2") is None, "旧账号元数据没有清理")
    expect(bridge_main.bridge.repository.get("oas2-renamed") is not None, "新账号元数据缺失")
    expect(bridge_main.bridge.repository.task_order("oas2-renamed") == ["Script", "Pets"], "显示顺序没有跟着迁移")


@check("WebSocket 不可用时启动命令退回 Core 的 REST 入口")
async def test_action_falls_back_to_rest():
    core = reset()
    result = await bridge_main.account_action("oas1", AccountAction(action="start"))
    expect(result["accepted"] is True, "命令没有被接受")
    expect(core.started == ["oas1"], f"没有走 REST 兜底：{core.started}")
    await bridge_main.account_action("oas1", AccountAction(action="stop"))
    expect(core.stopped == ["oas1"], f"停止没有走 REST 兜底：{core.stopped}")
    await bridge_main.bridge.runtimes.close()


@check("日志级别能从 Core 的文本日志里解析出来")
async def test_log_level_parsing():
    expect(parse_log_level("2026-07-26 11:44:12.123 | INFO     | tasks.orochi:run:12 - 开始") == "info", "INFO 解析失败")
    expect(parse_log_level("2026-07-26 11:44:12.123 | WARNING  | module:x:1 - 慢") == "warn", "WARNING 解析失败")
    expect(parse_log_level("2026-07-26 11:44:12.123 | ERROR    | module:x:1 - 崩了") == "error", "ERROR 解析失败")
    expect(parse_log_level("2026-07-26 11:44:12.123 | CRITICAL | module:x:1 - 崩了") == "error", "CRITICAL 解析失败")
    expect(parse_log_level("Traceback (most recent call last):") == "error", "traceback 应算错误")
    expect(parse_log_level("普通输出") == "info", "普通输出应算信息")
    expect(parse_log_timestamp("2026-07-26 11:44:12.123 | INFO | x") is not None, "时间戳解析失败")
    expect(parse_log_timestamp("没有时间戳") is None, "不该凭空造时间戳")


@check("多模拟器窗口只采用经过在线 ADB 列表验证的 serial")
async def test_window_serial_mapping():
    connected = {"127.0.0.1:16384", "127.0.0.1:16416", "emulator-5554", "emulator-5556"}
    expect(
        bridge_main.infer_window_serial(
            "MuMuNxDevice.exe", "MuMuNxDevice.exe", connected
        ) == "127.0.0.1:16384",
        "MuMu 实例 0 映射错误",
    )
    expect(
        bridge_main.infer_window_serial(
            "MuMuNxDevice.exe", "MuMuNxDevice.exe -v 1", connected
        ) == "127.0.0.1:16416",
        "MuMu 实例 1 映射错误",
    )
    expect(
        bridge_main.infer_window_serial(
            "MuMuNxDevice.exe", "MuMuNxDevice.exe -v 2", connected
        ) is None,
        "离线实例不应被猜成其他设备",
    )
    expect(
        bridge_main.infer_window_serial("dnplayer.exe", "", connected) is None,
        "多设备时未知映射必须拒绝",
    )


@check("模板与任务顺序能在 Bridge 侧持久化")
async def test_ui_metadata_roundtrip():
    reset()
    saved = await bridge_main.save_template(bridge_main.TemplatePayload(
        id="tpl-1", name="御魂标准", task_id="Orochi", task_title="御魂",
        created_at="2026-07-26T00:00:00Z", groups={"scheduler": {"priority": {"value": 3, "type": "integer"}}},
    ))
    expect(saved["id"] == "tpl-1", "模板保存返回值不对")
    listed = await bridge_main.list_templates()
    expect(len(listed) == 1 and listed[0]["groups"]["scheduler"]["priority"]["value"] == 3, f"模板读取不对：{listed}")
    await bridge_main.delete_template("tpl-1")
    expect(await bridge_main.list_templates() == [], "模板没有删掉")

    await bridge_main.put_task_order("oas1", bridge_main.TaskOrderPatch(order=["Orochi", "Script"]))
    expect(await bridge_main.get_task_order("oas1") == ["Orochi", "Script"], "任务顺序没存住")


@check("任务分类全部有中文名")
async def test_categories_localized():
    reset()
    catalog = await bridge_main.task_catalog()
    english = [task.category for task in catalog if any(ch.isascii() and ch.isalpha() for ch in task.category)]
    expect(not english, f"仍有未翻译的分类：{sorted(set(english))}")
    untranslated = [task.id for task in catalog if task.title == task.id]
    expect(not untranslated, f"仍有未翻译的任务：{untranslated}")


@check("CORS 放行任意本机端口")
async def test_cors_regex():
    import re
    kwargs = next(kw for cls, kw in bridge_main.app.middleware if "allow_origin_regex" in kw)
    pattern = re.compile(kwargs["allow_origin_regex"])
    for origin in ("http://127.0.0.1:5173", "http://127.0.0.1:4174", "http://localhost:4180", "http://127.0.0.1"):
        expect(pattern.match(origin) is not None, f"应放行 {origin}")
    for origin in ("http://evil.example.com", "http://127.0.0.1.evil.com"):
        expect(pattern.match(origin) is None, f"不应放行 {origin}")


@check("删除账号会同时清掉运行时和缓存")
async def test_delete_account():
    core = reset()
    await bridge_main.list_accounts()
    bridge_main.bridge.runtimes.get("oas3")
    await bridge_main.delete_account("oas3")
    expect("oas3" not in core.accounts_list, "Core 里没删掉")
    expect(bridge_main.bridge.runtimes.peek("oas3") is None, "运行时没释放")
    expect(bridge_main.bridge.task_cache.peek("oas3") is None, "缓存没清")


async def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        await test()
    for status, name, message in results:
        print(f"{'  ✓' if status == 'PASS' else '  ✗'} {name}{chr(10) + '      ' + message if message else ''}")
    failed = [item for item in results if item[0] == "FAIL"]
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
