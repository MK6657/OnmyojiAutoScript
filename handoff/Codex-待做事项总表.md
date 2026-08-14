# Codex 待做事项总表与文档流转规范

最后更新：2026-08-13（DeepSeek-13 修复轮前置补记；修复完成后再统一重写）
项目：MK6657 二次开发分支
分支：`codex/mk6657-secondary-development`

## 1. 这份文件的作用

这是当前项目唯一的开放事项总表。它回答“现在还有什么没做、为什么没做、下一步做什么、什么条件下可以结案”。

历史审计、实施记录和实测反馈不在这里重写；它们只作为证据被引用。旧文档里出现的“已完成”“下一步”“建议修复”不能直接改变本表状态，必须以当前源码、最新实测和本表为准。

本表不记录原始长日志。日志、截图、调用链和完整测试过程放在关联文档中，本表只保留可执行的摘要。

**范围声明（DeepSeek-13 4.1 增补）**：本表覆盖双项目口径——OAS（MK6657 二开分支）全量事项 + 双项目审计产生的 coordinate-calibrator 事项（§4.8 先例）+ 影响 OAS 验收的 CC 事项；纯 CC 内部治理项以指针式登记（一行指向 D:\coordinate-calibrator 自身 docs/工作日志）。

## 2. 状态定义

| 状态 | 含义 |
|---|---|
| `待确认` | 业务规则、游戏语义或用户选择尚未确定，暂不改代码。 |
| `待排期` | 需求已明确，但尚未进入当前开发批次。 |
| `待设计` | 已知需要方案，接口、状态机或流程还没有定稿。 |
| `待修复` | 实测已经证明现有行为不正确，等待代码修复。 |
| `实施中` | 正在修改代码或补测试。 |
| `待实测` | 代码已有变化或离线验证通过，尚缺真实游戏证据。 |
| `实测中` | 已启动当前事项的真实环境验证，结果尚未收束。 |
| `部分通过` | 主链路通过，但边界、性能或另一种模式仍未通过。 |
| `暂缓` | 需求保留，但按用户安排或依赖关系暂不推进。 |
| `已结案` | 验收标准全部满足，且有可追溯结案证据。 |
| `已取消` | 明确决定不再实现。 |

“已实施”不是最终状态。代码改完但没有实机验证时，必须写成“待实测”或“部分通过”。

## 3. 优先级和时效

优先级与时效分开判断，执行顺序为：

`当前测试窗口阻塞` -> `P0` -> `当前窗口内的 P1` -> `其他 P1` -> `P2` -> `P3`

| 优先级 | 判定标准 |
|---|---|
| `P0` | 错误目标、假成功、进度/奖励错误、可能误操作关键页面、无法安全停止或会影响后续任务。 |
| `P1` | 核心流程无法闭环、频繁卡住、需要人工介入，或当前正在测试的功能必须依赖它。 |
| `P2` | 性能、兼容性、边界和通用化缺口，有稳定绕行方式。 |
| `P3` | 架构债务、界面体验、发布包装和长期治理，不阻塞当前实机功能。 |

时效使用 `立即`、`本轮`、`晚上 21:00 后`、`近期`、`长期`、`暂缓`。例如寮突破只能在晚上测试，因此“自动选择最高勋章寮”虽不是调度器故障，仍属于当前窗口的 P0/P1 事项，排在普通性能优化前。

## 4. 当前开放事项

### 4.1 当前窗口优先事项

| ID | 领域 / 事项 | 状态 | 优先级 | 时效 | 下一步 | 依赖 | 验收标准 | 最新证据 |
|---|---|---|---|---|---|---|---|---|
| `RY-GUILD-001` | 寮突破未选寮时选择勋章最高目标 | `当前排序协议已结案，跨游戏日二次通过` | `P0` | 仅在重新打开条件出现时复测 | 已按真实 UI 实现“观察一端、切换对端、恢复并验证降序、点击第一行”；两次独立实测均验证最高 `241`、最低 `57` 并进入棋盘，第二次为游戏日刷新后的新帧 | 当前 `1280x720` 右侧四行排序布局；自动选寮默认关闭 | 降序/升序均单调且方向相反；最终降序与记录一致；点击第一行后进入棋盘；OCR/排序异常时不点击 | [游戏日刷新后二次实测](records/evidence/Codex-实测-RY-GUILD-DAY2-20260811-02.md)、[首次完整链路](records/evidence/Codex-实测-RY-GUILD-FULL-20260811-01.md)、[实施记录](records/implementation/Codex-RY-GUILD排序验证与固定首卡选择修复-20260811.md) |
| `RY-GUILD-002` | 寮突破失败箭头的游戏语义 | `待确认` | `P0` | 明晚单步 | 观察失败箭头目标是否允许继续挑战，只记录现场，不先改分支 | 用户/游戏实际规则 | 形成唯一规则：可继续或不可继续，并有截图/日志证据 | [Codex-40](archive/legacy-root-20260811/Codex-40-阴阳寮突破继续测试与失败箭头核对记录-20260806.md) |
| `RR-COMBAT-001` | 个人突破真实战斗/奖励误判/启动场景边界 | `业务多场通过，绿标快速采样 2/2` | `P0` | 扩大到 3 次新进攻，再决定是否执行 10 场 | 启动门禁、预设、自动、结果/回板和锁定闭环均通过；最新票数 `5→3`，两胜一负，失败不耗票；两次绿标均结构化确认 | 错误页面不串线、不误点击、不重启；真实战斗未结束时不处理奖励；绿标检测与业务胜利分别统计 | [修复后实测](records/evidence/Codex-实测-RR-GREEN-FAST-SAMPLE-20260810-04.md)、[漏采根因](records/evidence/Codex-实测-RR-LOCK-GREEN-20260810-03.md)、[启动场景实测](archive/legacy-root-20260811/Codex-实测-RR-COMBAT-001-20260807-04-启动场景门禁.md) |

### 4.2 寮突破

