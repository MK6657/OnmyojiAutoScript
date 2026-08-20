# MK6657 双项目迁移后环境指南

日期：2026-08-15
用途：让接手同事快速理解项目位置、结构、运行方式和当前状态。
性质：本机迁移说明，不是真机验收结案。

---

## 1. 项目具体位置

| 内容 | 位置 |
|---|---|
| OAS 主项目 | `D:\OSAyys` |
| 坐标校准器 | `D:\coordinate-calibrator` |
| 原始交接包（只读归档，不要改） | `D:\vibe_coding\YYSOAS-win\MK6657-双项目开发交接-20260814\` |
| 迁移执行总清单 | `D:\vibe_coding\YYSOAS-win\项目通读与迁移工作清单-20260814.md` |
| OAS 迁移记录 | `D:\OSAyys\handoff\records\migration\Codex-迁移-D盘落地-20260815.md` |
| CC 迁移记录 | `D:\coordinate-calibrator\docs\migration-20260815-local.md` |
| 真机测试证据 | `D:\OSAyys\handoff\records\evidence\`（含 2026-08-15 新增） |
| 运行日志 | `D:\OSAyys\log\` |
| 测试截图/证据产物 | `D:\OSAyys\output\` |
| 测试前配置备份 | `D:\OSAyys\backups\` |

MuMu 模拟器不在项目目录内：安装路径为 `D:\yys\MuMuPlayer`。

---

## 2. `D:\OSAyys` 目录地图

```text
D:\OSAyys
├─ server.py                     Core 服务入口，FastAPI，端口 22267
├─ script.py                     账号 worker / 调度器
├─ gui.py                        旧 QML 桌面入口（非当前主链路）
├─ 启动.bat / 重启Core.bat        控制中心启动入口
├─ requirements.txt / requirements-in.txt
├─ run-oas-tests.ps1             统一测试入口（91 模块 / 503 项，逐模块进程隔离）
├─ config\
│  ├─ template.json              账号配置模板
│  ├─ oas1.json                  当前本机账号配置
│  ├─ deploy.yaml                部署配置（AutoUpdate=false）
│  └─ findjade\
├─ module\                       Core 框架
│  ├─ config\                    pydantic 配置 / 调度
│  ├─ device\                    设备抽象：adb / minitouch / scrcpy / nemu_ipc / windows
│  ├─ ocr\                       ppocr-onnx / zerorpc OCR
│  ├─ server\                    FastAPI 路由、进程管理、WebSocket
│  ├─ gui\                       QML/FluentUI
│  └─ atom\ base\ map\ notify\ team_flow\
├─ tasks\                        游戏任务插件，60+ 个
│  ├─ RealmRaid\                 个人结界突破
│  ├─ Exploration\               困28 探索
│  ├─ RyouToppa\                 寮突破
│  ├─ Component\                 通用战斗 / 弹窗 / 换御魂 / 通用加成
│  └─ GameUi\                    页面识别与跳转
├─ control-center\
│  ├─ frontend\                  唯一 React/Vite 前端，端口 4175（可顺延）
│  ├─ bridge\                    FastAPI Bridge，端口 22367
│  ├─ desktop\                   Electron portable 构建
│  │  ├─ release\OAS-Control-Center-0.1.0-portable.exe
│  │  └─ bridge-dist\oas-control-bridge.exe
│  ├─ launcher\                  start.ps1 / dev-stack / wiring 脚本
│  ├─ docs\ / contracts\
│  └─ data\                      Bridge SQLite（运行时生成）
├─ handoff\                      交接文档体系
│  ├─ README.md
│  ├─ 00-当前状态.md
│  ├─ Codex-待做事项总表.md       唯一开放事项总表
│  ├─ contracts\v1\              跨项目中立证据契约
│  ├─ audits\ decisions\ records\ tasks\ patches\ tools\
├─ deploy\                       安装/部署链
├─ dev_tools\                    资产生成与清理工具
├─ fluentui\                     QML FluentUI 库源码（Qt 构建才需要）
├─ bin\                          scrcpy / droidcast / hermit 运行时二进制
├─ assets\ legal\ .github\
├─ log\ output\ work\ backups\  运行产物 / 证据 / 临时探针 / 备份
└─ .venv\ node_modules\          已重建依赖（不提交）
```

---

## 3. `D:\coordinate-calibrator` 目录地图

```text
D:\coordinate-calibrator
├─ src\coordinate_calibrator\
│  ├─ api\                       REST/WS 路由、幂等、运行时
│  ├─ storage\                   SQLite schema 6、Bundle、artifact
│  ├─ adapters\                  screen / adb / nemu_ipc 采集；OAS 只读适配器
│  ├─ domain\                    坐标几何、统计、比较
│  ├─ web\                       单页前端（原生 JS）
│  └─ server.py settings.py maintenance.py
├─ tests\                        178 项测试
├─ docs\                         架构、安全、数据模型、迁移记录
├─ scripts\                      清理脚本（回收站版）
├─ start.ps1 / stop.ps1 / test.ps1
├─ config.example.toml / config.local.toml
├─ pyproject.toml                版本 0.3.8，Python >=3.11,<3.13
└─ data\ logs\ outputs\          .gitkeep，运行时从空开始
```

---

## 4. 端口与服务

| 服务 | 地址 | 启动方式 |
|---|---|---|
| OAS Core | `http://127.0.0.1:22267` | `D:\OSAyys\control-center\start.ps1` 第 1 层 |
| Bridge | `http://127.0.0.1:22367` | 同上第 2 层；冲突或 Core 目标不一致时拒绝启动，不自动换端口 |
| 前端 | `http://127.0.0.1:4175` | 同上第 3 层；冲突自动顺延 |
| 隔离联调 | mock Core `22268` + Bridge `22368` + 前端 | `control-center\launcher\start-dev-stack.ps1` |
| CC | `http://127.0.0.1:22880` | `D:\coordinate-calibrator\start.ps1` |

