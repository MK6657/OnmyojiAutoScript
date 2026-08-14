# 坐标校准工具 DeepSeek-06 残留修复记录

日期：2026-08-07
项目：`D:\coordinate-calibrator`
依据：`DeepSeek-06-坐标校准工具修复验证与评测修订-20260807.md`

## 本轮已修复

- `start.ps1` 与 Python 应用统一使用有效 bind host：默认强制 `127.0.0.1`，只有显式允许远程时才读取 `server.host` 或 `CALIBRATOR_HOST`。
- 启动器可从本地 `[oas].root` 发现 OAS 虚拟环境；显式 `-PythonPath` 仍拥有最高优先级。
- 启动器依赖缺失时输出可读错误，不再把原始 Python traceback 作为主要提示。
- Nemu/OAS 导入遇到 OpenCV/NumPy ABI 冲突时输出明确修复指引。
- 同一画布的开始、停止、截图、切换来源和关闭操作增加服务端串行保护，避免截图保存与画布切换互相覆盖。
- Nemu 截图超时后阻断该来源，拒绝继续排队，要求重新应用截图来源；底层第三方线程无法由 Python 强制终止，保留在限制项中。
- 前端增加已删除标注显示和批量恢复入口。
- 前端使用 `/api/v1/capabilities` 动态禁用不可用窗口、鼠标和帧源能力。
- 前端补充画布切换、刷新和保存当前帧的请求序列保护。
- 增加 schema 2 到 schema 3 迁移、备份、复合帧主键和 Nemu ABI 诊断测试。

## 验证

- `38/38 unittest` 通过。
- Python `compileall` 通过。
- `node --check src/coordinate_calibrator/web/app.js` 通过。
- PowerShell 启动脚本语法检查通过。
- 临时端口 `22881` 启动、健康检查和停止通过。
- 当前 `22880` 只有一个监听实例，健康接口和能力接口正常。
- HTML 已包含批量恢复按钮、能力摘要和新版前端缓存版本。

## 未结案

- MuMu `2301` 的 Nemu/ADB 实机采集、重连、DPI、干扰窗口和多画布长测仍需用户环境验收。
- Python 不能强制终止已经卡在第三方 Nemu 调用中的原生线程；超时后的来源必须重新绑定，必要时重启服务回收残留线程。
- OAS 候选仍为只读导出，不提供自动写回。