| ID | 事项 | 状态 | 优先级 | 时效 | 下一步 / 依赖 | 验收标准 | 最新证据 |
|---|---|---|---|---|---|---|---|
| `RY-GUILD-003` | 从选寮到“完成且无可攻击目标”的完整闭环 | `选寮入板与两场通过，终局待实测` | `P1` | `RY-GUILD-002` 后 | 当前已完成选寮、入板、两场胜利和回板；下一步观察失败箭头，再补无可攻击目标、票耗尽和清空终局 | 页面明确完成、无可攻击目标、预设/御魂/自动战斗/回板均有证据 | [本轮完整链路](records/evidence/Codex-实测-RY-GUILD-FULL-20260811-01.md)、[Codex-39](archive/legacy-root-20260811/Codex-39-寮突破50场长程闭环测试与调度停用记录-20260806.md)、[Codex-40](archive/legacy-root-20260811/Codex-40-阴阳寮突破继续测试与失败箭头核对记录-20260806.md) |
| `RY-GUILD-004` | 寮突破 `green_left3` 目标映射和点击确认 | `点击通过，确认未通过` | `P1` | 绿标标定窗口 | 本轮点击 `(652,369)` 位于左三；旧模板最高分 `0.702876`，HSV 仅作诊断。用户稍后用 coordinate-calibrator 辅助标定左三及五个互斥头部确认区并补验证集 | 目标式神位置正确；确认器零跨目标误确认；失败最多走有限兜底 | [本轮实测](records/evidence/Codex-实测-RYOU-LOCK-GREEN-20260810-01.md)、[靶场证据](records/evidence/Codex-实测-GREEN-TARGET-RANGE-20260809-01.md) |
| `RY-GUILD-005` | 寮突破预设、御魂、锁定和战后准备状态 | `视觉锁定通过，当前仍需准备` | `P1` | 后续寮突破窗口 | 当前实机证明锁定动作切换成功后连续三场仍出现准备页；现已改为只切换一次并使用有限准备兜底，继续补预设/御魂独立生效与异常退出 | 不重复盲点锁定；真实准备页有限处理；加载页不误判；预设/御魂真实生效；异常时安全退出 | [边界实测](records/evidence/Codex-实测-RY-LOCK-BOUNDARY-20260811-01.md)、[本轮实施](records/implementation/Codex-RY-GUILD排序验证与固定首卡选择修复-20260811.md) |

### 4.3 个人结界突破 RealmRaid

| ID | 事项 | 状态 | 优先级 | 时效 | 下一步 / 依赖 | 验收标准 | 最新证据 |
|---|---|---|---|---|---|---|---|
| `RR-COMBAT-002` | 通用战斗手动 -> 自动真实切换 | `部分通过` | `P1` | 近期 | 本轮真实个人突破已从手动经 ADB 兜底确认自动；再补一场已是自动状态，确认不重复点击 | 手动只点击一次并确认自动；自动状态不重复点击；两种状态都有日志 | [个人突破单场复测](archive/legacy-root-20260811/Codex-实测-RR-COMBAT-001-20260807-05-个人突破单场复测.md)、[Codex-44](archive/legacy-root-20260811/Codex-44-通用战斗自动模式兜底修复-20260806.md) |
| `RR-LEVEL-001` | 升级、降级、保级、刷新 CD 与跨棋盘整任务 | `部分通过` | `P1` | 个人突破测试时 | 保级“退四打九”已作为基线；分开补升级、降级、跨棋盘和票耗尽分支 | 每种模式按用户确认规则闭环，刷新/冷却/中断后能正确重新调度 | [Codex-05](archive/legacy-root-20260811/Codex-05-个人结界突破目标等级模式实施规格.md)、[Codex-12](archive/legacy-root-20260811/Codex-12-个人突破退四打九完整保级实测闭环.md)、[Codex-13](archive/legacy-root-20260811/Codex-13-个人突破整任务生命周期修复.md) |
| `RR-LOCK-001` | 阵容解锁、战后重锁和下一场准备兜底 | `正常路径及日志去重实机通过，异常路径待样本` | `P1` | 收集锁图标失配或自动开战失败样本 | 多轮均证明战后重锁、下一场不点准备自动开战；修复后两次真实自动开战各只有一条最终验证日志。目标等级策略四次投降后的四次重锁属于预期 | 未确认锁定时有限等待后允许准备兜底；图标不替代下一场效果验证；每个真实转场只有一条最终日志 | [去重实测](records/evidence/Codex-实测-RR-GREEN-FAST-SAMPLE-20260810-04.md)、[漏采根因场](records/evidence/Codex-实测-RR-LOCK-GREEN-20260810-03.md)、[实施记录](records/implementation/Codex-RealmRaid阵容锁定效果验证修复-20260810.md) |

### 4.4 困28 Exploration

| ID | 事项 | 状态 | 优先级 | 时效 | 下一步 / 依赖 | 验收标准 | 最新证据 |
|---|---|---|---|---|---|---|---|
| `EXP-028-MAP-001` | 地图滑动后是否完整覆盖、是否漏怪 | `部分通过` | `P1` | 近期 | 30 场长程已确认实际滑动、章节终点和计数稳定；继续保留目标发现与漏怪证据采集 | 每次有效滑动有执行/稳定/视口变化证据；地图目标不因提前退出漏检 | [困28长程复测](archive/legacy-root-20260811/Codex-实测-EXP-028-20260807-02-长程闭环复测.md)、[Codex-52](archive/legacy-root-20260811/Codex-52-困28地图滑动与结算性能优化实施记录-20260806.md) |
| `EXP-028-RESULT-001` | 战斗结算等待过长 | `待优化` | `P1` | 近期 | 已取得 30 场 P50/P95；下一步拆分游戏动画耗时与程序空等，补首次终态/首次点击截图 | 正常单页/多页等待显著下降，慢动画仍有兜底；不漏奖励、不误回主界面 | [困28长程复测](archive/legacy-root-20260811/Codex-实测-EXP-028-20260807-02-长程闭环复测.md)、[Codex-52](archive/legacy-root-20260811/Codex-52-困28地图滑动与结算性能优化实施记录-20260806.md) |
| `EXP-028-BUFF-001` | 困28四项加成开关可靠确认 | `部分通过` | `P1` | 近期 | 三项加成已完成开关确认；`gold_50` 缺失分支正确识别，仍需把“当前不存在”业务语义和截图验收单列 | 日志和截图能证明目标状态已开启/关闭；未知状态不当作成功 | [困28长程复测](archive/legacy-root-20260811/Codex-实测-EXP-028-20260807-02-长程闭环复测.md)、[Codex-49](archive/legacy-root-20260811/Codex-49-困28退出自动模式与加成实机回归-20260806.md) |
| `GLOBAL-BUFF-IDLE-001` | 15 分钟未使用加成覆盖弹窗会拦截底层业务点击 | `策略已修，取消分支待防穿透实测` | `P1` | 下一次真实弹窗 | 当前任务显式启用加成时确认，否则取消；确认分支已有一次真实证据。取消分支真实命中正确，但修复前第二次点击穿透到寮突破卡片，已增加 `0.8s` 动作后等待；下一次弹窗先验证只点一次且底层页面不变，再重跑困28 30 场 | 两种策略与配置一致；弹窗连续两帧消失；不点击底层页面；业务收到稳定新帧；30 场中无弹窗漏网 | [取消分支实测](records/evidence/Codex-实测-COMMON-POPUP-20260810-02-取消分支.md)、[策略与防穿透实施](records/implementation/Codex-通用加成弹窗按任务意图选择与防穿透修复-20260810.md)、[确认分支证据](records/evidence/Codex-实测-COMMON-POPUP-20260810-01.md) |
| `EXP-028-AUTO-001` | 自动轮换皮肤模板和候补布局兼容 | `暂缓` | `P2` | 近期 | 记录当前皮肤兜底是否稳定；有新皮肤截图后补模板 | 候补弹窗已打开时不点底层设置；布局/OCR兜底可解释 | [Codex-46](archive/legacy-root-20260811/Codex-46-困28自动轮换候补弹窗实机修复-20260806.md)、[Codex-49](archive/legacy-root-20260811/Codex-49-困28退出自动模式与加成实机回归-20260806.md) |

