# Coordinate Calibrator 全貌只读审计

日期：2026-08-08（Asia/Hong_Kong）  
目标：`D:\coordinate-calibrator`  
范围：测试、文档、启动/停止脚本、打包与依赖、运行日志、旧会话恢复、OAS 适配边界，以及这些边界暴露出的直接正确性问题。  
约束：不修复，不启动或停止服务，不连接真实 MuMu/ADB，不修改 OAS 业务文件。

## 1. 总体裁定

当前版本不是“可发布、可长程验收”的完成状态。离线核心测试通过，REST 路由文档基本完整，OAS 业务文件没有发现写入路径；第一轮审计识别出 3 项 P1、10 项 P2 和 2 项 P3。

父代理随后对四路代理结论逐项做了源码、纯内存用例、临时目录测试、当前数据库和 wheel 构建复核，并在本文件第 9 节追加终版裁定。终版新增了坐标正确性、前端跨画布竞态、远程绑定策略、Windows DPI/句柄身份、事件循环阻塞、遗留工作区迁移和连续实时采集范围等问题。第 2 至 8 节保留第一轮证据；严重度、开放事项和修复顺序以第 9 节为准。

当前没有发现 P0。不能依据 38/38 离线测试把坐标输出、实时采集、多实例、打包、浏览器工作台或实机链路标记为结案。

## 2. Findings

### P1-01 多实例只按端口隔离，共享状态会互相干扰

证据：

- [start.ps1](/D:/coordinate-calibrator/start.ps1:11) 只检查传入端口，没有项目级 PID、互斥锁或数据库所有权锁。
- [start.ps1](/D:/coordinate-calibrator/start.ps1:64) 所有端口共用 `logs/uvicorn.stdout.log` 和 `logs/uvicorn.stderr.log`。
- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:70) 所有实例默认共用同一个 `data/index.sqlite3`。
- [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:132) 控制租约只保存在单进程内存中，第二个进程不会看到第一个进程的租约。
- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:73) 每个进程生成自己的随机令牌；[app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:149) Cookie 未按端口隔离。浏览器 Cookie 按主机和路径匹配，不按端口隔离。
- [uvicorn.stderr.log](/D:/coordinate-calibrator/logs/uvicorn.stderr.log:4) 最后只保留了临时 `22881` 启动记录；同目录 stdout 同时包含另一实例的请求。
- 实测 `uvicorn.stdout.log` 有 766 个 NUL 字节、223 条 `401 Unauthorized`，仅 1 条 `200 OK`。这是固定日志被不同实例/重启复用以及令牌互相覆盖后的实证。

影响：两个实例可以同时修改同一会话，且各自认为持有有效租约；不同端口页面会覆盖同主机认证 Cookie；日志不再可作为可靠证据。`stop.ps1` 默认只停止一个端口，不能保证其他实例已经退出。

### P1-02 GET 工作区会恢复全部旧外部来源并产生设备/数据库副作用

证据：

- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:179) 的 `GET /workspaces` 调用 `manager.list_workspaces()`。
- [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:165) 工作区序列化会逐个调用 `get(session_id)`。
- [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:190) 首次读取会调用 `_restore_external_source()`。
- [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:248) 恢复会创建 ADB/Nemu 适配器；失败时把会话改为 `rebind_required` 并持久化。
- [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:307) 页面启动即读取全部工作区。
- 当前只读数据库统计为 9 个会话，其中 3 个 `nemu_ipc`、2 个 `screen_visible`、4 个旧载荷没有 `capture_source`。3 个 Nemu 会话分别处于 `bound/bound/capturing`。

影响：只是打开页面或刷新画布列表，就可能为 3 个旧画布顺序建立 3 个 MuMu IPC 连接；每个初始化最长等待 5 秒，还可能改写旧会话状态。读取接口不应隐式恢复所有设备资源。

日志修订：现有 28 条 `capture_source_restore_failed` 的 session ID 全部不在当前生产数据库中，且尺寸/顺序与单元测试固定数据吻合。因此这些日志是测试污染，不能证明当前 3 个真实旧会话必然恢复失败；真实恢复仍未执行验证。

### P1-03 wheel 缺失 Web 静态资源，安装包不可运行

证据：

- [pyproject.toml](/D:/coordinate-calibrator/pyproject.toml:22) 只配置包发现，没有 `package-data` 或等效资源声明。
- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:72) 假定安装包内存在 `coordinate_calibrator/web`。
- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:95) 导入时立即挂载该目录，不存在则直接抛异常。
- 在临时副本中构建 wheel 成功，但 wheel 内 `index.html/app.js/styles.css` 三项均不存在；安装后导入报 `RuntimeError: Directory ... coordinate_calibrator\web does not exist`。

