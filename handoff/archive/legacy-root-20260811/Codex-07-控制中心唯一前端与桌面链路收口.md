# Codex 07 控制中心唯一前端与桌面链路收口

日期：2026-08-03  
分支：`codex/mk6657-secondary-development`  
范围：前端源码、Windows 启动器、隔离联调、Electron 构建来源和现行文档  
未触碰：真实账号配置、RealmRaid checkpoint、真实 Core、游戏和用户提供的审查报告

## 目的

迁移前同时存在旧 `control-center/frontend`、新 `desktop/release/UI-claude` 和 `frontend-preview`，启动、开发与打包入口指向不同目录。界面改动可能在浏览器里可见，却不会进入 portable；`release` 目录还同时承担源码和生成物职责。

本次将当前已经实测的新界面转正为唯一正式前端，并明确：

```text
网页开发、Mock 联调、真实 Bridge 联调、Electron、portable
                         ↓
           control-center/frontend
```

## 当前链路

### 真实环境

```text
启动.bat
  -> control-center/start.ps1
  -> OAS Core :22267
  -> Bridge :22367
  -> launcher/start-frontend.ps1
  -> control-center/frontend (Vite，首选 :4175)
```

如果前端端口被占用或被 Windows 预留，启动器会继续寻找可绑定端口。本机 Windows 预留 `4112–4211`，因此实际使用 `4212`。

### 隔离联调

```text
launcher/start-dev-stack.ps1
  -> mock Core :22268
  -> 隔离 Bridge :22368 + output/dev-stack 独立数据目录
  -> 同一份 control-center/frontend
```

测试脚本在写操作前验证回环地址、拒绝正式 `22367`、校验 mock Core、`integration_test`、`data_isolated`、Core URL 和数据目录。

### 桌面发布

```text
control-center/frontend
  -> Vite desktop build
  -> control-center/desktop/ui
  -> Electron portable
  -> 内置 PyInstaller Bridge :22367
  -> 独立 OAS Core :22267
```

Electron 的 `file://` 页面继续由 `src/api.js` 回退到 `127.0.0.1:22367`。本次没有改变这条桌面通信边界。

## 迁移内容

- 将 `desktop/release/UI-claude` 的完整 React 18/Vite 5 源码、工具和界面参考图迁入 `control-center/frontend`。
- 保留 `api.js`、`views.jsx`、`fields.jsx`、`components.jsx`、`store.js`、`emulator.js` 和两套 E2E，不只迁移外观文件。
- `start.ps1` 删除 `-Prod` 双前端分支，固定调用唯一前端启动器。
- `desktop/build.ps1` 删除 `-Ui` 选择，固定从 `control-center/frontend` 构建。
- `start-dev-stack.ps1` 使用同一前端，并能识别 Windows 预留端口后自动顺延。
- 根启动器把实际前端端口和监听 PID 登记到忽略的 `output/control-center/frontend.json`；再次启动会复用，`-RestartAll` 只结束 PID 一致的已登记前端，避免在 `4212` 场景留下重复实例或误杀未知进程。
- E2E 使用中性的 `OAS_UI_BASE`，兼容旧 `UI_CLAUDE_BASE`；Chromium 路径可由 `CHROMIUM_PATH` 指定。
- 真实三层 E2E 安全门同时支持浏览器直连 Bridge 和 Vite 同源代理，并继续校验返回的隔离标志。
- Playwright 已列入前端开发依赖，测试命令不再依赖未声明的本机包。

## 已删除

- `frontend-preview`：旧静态预览和重复 Mock。
- `desktop/release/UI-claude`：迁移后的旧源码位置及其生成缓存。
- `desktop/release/UI-grok`、`UI-hermes`：未参与当前链路的历史实验目录。
- `promote-to-production.ps1`：完成转正后不再需要的一次性脚本。
- `control-center/使用说明.html`：与 Markdown 重复且已经过时的人工维护副本。
- 旧 `win-unpacked` 和 `builder-debug.yml`：可重新生成的桌面构建产物。

保留了 `release/OAS-Control-Center-0.1.0-portable.exe`，但它仍是 2026-07-26 的旧构建，不能代表当前源码。本次按约定没有重新打完整 portable；下一次桌面阶段验收时应覆盖生成。

## 验证结果

| 验证 | 结果 |
|---|---:|
| `npm ci` | 通过 |
| Vite 普通构建 | 通过，38 modules |
| Vite desktop 构建 | 通过，38 modules |
| PowerShell 解析：5 个启动/构建脚本 | 通过 |
| Node 语法：Vite、Mock、E2E、Electron main/preload | 通过 |
| 轻量 Mock 前端 E2E | 21/21 |
| Bridge 单元回归 | 18/18 |
| 隔离 Bridge + mock Core 集成 | 16/16 |
| 正式前端 + 隔离 Bridge + mock Core 浏览器回归 | 15/15 |
| 隔离测试进程退出检查 | `22268/22368/4212` 均无残留监听 |

第一次运行真实三层 E2E 时，旧安全断言只允许请求 URL 直接显示 `22368`，没有兼容 Vite proxy。修改后它接受当前 UI origin，但必须从 health 响应中确认 `integration_test=true`、`data_isolated=true` 且 Core 指向指定 mock，之后 15/15 通过。

## 剩余风险

1. `npm audit` 报告 Vite 5 开发工具链 1 个 high、1 个 moderate，自动修复要求跨到 Vite 8。当前开发服务只绑定 `127.0.0.1`，本次没有把架构迁移与前端工具链大版本升级混在一起；应单独建升级任务并跑完整 E2E。
2. 完整 Electron portable 本次未重建，尚未对新的 portable 做窗口、DPI、Bridge 子进程和 `file://` 实机验收。
3. `desktop/build.ps1` 仍会把当前控制中心数据库复制为 data seed，这是此前已记录的发布数据风险，不属于本次前端路径收口范围，正式发布前仍需修复。
4. 历史 `handoff/13–18` 保留当时的 `UI-claude` 路径，用于追溯，不应作为当前启动说明。

## 后续规则

- 界面改动只进入 `control-center/frontend`。
- 日常使用 Vite 热更新和隔离联调，不为每次样式改动打 portable。
- 阶段验收时执行 desktop 构建，确认当前源码 hash、Bridge 版本、空数据种子、DPI 和 `file://` 通信。
- 不再创建平行的“新版前端”目录；实验设计用分支或明确的原型文件，验收后合并回唯一源码。
