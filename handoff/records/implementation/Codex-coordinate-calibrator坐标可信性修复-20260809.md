# coordinate-calibrator 坐标可信性修复实施记录

日期：2026-08-09  
范围：双项目逐阶段修复计划第 0、1 步  
版本：`coordinate-calibrator 0.3.4`  
结论：代码实施、完整离线回归和隔离生产数据浏览器验收通过；第 2 步及真实 MuMu/DPI/ADB 验收未开始。

## 基线与回滚点

- 校准器备份：`D:\coordinate-calibrator\backups\pre-step01-coordinate-trust-20260809-123121`，189 个文件，含源码、测试、文档、SQLite、会话和输出文件 SHA-256 清单。
- OAS 备份：`D:\OSAyys\work\backups\pre-step01-baseline-20260809-123121`，含分支、HEAD、工作树、监听器、进程、配置和 RealmRaid checkpoint SHA-256 清单。
- 修复前校准器 `120/120` 通过；OAS GotoMain、GameUi、GeneralBattle、RealmRaid、RyouToppa、Exploration、server、device、daemon 共 `258/258` 通过。
- 校准器正式服务在备份前优雅停止；所有隔离浏览器写操作只发生在 `22881` 的数据副本。

## 根因

1. 页面显示的是 `persisted_frame`，但坐标换算读取可被实时预览替换的 `session.latest_frame`。两帧尺寸不同时，点击点会按错误比例转换。
2. 叠加层渲染检查背景作用域，命中检测、选择集合、报告和导出没有共享同一个资格判断，导致背景外或隐藏标注仍可能参与交互。
3. 隔离验收又发现新增背景的持久帧会递增 mapping revision，但背景映射快照保留旧 revision。严格帧绑定会拒绝加载这个不一致证据。

## 实施

- 新增不可变 `displayedFrameContext`，包含 session、持久帧 ID、解码尺寸、mapping revision、截图 SHA-256 和规范画布快照。
- 点击、拖动、命中、预览、坐标显示和换算只使用正在显示的持久帧上下文，不再读取可变实时预览。
- 建立统一标注资格：当前背景匹配、未删除、可见并通过搜索/类型/仅显示选中筛选。渲染、命中、移动、报告和导出共用该规则。
- 缩放、黑白、描边和编号徽章继续只影响显示，不进入形状数据、命中几何或报告 bbox。
- 新增背景以实际持久帧写入 screen/canvas/scale/revision，同时保留导入证据的 source、valid、reason 和 metadata；`valid=false` 仍阻断差异比较。

主要改动文件：

- `D:\coordinate-calibrator\src\coordinate_calibrator\web\workspace_state.js`
- `D:\coordinate-calibrator\src\coordinate_calibrator\web\app.js`
- `D:\coordinate-calibrator\src\coordinate_calibrator\api\runtime.py`
- `D:\coordinate-calibrator\tests\test_web_math.js`
- `D:\coordinate-calibrator\tests\test_web_state.js`
- `D:\coordinate-calibrator\tests\test_frontend_usability.py`
- `D:\coordinate-calibrator\tests\test_library_bundles.py`

## 验证证据

- 最终 `test.ps1 -Package`：`122/122` Python 测试通过，同时通过 JS 坐标/状态断言、Python 编译、JavaScript 语法、PowerShell AST 和隔离 wheel 构建。
- 隔离端口：`127.0.0.1:22881`，使用正式数据完整副本。
- 画布 2：显示帧和叠加层均为 `710x413`，规范画布为 `1280x720`。
- 150% 缩放：图片显示尺寸为 `1065x620`，叠加层 backing store 仍为 `710x413`，点坐标仍为 `(294,305)`。
- 背景 C：持久帧和映射快照均为 revision `3`；限定于基准背景的 `01_点` 不显示、不自动选中，报告只包含共享的 `02_框`。
- 切回基准背景后，`01_点` 恢复显示并自动选中。
- 正式校准器 `data/outputs` 25 个文件与修复前清单零哈希差异；OAS 配置/checkpoint 5 个文件零哈希差异。
- 正式服务回切到 `127.0.0.1:22880`，health 返回 `0.3.4`，正式页面加载原 4 个画布、3 个背景和 34 条标注，无 mapping revision 错误。

## 未完成边界

- `CC-TXN-002`、`CC-ASYNC-002`、租约恢复和幂等 fencing 属于第 2 步，未在本记录中修复。
- MuMu `2301`、干扰窗口、窗口移动/缩放、DPI、真实 ADB 和双设备身份属于第 9 步，未实测。
- 本轮没有修改 OAS 业务代码、配置、checkpoint 或任务状态机，也没有建立校准器到 OAS 的自动写回。

## 回滚

停止 `22880` 后，可使用校准器备份恢复源码和正式数据；OAS 若需核对，使用独立 OAS 基线备份。回滚前必须再次保存当前数据和哈希，不得覆盖用户在本记录之后新增的画布或标注。
