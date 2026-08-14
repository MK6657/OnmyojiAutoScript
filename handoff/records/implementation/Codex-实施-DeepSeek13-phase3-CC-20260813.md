# Codex-实施-DeepSeek13-phase3-CC-20260813

> DeepSeek-13 修复轮 Phase 3（coordinate-calibrator 3.1-3.21）实施记录。3.1/3.2 核心由父代理实施，3.2f/3.3-3.21 由批量子代理实施（原文见 audits/DeepSeek-13-annex-CC批量子代理报告-20260813.txt）。

| # | 事项 | 关键改动 | 验证 |
|---|---|---|---|
| 3.1 | F1 阻断 mark_artifact_damaged CHECK 违规 | repository.py 改标合法态 delete_pending（零迁移）；runtime.py reconcile 单工件 try/except + restore_quarantine 补偿 | py_compile；新增 damaged-ready repairs 路径测试 |
| 3.2 | R-6 租约乒乓三因 | repository 同 owner 活租约原样返回（去自顶替）；heartbeat TTL 30→60；前端 ttl 60 + 指数退避（5s→60s）+ CONTROL_LEASE_MS 60 | py_compile + node --check；新增同 owner 幂等与 TTL 测试 |
| 3.2f | access log 时间戳 | uvicorn_log_config 接入 app.py main() 与 server.py | 模块导入 OK |
| 3.3-3.21 | F2-F19 + 文档漂移 + 测试 | 见 annex 逐项 | CC 全量 149/149 OK（26.1s）+ JS 检查全过 |

## 关键验收

- CC 全量套件 149/149（原 146 + 新增 3：damaged-ready repairs、同 owner acquire、heartbeat TTL 60）。
- F1 阻断：maintenance quarantine 在受损工件场景不再 IntegrityError 中断，先移后写有回滚补偿。
- R-6：三因（同 owner 顶替、TTL/心跳失配、无退避）全部收口；量化验收（双标签并发 30min ≤10 次 423）待实机浏览器场景。

## 回滚点

D:\coordinate-calibrator\backups\pre-fix-20260813-230741\。

## 待实测

- 双标签并发 30 分钟租约乒乓复测（浏览器端）；quarantine-gc 生产磁盘回收；bundle to_thread 的压测；DPI fail-closed 的实机 mouse_capture 显示。