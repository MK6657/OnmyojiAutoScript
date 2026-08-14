# Coordinate Calibrator 全量修复与验证记录

> 本记录保留全貌审计主体实施过程。后续 6 项完整性缺口、事务/fencing 补修、94 项测试和最终 wheel 证据见 [最终完整性修复记录](Codex-coordinate-calibrator最终完整性修复-20260808.md)。

日期：2026-08-08  
项目：`D:\coordinate-calibrator`  
依据：`handoff/audits/Codex-coordinate-calibrator全貌只读审计-20260808.md`

## 结论

审计确认的坐标、状态、并发、安全、数据、发布和主体交互缺陷已实施修复。生产数据已迁移到 schema 4，并恢复为原始 9 个会话、24 个标注和 7 个有效帧；6 个历史孤儿文件保留在可逆隔离区。当前没有已知 P0/P1 代码缺陷。

不能随代码结案一并宣称通过的实机项仍有：`2301` 前台鼠标采样与 DPI/移动矩阵、真实 ADB、两设备并行 Nemu。它们在总表中保留为 `待实测/部分通过`。

## 核心修复

- 坐标和几何：四方向半开边界、旋转圆/椭圆、小数外接框、凹多边形关系、区域内推荐点、协方差和复杂度预算。
- 状态和并发：所有异步写操作绑定画布 context；租约持久化到 SQLite 并带 fencing；工程导入恢复画布规格和 provenance；预览帧与锁定帧分离。
- 设备和性能：GET 纯读取、显式恢复外部来源、ADB/Nemu/窗口身份门禁、Per-Monitor DPI、每画布连续 worker、事件循环 I/O 边界和可终止 Nemu helper。
- 安全和发布：项目级单实例、Host/Origin/远程 token、请求和资源配额、独立 Python 3.11 `.venv`、wheel Web 资源、维护 CLI 和优雅停服。
- 数据：schema 4 外键、事务迁移、备份、对账、可恢复隔离和 legacy workspace。
- 操作台：六种标注、移动、多选、筛选、软删恢复、画布删除确认、缩放、工程往返、跨画布导出和静态资源 no-store。

## 本轮实机证据

- Nemu 身份：serial `127.0.0.1:16384`、instance `0`、config `oas1`。
- 连续时间：本地 13:16:16 至 13:53:00，共 36 分 44 秒。
- 序列：`frame_sequence=6757`；观察帧均为 `1280x720 / RGB / orientation=0`，身份未漂移。
- 保存帧：`frame_000136` 可按 immutable frame ID 和 SHA-256 重新加载。
- 清理：临时 session `sess_5fbcbbd770a147d0a74e` 已通过二次确认删除，目录不存在。
- 停服：修复 WebSocket 断开检测后，在浏览器连接存在时 0.885 秒优雅退出，无 Nemu helper 残留。
- 数据对账：schema 4、integrity `ok`、sessions 9、annotations 24、frames/artifacts 7、orphans 0、pending 0。

## 新发现与补修

1. 连续预览时，前端曾用 preview SHA 校验 persisted image。现会话同时返回 `latest_frame` 与 `persisted_frame`，锁定画布只访问 `/frames/{frame_id}/image`。
2. `lease_scope` 曾与 heartbeat 争用 SQLite 并产生一次 `database is locked / 500`。现租约事务与仓库写入共用 `RLock`，回归覆盖并发等待。
3. WebSocket 只发送不读取，空闲连接曾阻塞优雅停服。现循环读取 disconnect，真实停服通过。
4. 浏览器曾混载新 `app.js` 与旧 `workspace_state.js`。根页面和 `/web/*` 现统一 `Cache-Control: no-store`，并使用同一资源版本。

## 验证

- `D:\coordinate-calibrator\test.ps1 -Package`：85/85 Python unittest 通过。
- `tests/test_web_math.js`、`tests/test_web_state.js`：通过。
- Python `compileall`、前端语法和 PowerShell AST：通过。
- wheel 构建：通过，包含完整 Web 资源。
- 既有干净 Python 3.11 安装/启动/访问/停止 smoke：通过；最终代码在交付前再次执行。

## 备份与回滚

- 生产迁移前备份：`D:\coordinate-calibrator\work\backups\coordinate-calibrator-data-pre-schema4-20260808-122735.zip`
- SHA-256：`40F4C4B9BCBD2E947D75687D755839D172EAA0B8E808E92193A814EA602F2288`
- 本项目没有 Git 仓库。回滚必须先停服，保留当前数据，再按备份和迁移报告恢复；不得覆盖 `D:\OSAyys` 的用户工作树。