### 4.5 通用战斗、预设与御魂

| ID | 事项 | 状态 | 优先级 | 时效 | 下一步 / 依赖 | 验收标准 | 最新证据 |
|---|---|---|---|---|---|---|---|
| `COMBAT-PREP-001` | 统一队伍预设、御魂、锁定和战前准备契约 | `RyouToppa 效果验证已落地，通用化待设计` | `P1` | 业务链路稳定后 | 复用“首场是否需准备→回板后锁定→下一场效果验证”模式，抽取通用准备事务 | 不同任务可复用同一准备契约；视觉图标不替代效果验证；失败回退不互相覆盖 | [RyouToppa 锁定实施](records/implementation/Codex-RyouToppa阵容锁定效果验证与入口稳态修复-20260810.md)、[Codex-15](archive/legacy-root-20260811/Codex-15-通用战斗前准备预设与御魂规则.md) |
| `PRESET-SHORT-001` | 预设队伍人数不足时的素材补位 | `暂缓` | `P2` | 用户确认方案后 | 战斗内无法补齐，另设计战斗外补位流程 | 人数不足不会错误进入战斗；素材替换可追踪、可恢复 | [Codex-15](archive/legacy-root-20260811/Codex-15-通用战斗前准备预设与御魂规则.md) |

### 4.6 调度器与项目架构

| ID | 事项 | 状态 | 优先级 | 时效 | 下一步 / 依赖 | 验收标准 | 最新证据 |
|---|---|---|---|---|---|---|---|
| `SCHED-001` | 普通任务与定时任务生命周期分离 | `待设计` | `P1` | 当前业务闭环后 | 明确整项任务、单场战斗、调度器、手动启动和 `next_run` 的边界 | 手动启动不会被每场战斗重新调度；整项任务完成后才进入下一任务 | [Codex-03](archive/legacy-root-20260811/Codex-03-通用接口与任务框架重构基线.md)、[Codex-18](archive/legacy-root-20260811/Codex-18-调度竞态与识别兜底修复.md) |
| `SCHED-002` | TaskEnd 结构化、跨任务 next_run 权限、配置原子写入、实例锁 | `已完成（离线）` | `P2` | 长期 | 正式服务继续压力观察 | TaskEnd、配置事务、实例锁、统一 schedule 和跨任务授权名单均已实现 | [战斗终态实施记录](records/implementation/Codex-OAS战斗终态与任务结束语义修复-20260809.md)、[控制面实施记录](records/implementation/Codex-OAS控制面一致性修复-20260809.md) |
| `PERF-001` | Nemu 0.2/0.15 秒截图 A/B 和控制通道对比 | `待排期` | `P2` | 长期 | 保持默认 `0.3s`；完成当前功能实测后做同机 P50/P95 与误判率对照 | 只推荐满足 `1280x720`、颜色、方向和稳定性契约的方式 | [DeepSeek-03](archive/legacy-root-20260811/DeepSeek-03-性能报告交叉验证终审与修正汇总-20260806.md)、[Codex-51](archive/legacy-root-20260811/Codex-51-性能修复实施与验证记录-20260806.md) |

### 4.7 产品化与发布

| ID | 事项 | 状态 | 优先级 | 时效 | 下一步 / 依赖 | 验收标准 | 最新证据 |
|---|---|---|---|---|---|---|---|
| `PRODUCT-001` | 桌面端、授权、服务器校验、代码保护与商业发布 | `待排期` | `P3` | 长期 | 业务功能稳定后，沿 Core/Bridge/前端分层设计授权协议和发布构建 | 网页调试与桌面版共用功能契约；授权失败可安全降级；发布包可复现 | [Codex-07](archive/legacy-root-20260811/Codex-07-控制中心唯一前端与桌面链路收口.md)、[Codex-08](archive/legacy-root-20260811/Codex-08-授权服务与客户端代码保护架构审查.md) |

### 4.8 2026-08-09 双项目审计新增事项

本节最初来自 [双项目全貌只读审计](audits/Codex-OAS与coordinate-calibrator全貌只读审计-20260809.md)。2026-08-09 后续已完成多项代码修复；“已修”只表示相应实现和离线覆盖成立，缺少的实机矩阵仍按表补证。

