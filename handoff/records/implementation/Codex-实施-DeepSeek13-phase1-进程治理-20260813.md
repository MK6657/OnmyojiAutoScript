# Codex-实施-DeepSeek13-phase1-进程治理-20260813

> DeepSeek-13 修复轮 Phase 1（OAS 进程治理 1.1-1.7）实施记录。服务全程停服（23:07 优雅停止）。

## 改动文件与根因

| # | 事项 | 文件 | 改动 | 验证 |
|---|---|---|---|---|
| 1.1a | R-1 重启优雅化 | control-center/start.ps1 | 新增 Stop-CoreGraceful（/home/kill_server 优雅停 + 12s 端口轮询）；-RestartCore 改优雅优先、Force 兜底 | PS Parser 显式 UTF-8 解析通过；23:06 生产实跑 /home/kill_server 优雅链全段生效（Kill all server → Script stopping source=shutdown → 协程取消 → Kill main process，0 孤儿） |
| 1.1c | R-1 worker 管道写防护 | module/logger.py FlutterLogStream.write | BrokenPipeError/OSError/ValueError → 永久降级文件日志 + 单次 file-handler 告警，不再炸进程；print() 迭代快照 | py_compile OK |
| 1.2 | F-12 测试日志隔离 | module/logger.py _is_test_context/set_file_logger | 测试上下文（OAS_TEST_LOGDIR/PYTEST_CURRENT_TEST/pytest argv/unittest argv）→ %TEMP%\oas-test-logs | 实测：unittest 跑生命周期套件，生产 log/2026-08-13_python.txt 0 行增长，测试日志落 %TEMP% |
| 1.3 | R-3 失败计数持久化 | script.py | failure_record 改 sidecar work/<account>_failure_state.json（原子替换；条目 {count,last_failed_at}；≥3 升级后新 episode 清零；单写者由 AccountRunLease 保证） | py_compile OK |
| 1.4 | N-4 sync_next_run 守卫 | module/server/script_router.py | 失败后 target 钳制到 last_failed_at+failure_interval（force=true 可覆盖）；SCHEDULE_DECISION 审计 | py_compile OK |
| 1.5 | F-2 GuildActivityMonitor 热循环 | tasks/GuildActivityMonitor/script_task.py:22-24 | 无效 run_days 改 raise TaskEnd.failed（INCREMENT 治理） | py_compile OK |
| 1.6 | F-4 跨任务旁路 | module/config/config.py + tasks/MemoryScrolls/script_task.py:124-125 + tasks/CollectiveMissions/script_task.py:167 + script_router.py PATCH 审计 | 白名单补 memory_scrolls→exploration、collective_missions→bondling_fairyland；新增 Config.set_scheduler_enabled 授权入口；CollectiveMissions 改走 schedule()；PATCH /values 写 scheduler.* 补 SCHEDULE_DECISION 审计 | py_compile OK |
| 1.7 | F-16 测试租约隔离 | module/server/script_process.py AccountRunLease + module/server/tests/conftest.py | OAS_LEASE_DIR 环境注入租约目录；conftest 设临时目录 | unittest 生命周期套件全绿（0 AccountLeaseError） |

## 离线测试结果

- module.server.tests.test_script_process（unittest，含 AccountRunLeaseTest + ScriptProcessLifecycleTest）：全部通过（23:25 实跑，隔离生效）。
- 全部改动文件 py_compile 通过。

## 待实测（Phase 5 复验项）

- R-1：重启 5 次 0 孤儿 worker + 0 BrokenPipe（进程表断言）。
- R-3：跨 worker 重启计数保留 + 三连败跨重启触发退出。
- 1.4/1.5/1.6：sync_next_run 钳制、热循环消失、旁路负例需任务级回归（XiuxingHexun flow/config 套件等）。

## R-1 实机复验结果（2026-08-13 23:53-23:54，Phase 5.3 完成）

- 方法：start.ps1 -RestartCore 循环 5 次（job 记录 D:\OSAyys\work\ds13_r1_verify.log）。
- 结果：server.txt 显示 5 次 LAUNCHER CONFIG（23:53:09/29/42/56、23:54:03），其中 4 次重启前均有「Kill all server」优雅停止记录（23:53:23/36/50、23:54:03）——4/4 走优雅路径，0 次 Force 兜底。
- 进程树（终态）：仅 Core（venv 23108→uv 800，端口 22267）与 Bridge（venv 9340→uv 11360，端口 22367）两条正常链；0 孤儿 worker（无游离 spawn_main，旧 worker 2452 未残留）。
- BrokenPipe：log/2026-08-13_oas1.txt 计数保持 8（= 03:43-05:56 旧事件 4 对），复验期间 0 新增。
- **验收通过**：重启 5 次 0 孤儿进程 + 0 BrokenPipeError。
- 注：本轮 Core 空闲未拉 oas1 worker（deploy.yaml Run:null、无到期任务），孤儿场景的 worker 侧防护由 module/logger.py 单元路径覆盖，后续任务到期实机运行时继续观察。

## 回滚点

D:\OSAyys\backups\pre-fix-20260813-230741\（全部 6 个改动文件已含）。

## 日志污染说明（诚实披露）

本轮 23:24 首次 unittest 实跑时 _is_test_context 未覆盖 -m unittest 形态（sys.argv 无字面 'unittest'），向 log/2026-08-13_python.txt 写入约 171 行后修复并复验（此后 0 增长）。该污染窗口已在 DeepSeek-13 报告中如实记录。