停止任务 ≠ 关闭服务：在控制中心界面里停止账号任务；关闭服务要按 PID/端口/命令行核对后再关。

---

## 5. 环境与依赖

- Python：3.11.15（uv 管理；CC 强制 3.11）
- Node：22.23.2；npm：12.0.2
- Git：2.54.0；Windows PowerShell 5.1（项目 `.ps1` 已加 UTF-8 BOM 兼容）
- 已重建：
  - `D:\OSAyys\.venv`（OSA 90 包）
  - `D:\OSAyys\control-center\bridge\.venv`（22 包 + PyInstaller）
  - `D:\OSAyys\control-center\frontend\node_modules` / `desktop\node_modules`
  - `D:\coordinate-calibrator\.venv`（CC 0.3.8 editable）

安装命令（以后重装用）：

```powershell
# OSA 根环境
cd D:\OSAyys
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

# Bridge
cd D:\OSAyys\control-center\bridge
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

# 前端 / 桌面
cd D:\OSAyys\control-center\frontend
npm.cmd ci
cd D:\OSAyys\control-center\desktop
npm.cmd ci

# CC
cd D:\coordinate-calibrator
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[windows,vision,dev]"
```

注意：hermes npm 默认阻止 postinstall 脚本；Electron 二进制需要手工执行：
`cd desktop; node .\node_modules\electron\install.js`。

---

## 6. 本机配置

| 文件 | 来源 | 关键点 |
|---|---|---|
| `D:\OSAyys\config\deploy.yaml` | `deploy\template` 改 | AutoUpdate=false、KeepLocalChanges=true、Webui 127.0.0.1:22267 |
| `D:\OSAyys\config\oas1.json` | 备份恢复的标准版 | serial=127.0.0.1:16384，只启用 Restart |
| `D:\coordinate-calibrator\config.local.toml` | `config.example.toml` | OAS root=D:/OSAyys，adapter 已启用，config=`oas1`，窗口=`2301` |
| Bridge SQLite | 自动生成 | `D:\OSAyys\control-center\data\control_center.db` |
| CC token / 数据库 | 首次启动自动生成 | data 目录从空开始 |

不要提交 `config\*.json`、`config.local.toml`、日志、数据库、令牌到 Git。

---

## 7. Git 分支与回滚

两个仓库都在本地分支 `migration/20260815-local`，未推送。

```powershell
git -C D:\OSAyys branch --show-current      # migration/20260815-local
git -C D:\OSAyys tag --list                 # handoff-20260814, migration-20260815-local
git -C D:\coordinate-calibrator tag --list  # handoff-v0.3.8-20260814, migration-20260815-local
```

