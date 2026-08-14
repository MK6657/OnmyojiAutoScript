# DeepSeek-08 核验后代码修复记录

时间：2026-08-11

## 结论

DeepSeek-08 作为问题来源使用，最终结论由当前代码、失败测试、完整回归和正式服务健康检查决定。报告中的 OAS `418/418` 与校准器幂等记录数属于旧时间点；本轮独立基线分别为 OAS `444/444` 和校准器 `146/146`。

## 已确认并修复

### `CC-ENV-001`

Windows 本地化 `netstat` 输出在 `PYTHONUTF8=1` 下被错误按 UTF-8 解码，导致本地端点 PID 探测失败。现改为原始字节解析，不依赖标题文本或系统代码页；失败测试和完整包门禁通过。校准器版本提升到 `0.3.8`。

### `LAUNCH-WIRING-001`

控制中心启动器过去只检查 Bridge/前端“是否健康”，没有证明它们连接的是本次请求的上游。现有端点规范化契约；Bridge 复用必须验证 health 中的 `core_url`，前端登记并验证 `bridge_url`。身份不一致或旧登记无法证明时不静默复用。正式日常启动复跑确认 Core、Bridge 和前端目标一致。

### `BINDING-001`

通用模拟器窗口过去可能把“唯一在线 ADB serial”当作设备身份证据。该猜测已删除；未知品牌无可证明映射时保持未绑定。MuMu 实例端口映射仍需在线 ADB 列表验证。正式窗口 `2301` 抽查仍正确映射到 `127.0.0.1:16384`，来源为 `verified_adb_mapping`。

### 配置 revision 文档漂移

Bridge 实际行为是缺少 revision 返回 428、陈旧 revision 返回 409。契约文档已改为与代码一致，不再描述 Bridge 代客户端补 revision。

## 验证

- OAS 15 套定向与回归：`444/444`。
- Bridge 契约：`27/27`；运行时命令：`3/3`。
- 启动接线端点测试与三个 PowerShell 文件 AST：通过。
- coordinate-calibrator：`146/146`，JavaScript、编译、AST、wheel 构建和隔离安装通过。
- `PYTHONUTF8=1` 下 capture-source：`15/15`。
- 正式服务：Core `22267`、Bridge `22367`、前端 `4175`、校准器 `22880` 均健康；Bridge `1.1.5`、校准器 `0.3.8`。
- `oas1` 保持 offline、零选中任务、无 `next_run`，本轮未发起游戏任务。

## 尚未结案

- `LAUNCH-WIRING-001` 仍需第二套 Core/Bridge 的真实多端口集成复核。
- `BINDING-001` 仍需异构模拟器、双 MuMu、serial 变化和句柄复用矩阵。
- `CC-CAPTURE-002` 仍需 100/125/150% DPI、真实鼠标前后帧和 P95 坐标误差实测。
- 绿标、寮突破终局和 EXP-028 长程属于业务实机事项，不由本轮代码门禁替代。

## 备份与回滚

备份位于 `D:\OSAyys\backups\pre-audit08-code-fixes-20260811-100934`，含本轮修改前文件和 SHA-256 清单。未修改 OAS 任务配置、checkpoint 或校准器 schema/业务数据。
