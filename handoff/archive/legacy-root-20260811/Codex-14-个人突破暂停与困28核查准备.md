# Codex-14 个人突破暂停与困28核查准备

日期：2026-08-04  
分支：`codex/mk6657-secondary-development`

## 1. 当前工作状态

本轮个人结界突破实测暂时停止。用户确认当前已经没有突破券，后续待补充突破券后再回头验证第九胜奖励遮罩、跨棋盘执行和异常恢复。

个人突破最后一次运行停在奖励遮罩误判后的安全退出：

- 日志时间：2026-08-04 09:45 左右。
- 现象：第九胜后奖励遮罩仍在屏幕上，旧进程进入棋盘 OCR，九格等级为 0，票数识别为 `-1/30`。
- 结果：RealmRaid 返回主界面，旧调度将下一次安排到 2026-08-05 09:45:37。
- checkpoint：`output/realm_raid_state/oas1.json` 仍是 `failure_count=4`、`success_count=8`、`pending_action=attack`，只能作为中断现场证据，不能直接当作当前游戏状态。
- 当前 `oas1` 的 RealmRaid 配置没有在本次操作中修改；`level_mode_config.enable=true`、目标等级 58 和原有预设配置均保留，待后续有券后再由用户决定何时恢复测试。

本次已关闭 Codex 自动监控“监控 oas1 个人突破”，自动化编号为 `oas1`。后续不会继续对该账号进行定时状态报告，也没有停止 Core、游戏或其他任务进程。

奖励遮罩根因和修复记录见：

- `Codex-06-个人结界突破阶段奖励稳定等待修复.md`
- `Codex-13-个人突破整任务生命周期修复.md`

## 2. 困28功能入口

“困28”对应 `tasks/Exploration` 的探索任务，实际选择值为 `第二十八章`，不是单独的任务模块。

主要入口和链路：

1. `tasks/Exploration/config.py` 的 `ExplorationLevel.EXPLORATION_28` 和 `exploration_level` 配置。
2. `config/oas1.json` 当前探索配置为 `exploration_level=第二十八章`；探索任务调度开关目前仍以账号配置为准，本轮没有代用户启停。
3. `tasks/Exploration/script_task.py` 只是入口壳，实际流程继承 `tasks/Exploration/solo.py` 的 `ScriptTask`。
4. `run()` 先识别当前场景；无法识别时最多随机点击两次，然后执行 `pre_process()`，按 `user_status` 进入单人、队长或队员流程。
5. `pre_process()` 可切换御魂、开启探索加成并进入探索；`open_expect_level()` 通过章节 OCR 和右侧上下滑动选择第二十八章，最多滑动 15 次。
6. 单人模式在探索场景中寻找普通怪、UP 怪和 Boss，进入通用战斗；每次 `fire()` 后递增 `minions_cnt`。
7. 困28在连续找不到目标后检查 `I_SWIPE_END`；识别到最后一屏后调用 `quit_explore()`，再由 `post_process()` 返回庭院并结束本次探索任务。
8. `check_exit()` 同时受战斗次数 `minions_cnt`、运行时长 `limit_time` 和绘卷模式影响；绘卷模式达到突破券阈值时会提前安排 Exploration、RealmRaid 和 MemoryScrolls。

## 3. 后续核查重点

本阶段先审核和实测，不直接重构困28：

- 章节选择：第二十八章 OCR、滚动方向、15 次上限和“最后一屏”识别是否适配当前游戏画面。
- 战斗目标：`up_type=up_all` 时普通怪/Boss 的识别顺序；目标按钮消失后是否可能误滑、漏怪或重复点击。
- 探索结束：`I_SWIPE_END` 与动画稳定判断是否会提前退出或在最后一屏卡住；`quit_explore()` 的超时兜底是否会多次点击返回。
- 次数和时长：`minions_cnt` 是否按实际完成战斗计数，`limit_time` 是否能在未知场景、战斗和退出流程中生效。
- 预设链路：探索内部强制 `lock_team_enable=True` 的副作用；通用队伍预设、御魂切换、绿标和探索任务的复用关系。
- 任务联动：绘卷阈值触发 RealmRaid 时的票数 OCR、调度写入和异常恢复，避免再次影响其他任务。
- 三种模式：单人、队长、队员是否共用正确的返回和结束逻辑；本轮优先验证单人困28。

