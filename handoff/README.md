# OAS 控制中心项目交接包

版本：1.0.0  
交接快照：2026-07-26  
项目根目录：`D:\OSAyys`

这是 OAS（OnmyojiAutoScript）独立控制中心的交接资料。控制中心为原 OAS Core 增加了一个更易用的中文前端，重点解决多账号、多窗口、任务独立配置、模板复用和关键日志查看问题。

## 先看这几份

1. [项目初衷与范围](./01-项目初衷与范围.md)
2. [系统架构与目录说明](./02-系统架构与目录说明.md)
3. [安装与启动](./03-安装与启动.md)
4. [日常使用流程](./04-日常使用流程.md)
5. [多账号多窗口说明](./05-多账号多窗口说明.md)
6. [前端二次开发指南](./06-前端二次开发指南.md)
7. [Bridge 接口与数据流](./07-Bridge接口与数据流.md)
8. [上游同步与升级策略](./08-上游同步与升级策略.md)
9. [测试报告](./09-测试报告.md)
10. [当前进度与后续计划](./10-当前进度与后续计划.md)
11. [故障排查](./11-故障排查.md)
12. [交接清单](./12-交接清单.md)

## 一句话架构

```text
OAS Core（原项目，默认 :22267）
        ↑ HTTP / WebSocket
Bridge（独立适配层，默认 :22367）
        ↑ REST / WebSocket
React + Vite 前端（开发 :5173；桌面版内置静态文件）
```

## 当前可交付物

- 前端源码：`D:\OSAyys\control-center\frontend`
- Bridge 源码：`D:\OSAyys\control-center\bridge`
- Electron 桌面壳：`D:\OSAyys\control-center\desktop`
- 可执行程序：`D:\OSAyys\control-center\desktop\release\OAS-Control-Center-0.1.0-portable.exe`
- 原 OAS 任务代码：`D:\OSAyys\tasks`
- 交接资料：`D:\OSAyys\handoff`

## 快速启动

开发模式需要先确保 OAS Core 已运行：

```powershell
Set-Location D:\OSAyys
.\control-center\launcher\start-all.ps1
```

然后打开 `http://127.0.0.1:5173`。如果使用桌面版，直接运行上面的 portable 程序即可；桌面版自带生产前端和打包后的 Bridge，但 OAS Core 仍由原项目单独运行。

## 重要边界

`control-center` 是独立开发区。默认不要修改 `module/`、`tasks/`、原 QML 界面或 Core 的配置模型。上游更新时，优先只调整 Bridge 的契约适配和前端翻译映射。

