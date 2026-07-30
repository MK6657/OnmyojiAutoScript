# Codex 02 已知 Bug 与流程冲突清单

审计日期：2026-07-29  
分级：P0 表示当前会破坏数据、完全阻断核心功能或使交付不可恢复；P1 表示高概率错误行为、状态失真或严重维护风险；P2 表示中等风险、债务或尚未闭环的接口问题。

## 1. P0

### P0-01 二开基线没有进入版本控制，部分补丁不可重放

证据：

- Git HEAD 为 `b7497a35`，13 个上游文件共有约 486 行新增、64 行删除，但未提交。
- `control-center/`、`handoff/`、`frontend-preview/`、根启动 BAT、夜间模板等仍是未跟踪文件。
- `handoff/patches/realmraid-stuck-fix.diff` 的新路径是裸 `script_task.py`；`generalbattle-exit-fix.diff` 的新路径是裸 `general_battle.py`。从项目根执行 `git apply --check --reverse` 均因找不到目标文件失败。
- handoff 22 的 `module/atom/image.py`、`tasks/GameUi/assets.py` 和夜间 PNG 没有对应补丁。
- `tasks/RealmRaid/script_task.py` 标注 `handoff/23`，但目录不存在 23 号文档或补丁。
- `module/gui/fluent_app.py`、`Args.qml`、`MainWindow.qml` 的 QML 资源、DLL 搜索路径、Pydantic 2 schema 兼容和通知修改也没有专门留档补丁。

影响：上游更新、误操作或换机后无法可靠重建当前工作区；旧文档中的“重新 git apply”步骤会失败。当前 handoff 本身也未被 Git 管理，不能当作持久档案。

### P0-02 RealmRaid 当前不会挑战，却会按成功完成

`tasks/RealmRaid/script_task.py:54-56` 的 `LEVEL_DEBUG/CAPTURE_BOARD/CAPTURE_ONLY` 全为 True。进入棋盘后 `253-266` 保存截图、调用 `set_next_run(... success=True)` 并抛 `TaskEnd`。日志 `2026-07-27_teat2.txt:5933-5939` 已证明任务不挑战、被延期一天，随后调度器正常结束 RealmRaid。

影响：界面和调度看起来“成功”，实际既没有执行上游个人突破，也没有执行新卡级流程。这是最危险的假成功。

### P0-03 卡级决策层尚不存在

`tasks/RealmRaid/config.py:31-41` 没有每账号目标等级、卡级开关、阶段或恢复字段。等级只在 `script_task.py:529-600` 被读取、记日志并计算众数，主循环仍在 `303-340` 按旧勋章顺序选择目标。

当前缺失：红色“破”识别、RealmRaid 专用失败印记、当前棋盘成功/失败计数、降级/保级/升级状态机、刷新 CD 调度、自动刷新代次识别、票数预算和中断恢复。因此关闭 `CAPTURE_ONLY` 也不会得到用户要求的卡级功能。

### P0-04 Mock 联调会写入并清理真实控制中心元数据

`control-center/launcher/start-dev-stack.ps1:31-59` 只替换 Core URL，没有设置独立 `OAS_CONTROL_CENTER_DATA_DIR`。Bridge 默认仍使用 `control-center/data/control_center.db`，见 `bridge/app/main.py:34-36`。访问 `/accounts` 时，`repository.py:79-99` 会把不存在于 mock Core 的账号视为 stale，并删除其元数据和任务顺序。

例子：真实数据库有 A、B 两个账号，mock Core 只返回 demo。打开 mock 联调 UI 后，A、B 的控制中心昵称、标签、排序和 task_order 会被删除。Core 的真实 JSON 不会被删，但控制中心数据已经被污染。

### P0-05 启动前检查可以被顶部启动按钮和重启按钮绕过

概览按钮在 `UI-claude/src/views.jsx:45-113` 会检查 Core、设备、任务和实时通道；但顶部按钮 `App.jsx:790-800` 只要求存在账号，直接调用 `runAction('start')`。概览的 restart `views.jsx:117-119` 也不受 blocking 限制。Bridge `main.py:543-572` 只转发动作，没有二次验证。

影响：用户可以在未绑定设备、无启用任务或事件通道断开时启动账号，随后把框架错误误判成业务任务错误。

## 2. P1 Core 与调度

### P1-01 运行中再次 start 会启动进程但把状态留在 INACTIVE

