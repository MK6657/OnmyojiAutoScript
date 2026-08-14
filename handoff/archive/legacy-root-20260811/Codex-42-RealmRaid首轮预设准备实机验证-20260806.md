# Codex-42 RealmRaid 首轮预设准备实机验证

日期：2026-08-06
账号：`oas1`
设备：MuMu `2301`
范围：只验证 RealmRaid 的战斗前准备、进入棋盘、首场挑战和异常收束；不做长程刷票，不验证绿标正确性。

## 1. 测试环境

测试前通过 `control-center/start.ps1 -RestartAll -NoBrowser` 重启了真实三层服务：

- Core：`127.0.0.1:22267`
- Bridge：`127.0.0.1:22367`
- Frontend：`127.0.0.1:4175`
- Bridge 健康探针：`core=ok`、`bridge=ok`、`integration_test=false`
- ADB：识别到 `emulator-5554 device`

为隔离预设链路，本轮只启用 `oas1/RealmRaid`，暂时将 `general_battle_config.green_enable` 改为 `false`。测试收束后已恢复为 `true`，并恢复原来的 `scheduler.next_run=2026-08-06 17:27:19`；RealmRaid 任务当前保持禁用，未留下自动重跑。

测试时的关键配置：

| 配置 | 值 |
| --- | --- |
| 目标等级 | `58` |
| 队伍预设 | `日常 / 结界突破` |
| 队伍预设启用 | `true` |
| 按名称换御魂 | `true` |
| 御魂预设 | `日常 / 结界突破` |
| 阵容锁定 | `false` |
| 随机点击/滑动 | `true` |
| 绿标 | 本轮临时关闭，结束后恢复 `true` |

## 2. 已验证成功的链路

日志时间以 `log/2026-08-06_oas1.txt` 为准：

1. `10:22:06` 输出 `PREPARE_START team_requested=True, soul_requested=True, lock_desired=False`。
2. 从主界面进入式神录和预设页，OCR 识别到分组 `逢魔/秘闻/日常`，随后识别到 `结界突破/困28/道馆速攻阵容` 等队伍名。
3. 点击 `日常` 分组和 `结界突破` 队伍，识别到预设确认弹窗并点击确认。
4. 日志出现 `Preset team 结界突破 applied`，同时应用结果文本包含“预设队伍、素材、结界突破、阴阳师、契灵、成功、装备御魂、成功”等内容。
5. 输出：

   - `TEAM_PRESET_RESULT result=applied`
   - `SOUL_PRESET_RESULT result=covered_by_team_preset`
   - `PREPARE_RESULT result=ready team=True, soul=True, lock_desired=False`

6. `10:22:47` 到达 `page_realm_raid`，并识别到队伍为未锁定。
7. 目标等级模式启用：`target=58, single_step=False`。
8. 棋盘识别到第 9 格可攻击目标，目标选择证据为勋章匹配；点击后日志出现 `RealmRaid attack transition confirmed: target=9`。

结论：本轮已证明“重启后真实 Core 加载新代码、按名称选择队伍预设、预设确认、预设附带御魂安装、进入个人突破棋盘、目标选择和进攻点击”均能走通。当前问题不在预设入口或坐标死区。

## 3. 实机异常

首场进入战斗后，任务没有等待战斗结束：

1. 日志先出现 `Start battle process`。
2. 随后在真实战斗阶段错误出现：

   - `RealmRaid milestone reward overlay detected during battle result`
   - `RealmRaid milestone reward overlay cleared`
   - `Battle result continue prompt detected and dismissed`

3. 紧接着棋盘等待器识别到：

   - `RealmRaid board wait stopped: still in real battle`
   - `Level mode exit: outcome=deferred, reason=attack_unconfirmed`

4. 调度器把下一次 RealmRaid 排到 `10:27:59`，当前任务结束并尝试执行 `Goto main page`。由于游戏实际仍在战斗页，后续连续出现 `Unknown ui page remains`、`Starting from current page is not supported`，最后输出 `Task call: restart (skipped because disabled by user)`。
5. 桌面截图复核显示：`2301` 仍是实际战斗画面，不是棋盘、主界面或保护页。画面中仍有敌我单位、行动条和技能按钮。截图复核时没有执行额外点击，保留了异常现场。

## 4. 根因链

### 4.1 高置信根因：奖励检测抢占了战斗结果判断

当前 `tasks/RealmRaid/script_task.py` 的 `RealmRaid._dismiss_battle_result_continue()` 在通用 `battle_wait()` 的最前面调用 `level_reward_overlay_visible()`。该函数允许以下任一条件成立：

- `I_SOUL_RAID` 模板匹配；
- 宽范围颜色/变暗启发式匹配。

