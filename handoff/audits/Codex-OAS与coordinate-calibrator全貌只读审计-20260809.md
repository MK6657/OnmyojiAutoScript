# OAS 与 coordinate-calibrator 全貌只读审计

日期：2026-08-09  
审查对象：`D:\OSAyys`、`D:\coordinate-calibrator`  
审查性质：只读代码、文档、日志、运行状态与离线测试复核；本报告不等于修复记录或实机结案记录。  
关联外部审查：[DeepSeek-07](../archive/legacy-root-20260811/DeepSeek-07-双项目全面审查最终审计-20260809.md)

后续修订（2026-08-09 17:55）：本报告保留审查时点的 `0.3.3/120`、OAS `258` 和服务停止事实，不作为当前状态。后续已完成 coordinate-calibrator `0.3.5/125`、OAS `317/317`、Bridge `22/22`，并实施控制面、战斗终态、探索硬边界、调度所有权、选寮安全门禁和中立证据契约 v1。当前事实见 [当前状态](../00-当前状态.md)、[待做事项总表](../Codex-待做事项总表.md) 和 [坐标标定清单](../coordinates-to-calibrate-20260809.md)。这些修复仍不代表 30 场、绿标、选寮或真实设备矩阵结案。

## 1. 结论摘要

- 未发现会立即破坏两项目数据的系统级 P0；按 OAS 既有业务标准，`RY-GUILD-001` 的错误选寮和 `RR-COMBAT-001` 的绿标假确认风险继续作为业务 P0 开放。
- coordinate-calibrator 当前版本为 `0.3.3`，正式离线套件 `120/120` 通过；但显示帧/坐标帧不一致、背景作用域隐藏标注仍可命中等问题会直接影响坐标可信度，不能因离线基线通过而结案。
- OAS 定向离线套件共 `258` 项通过；通过项不包含进程竞态、命令确认、配置并发覆盖、真实绿标、真实窗口/DPI 和双设备身份等边界。
- 当前 coordinate-calibrator 的 HTTP 路径保持只读 OAS 边界；它生成的是候选，不是可以直接提交给 OAS 标注器的完整规则。
- 六个只读子代理均已结束并关闭。本报告的 P0/P1 均经过主审代码或运行证据复核；子代理意见没有直接当作事实写入。

## 2. 证据等级

| 标记 | 含义 |
|---|---|
| `代码复核` | 主审已读取当前源码并确认控制流或数据流成立。 |
| `日志复核` | 主审已读取本机日志、checkpoint 或进程状态。 |
| `离线通过` | 本轮实际执行对应离线测试并通过，只证明已有用例范围。 |
| `待故障注入` | 代码风险成立，但尚未通过可控异常重现。 |
| `待实机` | 依赖真实 MuMu、游戏画面、DPI、ADB 或交互时序。 |

## 3. 本轮基线

| 项目 | 本轮事实 |
|---|---|
| OAS 分支 / HEAD | `codex/mk6657-secondary-development` / `1724ce445cc9e44d277ec270c08c558ab9aa03d0` |
| OAS 工作树 | 审查开始时有 244 个修改或未跟踪条目；本结论针对当前磁盘状态，不代表干净提交。 |
| OAS 服务 | Core `22267`、Bridge `22367`、前端均未监听；旧 `frontend.json` 为历史登记。 |
| MuMu | 标题 `2301`、HWND `1442486` 存在，但窗口最小化；当前游戏画布、设备串号、方向和截图分辨率未确认。 |
| coordinate-calibrator | `0.3.3`，`127.0.0.1:22880` 健康，实际监听 PID `26944`，`allow_remote=false`。 |
| coordinate-calibrator 数据 | 本轮只读检查时 SQLite `integrity_check=ok`；数据数量以项目侧审计记录为准。 |

## 4. coordinate-calibrator 已验证问题

### 4.1 P1

