# DeepSeek-05 coordinate-calibrator（坐标标注操作台）全面审查报告

> **修订注记（2026-08-07，见 DeepSeek-06）**：本报告 C2"运行版本与代码树漂移"推论经复核**不成立**（reason 由 `str(exc)` 动态生成，真实根因是 OAS `.venv` cv2/numpy ABI 环境问题）；S1"DecompressionBombError 未捕获→500"**部分高估**（Pillow 仅 >179M 像素抛 Error，32M-179M 区间实为 409）。其余评测项修复前大体属实；对应修复见 Codex-坐标校准工具审查修复记录-20260807.md，落地验证见 DeepSeek-06。

日期：2026-08-07
审查对象：`D:\coordinate-calibrator`（坐标标注操作台，为 OAS 阴阳师自动化二开服务的辅助工具，后期计划改为通用型长期维护）
审查方式：3 个只读子代理并行（后端 / 前端 / 文档协议）+ 父代理关键点复核与结构验证
状态：只读审查，未修改任何文件、未启动服务
配套文档：OSAyys/handoff/Codex-坐标标注操作台实施记录-20260807.md、第二阶段功能实施与审核记录-20260807.md、审计与后台帧源修复-20260807.md、decisions/ADR-001-coordinate-calibrator-boundary.md

---

## 〇、项目概览

- 技术栈：Python FastAPI 后端（src/coordinate_calibrator/，25 文件 ~2549 行）+ 原生 JS 前端（web/app.js 1654 行 + index.html 207 行 + styles.css）+ SQLite（data/index.sqlite3）+ 会话帧 PNG（data/sessions/）
- 分层：domain（geometry/models/statistics/transforms）→ ports（frame_source/mouse_observer/window_provider）→ adapters（capture: adb/nemu_ipc/screen；oas: exporter/readonly；windows: mouse/provider）→ api（app/runtime/schemas）→ storage（artifacts/repository）
- 配置：config.example.toml / config.local.toml；启动 start.ps1 / stop.ps1
- 端口：22880（127.0.0.1）
- 当前数据：sessions 9 行、annotations 24、workspace_canvases 5、frames 1（另 12 个孤儿 PNG）

## 一、总体结论

**工程质量高，无 P0/P1 级问题**。架构分层干净（domain 零外部依赖、依赖方向正确、ports 稳定、adapters 全部向内依赖）、API 鉴权与路径穿越防护到位、SQL 全参数化、事务语义正确、前端-后端 29 个 API 调用点全部匹配、测试 29/29 与 test-plan 静态清点精确吻合、实施记录数字可复核。

主要问题集中在三类：**配置系统名存实亡**（config.example.toml 基本未被加载）、**文档超前于实现**（WS 事件流/错误码/OAS 候选 SHA-256 三处高不一致）、**少数边界健壮性**（解压炸弹、Nemu 无超时、孤儿文件、EPSILON 截断失效）。

## 二、安全专项（后端）

