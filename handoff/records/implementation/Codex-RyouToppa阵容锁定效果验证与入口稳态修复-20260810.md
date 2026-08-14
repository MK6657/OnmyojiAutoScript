# RyouToppa 阵容锁定效果验证与入口稳态修复

日期：2026-08-10

## 根因与修复

画布 10 给出的锁定控件外框约为 `[206.76,222.54) × [606.76,631.55)`，人工确认点约为 `(215.77,618.03)`。第一版随机区 `(209,609,12,21)` 仍可能落到视觉下沿，实机点击 `(209,629)` 后下一场继续出现准备。随机区已收紧为 `(212,614,8,9)`，保留中心小范围随机且不触碰边缘。

锁定成功不再由图标模板宣称，而由下一场是否跳过准备验证。实机中心点击后，战斗没有人工点击准备便自动结束，证明锁定生效。

该实测同时发现加载页会误触发通用蓝色准备按钮视觉规则：加载帧右下区域亮彩像素比例 `53.34%`，超过旧视觉规则 `45%`。RyouToppa 入口现要求准备状态连续两帧成立；单帧候选后若下一帧进入真实战斗，返回 `direct_battle`。未修改通用按钮阈值。

直接运行 `Script('oas1').run('RyouToppa')` 时，动态模块名曾使失败收尾调用者退化为 `ScriptTask`，同任务调度被权限门拒绝。新增源码路径回退，把调用者恢复为 `RyouToppa`；跨任务授权矩阵未放宽。

代码位置：

- [RyouToppa 锁定安全区与入口稳态](/D:/OSAyys/tasks/RyouToppa/script_task.py:114)
- [调度调用者身份恢复](/D:/OSAyys/tasks/base_task.py:785)
- [RyouToppa 回归](/D:/OSAyys/tasks/RyouToppa/tests/test_ryou_flow.py:256)
- [调度契约回归](/D:/OSAyys/module/config/tests/test_schedule_contract.py:58)

## 验证

- RyouToppa 与调度契约定向测试：`30/30`。
- OAS 14 组完整回归：`364/364`。
- 实机：中心锁定点击后下一场自动完成；稳态修复后新一场记录 `RYOU_PREPARE_CANDIDATE streak=1/2`，随后 `state=verified reason=first_battle_entered_directly`，战斗胜利并返回寮突破列表。
- 当前配置：scheduler 关闭、自动选寮关闭、`limit_count=50`、锁定开启、预设开启、绿标 `green_left3`。

## 回滚

实施前备份：`D:\OSAyys\backups\pre-ryou-effect-lock-20260810-002902`

恢复 `tasks/RyouToppa/script_task.py`、`tasks/RyouToppa/tests/test_ryou_flow.py` 和 `tasks/base_task.py` 前，先停止 OAS 服务并核对备份哈希。不要恢复整个脏工作树，也不要覆盖用户其他配置。

