# RY-GUILD-001 安全选择修复实施记录

日期：2026-08-09

## 结论

已移除当前运行路径中“点击勋章排序后固定点击第一张寮卡，并直接记录 maximum”的假成功逻辑。自动选寮现在默认关闭；候选 OCR 规则未配置、候选不完整、两帧不稳定、帧身份复用或 OCR 置信度不足时均返回失败，不点击任何寮卡。

这不是实机结案。寮卡区域和勋章 OCR ROI 尚未用坐标标注系统确认，21:00 后的“只选不打”实测也尚未执行。

## 实现

- 新增 `GuildCandidate`、`GuildSelectionResult` 和 `GuildObservationComparison`。
- 只有同一帧内全部候选勋章值有效，才允许计算最大值。
- 并列最大值按从上到下、从左到右、稳定 ID 的顺序选择。
- 点击前要求两张不同 frame ID 的连续观察在候选 ID、卡片区域、中心和勋章值上完全一致。
- 点击日志记录候选 ID、实际勋章、观察最大值、frame ID 和 SHA-256。
- `auto_select_highest_guild` 默认值为 `false`，旧配置无需新增字段即可安全解析。
- 旧 `_legacy_start_ryou_toppa()` 在入口处直接拒绝执行，不能再走固定第一张旁路。

## 验证

- `python -m unittest discover -s tasks/RyouToppa/tests -p "test*.py"`：12/12 通过。
- `python -m unittest discover -s tasks/Component/GeneralBattle/tests -p "test*.py"`：90/90 通过。
- `python -m compileall -q tasks/RyouToppa tasks/Component/GeneralBattle dev_tools/green_mark_target_range.py`：通过。
- `config/oas1.json` 通过 `RyouToppa.model_validate()` 解析，默认自动选寮为关闭。

## 备份与回滚

修改前备份：`D:\OSAyys\backups\pre-ryou-selection-20260809-151532`，含 36 个文件和 SHA-256 清单。

回滚时恢复 `tasks/RyouToppa`，不需要改动账号业务配置。正式实测前继续保持 `RyouToppa.scheduler.enable=false` 和 `auto_select_highest_guild=false`。

## 未完成验收

- 用坐标标注系统确定全部可见寮卡区域、每张卡的勋章 OCR ROI 和点击中心。
- 保留至少两套排序/不同候选截图作为离线 OCR 夹具。
- 21:00 后执行只选不打，证明 `selected_medal == max(observed_medals)`。
- 单步通过后再做一场寮突破，不直接进入长程。
