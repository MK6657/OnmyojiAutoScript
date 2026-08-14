# DeepSeek-09-coordinate-calibrator-v0.3.8只读审查-20260813

> 审查执行：Hermes（DeepSeek）父代理 + 4 个只读子代理并行，父代理独立复现验证后汇总落盘。
> 审查对象：`D:\coordinate-calibrator` v0.3.8（pyproject.toml 声明版本）。无 git 仓库，审查对象为完整工作树。
> 审查约束：**全程只读**。未修改任何文件、未安装依赖、未运行 start/stop/test 脚本、未运行迁移/维护命令、未操作游戏客户端。SQLite 一律只读模式（`mode=ro`）打开。
> 行号以当前工作树为准；置信度分级：**已证实 / 高概率 / 待实机**。

## Errata（2026-08-13 晚，DeepSeek-11/12/13 轮）

> 正文保留原判，不再作为当前事实引用。权威入口：handoff/audits/DeepSeek-11-根因定位审查-20260813.md §2、DeepSeek-11-复验结论-20260813.md、DeepSeek-13 修复轮实施记录（handoff/records/implementation/Codex-实施-DeepSeek13-*.md）。

- **F16（租约乒乓）**：机制由「同 session 多客户端互踢」修正为「多标签页 + 30s TTL 与后台节流(≥60s)心跳失配 + 前端失败即重抢无退避」三因耦合（DS-11 R-6）；「无 UI 提示」修正为「提示分支存在但乒乓中 acquire 恒 200，现象上无提示」。DB 实证：leases 17 行全过期、fencing_token 达 2025。**DS-13 已修**：repository 同 owner 活租约原样返回、heartbeat TTL 60、前端 ttl 60/指数退避/CONTROL_LEASE_MS 60。
- **F1 附注（「repairs 路径无测试」）**：修正为「孤儿文件 repairs 有测试，damaged-ready repairs 路径无测试」（DS-11 R-5）。**DS-13 已修**：mark_artifact_damaged 改标合法态 delete_pending（repository.py:3060）+ reconcile 单工件补偿（runtime.py:1959-1982）+ damaged-ready repairs 路径新测试。

---

## 0. 审查方法与实况基线

**方法**：
1. 父代理侦察：文件清单（49 py / 18,629 行；5 js / 4,952 行）、文档链（README → docs/audit-20260809.md 开放发现清单 → 0.3.7/0.3.8 两个工作日志）、上一轮审查参考。
2. 4 个只读子代理并行：A=API/服务器/设置层；B=storage/domain/ports/adapters；C=前端+API 契约核对；D=docs/config/launchers/tests 清点。
3. 父代理独立验证 21 项子代理声称（file:line 复现 + 内存复现 + 日志统计），全部成立，零虚报。
4. 父代理亲跑测试套件：`env -u PYTHONPATH .venv/Scripts/python.exe -B -m pytest tests/ -q` → **146/146 通过（31.60s）**。

**实况基线（2026-08-13 晚实测）**：
- 服务运行中（PID 25064，08-12 16:47 启动）：`GET /api/v1/health` → version=0.3.8，auth_required=true，automatic_click=false，allow_remote=false，绑定 127.0.0.1:22880。
- 数据库：schema=6，`PRAGMA integrity_check`=ok；17 sessions / 81 annotations / 16 backgrounds / 17 frames / 17 artifacts / 394 idempotency_operations / 17 leases / 6 quarantine_items / **0 samples**。
- 测试全部使用 tempfile 隔离，无 data/ 写入风险。

---

## 1. 历史声明核对总表

来源：docs/audit-20260809.md（0.3.3 时代发现清单）与 work/logs/2026-08-10-v0.3.7、2026-08-11-v0.3.8 两份工作日志的"已修复"声称。判定：**已实施 / 部分 / 未 / 现状成立但实现点不明**。

