# RealmRaid 阵容锁定效果验证修复（2026-08-10）

## 问题

原逻辑在 RealmRaid 战后看到 `RES_LOCK` 图标后即记录锁定成功，但下一场 `GeneralBattle.battle_before()` 只要看到准备按钮就立即点击。这样程序会抢在游戏的锁定自动开战之前点击准备，既无法验证阵容锁定是否真实生效，也可能把“图标已切换”误记为“效果已确认”。

## 修复

- `GeneralBattle` 增加 `LOCKED_AUTO_START_GRACE=2.5` 秒的有界观察窗口。
- 锁定预期生效时，准备页先等待游戏自动开战，不立即点击准备。
- 在窗口内进入真实战斗或直接进入结果页，记录 `LOCK_VALIDATION state=verified`。
- 准备按钮持续存在到窗口结束时，记录 `state=failed`，清除锁定预期，再使用原有最多三次的有界准备兜底。
- RealmRaid 首场因预设需要先解锁，明确设置 `_battle_lock_expected_active=false`；战后锁图标确认只记录 `indicator_confirmed / pending_next_battle`，下一场实际自动开战才算效果验证。
- 实机后修正重复验证日志：同一场首次确认后立即消费观察状态，每场只保留一条最终结论。

## 离线验证

- 新增“锁定后自动开战不点击准备”用例。
- 新增“锁图标陈旧时有限等待后准备兜底”用例。
- 新增“RealmRaid 战后锁图标只进入待下一场验证状态”用例。
- 定向用例 `17/17`。
- GeneralBattle 全套 `112/112`。
- RealmRaid 全套 `104/104`。

## 回滚

实机前源码和配置备份位于 `D:\OSAyys\backups\pre-realmraid-lock-validation-20260810-164800`。回滚时仅恢复其中两份源码；`config/oas1.json` 已通过 Bridge revision PATCH 恢复到原哈希，不应直接覆盖正在运行的配置。

## 实机结果

两场闭环中，第一场按设计点击一次准备；战后图标锁定；第二场进入准备页后约 `0.6` 秒自行进入真实战斗，程序没有点击准备，阵容锁定效果验证通过。完整证据见 [实测记录](../evidence/Codex-实测-RR-LOCK-GREEN-20260810-02.md)。
