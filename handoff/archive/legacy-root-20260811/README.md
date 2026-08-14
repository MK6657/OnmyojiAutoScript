# 2026-08-11 根目录历史归档

本目录由 `handoff/tools/archive-root-history.ps1` 从旧的扁平根目录整理而来，共归档 103 个原始文件。移动前的完整 handoff 快照位于 `D:\OSAyys\backups\pre-handoff-organization-20260811-1035.zip`。

## 分类

| 类别 | 数量 | 识别方式 | 用途 |
|---|---:|---|---|
| 旧版指南与交接说明 | 22 | 旧编号指南和兼容说明 | 查找历史架构、启动方式和旧前端口径 |
| Codex 阶段记录 | 72 | `Codex-*` | 查找单次实施、实测和阶段结论 |
| 外部审查 | 7 | `DeepSeek-*` | 保留第三方审查原文，不直接作为当前事实 |
| 历史附件 | 2 | PNG、ZIP 等非 Markdown 文件 | 对照旧截图和交接包 |

`MANIFEST.csv` 保存这 103 个原始文件移动前的文件名、大小和 SHA-256。当前事实以 [交接入口](../../README.md)、[当前状态](../../00-当前状态.md) 和 [待做事项总表](../../Codex-待做事项总表.md) 为准。

## 查找

```powershell
Set-Location D:\OSAyys
rg -n "关键词" handoff\archive\legacy-root-20260811
```

归档内文件保持原文件名，旧文件之间的相对链接尽量保留；指向当前资料或分类目录的链接已在移动时重写。