| # | 声明（来源） | 判定 | 证据（当前工作树） |
|---|---|---|---|
| 1 | CC-SEC-002 CLI 绑定与配置不一致启动前失败（0.3.7） | ✅ 已实施 | server.py:16-24 `resolve_bind_host`/`resolve_bind_port` 与配置 casefold 比对，不一致抛 ValueError（父代理亲读+探针实测） |
| 2 | CC-MIGRATE-001 普通启动绝不迁移（0.3.7） | ✅ 已实施 | app.py:163 `allow_schema_migration=False`；maintenance.py:162 仅 migrate 命令传 True |
| 3 | 幂等指纹含租约身份（audit P2，0.3.7 声称） | ✅ 已实施 | app.py:396-414 fingerprint=sha256(method:path:canonical(body+lease{session_id,lease_id,fencing_token}))；TTL 24h 持久化 |
| 4 | CC-BUNDLE-001 8192 边界 + group 数量上限 | ✅ 已实施 | bundles.py:30/275-276 尺寸校验；bundles.py:33/387-443 MAX_GROUPS_PER_WORKSPACE=200 |
| 5 | bundle 全量语义配额预校验 + 导出锁/快照（0.3.7） | ✅ 已实施 | bundles.py:447-449 先 `_prevalidate_import` 后 business write；bundles.py:175-248 锁序+单一快照+3 次重试 |
| 6 | CC-INTEGRITY-001 reconcile 校验 ready 文件存在/大小/SHA-256 | ✅ 已实施 | runtime.py:1916-1958（missing/truncated/replaced 三态） |
| 7 | CC-CORRECT-001 显示帧与换算帧一致（0.3.4） | ✅ 已实施 | workspace_state.js:55-87 displayedFrameContext 强制校验；app.js:1943-1950 换算只读锁定帧；后端 `_trusted_frame_record_unlocked` 双验（runtime.py:1784-1829） |
| 8 | CC-CORRECT-002 背景隐藏标注不可交互（0.3.4） | ⚠️ 部分 | hit test/选中维护/删除/导出均已过滤；**undoAnnotation 一条路径遗漏**（见 F12） |
| 9 | CC-ASYNC-001 事件刷新过期状态守卫（0.3.5） | ✅ 已实施 | app.js:1094-1152 socket 身份+workspaceId 双守卫；激活路径 serial 递增 |
| 10 | CC-EXPORT-SELECT-001 跨画布选择不被裁剪（0.3.5） | ✅ 已实施 | workspace_state.js:151-163 仅对含 annotations 数组的活动条目裁剪 |
| 11 | CC-LEASE-001 恢复归档画布重获租约（0.3.5） | ✅ 已实施 | app.js:1411-1428 restore 后 acquireLeaseFor+心跳+applyControlState |
| 12 | 0.3.7 鼠标原生时间戳/注入拒绝/before<click<after | ✅ 已实施 | mouse.py:47-50,154-160,205-215；models.py:209-227 证据校验；runtime.py:3237-3270 有序预览环选帧 |
| 13 | 0.3.7 DPI fail-closed（未知/非 Per-Monitor 禁用屏幕鼠标采样） | ✅ 已实施 | provider.py:38-82 真实查询 GetProcessDpiAwareness；arm 时强制 per_monitor 否则拒绝（runtime.py:2967-2973） |
| 14 | 0.3.8 netstat 字节解析修复 | ✅ 已实施 | common.py:144-158 无 text=True、读 `stdout or b""` 字节、只解析 ASCII 列（父代理亲读） |
| 15 | 0.3.8 generic 模拟器不再自动继承唯一 ADB serial | ⚠️ 现状成立，实现点不明 | 全 src grep "generic"/"serial_source"/"verified_adb_mapping" 均 0 命中；AdbFrameSource 强制显式 serial 无自动继承路径（adb.py:26-51）——属性成立，但"需品牌 PID/实例/端口证据"的判断逻辑不在本仓（工作日志该验证证据术语属 OSAyys Bridge 侧），建议在 OSAyys 侧补注实现位置 |
| 16 | P2 bundle import 阻塞事件循环 | ❌ 未（工作日志未声称修复） | app.py:1468-1502 无 to_thread（父代理亲读） |
| 17 | P2 session close 吞文件清理失败仍返回成功 | ❌ 未（未声称） | runtime.py:2284-2288 只 warning 不 raise（父代理亲读） |
| 18 | P2 token 创建依赖继承 ACL | ❌ 未（未声称） | app.py:109-125 write_text+os.replace，全库无 icacls/SetFileSecurity |
| 19 | P2 quarantine 无界 | ❌ 未（未声称） | runtime.py:541-593；artifacts.py:245-284 无任何配额/过期/GC |
| 20 | P2 部分 Session 序列化/报告无锁遍历字典 | ❌ 未（未声称） | runtime.py:151-152 as_dict 无锁迭代；app.py:879 GET 无锁 |
| 21 | P3 build_report 声称 Iterable 却双遍历 | ❌ 未（未声称） | statistics.py:187-188；调用点传 dict 视图侥幸正常，契约缺陷仍在 |
| 22 | P3 batch-visibility/restore 无 selection_hash | ❌ 未（audit 已记录） | schemas.py:114,190 vs app.py:1268-1276 |
| 23 | P3 失败 .ccproj 导入遗留空组 | ❌ 未（audit 已记录） | bundles.py:643-654 补偿只 close session+delete_workspace_if_empty，不删 create_group 建的分组 |
| 24 | P3 半开区间边缘显示 (1280,720) | ⚠️ 仍存在（显示层） | 后端 clamp 正确（transforms.py:25-27 nextafter）；前端 app.js:1972-1975 `Math.round` 可越界显示 |
| 25 | README 146 Python 测试 | ✅ 已证实 | 父代理亲跑 146/146 通过 |
| 26 | 配置键全激活（0.3.3 时代 max_* 死配置） | ✅ 已实施 | config.example.toml 22 键全部有强制点，0 死配置 |

