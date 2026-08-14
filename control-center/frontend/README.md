# OAS 控制中心前端

这是控制中心唯一的正式前端源码。浏览器开发、隔离联调、Electron 桌面窗口和 portable 构建全部使用本目录，不再维护第二套生产界面。

## 固定链路

```text
浏览器开发：control-center/frontend -> Vite :4175 -> Bridge :22367 -> OAS Core :22267
隔离联调：  control-center/frontend -> Vite :4175 -> 测试 Bridge :22368 -> mock Core :22268
桌面发布：  control-center/frontend -> Vite dist -> desktop/ui -> Electron portable
```

前端只访问 Bridge 的 `/api/v1` 和事件 WebSocket，不直接读取 `config/*.json`，也不导入 OAS Python 模块。Electron 使用同一份 Vite 构建结果；`src/api.js` 会在 `file://` 页面下连接 `127.0.0.1:22367`。

## 开发启动

连接真实环境时，推荐从项目根目录双击 `启动.bat`，或运行：

```powershell
Set-Location D:\OSAyys
.\control-center\start.ps1
```

只启动前端时：

```powershell
Set-Location D:\OSAyys
.\control-center\launcher\start-frontend.ps1 -Port 4175 -BridgeUrl http://127.0.0.1:22367
```

无游戏隔离联调时：

```powershell
Set-Location D:\OSAyys
.\control-center\launcher\start-dev-stack.ps1
```

隔离栈固定使用 mock Core `22268`、测试 Bridge `22368` 和本前端。UI 首选 `4175`，如果被 Windows 预留会自动顺延；本机当前使用 `4212`。隔离栈不会复用正式 Bridge 数据目录。

## 前端文件

```text
src/App.jsx          应用外壳与全局状态
src/api.js           Bridge REST 与事件连接
src/views.jsx        概览、任务、日志、设置
src/fields.jsx       通用配置字段编辑器
src/components.jsx   通用界面组件
src/store.js         主题、密度和本地降级存储
src/locale.js        中文映射
src/styles.css       界面样式与主题变量
tools/               mock Bridge 与端到端回归
docs/                界面参考截图
```

## 构建与测试

```powershell
Set-Location D:\OSAyys\control-center\frontend
npm install
npm run build
npm run build:desktop
```

轻量 mock 回归需要 Playwright。下面三组命令分别在三个 PowerShell 窗口运行；如果 `4175` 被 Windows 预留，把 UI 端口和 `OAS_UI_BASE` 一起改为启动器报告的端口（本机通常是 `4212`）：

```powershell
# 窗口 1：轻量 Mock Bridge
npm run mock

# 窗口 2：正式前端源码 + Mock 代理
$env:OAS_BRIDGE_URL = 'http://127.0.0.1:22368'
npm run dev -- --host 127.0.0.1 --port 4175

# 窗口 3：浏览器回归
$env:OAS_UI_BASE = 'http://127.0.0.1:4175/'
npm run test:e2e
```

桌面版统一从本目录构建：

```powershell
Set-Location D:\OSAyys\control-center\desktop
.\build.ps1
```

产物为 `release\OAS-Control-Center-0.1.0-portable.exe`。仅修改前端并且已有可用 Bridge 打包产物时，可以使用 `-SkipBridge` 缩短构建时间。

## 维护约束

- 不再创建 `UI-claude`、`frontend-preview` 等平行生产前端。
- 样式和交互改动直接进入本目录，通过 Vite 热更新检查。
- Bridge 契约变化先在 Bridge 层兼容，再调整前端。
- 日常调样式不打 portable；阶段验收时才验证 Electron 和 portable。
