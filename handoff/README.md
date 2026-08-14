# MK6657 二次开发交接入口

项目根目录：`D:\OSAyys`

2026-08-14 已完成交接清理。新开发者应先阅读 [交接清理与接手说明](HANDOFF-CLEANUP-20260814.md) 和 [当前状态](00-当前状态.md)。源码仓库不包含虚拟环境、Node 依赖、本机账号配置、运行数据库、完整连续帧、历史内部备份或发布二进制；这些内容有明确的重建方法或所有者侧归档。

这是基于 OnmyojiAutoScript 上游代码维护的 MK6657 二次开发分支。上游代码用于复用和对照，实际流程以用户实测反馈和双方确认的规则为准。

## 当前追踪入口

当前未完成事项、优先级、时效、依赖和下一步统一看 [Codex-待做事项总表.md](Codex-待做事项总表.md)。编号为 `Codex-*` 或 `DeepSeek-*` 的其他文档是历史审计、一次实施记录或一次实测证据，不作为当前待办清单。

> 跨轮问题编号约定（DeepSeek-13 4.9）：DeepSeek-09 与 DeepSeek-10 的 F-x 编号含义不同（如 09 F1=CC 工件损坏、10 F1=BrokenPipe；09 F16=租约乒乓、10 F16=测试租约冲突）。引用时必须带轮次前缀（例：DS-09 F16、DS-11 R-6），不得裸写 F-x。

旧版扁平文档已经移入 [历史归档](archive/README.md)。根目录只保留当前状态、运行规范、任务生命周期、测试规范、待办总表和坐标清单；历史文件可按原文件名和 SHA-256 追溯。

最新只读审计是 [2026-08-13 DeepSeek-12 记录体系审查](audits/DeepSeek-12-记录体系审查-20260813.md)（前序：[DeepSeek-11 根因定位审查](audits/DeepSeek-11-根因定位审查-20260813.md) + [复验结论](audits/DeepSeek-11-复验结论-20260813.md)、[DeepSeek-10 OAS 全项目审查](audits/DeepSeek-10-OSAyys全项目只读审查-20260813.md)（头部有 errata）、[DeepSeek-09 CC 审查](audits/DeepSeek-09-coordinate-calibrator-v0.3.8只读审查-20260813.md)（头部有 errata）、[2026-08-10 P0/P1 复核审计](audits/Codex-双项目P0P1复核审计-20260810.md)）。DeepSeek-13 修复轮（2026-08-13 晚）正在执行，实施记录见 records/implementation/Codex-实施-DeepSeek13-*.md。

最新寮突破证据为 [自动选寮完整链路实测](records/evidence/Codex-实测-RY-GUILD-FULL-20260811-01.md) 和 [阵容锁定/准备页边界实测](records/evidence/Codex-实测-RY-LOCK-BOUNDARY-20260811-01.md)；对应实现见 [排序验证与固定首卡选择修复](records/implementation/Codex-RY-GUILD排序验证与固定首卡选择修复-20260811.md)。

当前离线基线为 coordinate-calibrator `0.3.8 / schema 6 / 149/149`（DS-13 修复轮新增 3 测试后实测）、OAS 全量 85 个测试模块 `491/491`（08-13 晚 unittest 实测，含 Bridge 套件）、wiring `15/15`（08-14 00:13 服务在线实测）。控制面、checkpoint、任务结果、页面所有权、探索边界、弹窗 deadline、绿标颜色槽位诊断链和当前寮突破排序协议已实施；真实设备、真实弹窗、绿标靶场和长程业务仍按待办补证。

文档流转约定：

- 实测反馈只记录事实、日志、截图、结果和根因，不覆盖旧记录。
- 实施记录只记录代码改动、离线验证和回滚点，不等于实机结案。
- 只有满足验收标准后才建立结案记录，并在待做事项总表中标记 `已结案`。
- 游戏规则或失败语义未确认时，先标记 `待确认`，不直接改代码。

## 当前链路

```text
control-center/frontend       唯一 React/Vite 前端源码，首选端口 4175（本机自动顺延到 4212）
control-center/bridge         Bridge 适配层，正式端口 22367
control-center/desktop        Electron 壳与 portable 构建
server.py / module / tasks    OAS Core 与任务实现，端口 22267
```

浏览器开发、隔离测试和 Electron 都使用同一份 `control-center/frontend`。旧 `UI-claude` 与 `frontend-preview` 路径只会出现在历史记录中，不再是运行入口。

## 当前文档层

以下文件是当前环境和规则的优先入口：

