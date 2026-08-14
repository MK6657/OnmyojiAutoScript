# Coordinate Calibrator 最终完整性修复记录

日期：2026-08-08  
项目：`D:\coordinate-calibrator`  
性质：代码实施与离线验证记录，不替代真实设备验收

## 结论

全貌审计后追加确认的代码缺口已修复，并补充关闭了帧引用写入与淘汰之间的 TOCTOU、pending arm 取消丢失、长事务锁序反转、失效回调/后帧越权写入和历史 accepted 样本缺少来源证明等并发与证据边界。修复和实机冒烟均使用隔离数据根；生产 SQLite 只读核对后由 0.2.0 服务平滑切换至 0.2.1，计数与哈希基线未变化。

当前没有仍可由离线代码证据复现的 P0/P1 缺陷。`2301` 前台鼠标/DPI、真实 ADB、双 MuMu 并行与 P95 坐标误差仍属于实机验收，不因离线测试通过而结案。

## 已修复

- Nemu 每画布可分别指定 OAS 配置名、serial 和 instance ID；配置路径、serial/instance 一致性与持久身份均校验。
- `[oas].enabled=false` 同时封锁 Nemu 的 source、restore、start 和 capture API/运行时路径。
- 标注只能引用同一画布中 `ready` 的持久帧；`mapping_revision` 与 `source_sha256` 由服务端从帧和 artifact 派生并校验，前端使用当前显示的锁定帧 ID。
- 鼠标点击先持久化当前 preview，再写入 `frame_id == before_frame_id`；第一张后续持久帧作为 `after_frame_id`，两张证据均可按 immutable frame ID 下载。
- 鼠标 observer 保存 arm 时的 lease ID/fencing token。租约过期或被替换时，回调停止写入并异步 disarm，不在 dispatch 线程中自我 join。
- pending arm 在 observer 启动前后均复核 generation；disarm、stop、close、shutdown 可原子取消启动中的 observer。停止与关闭在 `capture -> session -> mouse` 锁区间 detach，并在锁外等待 observer 退出。
- 旧 `lease_scope` 已成为逐写 `lease_guard` 的兼容别名，不再持有跨调用 SQLite 写事务。鼠标回调和 pending after-frame 使用原始 lease/fencing token 逐写校验，失效后只清理本进程状态，不回写新租约持有者的 session/sample。
- ClickSample 保存并校验来源帧 SHA-256；三个帧 ID 必须为非空字符串。缺少可信帧 ID、before-frame 一致性或 64 位 SHA 的历史 accepted 样本保留审计可见性，但不进入推荐统计。
- annotation/sample 引用写入与 frame deletion 在 SQLite 写事务内互相校验。当前持久帧、软删除可恢复标注来源帧、sample 的 frame/before/after 均不可被 `max_frames` 淘汰。
- OAS 候选要求所选标注共享一个可信来源帧，只输出用户选择的 `clickPoint`、`roiFront` 或 `roiBack`，不再同时猜测两个 ROI 语义。
- 浏览器工程导出、克隆标注和创建标注均使用 `persisted_frame`，不再把持续变化的 preview 当作锁定截图来源。

## 验证

- `D:\coordinate-calibrator\test.ps1 -Package`：103/103 Python unittest 通过。
- `tests/test_web_math.js`、`tests/test_web_state.js`：通过。
- Python `compileall`、`node --check`、PowerShell AST：通过。
- 最终 wheel 在全新 Python 3.11.15 venv 中安装成功，依赖独立安装。
- 最终 wheel 通过 `uv run --isolated --no-project --python 3.11` 独立安装；真实 HTTP 冒烟中 `/api/v1/health` 版本 `0.2.1`，根页面 200，`/web/app.js` 200，随后优雅退出且端口无残留监听。
- wheel 包含 5 个 Web 资源：`index.html`、`styles.css`、`app.js`、`coordinate_math.js`、`workspace_state.js`。
- 独立临时数据根的真实 Nemu 冒烟按显式身份 `oas1 / 127.0.0.1:16384 / instance 0` 连续持久化 3 帧；全部为 `1280x720 / RGB / orientation 0 / source=nemu_ipc`。测试结束后临时目录释放，Nemu helper 残留为 0。
- 正式服务已恢复到 `http://127.0.0.1:22880`，PID `30132`，health 为 `ok / 0.2.1`，启动日志无错误，生产数据计数未变化。

最终包：

`D:\coordinate-calibrator\work\package\final-20260808-165314\dist\coordinate_calibrator-0.2.1-py3-none-any.whl`

SHA-256：

`8BEFD8C3952787E9ADAF600EF093D98801419B4F801AF00823CCD557C58FFC5F`

## 数据与回滚

本轮生产数据只读核对结果：schema 4、integrity `ok`、2 workspaces、9 sessions、24 annotations、7 frames、7 artifacts、0 samples。历史标注中来源不明确的记录不会被静默猜测或自动改写。

迁移前备份：

`D:\coordinate-calibrator\work\backups\coordinate-calibrator-data-pre-schema4-20260808-122735.zip`

备份 SHA-256：

`40F4C4B9BCBD2E947D75687D755839D172EAA0B8E808E92193A814EA602F2288`

项目没有 Git 仓库。回滚必须先停止服务并保留当前数据，再根据备份与迁移报告恢复；不得覆盖 `D:\OSAyys` 用户工作树。

## 待实机验收

- MuMu `2301` 与干扰窗口并存时的明确窗口绑定。
- Windows DPI、窗口移动和缩放后的映射重建。
- 10 个有效鼠标样本、before/after 帧和坐标误差 P95 不超过 2 个画布像素。
- 真实 ADB 设备。
- 两个 MuMu 实例并行至少 10 分钟，跨设备串帧为 0。
