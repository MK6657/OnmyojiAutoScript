# DeepSeek-10-OSAyys全项目只读审查-20260813

> 审查执行：Hermes（DeepSeek）父代理 + 5 个只读子代理并行，父代理独立复现验证后汇总落盘。
> 审查对象：`D:\OSAyys`（MK6657 二开分支）。git HEAD=`1724ce44`；**08-11 后无提交，审查对象 = 工作树对 HEAD 的全部未提交变更（195 个跟踪文件 +13425/−14039 行 + 大量 untracked 新文件，共 287 项）**。
> 审查约束：**全程只读**。未修改任何文件、未 git commit/checkout/stash、未装依赖、未启动服务/模拟器/游戏客户端、未运行迁移/维护命令。测试运行经用户授权，全部 `env -u PYTHONPATH .venv/Scripts/python.exe -B`。
> 行号以当前工作树为准；置信度：**已证实 / 高概率 / 待实机**。

## Errata（2026-08-13 晚，DeepSeek-11/12/13 轮）

> 正文保留原判，不再作为当前事实引用。权威入口：handoff/audits/DeepSeek-11-根因定位审查-20260813.md §2、DeepSeek-11-复验结论-20260813.md、DeepSeek-13 修复轮实施记录。

- **F-1（BrokenPipe 链）**：根因升级为已证实（DS-11 R-1：孤儿 worker + start.ps1:184 强杀工具链）。**DS-13 已修**：start.ps1 -RestartCore 优雅优先（/home/kill_server + 12s 轮询，Force 兜底）+ module/logger.py 管道写 BrokenPipeError/OSError 防护。
- **F-3（GotoMain 重置计数）**：**证伪**（DS-11 R-3：计数按任务名分键，GotoMain 只清自己；真因 = worker 换进程清空内存计数）。**DS-13 已修**：script.py failure_record 持久化 sidecar（work/<account>_failure_state.json，原子替换+时间戳）。
- **F-5 的「20:09:31 真实战斗 unconfirmed」旁证**：降级为测试夹具回放（DS-11 R-7：frame_sha256 为 64 个 'a' 占位、1970-01-01 假时间戳、毫秒级 duration）。黑底模板缺陷本身维持（OAS-GREEN-TPL-001）。
- **F-10 的「BLOCKED→GameStuckError→游戏重启」链**：经 DS-13 复核为误读——BLOCKED 仅生成报告不 raise；真实 fail-hard 是 dispatcher 内对无效帧的 GameStuckError。**DS-13 已修**：friend_invitation required_deadline_capabilities ('capture',)→()（尺寸契约保持 fail-closed，项目自有测试 enshrined）。
- **F-11（oas2 秒退 + Core 反复重建）**：**证伪**（DS-11 R-2：全部为 test_script_process 测试工件，child_pid 恒 4100=FakeProcess；server.txt 0 命中）。生产从未拉起 oas2。
- **F-12（测试污染）**：范围修正为全天 00:34→20:39（DS-11 R-8）。**DS-13 已修**：module/logger.py 测试上下文检测（OAS_TEST_LOGDIR/PYTEST/unittest argv）→ %TEMP%\oas-test-logs，实测生产日志 0 增长。
- **F-16（测试租约冲突）**：**DS-13 已修**：AccountRunLease 支持 OAS_LEASE_DIR 环境注入 + tests/conftest.py 隔离租约目录，套件全绿 0 AccountLeaseError。

---

## 0. 审查方法与实况基线

**方法**：① 父代理侦察（git 状态、新模块、总表、日志）；② 5 个只读子代理并行（A=XiuxingHexun+config 事务层；B=base_task+通用组件+设备层；C=control-center Bridge/前端/启动器；D=调度器+跨任务普查+日志证据；E=handoff 文档链+测试清点）；③ 父代理独立验证 20+ 项声称（亲读 file:line、内存复现、模板像素普查、日志统计），**纠正子代理 E 一条误判**（见 F-12）。