**结论**：0.3.4–0.3.8 声明的修复基本真实落地（P1 全关）；audit-20260809.md 的 P2/P3 中仍有 8 项未关，其中 7 项工作日志从未声称修复（文档诚实），不构成虚假声明。

---

## 2. 新发现问题清单

### 🔴 阻断级（1 条）

**F1 · `mark_artifact_damaged` 写入非法 state，maintenance quarantine 必然抛 IntegrityError 并留下文件/DB 分裂**
- 位置：repository.py:569（表 CHECK）+ repository.py:3057-3064（写方）+ runtime.py:1970-1984（调用链）+ maintenance.py:178（命令入口）
- 现象：`artifacts` 表 CHECK 仅允许 `('staging','ready','delete_pending')`，而 `mark_artifact_damaged` 执行 `UPDATE artifacts SET state='damaged' ...`。
- 证据：父代理内存复现确认——`sqlite3.IntegrityError: CHECK constraint failed: state IN ('staging','ready','delete_pending')`（100% 必现，纯静态+内存即可证实，无需实机）。
- 影响链：`maintenance quarantine` 命令 → `reconcile_artifacts(apply_repairs=True, quarantine=True)` → 对受损工件**先** `quarantine_file`（文件已移入 quarantine，不可回滚）**后** `mark_artifact_damaged`（抛 IntegrityError，无捕获）→ reconcile 在首个受损工件即中断；文件已移走但 DB 行仍 `ready` 指向不存在路径；后续所有受损工件不再处理。
- 对照：`permanently_delete_canvases`（runtime.py:575-593）有正确的 `restore_quarantine` 回滚补偿模板，reconcile 缺同样的补偿。
- 测试盲区：tests/test_full_remediation.py 只覆盖 `apply_repairs=False` 的报告路径，repairs 路径无测试，故 146/146 全绿未捕获。
- 建议方向（供实施方）：① 给 CHECK 增加 'damaged' 枚举并同步 `_validate_schema` 的 required_sql_fragments，或改标 `delete_pending`/直接删行；② reconcile 对单工件异常 try/except 后继续处理后续项；③ 补 repairs 路径测试。

