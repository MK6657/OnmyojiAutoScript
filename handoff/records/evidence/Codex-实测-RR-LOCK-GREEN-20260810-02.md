# RealmRaid 阵容锁定与左三绿标两场实测（2026-08-10-02）

## 结论

本次用 2 张个人突破券完成了“首场准备 -> 战后锁定 -> 下一场自动开战”的效果闭环：两场均胜，票数 `9 -> 7`；第二场程序没有点击准备，锁定状态在约 `0.6` 秒内自行进入真实战斗。因此 `RR-LOCK-001` 的正常锁定路径通过实机验证。

绿标必须单独统计：两场业务均胜，但结构化绿标结果为 `1 confirmed + 1 skipped`。这证明绿标失败保持非阻断符合设计，同时也说明 RealmRaid 多场绿标稳定性尚未通过，不能用战斗胜利改写为绿标确认。

## 环境

- 账号：`oas1`，唯一运行实例，run_id `9a4538cacd7d`。
- 设备：`127.0.0.1:16384`，MuMu 实例 `0`，窗口标题 `2301`；同时存在干扰设备 `emulator-5554`。
- 截图：Nemu IPC，`1280x720`，逐帧留证间隔 `0.25s`。
- 临时配置：`number_attack=2`、`lock_team_enable=true`、`green_enable=true`、`green_left3`、命名预设“日常/结界突破”。
- 绿标模式：仅本轮临时 `enforce`；结束后已按标准入口重启，恢复默认诊断模式。

## 时序

| 时间 | 事件 |
|---|---|
| `16:59:36.193` | 第一场按设计点击准备一次；首场尚未锁定 |
| `16:59:43.745` | 第一场绿标 `skipped`，自动/战斗状态在验证窗口内变为不确定 |
| `16:59:55.379` | 战后锁图标确认，仅记录 `validation=pending_next_battle` |
| `16:59:55.382` | 第一场目标 5 胜利，票数变为 8 |
| `16:59:57.785` | 第二场看到准备页，进入 `2.5s` 锁定效果观察窗口 |
| `16:59:58.380` | 未点击准备即进入战斗，`LOCK_VALIDATION state=verified` |
| `17:00:05.889` | 第二场左三绿标稳定确认，绿色、槽位 left3、连续 2 帧 |
| `17:00:25.136` | 第二场目标 1 胜利 |
| `17:00:25.148` | 票数为 7，命中 `ticket_spend_limit_reached` |
| `17:00:31.181` | `TASK_END outcome=returned success=True` |

第二场从进入锁定观察到确认只经过约 `0.595s`。本次完整日志中，`16:59:36.193` 之后没有第二条 `Prepare button clicked`，可排除程序抢点准备。

## 绿标结果

第一场：

```json
{
  "status": "skipped",
  "target": "green_left3",
  "click_point": [594, 392],
  "max_score": 0.7621287703514099,
  "attempts": 2,
  "reason": "battle or auto mode became unconfirmed during marker verification",
  "expected_slot": "green_left3",
  "stable_frames": 0
}
```

第二场：

```json
{
  "status": "confirmed",
  "target": "green_left3",
  "click_point": [679, 384],
  "marker_point": [626, 258],
  "detector": "color-contour-tip-slot",
  "max_score": 0.7284360527992249,
  "attempts": 2,
  "reason": "2/2 stable frames: expected_candidate",
  "color": "green",
  "expected_slot": "green_left3",
  "assigned_slot": "green_left3",
  "marker_tip": [626, 258],
  "stable_frames": 2,
  "confidence": 0.8145157976909487
}
```

## checkpoint 与恢复

- 结束 checkpoint：`revision=40`、`failure_count=4`、`success_count=7`、`observed_broken=[1,2,3,5,6,8,9]`、`pending_action=none`。
- `config/oas1.json` 已恢复为测试前 SHA-256：`635A3F54A00CCA2767FDF07024A69C6447827C33BB53951037312BB8C933C28F`。
- `oas1` 已停止，Bridge 报告 `offline`、任务实例数 0。
- Core、Bridge、前端已恢复标准启动环境；最终截图为庭院。

## 证据

证据目录：`D:\OSAyys\output\evidence\realm_raid\20260810-165100-lock-validation-2`

| 文件 | SHA-256 |
|---|---|
| `oas1-full.log` | `3F1A77816B5923CEB537F8739DE688B2859843869B433A3FFDE6242F27C9CE69` |
| `checkpoint-after.json` | `5507ED7771FF00BF0B694C304AF0C16F3E5CF2CF697B7626D848DFFB3E94F6EF` |
| `config-restored.json` | `635A3F54A00CCA2767FDF07024A69C6447827C33BB53951037312BB8C933C28F` |
| `manifest.json` | `033A7CB889902B9132FC7C528E62ED75E9CE7F32E004BEF7F6014375A2417315` |
| `0580-145.02.png`（第二个目标选择前） | `E3AA024EC48316C8609C83CC7F9D5A2EE2F23B40A9B22035075EE77EF9334D7B` |
| `0584-146.00.png`（第二个目标进攻确认） | `711A2A6BF6287E80C4B47868811D50771B37530557669044556ABB516389D9FE` |
| `0592-148.02.png`（锁定自动开战过渡） | `E6E6A135E9F596A3A31A38C8FACA4BCD968D826295D9295EF3701A663066732E` |
| `0596-149.00.png`（真实自动战斗） | `E0E8EDF679A7EEDDC62771D3962814C186625A926C037E3C9A13131DDE154340` |
| `post-task-main.png` | `CC246F2DD770D5FDB13BABFC50B6D12C0AB963546BDEDC588142A6871B824892` |

## 当前状态

- 阵容锁定正常路径：实机通过。
- 锁图标失配或准备持续存在的兜底路径：离线通过，仍待真实异常样本。
- 左三绿标：单场曾通过，本轮两场仅 `1/2` 结构化确认；多场稳定性未通过。
- 不执行 10 场绿标扩展；先诊断第一场 `skipped` 的自动状态/截图时机，再决定是否修改检测器。
