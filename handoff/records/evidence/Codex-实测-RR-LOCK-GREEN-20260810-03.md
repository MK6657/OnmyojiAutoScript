# RealmRaid 阵容锁定与绿标采样两场复测（2026-08-10-03）

## 结论

本轮消耗 2 张个人突破券，完成两场胜利，票数 `7 -> 5`。第一场正常点击一次准备，战后重新锁定；第二场没有准备点击即进入真实战斗。因此 `RR-LOCK-001` 正常路径获得第二次独立实机通过。

绿标结果为 `1 confirmed + 1 unconfirmed`。第二场被动帧证明左三绿色箭头实际连续出现两帧，根因是任务确认取帧过慢，不是坐标或槽位错误。根据该证据完成了快速取帧修复，但修复后的实机复测尚未执行。

## 环境

- 账号：`oas1`，唯一任务实例，run_id `536ef13a8657`。
- 设备：`127.0.0.1:16384`，MuMu 实例 0，窗口标题 `2301`；同时存在干扰设备 `emulator-5554`。
- 截图：Nemu IPC，`1280x720`；被动帧间隔 `0.25s`。
- 临时任务配置：`number_attack=2`、`lock_team_enable=true`、`green_enable=true`、`green_left3`、命名预设“日常/结界突破”。
- 临时绿标模式：仅本轮 `enforce + diagnostics`；结束后 Core 已恢复标准环境。

## 时序

| 时间 | 事件 |
|---|---|
| `18:09:19.450` | 棋盘确认，票数 `7/30` |
| `18:09:24.871` | 第一场点击准备一次 |
| `18:09:31.799` | 第一场左三绿标确认，`2/3 expected_candidate` |
| `18:09:41.238` | 第一场战后锁定图标确认，进入下一场效果验证 |
| `18:09:41.240` | 第一场目标 4 胜利 |
| `18:09:43.781` | 第二场看到准备页，开始锁定自动开战观察 |
| `18:09:44.403` | 未点击准备进入真实战斗，锁定效果验证成功 |
| `18:09:45.503` | 第二场客户端处于手动模式，程序开始自动切换 |
| `18:09:49.034` | ADB 兜底后自动模式确认 |
| `18:09:50.401` | 第二场第一次点击左三 `(595,360)` |
| `18:09:51.09–18:09:51.34` | 被动帧连续两张显示左三完整绿色箭头，尖端 `(626,258)` |
| `18:09:55.564` | 任务确认循环因有效帧不足返回 `unconfirmed` |
| `18:10:04.085` | 第二场目标 7 胜利 |
| `18:10:04.092` | 达到两票预算，票数 `5/30` |
| `18:10:09.856` | RealmRaid 正常结束 |

日志中第二场曾对同一自动开战转场重复输出两次 `LOCK_VALIDATION=verified`。这不代表点击两次，也不影响锁定结果；根因是早期战斗帧再次瞬时误检准备按钮，已在实测后增加单场锁存并通过离线测试。

## 结构化绿标结果

第一场：

```json
{
  "status": "confirmed",
  "target": "green_left3",
  "click_point": [609, 370],
  "marker_point": [626, 259],
  "detector": "color-contour-tip-slot",
  "attempts": 2,
  "color": "green",
  "expected_slot": "green_left3",
  "assigned_slot": "green_left3",
  "stable_frames": 2,
  "confidence": 0.8202418744273318
}
```

第二场（任务原始结果）：

```json
{
  "status": "unconfirmed",
  "target": "green_left3",
  "click_point": [600, 378],
  "attempts": 2,
  "reason": "no stable colored marker was confirmed in the requested slot",
  "expected_slot": "green_left3",
  "stable_frames": 0
}
```

同场被动帧离线分类：

```text
0616-154.02.png -> green / green_left3 / tip=(626,258) / confidence=0.8145418190
0617-154.27.png -> green / green_left3 / tip=(626,258) / confidence=0.8146459044
```

## 恢复状态

- `oas1` 已停止，Bridge 状态 `offline`，任务实例数 0。
- `config/oas1.json` 已恢复 SHA-256：`635A3F54A00CCA2767FDF07024A69C6447827C33BB53951037312BB8C933C28F`。
- 本轮棋盘代次发生变化，checkpoint 按正常分支清除，无 pending action。
- Core 已以标准环境重新启动；绿标生产默认仍为 `detect_only`。

## 证据

证据目录：`D:\OSAyys\output\evidence\realm_raid\20260810-180714-lock-green-retest`

| 文件 | SHA-256 |
|---|---|
| `oas1-full.log` | `0AA6DA09552697C1B99D7B7E8D6E7AEDAEF7B24C90A6DBF04DF67A253514E842` |
| `config-restored.json` | `635A3F54A00CCA2767FDF07024A69C6447827C33BB53951037312BB8C933C28F` |
| `manifest.json` | `6DBD5CDD26357C44EF476E463D049D3B25CF3C95EE72BC7165C08055EBBE7A01` |
| `0616-154.02.png` | `9DB0220484CD0D6ABDDDE8E92E5F7AD391D66EA5717C04B5401ECBAF7F40B8E1` |
| `0617-154.27.png` | `E28BFBBAB9F8CE63EAD36DEABC719F64727007F331A0B126468BEEC908632156` |
| `0618-154.50.png` | `845347236C7B9129F0732BA7D6650A710CB97A0F20E26C44E2902E601D183BE0` |
| `0960-240.02.png` | `961A850FCE162DB0FA893F5B63CEDF583CF907BD74717328021B3AC8087FC7F3` |

## 当前状态

- 阵容锁定正常路径：两轮、共四场中的两个“下一场自动开战”均通过，可作为正常路径有效基线。
- 锁图标陈旧或自动开战真实失败：仅离线兜底覆盖，仍待异常样本。
- 左三绿标：本轮任务确认 `1/2`；快速稳定帧采样修复已离线通过，待新的两场实机复测。