### 通过项（实测确认）
- ✅ 无 CORS 中间件（浏览器默认阻断跨源读取，本地控制台安全模式）
- ✅ SQL 全部参数化（repository.py 无一处字符串拼接）
- ✅ token 用 `hmac.compare_digest` 恒时比较 + cookie `httponly, samesite=strict`（CSRF 免疫）
- ✅ `download_export`（app.py:408-415）`Path(artifact_name).name` 校验 + resolve 后 `OUTPUT_ROOT not in parents` 双重防穿越
- ✅ `ArtifactStore.session_dir`（artifacts.py:14-20）拦截 `/`、`\`、`..`
- ✅ 无 eval/exec/shell=True/os.system；日志无敏感信息（token 不落盘）
- ✅ OasReadOnlyAdapter 防穿越顺序正确（先 resolve 再 relative_to）

### 发现项
| # | 位置 | 级别 | 问题 | 建议 |
|---|---|---|---|---|
| S1 | runtime.py:534-541 | **P2** | **解压炸弹**：`Image.open()` 后立即 `image.load()` 完成解码，尺寸/像素校验（539-541）在解码之后。20MB PNG 可膨胀至 ~178M 像素，解码内存峰值数百 MB；超过阈值的 `DecompressionBombError` 不在捕获清单 `(UnidentifiedImageError, OSError, ValueError)` 内 → 未处理 500 | 读头部先查 size/像素数再 load()；显式捕获 DecompressionBombError |
| S2 | config.example.toml:21-23 | **P2** | **无效安全开关**：`[security] require_token / allow_remote` 全代码库 0 引用。鉴权实际恒开（app.py:49 随机 token）、host 恒为 127.0.0.1（app.py:445 + start.ps1:40 双重硬编码）。用户按文档改配置无任何效果 | 删除无效项或让代码真正读取；至少文档标注"仅示意" |
| S3 | app.py:420 | P3 | WebSocket 接受 `?token=` query 参数（token 进浏览器历史/代理/WS 日志） | 仅用 Header/Cookie 鉴权 |
| S4 | readonly.py:30-35 | P3 | `OasReadOnlyAdapter.read_text`：绝对路径/`..` 使 `relative_to` 抛 ValueError 未捕获 → 500；且该适配器是**死代码**（全库无引用） | 捕获转 400/404，或删除死代码 |
| S5 | app.py:98-105 | P3 | `/` 与 `/web/*` 无鉴权（token bootstrap 需要，可接受）；cookie 无 secure（本地 HTTP 可接受） | 维持现状，注明设计意图 |

## 三、分层架构

### 通过项
- ✅ domain 仅依赖 stdlib + 内部模块；ports 只依赖 domain；adapters 无一处 import api/
- ✅ api 层向外依赖合规；domain 无 sqlite/PIL/win32 痕迹

### 发现项
| # | 位置 | 级别 | 问题 | 建议 |
|---|---|---|---|---|
| A1 | config.example.toml 全文件 | **P2** | **配置系统名存实亡**：除 `[oas].root/.config_name`（仅 nemu_ipc 读取）外，`[server]/[storage]/[windows]/[security]` 全部 0 引用。`max_frames/max_samples/max_annotations`（config:7-9）未实现任何清理逻辑 | 实现配置加载（tomllib+校验），或删掉死配置 |
| A2 | runtime.py:20-25, 109-113 | P3 | 组合根职责模糊：SessionManager 直接 new 具体适配器；FrameSource Protocol 只含 capture，open/close/health 靠 hasattr 鸭子判断 | 生命周期方法纳入 Protocol |
| A3 | ports/__init__.py:1-4 | P3 | 未导出 MouseObserver/MouseEvent（与另外两个 port 不一致） | 补导出 |

## 四、截图适配器（adb / nemu_ipc / screen）

### 通过项
- ✅ adb CRLF 处理正确（保留二进制通道，靠解码器校验）；无连接泄漏（每次 capture 独立子进程，close 幂等）
- ✅ Nemu flip_vertical=True 与 OAS 约定一致；`_serial_to_instance_id` 端口数学（16384+idx*32）与 MuMu 实际吻合
- ✅ folder 推导 `emulatorinfo_path.parent.parent` 与 OAS 自身 nemu_ipc.py 完全一致
- ✅ capture 有 source/identity 双重校验（runtime.py:454-462）防串源

### 发现项
| # | 位置 | 级别 | 问题 | 建议 |
|---|---|---|---|---|
| C1 | nemu_ipc.py:132-148 | **P2** | **IPC 调用链无超时**：`executor.submit().result()` 在初始化/截图/close 均无 timeout。MuMu IPC 挂起 → capture 线程永久占用；close 挂起 → close_session 永久阻塞 | result(timeout=...) + 失败 shutdown |
| C2 | runtime.py:162-173, 216-235 | **P2** | `get()` 持 RLock 时执行 `_restore_external_source` → Nemu 连接在锁内无超时：挂起则**全局锁死，所有 API 不可用**。且日志实测 7 次 `capture_source_restore_failed reason=adapter unavailable`（该字符串不在当前源码 → **运行版本与代码树漂移**） | 恢复逻辑移出锁外/加超时；核对部署版本 |
| C3 | nemu_ipc.py:128-131 | P3 | `sys.path.insert(0, oas_root)` 全局副作用（多 OAS 根冲突） | importlib 按路径加载 |
| C4 | screen.py:25 | P3 | `ImageGrab.grab(all_screens=True)` 虚拟屏坐标 vs GetWindowRect 物理坐标在多显示器/DPI 场景可能错位 | 实机多屏验证 |

## 五、存储（sqlite / 制品）

### 通过项
- ✅ 事务语义正确（_connection contextmanager commit/rollback/close 三态完备）
- ✅ 条件更新 `UPDATE ... AND version=?` 原子防版本竞争；update_annotations_atomic 多行单事务
- ✅ 进程内 RLock 串行化；删除会话级联清理 5 张表

### 发现项
| # | 位置 | 级别 | 问题 | 建议 |
|---|---|---|---|---|
| ST1 | repository.py:23-26 | **P2** | 无 journal_mode=WAL、无 busy_timeout、每操作新建连接：双实例/多进程共享 data 目录 → `database is locked` | PRAGMA（WAL + busy_timeout=5000）或单实例互斥锁 |
| ST2 | runtime.py:463, 514-524 / artifacts.py | **P2** | **无界增长 + 孤儿文件**：max_frames 等配置未实现清理；close_session 只删 DB 行不删 PNG。实测 frames 表 1 行而 data/sessions/ 有 13 个 PNG → **12 个孤儿** | 帧数上限裁剪；close_session 删会话目录 |
| ST3 | runtime.py:117-119 + repository.py:95-100 | P3 | sessions.payload 冗余内嵌全部 annotations/samples，每次点击全量重写 O(N) JSON + 写库 | 分表或增量更新 |

## 六、OAS 适配（exporter / readonly）

| # | 位置 | 级别 | 问题 | 建议 |
|---|---|---|---|---|
| O1 | exporter.py:16-21, 32-38 | P3 | **导出形态与 OAS 资产约定不一致**：实测 OAS `res/image.json`/`click.json` 中 ROI 为 `"x,y,w,h"` 逗号分隔字符串（如 `"roiFront": "55,662,21,21"`），点击点为 `[x,y]` 列表；而 exporter 输出 dict 形态 `point:{x,y}`/`roi:{x,y,width,height}`。名为 oas_candidate 但落不了 OAS 资产，需人工二次转换（warnings 已诚实声明 "candidate only"） | 增加 OAS 原生形态输出（`"x,y,w,h"` 字符串 + `[x,y]`）或提供显式转换函数；roiFront/roiBack 语义需用户确认 |
| O2 | readonly.py:30-35 | P3 | 见 S4（死代码 + 未捕获异常） | 接入 API 或删除 |
| O3 | exporter.py:36 | P3 | 导出文件名未消毒（当前 annotation_id 服务端生成，低风险） | 统一走 ArtifactStore |
| — | — | — | **OAS 候选缺 SHA-256 与转换损失字段**（见 C 路问题 3）：oas-adapter.md + ADR-001 承诺的"源截图/报告 SHA-256、转换损失"未实现 | 补字段或修订文档 |

## 七、启动脚本（start.ps1 / stop.ps1）

### 通过项
- ✅ 路径用 `$MyInvocation.MyCommand.Path` 派生（无 cwd 依赖）；UTF-8 无 BOM 纯 ASCII 无编码坑
- ✅ 端口占用前置检查防双实例；stop.ps1 校验命令行含 coordinate_calibrator 才杀进程（防误杀）
- ✅ `-Install` extras 语法合法

### 发现项
| # | 位置 | 级别 | 问题 | 建议 |
|---|---|---|---|---|
| PS1 | start.ps1:41 | P3 | `-WindowStyle Hidden` 启动：uvicorn 崩溃信息完全不可见（端口探测只报"未监听"不带原因） | 重定向 stdout/stderr 到 logs/uvicorn.log，失败打印尾部 |
| PS2 | start.ps1:10,45 / stop.ps1:4 | P3 | Get-NetTCPConnection 对排除端口范围不可见 | 接受现状或 Test-PortBindable 实绑探测 |
| PS3 | start.ps1:30-33 | P3 | 只查依赖 import 不查 Python 版本（pyproject 要求 ≥3.11,<3.13） | 加版本检查 |
| PS4 | start.ps1 / app.py:49 | P3 | CALIBRATOR_TOKEN 未设置时随机生成且**不打印**，纯 CLI 用户拿不到 token（只能靠浏览器 cookie） | 加 -ShowToken 开关或写 data/token.txt（0600） |

## 八、前端审查（app.js 1654 行 / index.html 207 行 / styles.css）

### API 调用 ↔ 后端路由核对（29 个调用点，全部匹配 ✅）
- 覆盖：health/workspaces/canvases/sessions 全生命周期/lease/bind/capture 三源/import 帧/annotations CRUD+batch/click-capture 全套/reports/exports
- 关键一致性：selection_hash 算法**逐字节一致**（前端 `sha256(JSON.stringify(sorted unique ids))` == 后端 `sha256(json.dumps(sorted(set(ids)), separators=(",",":")))`）；无 crypto 时安全降级（后端 `if body.selection_hash` 跳过校验）
- 乐观锁（version 必填）、lease header、错误解包（body.detail.message/code）全部对齐

### 前端未使用的后端能力（不影响正确性）
`/capabilities`、POST /sessions、GET workspaces/{id}/canvases、GET annotations、batch-restore、reports/geometry、GET exports/{id}/{name}、WebSocket /events

### 发现项
| # | 位置 | 级别 | 问题 | 建议 |
|---|---|---|---|---|
| B1 | api() 46-58 | 中 | FastAPI 422 校验错误时 detail 是数组，body.detail.message 取不到 → 用户只见"HTTP 422"（导入超限图片时触发） | 前端导入前预检大小；api() 对数组型 detail 提取首项 |
| B2 | imageToCanvasPoint 395-396 | 中（**真 bug**） | **EPSILON 截断失效**：`canvas.width - Number.EPSILON` 在双精度下等于 canvas.width（1280 的 ULP ≫ 2.2e-16），clamp 形同虚设。图片最右/最下 1px 内点标注 → x==canvas.width → 后端 `_inside_canvas` 严格 < 拒绝 → 409"point is outside canvas"；circle/ellipse 中心同理 | 改用 canvas.width - 1e-9（或 nextafter） |
| B3 | importScreenshotBlob 751-854 | 低 | 导入前无大小/维度预检（后端限制 20MB/8192px/32M 像素），失败信息依赖 B1 | 读文件后先校验再转 dataURL |
| B4 | heartbeatSessionLease 116-124 | 中 | 心跳失败即 lease_id=null 且不再自动重试（后续心跳直接 return），写操作全部 423，需手动切换画布恢复 | 失败后延迟重试或重新 acquire；心跳错误不走 showError 刷横幅 |
| B5 | refreshCanvasList 235-256 | 低 | 刷新用 GET 返回的 session 覆盖 state.session，依赖调用处手工恢复 lease_id；lease 恰在刷新窗口过期则写操作 423 | 刷新后统一重新 acquire |
| C1 | moveScreenshotAnnotation/renderOverlay | 中 | pointermove 无节流，每次移动全量清空重绘所有标注；>100 标注拖拽明显卡顿 | rAF 节流 + 画布分层（静态层+交互层）或脏矩形 |
| C2 | refreshSamples 1235-1259 | 低 | 1s 轮询 + 全量重建 DOM；切换画布期间旧响应到达会渲染到新画布（错位） | 响应校验 sessionId() 是否仍当前 |
| A1 | exportReport 1275-1287 | 中（**功能完整性**） | 「导出 JSON / OAS 候选」仅把响应 JSON 回显到 reportOutput，后端返回的 artifact_id 未使用，GET /exports/{session_id}/{artifact_name} 下载路由从不调用——**用户拿不到实际文件** | 响应后构造下载链接（<a download> 或调用下载路由），至少提示 artifact_id 与保存路径 |
| A2 | openDeleteConfirm 1425 | 中 | 确认文案承诺"可通过恢复接口撤销"，但前端无恢复入口（后端 batch-restore 路由闲置） | 补「恢复标注」按钮或删除文案 |
| A3 | boot 1542-1553 | 低 | 未调用 /capabilities，截图来源下拉、导出格式硬编码 | 启动时拉取 capabilities 动态渲染 |
| A4 | captureStart 1135 | 低 | imported_image 模式下「开始采集」未禁用，点击后报后端 409 原始英文 | 按 mapping.source 禁用采集按钮 |
| A5 | index.html | 低 | 无标注重命名 UI（后端 PATCH 支持 label）、无帧历史浏览 | 可选增强 |

### 安全（前端）
- ✅ escapeHtml 用于动态文本；无 innerHTML 注入用户数据痕迹
- ✅ 帧图走 <img> + cookie 鉴权；?ts= 防缓存

## 九、文档/协议/测试计划一致性

### 一致性核对表（19 项，16 ✅ / 3 ❌）

**✅ 一致**：服务地址/端口（22880）、认证模型（cookie+header）、租约（X-Calibration-Lease 覆盖全部写端点）、selection_hash、下载路由防穿越、Frame/Annotation 数据模型（实现为文档超集）、报告统计字段（median/mean/std/MAD/P05/P95/covariance/outlier/推荐点/ROI/confidence/warnings/status 全部实现）、OAS 不暴露 HWND（_opaque_id SHA-256）、帧源身份校验、生命周期状态机（created→bound→capturing→armed→(disarm)→closed + rebind_required）、workspace bundle（形状/30M 限制逐字段吻合）、后台帧源约束（Nemu 单线程、禁鼠标采集、身份不含绝对路径）、六工具/标签。

**❌ 不一致（3 高）**：
1. **WS 事件流协议虚标**：protocol.md 声称 6 种事件（session_state/frame_published/mapping_changed/click_sample_captured/target_lost/session_error），实现只有 session_state 轮询推送，前端未接入 WS。→ 实现事件或修订文档为"仅 session_state 状态快照"
2. **错误码契约与实现脱节**：protocol.md 的 8 个 "stable application codes" 中 5 个在 API 层不存在（coordinate_out_of_bounds/invalid_mapping/target_not_foreground/target_lost/insufficient_data 仅存在于 domain 异常/样本 flags/报告状态，不作 API 错误码返回）。→ 文档区分"domain 概念码"与"API 错误码"，或补映射
3. **OAS 候选缺 SHA-256 与转换损失**：oas-adapter.md + ADR-001 均承诺候选含源截图/报告 SHA-256 与转换损失，exporter 未实现（输出仅 semantic/point/roi/confidence/warnings/source_report）。→ 补字段或修订 ADR

**⚠️ 其他**：protocol.md REST 表漏列 7 条实际路由；配额声明未落地（security.md 声称限制帧/样本/标注数，config 有配额配置，代码无配额逻辑——审计记录已诚实承认"配额尚未真正执行"）；`[oas].window_title` 死配置；test-plan 把浏览器手工验收写进"Unit tests"清单（措辞不实，但 phase2 日志如实记录为手工验证）。

### 测试计划评估
- **数量可验证**：test-plan 声称 29/29，静态清点 test_api_contract(1)+test_capture_sources(3)+test_domain(8)+test_runtime_safety(14)+test_storage_and_export(3)=29 ✅ 精确吻合
- **覆盖核心**：transform/映射修订/形状校验/统计/序号不重用/软删恢复/批量原子/租约冲突/workspace 隔离/ADB+Nemu 身份与尺寸/路径穿越/OAS 只读边界 ✅
- **差距**：DPI/rotation 无直接测试；MAD/P05/P95/outliers 显式断言未覆盖；lease expired 场景无直接测试；前端 UI 无自动化测试（手工）
- **可执行验收**："Still required before release" 三项（真实 MuMu 2301 绑定+干扰窗口、ADB/Nemu 实机矩阵、连续采集+配额清理）与实施记录开放项、00-当前状态.md 完全一致 ✅

### 实施记录可信度（高，证据可复核）
- 数据库数字实测吻合（9 session 行 vs 12 目录；迁移基线演进自洽；schema_version=2）
- 服务状态实测吻合（22880 运行中、health version 0.1.0、auth_required=true）
- 测试数量演进链合理（11→18→27→29→29 单调递增）
- 前端修复痕迹可验证（sessionStorage tab ID、lease 恢复、画笔去重、selection_hash）
- 未结案项（配额、GC、跨进程租约、椭圆方向转换、批量版本强制）与代码现状一致，无虚标 ✅

## 十、修复优先级建议

### 第一批（安全与稳定性，P2）
1. **S1 解压炸弹**：解码前校验尺寸/像素数 + 捕获 DecompressionBombError
2. **C1/C2 Nemu 超时**：IPC 调用链 result(timeout) + 恢复逻辑移出锁外；**同时核对部署版本与代码树漂移**（7 次 restore_failed 的 reason 字符串不在源码）
3. **ST1 WAL + busy_timeout**（一行 PRAGMA）
4. **ST2 清理策略**：close_session 删会话目录 + 帧数上限裁剪（清现有 12 个孤儿 PNG）
5. **S2/A1 配置系统**：实现 config 加载或删除死配置（require_token/allow_remote/max_* 三处一致性）

### 第二批（功能完整性，前端）
6. **B2 EPSILON 修复**（一行：1e-9）
7. **A1 导出下载入口**（构造 <a download> 链接）
8. **B4 心跳重试**（失败后延迟重试/重新 acquire）
9. **C1 pointermove 节流**（rAF + 分层画布）

### 第三批（文档诚实性）
10. protocol.md：WS 事件流改"仅 session_state"、错误码表区分 domain/API 两层、REST 表补 7 条路由
11. oas-adapter.md/ADR-001：OAS 候选补 SHA-256 与转换损失，或修订承诺
12. security.md 配额标注"规划中"；test-plan 把 UI 手工验收移出 Unit tests 清单

### 第四批（P3 批量）
13. S3 WS query token、S4 死代码、C3 sys.path、C4 多屏验证、PS1-4 脚本增强、A2/A3 架构小项、ST3 payload 分表、O1 OAS 原生格式输出、O3 文件名消毒

## 十一、与 OSAyys 的衔接

1. **OAS 导出格式**：exporter 需输出 OAS 原生形态（`"x,y,w,h"` 逗号字符串 ROI + `[x,y]` 点击点，参照 OAS tasks/*/res/image.json|click.json 实际约定）才能真正落地 OAS 资产
2. **OAS 侧 00-当前状态.md**：工作树 225 项（80 M + 29 D + 116 ??）记录属实；handoff 新增坐标标注操作台 3 份实施记录 + decisions/ADR-001 + 待做事项总表
3. **ADR-001 符合度**：边界决策（只读 OAS、Nemu 单线程、禁鼠标采集、身份不含绝对路径）与实现一致；但"候选含 SHA-256/转换损失"承诺未兑现（见问题 3）

## 附：审查纪律

- 全部结论为静态审查（源码/配置/日志/数据库实测），未运行服务、未修改任何文件
- 子代理原文归档：`C:\Users\ggy\AppData\Local\hermes\cache\delegation\subagent-summary-{0,1,2}-20260807_180452_*.txt`
- 审查过程中 search_files 对 D: 盘路径报 IO 错误，已改用 Python stdlib 扫描/terminal grep 绕过
