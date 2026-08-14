# DeepSeek-12 评分与后端修复验收基线（2026-08-13）

> 用途：记录 DeepSeek-11 复验与 DeepSeek-12 记录体系审查的独立评分、已确认偏差，以及后续后端修复的验收口径。
> 本记录不代表修复，不修改任何业务代码、配置或运行状态。

## 1. 当前评分

- DeepSeek-11 独立复验：89/100。
- DeepSeek-12 记录体系审查：82/100。
- 综合评分：85/100。

## 2. 已确认的主要偏差

1. DeepSeek-12 H6 结论错误。`Codex-实测-GREEN-TARGET-RANGE-20260810-02.md` 已明确记录五槽各 `10/10`、合计 `50/50 confirmed`，并保存独立 `samples.jsonl` 哈希。coordinate-calibrator 数据库 `samples=0` 属于另一套鼠标标注数据，不能否定 OAS 的实测证据。真实问题是其余根文档没有同步这项完成事实。
2. 租约日志已证明 `heartbeat 423 -> 同连接 acquire 200 -> lease 被替换`，但缺历史 `owner_id`、准确服务端时间戳和客户端标签现场，尚不能把“多标签 + 后台节流”定为唯一已证实根因。
3. 测试数字 `456/488/520` 尚未统一。静态 `def test_` 数量不能直接作为实际通过项数，后续必须保存明确的测试命令、发现范围和实际 runner 汇总。
4. BrokenPipe 孤儿 worker 机制成立；具体五次 Core 重启是否全部由 `重启Core.bat` 触发仍缺直接命令历史，应把机制与触发者置信度分开。
5. “60 张错误截图”不成立，实际为每个失败事件 1 张 PNG；OCR 原文 `O/0` 没有直接日志，只能保持高概率。
6. “无虚报”应改为“未发现核心根因伪造，但存在统计、表述和置信度错误”。

## 3. OSAyys 后端现状基线

### 3.1 Core 与 worker 生命周期

- `control-center/start.ps1` 的 Core 重启仍直接执行 `Stop-Process -Force`。
- `/kill_server` 会设置 `MainManager.signal_kill_server`；监控线程尝试停止全部 worker 后，以 `SIGILL` 结束 Core 进程。后续修复不能只把一个强杀替换成另一个强杀，必须先确认 worker 全部退出、IPC 关闭、账号租约释放，再结束 Core。
- worker 的信号处理器先写日志再关闭 `log_pipe_in`；断管时该日志写入本身可能失败。
- `set_func_logger(log_pipe_in.send)` 没有 BrokenPipeError/OSError 降级策略，管道 handler 失败会向业务调用栈传播。

### 3.2 失败计数与调度

- `Script.failure_record` 仅在 worker 内存中，worker 重启后清空。
- 失败计数按任务名分键；`GotoMain` 成功只重置自己的键，这一点无需修改。
- `sync_next_run` 同时提交 `success=True` 和调用方 `target_dt`；`Config.task_delay()` 最终取所有候选时间的最小值。真正覆盖失败延时的是立即 `target`，不是单独的 `success=True`。
- `MemoryScrolls` 和 `CollectiveMissions` 仍直接修改其他任务调度字段，绕过统一 schedule 契约与审计。

### 3.3 配置并发与日志隔离

- PATCH 配置接口已有调用方 revision 门禁；普通任务的旧 PUT 单值接口仍直接保存，没有调用方 revision/CAS 保护。
- `module.logger` 导入时立即创建按 `argv[0]` 命名的生产日志并写 START 横幅，测试进程会污染 `python.txt`。

### 3.4 修行合训安全边界

- 空 OCR、低置信 OCR、字母 `O` 均不得作为无票证据。
- 只有明确数字 `0` 且活动页锚点稳定、连续读取一致、没有“自己发现”卡片时，才允许正常完成。
- 连续 N 次 `None` 不能转换成耗尽；无法确认必须失败并保留证据。

## 4. coordinate-calibrator 后端现状基线

### 4.1 工件修复事务

- `artifacts.state` CHECK 仅允许 `staging/ready/delete_pending`，但 `mark_artifact_damaged()` 写入 `damaged`。
- damaged-ready 修复路径先把文件移入 quarantine，再写数据库；数据库失败时没有对应的文件恢复补偿，且首个异常会中断后续工件处理。
- 孤儿文件 quarantine 测试不能替代 damaged-ready 路径测试。

### 4.2 会话租约