**实况基线（2026-08-13 20:40 实测）**：
- Core 运行中（PID 5936，监听 127.0.0.1:22267）；coordinate-calibrator 运行中（PID 25064，22880，两个 nemu_worker 占用模拟器连接端口 3278/7230）；**Bridge（22367）与前端（4175）已停**。
- `log/2026-08-13_oas1.txt`：97,918 行（00:16–06:04），**全天只有 XiuxingHexun 一个任务运行**：18 次启动、82 场胜利、2 次恢复判定、9 次失败、4 次打满挑战上限，06:04:27 以 `no ticket evidence` 正常收工，next_run=2026-08-14 06:04:27（明早自动再跑）。
- 日志行号与当前树**逐位吻合**（script.py:673/533/442、script_process.py:404 等抽查全中）——运行的就是当前树；但 XiuxingHexun 模块自身夜间经历热修（00:34 版本行号 :0103 → 当前 151，06:04 收尾跑的是中间版本，'no ticket evidence' 字样当前树已不存在）。
- 父代理亲跑：XiuxingHexun flow 32/32 + config 18/18 + 批量路由/迁移 47 项 OK；子代理实跑 GeneralBattle 116/116、CommonPopup 27/27、Bridge 29/29+3/3。
- 配置：`config/oas1.json` enable=true；`config/` 下无 oas2.json（oas2 被 auto 启动但无配置）。

---

## 1. 历史声明核对总表（总表 SCHED-AUTH/TASKEND/CONTROL-ACK/CONFIG-CONCURRENCY/LAUNCH-WIRING/BINDING + 历史缺陷家族）

| # | 声明/缺陷 | 判定 | 证据（父代理亲验或子代理+父代理交叉） |
|---|---|---|---|
| 1 | TASKEND-001 结构化 TaskEnd 全量落地 | ✅ 已实施 | tasks/+module/ 114 处 raise 全部工厂式（completed 53/aborted 2/deferred 2/failed 2/stopped 2），**0 处裸 raise TaskEnd()**（父代理 grep 复验） |
| 2 | SCHED-AUTH-001 白名单 + 审计 | ✅ 主路径已实施 | `_CROSS_TASK_SCHEDULE_ALLOWLIST`（config.py:31-46）+ `_assert_schedule_authorized`（56-66）+ schedule() 统一入口 + SCHEDULE_DECISION 审计日志；全量普查 7 个跨任务调用点全部命中白名单 |
| 3 | SCHED-AUTH-001 旁路未收敛 | ❌ 2 处直接写旁路 | 见 F-4 |
| 4 | 三连败退出治理 | ✅ 已实机生效 | 08-12 22:56:43 日志实测：`failed 3 or more` → `Request human takeover` → exit(1)（父代理亲验） |
| 5 | CONTROL-ACK-001（发送成功≠执行成功） | ✅ 已实施 | bridge runtime.py:117-147 command_id 请求-回执协议、success:false→CommandExecutionError；真 Core script_router 同协议；29/29 测试 |
| 6 | CONFIG-CONCURRENCY-001（428/409+草稿保留） | ✅ 已实施 | Bridge main.py:687-689 缺 revision→428；Core 侧 PATCH 428/409（script_router.py:394-396）；前端 If-Match+草稿保留；**但 PUT 单值路由无门禁**（F-9） |
| 7 | LAUNCH-WIRING-001（端点身份校验） | ✅ 已实施 | start.ps1 `Test-BridgeHealthMatchesCore`；前端登记 PID+StartTime+HTML 指纹+bridge_url 三关；wiring.ps1 9 断言实跑通过 |
| 8 | BINDING-001（删除唯一 serial 猜测） | ✅ 已实施 | bridge main.py:99-114 非 MuMu 一律 None；OSAyys capture 层无自动继承路径（父代理全仓 grep 'generic'/'serial_source' 0 命中） |
| 9 | match_multi_scale 循环变量写回 bug | ✅ 已修复 | module/atom/image.py:271-277 `best_size` 从胜出尺度写回，注释明示旧缺陷（父代理亲读） |
| 10 | GeneralBuff 动态 ROI 类属性污染 | ✅ 已修复 | general_buff.py set_switch_area 返回局部副本（父代理亲读） |
| 11 | 无效基准选出错分辨率 | ✅ 已修复 | benchmark.py 1280x720 RGB 契约校验器（子代理 B 亲读） |
| 12 | Config.__getattr__ 静默 None 家族 | 🟡 部分 | 机制仍在（config.py:148-160），但已知错误引用已清零（Emulator_ScreenshotMethod 0 处活动引用，死 clamp 分支已删） |
| 13 | nemu_ipc 超时线程残留 | ❌ 仍存在 | nemu_ipc.py 全文 0 处 Lock/Semaphore/join（父代理 grep 复验）；本轮只加了日志 |
| 14 | 绿标黑底模板确定性缺陷 | ❌ 缺陷文件仍在树中 | 见 F-5（父代理 PIL 普查） |
| 15 | 困28/寮突破/RealmRaid 各事项状态 | ✅ 与总表一致 | 子代理 E 逐条核对 EXP-028/COMBAT-PREP 一致；RR/RY 状态以总表为准（本轮无新实机证据推翻） |

