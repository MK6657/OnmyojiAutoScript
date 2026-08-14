# RealmRaid 保级与左三绿标单场实测（2026-08-10-01）

## 结论

本场程序行为与用户现场观察一致：目标等级 `58` 的保级流程对第 9 个目标先投降四次，随后第五次正式战斗获胜；正式战斗首次点击即把绿色箭头稳定确认到己方左三。任务只消耗 1 张个人突破券，达到临时 `number_attack=1` 的票耗上限后正常结束。

因此，本场满足 RealmRaid 绿标单场门槛。它不能替代后续 3 场和 10 场回归，也不能证明所有快速结束战斗都完成了可观测绿标确认。

## 时序证据

| 时间 | 事件 |
|---|---|
| `14:52:37.398` | 第 1 次投降，目标 9 |
| `14:52:47.849` | 第 2 次投降，目标 9 |
| `14:52:55.923` | 第 3 次投降，目标 9 |
| `14:53:03.894` | 第 4 次投降，目标 9 |
| `14:53:13.443` | 第 5 次进入正式战斗，目标 9 |
| `14:53:21.365` | 左三绿标首次点击确认，点击点 `(679,389)` |
| `14:53:52.913` | 战斗获胜，目标 9 |
| `14:53:52.922` | 票数 `14 -> 13`，命中单票预算停止条件 |
| `14:53:58.883` | `TASK_END outcome=returned success=True` |

结构化绿标结果：

```json
{
  "status": "confirmed",
  "target": "green_left3",
  "click_point": [679, 389],
  "marker_point": [624, 224],
  "detector": "color-contour-tip-slot",
  "attempts": 1,
  "color": "green",
  "expected_slot": "green_left3",
  "assigned_slot": "green_left3",
  "marker_tip": [624, 224],
  "stable_frames": 2,
  "confidence": 0.8182278877534812,
  "reason": "2/3 stable frames: expected_candidate"
}
```

## checkpoint 与棋盘

- 程序结束 checkpoint：`failure_count=4`、`success_count=1`、`observed_broken=[9]`、`pending_action=none`。
- 程序结束棋盘截图显示第 9 个目标“臻如月”已击破，攻击记录为 1。
- 用户随后手动再战一场，第二张截图显示第 8、9 个目标均已击破，攻击记录为 2。该手动结果证明操作可行，但不替代程序绿标结构化证据。
- `config/oas1.json` 已恢复原配置，SHA-256 为 `635A3F54A00CCA2767FDF07024A69C6447827C33BB53951037312BB8C933C28F`。
- `oas1` 任务实例已停止；Core、Bridge、前端已用标准启动器重启，Bridge 报告账号 `offline`。

## 快速胜利边界

业务结果和检测结果必须分开记录：

- 战斗胜利始终记为业务成功，绿标是非阻断优化，不得因为绿标未确认而否定胜利。
- 只有连续稳定帧显示正确颜色和正确槽位时，`GreenMarkResult.status` 才能记为 `confirmed`。
- 若战斗在确认窗口内过快进入终态，绿标记为 `terminal`，原因为 `battle terminal appeared during green mark confirmation`；业务层仍记胜利并继续流程。
- 对用户可显示“战斗已完成，绿标未需继续确认”，但内部不得把 `terminal` 或 `unconfirmed` 改写为 `confirmed`，否则无法发现真实绿标回归。

当前代码已具备该分层：绿标终态会立即停止重试，随后由 `battle_wait()` 继续确认胜负；`BattleOutcome` 单独保存最终胜负及 `green_mark_status`。

已增加两项回归：终态结果只允许一次绿标点击且不宣称确认；绿标状态为 `terminal` 时战斗胜利仍保持 `BattleOutcome.VICTORY`。GeneralBattle 全套 `110/110` 通过。

## 证据文件

证据目录：`D:\OSAyys\output\evidence\green_mark\20260810-145237-realmraid-single`

| 文件 | SHA-256 |
|---|---|
| `oas1-full.log` | `CE4A6F01D2C71A06253C3CF9B8A6366A87073ECCD79282B8E74CBF1747888232` |
| `checkpoint-after-program.json` | `052A315549D8CC58EC23C28E73D8AAA4D87D28885489E659D48723F30480534A` |
| `config-restored.json` | `635A3F54A00CCA2767FDF07024A69C6447827C33BB53951037312BB8C933C28F` |
| `board-after-program.png` | `E0A967C36A4695119EE1B9EE108A74DE391CC9FF950144B2483A56A4634AA354` |
| `board-after-user-manual.png` | `6EF03CE26661C48E5A254F509CC5CDA0A4AD1E187B48190B7741F0AC89E944F2` |

## 当前状态

- RealmRaid 左三绿标：单场通过。
- RealmRaid 保级“退四打九”：本场再次通过。
- RealmRaid 3 场、10 场：待实测。
- 快速结算早于绿标确认：代码语义已正确分层，仍需专门实机样本验证。
- 生产默认保持 `OAS_GREEN_MARK_COLOR_SLOT_MODE=detect_only`；本场仅在临时服务环境启用 `enforce`，服务已按标准入口重启恢复。
