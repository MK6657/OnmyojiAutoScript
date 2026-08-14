# Codex-19 困28补券与个人突破锁定识别实测

日期：2026-08-04
账号：oas1
窗口：MuMu 2301
状态：本轮真实回归已完成一部分；当前突破券为0，绿标新坐标需下次补券后继续现场确认。本文件区分已验证、已修复和待验证项。

## 1. 本轮目标

1. 运行困28约30场，获取个人突破券。
2. 进入目标等级58的个人突破卡级流程。
3. 观察预设队伍、预设御魂、绿标、锁定状态、调度退出和后续恢复。
4. 遇到异常先保留日志和根因线索，后续单独修复。

## 2. 困28闭环

- 配置：第28章，单人战斗次数30，目标上升类型为红达摩。
- 结果：2026-08-04 20:56:18 开始第30场，20:56:24 战斗胜利。
- 20:56:27 记录 `Minions count is enough, exit`，随后退出探索并返回庭院。
- 探索任务正常结束，下一次探索被写入2026-08-05 20:48:07，没有出现31场或重复战斗。
- 期间的 `Unknown scene` 均在短时间内恢复到入口或主界面，未形成任务级卡死。
- 金50、金100、经验50、经验100 buff 均被识别并处理。

## 3. 个人突破配置快照

- `scheduler.enable=true`
- `level_mode_config.enable=true`
- `level_mode_config.target_level=58`
- `level_mode_config.single_step=false`
- `raid_config.number_attack=30`
- `raid_config.number_base=0`
- `raid_config.exit_four=true`
- `raid_config.when_attack_fail=Refresh`
- `general_battle_config.preset_enable=true`
- `general_battle_config.preset_group_name=日常`
- `general_battle_config.preset_team_name=结界突破`
- `general_battle_config.green_enable=true`
- `general_battle_config.green_mark=green_left3`
- `general_battle_config.lock_team_enable=false`
- `switch_soul_config.enable=false`

## 4. 预设应用证据

个人突破在20:58:22启动后，先从庭院进入式神录预设页：

- 20:58:27 按名称查找 `日常 / 结界突破`。
- 分组列表和队伍列表均执行了滑动扫描，说明当前名称选择器覆盖了可滚动列表。
- 20:58:50 点击目标队伍的应用按钮。
- 20:58:51 记录 `Preset team ... is already active`。
- 20:58:52 记录 `Switch preset by name completed`，随后返回主界面并进入个人突破。

结论：本轮至少确认“庭院式神录 -> 分组/队伍名称 -> 应用预设 -> 返回个人突破”的入口链路已执行；因为当前队伍已处于目标预设，尚不能据此证明发生了实际队伍变更或御魂变更。

## 5. 当前异常

个人突破页面已在20:58:58到达。20:59:00出现：

```text
Ensure team unlock timeout after 2s
RealmRaid team lock state is unconfirmed; pause and retry at 2026-08-04T21:04:00
Level mode exit: outcome=deferred, reason=team_lock_unconfirmed
```

随后程序通过 `RES_BACK_RED` 返回庭院，并将 `realm_raid.scheduler.next_run` 写为21:04。没有进入目标挑战，没有消耗突破券，也没有重启游戏或停止 Core/Bridge。

21:04重试结果相同：

- 21:04:38 到达个人突破页。
- 21:04:38-21:04:41 再次执行 `Ensure team unlock (timeout 2s)`，仍未识别锁定或未锁定图标。
- 21:04:41 记录 `team_lock_unconfirmed`，返回庭院并把下一次重试写为21:09:41。
- 两次失败均未消耗突破券，说明安全门和任务退出链路生效；也说明该问题不是一次性页面动画或调度竞态。

21:04:47 通过 Bridge 暂停 `RealmRaid` 调度，避免休息期间每5分钟重复进入并退出；没有停止 Core、Bridge、游戏或探索任务。

## 6. 初步根因判断

- 不是调度器未拉起：日志明确有 `Scheduler: Start task RealmRaid`。
- 不是预设名称找不到：预设应用完成日志已出现。
- 不是游戏崩溃：页面导航和返回主界面均正常。
- 直接阻塞点是个人突破页锁定/未锁定图标在2秒内没有被当前模板识别。
- 该结论暂不等于模板本身错误，也可能是进入页面后的遮罩、页面动画或识别 ROI 与当前版本画面不一致；需等待自动重试观察是否稳定复现。

复现两次后，当前更可能是锁图标资源或 ROI 与这版个人突破页面不匹配。`ensure_lock()` 同时尝试旧位置 `I_LOCK/I_UNLOCK`（约 `(814,578)`）和适配呱太入口的位置 `I_LOCK_2/I_UNLOCK_2`（约 `(1002,643)`），但两组模板均未命中；仍需用当前个人突破页原始截图确认实际图标位置和样式，不能仅凭日志直接改坐标。

安全行为符合当前设计：状态不确定时不继续消耗票，不把超时当作“已解锁”，短延时后再调度。

## 7. 待续验证

1. 观察21:04自动重试是否仍在同一位置超时。
2. 若复现，保留进入个人突破页的截图和锁图标 ROI，对照 `tasks/RealmRaid/assets.py` 与 `tasks/RealmRaid/res/image.json`。
3. 若锁状态识别通过，再继续验证目标等级58的退四打九、票数消耗、绿标和自动换盘。
4. 本轮不因该问题直接修改代码；修复前先与 Codex-18、Codex-20/21 的历史证据对照。

## 8. 定位与最小修复

后续取证确认模板和坐标本身没有失效：