---

## 2. 新发现问题清单

### 🔴 阻断级（1 条）

**F-1 · Worker 因日志管道断裂崩溃（BrokenPipeError），当日 4 次，每次中断任务后自愈重启**
- 位置：script_process.py:404（`script.loop()` 顶层）← script.py:676（`logger.hr(task)` 首行日志）← module/logger.py print 写 log pipe
- 证据：今日 oas1 日志 4 个 rich traceback，locals 全部 `e=BrokenPipeError(32,'管道正在被关闭。',None,232,None)` + `log_pipe_in=<PipeConnection>`（父代理亲验 03:43/05:45 两处完整 traceback）；崩溃后 2-4 秒 auto 重启（双 `Start task` 行相邻）；05:45:34 崩溃与配置热重载（config_watcher "Config oas1 changed"）时间吻合。
- 机制：已证实。**根因归属（Core 重启/退出时未优雅终止旧 worker，旧 worker 下次写日志即崩）= 高概率**，需 Core 侧日志佐证（D 子代理找到 8-12 server 日志 'log coroutine cancelled' 同型旁证）。
- 影响：每次崩溃中断正在运行的任务（05:45 场即被中断后重启），虽自愈但任务连续性受损；与 E1 idle-vs-crash 启发式、Core 20:01-20:36 反复重建（parent_pid ×10，见 F-11）同族。
- 建议：① script_process 优雅关停时先终止/排空旧 worker 日志管道再退出；② logger 写管道加 OSError 防护（BrokenPipeError 落文件日志而非炸进程）；③ 定位 Core 20:01-20:36 反复重建的触发者（watchdog？手动？日志只记录结果不记录原因）。

### 🟡 注意级（15 条）