| ID | 领域 / 事项 | 状态 | 优先级 | 下一步 | 验收标准 | 最新证据 |
|---|---|---|---|---|---|---|
| `CORE-LIFE-001` | 任务进程发布、强杀失败和账号所有权 | `代码已修（DS-13 收口强杀工具链同族缺陷 OAS-CRASH-001：start.ps1 -RestartCore 优雅优先/Force 兜底 + worker 管道写防护；重启 5 次实机复验待 Phase 5.3），待正式服务压力实测` | `P1` | 正式服务高频启停与强杀失败注入 | 强杀失败保留 PID/IPC/run_id/账号租约并进入 WARNING；拒绝再次启动、删除或改名；离线和隔离链路通过 | [本轮实施记录](records/implementation/Codex-双项目P0P1分阶段修复实施记录-20260810.md)、[DS-13 Phase1 实施](records/implementation/Codex-实施-DeepSeek13-phase1-进程治理-20260813.md) |
| `CONTROL-ACK-001` | Bridge 发送成功被当作 Core 执行成功 | `代码已修，隔离链路通过` | `P1` | 正式 UI 执行一次成功和一次拒绝命令 | command_id、接受与最终结果已贯通；停止失败不再包装成功；隔离 HTTP/WebSocket `16/16` | [本轮实施记录](records/implementation/Codex-双项目P0P1分阶段修复实施记录-20260810.md) |
| `CONFIG-CONCURRENCY-001` | 多字段部分提交、全文件自动保存和并发丢失更新 | `代码已修（DS-13 收口 PUT 单值路由 If-Match 428/409 门禁，见 OAS-PUT-REV-001），待正式并发实测` | `P1` | 两个前端/worker 同时编辑同一账号 | PATCH 缺 revision 返回 428，陈旧 revision 返回 409并保留草稿；PUT 单值同门禁；原子替换和离线覆盖通过 | [本轮实施记录](records/implementation/Codex-双项目P0P1分阶段修复实施记录-20260810.md)、[DS-13 Phase2 实施](records/implementation/Codex-实施-DeepSeek13-phase2-OAS其余-20260813.md) |
| `COMBAT-STATE-001` | 自动模式未知后活动战斗/待结算缺少恢复所有者 | `代码已修，待完整实机矩阵` | `P1` | 完成胜/负/卡结算/人工停止/恢复实机矩阵 | `BattleOutcome`、GotoMain 门禁和结构化 TaskEnd 已覆盖；活动战斗不被普通导航接管 | [战斗终态实施记录](records/implementation/Codex-OAS战斗终态与任务结束语义修复-20260809.md) |
| `EXP-LEVEL-001` | 章节命中后的点击与确认循环无截止时间 | `代码已修，3/10 场通过` | `P1` | 通用加成弹窗门卫实机确认后重跑 30 场 | 任一路径均在约定时限内成功或结构化失败；30 场完整闭环 | [EXP 实施记录](records/implementation/Codex-EXP探索硬边界与加成恢复修复-20260809.md)、[实测](records/evidence/Codex-实测-EXP-028-20260809-01.md) |
| `EXP-MAP-001` | MAIN 地图搜索缺总体退出约束，无位移滑动可能重置计数 | `代码已修，3/10 场通过` | `P1` | 通用加成弹窗门卫实机确认后重跑 30 场 | 搜索、识别和有效滑动预算有界；跨地图重置；30 场完整闭环 | [EXP 实施记录](records/implementation/Codex-EXP探索硬边界与加成恢复修复-20260809.md)、[实测](records/evidence/Codex-实测-EXP-028-20260809-01.md) |
| `LAUNCH-WIRING-001` | 复用 Bridge/前端时未验证完整依赖身份 | `代码已修，待多端口集成复核` | `P1` | 用第二套 Core/Bridge 做自定义 CoreUrl、备用端口和陈旧登记集成测试 | Bridge 复用校验 `core_url`；前端登记并校验 `bridge_url`；端点不一致时拒绝静默复用 | [2026-08-11 实施记录](records/implementation/Codex-DeepSeek08核验后代码修复-20260811.md) |
| `BINDING-001` | 非 MuMu 窗口把单一 ADB serial 当作身份关联 | `代码已修，待异构实机矩阵` | `P1` | 构造多窗口单 serial 及不同模拟器，要求无证据时拒绝自动映射 | 已删除通用“唯一 serial”猜测；MuMu 仅接受实例端口映射并经 ADB 验证；`2301` 抽查正确 | [2026-08-11 实施记录](records/implementation/Codex-DeepSeek08核验后代码修复-20260811.md) |
| `CC-ENV-001` | `PYTHONUTF8=1` 时按 UTF-8 解码本地化 `netstat` 输出，导致端点 PID 探测崩溃 | `已完成（0.3.8）` | `P2` | Windows 端点探测或子进程解码策略变化时重开 | 原始字节解析，不依赖本机代码页或标题文本；UTF-8 模式采集测试通过 | [0.3.8 实施记录](/D:/coordinate-calibrator/work/logs/2026-08-11-v0.3.8-windows-identity-hardening.md) |
| `TASKEND-001` | TaskEnd 无结构化 outcome/reason/next_run | `已完成（离线）` | `P1` | 新增任务必须使用显式构造器 | 正常、失败、重试和暂停语义可区分且日志可追踪 | [战斗终态实施记录](records/implementation/Codex-OAS战斗终态与任务结束语义修复-20260809.md) |
| `SCHED-AUTH-001` | Exploration/MemoryScrolls 可直接改其他任务调度 | `已修复（DS-13 收口 2 处旁路：MemoryScrolls→set_scheduler_enabled 授权入口、CollectiveMissions→schedule()，白名单补 2 条 + PATCH 审计；原「已完成」被 DS-10 F-4 证伪后重开）` | `P1` | 新增跨任务关系时必须同步扩展白名单与测试 | 默认只允许改自身；现有业务关系、管理入口和共享 WantedQuests 有显式授权；越权保存前失败（无旁路） | [战斗终态实施记录](records/implementation/Codex-OAS战斗终态与任务结束语义修复-20260809.md)、[DS-13 Phase1 实施](records/implementation/Codex-实施-DeepSeek13-phase1-进程治理-20260813.md) |
| `CC-TXN-002` | 帧、artifact、背景、Session 提交非原子；ready 文件对账不完整 | `已完成（0.3.5）` | `P1` | 仅在新增持久化路径时重开 | staging/提升/事务故障注入后 DB、文件、配额和内存收敛；损坏 ready 文件必报 | [一致性实施记录](records/implementation/Codex-coordinate-calibrator一致性修复-20260809.md) |
| `CC-ASYNC-002` | 工作区刷新竞态、跨画布选择丢失、恢复画布无租约 | `已完成（0.3.5）` | `P1` | 仅在新增异步资料库入口时重开 | 请求代次生效；摘要不清空跨画布选择；恢复后首个写操作成功 | [一致性实施记录](records/implementation/Codex-coordinate-calibrator一致性修复-20260809.md) |
| `CC-CAPTURE-002` | Nemu/ADB 前帧时序、DPI 真实性和双设备身份 | `代码已修，待实机矩阵` | `P1` | 跑 `2301`、干扰窗口、100/125/150% DPI、真实 ADB 和双 MuMu | 源独占和 identity generation 已离线通过；实机需证明无串帧、`before<click<after`、P95 不超过 2 画布像素 | [0.3.7 实施记录](/D:/coordinate-calibrator/work/logs/2026-08-10-v0.3.7-p0p1-remediation.md) |
| `CC-SEC-002` | CLI 实际 bind 与认证来源不一致；启动隐式迁移 | `已完成（0.3.7）` | `P1` | 仅在新增远程/启动入口时重开 | 有效 bind 统一；冲突 CLI 拒绝；普通启动拒绝旧 schema；正式数据已显式迁移到 schema 6 | [0.3.7 实施记录](/D:/coordinate-calibrator/work/logs/2026-08-10-v0.3.7-p0p1-remediation.md) |
| `CC-IDEMP-003` | 进程崩溃后内存幂等记录丢失会重复创建资源 | `已完成（0.3.7）；DS-13 收口后续发现 F5-F8（owner 维度/租约指纹重放校验/残留窗口 1h/注册表 LRU），见 CC-BATCH-DS13-001` | `P1` | 新增创建/导入/导出路由时重开 | schema 6 持久化 operation；相同 key 重放返回同一资源；指纹或 fencing 不同返回冲突 | [0.3.7 实施记录](/D:/coordinate-calibrator/work/logs/2026-08-10-v0.3.7-p0p1-remediation.md)、[DS-13 Phase3 实施](records/implementation/Codex-实施-DeepSeek13-phase3-CC-20260813.md) |
| `CC-BUNDLE-002` | Bundle 语义放大、删除编号往返和并发导出混合快照 | `已完成（0.3.7）` | `P1` | 新增 Bundle 实体或配额时重开 | 写入前完整预验证；历史删除编号不占活动唯一约束；workspace/session 锁和单一读快照导出 | [0.3.7 实施记录](/D:/coordinate-calibrator/work/logs/2026-08-10-v0.3.7-p0p1-remediation.md) |
| `RR-CHECKPOINT-002` | RealmRaid checkpoint 跨进程覆盖和损坏静默重置 | `代码已修，待真实恢复演练` | `P1` | 复制 checkpoint 做双进程 CAS 与损坏恢复演练 | schema 3 revision/run_id、跨进程锁、唯一临时文件、fsync 和隔离区均通过离线测试 | [本轮实施记录](records/implementation/Codex-双项目P0P1分阶段修复实施记录-20260810.md) |
| `GREEN-MARK-001` | 旧模板单帧命中会误授权绿标成功 | `左三快速采样实机 2/2，生产诊断模式` | `P0` | 扩大到 3 次新进攻；其后补五槽位与红标样本 | 颜色、尖端、互斥槽位、不同哈希稳定帧和快速受保护采样已实现；修复后两次均确认 `green_left3`，置信度约 `0.823/0.829`，错误槽位为 0 | 确认必须是正确颜色、正确独占槽位和不同哈希稳定帧；下一门槛 `3/3`、误确认 0；五槽位和红标未补齐不得结案 | [修复后实测](records/evidence/Codex-实测-RR-GREEN-FAST-SAMPLE-20260810-04.md)、[采样修复实施](records/implementation/Codex-绿标快速稳定帧采样与锁定转场去重修复-20260810.md)、[绿标 ADR](decisions/ADR-002-green-marker-color-slot-ownership.md) |
| `X-INTEGRATION-001` | 校准器候选不能直接成为 OAS 完整规则，双方缺版本化帧/证据契约 | `契约 v1 已落盘，运行时待接入` | `P2` | 坐标实测按 v1 生成候选与证据；不做自动写回 | `DeviceIdentity/Frame/Candidate/Evidence/BattlePreparation` 可校验；应用仍需人工复核 | [契约实施记录](records/implementation/Codex-跨项目中立证据契约-v1-20260809.md)、[Schema](contracts/v1/contracts.schema.json) |