`script_process.py:35-42` 先把状态设为 RUNNING；发现旧进程存活后 `await stop()`，而 stop 在 `50-52` 把状态改为 INACTIVE；随后 `43-48` 创建新进程却没有恢复 RUNNING。

影响：第二次启动后任务可能真实运行，但 Core/Bridge/UI 认为已停止；`MainManager` 也会因为 INACTIVE 不再拉取新进程日志和状态。

### P1-02 子进程死亡不能可靠修正父状态

只有 `script_process.py:153-158` 捕获 SystemExit 时推 WARNING；普通 Exception 在 `159-162` 重新抛出，没有状态事件。父进程也没有周期性用 `_process.is_alive()` 对账。

例子：任务初始化、Device 建立或未覆盖异常使子进程退出，`ScriptProcess.state` 仍可能永久为 RUNNING。当前 UI 的“运行中”不能作为进程存活证据。

### P1-03 MainManager 存在线程竞态和监听泄漏

`main_manager.py:85` 在推送线程遍历 `script_process`，REST/WebSocket 同时可新增、重命名、删除字典成员，可能触发 `dictionary changed size during iteration` 并杀死整个推送线程。

`main_manager.py:74-100` 的状态/日志协程只创建不取消。账号删除后旧任务仍持有旧 `ScriptProcess`；同名账号重建时任务 key 已存在，新实例反而不会得到监听。

### P1-04 配置存在丢失更新

Core API 每次创建新的 Config；任务子进程长期持有另一个 Config。虽然文件读写各自有锁和原子替换，但完整读改写没有共享事务。

例子：前端刚把 RealmRaid `target_level` 写入内存中的 A 版本，任务进程随后用旧 B 版本调用 `task_call()` 并整体 save，A 版本其他字段可能被覆盖。Bridge 的多字段 PATCH 也是逐字段 PUT，中途失败会留下部分保存状态。

### P1-05 默认 Filter 会静默丢任务

`FindJade` 出现在 `config_model.py:71,132` 和 `config_menu.py:35`，却不在 `config_manual.py:10-23`。默认调度规则是 Filter，`filter.py:45-78` 只输出匹配项。

影响：FindJade 可以在 UI 显示、可以启用、可以到期，却从 pending 结果消失，用户看不到明确报错。以后新任务也会重复踩三处注册契约。

### P1-06 schedule.running 不是实际运行态

Core WebSocket 建连时不检查账号进程状态就调用 `get_next()`，`config.py:244-245` 又只凭 `next_run < scheduler_update_dt` 填充 running。

影响：账号已停止时，前端仍可能显示某任务运行中；Bridge 再把这个快照用于启用任务缓存，放大了语义混乱。

### P1-07 `sync_next_run` 不能保证设置到指定时间

`script_router.py:154-163` 同时向 `task_delay()` 传 `success=True` 和 target；`config.py:308-346` 先取成功间隔和 target 的最早值，某些 `server_update` 设置还会把结果替换为服务时间。

这不适合作为未来“立即运行”“预约执行”的统一接口，因为调用者传入的绝对时间不是最终事实。

### P1-08 配置赋值验证并未启用

项目固定 Pydantic 2.10，`ConfigBase` 没有 `validate_assignment=True`。`config_model.py:407-415` 在 setattr 后捕获 ValidationError 的保护通常不会生效，非法值可能先进入内存或 JSON，到下次完整加载才失败。

## 3. P1 任务框架与通用组件

### P1-09 `TaskEnd` 和 `next_run` 是容易失配的双协议

任务必须自行安排下一次时间，并以异常表示成功。普通返回会被当失败，写了时间但没有 TaskEnd 仍失败，抛了 TaskEnd 但没有写时间会立即重跑。

例子：

- `GuildActivityMonitor/script_task.py:22-24` 在 run_days 无效时直接 TaskEnd，却不更新已到期 next_run，可能形成热循环。
- 只配置一个运行日且当天命中时，`candidate_days` 为空，`28` 对空序列 min()，直接终止任务。
- `GuildBanquet/script_task.py:190-192` 捕获配置异常后抛 TaskEnd，跳过 `plan_next_run()`，旧到期时间可能保留。
- `FindJade/script_task.py:42-45` 子账号异常先安排 10 分钟后重试，循环末尾又无条件按成功计划覆盖。

### P1-10 基础动作返回值不可信