影响：README 的 editable 安装可以借用源码目录而暂时正常，正式 wheel、离线分发和干净环境安装均不可用。现有测试没有构建或安装 wheel。

### P2-04 启动器会回退到 OAS 虚拟环境，`-Install` 可修改 OAS 运行依赖

证据：

- 当前项目没有 `.venv`。
- [start.ps1](/D:/coordinate-calibrator/start.ps1:16) 在本地 `.venv` 不存在时，从 `config.local.toml` 解析 OAS 根目录并选择 `D:\OSAyys\.venv\Scripts\python.exe`。
- [start.ps1](/D:/coordinate-calibrator/start.ps1:37) `-Install` 会向“当前选中的 Python”执行 editable 安装，因此会直接改动 OAS `.venv`。
- 当前实际选中环境是 OAS Python 3.11.15。运行依赖可导入，但构建工具组合为 `setuptools 79.0.1 + packaging 20.9`；在临时副本中执行 `pip wheel --no-build-isolation` 会因 `canonicalize_version(... strip_trailing_zero=...)` 不兼容而失败。
- `pip check` 对该构建工具冲突仍报告 `No broken requirements found`。

影响：独立工具的安装操作可能升级/降级 OAS 的 NumPy、OpenCV、Pillow、FastAPI 等依赖。当前 ABI 已正常，但环境再次漂移会同时影响 OAS 和坐标工具。

### P2-05 服务重启后旧页面不会恢复认证，产生持续 401 轮询

证据：

- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:73) 未固定环境变量时，每次进程启动更换令牌。
- [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:53) API 包装器收到 401 只抛错，没有重新加载根页面或停止轮询。
- [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1907) 每秒调用一次 `refreshSamples()`；[app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1419) 失败后下一秒继续。
- `uvicorn.stdout.log` 已有 223 条 401，形成实际日志风暴。

影响：服务重启或另一端口覆盖 Cookie 后，旧标签页会表现为“没反应”，并持续刷日志，直到用户完整刷新根页面获取新 Cookie。

### P2-06 文档给出的测试命令会污染生产运行日志

证据：

- [README.md](/D:/coordinate-calibrator/README.md:65) 和 [test-plan.md](/D:/coordinate-calibrator/docs/test-plan.md:16) 直接从源码运行测试，没有设置隔离的 `CALIBRATOR_ROOT`。
- [test_api_contract.py](/D:/coordinate-calibrator/tests/test_api_contract.py:12) 只临时替换 `CALIBRATOR_DATA_ROOT`，没有替换项目根或日志根。
- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:93) 始终按 `PROJECT_ROOT/logs` 配置日志。
- [logging_setup.py](/D:/coordinate-calibrator/src/coordinate_calibrator/logging_setup.py:14) 全局 logger 一旦已有 handler，就不会切换到新的测试根目录。
- `2026-08-08.log` 中出现多组 `320x180/710x413/400x200` 固定测试帧和 `adapter unavailable` 假适配器错误。28 个恢复失败 ID 全部不在生产数据库。

影响：运行日志混入离线测试事件，历史审计可能把模拟错误误判为实机失败。默认测试命令不满足“只读验证”的预期。

### P2-07 停止脚本强制杀进程，应用没有全局 shutdown 清理

证据：

- [stop.ps1](/D:/coordinate-calibrator/stop.ps1:16) 直接 `Stop-Process -Force`。
- `app.py` 没有 FastAPI lifespan/shutdown 钩子。
- [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:651) 只有显式关闭单个 session 时才释放鼠标 observer 和外部 frame source。

影响：停止服务时不能保证 Nemu disconnect、鼠标观察器解除、后台 executor 结束和日志刷新按正常顺序完成。SQLite 每次操作使用短连接，降低了数据库损坏概率，但不能替代生命周期清理。

### P2-08 `/capabilities` 是静态声明，不代表当前环境真实可用

证据：

- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:158) 无条件声明 Windows、screen、ADB、Nemu 和鼠标能力。
- 当前 `adb` 不在 PATH，但 API 仍会把 `adb` 放进 `capture_sources`。
- 前端虽按 capabilities 渲染，后端返回值本身没有 probe 结果，因此“能力动态显示”只是静态列表驱动。

影响：用户仍可选择当前不可用来源，直到真正 open/capture 时才得到错误。健康页不能用于启动前诊断。

### P2-09 椭圆旋转和退化多边形存在后端正确性缺口

证据：

- [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:634) 绘制椭圆时应用 `rotation`。
- [geometry.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/geometry.py:41) 外接框忽略旋转；[geometry.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/geometry.py:156) 点包含判断也忽略旋转，而同文件采样多边形路径会应用旋转。
- [geometry.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/geometry.py:112) 多边形只检查点数、边界和自交，没有检查面积、重复点或共线退化。
- 只读调用验证：三个点 `[(10,10),(10,20),(10,20)]` 被 `validate_shape()` 接受。
- 38 项测试没有旋转椭圆、零面积多边形、重复点三角形或退化画笔测试。

