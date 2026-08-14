# Codex 实施记录：个人突破与困28完整闭环验证

日期：2026-08-07
分支：`codex/mk6657-secondary-development`
账号：`oas1`
设备：MuMu 窗口 `2301`，ADB `127.0.0.1:16384`

## 目标

先验证目标等级 58 的个人突破 RealmRaid；票数不足时安全切换到困28补券。个人突破和困28均按 3、10、30 阶段验证，异常停止扩大量并记录根因。暂不人为制造升级、降级场景。

## 执行约束

- 只保留一套 Core、Bridge、前端和一个 `oas1` 任务实例。
- 不并行运行 RealmRaid 与困28。
- 不回滚工作树中的既有用户/代理改动。
- 困28运行时绿标临时关闭，不写回持久配置；RealmRaid保留当前绿标配置。
- 真实战斗未完成前，不允许处理奖励、回棋盘或调度下一轮。

## 基线

- Core：`127.0.0.1:22267`，健康。
- Bridge：`127.0.0.1:22367`，健康，版本 `1.1.4`。
- 前端：`127.0.0.1:4175` 正在监听。
- `oas1`：API状态为 `offline`，无选中任务，无运行实例。
- RealmRaid：目标等级模式开启，目标 `58`，`number_attack=30`，`exit_four=true`，失败策略 `Refresh`，队伍预设和御魂预设均为 `日常 / 结界突破`，绿标 `green_left3`。
- Exploration：`minions_cnt=30`，困28，自动轮换开启，候补为素材，`up_daruma`，四项加成配置开启。
- `config/oas1.json` 原始文本存在格式/编码异常，本轮以 Core/Bridge 规范化 API 返回为配置真相。

## 验证阶段

- RealmRaid 冒烟：3场，检查入口、预设/御魂、自动战斗、绿标、奖励边界、回板和票数。
- RealmRaid 中程：10场，检查保级计数、checkpoint、刷新和锁定/战后准备。
- RealmRaid 长程：使用剩余票数，最多覆盖30张票。
- 票数不足：停止RealmRaid后运行困28，按3、10、30阶段补券并验证地图、加成、自动战斗和结算。

## 结果

首轮RealmRaid冒烟未通过，已停止扩大量并完成最小修复，等待同场景复测。

### 2026-08-07 02:04 首轮闸门

- 任务进入棋盘，预设/御魂日志完整，目标等级连续识别为 `58`。
- 保级阶段正确执行失败计数到4后进入攻击阶段。
- 自动模式识别为 `auto`，未重复点击自动按钮。
- 战斗结果阶段误将普通结果页的图像命中为3/6/9奖励，随后奖励检测连续3次未清除。
- 最终日志为 `Level mode exit: outcome=deferred, reason=attack_unconfirmed`，任务延迟到 `02:11:18` 并停止。
- 现场页面已回到主界面，截图：[RR-COMBAT-001-after-failure.png](../../../log/Codex-2026-08-07-RR-COMBAT-001-after-failure.png)。
- checkpoint 保留为目标 `8`、失败计数 `4`、成功计数 `6`、`pending_action=attack`、`pending_stage=battle`。

### 首轮修复

- `tasks/RealmRaid/script_task.py`：通用结算提示优先由 `GeneralBattle` 消费；仅当当前没有通用结果提示时才使用3/6/9奖励兜底。
- `tasks/RealmRaid/tests/test_result_overlay.py`：增加普通结果提示与奖励图同时出现时的优先级回归用例。
- 离线结果：RealmRaid目标等级、恢复、奖励和结算专项 `57/57` 通过。
- 回滚点：恢复 `_dismiss_battle_result_continue()` 的修改，并移除新增优先级用例即可；未修改RealmRaid等级规则、票数规则或持久化业务配置。

### 2026-08-07 02:13 第二轮实机与修复