- heartbeat 固定续期 30 秒。
- heartbeat 失败后客户端立即重新 acquire。
- 同 owner acquire 会无条件生成新 lease_id 并提升 fencing_token；旧 lease 随即失效。
- 当前访问日志没有时间戳，数据库没有保留可用于复盘的租约 owner 历史，因此现阶段只能确认循环机制，不能确认唯一客户端拓扑根因。

## 5. 后续后端修复验收标准（100 分）

### A. Core 生命周期与断管防护（20 分）

- 重启流程先请求并确认全部 worker 停止，再结束 Core；超时回退不会遗留孤儿 worker。
- worker/日志 handler 遇到 BrokenPipeError、EOFError、OSError 时移除失效管道 handler，继续写本地日志或安全退出。
- 有正常退出、超时、terminate 失败、kill 失败、断管后日志等自动化测试。

### B. 失败计数与调度权威（20 分）

- 失败计数跨 worker 重启保存，按账号和任务隔离，成功才重置对应任务。
- `sync_next_run` 明确调用方权限、目标时间和已有失败延时的覆盖规则，不能用表面删除 `success=True` 代替修复。
- 所有跨任务调度写入进入统一授权、审计和冲突处理路径。

### C. 配置并发与日志隔离（15 分）

- PATCH 与旧 PUT 均具备一致的调用方 revision/CAS 语义，陈旧写返回冲突且不部分保存。
- 测试日志默认写隔离目录或内存 handler，不再污染生产 `python.txt`。

### D. 修行合训失败关闭（10 分）

- `None/O/空值/低分` 不会触发耗尽；明确 `0` 需要稳定、多证据确认。
- 搜寻、自己发现卡片和无票三条分支有独立回归测试。

### E. 校准器工件事务（15 分）

- schema 与状态机一致；旧数据库有明确迁移或兼容策略。
- 文件移动与数据库状态更新具有补偿，单工件失败不会造成文件/DB 分裂，也不会静默中断全部 reconcile。
- damaged-ready 的成功、DB 失败、文件恢复失败和重复执行均有测试。

### F. 校准器租约契约（15 分）

- 服务端定义续期、过期、同 owner 重入和 fencing 语义，避免每次恢复都无条件替换 lease。
- 服务端具备足够的 owner/lease/时间可观测性；客户端重试有退避且不会形成 423/200 自持续循环。
- 覆盖同 owner、多 owner、过期、后台恢复、并发 acquire/heartbeat 的测试。

### G. 证据与回归质量（5 分）

- 给出可复现测试命令、实际 runner 汇总和失败路径证据；不再混用静态测试函数数量与通过项数。

## 6. 当前文件哈希基线

### OSAyys

- `control-center/start.ps1`: `5AFE3926CC3AF977223135012F7C38BD55A85F27B5B4AE3A52901F353B749928`
- `module/server/script_process.py`: `F66238B69A689C95B25CADF85F1EA872AE4BBBB2B60463B930B9437118697891`
- `module/logger.py`: `5EC51EDB235B655BDFDD052A8A4388FC306AD2077E6EC99C2CA1931E561D1BFC`
- `script.py`: `EA45022024EE9A92B4B69C50A858014B9FF05E0C3B65882DFE7EAE63FBAAB4F7`
- `module/config/config.py`: `228141DF1E7462EB8B139EC403016F305080EDE89118ACEB6D2EFD749217D331`
- `module/server/script_router.py`: `579C65E8B8F816E952B15C73E337711ED51AB2111E36C4E8A59B5C41C9DFFDC6`
- `tasks/XiuxingHexun/script_task.py`: `3C748D885D939D3000DFDAF4BF975B39A4CFCD0B6D1F5574725611DECC14EFCA`

### coordinate-calibrator

- `storage/repository.py`: `CAC101E3F2A8065B38ACCBF7FC6CC4B21C68F0009A3EB4D55942A0C5CC6CD05F`
- `api/runtime.py`: `87D2FED187A8C960212174783A2AADBD832F4D0E1B7236284173EC45DB6A2FC2`
- `api/app.py`: `FD6F4AC2874F2D6B17CA034B17C7C22AFD4C5454FF9925D5684EC21C39C2215E`
- `web/app.js`: `8E81BA08E476955DCCA7E4E7E2B0F4ADB3C9AEB10B34F0EA8ACA82B93430A38C`

## 7. 后续审查流程

1. 比较上述文件及新增测试的实际差异，不按修复者的摘要代替代码审查。
2. 逐条验证根因是否消除，重点检查失败路径和并发路径。
3. 运行与变更范围匹配的定向测试、完整回归和必要的隔离集成测试。
4. 检查生产配置、日志和已有标注档案未被测试污染或覆盖。
5. 按第 5 节评分，并单列仍需实机验证的残余风险。