### 4.9 2026-08-12/13 事件与 DeepSeek-09/10/11/12 审查新增事项（DeepSeek-13 修复轮前置补记）

> 本节为 08-12/13 两天事件与四轮 DeepSeek 审查（handoff/audits/）发现的事实登记。修复进行中，状态暂标「实施中」；修复完成后随 §4 统一重写并更新状态。oas2 澄清：08-13 日志中「oas2 秒退/Core 反复重建」已被 DS-11 R-2 证伪为测试工件（child_pid=4100=FakeProcess，test_script_process.py:24），生产环境从未拉起 oas2。

| ID | 领域 / 事项 | 状态 | 优先级 | 备注 / 证据 |
|---|---|---|---|---|
| XIUXING-001 | XiuxingHexun 新模块上线与实机 | 实施中 | P1 | 08-12/13 通宵实机 82 胜/9 败/4 次打满；flow 32/32 + config 18/18；next_run=2026-08-14 06:04（DS-10/11） |
| OAS-CRASH-001 | 孤儿 worker/BrokenPipeError 崩溃链（关联 CORE-LIFE-001 同族） | 已修（离线，重启 5 次实机复验待 Phase 5） | P0 | DS-11 R-1；Phase1 1.1 优雅优先+管道写防护 |
| OAS-FAILCOUNT-001 | 失败计数随 worker 重启清零，三连败治理失效 | 已修（离线，跨重启实测待 Phase 5） | P1 | DS-11 R-3；Phase1 1.3 sidecar 持久化 |
| OAS-SYNCNEXT-001 | sync_next_run 以 success=True 覆盖失败延时 | 已修（离线） | P1 | DS-11 N-4；Phase1 1.4 失败延时钳制+force |
| OAS-GUILD-LOOP-001 | GuildActivityMonitor 无效 run_days 热循环 | 已修（离线） | P1 | DS-10 F-2；Phase1 1.5 TaskEnd.failed |
| OAS-POPUP-001 | CommonPopup 对非 nemu 截图方式 fail-closed 过严 | 已修（能力要求放宽；尺寸契约维持） | P2 | DS-10 F-10；Phase2 2.5 |
| OAS-WS-HB-001 | Bridge→前端事件 WS 无心跳 | 已修（30s bridge.ping） | P2 | DS-10 F-13；Phase2 2.3 |
| OAS-CMD-IDEM-001 | 命令 5s 超时后 REST 重发可能双发 | 已修（宽限期采用迟到回执） | P2 | DS-10 F-14；Phase2 2.4 |
| OAS-RECOVER-001 | VICTORY 恢复判定单模板证据 | 已修（第二帧稳定证据+新测试） | P2 | DS-10 F-8；Phase2 2.6 |
| OAS-NEMU-THREAD-001 | nemu_ipc 超时线程残留无锁 | 已修（单工作线程串行） | P2 | DS-10 #13；Phase2 2.7 |
| OAS-NEXT-RUN-001 | TaskEnd.next_run 载荷不被调度器消费 | 已修（schedule() 写回） | P2 | DS-10 obs6；Phase2 2.8 |
| OAS-TESTLOG-001 | 测试运行污染生产日志 | 已修（实测：套件运行后生产日志 0 增长） | P1 | DS-10 F-12；Phase1 1.2 测试上下文隔离 |
| OAS-TEST-HERMETIC-001 | 生命周期测试与真实 oas1 租约冲突 | 已修（套件全绿 0 AccountLeaseError） | P1 | DS-10 F-16；Phase1 1.7 OAS_LEASE_DIR 隔离 |
| OAS-CFGSAVE-001 | config_model __setattr__ 写放大未节流 | 已修（0.5s debounce） | P3 | DS-10 F-15；Phase2 2.10 |
| OAS-PUT-REV-001 | PUT 单值路由无 revision 门禁 | 已修（If-Match 428/409 + bridge 带 revision） | P1 | DS-10 F-9；Phase2 2.2 |
| OAS-EXHAUST-001 | OCR '0'→'O' 误读致耗尽判定失败链 | 已修（离线；实机命中分布待 Phase 5） | P1 | DS-11 R-4；Phase2 2.1 None-streak 回退 |
| OAS-MAXCHALLENGE-001 | max_challenges 默认 0 无上限 | 已修（默认 50；生产 oas1.json 仍 0，待用户确认） | P2 | DS-10 F-7；Phase2 2.1 |
| OAS-GREEN-TPL-001 | 绿标黑底模板确定性缺陷（42/28.5/36.4% 黑像素） | 待实测 | P1 | DS-10 F-5；重采需实机窗口 |
| OAS-CONTRACT-ENV-001 | contracts 信封规范未被执行（本轮不修） | 待排期 | P3 | DS-10 obs7 |
| CC-DAMAGED-001 | mark_artifact_damaged CHECK 违规（关联 CC-TXN-002） | 已修（delete_pending 零迁移 + reconcile 补偿 + damaged-ready repairs 新测试；CC 套件 149/149） | P0 | DS-09 F1/DS-11 R-5；DS-13 Phase3 3.1 |
| CC-LEASE-STORM-001 | 租约乒乓（多客户端+TTL/心跳失配+无退避） | 已修（同 owner 活租约原样返回+TTL 60+前端退避；双标签 30min 量化复测待浏览器实机） | P1 | DS-09 F16/DS-11 R-6；DS-13 Phase3 3.2 |
| CC-DOC-DRIFT-001 | CC 文档漂移 5 条 | 已修（protocol.md 信封/错误码/心跳、architecture.md start.ps1 措辞） | P3 | DS-09 文档漂移；DS-13 Phase3 3.20 |
| CC-P3-BATCH-001 | CC P3 降级清单（build_report 双遍历/selection_hash 缺口/.ccproj 遗留空组/半开区间/DOM 重建/画笔自交/MUTATING_CONTROL_IDS/XSS 单引号/N12/N15/心跳测试缺口） | 待排期 | P3 | DS-09 §1 P3 + annex-A/C；本轮不修（理由存档于 DS-13 报告 §P3 降级清单） |
| OAS-TEST-ORDER-001 | OAS 测试套件存在顺序依赖（先导入的模块可破坏后导入的 green_mark/battle_page 测试；DS-14 实测：文件系统序失败、mtime 降序全过） | 待排期 | P2 | DS-14 全量回归实测；run-oas-tests.ps1 暂以 mtime 降序复刻 491 轮已证顺序 |