## 5. 当前配置快照

`config/oas1.json` 中与困28直接相关的配置目前是：

```text
exploration.scheduler.enable = false
exploration_level = 第二十八章
user_status = alone
minions_cnt = 30
limit_time = 00:30:00
up_type = up_all
auto_rotate = 不
scrolls_enable = false
general_battle_config.preset_enable = false
switch_soul_config.enable = false
```

因此当前账号没有被本轮操作安排去执行困28；上面的配置只作为代码审查基线。

## 6. 初步问题清单

以下问题来自源码链路，尚未经过当前游戏版本的实机画面确认：

1. `open_expect_level()` 的章节选择第二阶段没有总超时。如果章节 OCR、确认按钮或探索入口模板持续失效，可能一直循环；第一阶段虽有 15 次滑动上限，但第二阶段没有对应上限。
2. `wait_world_stable()` 没有总超时。如果右侧箭头模板失效或场景一直被遮挡，可能停在等待循环。
3. `quit_explore()` 只有 15 秒局部计时器，计时到达后会重置并继续点击返回，没有整个退出流程的硬上限；需要确认不会在弹窗/场景识别异常时反复返回。
4. `BaseExploration.fire()` 调用 `run_general_battle()` 后不检查返回值，就增加 `minions_cnt`。这会把战斗失败、超时或结果未确认也算作一次探索战斗；需结合用户对“战斗次数”的定义确认是否应改为只统计已确认完成的战斗。
5. `BaseExploration._config` 会强制把 `general_battle_config.lock_team_enable` 设为 `True`。通用战斗在锁阵容时不会执行 `general_battle_config` 的队伍预设切换，因此探索配置里的队伍预设即使打开也可能被绕过；独立的 `switch_soul_config` 仍会在进入探索前执行。
6. 困28末屏使用固定 `I_SWIPE_END` 模板和 `RuleAnimate` 双重判断，但仓库没有困28专用的离线测试或当前版本实机截图回归；这是本轮最需要优先实测的识别点。
7. `up_all` 直接在全屏寻找普通战斗按钮；指定经验、金币或达摩时则改为围绕 UP 图标缩窄 ROI 并以 0.9 阈值匹配。两套路径的漏怪、误点和滑动时序需要分别验证。
8. `check_exit()` 每轮都会检查绘卷模式；当前绘卷模式关闭，所以不会触发 RealmRaid 联动。开启后会同时改写 Exploration、RealmRaid、MemoryScrolls 的下一次执行时间，属于跨任务副作用，暂不在本轮改动。

## 7. 困28核查顺序

建议按以下顺序进行单人、小次数实测：

1. 仅确认从庭院进入探索，章节列表能定位并选中第二十八章。
2. 只跑一次普通怪战斗，确认战斗准备、绿标/队伍/御魂配置和战后奖励返回。
3. 观察连续找不到目标时是否正确向右滑动，而不是误判最后一屏。
4. 到达困28最后一屏后确认 `I_SWIPE_END` 触发退出，且不会点击返回到主界面之外或卡在退出弹窗。
5. 最后才验证 30 次/30 分钟结束、队长/队员模式和绘卷联动。

实测前需要保留每个阶段的 OAS 原始截图和日志；如果要先做最小风险测试，建议把 `minions_cnt` 临时设为 1，并只启用单人探索，测试完成后恢复原值。配置修改由用户确认后再做，本轮不代改。

## 8. 暂不修改项

当前不修改 `tasks/Exploration` 代码、不调整 `config/oas1.json` 的探索或RealmRaid开关、不清理旧 RealmRaid checkpoint。先完成困28的源码链路审查和必要的离线测试，再由用户提供实际游戏画面或明确测试条件后逐项验证。