| # | 问题 | 证据 | 置信度 |
|---|---|---|---|
| F-2 | **GuildActivityMonitor run_days 配置无效 → `raise TaskEnd.completed` 无 set_next_run**：completed→RESET，next_run 停在过去 → 调度器立即重跑 → 无限热循环且失败计数永远为 0（8-09 A1 同款，漏网）。当前 guild_activity_monitor enable=False 未触发，**潜伏态** | GuildActivityMonitor/script_task.py:23-24（父代理亲读） | 已证实（代码路径） |
| F-3 | **失败计数被穿插的成功 GotoMain 重置**：08-13 凌晨 05:36/05:46/06:00 三次 XiuxingHexun 搜索失败（GameStuckError→INCREMENT），每次失败后 18s 内 GotoMain success→RESET，计数回到 0，连败 3+ 次未触发禁用阈值 | 日志序列（父代理统计：FAILURE→GotoMain end 时间线） | 已证实（日志），语义设计问题待确认 |
| F-4 | **跨任务越权 2 处直接写旁路**（不走 schedule()、无白名单、无审计）：① MemoryScrolls/script_task.py:124-125 `config.exploration.scheduler.enable=False`+save()（8-09 B1 残留，反向关系不在白名单）；② CollectiveMissions/script_task.py:167 `config.bondling_fairyland.scheduler.next_run=self.start_time`（collective_missions 不在白名单）。另 script_router PATCH /values 可写任意 scheduler 字段（actor 有 '*' 权限，非越权但审计盲区） | 父代理亲读三处 | 已证实 |
| F-5 | **绿标黑底模板确定性缺陷仍在树中**：PIL 普查 `gb_green_marker.png` 黑色像素 42.0%、`gb_green_marker_bottom.png` 28.5%、`gb_green_marker_left_top.png` 36.4%（全不透明；对照 TrueOrochi 6 个绿模板 0% 黑）。TM_CCOEFF_NORMED 下分数天花板≈0.90，阈值 0.8 不可达。主链路已绕行（颜色槽位检测器 detect_only，模板仅诊断），ADR-002 已承认；**但缺陷模板未重采**。实机旁证：今晚 20:09:31 真实战斗 green_left1 两次点击均 unconfirmed（"no marker in target region"） | 父代理 PIL 普查 + 20:09 日志 | 已证实 |
| F-6 | **XiuxingHexun 凌晨 3 连败根因 = OCR 把 "0" 读成字母 "O"**：O→0 防护（script_task.py:299-302）刻意拒信 → count=None → 搜索点击后无结果 → GameStuckError；05:36/05:46/06:00 三次连败，直到 06:04 读到真 "0" 才确认耗尽收工。防护方向正确（防误判耗尽），代价是真实耗尽会被多次误判为失败并触发游戏重启链 | 日志序列（父代理统计决策/读数）+ 代码亲读 | 已证实 |
| F-7 | **XiuxingHexun max_challenges 默认 0 = 无上限循环，唯一正常出口完全依赖 OCR 耗尽判定**（config.py 默认 0；run() 87 行 while max_challenges==0 or ...）。若皮肤漂移使搜索按钮模板持续匹配且 OCR 读不出 0，理论空转（每轮有 deadline+失败 raise，无死循环，但反复失败重启） | script_task.py:87-92（父代理亲读） | 已证实（代码），实机概率待观察 |
| F-8 | `_recover_existing_result` 单凭 VICTORY 标题模板（threshold 0.8）即记 recovered VICTORY；重启时若战败页局部与胜利标题相似度≥0.8 会误记胜利。模板实测非黑底（子代理 A 灰度普查），误匹概率低 | script_task.py:132-142（父代理亲读） | 高概率风险，实机未触发 |
| F-9 | **PUT 单值路由无 revision 门禁**：script_router.py:450-455 非 xiuxing_hexun 分支走 `mm.config_cache(...).model.script_set_arg`，无 HTTP 层 428/409；与 PATCH 批量路由不对称 | 父代理亲读 | 已证实 |
| F-10 | **CommonPopup 分发器对非 nemu 截图方式 fail-closed 过严**：好友邀请 handler 要求 `required_deadline_capabilities=('capture',)`（friend_invitation.py:23），非 nemu（ADB/窗口）直接 BLOCKED→GameStuckError→游戏重启+失败计数；帧尺寸严格 ==(1280,720)（dispatcher.py:122-123）否则每帧判死。旧 `_burst` 对所有截图方式自动点击 | 父代理亲读两处 | 已证实（代码），触发取决于部署方式 |
| F-11 | **oas2 无配置文件被 source=auto 反复拉起秒退（child_pid 恒 4100）** + Core 20:01-20:36 反复重建（parent_pid ×10）。租约拦截机制本身工作正常（oas1 未被双开，rest/ws/auto 三源均被拦），但 Core 崩溃循环 + oas2 秒退被 auto 反复拉起 = E1/F1 历史问题的实机复现。重启触发者无法从日志判定 | python.txt 时间戳链（父代理亲验尾部）+ config/ 目录无 oas2.json（父代理亲验） | 已证实（现象），触发者待查 |
| F-12 | **测试运行污染生产日志**：module.logger 无测试隔离，独立测试运行（无账号上下文）写入 `log/2026-08-13_python.txt`。证据链：日志簇含 `XIUXING_HEXUN_FAILURE stage=page reason=unknown page`——该字符串在当前生产模块源码与 pyc 中**均不存在**（父代理字节级验证），仅存在于 tests/test_flow.py:424；`readings=[0,0,41]` 与 test mock `(0,41)` 完全一致；20:29/20:34/20:37 的日志簇 = 父代理与子代理授权的测试实跑。**子代理 E 据此把 20:29 的测试噪声误判为"生产失败循环持续到 20:29"——父代理已纠正**。真正问题：测试不隔离 logger，任何测试运行（含本轮审查自身）都会污染生产日志，干扰日志证据分析 | 父代理字节级/字符串级取证 | 已证实 |
| F-13 | **Bridge→前端事件 WS 无心跳**（只收不发），前端仅 onclose 重连；半开连接需 TCP 超时才恢复。Bridge→Core 方向有 ping 20s，不对称 | 子代理 C 亲读 events.py:11-60 | 高概率 |
| F-14 | **命令 5s 超时后 REST 重发可能双发** start/stop：WS 已送达但回执迟到→REST 兜底再发。Core 状态机大体幂等（stop 无害、start 已运行 changed=False），实际风险低 | 子代理 C 亲读 runtime.py:117-135 | 高概率（机制），影响低 |
| F-15 | **config_model `__setattr__` 每次赋值全量自动 save 未节流**（8-09 C1 写放大未修）；XiuxingHexun 票务 OCR 稳定零确认路径每轮 3+ 次读数也走此路径 | config_model.py:186-199（子代理 B/D 一致，父代理认可） | 已证实 |
| F-16 | **测试与真实 Core 共享账号租约文件**：ScriptProcessLifecycleTest 用真实 'oas1' 账号名，实跑 9 项全部 `AccountLeaseError: account lease held by another Core: oas1`（本机运行中的 Core 持锁）。属环境干扰非代码回归，但测试不 hermetic（子代理 A/B/E 三方独立同结论 + 父代理运行同套件复现） | 三方一致 + 父代理亲跑 | 已证实 |

