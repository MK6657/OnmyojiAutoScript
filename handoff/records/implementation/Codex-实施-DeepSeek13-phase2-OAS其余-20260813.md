# Codex-实施-DeepSeek13-phase2-OAS其余-20260813

> DeepSeek-13 修复轮 Phase 2（OAS 其余修复 2.1-2.10）实施记录。停服状态。

| # | 事项 | 文件 | 改动 | 验证 |
|---|---|---|---|---|
| 2.1 | R-4 耗尽判定 + F-7 | tasks/XiuxingHexun/script_task.py _confirm_empty_after_search + config.py | count=None 连续 ≥3 帧稳定（home/search 可见、无 own-card）→ 判耗尽（显式 WARNING 标记）；max_challenges 默认 0→50（生产 oas1.json 保持 0，待用户确认） | test_flow 33/33（含新增） |
| 2.2 | F-9 PUT 路由 revision 门禁 | module/server/script_router.py + control-center/bridge/app/core_client.py | 非 xiuxing 分支要求 If-Match（428 缺/409 陈旧）；bridge set_value 先取 config_revision 再带 If-Match | py_compile OK |
| 2.3 | F-13 事件 WS 心跳 | bridge/app/events.py + frontend/src/api.js | EventHub 30s bridge.ping 心跳 + 断开回收 task；前端忽略 ping 帧 | py_compile OK |
| 2.4 | F-14 命令重发幂等 | bridge/app/runtime.py + main.py | command 超时保留 future（60s 宽限期）；新增 wait_last_command_result；REST 兜底前等 2s 采用迟到回执 | py_compile OK |
| 2.5 | F-10 CommonPopup | friend_invitation.py | required_deadline_capabilities ('capture',)→()（身份指纹任何截图方式可用；尺寸契约保持 fail-closed——项目自有测试 enshrined，F-10 中 BLOCKED→重启链经查为 10 轮误读，BLOCKED 仅生成报告不 raise） | test_dispatcher 27/27 OK |
| 2.6 | F-8 恢复判定 | tasks/XiuxingHexun/script_task.py | _recover_existing_result 加第二帧稳定证据，不稳定拒记 recovered VICTORY | 新增 test_explicit_result_recovery_rejects_unstable_title；flow 33/33 |
| 2.7 | nemu_ipc 超时线程残留 | module/device/method/nemu_ipc.py | run_in_executor（超时线程泄漏）改单工作线程 queue 串行（每实例至多 1 线程，超时调用后台完成、下个调用排队） | py_compile OK |
| 2.8 | TaskEnd.next_run 消费 | script.py | 调度循环将 result.next_run 经 schedule() 写回（caller=Script.run） | py_compile OK |
| 2.9 | contracts 信封 | —— | 不实施，立 OAS-CONTRACT-ENV-001 P3 | —— |
| 2.10 | F-15 写放大 | module/config/config_model.py | __setattr__ 改 0.5s debounce（threading.Timer 合并保存） | py_compile OK |

## 离线测试结果

- CommonPopup test_dispatcher 27/27 OK；XiuxingHexun test_flow 33/33 OK（新增 1 项）。
- 生产日志零污染（4624 行不变）。

## 回滚点

D:\OSAyys\backups\pre-fix-20260813-230741\。

## 待实测（Phase 5）

- R-4 新 None-streak 判定的实机命中分布；2.3/2.4 半开连接与双发实测；max_challenges 默认值用户确认。