回滚到交接基线：

```powershell
git -C D:\OSAyys checkout handoff-20260814
git -C D:\coordinate-calibrator checkout handoff-v0.3.8-20260814
```

---

## 8. 验证命令

```powershell
# OSA 统一测试（期望 91 模块 / 503 项；每个模块独立进程）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\OSAyys\run-oas-tests.ps1

# Markdown 链接
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\OSAyys\handoff\tools\test-markdown-links.ps1

# 前端构建
cd D:\OSAyys\control-center\frontend
npm.cmd run build

# portable 构建（已改为回收站删除）
cd D:\OSAyys\control-center\desktop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -SkipNpmInstall

# CC 测试（期望 178 项 + wheel）
cd D:\coordinate-calibrator
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\test.ps1 -Package
```

---

## 9. 当前状态与重要提醒

- 所有服务当前已停止；`oas1` 为标准配置（Restart 启用，RealmRaid 关闭，绿标 `detect_only`）。
- MuMu `2301`：serial `127.0.0.1:16384`，窗口句柄 `264384`，进程 `MuMuNxDevice.exe`，绑定已验证。
- 2026-08-15 保级 58 完整一轮因安全边界 `enemy_selected`（绿标检测到敌方红色箭头）主动停止；**游戏画面停在 `page_battle`，需要人工确认回主界面后再继续任何任务**。
- 真机证据：`D:\OSAyys\handoff\records\evidence\Codex-实测-RR-HOLD58-20260815-01.md`。
- 所有删除操作必须走回收站；本项目相关脚本已统一为 `Remove-ItemRecycleBin`。

### 2026-08-15 迁移整合修复结果

- CC 导出保留 `oas.res.v1` 兼容字段，并在来源帧 ID、SHA-256、画布 profile 和 mapping revision 齐全时附带中立 v1 `CandidateEnvelope`；仍为 `candidate_only`，不会写回 OAS。
- Bridge 启动脚本统一优先使用 `control-center\bridge\.venv`；每个数据目录有进程锁，22367 被占用或指向其他 Core 时直接失败，避免共享 SQLite 的多实例漂移。
- Core 启动/停止/关服控制入口统一为 POST；跨站 Origin 的写请求被拒绝；默认监听地址回退为 `127.0.0.1`。如配置了 `--key`/Password，写请求需带 `X-OAS-Key`，Bridge 可通过 `OAS_CORE_KEY` 传递。
- Core 非回环绑定现在默认拒绝；只有显式启用 `Webui.EnableRemoteAccess` 且配置 `--key`/Password 才会启动，HTTP/WebSocket 远程入口均要求密钥。
- OAS 账号配置名经过路径边界校验，Windows 删除通过回收站执行；CC `start.ps1 -Install` 优先使用 uv 对指定解释器安装依赖。
- `run-oas-tests.ps1` 已改为每个测试模块独立 Python 进程，消除导入顺序污染；最新证据为 `IMPORT_OK 91`、`91/91` 模块通过、`503` 项通过。此前单进程 `512` 项为顺序依赖快照，不再作为验收口径。
- Bridge/CC 的 FastAPI、Uvicorn、Pydantic、HTTPX、WebSocket 版本声明已对齐并锁定；`module.device` 启动时加载 `pkg_resources` 兼容层，适配新版 setuptools。
- 离线回归：CC `178/178`，OAS 全量 `91 模块 / 503 项`（含 Bridge）；未启动服务或真实设备任务。

---

## 10. 建议阅读顺序（同事接手）

1. 本文件
2. `D:\OSAyys\handoff\README.md`
3. `D:\OSAyys\handoff\00-当前状态.md`
4. `D:\OSAyys\handoff\Codex-待做事项总表.md`
5. `D:\OSAyys\handoff\records\migration\Codex-迁移-D盘落地-20260815.md`
6. `D:\OSAyys\handoff\records\evidence\Codex-实测-DEVICE-BIND-20260815-01.md`
7. `D:\OSAyys\handoff\records\evidence\Codex-实测-RR-COMBAT-001-20260815-01.md`
8. `D:\OSAyys\handoff\records\evidence\Codex-实测-RR-HOLD58-20260815-01.md`
9. `D:\coordinate-calibrator\README.md` 和 `docs\migration-20260815-local.md`