真实战斗画面中，奖励图标 ROI 或启发式条件被误命中。随后 `dismiss_level_reward_overlay()` 点击屏幕中心，并在检测条件消失后直接返回 `True`。它没有同时确认“当前已离开真实战斗”或“确实存在结算/奖励页”。于是 `battle_wait()` 将仍在进行中的战斗当成了已处理的结果，返回给 `run_general_battle()`。

证据是：代码调用链允许“奖励检测成功 -> 返回 True”，而同一秒的日志和桌面截图又证明游戏仍处于真实战斗；这是静态代码与实机状态的交叉吻合，不是单纯 OCR 推断。

### 4.2 放大问题：棋盘等待器只能发现已发生的错误，不能阻止任务退出

`wait_level_board()` 发现 `is_in_real_battle(False)` 后立即返回 `False`，`execute_level_attack()` 将其转为 `None`，`run_level_mode()` 再以 `attack_unconfirmed` 调用 `finish_level_mode()`。此时任务已经进入“结束/重新调度”路径，但没有一个收束状态表示“战斗仍在进行，不能结束当前任务”。

### 4.3 收束问题：退出任务时没有处理“仍在战斗”状态

`finish_level_mode()` 会尝试点击棋盘返回按钮并导航主界面。真实战斗页没有棋盘返回按钮，也不是 `GameUi` 支持的起始页，所以出现 `Unknown ui page`。这解释了为什么任务看起来已经返回调度器，但游戏画面仍停在战斗中。

### 4.4 待单独确认的附加风险：战斗自动/手动状态

异常现场截图左下角显示 `手动`。仅凭按钮文字不能直接断定当前模式语义，需要下一轮在进入战斗前后确认游戏按钮的“当前状态/点击后状态”。但即使当前确实是自动，奖励检测误判也足以解释本轮的提前退出；因此自动/手动不是本轮首要根因。

## 5. 修复建议，暂不实施

1. **先修结果判定边界。** RealmRaid 的 `_dismiss_battle_result_continue()` 不得只凭奖励模板或启发式返回成功。至少要同时满足“结果页/结算提示证据”和“`is_in_real_battle(False)` 已确认”，否则把检测交回 `battle_wait()`继续等待。
2. **收窄奖励检测时机。** `I_SOUL_RAID` 和颜色启发式只允许在已经确认战斗结束、且棋盘返回标记或结算页证据出现后使用；不能在通用 `battle_wait()` 的实时战斗循环中抢占判断。
3. **增加战斗进行中的显式状态。** `wait_level_board()` 不要把“仍在战斗”折叠成普通 `False`。建议返回可区分的结果，例如 `BATTLE_IN_PROGRESS`，由上层等待有限时间或走任务级短重试，不能直接调用 `finish_level_mode()`。
4. **任务结束前加安全闸。** `finish_level_mode()` 在 `is_in_real_battle(False)` 仍为真时，不应执行主界面导航和下一轮调度；应先记录 `battle_in_progress`，等待战斗收束或进入人工接管/短重试。
5. **补一条实机回放测试。** 固化一帧当前真实战斗画面和一帧真实奖励页，验证：真实战斗帧不能触发 `level_reward_overlay_visible()`；奖励页可以被识别并点击；战斗结果确认后才允许进入棋盘 OCR。
6. **补自动/手动状态验收。** 记录进入准备页、点击准备后、进入真实战斗后三帧截图，明确左下角按钮语义，并让通用战斗准备在需要时确认自动模式。

## 6. 当前收束状态

- RealmRaid 任务：已禁用。
- `oas1`：已停止，当前没有运行、等待或挂起任务。
- Core/Bridge/Frontend：仍健康运行，便于后续继续测试。
- 绿标：已恢复为测试前的 `true`。
- 原始 `next_run`：已恢复为 `2026-08-06 17:27:19`。
- 游戏：仍停留在本轮异常留下的真实战斗画面；本轮没有用人工点击掩盖现场，也没有继续消耗票。

## 7. 验收标准

修复后首轮最小验收应同时满足：

- 预设链路仍输出 `TEAM_PRESET_RESULT=applied`、`SOUL_PRESET_RESULT=covered_by_team_preset`、`PREPARE_RESULT=ready`。
- 进入战斗后，在真实战斗持续期间不得出现“奖励弹窗已清除”或“结果页已确认”的日志。
- 只有实际战斗结束并回到棋盘后，才开始棋盘 OCR 和成功/失败计数。
- 若战斗仍在进行，任务不能结束、不能调度下一轮、不能盲目导航主界面。
- 结算后能回到棋盘，提交一次成功/失败证据，再决定下一步，不要求本轮直接完成长程刷票。