### 🟡 注意级（19 条）

| # | 问题 | 证据 | 置信度 |
|---|---|---|---|
| F2 | bundle import 同步阻塞事件循环：ZIP 解压（≤512MB）+哈希+图像校验+逐画布 DB/FS 写全部在 async 路由事件循环线程同步执行，期间 health/WS 全等待 | app.py:1468-1502（1493-1497 无 to_thread）；bundles.py:447 纯同步 | 已证实（代码事实；时长未实机压测） |
| F3 | quarantine 目录无配额/无过期/无 GC：`quota` 只统计 DB artifacts 表 staging/ready 行，quarantine 文件不计数 | runtime.py:541-593；artifacts.py:245-284；repository.py:2880-2896 | 已证实 |
| F4 | session close 先删 DB 所有权、文件清理失败吞错仍返回 200：留下孤儿文件（缓解：启动时 reconcile 会标记） | runtime.py:2278-2294；app.py:898-901 | 已证实 |
| F5 | 幂等 DB 层 owner 维度失效：begin 查询 `WHERE route=? AND idempotency_key=?`（无 owner）vs 表约束 `UNIQUE(route,owner,idempotency_key)`，且指纹不含 owner → 跨 owner 同 key 同 body 可回放他人已提交响应 | repository.py:373-376 vs 675 | 已证实（需知晓对方 Idempotency-Key，风险低但为契约缺口） |
| F6 | lease/acquire 幂等重放可返回死租约：acquire 无 lease_session_id → 指纹不含租约；TTL 内同 key 重试直接回缓存 envelope（含旧 lease_id），不重新校验有效性；客户端首个操作 423 自愈 | app.py:840-844；idempotency.py:133-139 | 已证实 |
| F7 | 幂等崩溃残留阻塞窗口：in_progress+有 resource_ids+recover 失败（如资源已删）→ 该 key 阻塞至 24h TTL 才可复用 | idempotency.py:140-153；repository.py:399-412 | 已证实 |
| F8 | 幂等内存注册表容量 1024，超限直接 409 拒合法请求 | idempotency.py:93-94 | 已证实 |
| F9 | Session 序列化/报表无锁遍历 dict：`as_dict()`（annotations/samples/backgrounds.values()）与 GET /sessions/{id}、report 路径均不持锁，与 capture/mouse 写线程并发时可能 "dictionary changed size during iteration" → 500 | runtime.py:123-161,151-152；app.py:879；runtime.py:3316-3323 | 已证实（触发概率低） |
| F10 | 标注配额计软删行：`len(session.annotations) >= max_annotations` 计 total（软删条目保留在 dict），历史删除累积可耗尽配额，与文档 "200 active" 措辞不符 | runtime.py:2675；软删见 runtime.py:2823 | 已证实 |
| F11 | bundle 画布只限单边 8192 无像素积上限（8192×8192≈67M 像素）；comparison `_canonical_rgb` resize 到画布尺寸，ImageChops 复数副本峰值内存数百 MB；对照：单帧截图有 MAX_FRAME_PIXELS=32M 上限 | bundles.py:275-276；comparison.py:24-30；common.py:30 | 已证实 |
| F12 | undoAnnotation 未套背景过滤：`activeAnnotations()` 只过滤 deleted_at（app.js:370），切到背景 B 后仍可"撤销"软删 A-only 标注（可恢复，故为部分实施） | app.js:370,2751-2768 | 已证实 |
| F13 | 前端 v1 JSON 工程导入无大小上限：`JSON.parse(await file.text())` 前无检查（.ccworkspace 分支有 128MB 检查，此分支没有）；dataUrlToBlob 的 atob 大 base64 解码先于 validateScreenshotBlob 校验 → 内存 DoS 风险 | app.js:2680-2701 | 已证实 |
| F14 | addPoint 死代码绕过帧锁定：读 `state.session.latest_frame` 换算（无 persisted/SHA-256/mapping_revision 校验）；当前不可达（全文件仅定义处 1 次引用，无事件绑定），未来重新绑定即重开 CC-CORRECT-001 | app.js:3123-3150 | 已证实 |
| F15 | blink 定时器/比较状态跨画布残留：`clearScreenshotFrame` 不调 `stopCompareBlink`，切画布后 500ms setInterval 继续跑、compareEnabled/BaseId/TargetId 保留 | app.js:681-706；stopCompareBlink 仅在 1766/1783 被调 | 已证实（低影响，作用在无 src 的 img 上） |
| F16 | 实机租约乒乓高频：08-12 日志 337 次、08-10 达 880 次、08-11 864 次 heartbeat 423，模式=heartbeat 423→acquire 200 循环（同 session 多客户端互踢）；前端被抢占无 UI 提示（heartbeat 失败静默置空 lease 下次再抢）；leases 表 17 行全过期不清理 | 日志统计（uvicorn-20260812-164720.stdout.log 等）；leases 表实查 | 已证实（行为高频有日志背书；"无 UI 提示"为代码事实：app.js:549-565 无提示分支） |
| F17 | capabilities `mouse_capture` 恒等于静态 `windows_available`，不反映 DPI fail-closed 实际状态（arm 时才拒绝）——前端可能在用户操作前显示可用 | app.py:572 | 已证实 |
| F18 | token 文件创建无 ACL 加固（多用户主机上其他本地用户可读 .auth-token；未声称修复的遗留项） | app.py:109-125；全库无 icacls/win32security/SetFileSecurity | 已证实（实际暴露面依赖部署环境） |
| F19 | 部分 OSError/sqlite3.Error 逃逸为非结构化 500：operation() 映射覆盖 WindowsAdapterUnavailable/KeyError/RepositoryConflict/FrameCaptureError/(RuntimeError,ValueError)，但无 OSError；三处 `read_bytes()` 缺文件路径直接 FileNotFoundError→500（import_background_from_canvas / background_thumbnail / compare_backgrounds） | app.py:476-491（父代理亲读）；runtime.py:2548-2550, 2622-2624, 2650-2652（父代理亲读） | 已证实 |