### 4.10 DeepSeek-13 修复轮 CC 批量收口（DS-09 F2-F19，指针式登记）

> 完整改动与验证见 handoff/records/implementation/Codex-实施-DeepSeek13-phase3-CC-20260813.md 与 handoff/audits/DeepSeek-13-annex-CC批量子代理报告-20260813.txt。CC 全量套件 149/149（26.1s）通过。

| ID | 事项 | 状态 | 优先级 | 备注 |
|---|---|---|---|---|
| CC-BATCH-DS13-001 | DS-09 F2-F19 批量收口（F2 bundle to_thread、F3 quarantine 配额+GC 命令、F4 close 清理失败上报、F5 幂等 owner 维度、F6 租约指纹重放校验、F7 残留窗口 1h、F8 注册表 LRU、F9 序列化加锁、F10 配额计 active、F11 像素积 64M、F12 undo 背景过滤、F13 v1 导入 128MB、F14 addPoint 删除、F15 blink 清理、F16 租约乒乓、F17 DPI fail-closed、F18 token ACL、F19 OSError/sqlite3 映射） | 已修（149/149） | 对应原报告 P1/P2 | 指针式登记；细节以 CC 项目自身实施记录为准 |


## 5. 可暂时结案或作为有效基线的事项

这些事项已达到当前范围的验收标准，但“结案”只针对明确范围，后续出现新证据时重新打开同一 ID，不另起重复事项。

