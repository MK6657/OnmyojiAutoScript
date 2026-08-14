# 寮突破阵容锁定与准备页边界实测 2026-08-11-01

## 结论

阵容锁定控件的视觉切换真实成立，但在当前寮突破环境中不等于下一场跳过准备。程序成功识别“锁定动作可用”，点击一次后识别到“解锁动作可用”；其后的第二场以及三场链路仍连续出现真实准备页。

因此当前安全语义为：锁定只点击并验证一次；若后续寮突破仍要求准备，记录 `VERIFIED_PREPARE_REQUIRED`，不重复点锁定，交给通用战斗的有限准备兜底。旧记录中“锁定后必然直入”的结论被本次新实机证据取代。

## 关键证据

```text
00:45:03  RYOU_LOCK_VALIDATION state=locking action=click_stable_lock_action
00:45:04  RYOU_LOCK_VALIDATION state=verify_next_battle action=lock_clicked_and_verified
00:45:08  RYOU_BATTLE_START area=1, entry=prepare_required
```

三场链路中三次均稳定识别为 `entry=prepare_required`，通用战斗有限点击准备后均正常进入战斗并获胜。视觉锁定切换不应再被用作“无需准备”的唯一证明。

## 证据目录

- `D:\OSAyys\output\evidence\ryou_toppa\20260811-lock-action-retest`：动作图标切换和第二场准备页。
- `D:\OSAyys\output\evidence\ryou_toppa\20260811-lock-three-battle`：连续三场准备页与战斗回板。
- 原始日志快照同时保存在 `D:\OSAyys\output\evidence\ryou_toppa\20260811-full-chain-selection\runtime-log-full.txt`。

## 当前处理规则

- 未能连续两帧识别锁定/解锁动作时 fail-closed，不盲点。
- 视觉锁定切换最多点击一次。
- 后续真实准备页使用有次数和时限的准备兜底。
- 不因战斗胜利反推“锁定跳过准备”成功。
- 若游戏版本变化后确实连续直入，应另行采集新证据再调整状态机。