### 🟢 观察级（文档漂移 / 低危，7 条）

1. **handoff 总表滞后 3 个轮次 ≈2.5 天**：mtime 08-11 10:40 vs 表头标注 08-10（自相矛盾）；对 XiuxingHexun（08-12/13 新模块，已通宵实机运行 82 胜场）**零记录**；§9 "Core、Bridge、前端均运行"已过期（Bridge/前端已停，oas2 被 auto 启动）。
2. **RY-GUILD-001 已结案但 records/closure/ 空目录**——结案记录缺失（04-测试与结案规范.md 要求结案记录唯一代表结案）。
3. **tasks/RY-GUILD-001.md、RR-COMBAT-001.md 任务文件状态句过期**（8-10 方案 vs 8-11 排序协议），ADR-002 状态句滞后。
4. 总表 86 个 markdown 链接全量核查 0 缺失；archive 105 文件全在（子代理 E 逐文件实测）。
5. 测试口径：官方 15 套件静态清点 456 def test_（vs 8-11 声称 444，+12 中 4 个=xiuxing migration 可归因，8 个无法归因）；含 XiuxingHexun 共 520。
6. `TaskEnd.next_run` 载荷被记录但调度器 loop 从不消费（script.py 无引用）——目前仅日志装饰。
7. contracts.md 信封规范（{code,data,request_id}）未被执行（新接口返回裸 dict）；Core/Bridge/前端三层无鉴权（仅 loopback+CORS 本机，与 PRODUCT-001 授权路线未衔接）。

---

## 3. 通过项（🟢 已证实）

**测试**：XiuxingHexun 32/32、config 18/18、批量路由+迁移 47 项、GeneralBattle 116/116、CommonPopup 27/27、GeneralBuff 22/22、Bridge 29/29+3/3、wiring.ps1 9 断言——全部实跑通过（父代理亲跑前两项，子代理交叉其余）。