### 🟢 文档漂移（5 条，不影响功能，低成本修复）

1. protocol.md:22-30 错误信封示例含 `fields`/`request_id`，实际只发 `detail:{code,message}`；404/405 等 Starlette 默认响应为纯文本。
2. protocol.md:139-141 稳定错误码表列出 `lease_required`——**全库 0 发射**（缺租约实际走 RepositoryConflict→`lease_conflict` 423）。
3. 代码新发的 5 个错误码未列入文档：`invalid_owner`/`cross_workspace_selection`/`invalid_content_length`/`bundle_too_large`/`invalid_bundle`（文档措辞为 "include" 非穷举，低危）。
4. protocol.md 称 workspace_heartbeat "approximately 15-second"，实际空轮询 1.0s 即发 → 实际 ~1s（app.py:1599；15.0s 是会话 WS 的状态轮询）。
5. architecture.md:77 称 "start.ps1 validates schema, data-root ownership"——实际由服务进程完成（旧 schema 拒启+instance lock），start.ps1 本身不校验这两项，措辞与实现分层有出入。

---

## 3. 通过项（🟢 已证实）

**测试与验证**：父代理亲跑 146/146 通过（31.6s）；README/test-plan 声称精确吻合；JS 断言 51 处；测试全 tempfile 隔离。