影响：导入带旋转椭圆的工程后，关系和 OAS ROI 可能与画面不一致；零宽/零高三角拖拽可生成后端认可的无效区域。

### P2-10 历史帧没有垃圾回收，当前已有 12 张未引用 PNG

证据：

- 当前数据库只有 1 条 frame 记录，但 `data/sessions` 下有 13 张 PNG。
- 按 `session_id/frame_id.png` 推导，12 张未被数据库引用，总计 6,781,655 字节。
- 12 个 session 目录中有 5 个目录不属于当前 9 个数据库会话，含 5 个文件、3,721,408 字节。
- [workspace-bundle.md](/D:/coordinate-calibrator/docs/workspace-bundle.md:72) 已诚实记录“旧帧目录尚未自动垃圾回收”。

影响：长期导入/删除会持续占用磁盘，且人工读取目录时容易把孤儿截图当成当前证据。

### P2-11 远程模式的令牌不是访问控制

证据：

- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:143) 根页面不要求令牌。
- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:149) 任意能访问根页面的客户端都会收到有效令牌 Cookie。
- [README.md](/D:/coordinate-calibrator/README.md:61) 允许显式打开远程绑定，同时要求外部网络边界和额外安全审查。

影响：默认 loopback 下主要是 CSRF 防护，风险可控；一旦启用远程绑定，局域网访问者可以先访问根页面自行获得令牌，因此不能把该令牌当作远程身份认证。

### P2-12 测试覆盖明显低于 test-plan 声明

现有 38 项测试约 647 行，对约 3,888 行 Python 源码提供了有价值但有限的单元覆盖。`coverage.py` 未安装，无法给出行覆盖率；从测试调用关系可确认以下盲区：

- 37 条 REST/WS 路由中，唯一 API contract 测试只实际触达 health、创建 session、读取 session、窗口列表四类路由。
- WebSocket、批量 HTTP 契约、导出下载、工作区 bundle、浏览器多选/拖动/缩放、401 恢复均无自动化测试。
- `app.js` 约 1,900 行，仅做了 `node --check`，没有 DOM/浏览器测试。
- `start.ps1/stop.ps1` 只有语法检查，没有多实例、端口冲突、日志、令牌和停止清理测试。
- Windows provider、低级鼠标钩子、真实 ADB、真实 Nemu、OAS `from_environment()` 初始化均未真实执行；现有测试使用 fake runner/source。
- 没有多进程共享 SQLite、跨进程租约、WAL 崩溃恢复、打包安装、历史孤儿清理测试。
- [test-plan.md](/D:/coordinate-calibrator/docs/test-plan.md:7) 声称覆盖半开边界、椭圆、三角、画笔、异常值、MAD/P05/P95/协方差；测试源码没有这些边界的独立断言。

### P2-13 `start.ps1` 为读取 host 导入完整应用并产生持久化副作用

证据：

- [start.ps1](/D:/coordinate-calibrator/start.ps1:60) 通过 `from coordinate_calibrator.api.app import SERVER_HOST` 读取一个配置值。
- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:85) 模块导入立即构造 `SessionManager` 和 Repository。
- [repository.py](/D:/coordinate-calibrator/src/coordinate_calibrator/storage/repository.py:18) Repository 构造会创建目录、打开数据库、设置 WAL，并在需要时执行迁移/备份。
- 临时根目录复现仅执行 host import，就生成了 `data/index.sqlite3` 和 `logs/2026-08-08.log`。

影响：真正启动 Uvicorn 前，预检进程已经打开或迁移生产数据库；如果之后启动失败，仍会留下数据库/WAL/日志副作用。

### P3-14 文档存在计数和错误码轻微漂移

证据：

- [test-plan.md](/D:/coordinate-calibrator/docs/test-plan.md:5) 写 36 项；README 和实际源码均为 38 项。
- [protocol.md](/D:/coordinate-calibrator/docs/protocol.md:66) 的错误码列表缺少实际返回的 `version_required`、`selection_changed`、`annotation_required` 和 `invalid_session_id`，对应 [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:346)、[app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:381)、[app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:444)、[app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:449)。

通过项：REST/WS 路由表共 37 条，按方法和归一化路径比较，文档与实现完全一致；README/docs 相对链接没有断链。

### P3-15 日志没有轮转/保留策略，固定 Uvicorn 文件会无限增长

证据：

- [logging_setup.py](/D:/coordinate-calibrator/src/coordinate_calibrator/logging_setup.py:15) 只在进程启动时按日期选择一次文件，跨日不切换，也没有大小/保留期轮转。
- [start.ps1](/D:/coordinate-calibrator/start.ps1:66) Uvicorn stdout/stderr 始终写固定文件。
- 401 每秒轮询已经证明异常状态可以持续增长日志。