**XiuxingHexun 新模块（本轮最大变更，质量显著高于历史轮次）**：
- 全链有界：页面 20s/战斗 600s deadline、每步失败即 raise，无 break 尾坠 raise 类 P1 回归（逐 break 排查：仅 :376/380/654/658，均无尾坠）。
- 防误判设计：票数 OCR 带 digit 校验 + O→0 拦截 + 3 采样稳定零确认（不假设递减）；防队友卡（非"自己发现"徽标卡拒开）；失败前保存证据截图。
- 契约合规：TaskEnd.completed 带 statistics、只写自己 next_run、_stop→PRESERVE 不重置失败计数；13 个模板全非黑底（子代理 A 灰度普查）；恢复路径（_resume_active_battle/_recover_existing_result）完整。
- 实机成绩：通宵 82 胜 / 9 败 / 4 次打满上限，06:04 正常收工；失败路径走 INCREMENT 治理（08-12 三连败退出已实机触发）。

**调度/治理**：白名单机制+审计日志落地且 7 个活动调用点全授权；114 处 TaskEnd 全工厂化；空队列干净退出（旧 RequestHumanTakeover 已删）；RealmRaid 自愈路径改走 TaskEnd.failed/deferred 不再绕过失败治理。

**Bridge/前端**：CONTROL-ACK/CONFIG-CONCURRENCY/LAUNCH-WIRING 三项历史声明代码+测试+真 Core 契约三方吻合；前端↔Bridge 契约 16 组调用零失配；前端 XSS 面干净（全 React JSX 无 innerHTML/eval）；启动器 PID+StartTime 双校验不误杀。

**设备层**：RGBA→RGB 通道修复、drag() 字段修正、竖屏回退、设备级识别缓存+失效链、benchmark 契约校验器、死 clamp 删除——本轮设备层 diff 整体收敛。

---

## 4. 待实机（开放边界，与文档一致）

- 绿标：五锚点/红标样本、3/3 门控（当前 detect_only，生产绿标仍是盲点模式——20:09 实机两次 unconfirmed 佐证）。
- DPI 100/125/150%、真实鼠标 before<click<after、真实 ADB、双 MuMu 零串帧。
- 428/409 真实双窗口并发编辑（当前仅单进程离线测试）。
- CommonPopup 分发器实机表现（每帧开销、idle_buff 关键词 OCR 稳定性、F-10 触发概率）。
- GeneralBuff 阈值下调（0.7/0.65）后的误报回归。
- XiuxingHexun：预设链 4 回退的实机命中分布、VICTORY 标题恢复的误匹率、run() 端到端（test_flow 无真机全流程覆盖）。

---

## 5. 子代理核验记录（父代理独立验证清单）

5 份子代理报告约 45 项声称，父代理独立复现验证 **21 项：全部成立，零虚报**；**纠正 1 条误判**（见下）。