| ID / 范围 | 当前结论 | 证据 | 重新打开条件 |
|---|---|---|---|
| `EXP-EXIT` | 探索未知页不再随机盲点，章节页/世界页退出确认和保护页收束已通过实机 | [Codex-45](archive/legacy-root-20260811/Codex-45-探索未知页面安全退出与实机根因修复-20260806.md)、[Codex-48](archive/legacy-root-20260811/Codex-48-探索退出确认公共恢复修复-20260806.md) | 再次出现友人帐误入、随机点击或退出超时 |
| `EXP-CANDIDATE` | 困28候补弹窗已打开时不会再点击底层设置，数量足够可确认继续 | [Codex-46](archive/legacy-root-20260811/Codex-46-困28自动轮换候补弹窗实机修复-20260806.md) | 新皮肤/新布局导致候补弹窗识别失败 |
| `EXP-MAP-CONTROL` | 地图滑动执行、视口稳定、双帧终点和长程可恢复性：3/10 场已通过；**30 场未通过**（swipe_budget_exhausted，见 records/evidence/Codex-实测-EXP-028-20260809-01.md:37，待重跑） | [Codex-52](archive/legacy-root-20260811/Codex-52-困28地图滑动与结算性能优化实施记录-20260806.md) | 再次出现未确认滑动、提前 `search_exhausted` 或漏怪证据 |
| `PERF-FRAME-OCR` | `frame_id`、同帧 OCR 缓存、Nemu 分辨率/颜色契约和关键回归已实施并通过离线/长程正确性验证 | [Codex-51](archive/legacy-root-20260811/Codex-51-性能修复实施与验证记录-20260806.md) | 需要 0.2/0.15 秒 A/B 或再次出现颜色/缓存误判 |
| `RR-HOLD-001` | RealmRaid 保级“退四打九”单棋盘主链路已验证 | [Codex-12](archive/legacy-root-20260811/Codex-12-个人突破退四打九完整保级实测闭环.md) | 升降级、跨棋盘、冷却或战斗结果边界测试重新开始 |
| `SCHED-IDLE` | 空任务队列进入 idle 并清理旧任务状态；预设异常有专用重试边界 | [Codex-41](archive/legacy-root-20260811/Codex-41-T3-preset-error-preflight-20260806.md)、当前 `module/config/config.py` 与 `module/server/tests` | 再出现空队列退出进程、预设异常触发重启或状态残留 |
| `CC-CORRECT-001` | 显示帧身份、尺寸、映射版本和哈希已锁定为不可变上下文；缩放不改变坐标 | [坐标可信性实施记录](records/implementation/Codex-coordinate-calibrator坐标可信性修复-20260809.md)、[校准器测试计划](/D:/coordinate-calibrator/docs/test-plan.md) | 再出现显示帧与换算帧混用、缩放后坐标漂移或帧/映射 revision 不一致 |
| `CC-CORRECT-002` | 渲染、命中、移动、报告和导出共用当前背景/可见性/过滤资格；背景外标注不参与报告（DS-13 收口 DS-09 F12：undoAnnotation 改用 canvasEligibleAnnotations 背景过滤） | [坐标可信性实施记录](records/implementation/Codex-coordinate-calibrator坐标可信性修复-20260809.md)、[校准器测试计划](/D:/coordinate-calibrator/docs/test-plan.md)、[DS-13 Phase3 实施](records/implementation/Codex-实施-DeepSeek13-phase3-CC-20260813.md) | 隐藏、删除、背景外或过滤掉的标注再次可命中、移动或误导出 |

寮突破 50 场只能结案为“战斗/回板稳定性基线”，不能结案为“寮突破业务清空完成”；后者仍由 `RY-GUILD-003` 管理。

## 6. 明确暂不纳入当前测试

- `RY-GUILD-004` 本轮目标改为左三：点击映射已通过，确认器仍未通过；不与自动选寮验收混写。
- `EXP-028-BUFF-001`、`EXP-028-RESULT-001`：本轮已独立记录，不与明晚寮突破排序单步混测；两项均不建立结案记录。
- 个人突破升级/降级/CD：不因保级测试通过而默认通过，单独安排场景。
- `PRODUCT-001` 产品化和授权：不在当前网页实机调试批次实施。

## 7. 后续文档分工

以后每个事项使用稳定的事项 ID；编号文档是一次记录，不是事项本身。

### 7.1 待做事项总表

当前文件只保留开放事项、状态、优先级、下一步、依赖和验收标准。状态变化时更新这一份表。

### 7.2 实测反馈

每次真实测试新建一份不可变记录，建议命名：

`Codex-实测-<事项ID>-<日期>-<轮次>.md`

只记录测试前置、实际操作、日志/截图证据、结果、异常和根因判断。不要把“下一步计划”写成已经完成，也不要覆盖以前的实测结果。

当前寮突破错误选寮的事实证据见 [本轮实测反馈](archive/legacy-root-20260811/Codex-实测-RY-GUILD-001-20260807-01.md)；`Codex-55` 保留为原始测试计划。后续若再次实测，应新增轮次并更新本表状态。

### 7.3 实施记录

代码有改动时新建：

`Codex-实施-<事项ID>-<日期>.md`

记录改动文件、根因、离线测试、回滚点和尚未实测的风险。实施记录不能直接写“功能完成”，只能写“代码实施完成”。

### 7.4 结案记录

只有验收标准全部满足后才新建：

`Codex-结案-<事项ID>-<日期>.md`

结案必须包含最终环境、真实证据、离线结果、长程结果、剩余风险和重新打开条件。结案后仍保留历史实测和实施记录，不删除、不覆盖。

### 7.5 决策与用户确认

涉及游戏语义、失败策略、并列选择或是否继续挑战时，先记为 `待确认`，得到用户确认后再进入实施。不能把代理推测、OCR 单帧或上游流程当作当前版本规则。

## 8. 当前唯一执行顺序

1. P0/P1 代码阶段已完成：OAS 控制面、checkpoint、任务结果、页面所有权、探索边界、弹窗分发和绿标诊断链；校准器有效 bind、schema 6、持久幂等、Bundle 快照和采集门禁均有完整离线回归。
2. 下一次真实“15 分钟加成”弹窗先复核确认/取消均只点一次、连续两帧消失且底层页面不变；通过后重跑困28 30 场。
3. 达摩武场五槽靶场 50/50 已完成（GREEN-TARGET-RANGE-20260810-02）；**五锚点与红标样本未补齐**；生产继续保持 `detect_only`。
4. RealmRaid 左三单场已经通过；下一步执行 3 场和 10 场，并单独采集一次战斗过快、终态先于绿标确认的边界证据。
5. 当前寮已选定，`RY-GUILD-001` 不消耗本轮唯一选择机会；下次可选寮时先做“只选不打”的勋章最大值验证。
6. 执行 MuMu `2301` 加干扰窗口、DPI 100/125/150%、窗口移动、真实 ADB、句柄复用和双设备身份矩阵。
7. 全部实机门槛通过后才建立结案记录；任何坐标候选继续只读导出，不自动写回 OAS。

## 文档和通用工具

当前文档层已拆分为状态快照、运行停止、配置归属、任务生命周期、测试结案、任务规格、记录、审计和决策目录。旧编号文档仍保留历史证据，不自动改变本表状态。

通用坐标校准工具单独维护在 D:\coordinate-calibrator。它只生成坐标、几何统计和 OAS 候选导出，不写入 OAS 业务文件；独立项目的接口和验收以该项目 docs 目录为准。