## 3. 环境与数据基线

- 项目类型：本地项目，没有 `.git`，没有项目 `.venv`。
- 服务状态：审计开始和结束时 `127.0.0.1:22880` 均无监听；没有 Coordinate Calibrator Python 进程。本轮未启动或停止服务。
- 当前启动器实际首选：`D:\OSAyys\.venv\Scripts\python.exe`。
- OAS Python：3.11.15；FastAPI 0.104.1；Pydantic 2.10.0；Uvicorn 0.38.0；Pillow 10.2.0；pywin32 306；Shapely 2.0.2。
- 当前 ABI：NumPy 1.24.3 + OpenCV 4.7.0，`import cv2,numpy` 成功。旧版“NumPy 2.x 与旧 cv2 ABI 冲突”是历史状态，当前不可继续当作阻塞项。
- 系统 Python：3.12.10；NumPy 2.4.4 + OpenCV 4.13.0 可导入，但缺 FastAPI/Pydantic/Uvicorn/Shapely，不满足当前服务启动要求；Pillow 12.2.0 也超出项目声明的 `<12`。
- OAS `oas1.json`：UTF-8 JSON 可解析，serial 和 emulatorinfo 均存在，推导 instance 0，MuMu 目录和 1 个 IPC DLL 候选存在。
- OAS 配置 SHA-256：`138C234D06B2661A3649C36CA8A28EAEF47C39851D150A63413F8456D810D44F`；审计前后未变化。
- 当前库：schema 3，9 sessions、1 frame、24 annotations、1 workspace。

## 4. 已验证通过

- 隔离临时根目录运行 `unittest`：38/38 通过，2.818 秒；生产数据库与生产日志时间戳在该次父代理复跑前后保持不变。
- 临时副本运行 `compileall`：通过。
- `node --check src/coordinate_calibrator/web/app.js`：通过。
- PowerShell AST 解析 `start.ps1/stop.ps1`：0 个语法错误。
- REST/WS 路由文档：37/37 方法和路径一致。
- README/docs 相对链接：0 个断链。
- schema 2 -> 3 的现有 unittest 通过，复合 frame 主键和迁移前备份有测试。
- OAS exporter 的生产 API 输出目录被限制在工具自己的 `outputs`；没有 OAS apply 端点。
- `OasReadOnlyAdapter` 的路径逃逸测试通过；Nemu live adapter 只调用 OAS `NemuIpcImpl` 的 connect/screenshot/disconnect，不调用触控方法。
- 当前 OAS 业务配置哈希未改变，服务未连接真实设备。

## 5. 可复现命令

### 5.1 隔离运行测试

```powershell
$tmp = Join-Path $env:TEMP ("coordinate-calibrator-audit-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$env:CALIBRATOR_ROOT = $tmp
$env:CALIBRATOR_CONFIG = Join-Path $tmp "missing.toml"
$env:PYTHONPATH = "D:\coordinate-calibrator\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
& D:\OSAyys\.venv\Scripts\python.exe -m unittest discover -s D:\coordinate-calibrator\tests -v
```

### 5.2 检查当前 ABI

```powershell
& D:\OSAyys\.venv\Scripts\python.exe -c "import cv2,numpy; print(cv2.__version__, numpy.__version__)"
```

预期当前输出：`4.7.0 1.24.3`。

### 5.3 在临时副本复现 wheel 缺资源

```powershell
$tmp = Join-Path $env:TEMP ("coordinate-calibrator-wheel-" + [guid]::NewGuid().ToString("N"))
Copy-Item D:\coordinate-calibrator $tmp -Recurse
python -m pip wheel --no-deps --no-build-isolation -w "$tmp\dist" $tmp
tar -tf (Get-ChildItem "$tmp\dist\*.whl").FullName | Select-String "coordinate_calibrator/web"
```

当前结果：无匹配项。

### 5.4 检查日志污染和 401

```powershell
rg -a -c "401 Unauthorized" D:\coordinate-calibrator\logs\uvicorn.stdout.log
rg -n "capture_source_restore_failed" D:\coordinate-calibrator\logs\2026-08-07.log D:\coordinate-calibrator\logs\2026-08-08.log
```

当前分别为 223 条 401、28 条 restore failure；28 个失败会话均不在当前数据库。

### 5.5 只读查看数据库时避免生成 WAL

使用 SQLite URI `mode=ro&immutable=1`，不要直接导入 `coordinate_calibrator.api.app`。后者会初始化 Repository。

## 6. 实机未验证项