**安全基线**：
- 无硬编码密钥（grep password/secret/api_key 仅 `import secrets`）；token 用 `secrets.token_urlsafe(32)`。
- 认证比较全部 `hmac.compare_digest` 恒定时间（app.py:465,523,1117,1534,1578）。
- SQL 全参数化：唯一 f-string 为 sqlite_master 来源的表名（已 `""` 转义）与 IN 占位符列表；LIKE 搜索做 `\ % _` 转义。
- 无 eval/exec/os.system/shell=True/pickle。
- CORS/Host/Origin 与 loopback 一致：无 CORSMiddleware（loopback 正确姿势）、origin_guard 403 信封、WS 双侧 Origin 校验、TrustedHost 中间件；远程模式强制 token+hosts/origins。
- 路径安全：ArtifactStore 组件白名单正则+`..` 拒绝+逐级 reparse（symlink/junction）检查贯穿 safe_path/delete_session/quarantine；bundle 防 zip 遍历/盘符/符号链接。
- 解压/图像炸弹防护：bundle 128MB/1000 文件/512MB 解压/2000 压缩比；导入图 20MB/8192px/32M 像素；Pillow DecompressionBomb 显式捕获。
- 租约 fencing 双点校验（BEGIN IMMEDIATE 与 commit 前各校验 lease+fencing+过期）；fencing_token 单调递增。
- 迁移安全：迁移锁+备份+sha256 先于迁移+结构/外键/索引校验。
- 原子写 fsync+os.replace 全链路；跨进程实例锁（msvcrt.locking 非阻塞）；请求体 32MB 上限中间件。
- 前端帧下载三处 SHA-256 复核后才显示/导出；显示帧与 mapping_revision 强制一致，不一致 fail-closed。

**契约一致性**：
- 前端 51/51 API 调用点与后端路由/字段完全匹配；selection_hash 前端 JS 与后端 Python **字节级一致**（独立推导验证，非自洽核对）；乐观锁 version/expected_versions 全覆盖；幂等 key 复用正确。
- 坐标数学 0/90/180/270 四向互逆一致（独立推导验证）；JS 半开钳制 `size − max(1e-9, EPSILON·size·2)` 有效（旧死钳制已修）。
- protocol.md 路由表 62/62 双向吻合。
- 配置 22 键全部有强制点，0 死配置；config.local.toml 无凭据（token/key/secret/password 0 命中）。
- 启动器：start/stop 单实例锁+服务身份文件+优雅关停链路完整；cleanup-generated.ps1 白名单不可能删到 data/logs/outputs。
- DB 实况 integrity=ok、schema 6、WAL 正常。

---

## 4. 待实机（开放边界，与文档一致，静态无法判定）

- 前景窗口 2301 + 干扰窗口下的客户端/游戏画布矩形验证。
- 100/125/150% DPI、跨显示器、负坐标、P95 映射误差 ≤2 画布像素。
- 真实鼠标采样：native 时间戳、注入事件实机拒绝、before<click<after 严格时序（**samples 表 0 行**——佐证仍未实机验证）。
- 真实 ADB serial 采集与身份漂移拒绝。
- 双 MuMu 同时运行 ≥10 分钟零串帧。
- 黑屏/同尺寸方向漂移/句柄复用/目标丢失/源重启行为。
- Nemu 原生调用超时后的源重绑定/服务重启流程（设计已含 _blocked 拒绝，实机行为未验）。

---

## 5. 子代理核验记录（父代理独立验证清单）

4 份子代理报告共约 45 项声称，父代理独立复现验证 **21 项，全部成立，零虚报**；行号与父代理亲读一致。抽查清单：

