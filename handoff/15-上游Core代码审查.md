# 15 上游 Core 代码审查（module/server 与相关模块）

日期：2026-07-26
审查对象：上游 OnmyojiAutoScript 的服务端层——`module/server/`（app、script_router、script_process、script_websocket、main_manager、config_manager、setting、updater、tool_router、tool、home_router）、`module/config/`（config、config_model、config_menu、config_state、config_watcher、config_modify、utils、scheduler）、`server.py`、`gui.py`、`script.py`（调度相关段落）、`config/deploy.yaml`。
未审查：`tasks/` 下各任务的游戏逻辑、图像识别、设备控制层（与控制中心无接口关系）。

结论先行：**发现 3 处直接影响使用的功能 bug（A 级，已按最小补丁修复并双备份）、
2 处安全问题（B 级，提供补丁但默认不动）、若干正确性/性能隐患（C 级，文档化 + Bridge 侧规避）。**

---

## A 级：影响使用的功能 bug（已修，共 5 行，每行只加 `await`）

三处是同一类错误：`async def` 方法被当普通函数调用，协程创建后被直接丢弃，
**函数体一行都不会执行**，Python 只在日志里发一条 `coroutine ... was never awaited` 警告。
沙箱里已用最小实验证实该行为（`p.start()` 不带 await → `p.started` 仍为 False）。

### A1 REST 启动/停止接口是静默空操作 — `module/server/script_router.py` 105-118 行

```python
@script_app.get('/{script_name}/start')
async def script_start(script_name: str):
    ...
    mm.script_process[script_name].start()   # start() 是 async，没有 await
```

`GET /{name}/start`、`GET /{name}/stop` 返回 200，但什么都没发生。
**对控制中心的直接影响**：Bridge 在 WebSocket 断开时的 REST 兜底（13 号 B10）
一直在拿假成功——集成测试没抓到是因为 mock Core 把 REST 实现「修好了」，
这次审查修正了这个契约偏差。上游原生前端只走 WebSocket 命令，所以上游用户
没有感知；任何走 REST 的第三方工具都会中招。

### A2 重命名/删除运行中的配置不会停掉旧进程 — 同文件 57-59、75-78 行

`config_rename` / `config_delete` 里 `mm.script_process[old].stop()` 未 await，
然后紧接着 `del mm.script_process[old]`——**正在跑的脚本进程被从管理表里移除但没有被终止**，
变成脱管进程继续控制模拟器，直到整个服务退出（daemon 进程随主进程死）。
用户视角：删除了账号，游戏窗口却还在被操作。

### A3 对运行中的脚本再次 start 会产生双进程 — `module/server/script_process.py` 40-42 行

```python
if self._process and self._process.is_alive():
    logger.warning(...)
    self.stop()        # 未 await → 旧进程没停
self._process = multiprocessing.Process(...)   # 又起了一个新的
```

WebSocket 的 `start` 命令是 await 过的（会执行到这里），所以任何前端对运行中的
账号再点一次启动，就会出现**两个脚本进程同时控制同一个游戏窗口**——点击冲突、
状态错乱，且旧进程句柄被覆盖后再也无法从界面停止。

### 修复与留档

- 修改文件：`module/server/script_router.py`（4 处）、`module/server/script_process.py`（1 处）；
  每处补 `await` 并加行尾注释标注出处（`handoff/15 A1/A2/A3`）。
- 双备份：改动前原件在 `handoff/patches/core-backup-20260726/`；
  统一 diff 在 `handoff/patches/applied-01-missing-awaits.diff`。
- 回退：把备份的两个文件拷回 `module/server/` 即可；回退后 Bridge 依然可用
  （启动/停止走 WebSocket 主路径），只是 REST 兜底重新变成空操作、A2/A3 复现。
- 上游同步：`git pull` 若冲突，冲突点就是这 5 行；建议把这个 diff 提给上游
  （runhey/OnmyojiAutoScript）作 PR，合入后本地补丁自然消失。