| ID | 根因与触发条件 | 影响 | 证据 | 状态 / 缺失测试 |
|---|---|---|---|---|
| `CC-CORRECT-001` | 页面显示 `persisted_frame`，坐标换算却读取可能指向实时预览的 `latest_frame`。持久帧与预览帧尺寸不同时触发。 | 在用户看到的图片上点击中心，可能保存成另一套尺寸下的坐标。 | [显示帧](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L1528)、[换算尺寸](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L1847)、[双帧模型](../../../coordinate-calibrator/src/coordinate_calibrator/api/runtime.py#L107) | `代码复核`；缺 1280×720 持久帧叠加 1600×900 预览帧的浏览器回归。 |
| `CC-CORRECT-002` | 绘制过滤背景作用域，命中检测和部分选择校验没有使用同一谓词。 | 当前背景不可见的标注仍可被选中、拖动、隐藏或删除。 | [作用域谓词](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L355)、[绘制过滤](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L1981)、[命中检测](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L2091) | `代码复核`；缺背景 A 限定标注切到背景 B 后的命中/批量操作测试。 |
| `CC-TXN-001` | 帧文件、artifact、frame 行、背景关联、Session 缓存分属多个提交和回滚域。 | 配额拒绝、租约过期或背景写入失败后可能留下不可见 artifact、配额占用和内存/SQLite 分歧。 | [帧持久化](../../../coordinate-calibrator/src/coordinate_calibrator/api/runtime.py#L1496)、[背景提交](../../../coordinate-calibrator/src/coordinate_calibrator/api/runtime.py#L2083) | `待故障注入`；缺 frame commit 后逐点失败及重启恢复测试。 |
| `CC-ASYNC-001` | 工作区事件刷新未绑定 `{workspace_id, session_id, epoch}`；旧请求可在切换工作区后提交。 | A 工作区数据可能覆盖 B 工作区当前状态或携带错误租约。 | [事件刷新](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L1033)、[工作区激活](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L1416) | `代码复核`；缺延迟 A 响应、切换 B、释放 A 响应的确定性测试。 |
| `CC-EXPORT-SELECT-001` | 摘要接口按设计不返回 annotations，但刷新后使用摘要清理跨画布标注选择。 | 跨画布导出前一次刷新会静默丢失非当前画布选择。 | [摘要加载](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L760)、[选择裁剪](../../../coordinate-calibrator/src/coordinate_calibrator/web/workspace_state.js#L34) | `代码复核`并通过纯状态重现；缺真实 DOM/导出回归。 |
| `CC-LEASE-001` | 当前已归档画布恢复后只刷新数据，没有重新申请写租约。 | 界面恢复为可编辑，首次修改却返回 `423 lease_required`。 | [恢复流程](../../../coordinate-calibrator/src/coordinate_calibrator/web/app.js#L1350)、[租约门禁](../../../coordinate-calibrator/src/coordinate_calibrator/api/app.py#L382) | `代码复核`；缺当前归档画布恢复后立即创建/移动标注测试。 |
| `CC-SEC-002` | `server.py --host` 可覆盖实际绑定地址，认证判断仍读取启动前的 `SETTINGS.host`。 | 仅在显式开放远程并绕过日常启动器时，可能向伪造 localhost Host 的远端响应发放令牌 Cookie。 | [CLI host](../../../coordinate-calibrator/src/coordinate_calibrator/server.py#L31)、[UI 认证](../../../coordinate-calibrator/src/coordinate_calibrator/api/app.py#L398) | `代码复核`；默认 `127.0.0.1` 不触发。缺有效绑定地址驱动的认证测试。 |
| `CC-MIGRATE-001` | 正式应用启动固定传入 `allow_schema_migration=True`，绕过维护命令显式确认语义。 | 普通启动旧数据库会自动备份并升级 schema。 | [应用启动](../../../coordinate-calibrator/src/coordinate_calibrator/api/app.py#L151)、[维护入口](../../../coordinate-calibrator/src/coordinate_calibrator/maintenance.py#L143) | `代码复核`；缺旧 schema 应用生命周期测试。 |
| `CC-INTEGRITY-001` | reconcile 对数据库中 `ready` artifact 建立引用集合，但不逐个校验文件存在、大小和 SHA。 | 已登记证据文件被删除或篡改时，对账仍可能报告正常。 | [对账流程](../../../coordinate-calibrator/src/coordinate_calibrator/api/runtime.py#L1659) | `代码复核`；缺 ready 文件缺失/篡改测试。 |
| `CC-BUNDLE-001` | 工程包校验未完全复用 API 的画布尺寸上限，也没有限制唯一分组数量。 | 合法哈希包可放大 SQLite 数据和比较阶段图像内存分配。 | [包校验](../../../coordinate-calibrator/src/coordinate_calibrator/storage/bundles.py#L223)、[比较缩放](../../../coordinate-calibrator/src/coordinate_calibrator/domain/comparison.py#L29) | `代码复核`；缺超大尺寸、海量分组和比较内存边界测试。 |
| `CC-CAPTURE-001` | Nemu 身份主要证明配置组合，校准器还直接导入 OAS 私有 `NemuIpcImpl` 并复制实例解析。 | OAS 路径、配置模型或多实例解析变化时可能静默失效或串设备。 | [Nemu worker](../../../coordinate-calibrator/src/coordinate_calibrator/adapters/capture/nemu_worker.py#L57)、[OAS 私有实现](../../module/device/method/nemu_ipc.py#L483) | `代码复核`；缺真实双实例错误设备拒绝与版本契约测试。 |
| `CC-CAPTURE-002` | 低级鼠标钩子没有保留原生时间和 injected 标记；回调把当前预览持久化为“前帧”。 | 点击前帧不一定在物理点击前产生，证据时序不可证明。 | [鼠标适配器](../../../coordinate-calibrator/src/coordinate_calibrator/adapters/windows/mouse.py#L33)、[样本持久化](../../../coordinate-calibrator/src/coordinate_calibrator/api/runtime.py#L2833) | `待实机`；缺高频变化画面和注入点击拒绝测试。 |
| `CC-DPI-001` | 设置 Per-Monitor DPI awareness 返回拒绝时被当作可继续，启动层没有验证实际 DPI awareness。 | 特定宿主先设置了不同 DPI 模式时，屏幕坐标和窗口坐标可能不在同一物理基准。 | [DPI 初始化](../../../coordinate-calibrator/src/coordinate_calibrator/adapters/windows/provider.py#L30) | `待实机`；缺多显示器、125%/150%、移动窗口 P95。 |

### 4.2 重要 P2/P3

- 幂等缓存指纹不含租约身份，600 秒缓存还长于 300 秒最大租约；旧幂等响应可能绕过当前租约检查。
- 工程包导入在 async 路由内执行同步解压、哈希、图像解码和数据库写，可能阻塞健康检查与 WebSocket。
- 工程包导出不是 SQLite/文件一致性快照；并发修改背景作用域时可能生成哈希正确但自身无法导入的包。
- “永久删除”进入无限期隔离区，隔离字节不计入正式配额；长期反复删除可能耗尽磁盘。
- Session 数据库删除后若文件清理失败，接口仍可能返回成功并留下孤儿。
- 部分并发读没有使用 Session 锁，可能返回混合版本或触发迭代期间字典变化。
- 当前 Windows 令牌文件继承目录 ACL；多用户机器上需单独验证权限。
- 比较闪烁定时器、背景切换和画布切换的生命周期未统一；大量选择操作仍全量重建 DOM/overlay。

完整项目侧问题清单见 [coordinate-calibrator audit](../../../coordinate-calibrator/docs/audit-20260809.md)。

## 5. OAS 已验证问题

### 5.1 业务 P0

| ID | 根因与触发条件 | 影响 | 证据 | 状态 / 缺失测试 |
|---|---|---|---|---|
| `RY-GUILD-001` | 点击一次勋章排序按钮后假定为降序，再固定点击第一张，并记录 `medal_reward=maximum`；未验证排序状态，也未读取勋章数。 | 可能选择错误寮并产生业务假成功。 | [选寮实现](../../tasks/RyouToppa/script_task.py#L477) | `代码复核`、历史实测已失败；缺升/降序、像素稳定、OCR 不完整和最大值比较测试。 |
| `RR-COMBAT-001` | 2026-08-07 日志为 `0 confirmed / 80 unconfirmed / 0 outside`；当前调用方忽略 `green_mark()` 的 False，`LEFT3` 与 `MAIN` 扩展确认带又大面积重叠。 | 未确认绿标仍继续战斗；已有其他目标绿标可能被误当成当前目标成功。 | [调用方](../../tasks/Component/GeneralBattle/general_battle.py#L139)、[确认带](../../tasks/Component/GeneralBattle/general_battle.py#L1053)、[目标 ROI](../../tasks/Component/GeneralBattle/assets.py#L56)、[8-07 日志](../../log/2026-08-07_oas1.txt) | `代码+日志复核`；需要逐帧实测与 max-score/HSV 对照。不能仅凭模板颜色数量断言根因。 |

### 5.2 P1

| ID | 根因与触发条件 | 影响 | 证据 | 状态 / 缺失测试 |
|---|---|---|---|---|
| `CORE-LIFE-001` | `self._process` 在 `process.start()` 前发布；独立监控线程调用未加生命周期锁的 reaper。 | 监控线程可能清掉尚未启动对象，形成无法停止的孤立 worker，随后又允许重复启动。 | [发布顺序](../../module/server/script_process.py#L89)、[reaper](../../module/server/script_process.py#L42)、[监控线程](../../module/server/main_manager.py#L30) | `代码复核`；缺 monitor-before-start、kill 后存活和重复启动测试。 |
| `CONTROL-ACK-001` | Core WebSocket 启停没有命令 ID/回执；Bridge 把 socket send 成功当作执行成功。 | Core spawn 失败或子进程异常时，前端仍可能显示 accepted。 | [Core WS](../../module/server/script_router.py#L222)、[Bridge command](../../control-center/bridge/app/runtime.py#L108) | `代码复核`；缺延迟失败、断线后失败和结构化 crash reason 测试。 |
| `CONFIG-CONCURRENCY-001` | Bridge 多字段逐项提交；`ConfigModel.__setattr__` 每次全量保存，worker 旧模型可覆盖 UI 新改动。 | 请求部分成功、写放大、并发丢失更新。 | [逐字段保存](../../control-center/bridge/app/main.py#L631)、[自动全量写](../../module/config/config_model.py#L166) | `代码复核`；缺多字段回滚和 worker/UI 并发写测试。 |
| `COMBAT-STATE-001` | 战斗开始后自动模式未知返回普通 False；业务任务可能按战败结束，而 GotoMain 又正确拒绝触碰 `page_battle`。 | 活动战斗/待结算页面可能没有明确恢复所有者。 | [自动模式失败](../../tasks/Component/GeneralBattle/general_battle.py#L133)、[GotoMain 门禁](../../tasks/GotoMain/script_task.py#L13) | `代码复核`；缺“自动未知→任务退出→恢复/Restart”端到端状态机测试。 |
| `EXP-LEVEL-001` | 找章节阶段最多滑动 15 次，但命中候选后的点击与等待循环没有截止时间。 | OCR 曾命中但点击/确认失败时无限等待。 | [章节选择](../../tasks/Exploration/base.py#L561)、[无界确认循环](../../tasks/Exploration/base.py#L597) | `代码复核`；缺点击失败、确认框残留和入口缺失测试。 |
| `EXP-MAP-001` | MAIN 地图搜索的总体退出约束不足；稳定但没有位移的滑动仍可能被当成成功并重置计数。 | 无怪、终点漏识别或地图到边缘时可能长期搜索。 | [MAIN 循环](../../tasks/Exploration/solo.py#L65)、[搜索耗尽](../../tasks/Exploration/solo.py#L92) | `代码复核`；缺 MAIN 总时限、终点漏识别和无位移组合测试。 |
| `LAUNCH-WIRING-001` | 启动器复用 Bridge/前端时只核对表面健康和页面签名，不核对完整 Core→Bridge→frontend 依赖身份。 | 自定义 Core URL 或备用端口下，界面可能连接另一套 Core。 | [Bridge 复用](../../control-center/start.ps1#L313)、[前端代理](../../control-center/frontend/vite.config.js#L6) | `代码复核`；缺自定义 Core、备用 Bridge 端口和陈旧登记测试。 |
| `BINDING-001` | 非 MuMu 映射在只有一个 ADB serial 时，把数量唯一当作窗口身份依据。 | 多个模拟器窗口可能都被分配同一设备。 | [Bridge 映射](../../control-center/bridge/app/main.py#L111) | `代码复核`；缺多窗口单 serial 和身份拒绝测试。 |
| `TASKEND-001` | `TaskEnd` 无结构化 outcome/reason/next_run 契约，`Script.run` 捕获后统一返回成功。 | 失败、重试、正常结束和调度结果可能混为同一种状态。 | [TaskEnd 捕获](../../script.py#L502)、[异常类型](../../module/exception.py#L61) | `代码复核`；缺所有 TaskEnd 路径的结果与调度矩阵。 |
| `SCHED-AUTH-001` | Exploration 同时写自身、RealmRaid、MemoryScrolls next_run；MemoryScrolls 仍直接关闭 Exploration scheduler。 | 任务边界不清，任务可越权改变其他任务调度。 | [跨任务 next_run](../../tasks/Exploration/base.py#L906)、[跨任务 enable](../../tasks/MemoryScrolls/script_task.py#L124) | `代码复核`；缺统一授权入口和跨任务拒绝测试。 |

### 5.3 已实施但仍待实测的边界

- `GotoMain page_battle` 当前代码已有保护，并有 [离线测试](../../tasks/GotoMain/tests/test_battle_guard.py)；DeepSeek-07 将历史 2026-08-07 现场继续列为“当前未实现缺口”不准确。当前状态应为“代码已实施、真实异常链待复测”，不能作为当前待修复代码缺陷。
- RealmRaid 的 RAISE/LOWER、手动刷新和跨棋盘模式仍没有真实运行证据；当前 checkpoint 是 2026-08-07 历史状态，不是本轮运行状态。
- 绿标 HSV 检测是值得对照的候选方案，但模板颜色丰富、暗底或抗锯齿本身不能证明 TM_CCOEFF_NORMED 必然失败；需要同一真实帧比较模板 max-score、HSV 命中和目标身份。

### 5.4 重要 P2/P3

- RyouToppa 战败后立即返回，未先回棋盘读取失败标记，`skip_difficult` 缺少有效闭环。
- RyouToppa `count_limit`、`time_limit` 走失败调度，而配置语义把正常限额定义为成功结束。
- 旧数字队伍/御魂预设路径存在无界等待或全部点击失败仍记录成功；命名预设路径相对可靠。
- Exploration Buff 不保存任务开始前状态，结束时可能关闭用户原本已开启的 Buff。
- Core shutdown、worker join/kill、Queue/Pipe 生命周期没有统一 supervisor；WARNING 活进程前端又不显示 Stop。
- 八个识别资源源清单不是合法 JSON，当前生成的 `assets.py` 可用，但资源重新生成链不可靠。

## 6. 跨项目问题

| ID | 结论 | 状态 |
|---|---|---|
| `X-ADAPTER-001` | coordinate-calibrator 依赖 OAS 私有 Nemu 类和配置模型，缺少版本化公共 `DeviceIdentity/FrameEnvelope` 契约。 | `代码复核` |
| `X-CANDIDATE-001` | 校准器一次只导出 clickPoint、roiFront 或 roiBack；OAS 点击规则要求同一规则具有 `itemName + roiFront + roiBack`，正式保存还需要 task、路径、rule_type。DeepSeek-07 所称“原生格式已基本闭环”不成立。 | `代码复核` |
| `X-EVIDENCE-001` | OAS 状态快照没有统一帧 SHA/设备来源，校准器工程包又不包含完整点击样本及前后帧；两边无法形成 action→frame→result 的可重放证据链。 | `代码复核` |
| `X-COORD-001` | 校准器方向用角度，OAS 用四分之一转枚举，两个前端各自实现 ROI/缩放换算；缺跨项目黄金向量。 | `代码复核` |
| `X-DOC-001` | OAS 当前入口仍记录校准器旧版本和旧测试数，当前状态快照也保留重启前服务状态。 | `运行+文档复核` |

## 7. 已成立能力与建议沉淀

以下是建议方向，不表示接口已经存在：

- 从校准器领域层提炼跨语言坐标黄金向量：屏幕、图像、画布、半开 ROI、方向和缩放。
- 建立中立的 `DeviceIdentity`、`FrameEnvelope`、`CandidateEnvelope`、`EvidenceManifest`；OAS 生产运行帧，校准器只读消费和复核。
- OAS 视觉诊断应直接复用 `RuleImage.match()` 的多模板与阈值语义，避免诊断工具和运行时结果不同。
- OAS 建立结构化 `BattleOutcome` 和战斗恢复门，明确活动战斗、待结算、胜负、已回业务页和异常退出的所有者。
- 将预设、御魂、锁定、Buff 组织成事务式 `BattlePreparationSpec/Result`，记录原状态、应用证据和精确恢复结果。
- 校准器继续拥有版本化背景、通用标注、比较、统计和只读候选；OAS 拥有业务规则语义、目标路径验证与正式写入。

## 8. DeepSeek-07 交叉验证结论

| DeepSeek-07 结论 | 本轮处理 |
|---|---|
| OAS `.venv` 可用 | 采纳。清空 `PYTHONPATH` 后实测 Python 3.11.15 / NumPy 1.24.3 / OpenCV 4.7.0。当前 PowerShell 的 `PYTHONPATH` 本身为未设置；不把 Linux `env -u` 写成 Windows 唯一命令。 |
| MemoryScrolls 跨任务 next_run 已注释但 scheduler.enable 越权仍在 | 采纳。代码行复核成立。 |
| GotoMain page_battle 仍是当前代码缺口 | 修正。当前已有门禁和 unittest，只保留真实异常链待复测。 |
| 绿标模板结构是主根因 | 保留待证。8-06 同模板有 66 次 confirmed，8-07 为 0/80，说明发生回归，但不能仅凭模板颜色统计锁定根因。 |
| coordinate-calibrator 为 38/38 | 拒绝。当前版本 `0.3.3`，正式套件是 `120/120`。 |
| OAS 候选原生格式已闭环 | 拒绝。当前候选缺少可直接提交的完整规则和正式目标元数据。 |
| RAISE/LOWER、手动刷新无实机 | 采纳为证据缺口；历史 checkpoint 不作为当前运行事实。 |
| TaskEnd、配置写放大、跨任务调度越权 | 采纳。当前源码逐项复核成立。 |

## 9. 测试方建议顺序

1. 先在隔离数据副本复现 `CC-CORRECT-001/002`，确认坐标和隐藏标注问题，不连接游戏。
2. 用故障注入验证 `CC-TXN-001`、租约/幂等和 ready artifact 对账，不操作正式数据。
3. 为 `CORE-LIFE-001`、`CONTROL-ACK-001`、`CONFIG-CONCURRENCY-001` 写确定性并发测试，不先启动真实任务。
4. 用历史/靶场真实帧对绿标模板 max-score、HSV 和目标区域做三方比较；没有逐帧证据前不选择算法。
5. 最后执行 MuMu `2301`、干扰窗口、DPI/移动、十个点击样本、真实 ADB 和双 MuMu 实机矩阵。

## 10. 未验证边界

- 本轮没有运行真实 OAS 任务，没有操作游戏，也没有验证 OCR 阈值和动画时序。
- MuMu `2301` 当前最小化；游戏画布矩形、截图分辨率、设备 serial 和方向未确认。
- 没有执行 kill-at-every-write、跨进程配置冲突、远程网络和多用户 ACL 实验。
- coordinate-calibrator 无 Git 元数据，无法证明源码来源或未提交改动边界；OAS 工作树本身已有大量用户修改。
- 历史日志只证明当时状态，不能替代 2026-08-09 当前实机结论。