- 真实 MuMu 窗口 `2301` 与干扰窗口的明确绑定。
- 当前 instance 0 的 Nemu 初始化、首帧、颜色、方向、1280x720、断开和重连。
- 真实 ADB；当前 shell 的 PATH 中没有 `adb`。
- 多显示器负坐标、Per-Monitor DPI、窗口缩放、句柄复用和 canvas child 变化。
- 低级鼠标钩子、前后帧配对及 P95 不超过 2 个画布像素。
- 两个 MuMu 来源并行 10 分钟、串帧为 0、黑帧为 0。
- 服务停止时 Nemu/鼠标/线程的真实释放。
- 远程绑定安全性、多端口隔离和崩溃恢复。本轮为遵守“不得改变服务状态”没有主动启动这些场景。
- 完整浏览器验收：六种工具、拖动、批量恢复、工程导入导出和截图替换层。

## 7. 审计副作用声明

父代理的 38 项复跑使用隔离临时根目录，确认未修改生产数据库和生产日志。委派审查期间，另一次按项目文档原命令运行的测试把 `logs/2026-08-08.log` 从第 43 行追加到第 56 行；数据库时间戳、服务状态和 OAS 配置哈希未改变。追加内容保留作为“默认测试命令污染运行日志”的现场证据，没有删除或改写。

## 8. 建议修复顺序（本轮未实施）

1. 项目级单实例锁、PID/所有权文件、端口无关的状态隔离，以及 Cookie/令牌重启恢复。
2. 将工作区读取与外部来源恢复拆开，只对当前活动画布显式重连。
3. 修复 package-data 并增加 wheel 构建、安装、启动 smoke test。
4. 禁止 `-Install` 自动写 OAS `.venv`，建立项目独立 `.venv` 和锁定依赖。
5. 隔离测试日志，补 shutdown 生命周期、动态 capabilities 和历史孤儿清理。
6. 修复旋转椭圆和退化多边形，并补浏览器/API/并发测试。
7. 最后进行 `2301`、ADB/Nemu、DPI、多画布长程实机验收。

## 9. 父代理终版复核

复核时间：2026-08-08。复核边界仍为只读：没有启动或停止服务，没有连接真实 MuMu/ADB，没有修改 `D:\coordinate-calibrator` 的源码、配置、数据库或日志，也没有写入 OAS 业务目录。父代理运行测试时将 `CALIBRATOR_ROOT`、数据、日志和 pycache 全部指向临时目录；项目 `logs` 的大小和时间戳在复跑前后未变化。

### 9.1 终版状态

终版裁定为：无 P0；存在 11 个 P1 问题组、12 个 P2 问题组，以及文档和验收缺口。P1 的含义是“在把坐标结果用于 OAS、开放远程模式、启用真实窗口采样或声明操作台稳定之前必须处理”，不表示当前默认 loopback、截图导入的每一步都会立即失败。

第一轮的 wheel 问题由 P1 调整为 P2：它阻断正式打包和独立分发，但当前源码目录下的 editable 运行仍可使用。第一轮其他已确认事实继续成立。

### 9.2 P1：坐标、安全、状态和范围阻塞

#### P1-F01 多端口实例共享状态，租约和认证互相失效

第一轮第 P1-01 项成立。父代理独立复核到 `uvicorn.stdout.log` 中 223 条 401 和 766 个 NUL 字节；[start.ps1](/D:/coordinate-calibrator/start.ps1:11) 仅按端口检查，[runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:132) 的租约只在单进程内存中，数据库、固定日志和主机 Cookie 仍被不同端口共享。

#### P1-F02 远程绑定门禁可绕过，令牌可由匿名访问者自行取得

- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:77) 无条件优先采用 `CALIBRATOR_HOST`，没有受 `ALLOW_REMOTE` 约束。
- 临时根目录复现：`CALIBRATOR_ALLOW_REMOTE=false`、`CALIBRATOR_HOST=0.0.0.0` 时，导入后的有效值为 `SERVER_HOST=0.0.0.0`、`ALLOW_REMOTE=False`。
- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:143) 的公开根页面会向任何访问者设置有效令牌 Cookie；[test_api_contract.py](/D:/coordinate-calibrator/tests/test_api_contract.py:20) 还把“401 -> GET / -> 受保护 POST 成功”固定为当前契约。
- 没有 Trusted Host、Origin 或同等门禁。默认回环地址降低了暴露面，但一旦环境变量误设、显式远程绑定或发生 DNS rebinding，随机令牌不能提供身份认证。

#### P1-F03 读取工作区会连接设备，Nemu 恢复前不核对持久化身份

- 第一轮第 P1-02 项成立：[runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:161) 的工作区 GET 会逐画布进入 `get()`，冷启动时触发 [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:248) 的外部来源恢复并可能写入 `rebind_required`。
- [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:241) 从当前环境/OAS 配置构造 Nemu 适配器，没有先把新适配器 `identity` 与会话中的 `capture_identity` 比较；身份比较直到真正截图后的 [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:586) 才发生。OAS 配置从设备 A 改到 B 时，程序会先连接并读取 B，之后才拒绝帧。
- 当前数据库确有 3 个 Nemu 会话，因此该路径不是纯理论分支。