- 00-当前状态.md：本机服务、账号、窗口、版本和开放阻塞。
- 01-运行与停止.md：真实环境、隔离环境、停止和单实例门禁。
- 02-配置与数据归属.md：Core、Bridge、前端、日志和坐标工具的写入边界。
- 03-任务生命周期.md：调度器、任务实例和 TaskEnd/next_run。
- 04-测试与结案规范.md：测试证据和结案规则。
- tasks：当前业务事项规格。
- records：实施、实测和结案记录。
- decisions：用户确认和架构决策。
- ../control-center/docs/contracts.md：Bridge REST/WebSocket 契约。
- contracts/v1：OAS 与 coordinate-calibrator 的只读中立证据契约。
- coordinates-to-calibrate-20260809.md：集中管理待标定的按钮、ROI、设备画布和验收样本。

旧编号文档保留历史证据；发生冲突时，优先顺序为当前源码和运行日志、当前状态快照、待做事项总表、最新实测记录、历史审计。

## 建议阅读顺序

1. `Codex-待做事项总表.md`：当前唯一开放事项和执行顺序。
2. `audits/DeepSeek-12-记录体系审查-20260813.md` 及 `audits/DeepSeek-11-根因定位审查-20260813.md`：最新审查与根因结论（其前序 DeepSeek-09/10 头部已附 errata）。
3. `audits/Codex-双项目P0P1复核审计-20260810.md`：P0/P1 代码、运行和证据边界复核。
4. `00-当前状态.md`：当前机器服务、窗口、设备和数据快照。
5. 以下 5-16 项历史文档均已归档到 `archive/legacy-root-20260811/`（原名不变）：
   `Codex-README.md`、`Codex-01`、`Codex-02`、`Codex-03`、`Codex-05`、`Codex-15`、`Codex-42`、`Codex-44`、`Codex-49`、`Codex-51`、`Codex-52`、`Codex-实测-RY-GUILD-001-20260807-01`、`Codex-55`。
17. `records/implementation/Codex-OAS战斗终态与任务结束语义修复-20260809.md`：BattleOutcome、TaskEnd、绿标结果与失败调度。
18. `records/implementation/Codex-EXP探索硬边界与加成恢复修复-20260809.md`：探索预算、加成恢复和候补启动识别。
19. `records/evidence/Codex-实测-EXP-028-20260809-01.md`：3/10 场通过及 30 场未通过的现场证据。
20. `records/implementation/Codex-跨项目中立证据契约-v1-20260809.md`：Device/Frame/Candidate/Evidence 契约边界。
21. `records/implementation/Codex-通用弹窗分发器与双门卫迁移-20260809.md`：全局覆盖弹窗的优先级分发、双处理器、证据和离线边界。
22. `records/implementation/Codex-通用加成弹窗按任务意图选择与防穿透修复-20260810.md`：按任务配置选择确认或取消，以及关闭动画点击穿透修复。
23. `records/evidence/Codex-实测-COMMON-POPUP-20260810-02-取消分支.md`：取消分支真实命中、点击穿透现场和重新验证条件。
24. `records/implementation/Codex-双项目P0P1分阶段修复实施记录-20260810.md`：本轮控制面、数据、安全、采集和绿标诊断实施与回滚边界。
25. `records/evidence/Codex-实测-RR-LOCK-GREEN-20260810-03.md`：阵容锁定第二轮通过、左三绿标漏采根因和逐帧证据。
26. `records/implementation/Codex-绿标快速稳定帧采样与锁定转场去重修复-20260810.md`：绿标确认窗口快速受保护取帧、自动模式复用和锁定日志去重。
27. `records/evidence/Codex-实测-RR-GREEN-FAST-SAMPLE-20260810-04.md`：修复后左三绿标 `2/2` 结构化确认、阵容锁定日志去重和两票预算实测。

## 常用入口

```powershell
# 日常真实环境
.\control-center\start.ps1

# 无游戏隔离联调
.\control-center\launcher\start-dev-stack.ps1

# portable 构建
Set-Location .\control-center\desktop
.\build.ps1
```

历史编号文档保留当时路径和验证事实，不应把其中的旧路径当作当前入口。

## 文档维护

```powershell
# 检查 handoff 内所有本地 Markdown 链接
.\handoff\tools\test-markdown-links.ps1

# 预览以后新增的根目录历史文件归档
.\handoff\tools\archive-root-history.ps1 -WhatIf

# 预览 OAS 可再生成的 Python 缓存
.\dev_tools\cleanup-generated-caches.ps1 -WhatIf
```

归档和清理脚本均先校验项目根目录、目标边界和 reparse point；默认使用 `-WhatIf` 预览后再执行。
