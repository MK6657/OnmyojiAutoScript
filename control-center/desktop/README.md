# OAS 控制中心桌面版

桌面版参考 `D:\助手\annie-1.0.152` 的 Electron + 内置 Python 结构：

- Electron 负责窗口和本地生产版前端；
- Bridge 使用 PyInstaller 打包为 `oas-control-bridge.exe`；
- OAS Core 仍保持原项目服务，默认连接 `127.0.0.1:22267`，不与上游代码耦合。

## 构建

在 PowerShell 中运行：

```powershell
Set-Location D:\OSAyys\control-center\desktop
.\build.ps1
```

产物位于 `release\OAS-Control-Center-0.1.0-portable.exe`。

如果 Core 使用其他端口：

```powershell
$env:OAS_CORE_URL = 'http://127.0.0.1:22270'
.\build.ps1 -SkipNpmInstall
```

仅修改前端时可以跳过 Bridge 重打包：

```powershell
.\build.ps1 -SkipNpmInstall -SkipBridge
```

桌面版会把 UI 元数据放在当前用户目录，不会把可写数据放进 Electron 安装包。