| 声称 | 验证方式 | 结论 |
|---|---|---|
| D-N1 BrokenPipeError 崩溃链（🔴） | 父代理亲验 4 个 traceback + script.py:676/script_process.py:404 行号对齐 | ✅ 成立（根因归属维持"高概率"） |
| D-N2 GuildActivityMonitor 热循环 | 亲读 :23-24 | ✅ 成立（潜伏） |
| D-N3 旁路 2 处 | 亲读 MemoryScrolls:124-125 + CollectiveMissions:167 | ✅ 成立 |
| D-N4 Core 反复重建+oas2 秒退 | python.txt 尾部亲验（22 处 oas2 + lease blocked ×3 源） | ✅ 成立（现象级） |
| D: 三连败退出实机触发（08-12 22:56:43） | 08-12 日志亲验 "failed 3 or more"→"Request human takeover"→exit | ✅ 成立 |
| B: match_multi_scale/ROI 污染已修 | 亲读 image.py:271-277 + general_buff.py:92-100 | ✅ 成立 |
| B: nemu_ipc 无锁仍在 | grep Lock/Semaphore/join = 0 命中 | ✅ 成立 |
| B: 绿标黑底模板 | 父代理 PIL 普查：42.0/28.5/36.4% 黑，与 B 数字完全一致 | ✅ 成立 |
| B: 弹窗分发器严格尺寸+capture 能力 | 亲读 dispatcher.py:122-123 + friend_invitation.py:23 | ✅ 成立 |
| A: XiuxingHexunState 死代码 | grep 全文件 0 引用（类定义外） | ✅ 成立 |
| A: PUT 路由无 revision | 亲读 script_router.py:450-455 | ✅ 成立 |
| A: pydantic int/str 警告 | 父代理亲跑测试时亲眼复现（'30'/'25'） | ✅ 成立 |
| A: 9 ERROR 租约污染 | 父代理跑同套件同结论 + 进程表亲验 Core 持锁 | ✅ 成立 |
| C: CONTROL-ACK command_id 协议 | 亲读 runtime.py:117-127 | ✅ 成立 |
| C: Core 侧 PATCH 428/409 | 亲读 script_router.py:394-396 | ✅ 成立 |
| E: 总表 mtime 矛盾 / config 无 oas2.json / Bridge/前端已停 / error 证据停在 06:00 | 亲验 ls -la + netstat + config 目录 | ✅ 成立 |
| E: 86/86 链接存在 | 接受（E 逐文件 os.path.exists 全量扫描） | ✅ 采信 |
| **E: "失败循环持续到 20:29:38"** | **父代理字节级取证：'unknown page' 仅存在于 test_flow.py:424（生产模块源码+pyc 均无）；readings=[0,0,41] 与 test mock (0,41) 一致；20:29 簇 = 测试实跑写入生产日志** | ❌ **不成立（误判）**——E 将测试噪声当作生产失败。真实发现改写为 F-12（测试污染生产日志） |
| B: TaskEnd 114 处全工厂化 | 父代理 grep 裸 raise = 0 | ✅ 成立 |

**交叉验证教训**：E 的误判源于"测试运行会写入生产日志文件"这一隐藏机制（module.logger 无隔离）。父代理通过字符串来源字节级取证（源码+pyc 双重否定）推翻之。**本轮审查自身的测试运行同样污染了生产日志**——后续轮次需注意：跑测试前应记录起点行号，或先停 Core。

---

## 6. 修复优先级建议（供实施方参考，本轮未改任何代码）

1. **F-1（🔴）**：logger 写管道加 OSError 防护 + 优雅关停先排空旧 worker 日志管道；并排查 Core 20:01-20:36 反复重建触发者。
2. **F-2/F-4（治理漏洞）**：GuildActivityMonitor 补 set_next_run 或改 TaskEnd.failed；MemoryScrolls/CollectiveMissions 直接写改走 schedule() 白名单路径（或显式加入授权）。
3. **F-5（绿标）**：重采 3 个黑底模板（42%/28.5%/36.4% 黑——确定性缺陷），把 detect_only 的门槛（五锚点+红标）作为结案条件持续推进。
4. **F-6/F-7（XiuxingHexun）**：O→0 误读场景增加"读 'O' 时回退到搜索按钮状态判断"的辅助证据；考虑 max_challenges 默认保守值或空转上限。
5. **F-9/F-12/F-15/F-16**：PUT 路由补 revision；测试日志隔离（logger 定向临时文件）；__setattr__ 写节流；生命周期测试改用临时账号名/租约目录。
6. **文档链**：总表补 XiuxingHexun 事项（新模块已实机运行 82 胜场但 handoff 零记录）；表头日期修正；RY-GUILD-001 补结案记录；§9 运行状态更新。

---

## 附录：子代理完整报告（原文一字未改）

- annex-A-XiuxingHexun与config层：`handoff/audits/DeepSeek-10-annex-A-XiuxingHexun-config层子代理报告-20260813.txt`
- annex-B-base_task与设备层：`handoff/audits/DeepSeek-10-annex-B-base_task设备层子代理报告-20260813.txt`
- annex-C-control-center：`handoff/audits/DeepSeek-10-annex-C-control-center子代理报告-20260813.txt`
- annex-D-调度器与日志：`handoff/audits/DeepSeek-10-annex-D-调度器日志子代理报告-20260813.txt`
- annex-E-文档链与测试：`handoff/audits/DeepSeek-10-annex-E-文档链测试子代理报告-20260813.txt`