- 验证：沙箱做了语法编译检查与协程行为实验；**进程级验证需要在你的 Windows 上做**——
  跑 `start-dev-stack` 之外，用真实 Core 启动一个测试账号，然后：
  重命名它 → 确认脚本真的停了；对运行中的账号连点两次启动 → 任务管理器里
  确认只有一个对应 Python 进程。

---

## B 级：安全问题（提供补丁，默认不动，由你决定）

### B1 Core 对所有网站开放跨域 + 全接口无鉴权

`module/server/app.py`：`allow_origins=["*"]` 且 `allow_credentials=True`；
`-k/--key` 参数在 `gui.py` 和 `app.py` 里都解析了但**从未使用**，deploy.yaml 的
`Password` 是死配置。后果：浏览器里打开的**任何网页**都可以跨域调用
`127.0.0.1:22267`——删除配置（`DELETE /config`）、停启脚本、触发
`GET /home/execute_update`（git pull）、`GET /home/kill_server`。
这是典型的 drive-by localhost 攻击面。

现状缓解：deploy.yaml 的 `WebuiHost: 127.0.0.1` 是对的（别改成 0.0.0.0——
`gui.py` 的兜底默认值恰恰是 0.0.0.0，注意别删掉 yaml 里这行）。
Bridge 层没有这个问题（只放行 localhost 来源的页面）。

可选补丁：`handoff/patches/optional-02-core-cors-localhost.diff`——把 Core 的
CORS 改成与 Bridge 相同的 localhost 正则。原生 QML/OASX/Flutter 客户端不是浏览器、
不受 CORS 约束，标注器页面由 Core 自己伺服（同源），**理论上不影响任何现有用法**，
但因为是上游行为变更，默认不替你应用。

### B2 高危运维接口无确认

`/home/execute_update`（远程 git pull）、`/home/kill_server`、`/home/notify_test`
（用任意配置发通知，可被用来探测内网）均为无鉴权 GET/POST。风险与 B1 叠加。
建议随 B1 一并收紧，或等上游加鉴权。

---

## C 级：正确性 / 性能隐患（文档化；Bridge 侧已规避的注明）

### C1 `time_delta` 天数解析只取一个字符 — `script_router.py` 147 行

```python
day = int(value[1])                       # "10 06:00:00" → day = 0（丢了十位）
date_time = datetime.strptime(value[3:], '%H:%M:%S')
```

`value[0]` 被完全忽略：天数 0–9（两位补零格式）恰好正确，**≥10 天被静默存成个位数**；
不带前导零的输入（`"5 06:00:00"`）直接 400。即 Core 的线格式物理上表达不了两位天数。
上游一行修法：`day = int(value[:2])`（顺带兼容 10–99 天）。
**Bridge 已规避**（v1.1.2）：>9 天在发给 Core 之前就拒绝并给中文错误；
前端天数输入框限制 max=9。属于表达能力限制而非数据损坏，故不动上游。

### C2 跨事件循环广播 WebSocket — `main_manager.py` + `script_process.py`

`MainManager.__init__` 起了一个独立线程跑 `asyncio.run(push_data_handle())`，
在**自己的事件循环**里创建 `coroutine_broadcast_state/log` 任务，向 uvicorn
主循环上 accept 的 starlette WebSocket 直接 `send_json/send_text`。
starlette/uvicorn 的 WebSocket 不是跨循环安全的——这是偶发丢日志、
偶发断连的合理解释（症状随时序漂移，难复现）。

Bridge 的自动重连已把「断连」这一半兜住；「丢行」无法从外部兜。
正确修法是把推送循环挪到主循环（lifespan 里 `create_task`）或改用
`asyncio.run_coroutine_threadsafe` 定向主循环。**这属于并发结构调整，
没有真实 Core 环境验证过的补丁我不交付**——建议提 issue 给上游，
或在你机器上做修改后用长跑观察。定位信息都在本节。