- 第二轮从 checkpoint 恢复，目标等级仍为 `58`，成功 `7`、失败 `4`、票数 `29/30`，说明恢复提交链路生效。
- 点击目标并进入挑战后，首帧尚未识别出 `BATTLE_PREPARE`，但固定 `I_SOUL_RAID` ROI 命中；RealmRaid 覆盖方法在通用战前预检查阶段误点 `(640,540)`，页面实际仍停留在准备页，最终 `wait_level_board` 超时并以 `attack_unconfirmed` 暂停。
- 根因不是单纯 OCR 漏识别，而是战前预检查允许调用任务专属奖励兜底；准备页门禁只能在准备 OCR 已出现后生效，无法保护首帧过渡窗口。
- 修复：`GeneralBattle.run_general_battle()` 战前预检查显式调用 `allow_task_reward=False`；RealmRaid 覆盖方法在该上下文只允许通用结果提示处理，跳过 `I_SOUL_RAID` 奖励兜底；战斗结果循环保持默认 `allow_task_reward=True`。
- 新增回归用例覆盖“首帧准备 OCR 为空但奖励 ROI 命中”以及“通用战前调用传递禁用标志”。
- 修复后离线结果：RealmRaid `80/80`、GeneralBattle `81/81`，专项结果 `16/16`、`7/7`，`py_compile` 和 `git diff --check` 通过。
- 当前状态：代码修复完成，等待同一 checkpoint 的单场实机复测；未启动困28，未扩展到3/10场。

### 2026-08-07 03:39-03:50 修复后个人突破最终段

- 从既有 checkpoint 继续运行，剩余 9 张票全部消耗；最终日志为 `tickets=0/30`、`spent=9`、`Level mode exit: outcome=completed, reason=ticket_reserve_reached`，随后回到主界面并记录 `Scheduler: End task RealmRaid`。
- 奖励层修复在实机中生效：多次记录 `RealmRaid reward overlay detected`、底部兜底点击 `(640,675)` 和 `milestone reward overlay cleared`，未再把该奖励层直接当作棋盘状态。
- 自动战斗链路多次确认 `AUTO_MODE_RESULT result=enabled`，其中包含一次 `adb_fallback`；没有重复点击已确认的自动状态。
- `green_left3` 在本段多次执行两次点击，但每次均记录 `Green mark click unconfirmed`，目标式神是否正确尚未有点击前后截图证据。
- 同一轮在 `03:41:22` 仍出现一次 `GameStuckError: Battle result` 并保存棋盘原图；后续恢复继续完成剩余票数。因此本段证明“可恢复并完成”，不能证明“无异常稳定闭环”。

### 2026-08-07 03:55 离线门禁

- `tasks/RealmRaid/tests`：`85/85` 通过。
- `tasks/Component/GeneralBattle/tests`：`85/85` 通过。
- `tasks/Exploration/tests`：`41/41` 通过。
- 当前服务仍为 Core `22267`、Bridge `22367`、前端 `4175` 各一套实际监听；MuMu 窗口 `2301`、ADB `127.0.0.1:16384`。
- 个人突破已因票数为 `0/30` 停止，尚未启动困28；下一阶段只启用困28，不与 RealmRaid 并行。

### 2026-08-07 03:57-04:04 困28 3/10 阶段

- 困28预设按名称应用成功：`SOUL_PRESET_RESULT result=applied_by_name`，队伍预设和御魂预设均指向日常分组的困28队伍。
- 四项加成逐项读取并确认状态；`gold_50` 当前未出现，日志明确为 `No GOLD_50 buff`，未误判为已开启；其余三项完成打开/确认，结束时按原状态关闭。
- 地图阶段记录真实滑动和视口变化；3场阶段至少有一次 `EXPLORATION_SWIPE_SETTLE viewport_changed=True`，目标锁定后进入战斗，结算完成后计数到3并回主界面。
- 10场阶段从累计3继续到10；记录多次视口变化，出现一次 `viewport_changed=False` 后按规则重试一次，随后继续完成目标搜索和战斗；未出现 `GameStuck`、错误页面或提前退出。
- 10场阶段结束日志为 `Scheduler: End task Exploration`，临时绿标仍关闭；当前进入长程前状态正常。

### 2026-08-07 04:04-04:16 困28 30场长程

- 从中程状态继续执行，最终日志到达 `Fight, minions cnt 30`，随后 `Scheduler: End task Exploration`、回到 `page_main`、`nemu_ipc released`。
- 本窗口完成 30 次结算处理；`BATTLE_RESULT_TIMING stage=continuation_handled` 耗时 P50 `8.547s`、P95 `8.890s`，范围约 `7.297-8.953s`。这仍包含游戏结算动画，不能全部归因于程序空等。
- 记录 41 次 `EXPLORATION_SWIPE_SETTLE`，3 次 `EXPLORATION_SWIPE_RETRY`；代表性记录包含视口变化为真和视口未变化后的单次重试。没有因为一次稳定画面直接扩大退出。
- 记录 28 次目标锁定、11 次章节页终点确认；右侧边界出现 `EXPLORATION_UP_ROI_CLIPPED` 后仍成功锁定目标，说明边界裁剪没有导致本窗口漏掉已发现目标。
- 自动模式确认 30 次，失败/未识别 0 次；窗口内 `GameStuck`、Traceback、`Cannot goto page` 和错误级日志为0。
- 30场长程通过当前地图/结算/自动战斗稳定性门禁；困28四项加成中的 `gold_50` 缺失仍需作为“正确识别不存在”保留，不可当作四项均已开启。

