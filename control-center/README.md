# OAS Control Center

这是 OAS 的独立控制中心，不修改 `module/`、`tasks/` 或原 QML 界面。它由两层组成：

```text
React/Vite 前端 → FastAPI Bridge (:22367) → OAS Core (:22267)
```

Bridge 只调用 OAS 公开的配置、任务参数和 WebSocket 接口；账号昵称、标签和排序等 UI 元数据保存在 `data/control_center.db`。任务配置仍由 OAS 配置文件维护，因此上游更新后只需要适配 Bridge 的契约，不需要把前端绑进 OAS 的 Python 模块。

## 启动

先启动原项目服务（默认 `http://127.0.0.1:22267`），再启动 Bridge 和前端：

```powershell
Set-Location D:\OSAyys
.\control-center\launcher\start-bridge.ps1
.\control-center\launcher\start-frontend.ps1
```

打开 `http://127.0.0.1:5173`。也可以用 `start-all.ps1` 一次启动 Bridge 与前端；脚本不会替用户启动或关闭 OAS Core。

如果 Core 使用其他地址：

```powershell
$env:OAS_CORE_URL = 'http://127.0.0.1:22270'
Set-Location D:\OSAyys\control-center\bridge
python -m uvicorn app.main:app --host 127.0.0.1 --port 22367
```

## 桌面版

参考 `D:\助手\annie-1.0.152` 的 Electron + 内置 Python 结构，桌面版把生产版前端和 PyInstaller Bridge 收进一个 portable 程序中。它不再依赖 Vite 开发服务器，默认仍连接原 OAS Core：

```powershell
Set-Location D:\OSAyys\control-center\desktop
.\build.ps1
```

产物位于 `desktop\release\OAS-Control-Center-0.1.0-portable.exe`。Core 仍作为独立服务保留，这是为了让控制中心与上游同步时保持低耦合。

## 当前功能

- 多账号列表与独立状态、日志流
- 从 OAS 任务菜单生成全部任务目录
- 账号独立启用/停用任务
- 所有任务参数按 OAS Schema 通用渲染
- 当前账号独立启动、停止、重启和刷新
- Bridge 断线自动重连，前端通过版本化事件接收状态和日志
- 新账号从 OAS `template.json` 创建
- 点击任务目录即可预览设置，加号只负责启用任务
- 已启用任务支持控制中心内的显示排序和停用
- 任务配置模板保存在本机前端，可跨账号复用

## 与上游同步约定

不要把 `control-center` 的代码移动到 OAS 的 `module/` 或 `tasks/` 目录。上游同步时重点检查：

1. `/script_menu` 的任务 ID 是否变化；
2. `/{config}/{task}/args` 的 Schema 字段类型是否增加；
3. `/ws/{config}` 的消息格式是否变化；
4. OAS Core 端口是否仍为 22267。

对应适配集中在 `bridge/app/core_client.py`、`bridge/app/main.py` 和 `bridge/app/runtime.py`。
