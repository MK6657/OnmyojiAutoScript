# OAS Control Center

这是 MK6657 二次开发分支的独立控制中心。它不把界面逻辑塞进 OAS Core，而是保持清晰的四层边界：

```text
React/Vite 前端 :4175
        ↓ /api/v1 + WebSocket
FastAPI Bridge :22367
        ↓ OAS HTTP + WebSocket
OAS Core :22267
        ↓
账号任务进程与游戏窗口
```

## 唯一前端

正式前端源码只有一份：`control-center/frontend`。

- 浏览器开发由 Vite 直接运行这份源码。
- 无游戏联调仍运行这份源码，只把后端切到隔离 Bridge/mock Core。
- Electron 构建先把这份源码编译到 `desktop/ui`，再放进 portable。
- 不再维护 `UI-claude`、`frontend-preview` 或旧生产前端副本。

## 目录

```text
control-center/
├─ frontend/       唯一 React/Vite 前端源码
├─ bridge/         前端与 OAS Core 之间的稳定适配层
├─ desktop/        Electron 壳和 portable 构建
├─ launcher/       开发、隔离联调和服务启动脚本
├─ docs/           当前架构说明
└─ start.ps1       Core → Bridge → 前端一键启动
```

## 日常启动

推荐双击项目根目录的 `启动.bat`，或运行：

```powershell
Set-Location D:\OSAyys
.\control-center\start.ps1
```

默认地址：Core `22267`、Bridge `22367`、前端首选 `4175`。脚本会复用已经正常运行的本项目服务；Bridge 端口被占用或指向其他 Core 时会拒绝启动，避免多实例共享 SQLite；只有前端端口被占用或被 Windows 预留时才会自动顺延。

## 无游戏联调

```powershell
Set-Location D:\OSAyys
.\control-center\launcher\start-dev-stack.ps1
```

隔离栈使用 mock Core `22268`、测试 Bridge `22368`、正式前端 `4175` 和独立 SQLite 数据目录。它不连接真实游戏、不写真实账号配置。

## 桌面构建

```powershell
Set-Location D:\OSAyys\control-center\desktop
.\build.ps1
```

构建链：

```text
frontend -> Vite desktop build -> desktop/ui
bridge -> PyInstaller -> desktop/bridge-dist/oas-control-bridge.exe
Electron + 上述资源 -> release/OAS-Control-Center-0.1.0-portable.exe
```

portable 自带前端和 Bridge，但当前仍连接独立运行的 OAS Core。这样能让控制中心与上游 Core 保持低耦合。

更详细的开发方式见 `frontend/README.md`，架构边界见 `docs/architecture.md`。
