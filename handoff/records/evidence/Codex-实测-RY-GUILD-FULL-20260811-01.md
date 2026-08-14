# 寮突破自动选寮完整链路实测 2026-08-11-01

## 结论

`RY-GUILD-001` 的当前排序协议已通过真实游戏验证：程序识别降序最高值 `241`，切到升序确认最低值 `57`，恢复原降序并验证数值一致，随后点击第一行“一叶孤城”并进入寮突破棋盘。该点击是“排序已验证后的固定第一行”，不是旧版无条件固定点第一张。

从选寮进入棋盘后的同一任务继续完成两场战斗并正常回板，最终因测试设置的场次数上限返回 `deferred/count_limit`，没有累计连续失败。自动选寮配置和任务调度在测试后均恢复关闭。

## 环境

- 账号：`oas1`。
- 设备：MuMu 窗口 `2301`，serial `127.0.0.1:16384`。
- 截图：Nemu IPC，`1280x720`。
- 干扰设备：`emulator-5554` 存在，但未被选作目标。
- 运行日志：`log/2026-08-11_oas1.txt`，证据目录保存了本轮日志快照。

## 排序与选择证据

```text
00:29:42  RYOU_GUILD_SORT_STABLE order=descending values=(241,231,219,205)
00:29:44  RYOU_GUILD_SORT_STABLE order=ascending  values=(57,58,60,64)
00:29:46  RYOU_GUILD_SORT_STABLE order=descending values=(241,231,219,205)
00:29:46  RYOU_GUILD_SORT_VERIFIED highest=241 lowest=57
00:29:46  RYOU_GUILD_SELECT_CARD candidate=row_1 medal_reward=241 verified_sort=descending
00:29:48  RYOU_GUILD_SELECT_RESULT result=board
```

三次稳定观察的帧哈希分别为：

- 初始降序：`8da93ec05d0b4d29e0ffb8893bd6319da5ad817928181c17f1a06f1fa7bb2b16`。
- 升序：`10ae0cd04c91017bf71b984ecdd20dfe6c4a33a82c7b4d685863741526aee060`。
- 恢复降序：`7a1b4618634b94654ddab676c27e360fee40564123c99d9339b8750fc5fb8f34`。

用户截图中降序第一行名称为“一叶孤城”，勋章数为 `241`。程序点击 `(1163,144)` 后点击开始 `(905,513)`，约 1.7 秒后确认进入棋盘。

## 后续战斗

- 第 1 场：`RYOU_AREA_RESULT area=1, result=success`。
- 第 2 场：`RYOU_AREA_RESULT area=1, result=success`。
- 终止原因：`RYOU_OUTCOME=count_limit`，结构化任务结果为 `deferred`，不计为程序失败。
- 绿标检测仍按独立指标统计，本记录不使用战斗胜利来替代绿标确认。

## 配置恢复

实测结束后：

- `RyouToppa.scheduler.enable=false`。
- `auto_select_highest_guild=false`。
- `limit_count=50`。
- `oas1` 为 `offline`，当前任务实例数为 `0`。
- `config/oas1.json` SHA-256：`635a3f54a00cca2767fdf07024a69c6447827c33bb53951037312bb8c933c28f`，与实测前基线一致。

## 证据目录

`D:\OSAyys\output\evidence\ryou_toppa\20260811-full-chain-selection`

- `00-before-start.png`：实测前选寮页。
- `01-user-descending.png`：降序列表，最高 `241`。
- `02-user-ascending.png`：升序列表，最低 `57`。
- `03-user-top-card.png`：第一行“一叶孤城 241”局部。
- `runtime-log-full.txt`：本轮运行日志快照。
- `sha256.csv`：证据文件大小与 SHA-256。

## 验收边界

本记录结案的是“当前 UI 排序两端验证、恢复降序、点击第一行、进入棋盘”这一范围。它不替代失败箭头语义、无可攻击目标、票耗尽、完整清空或长程稳定性的后续验收。
