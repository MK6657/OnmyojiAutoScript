# Codex 实测：DEVICE-BIND-20260815-01

日期：2026-08-15
事项：迁移后首次真实设备绑定与取帧检查。
当前状态：绑定与取帧通过；未运行任何自动化任务。

## 前置

- MuMu 12 实例：标题 `2301`，窗口句柄 `264384`，进程 `MuMuNxDevice.exe` PID `12360`。
- VM 实例：`MuMuPlayer-12.0-0`，安装路径 `D:\yys\MuMuPlayer`。
- 账号已由用户在本机登录；ADB 在线设备 `emulator-5554`。
- 本机配置：`config/oas1.json` 已从 `template.json` 创建。
  - `serial = 127.0.0.1:16384`
  - `screenshot_method = nemu_ipc`
  - `control_method = minitouch`
  - `emulatorinfo_type = auto`

## 操作

- 运行只读探针 `work/device-bind-check.py`，只创建/修正 `oas1.json` 并取一帧，不点击、不启动任务。
- 启动真实三层：Core 22267 → Bridge 22367 → 前端 4175。
- 运行 `control-center\check-wiring.ps1`。

## 结果

- Device 初始化日志：
  - `connected to 127.0.0.1:16384`
  - `Found emulator instance: MuMuPlayer12(serial="127.0.0.1:16384", name="MuMuPlayer-12.0-0", path="D:/yys/MuMuPlayer/nx_main/MuMuNxMain.exe")`
  - `NemuIpcImpl init ... external_renderer_ipc.dll, instance_id=0, display_id=0`
  - `NEMU_RESOLUTION width=1280 height=720`
- 自动识别游戏包：`com.netease.onmyoji.wyzymnqsd_cps`
- 实际取帧：`shape=(720, 1280, 3)`，即 **1280x720 横屏，orientation=0**。
- 结果判定：`RESULT: BIND_OK 1280x720`
- Bridge `/api/v1/windows` 对窗口 `2301 / handle 264384 / MuMuNxDevice.exe` 推断：
  - `serial = 127.0.0.1:16384`
  - `serial_source = verified_adb_mapping`
- `check-wiring.ps1`：**15/15 通过**；Core 配置列表含 `oas1`，Bridge 缓存命中正常，事件 WebSocket 握手正常。
- 账号状态：`oas1` 为 `offline`，已启用任务只有默认的 `Restart`，`next_run=2023-01-01`（不会自动跑任务）。

## 证据

- 日志：`D:\OSAyys\log\2026-08-15_device-bind-check.txt`
- 服务日志：`D:\OSAyys\log\2026-08-15_server.txt`
- 探针脚本：`D:\OSAyys\work\device-bind-check.py`（只读取帧，不点击）

## 结论

本机 OAS 可以绑定 MuMu `2301`：串口、模拟器实例、窗口身份和 1280x720 画布均已验证。后续真机业务测试可在该绑定点上继续。

当前状态：未结案（仅绑定与取帧，业务任务尚未测试）。