| 声称 | 验证方式 | 结论 |
|---|---|---|
| B-N1 mark_artifact_damaged CHECK 违规（🔴） | 父代理内存 sqlite 复现 | ✅ IntegrityError 100% 复现 |
| A-N1 bundle import 阻塞 | 父代理亲读 app.py:1467-1502 + bundles.py:447 | ✅ 无 to_thread |
| A-N2 幂等 DB 查询缺 owner 维度 | 亲读 repository.py:373-376 vs 675 | ✅ 成立 |
| A-N3 lease/acquire 重放死租约 | 亲读 app.py:840-844 | ✅ 无 lease_session_id |
| A-N4 无锁序列化读 | 亲读 runtime.py:123-162 + app.py:879 | ✅ 成立 |
| A-N10 capabilities mouse_capture 恒 True | 亲读 app.py:570-585 | ✅ 成立 |
| A-N11/N13 幂等容量 409/24h 阻塞 | 亲读 idempotency.py:92-95,140-153 | ✅ 成立 |
| A-N15 testserver+重复 origin | 亲读 settings.py:135-151 | ✅ 成立 |
| A-N6/N7 错误信封/错误码漂移 | 亲读 protocol.md:22-30 + lease_required 全库 grep=0 | ✅ 成立 |
| B-N4 配额计软删行 | 亲读 runtime.py:2675 | ✅ 成立 |
| B-N6 bundle 无像素积上限 | 亲读 bundles.py:275-276 + comparison.py:24-30 + common.py:30 | ✅ 成立 |
| B-N10 build_report 双遍历 | 亲读 statistics.py:187-188 | ✅ 成立 |
| B-5b generic 模拟器声明 | 全 src grep generic/serial_source/verified_adb_mapping=0 | ⚠️ 现状无自动继承路径（属性成立），实现点不在本仓 |
| C-1 undoAnnotation 背景过滤遗漏 | 亲读 app.js:365-372,2745-2772 | ✅ 成立 |
| C-2 addPoint 死代码 | 亲读 app.js:3123-3150 + 全文件引用计数=1 | ✅ 成立 |
| C-3 v1 导入无大小上限 | 亲读 app.js:2680-2701 | ✅ 成立 |
| C-4 blink 残留 | 亲读 app.js:681-706（无 stopCompareBlink 调用） | ✅ 成立 |
| C-10 toggleLibraryArchived 未入 MUTATING_CONTROL_IDS | 亲读 app.js:3 清单 | ✅ 成立 |
| D-2 心跳 1s | 亲读 app.py:1595-1602 | ✅ 成立 |
| D-19 失败导入遗留空组 | 亲读 bundles.py:640-654 | ✅ 成立 |
| F19 OSError 逃逸（部分实施） | 亲读 app.py:476-491 映射 + runtime.py:2548/2622/2650 三处 read_bytes | ✅ 升级为已证实 |

测试数：父代理亲跑 146/146，子代理 D 静态清点 146——两者独立吻合，README 声称可信。

---

## 6. 修复优先级建议（供实施方参考，本轮未改任何代码）

1. **F1（🔴）**：CHECK 枚举 + reconcile 回滚补偿 + repairs 路径测试 —— 唯一阻断级，`maintenance quarantine` 命令当前在受损工件场景必然失败。
2. **F12/F13/F14（前端小改）**：undo 改 `canvasEligibleAnnotations()`；v1 导入加 128MB 预检；删除 addPoint 死代码或改写为 displayedFrameContext 路径。
3. **F2/F4/F5/F6/F9/F19（旧 P2 遗留，收敛性）**：import 移 to_thread；close 失败上报；幂等查询补 owner、acquire 指纹入租约或重放前校验；as_dict 加锁或快照；operation() 补 OSError/sqlite3.Error 映射。
4. **F3/F10/F11/F7/F8/F16（配额/容量语义）**：quarantine 配额+GC；标注配额改计 active；bundle 像素积上限；幂等容量策略；租约表过期清理+前端被抢占提示。
5. **文档漂移 5 条**：低成本诚实性修复（错误信封示例、lease_required、5 个新错误码、心跳 15s→1s、start.ps1 措辞）。
6. **F17/F18**：capabilities 反映 DPI 实际状态；token 文件 ACL（多用户主机）。

---

## 附录：子代理完整报告

- annex-A-api层：`handoff/audits/DeepSeek-09-annex-A-api层子代理报告-20260813.txt`
- annex-B-存储域适配器：`handoff/audits/DeepSeek-09-annex-B-存储域适配器子代理报告-20260813.txt`
- annex-C-前端：`handoff/audits/DeepSeek-09-annex-C-前端子代理报告-20260813.txt`
- annex-D-文档配置启动器：`handoff/audits/DeepSeek-09-annex-D-文档配置启动器子代理报告-20260813.txt`

（子代理原文一字未改，含其自身的方法说明与无法判定项。）