#### P1-F04 同步 I/O 和几何重计算阻塞 FastAPI 事件循环

- [app.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/app.py:174) 起的路由均为 `async def`，但 SQLite、Pillow、ADB、Nemu、文件导出和 `SessionManager` 调用都在事件循环线程同步执行，没有 `to_thread` 或执行器边界。
- 临时 ASGI 复现把工作区读取阻塞 0.40 秒；原本计划在 0.02 秒后执行的 `/health` 直到 0.401 秒才完成，证明健康检查和 WebSocket 会被同一阻塞调用拖住。
- [statistics.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/statistics.py:113) 对选中标注两两计算关系；[geometry.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/geometry.py:180) 对多边形做边对边嵌套比较。默认上限 200 个、每个 256 条边时，仅成对边比较上界约为 1,304,166,400 次，可长时间冻结整个服务。

#### P1-F05 实时预览点击保存的是截图像素，不是游戏画布坐标

[app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1375) 的 `addPoint()` 直接把预览图自然像素 `x/y` 作为后端 canvas 坐标提交，没有调用已存在的 `imageToCanvasPoint()`。对当前曾出现的 `1342x783 -> 1280x720` 映射，预览中心当前会保存 `(671,391.5)`，正确画布坐标应为 `(640,360)`，横向误差 31 像素、纵向误差 31.5 像素。

#### P1-F06 圆形、复杂多边形和小数外接框可生成错误候选

- [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:541) 与 [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:575) 只取水平点的 x 差和垂直点的 y 差。直接执行项目函数验证：90 度画布上的半径 50 圆，正向和反向转换均退化为 `r=1`。
- [statistics.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/statistics.py:61) 用多边形顶点算术平均值作为推荐点击点。U 形多边形得到推荐点 `(2.0,2.25)`，而 `contains_point()` 判定该点位于形状外。OAS 候选可能因此给出区域外点击点。
- [geometry.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/geometry.py:30) 使用 `floor(x) + ceil(width)` 形成外接框，而不是 `ceil(x+width)-floor(x)`。`x=0.9,width=0.2` 的形状实际右界为 1.1，报告却给出右界 1，ROI 会裁掉一部分形状。
- [geometry.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/geometry.py:190) 只检查对方顶点是否位于多边形内来判断包含。父代理构造的 U 形多边形把横跨凹口、中心实际在形状外的矩形错误标为 `contains`。

#### P1-F07 工程包导入忽略自身画布规格和方向

[app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1035) 导出 `canvas` 和 `mapping`，但 [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1053) 导入时只传图片和标注；[app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:945) 创建新画布时继承“当前活动画布”规格。跨分辨率或 90/270 度工程导入会错位、越界或失败，且导出的 mapping 审计快照没有保留到新会话。

#### P1-F08 前端异步响应和两套租约可形成跨画布混合状态

- 创建、移动、单项显隐和多项操作在响应返回后直接修改全局 `state.annotations`，例如 [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:766)、[app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:841) 和 [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1553)，没有校验发起请求时的 `session_id/canvasRequestSerial`。切换画布期间，A 的响应可写进 B 的当前 UI。
- [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:406) 先把 `state.session` 换成新画布，再获取服务端租约；租约失败没有恢复旧画布，形成“新 session + 旧截图/列表”的混合状态。
- [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1705) 的“接管当前标签”只改 localStorage，不获取服务端租约；[app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1375) 的实时预览点击又不调用 `ensureControl()`。本地只读状态和服务端写权限可能相互矛盾。

#### P1-F09 Windows DPI 与窗口身份契约没有落地

- `config.example.toml` 的 `per_monitor_dpi` 和 `mouse_backend` 在源码中没有任何读取点；进程没有调用 Per-Monitor DPI awareness API。只读取 [provider.py](/D:/coordinate-calibrator/src/coordinate_calibrator/adapters/windows/provider.py:199) 的 `GetDpiForWindow()` 不能保证 ClientToScreen 与低级鼠标钩子使用同一物理坐标基准。
- [provider.py](/D:/coordinate-calibrator/src/coordinate_calibrator/adapters/windows/provider.py:180) 刷新窗口列表时不清空旧 `_targets/_candidates`；[provider.py](/D:/coordinate-calibrator/src/coordinate_calibrator/adapters/windows/provider.py:220) 绑定时只检查 HWND 仍是窗口，不重新核对当前 PID、父子关系和句柄身份。Windows 句柄复用后可能静默绑定到另一个进程或子窗口。
- 前端 [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1113) 还会丢弃小于 `1000x500` 的有效候选，与动态缩放和 DPI 校准目标冲突。