- `BaseTask.click()` 在 `base_task.py:504-514` 已执行点击，但未传 interval 时返回 False。
- `list_appear_click()` 在 `626-644` 找到目标后只有传 interval 才点击。
- `ui_get_reward()` 在 `696-728` 超时也固定返回 True。
- `wait_until_appear_then_click()` 在 `313-332` 把 wait_time 当作第二个位置参数传入 `skip_first_screenshot`，实际没有设置超时；传 action 时仍点击 target 坐标。

这些接口使 `if click(...)`、重试和降级策略无法可信组合。

### P1-11 大量局部循环没有硬超时

对 `tasks/` 的静态检索发现 501 个 `while 1/while True` 语句，不代表全部有问题，但基础层已确认 `wait_until_disappear()`、`ui_clicks()`、`ui_click_until_disappear()` 默认无超时。GeneralBattle 的战斗结果、二次确认、奖励和预设确认仍有无限循环。

全局 stuck 检测不能完全兜底，因为持续点击/滑动会更新记录；故障模式会从“无日志卡住”变成“不断点击直到 TooManyClick”，RealmRaid 已有真实日志证据。

### P1-12 GeneralBattle 忽略准备失败

`general_battle.py:40` 不检查 `battle_before()` 返回值。准备阶段 5 秒超时返回 False 后，仍进入 `battle_wait()` 无限等战斗结果。预设确认 `445-454` 的 timer 到期只打印 warning，不 break。

### P1-13 页面注册和识别规则会跨任务泄漏状态

- 每个 GameUi 实例都扫描并 exec 所有 `tasks/**/page.py`，见 `game_ui.py:41-60`。
- `PageRegistry` 在 `page.py:16-25` 只追加不去重，账号子进程长期运行时会不断累积重复页面。
- RuleImage/RuleOcr 多为 Assets 类属性，任务代码会原地修改 ROI、keyword、file 或 name，状态会跨任务和测试残留。

## 4. P1 RealmRaid

### P1-14 handoff 22 的“退四打通”与日志冲突

第一次证据：`log/2026-07-27_teat2.txt:5383` 盲点退出确认，`5385-5388` 失败结算识别失败，随后 `5392-5404` 反复点击 partition_1 并触发 TooManyClick。

第二次证据：`5794-5798` 看似成功退出一次，马上再次进入退四；`5805-5810` 又因重复 GB_EXIT 触发 TooManyClick。

根因：`run_general_battle_back()` 可以返回 False，但 `RealmRaid/script_task.py:328-335` 四次调用都忽略返回值；上层也没有验证已经回到棋盘再进行下一次投降。

准确状态：已把永久等待改成超时和兜底，但没有完成“退出一次、确认失败、回到棋盘、计数加一”的可靠事务。

### P1-15 破印、失败印和中断恢复缺失

RealmRaid 资源中没有红色“破”规则；失败过滤只有 `WhenAttackFail.CONTINUE` 才执行，并借用 `RyouToppa/dev/loser_sign_1.png`。当前默认策略是 Refresh，失败过滤路径不会运行。

`current_count` 每次新建任务对象归零，success/last_battle 是局部变量。重启后无法从棋盘恢复已成功人数、失败次数或当前阶段，可能重复投降、重复挑战或错误刷新。

### P1-16 刷新 CD 资源存在但没有进入逻辑

`tasks/RealmRaid/assets.py:69` 已有 `O_FRESH_TIME`，任务没有调用。`check_refresh()` 只凭刷新按钮不存在断言“在 CD”，不能区分 CD、模板失配和页面未稳定，也不会把任务精确调度到 CD 结束。

### P1-17 等级 OCR 缺少当前版本的运行验证和可信度门槛

旧日志 `5914-5931`、`6022-6031` 出现 8、10、160、601 等误读。当前源码后来增加菱形掩膜、1 到 60 过滤和新 ROI，但没有之后的 RealmRaid 运行日志证明最终 9/9。

即使过滤有效，`current_challenge_level()` 没有“至少识别几格”或“众数占比”门槛；只识别出一个合法值也会成为决策等级。卡级动作不可建立在单格偶然结果上。

## 5. P1 控制中心与启动链

### P1-18 启动器会复用连接到错误 Core 的 Bridge

`start.ps1:243-249` 只看 `bridge=ok`，不比较 health 的 `core_url` 和本次 `-CoreUrl`。旧 Bridge 即使连着另一端口或 mock Core 也会被复用。

