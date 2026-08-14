# RealmRaid 绿标快速采样与阵容锁定复测（2026-08-10-04）

## 结论

本轮以修复后的快速受保护取帧代码执行 RealmRaid，实际票数 `5 -> 3`，达到 2 张真实票消耗预算后正常退出。期间发生 3 个战斗结果：目标 9 胜利、目标 5 失败、目标 5 胜利；失败场没有消耗突破券，因此执行 3 场但只消耗 2 张票，预算行为正确。

两次执行绿标均得到结构化 `confirmed`，颜色为绿色、归属槽位为 `green_left3`、稳定帧数为 2，快速采样修复取得 `2/2` 实机通过。两次锁定后的自动开战各只输出一条最终 `LOCK_VALIDATION=verified`，没有再次出现同一转场重复成功日志。

本轮只能证明左三和阵容锁定正常路径，不能替代左一至左五、红标、错误槽位、锁图标陈旧或自动开战失败等边界证据。

## 环境

- 账号：`oas1`，唯一任务实例，run_id `13e18e903042`。
- 设备：`127.0.0.1:16384`，MuMu 实例 0，窗口标题 `2301`；同时存在干扰设备 `emulator-5554`。
- 截图：Nemu IPC，`1280x720`；被动证据帧间隔 `0.20s`。
- 临时任务配置：票数预算 2、目标等级 58、阵容锁定开启、命名预设“日常/结界突破”、绿标目标 `green_left3`。
- 临时绿标模式：仅本轮 `enforce + diagnostics`；结束后恢复标准 Core 环境。
- 实机前备份：`D:\OSAyys\backups\pre-realmraid-fast-sample-retest-20260810-192445`。

## 时序与业务结果

| 时间 | 事件 |
|---|---|
| `19:26:56–19:27:33` | 目标等级策略对第 9 格完成四次主动投降；每次真实战斗结束后重新确认阵容锁定 |
| `19:27:35.446` | 第一次正式进攻看到准备页，开始观察锁定自动开战 |
| `19:27:36.030` | 未点击准备进入真实战斗，锁定效果验证成功；本次转场只记录一次 |
| `19:27:43.684` | 第一次左三绿标结构化确认 |
| `19:27:51.353` | 目标 9 胜利 |
| `19:28:11.083` | 目标 5 失败，失败数更新为 5；未消耗突破券 |
| `19:28:13.750` | 再次进攻看到准备页，开始观察锁定自动开战 |
| `19:28:15.124` | 未点击准备进入真实战斗，锁定效果验证成功；本次转场只记录一次 |
| `19:28:21.200` | 第二次左三绿标结构化确认 |
| `19:28:29.669` | 目标 5 胜利 |
| `19:28:29.678` | 票数 `3/30`、实际消耗 2，按 `ticket_spend_limit_reached` 正常退出 |
| `19:28:35.448` | RealmRaid 任务结束 |

日志中正式进攻前的四条 `LOCK_AFTER_BATTLE` 不是空转：它们逐一对应目标等级策略的四次主动投降。阵容锁定需要在每次投降后恢复，因此属于预期流程。

## 结构化绿标结果

第一次：

```json
{
  "status": "confirmed",
  "target": "green_left3",
  "click_point": [682, 342],
  "marker_point": [626, 258],
  "detector": "color-contour-tip-slot",
  "frame_sha256": "722ccb4e2557d0cdcdab0811392fa4347673b9143f196434fad8984ded9413ae",
  "attempts": 2,
  "reason": "2/3 stable frames: expected_candidate",
  "color": "green",
  "expected_slot": "green_left3",
  "assigned_slot": "green_left3",
  "stable_frames": 2,
  "confidence": 0.8226785714285714
}
```

第二次：

```json
{
  "status": "confirmed",
  "target": "green_left3",
  "click_point": [679, 379],
  "marker_point": [626, 259],
  "detector": "color-contour-tip-slot",
  "frame_sha256": "622c334c947190140304c3b66546e780c61157094b78ba0076555eb1505a3ad0",
  "attempts": 2,
  "reason": "2/3 stable frames: expected_candidate",
  "color": "green",
  "expected_slot": "green_left3",
  "assigned_slot": "green_left3",
  "stable_frames": 2,
  "confidence": 0.8286135033953649
}
```

被动证据帧也连续覆盖两个绿色箭头窗口：第一次为 `0620-124.00.png` 至 `0626-125.22.png`，第二次为 `0810-162.00.png` 至 `0815-163.02.png`。这与任务内快速采样的两个结构化结果相互印证。

## 证据与哈希

证据目录：`D:\OSAyys\output\evidence\realm_raid\20260810-192534-fast-sample-retest`

| 文件 | SHA-256 |
|---|---|
| `oas1-full.log` | `E393854A6803187092E49F3E5157806BD64AD8DA2E6A2491ACCF597E1B9A9D0B` |
| `config-restored.json` | `635A3F54A00CCA2767FDF07024A69C6447827C33BB53951037312BB8C933C28F` |
| `manifest.json` | `2965E94F94F6A4515F3529B044E7A0BB110CA0F09658C9FD7ECB7AFE4383AE69` |
| `0620-124.00.png` | `7071CC32463B542CF779E2ED4BCD365FBA8FF968A8ABEA87BC133E27FC2BB343` |
| `0621-124.20.png` | `4BECE5E2287600890EEE5E0394910CC04BDEB57B4D878F6C16F61CB6D9808D63` |
| `0810-162.00.png` | `B54F98B1003C60925D15E05C53E566435B919A13E96CD6A596F4B02E05705544` |
| `0811-162.20.png` | `627F7473EF762340A57CDC153A269D250E49363BE3A1CD0AC5F134C75EDE453F` |
| `0900-180.02.png` | `A455AA3083CB1C223BB265990C5227F142550F0E9888F2D009443D4688C06B6D` |

## 恢复状态与下一门槛

- `oas1` 已停止，Bridge 实测状态为 `offline`、选中任务数 0；Core 已以标准环境重新启动。
- `config/oas1.json` 已恢复 SHA-256：`635A3F54A00CCA2767FDF07024A69C6447827C33BB53951037312BB8C933C28F`。
- 左三快速采样从“代码完成、待实测”推进为“实机 `2/2` 通过”。
- 下一门槛是 3 次新的真实进攻结构化确认且错误槽位为 0；通过后再决定是否做 10 场。
- 五槽位、红标样本和锁定异常路径继续开放，不能据本轮建立结案记录。
