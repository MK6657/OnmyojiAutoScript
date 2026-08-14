# Codex-20：设备帧缓冲与探索双状态修复

## 当前目标

本轮目标是先用困28获取突破券，再验证目标等级58的个人突破闭环。操作与识别必须以模拟器内部的 1280x720 游戏画面为准，不依赖 MuMu 窗口在桌面上的缩放尺寸。

## 截图与输入链路结论

- `config/oas1.json` 当前使用 `screenshot_method: nemu_ipc`，通过 MuMu 的 `external_renderer_ipc.dll` 读取模拟器帧缓冲。
- `module/device/method/nemu_ipc.py` 将帧缓冲转换为项目使用的 RGB 图像；`module/device/screenshot.py` 校验识别画面为 1280x720。
- 输入使用 `minitouch`，坐标使用游戏内部坐标，不使用桌面窗口坐标。
- 因此缩小、遮挡 MuMu 窗口不会改变 Core 的截图尺寸；只有修改模拟器内部输出分辨率才会触发分辨率不支持。

## 已复现根因

探索地图存在两种合法状态：右侧章节面板收起、右侧章节面板展开。

错误截图 `log/error/1785860468929/2026-08-05_00-21-08-850364.png` 中：

- 旧 `I_CHECK_EXPLORATION` 得分 `0.46861`，低于阈值 `0.65`。
- 右侧展开/收起箭头 `I_EXP_ARROW_RIGHT` 得分 `0.93153`，可稳定识别。

当前账号截图中：

- 收起态 `I_EXP_ARROW_LEFT` 得分 `0.97885`。
- 展开态 `I_EXP_ARROW_RIGHT` 得分 `0.96793`。

旧流程只把 `I_CHECK_EXPLORATION` 注册为 `page_exploration` 的页面标识，因此在某些皮肤或过渡帧中把真实探索地图当成未知页面，随后回到主界面重试。

## 本次最小修复

- `tasks/GameUi/page.py`：`page_exploration` 同时接受旧页面模板、左箭头和右箭头。
- `tasks/Exploration/base.py`：增加 `is_exploration_world()`，统一覆盖两个面板状态，并排除探索设置面板。
- `tasks/Exploration/solo.py`：退出组队等待时使用新的探索世界判定。
- `tasks/Exploration/tests/test_exploration_page_states.py`：增加双状态页面注册回归测试。

## 后续验证顺序

1. 重启唯一的实际 Core/Bridge，确认端口为 22267/22367，避免旧窗口日志混入。
2. 只启用 Exploration，验证日常分组、困28队伍、按名称换御魂、加成、候补和战斗。
3. 完成困28所需场次并记录突破券数量变化。
4. 停用 Exploration，启用 RealmRaid，验证目标等级58、跨棋盘、绿标和票数消耗。

## 未验证风险

- 本修复覆盖探索任务自身及页面路由；其他任务仍有少量直接引用旧 `I_CHECK_EXPLORATION` 的退出判断，需要在对应任务实测时单独确认。
- 当前还未完成本轮困28和个人突破实机闭环。