### P1-19 自定义 Core 端口只能探活，不能正确启动

`start.ps1:196-197` 解析 CoreUrl 的端口，但 `230-231` 启动 `server.py` 时没有传 `--port`。如果目标 `:22270` 未运行，脚本实际拉起 deploy.yaml 的 `:22267`，然后等待 `:22270` 超时。

### P1-20 端口避让和强制停止没有实例身份

避让到 22368/4176 的实例不写 PID/端口登记，下次启动和 `-RestartAll` 只检查固定 22367、4175、5173，容易留下多个 Bridge/UI。`Stop-PortOwner()` 又只按端口强杀，不校验进程是否属于本项目。

### P1-21 Electron 对 Bridge 的检查和失败处理不完整

`desktop/main.cjs:82-90` 只要 health 返回 HTTP 200 到 499 就视为 Bridge，不校验 JSON、版本、Core URL或实例身份。`143-148` 忽略 `waitForBridge()` 的 false，Bridge 启动失败仍打开页面。

### P1-22 当前 portable 与源码不一致

现有 portable 和打包 Bridge 生成于 7 月 26 日，早于 7 月 27 日 UI-claude 默认化和 Bridge 1.1.3。`desktop/ui` 仍是旧前端快照。默认 UI 源码又位于被 `release/` 忽略的目录，正常 Git 提交不会包含它。

另外 `build.ps1:62-65` 会把当前工作数据库复制为 data seed，可能把本机账号元数据和模板带入发布包；portable 只应携带空 schema/迁移。

### P1-23 多账号运行态不是全局实时

Bridge `/accounts` 用 `runtimes.peek()`，不会为所有账号建立 Core WebSocket。默认 UI 主要为当前选中账号请求排期和日志，因此未选中过但真实运行的账号可能在侧栏显示“已停止”，其日志也不会被 Bridge 接收。

### P1-24 “绑定窗口”不等于设备链路已绑定

前端一键绑定主要写 `script.device.handle`。OAS 默认截图/控制仍依赖 ADB serial；仅有 HWND 不能保证设备可控。handoff 18、19 已记录这一点，但 UI 入口名称仍容易让用户理解为一次操作完成全部绑定。

## 6. P2 与残余风险

- Core `/state`、`/log` SSE 在 `script_router.py:167-196` 仍固定输出占位字符串，任何新客户端误用都会获得假数据。
- WebSocket send 已回主循环，但 disconnect/close 和连接集合仍可跨线程执行；状态与日志也没有统一发送序列。
- Core 正常 shutdown 只写日志，不停止账号子进程和推送线程；`/kill_server` 最终使用 SIGILL 异常终止。
- Queue/Pipe 在 ScriptProcess 构造时创建并跨多代子进程复用，可能残留上一代消息；代码捕获 `asyncio.QueueEmpty`，而 multiprocessing Queue 抛的是 `queue.Empty`。
- `ConfigWatcher` mtime 精度只有秒，同一秒多次写配置可能不唤醒等待中的调度器。
- Bridge 任务状态缓存默认 45 秒，外部改 JSON 的展示存在延迟。
- Bridge 配置 PATCH 逐字段执行，不是原子事务；中途字段失败会留下半保存状态。
- `check-wiring.ps1` 自称只读，但 `/accounts` 会同步写 SQLite，`/schedule` 会建立 Core WebSocket 并发送命令，准确说应是“不启动游戏任务，但会改变控制中心运行态/元数据”。
- UI-claude README 仍记录不存在的 `-Mock` 参数；主 README 和早期 handoff 对默认端口、前端来源、SQLite 表结构的说明已过时。

## 7. 当前已修但尚未固化的内容

下列修补在当前工作区存在，但仍是未提交差异，不能视为稳定版本：

- REST start/stop、重命名、删除漏 await；重复启动双进程中的漏 await。
- Core CORS 收紧、time_delta 两位天数、WebSocket send 回主循环。
- RealmRaid 锁阵容、部分等待、刷新确认的超时；GeneralBattle 退出确认超时和 ROI 兜底。
- RuleImage 多模板和庭院夜间探索入口。
- QML FluentUI 资源/DLL 加载、Pydantic 2 `$defs` 兼容等修补。

在建立可提交基线、可重放补丁和自动回归前，这些修复仍可能被上游更新覆盖或相互漂移。