### C3 `config_cache` 名不副实（性能根因）— `main_manager.py`

```python
@staticmethod
def config_cache(name: str) -> Config:
    return Config(name)        # 每次调用全新构建：读 JSON + 全量 pydantic 解析
```

每次 `/args`、每次 WS `get_schedule` 都重建一次完整配置模型——这就是 13 号 B1
里「args 昂贵」的根因（被注释掉的 `ensure_config_cache` 说明上游曾尝试过缓存）。
**Bridge 已规避**（快照/缓存三级取数），上游可选优化：真缓存 + `ConfigWatcher`
mtime 失效（组件已存在，没接上）。

### C4 杂项（低危，仅记录）

| 位置 | 问题 | 影响 |
|---|---|---|
| script_router.py 121/125 | 两个路由函数同名 `script_task`，后者遮蔽前者 | FastAPI 注册在前，功能不受影响；可读性差 |
| script_router.py 172-200 | SSE 端点 `/{name}/state`、`/{name}/log` 是占位实现（无限 "Hello, SSE!"） | 误连的客户端会挂住；别用，用 WebSocket |
| config.py `task_delay` | `interval` 为 str 时 `timedelta(interval)` 会 TypeError | 正常路径 interval 是 TimeDelta 对象，属死路径 |
| config.py `save`/`update_scheduler` | 用 pydantic v1 的 `.dict()`（v2 下 deprecated） | 目前能用，pydantic 3 会断 |
| main_manager.py | `dict[str: ScriptProcess]` 注解笔误（应为逗号）；`os.kill(SIGILL)` 自杀式关闭 | 无运行时影响 / 关闭方式粗暴 |
| config_manager.py `copy` | 目标已存在时只记日志静默返回 | Bridge 已在创建前查重（13 号 B9） |
| script_router.py `config_rename` | `old==new` 或空名返回 False + HTTP 200 | Bridge 侧已有参数校验挡住 |

### 审查中确认干净的部分

- `tool.py` 标注器的文件操作有 `_ensure_within_root`（resolve + relative_to）防目录穿越，
  上传文件名做了 `_safe_stem` 清洗——这层是新代码，防御意识明显更好；
- `module/config/utils.py` 的配置写入用 `FileLock` + `atomic_write`，无半写风险；
- `script_websocket.py` 的连接管理对断开、重复关闭都做了防御。

---

## 本次落盘清单

```text
module/server/script_router.py     A1/A2 修复（5 行 await 之 4）
module/server/script_process.py    A3 修复（1 行）
handoff/patches/core-backup-20260726/{script_router.py, script_process.py}   改前原件
handoff/patches/applied-01-missing-awaits.diff                               已应用补丁的 diff
handoff/patches/optional-02-core-cors-localhost.diff                         可选：Core CORS 收紧（未应用）
control-center/bridge/app/core_client.py   v1.1.2：time_delta >9 天护栏
control-center/bridge/app/main.py          v1.1.2：重命名前先停任务（配合 A2）
control-center/bridge/tests/test_bridge.py       +1 用例（17）
control-center/bridge/tests/test_integration.py  +1 用例（16）
control-center/desktop/release/UI-claude/src/fields.jsx   天数输入限 9
handoff/15-上游Core代码审查.md   本文档
```

回归状态：单元 17/17，集成 16/16，真实三层端到端 15/15（本次改动后全部复跑）。

## 上游同步提醒（补充 14 号第五节）

这次动了两个上游文件（共 5 行）。`git pull` 前记住：
1. 冲突只可能出现在这 5 行，按 `applied-01` diff 解决；
2. 如果上游自己修了这些 bug，直接采用上游版本并删除本地补丁记录；
3. 强烈建议把 `applied-01-missing-awaits.diff` 提成上游 PR——合入后本地永久无负担。