2026-08-08/09 审计与修复记录保留为历史证据。当前事实以 [2026-08-10 P0/P1 实施记录](records/implementation/Codex-双项目P0P1分阶段修复实施记录-20260810.md)、[2026-08-11 补修记录](records/implementation/Codex-DeepSeek08核验后代码修复-20260811.md) 和 [校准器 0.3.8 记录](/D:/coordinate-calibrator/work/logs/2026-08-11-v0.3.8-windows-identity-hardening.md) 为准：版本 `0.3.8`，正式套件 `146/146`，正式数据 schema 6；真实采集身份、DPI、ADB 和双设备验收继续开放。

| ID | 事项 | 状态 | 优先级 | 下一步 | 验收标准 |
|---|---|---|---|---|---|
| `CC-COORD-001` | 坐标、旋转圆/椭圆、多边形推荐点、小数 bbox、凹多边形关系、协方差和方向边界 | `已完成（旧范围）` | `P1` | 显示帧问题已由 `CC-CORRECT-001/002` 完成当前范围修复 | Python/JS 四方向、几何与来源证明回归已纳入 126 项测试；OAS 候选仍需人工确认 |
| `CC-STATE-001` | 跨画布异步状态、租约、工程规格和预览/持久帧隔离 | `已完成（旧范围）` | `P1` | 新竞态由 `CC-ASYNC-002` 管理 | 请求 context、逐写 lease/fencing、pending arm 生命周期取消、`persisted_frame` 和按帧 ID 下载已有旧范围验证 |
| `CC-DEVICE-001` | GET 副作用、设备/窗口身份、Per-Monitor DPI 与前台过滤 | `待实测` | `P1` | 完成 `2301` 前台鼠标和移动/DPI矩阵 | 代码门禁、Nemu 身份和 36 分钟后台采集已通过；真实前台/DPI 证据未完成 |
| `CC-PERF-001` | 阻塞 I/O、几何复杂度和 SQLite 并发 | `已完成` | `P1` | 仅在新适配器引入同步 I/O 时重开 | 同步路由在线程池，复杂度有预算；旧 lease scope 已改为逐写 guard，心跳不再被长事务阻塞 |
| `CC-SEC-001` | 单实例、远程 host/token、Host/Origin 和路径边界 | `已完成（旧范围）` | `P1` | CLI bind 漂移和迁移边界由 `CC-SEC-002` 管理 | 默认 loopback、单实例锁、端口 Cookie、Host/Origin 和输出边界已有旧范围测试 |
| `CC-LIVE-001` | 连续实时帧、多画布 worker、跨画布导出 | `部分通过` | `P1` | 做两设备并行 10 分钟和真实 ADB | 每画布 worker、内存预览、跨画布导出已实现；单 Nemu 36 分钟通过，双设备未实测 |
| `CC-DATA-001` | legacy workspace、标注可达、孤儿帧、迁移和对账 | `已完成（schema 6 当前范围）` | `P1` | 新的提交/对账问题由 `CC-TXN-002` 管理 | 正式数据 9 session、47 标注、8 背景、8 截图哈希迁移前后不变，`integrity_check=ok` |
| `CC-RELEASE-001` | 独立环境、wheel Web 资源、安装与优雅停止 | `已完成（0.3.8）` | `P2` | 发布前重复干净环境 smoke | `0.3.8` 在 Python 3.11 环境运行；146/146、编译、AST、wheel 构建和隔离安装通过 |
| `CC-UX-001` | 标注、移动、多选、过滤、删除、缩放、多画布和工程往返 | `已完成` | `P2` | 出现可重复浏览器回归时重开 | 主体浏览器验收通过；静态资源改为 no-store，旧新脚本混载已消除 |
| `CC-IMPORT-CANVAS-001` | 新建空画布后普通导入截图会隐式创建第二画布 | `已完成（0.3.6）` | `P2` | 仅在新增截图入口时重开 | 首图导入复用当前空画布；已有背景时明确拒绝并引导“添加背景版本”；隔离验收画布数始终为 7 |
| `CC-TEST-001` | 隔离测试、JS、浏览器、打包、多进程和实机矩阵 | `部分通过` | `P2` | 补前台鼠标/DPI、真实 ADB、双设备 | `0.3.8` 的 146/146、JS、编译、AST、隔离 wheel、schema 6 迁移和 22881 验证已通过；实机矩阵未执行 |

## 9. 2026-08-09 本轮收束状态

> **2026-08-13 23:07 状态注记（DeepSeek-13 修复轮）**：OAS Core（PID 5936）与 coordinate-calibrator（PID 25064）均已优雅停止（/home/kill_server 与 stop.ps1），进入停服修复；Bridge/前端本已停。修复完成后本节整体重写。DB 基线（停服后只读核验 08-13 23:10）：CC sessions 17、annotations 81、frames 17、artifacts 17、leases 17（全部过期）、idempotency_operations 394、quarantine_items 6、integrity=ok；sessions「9」为迁移时点快照、「19」为 data/sessions 目录数（含空/迁移遗留）。

- 双项目只读审计和交叉验证已经完成，六个子代理均已结束。
- 后续第 0、1、2 步已完成：建立可恢复基线，并修复校准器坐标可信性、持久化事务、异步竞态和租约一致性。
- coordinate-calibrator 当前为 `0.3.8`、schema 6，正式套件 `146/146` 及 22881 复制数据验收通过；本地化 Windows 端点识别已修，有效 bind、显式迁移、持久幂等、Bundle 和采集门禁已实现，真实 DPI/ADB/双设备问题保持开放。
- OAS 当前 15 个定向与回归套件合计 `444/444`，Bridge `27/27 + 3/3`，隔离 Core/Bridge 集成 `16/16`；控制面、checkpoint、任务结果、页面所有权、探索边界、弹窗 deadline 和绿标诊断链已有新增覆盖。
- `GotoMain page_battle` 当前已有代码门禁和 unittest，状态是待真实异常链复测，不再记为“尚未实现”。
- 绿标旧模板失配已被 2026-08-09 靶场和 2026-08-10 寮突破左三再次复现；左三最高分 `0.702876 < 0.8`。HSV 能看到典型 `63×61` 候选，但 45 轮旧样本的 `0.35s` 目标命中仅 `32/45`，暂不进入生产确认。
- 当前 Core、Bridge、前端和 coordinate-calibrator 均运行；`oas1` 已停止。MuMu `2301` 可见，Bridge 已验证 serial `127.0.0.1:16384`；跨 DPI、双 MuMu 和完整坐标映射仍未确认。