#### P1-F10 连续实时采集和多画布并行 worker 尚未实现

- 当前 `start_capture()` 只切换状态；真正截图仅由用户点击 [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:1346) 的“保存当前帧”触发。
- 全仓库没有持续 capture loop、每画布 capture worker 或 frame queue；前端定时器只有租约、控制权和样本列表轮询。
- 现有文档已诚实记录该范围：[坐标标注操作台审计与后台帧源修复](/D:/OSAyys/handoff/Codex-坐标标注操作台审计与后台帧源修复-20260807.md:71) 明确称当前只是可靠单帧采集；[第二阶段实施记录](/D:/OSAyys/handoff/Codex-坐标标注操作台第二阶段功能实施与审核记录-20260807.md:51) 把连续刷新和多画布并行列为后续项。
- 因此“截图操作台”可继续评测，但不能把“实时内存画面、多画布并行采集 10 分钟”当作已实现功能。

#### P1-F11 旧会话没有迁入 legacy workspace，当前 16 个标注从 UI 不可达

当前只读数据库有 9 个 session、1 个 workspace、5 条 workspace-canvas 关系；4 个 session 未关联任何 workspace。未关联 session 中 `sess_c766...` 有 3 个标注、`sess_d0acc...` 有 13 个标注，合计 16 个。前端 [app.js](/D:/coordinate-calibrator/src/coordinate_calibrator/web/app.js:307) 只加载服务器返回的第一个 workspace，没有旧 session 入口。原实施方案要求为旧会话创建 legacy workspace，当前现场证明该迁移没有完成。

### 9.3 P2：稳定性、持久化、发布和治理

1. **正式包缺 Web 资源。** 第一轮 P1-03 事实成立，终版调为 P2。父代理用 Python 3.12 在临时副本构建 wheel，35 个成员中 `web_assets=[]`；[pyproject.toml](/D:/coordinate-calibrator/pyproject.toml:22) 缺 package-data。
2. **数据库与帧文件非原子且无启动对账。** [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:546) 先写文件再写数据库，修剪也分步执行；表没有外键。当前有 12 张数据库未引用 PNG，共 6,781,655 字节，其中 5 张属于已删除 session。
3. **两类迁移可在中断后留下不完整状态。** [repository.py](/D:/coordinate-calibrator/src/coordinate_calibrator/storage/repository.py:98) 的 `frames_v3` DDL 不在事务中；纯内存复现显示回滚后空表仍存在。重新打开 `schema_version=99` 的临时数据库会被静默改写为 `3`。此外 [runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:366) 逐条迁移旧嵌入标注/样本，中途失败后下次只要发现一条规范化记录就会丢弃未迁移的旧集合。
4. **生命周期锁和清理不完整。** capture/source/close 使用 per-session 锁，但 bind/import/arm/disarm/鼠标回调没有统一串行化；[runtime.py](/D:/coordinate-calibrator/src/coordinate_calibrator/api/runtime.py:651) 在全局锁内执行 observer/source close，慢断开会阻塞所有画布，异常还会中断后续删除。应用没有 shutdown lifespan，`stop.ps1` 直接强杀。
5. **Nemu timeout 只限制等待，不终止底层调用。** `future.cancel()` 不能停止已经运行的 native 调用；初始化、截图或 disconnect 永久卡住时，线程和 IPC 对象可能残留。关闭回调还可在 Manager 全局锁内等待最多约 5 秒。
6. **输入和全局资源上限不完整。** HTTP 请求体要在 Pydantic 校验前完整接收；ADB `capture_output=True` 在 20 MB 检查前已把 stdout 全读入内存；没有 workspace/session/总磁盘/总输出配额。
7. **配置与能力声明不真实。** `/capabilities` 静态声称 ADB/Nemu/鼠标可用，当前 PATH 实际没有 ADB；`per_monitor_dpi`、`mouse_backend`、`oas.enabled`、`oas.window_title` 是未消费配置。格式错误的 TOML 被静默当作空配置，不产生诊断。
8. **几何统计仍有独立错误。** [statistics.py](/D:/coordinate-calibrator/src/coordinate_calibrator/domain/statistics.py:196) 把协方差矩阵 `[0][0]` 写成 `cov(x,y)` 而不是 `var(x)`；点 `(0,0),(2,0)` 的正确矩阵应为 `[[1,0],[0,0]]`，当前返回全零。旋转椭圆在采样时应用 rotation，但 bbox/contains 忽略；共线、重复点和零面积多边形仍可通过校验。后端 90/180/270 度半开边界也会把合法边缘映射到 width/height 后拒绝或返回屏幕矩形外坐标。
9. **前端边界与失败回滚不完整。** 拖动标注出界时逐点 clamp 会压缩/变形原形状；首张截图导入先创建 canvas，失败时没有像“新图层”路径那样删除空 canvas；复制图层不保持 ordinal/label_mode，且没有重命名入口。
10. **前端次级交互和性能缺口。** 类型过滤状态、仅显示选中按钮、刷新后的旧选中 ID、Shift 范围选择、按筛选全选、pointercancel、画笔原始点增长、每秒无条件样本轮询、REST 超时/取消、workspace 选择器和键盘无障碍均未形成稳定契约。
11. **独立环境与启动边界不成立。** 项目没有 `.venv`，启动器会回退 OAS `.venv`，`-Install` 会修改 OAS 环境；Nemu adapter 将 OAS 根插入 `sys.path`。当前 NumPy 1.24.3 + OpenCV 4.7.0 ABI 正常，但跨项目耦合仍会造成升级漂移。
12. **API 并发与协议尚未闭合。** 租约是进程内对象且 heartbeat/release 存在检查后再写竞态；创建类请求没有 `Idempotency-Key`；GET/list 没有对象 ETag；session 在 WebSocket 存续期间删除会异常退出而非发送终态事件；`OasReadOnlyAdapter` 目前只被测试使用，没有运行端点。

