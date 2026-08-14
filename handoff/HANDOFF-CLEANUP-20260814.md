# OSAyys 交接清理与接手说明

日期：2026-08-14

本目录是 MK6657 二次开发的当前交接入口。清理前的完整工作树、未提交差异、Git refs、逐文件 SHA-256、运行数据、发布工件和完整实测证据均由项目所有者另行封存；开发仓库只保留源码、测试、模板、契约和当前有效记录。

## 接手范围

- OAS Core：`server.py`、`module`、`tasks`。
- 控制中心：`control-center/frontend`、`control-center/bridge`、`control-center/desktop`。
- 坐标工具：独立项目 `coordinate-calibrator`，版本 `0.3.8`、schema 6。
- 跨项目边界：`handoff/contracts/v1`。坐标工具只读 OAS 并导出候选，不自动写回 OAS 任务、资产、配置或日志。

## 已从开发仓库移出的内容

- Python 虚拟环境、Node `node_modules`、前端/桌面构建目录和缓存。
- 本机 `config/deploy.yaml`、`config/oas1.json` 和控制中心运行数据库。
- 项目内历史 `backups`、临时 `work/tmp`、Playwright 本机状态。
- 7 GiB 连续帧和完整运行日志。
- portable 与 Bridge 可执行文件；它们作为独立发布工件保存。

当前工作目录保留了精选证据：`output/evidence` 每批最多五张均匀抽样关键帧并保留全部状态/日志元数据；`log` 只保留当前交接文档实际引用的文件。二者属于可选交接附件，默认不进入 Git。

## 首次安装

```powershell
Set-Location <OSAyys根目录>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

python -m venv .\control-center\bridge\.venv
.\control-center\bridge\.venv\Scripts\python.exe -m pip install -r .\control-center\bridge\requirements.txt

Set-Location .\control-center\frontend
npm ci

Set-Location ..\desktop
npm ci
```

根依赖已包含统一测试入口所需的 Bridge HTTP 客户端；不要只安装旧版根依赖快照，否则 `bridge.tests.test_bridge` 会因缺少 `httpx` 无法导入。

复制模板生成本机配置，不要复用原所有者账号配置。控制中心运行数据库会在本机重新创建。

## 验证入口

```powershell
Set-Location <OSAyys根目录>
.\run-oas-tests.ps1
.\handoff\tools\test-markdown-links.ps1
.\control-center\check-wiring.ps1
```

前端和桌面构建方法见 `control-center/README.md`。当前开放事项、真实设备边界和验收顺序见 `handoff/Codex-待做事项总表.md`。

本次清理后的离线验证结果：OSA 统一回归 `89` 个模块、`510` 项测试通过；Markdown 本地链接检查通过；前端 Vite 构建通过；Bridge 单文件打包与 Windows portable 桌面包构建通过。真实设备、真实账号和长时间运行仍属于接手后的环境验收范围。

## 回滚与证据

所有者侧原始封存位置为 `D:\Project-Handoff-Archive\20260814-handoff-cleanup`。该目录不是源码仓库的一部分，不应推送到公共远程。任何需要恢复的旧日志、连续帧、运行配置或数据，应先核对该目录中的 SHA-256 清单。
