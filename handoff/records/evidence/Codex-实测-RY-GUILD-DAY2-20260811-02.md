# 寮突破游戏日刷新后二次自动选寮实测 2026-08-11-02

## 结论

游戏日刷新后再次出现可选寮机会，自动选最高勋章流程第二次实机通过。程序使用当天新帧重新识别，不复用前一次截图或排序结果；验证降序、升序和恢复降序后，选择第一行最高勋章寮并进入棋盘。

本轮只验证选寮。临时设置 `limit_count=0`，进入棋盘后立即以 `deferred/count_limit` 结束，没有发起战斗。账号随后停止，完整配置恢复到实测前哈希。

## 环境

- 账号：`oas1`。
- 目标窗口：标题 `2301`，PID `7580`，HWND `657286`。
- 设备：serial `127.0.0.1:16384`，Nemu IPC，`1280x720`。
- 游戏初始页面：庭院。
- Core / Bridge / 前端 / coordinate-calibrator 均为重启后新进程且健康。

## 当天排序证据

```text
08:27:06  descending (241,231,219,205)
            frame_id=guild_4029921000000
            sha256=8d5af48d30675ef643f5c45850e033881d16ded626a340d4eb0560dcf19a7529
08:27:08  ascending  (57,58,60,64)
            frame_id=guild_4031828000000
            sha256=d0e9b088968a170446545218b8ecd231924eb0af844280a3579693a3e2c82025
08:27:10  descending (241,231,219,205)
            frame_id=guild_4033734000000
            sha256=73c31871dfa1dc4a5f472136e7812e2147d68205bd934915b271a05cdf5225ea
```

当天可见勋章极值与前一次恰好相同，但帧 ID 和三个图像哈希均为新值，因此本次是独立重新识别，不是缓存命中。

## 动作与结果

```text
08:27:10  RYOU_GUILD_SORT_VERIFIED highest=241 lowest=57
08:27:10  Click (1158,143) @ select_first_ryou
08:27:10  RYOU_GUILD_SELECT_CARD candidate=row_1 medal_reward=241 verified_sort=descending
08:27:11  Click (923,532) @ RES_START_TOPPA_BUTTON
08:27:12  RYOU_GUILD_SELECT_RESULT result=board
08:27:13  RYOU_COUNT_LIMIT
```

`result=board` 先于 `count_limit`，证明已经完成选择并进入寮突破棋盘。随后调度器按空任务规则安全返回庭院。

为便于人工复核，账号停止后使用同一设备绑定执行了一次有界只读导航，结果为 `RYOU_ENTRY_STATE=board`，再次进入已选寮棋盘。08:33 后的可视复核确认左侧寮名为“一叶孤城”、击破奖励为 `241`；未发起战斗，也未再次执行选寮。

## 非阻塞诊断

启动阶段出现一次 `MinitouchNotInstalledError`，控制链随后自行恢复并完成预设、导航、排序和点击。该事件没有改变本轮结论，但保留在运行日志中供后续控制方式稳定性审查。

## 恢复与证据

- 账号最终状态：`offline`，无运行任务实例。
- `config/oas1.json` 恢复后 SHA-256：`635a3f54a00cca2767fdf07024a69c6447827c33bb53951037312bb8c933c28f`。
- 修改前备份：`D:\OSAyys\backups\pre-ryou-day2-selection-20260811-082543`。
- 证据目录：`D:\OSAyys\output\evidence\ryou_toppa\20260811-082543-day2-selection`。
- 证据目录包含测试前、测试后、恢复后配置，完整运行日志和 `sha256.csv`。
- 最终恢复后精确重启 Core、Bridge 和前端，使内存配置与已恢复的磁盘配置重新一致；账号状态为 `offline`，无运行任务和待运行时间残留。coordinate-calibrator 未重启，继续运行于 `127.0.0.1:22880`。

## 当前判定

`RY-GUILD-001` 当前排序协议已有两次独立真实运行证据，其中一次跨游戏日刷新。无需重新校准当前 `1280x720` 排序按钮、四行 OCR 或第一行点击位置。只有 UI 布局、分辨率、排序语义或 OCR 字体变化时才重新打开。
