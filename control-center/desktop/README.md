# OAS 控制中心桌面版

桌面版使用 Electron 显示 `control-center/frontend` 的生产构建，并携带 PyInstaller 打包的 Bridge。

```text
control-center/frontend
  -> Vite dist
  -> desktop/ui
  -> Electron portable
  -> 内置 Bridge :22367
  -> 独立 OAS Core :22267
```

## 构建

```powershell
Set-Location D:\OSAyys\control-center\desktop
.\build.ps1
```

依赖已经安装时可以使用：

```powershell
.\build.ps1 -SkipNpmInstall
```

只修改前端并且 `bridge-dist/oas-control-bridge.exe` 已经是正确版本时，可以跳过 Bridge 重打包：

```powershell
.\build.ps1 -SkipNpmInstall -SkipBridge
```

输出：`release\OAS-Control-Center-0.1.0-portable.exe`。

`desktop/ui`、`bridge-dist`、`data-seed`、`build` 和 `release` 都是生成目录，不是源码。不要直接修改其中内容，也不要用旧 portable 判断当前源码。

当前目录中保留的 portable 生成于 2026-07-26，早于唯一前端收口。完成下一次桌面阶段验收前，它只能作为旧版本回退，不代表当前源码。

桌面版不会启动 OAS Core。运行 portable 前应确认 Core 已经在 `127.0.0.1:22267` 运行。