### 9.4 文档与测试裁定

- `README.md` 写 38 项，实际也是 38 项；[test-plan.md](/D:/coordinate-calibrator/docs/test-plan.md:5) 仍写 36 项。
- 38/38 unittest、compileall、`node --check` 和 PowerShell AST 均通过。该结果证明后端基础路径没有语法/现有回归错误，但不能覆盖约 1900 行前端交互、浏览器竞态、真实 Windows hook/DPI、真实 ADB/Nemu、打包安装和多进程。
- [protocol.md](/D:/coordinate-calibrator/docs/protocol.md:62) 声称客户端 WebSocket 重连后会重新加载 REST 状态，但前端没有创建 WebSocket；协议列出的 REST/WS 方法和归一化路径本身为 37/37 对齐。
- [repair-20260807.md](/D:/coordinate-calibrator/docs/repair-20260807.md:26) 关于“启动器 loopback 在未允许远程时保持强制”的声明被 P1-F02 推翻；“并发旧请求保护”只覆盖少数路径，不能代表所有标注写操作。
- 现有 8 月 8 日应用日志含大量固定 `320x180/710x413/400x200` 测试帧；这些记录不是实机证据。父代理本次已用隔离根复跑并确认项目日志未再变化。

### 9.5 已确认通过

- 默认配置仍是 loopback；没有 OAS 自动写回、自动鼠标注入或任意进程控制 API。
- 图片 payload、尺寸、像素数和 Pillow decompression bomb 防护已落地；静态路径逃逸测试通过。
- SQLite WAL、busy timeout、复合 frame 主键、批量版本条件和事务回滚已存在。
- 六种标注工具、自动编号、软删除/恢复、画布删除二次确认、缩放不改存储坐标、无选择禁止分析导出等主体截图路径已实现。
- OAS exporter 输出工具自身 `outputs`，包含原生 ROI 字符串、源报告哈希和转换警告；没有 apply 端点。
- 当前 OAS 环境 `numpy=1.24.3`、`opencv=4.7.0` 可正常导入，旧 NumPy 2.x ABI 冲突不是当前阻塞项。
- 审计期间 `22880` 无监听；本轮未启动、停止或连接真实设备。

### 9.6 建议修复批次（本轮未实施）

1. **坐标正确性门禁：** 修实时点坐标、圆形旋转、多边形推荐点、外接框、协方差、凹多边形关系和方向边界，并建立纯 JS/浏览器坐标测试。
2. **状态与设备安全：** 让 GET 纯读取，外部来源显式恢复且连接前核对身份；统一画布请求 guard、租约和 per-session 生命周期锁；补 HWND/PID/子窗口/DPI 身份门禁。
3. **单实例与远程安全：** 项目级单实例锁，隔离数据库/日志/令牌，强制 `allow_remote` 控制 host，并增加 Host/Origin/远程认证策略。
4. **数据迁移与持久化：** 为 4 个旧 session 建 legacy workspace，先备份再处理 16 个不可达标注和 12 张孤儿帧；迁移、文件和数据库写入增加可恢复事务/对账。
5. **性能与生命周期：** 同步 I/O 移出事件循环，对关系计算设复杂度预算；补 graceful shutdown、Nemu 挂起隔离、请求体/ADB 流和全局配额。
6. **产品范围：** 先决定连续实时采集、多画布并行 worker、跨画布导出是否纳入下一版本；未实现前改正 UI 名称和完成状态。
7. **发布与验收：** 独立 `.venv`、锁定依赖、修 package-data，增加 wheel 安装 smoke test；最后执行 `2301` 干扰窗口、DPI、鼠标、ADB/Nemu、10 分钟并行采集实机验收。
