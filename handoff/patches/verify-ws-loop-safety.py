# This Python file uses the following encoding: utf-8
"""验证 handoff/16 C2 修复：跨事件循环的 WebSocket 广播被正确定向回主循环。

在项目根目录运行（这样能 import module.server.*）：
    cd D:\\OSAyys
    .\\.venv\\Scripts\\python.exe handoff\\patches\\verify-ws-loop-safety.py

它构造两个事件循环（主循环 accept 连接、工作线程的独立循环发起广播），
用假连接记录 send 实际在哪个循环执行，断言跨循环发送被 run_coroutine_threadsafe
定向回主循环，并验证「同循环」「未记录主循环」两种回退路径不受影响。
不启动游戏、不连接真实设备、不写任何文件。
"""
import asyncio
import sys
import threading

from starlette.websockets import WebSocketState

from module.server.setting import State
from module.server.script_websocket import ScriptWSManager

results = []


def check(name, cond, extra=""):
    results.append((cond, name, extra))


class FakeWS:
    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.sent = []
        self.exec_loops = []

    async def send_json(self, data):
        self.exec_loops.append(asyncio.get_running_loop())
        self.sent.append(data)

    async def send_text(self, text):
        self.exec_loops.append(asyncio.get_running_loop())
        self.sent.append(text)

    async def close(self):
        pass


async def main():
    main_loop = asyncio.get_running_loop()
    State.main_loop = main_loop

    mgr = ScriptWSManager()
    ws = FakeWS()
    mgr.active_connections.append(ws)

    done = threading.Event()
    err = []

    def worker():
        wl = asyncio.new_event_loop()
        asyncio.set_event_loop(wl)
        try:
            wl.run_until_complete(mgr.broadcast_state({"state": 1, "schedule": {"running": {}}}))
        except Exception as exc:  # noqa: BLE001
            err.append(repr(exc))
        finally:
            wl.close()
            done.set()

    thread = threading.Thread(target=worker)
    thread.start()
    while not done.is_set():
        await asyncio.sleep(0.02)   # 主循环保持转动，定向过来的发送才能执行
    thread.join()

    check("跨循环广播无异常", not err, str(err))
    check("消息确实发出去了", len(ws.sent) == 1, str(ws.sent))
    check("数据内容正确", bool(ws.sent) and ws.sent[0].get("state") == 1, str(ws.sent))
    check("发送在主循环执行(定向成功)",
          bool(ws.exec_loops) and all(loop is main_loop for loop in ws.exec_loops),
          f"exec={ws.exec_loops} main={main_loop}")

    ws2 = FakeWS(); mgr2 = ScriptWSManager(); mgr2.active_connections.append(ws2)
    await mgr2.broadcast_state({"state": 0})
    check("同循环 fallback 正常",
          ws2.sent == [{"state": 0}] and ws2.exec_loops[0] is main_loop, str(ws2.sent))

    State.main_loop = None
    ws3 = FakeWS(); mgr3 = ScriptWSManager(); mgr3.active_connections.append(ws3)
    await mgr3.broadcast_state({"state": 3})
    check("未设主循环时 fallback 正常", ws3.sent == [{"state": 3}], str(ws3.sent))


asyncio.run(main())

for ok, name, extra in results:
    print(f"  {'OK' if ok else 'XX'} {name}" + (f"\n     {extra}" if not ok else ""))
print(f"\n{sum(1 for ok, _, _ in results if ok)}/{len(results)} 通过")
sys.exit(0 if all(ok for ok, _, _ in results) else 1)