- 程序自身 `nemu_ipc` 读取的当前1280x720帧保存在 `log/board/manual_current_lock_state_20260804.png`。
- 该帧中 `I_LOCK` 在 `(814,577)` 命中，模板匹配分数约0.91。
- 手动点击一次锁图标后，画面在约1秒内切换为未锁定状态；新帧中 `I_UNLOCK` 命中，`I_LOCK` 不再命中。
- 两次自动失败都发生在页面到达后约0.3秒开始、约2.1秒结束的 `Ensure team unlock (timeout 2s)` 窗口内。

因此本轮采用最小修复：

- `tasks/RealmRaid/script_task.py`：目标等级模式的锁状态等待从2秒调整为5秒；普通模式仍为12秒。
- `tasks/RealmRaid/tests/test_setup_guard.py`：增加超时参数断言，防止目标等级门禁被再次缩回2秒。

验证结果：`test_setup_guard` 与 `test_lock_assets` 共3项通过，Python编译检查通过，`git diff --check` 无错误。

修复后真实回归尚未完成；RealmRaid 调度仍保持暂停，等待下一节记录单次自动启动结果。

## 9. 相关日志与证据

- `log/2026-08-04_oas1.txt`
- 关键时间段：20:58:22-20:59:09
- 第二次复现：21:04:04-21:04:49
- `log/board/manual_current_lock_state_20260804.png`
- `log/board/manual_after_lock_toggle_20260804.png`

## 10. 22:04-22:33 真实回归与新根因

### 10.1 不是宿主窗口缩放

- OAS 实际读取的错误现场截图为 `1280x720`。
- `module/device/screenshot.py` 对截图尺寸做了 `1280x720` 校验；日志中的 minitouch 触摸轴为 `720x1280`，方向为1。
- 对话中看到的 `741x416` 是截图展示缩放，不会改变 Nemu IPC 截图或 minitouch 的设备坐标。
- 因此本轮不把问题归因于 Windows 窗口缩小或 DPI 缩放。真正风险是上游固定绿标区域与当前游戏版本的战场布局不一致。

### 10.2 结界突破没有局内快捷预设

22:26 与 22:27 的成功战斗均出现：

```text
Reuse preset pre-applied before entering this task
```

这说明 RealmRaid 先在庭院式神录完成 `日常 / 结界突破` 预设应用，进入个人突破后的 GeneralBattle 没有再次打开局内快捷预设。当前现场没有证据表明结界突破页误点击了快捷预设；停留准备页的直接原因是战斗状态转场确认失败。

### 10.3 准备页与实战页状态冲突

22:04 现场仍停留在右下角“准备”页，但准备页同时有好友图标。旧 `is_in_battle()` 把好友图标当成实战证据，导致流程直接进入 `battle_wait()`，约两分钟后才触发 `GameStuckError`。

22:27 第六场进一步证明了“转场慢”边界：程序已点击准备，约5秒内未确认实战便安全返回；但错误截图 `log/error/1785853682956/2026-08-04_22-28-02-928442.png` 显示游戏随后确实进入了战斗。原来的5秒门禁过短，后续棋盘等待又把仍在战斗中的画面误判为3/6/9奖励并重复点击。

## 11. 本轮已实施修复

- `tasks/Component/GeneralBattle/general_battle.py`：实战判断先排除准备按钮、胜利、失败和奖励页面，再使用稳定的好友图标作为当前战斗主题的兜底证据；战斗前准备等待从5秒延长到15秒，最多重试两次准备点击。
- `tasks/Component/GeneralBattle/general_battle.py`：绿标只在确认进入真正战斗后执行，等待有10秒上限；日志改为带模式和坐标的 `GREEN_MARK:<mode>` 形式，避免在准备页误点。
- `tasks/Component/GeneralBattle/assets.py` 与 `tasks/Component/GeneralBattle/gb/click.json`：按本账号当前战场实测，恢复此前的战场前排绿标区域。`green_left3` 从底部偏移区域 `(608,446,64,44)` 恢复为 `(586,328,100,76)`，避免把阴阳师位置当成第三个前排式神。
- `tasks/RealmRaid/script_task.py`：RealmRaid 每次热加载时同时重载 GeneralBattle 资产，确保绿标坐标修改不被 Python 模块缓存吞掉。
- `tasks/RealmRaid/script_task.py`：棋盘等待发现仍处于实战时立即退出，不把战斗画面当作奖励弹窗；奖励弹窗最多执行3次关闭尝试，防止触发 `TooManyClick`。

## 12. 本轮验证结果

- 22:26:52-22:27:05：第4场进入战斗并胜利，奖励处理完成，棋盘票数从3降至2。
- 22:27:10-22:27:32：第5场进入战斗并胜利，奖励处理完成，棋盘票数从2降至1。
- 22:33:45：无剩余突破券，目标等级模式安全完成并返回主界面，未继续消耗或重复挑战。
- `GeneralBattle` 测试：41项通过。
- `RealmRaid` 测试：56项通过。
- Python 编译检查通过；`git diff --check` 通过。

以上两场真实胜利发生在绿标坐标热重载补丁之前，日志中的点击仍为旧的 `@ Click` 记录。因此“恢复战场前排坐标后确实标记到用户指定式神”暂不能标记为已通过，必须等困28补券后至少完成一场带 `GREEN_MARK:green_left3` 坐标日志的现场验证。

## 13. 下一次验证顺序

1. 困28补券后，先只执行个人突破的一场，确认日志出现 `GREEN_MARK:green_left3` 且坐标落在 `x=586..685, y=328..403`。
2. 对照战斗截图确认绿标落在用户指定的前排式神，不是阴阳师或底部头像栏。
3. 再连续验证战斗胜利、奖励一次性关闭、棋盘回读和剩余票数。
4. 有足够票数后再验证退四打九、自动换盘和目标等级重新判定。