### 2026-08-07 04:20 RealmRaid startup scene guard

- 现场证据：[RR-EXP-closure-stuck-20260807-0420.png](../../../log/diagnostics/RR-EXP-closure-stuck-20260807-0420.png) 显示实际页面是永生之海御魂副本战斗，不是个人突破棋盘。
- 日志证据显示启动时 `ui_get_current_page()` 已识别为 `page_battle`，随后旧路径仍尝试 `page_battle -> page_main`，并重复等待/识别；这条路径可能触碰当前战斗返回控件，不能继续保留。
- 根因是 RealmRaid 的预设准备和通用页面导航在任务入口之前没有主动拒绝活动战斗页；任务实例串线时会把其他任务的战斗页当作可恢复的导航起点。
- 修复已实施：入口最先执行 `REALM_RAID_SCENE_GATE`，检测 `page_battle` 后只保存证据、延迟 RealmRaid、抛出 `TaskEnd`，不点击当前页、不调用全局 Restart；进入目标页后再次确认 `page_realm_raid`、RealmRaid 标记和票数 OCR，并将等级确认交给首次稳定棋盘观察。
- 离线结果：新增场景门禁 `3/3`，RealmRaid 启动锁定回归 `2/2`，预设准备/入口回归 `9/9`，页面注册/路由 `4/4`，编译检查通过。
- 尚未结案：需要在同一 MuMu 窗口 `2301`、单一 `oas1` 实例下完成一次真实 RealmRaid 单场复测；复测前不扩大到中程或长程，也不在活动战斗页上强制退出。

### 2026-08-07 04:37 调度等待链补充发现

- 真实门禁复测证明 RealmRaid 自身没有点击活动战斗页，但任务结束后调度器的 `when_task_queue_empty=goto_main` 仍调用 `GotoMain`，旧 `GotoMain` 在 `page_battle` 上消费了“点击屏幕继续”。
- 最小修复已补入 `tasks/GotoMain/script_task.py`：`page_battle` 只记录并 `TaskEnd`，不调用 `ui_goto(page_main)`；普通非战斗页面仍保持原导航。
- 新增 `tasks/GotoMain/tests/test_battle_guard.py`，覆盖活动战斗页停留和普通页面回主界面两条路径。
- 本轮现场验证的“RealmRaid 不点击”结论需要以补丁后的再次实机验证为准，之前 04:37:51 的 `BATTLE_RESULT_CONTINUE` 点击保留为缺陷证据。

### 2026-08-07 04:44-05:02 第二轮闭环验证

- 离线回归：RealmRaid `88/88`、GeneralBattle `85/85`、Exploration `41/41`、GameUi `13/13`、GotoMain `2/2`；设备/服务相关 unittest 和 `compileall` 通过。
- RealmRaid 单场复测从主界面启动，入口门禁没有误触活动战斗页；按名称预设、目标等级 `58` 棋盘双帧观察、自动模式 ADB 兜底、结果/回板和 checkpoint 提交通过。
- RealmRaid 本轮以 `ticket_reserve_reached` 完成 1 场并回主界面；`green_left3` 两次点击均未确认，且历史长程仍有一次 `GameStuckError`，所以事项保持“部分通过/待补证据”。
- RealmRaid 结束后才启动困28。困28累计达到 30 场，30 次结算完成；地图 `swipe_settle=32`、`swipe_retry=0`、`swipe_skipped=13`，新增错误级日志为 0。
- 困28结算耗时 P50 `8.484s`、P95 `8.969s`，范围 `6.234-8.985s`；加成状态完成读取/切换/恢复，`gold_50` 明确不存在，未误判成功。
- 困28出现 1 次未知场景告警，现场截图证明是正常战斗页转场，随后恢复并完成 30 场；结束后绿标持久配置恢复为开启，账号和任务均停止。
