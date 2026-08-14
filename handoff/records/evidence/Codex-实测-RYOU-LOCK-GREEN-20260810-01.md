# 寮突破阵容锁定与左三绿标实测 2026-08-10-01

## 结论

- 阵容锁定中心点击真实生效，后续战斗可以跳过准备并由游戏自动接管。
- 加载页单帧曾被误判为准备；连续两帧稳态修复后，实机正确返回 `direct_battle`。
- 左三点击坐标正确，但旧模板仍未确认绿标。本轮状态为 `unconfirmed`，不能因战斗胜利改写为绿标成功。
- 两场自动战斗均正常结束并回到寮突破列表；当前没有 OAS 任务实例。

## 阵容锁定

人工标定中心 `(约216,618)`。点击前后控件局部约 43% 像素变化，随后未人工点击准备，战斗自动完成。稳态修复后的复测记录：

```text
RYOU_PREPARE_CANDIDATE streak=1/2
RYOU_LOCK_VALIDATION state=verified reason=first_battle_entered_directly
RYOU_FIXED_BATTLE win=True
RYOU_FIXED_RETURN returned=True
```

这证明第一帧为加载动画误报，下一帧是真实直入战斗；两帧稳定门禁没有把加载页当作准备页。

## 左三绿标

- 配置：`green_mark=green_left3`。
- 点击区：`[586,328,100,76]`。
- 实际点击：`(652,369)`，位于左三点击区。
- 两次模板确认均失败，最高分 `0.7028759717941284 < 0.8`。
- 结构化结果：`status=unconfirmed`，`attempts=2`，`marker_point=null`。
- HSV 诊断在两帧中都找到约 `63×61` 的大绿色候选，典型中心 `(626,229)`，位于左三的头部确认带；HSV 仍只是诊断，不参与生产授权。

历史靶场 `sample-09` 共 45 轮。按“大绿色块、位于目标头部和水平中心附近”的候选规则复算，`0.35s` 目标命中仅 `32/45`，未达到零漏检和零串位门槛。因此本轮不启用 HSV 正式确认，也不降低模板阈值。

## 证据

目录：`D:\OSAyys\output\evidence\ryou_toppa\20260810-lock-center-02`

- `before-lock.png` / `after-lock.png`：中心点击前后控件状态。
- `entry-mode.png`：第一轮错误分类时仍处加载页。
- `prepare-failure.png`：没有人工点准备却已经自动完成的结果页，反证锁定有效。
- `entry-mode-fixed.png`：稳态修复后的入口证据。
- `board-after-fixed-battle.png`：战斗和结算后回到寮突破列表。
- `runtime-log.txt`：本轮完整运行日志。
- `sha256.csv`：上述证据大小和 SHA-256。

## 尚未结案

- 绿标确认器仍需用新截图和校准器标注五个互斥头部确认区，并补保留验证集。
- 本轮只验证寮突破左三，不替代 RealmRaid 1/3/10 场绿标验收。
- 自动选最高勋章寮未启用，也未测试；用户已事先选定寮，不能把本轮战斗记录用于 `RY-GUILD-001` 选寮结案。

