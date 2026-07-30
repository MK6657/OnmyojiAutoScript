"""真实三层集成回归：真实 Bridge ←→ mock Core（接口对齐真实 OAS Core）。

与 test_bridge.py 的区别：这里跑的是【真正启动的 Bridge 进程】，请求走真 HTTP，
Bridge 再通过真 HTTP/WebSocket 访问 mock Core——覆盖单元测试摸不到的路径：
缓存与调度快照、WebSocket 运行时、值规范化落到 Core 解析器、错误码翻译。

运行前先启动两层（用户机器示例）：
    cd D:\\OSAyys\\control-center\\bridge
    .venv\\Scripts\\python.exe -m uvicorn tests.mock_core:app --port 22268
    # 另一窗口（注意 OAS_CORE_URL 指向 mock）
    set OAS_CORE_URL=http://127.0.0.1:22268
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 22367
然后：
    .venv\\Scripts\\python.exe tests\\test_integration.py

也可以把 Bridge 指向【真实 Core】跑同一套用例（只读用例会通过，
涉及创建/改值的用例会真实写入，请只在测试配置上执行）。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

BRIDGE = "http://127.0.0.1:22367/api/v1"
MOCK = "http://127.0.0.1:22268"

results: list[tuple[str, str, str]] = []


def call(method: str, url: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except Exception:
            return error.code, raw.decode("utf-8", "replace")


def check(name: str):
    def wrap(fn):
        def run():
            try:
                fn()
                results.append(("PASS", name, ""))
            except Exception as error:  # noqa: BLE001
                results.append(("FAIL", name, f"{type(error).__name__}: {error}"))
        return run
    return wrap


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def stats() -> dict:
    return call("GET", f"{MOCK}/__mock__/stats")[1]


def field_value(account: str, task: str, group: str, name: str):
    _, config = call("GET", f"{BRIDGE}/accounts/{account}/tasks/{task}/config")
    return next(f["value"] for f in config["groups"][group] if f["name"] == name)


@check("health：Bridge 版本 >= 1.1.2 且 Core 在线")
def t_health():
    status, body = call("GET", f"{BRIDGE}/health")
    expect(status == 200 and body["core"] == "ok", f"{status} {body}")
    expect(tuple(int(x) for x in body["version"].split(".")) >= (1, 1, 2), f"版本 {body['version']}")


@check("账号列表：3 个账号，已启用任务来自扫描")
def t_accounts():
    status, body = call("GET", f"{BRIDGE}/accounts")
    expect(status == 200 and len(body) == 3, f"{status} {len(body) if isinstance(body, list) else body}")
    oas1 = next(a for a in body if a["id"] == "oas1")
    expect(sorted(oas1["selected_tasks"]) == ["KekkaiUtilize", "Orochi", "WantedQuests"], str(oas1["selected_tasks"]))


@check("缓存：第二次账号列表 0 次 Core 扫描")
def t_cache():
    before = stats()["args_calls"]
    call("GET", f"{BRIDGE}/accounts")
    call("GET", f"{BRIDGE}/accounts")
    after = stats()["args_calls"]
    expect(after == before, f"多扫了 {after - before} 次")


@check("调度快照：runtime 连上 Core 后 /schedule 返回 pending/waiting")
def t_schedule():
    status, body = call("GET", f"{BRIDGE}/accounts/oas1/schedule")
    expect(status == 200, f"{status} {body}")
    expect(body["connected"] is True, f"runtime 未连接: {body}")
    total = len(body["pending"]) + len(body["waiting"]) + (1 if body["running"] else 0)
    expect(total == 3, f"快照任务数 {total}: {body}")


@check("快照优先：有快照后账号列表不再扫描（TTL 内外都不扫）")
def t_snapshot_beats_scan():
    before = stats()["args_calls"]
    call("GET", f"{BRIDGE}/accounts")
    expect(stats()["args_calls"] == before, "有快照仍触发了扫描")


@check("date_time 规范化：16 位输入被补秒后 Core 严格解析通过")
def t_datetime_normalize():
    status, body = call("PATCH", f"{BRIDGE}/accounts/oas1/tasks/Orochi/config", {
        "fields": [{"group": "scheduler", "name": "next_run", "value": "2026-07-27T09:30", "type": "date_time"}],
    })
    expect(status == 200 and body["saved"], f"{status} {body}")
    stored = field_value("oas1", "Orochi", "scheduler", "next_run")
    expect(stored == "2026-07-27 09:30:00", f"存储值 {stored!r}")


@check("time_delta 规范化：'0 6:0:0' 落库为 '00 06:00:00'")
def t_delta_normalize():
    status, body = call("PATCH", f"{BRIDGE}/accounts/oas1/tasks/Orochi/config", {
        "fields": [{"group": "scheduler", "name": "success_interval", "value": "0 6:0:0", "type": "time_delta"}],
    })
    expect(status == 200, f"{status} {body}")
    stored = field_value("oas1", "Orochi", "scheduler", "success_interval")
    expect(stored == "00 06:00:00", f"存储值 {stored!r}")


@check("time_delta 两位天数：30 天能正确存（Core C1 修复），100 天被拒绝")
def t_delta_range():
    status, body = call("PATCH", f"{BRIDGE}/accounts/oas1/tasks/Orochi/config", {
        "fields": [{"group": "scheduler", "name": "success_interval", "value": "30 00:00:00", "type": "time_delta"}],
    })
    expect(status == 200, f"30 天应当成功: {status} {body}")
    stored = field_value("oas1", "Orochi", "scheduler", "success_interval")
    expect(str(stored).startswith("30"), f"30 天没存对(可能 Core 未打 C1 补丁): {stored!r}")
    status, body = call("PATCH", f"{BRIDGE}/accounts/oas1/tasks/Orochi/config", {
        "fields": [{"group": "scheduler", "name": "success_interval", "value": "100 00:00:00", "type": "time_delta"}],
    })
    expect(status == 502 and "99 天" in str(body), f"100 天应被拒: {status} {body}")


@check("非法枚举值：Core 返回 false → Bridge 502 拒绝（不再假成功）")
def t_enum_rejected():
    status, body = call("PATCH", f"{BRIDGE}/accounts/oas1/tasks/Script/config", {
        "fields": [{"group": "device", "name": "screenshot_method", "value": "bogus_method", "type": "enum"}],
    })
    expect(status == 502, f"应 502，实际 {status} {body}")
    expect("拒绝" in str(body), f"错误文案不对: {body}")
    stored = field_value("oas1", "Script", "device", "screenshot_method")
    expect(stored == "auto", f"非法值居然写进去了: {stored!r}")


@check("格式非法的 date_time：Core 400 → Bridge 502 且带原因")
def t_bad_datetime():
    status, body = call("PATCH", f"{BRIDGE}/accounts/oas1/tasks/Orochi/config", {
        "fields": [{"group": "scheduler", "name": "next_run", "value": "not-a-date", "type": "date_time"}],
    })
    expect(status == 502 and "Argument type error" in str(body), f"{status} {body}")


@check("启用/停用任务：缓存立刻失效，计数同步")
def t_toggle():
    status, body = call("PUT", f"{BRIDGE}/accounts/oas1/tasks/Duel/enabled?enabled=true")
    expect(status == 200 and body["enabled"] is True, f"{status} {body}")
    _, tasks = call("GET", f"{BRIDGE}/accounts/oas1/tasks")
    expect(len(tasks) == 4 and any(t["id"] == "Duel" for t in tasks), str([t["id"] for t in tasks]))
    call("PUT", f"{BRIDGE}/accounts/oas1/tasks/Duel/enabled?enabled=false")
    _, tasks = call("GET", f"{BRIDGE}/accounts/oas1/tasks")
    expect(len(tasks) == 3, str([t["id"] for t in tasks]))


@check("账号生命周期：创建→出现在 Core→重命名迁移→删除")
def t_account_lifecycle():
    status, created = call("POST", f"{BRIDGE}/accounts", {"name": "oas-int"})
    expect(status == 200 and created["id"] == "oas-int", f"{status} {created}")
    _, core_list = call("GET", f"{MOCK}/config_list")
    expect("oas-int" in core_list, f"Core 列表没有新账号: {core_list}")

    status, dup = call("POST", f"{BRIDGE}/accounts", {"name": "oas1"})
    expect(status == 409, f"重名应 409，实际 {status} {dup}")

    status, renamed = call("PATCH", f"{BRIDGE}/accounts/oas-int", {"name": "oas-int2"})
    expect(status == 200 and renamed["id"] == "oas-int2", f"{status} {renamed}")
    _, core_list = call("GET", f"{MOCK}/config_list")
    expect("oas-int2" in core_list and "oas-int" not in core_list, f"Core 重命名不一致: {core_list}")

    status, _ = call("DELETE", f"{BRIDGE}/accounts/oas-int2")
    expect(status == 200, f"删除失败 {status}")
    _, core_list = call("GET", f"{MOCK}/config_list")
    expect("oas-int2" not in core_list, f"Core 里没删掉: {core_list}")


@check("模板与任务顺序：经 Bridge SQLite 持久化")
def t_templates():
    status, saved = call("POST", f"{BRIDGE}/templates", {
        "id": "tpl-int", "name": "御魂标准", "task_id": "Orochi", "task_title": "御魂",
        "created_at": "2026-07-26T00:00:00Z",
        "groups": {"scheduler": {"priority": {"value": 3, "type": "integer"}}},
    })
    expect(status == 200 and saved["id"] == "tpl-int", f"{status} {saved}")
    _, listed = call("GET", f"{BRIDGE}/templates")
    expect(any(t["id"] == "tpl-int" for t in listed), str(listed))
    call("DELETE", f"{BRIDGE}/templates/tpl-int")
    _, listed = call("GET", f"{BRIDGE}/templates")
    expect(not any(t["id"] == "tpl-int" for t in listed), "模板没删掉")

    call("PUT", f"{BRIDGE}/accounts/oas1/task-order", {"order": ["Orochi", "KekkaiUtilize"]})
    _, order = call("GET", f"{BRIDGE}/accounts/oas1/task-order")
    expect(order == ["Orochi", "KekkaiUtilize"], str(order))


@check("启动/停止：命令送达 Core，状态与日志回流（含级别解析）")
def t_start_stop_logs():
    status, body = call("POST", f"{BRIDGE}/accounts/oas1/actions", {"action": "start"})
    expect(status == 200 and body["accepted"], f"{status} {body}")
    deadline = time.time() + 8
    levels: set[str] = set()
    state = ""
    while time.time() < deadline:
        _, logs = call("GET", f"{BRIDGE}/accounts/oas1/logs?limit=50")
        levels = {log["level"] for log in logs}
        _, snap = call("GET", f"{BRIDGE}/accounts/oas1/schedule")
        state = snap["state"]
        if {"info", "warn", "error"} <= levels and state == "running":
            break
        time.sleep(0.6)
    expect(state == "running", f"状态 {state}")
    expect({"info", "warn", "error"} <= levels, f"日志级别解析不全: {levels}")
    status, _ = call("POST", f"{BRIDGE}/accounts/oas1/actions", {"action": "stop"})
    expect(status == 200, "停止失败")
    time.sleep(0.8)
    _, snap = call("GET", f"{BRIDGE}/accounts/oas1/schedule")
    expect(snap["state"] == "offline", f"停止后状态 {snap['state']}")


@check("Core 故障：health 显示 offline，保存返回 5xx 可读错误")
def t_core_fault():
    call("POST", f"{MOCK}/__mock__/fault?on=true")
    try:
        _, health = call("GET", f"{BRIDGE}/health")
        expect(health["core"] == "offline", f"health 未反映故障: {health}")
        status, body = call("PATCH", f"{BRIDGE}/accounts/oas1/tasks/Orochi/config", {
            "fields": [{"group": "scheduler", "name": "priority", "value": 4, "type": "integer"}],
        })
        expect(status in (502, 503), f"应 5xx，实际 {status} {body}")
    finally:
        call("POST", f"{MOCK}/__mock__/fault?on=false")
    _, health = call("GET", f"{BRIDGE}/health")
    expect(health["core"] == "ok", "故障解除后未恢复")


@check("空任务账号：不再重连风暴（15 秒 ≤ 4 次）")
def t_no_storm():
    before = stats()["ws_connects"].get("oas3", 0)
    call("GET", f"{BRIDGE}/accounts/oas3/logs?limit=5")
    time.sleep(15)
    after = stats()["ws_connects"].get("oas3", 0)
    expect(after - before <= 4, f"15 秒内重连 {after - before} 次")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_") and callable(v)]
    for test in tests:
        test()
    for status, name, message in results:
        print(f"{'  ✓' if status == 'PASS' else '  ✗'} {name}{chr(10) + '      ' + message if message else ''}")
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
