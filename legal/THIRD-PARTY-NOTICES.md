# 第三方来源与通知清单

状态日期：2026-08-03

本文件记录仓库中已经发现的外部代码来源。它是发行前审计基线，不表示清单已经穷尽，也不表示某一上游团体的授权可以替代独立第三方权利人的许可证。

## 已确认并随仓库保存许可证

| 项目 | 本地范围 | 原始许可 | 本地归档 |
|---|---|---|---|
| OnmyojiAutoScript 历史公开版本 | 仓库历史基础 | GPLv3 | `licenses/GPL-3.0-upstream.txt` |
| FluentUI | `fluentui/` | MIT，Copyright (c) 2023 zhuzichu | `licenses/FluentUI-MIT.txt` |
| python-atomicwrites | `module/config/atomicwrites.py` | MIT，Copyright (c) 2015-2016 Markus Unterwaditzer | `licenses/python-atomicwrites-MIT.txt` |
| cached-property | `deploy/utils.py`、`module/device/platform2/utils.py` 中的相关实现 | BSD 3-Clause，Copyright (c) 2015 Daniel Greenfeld | `licenses/cached-property-BSD-3-Clause.txt` |
| Bottle | 上述 `cached_property` 注释指向的原始提交 | MIT，Copyright (c) 2009-2025 Marcel Hellkamp | `licenses/Bottle-MIT.txt` |

## 已确认的复制或派生来源

| 来源 | 仓库内证据或主要文件 | 当前审计结论 |
|---|---|---|
| `LmeSzinc/AzurLaneAutoScript` | `deploy/*.py`、`module/server/config.py`、`module/server/setting.py`、`server.py` 等文件含 copy/from 注释；README 明确说明 OAS 基于该项目开发 | 上游仓库为 GPLv3。正式切换为自有闭源许可证前，需识别仍在使用的派生文件，并选择保留 GPL 边界、取得独立许可或重写替换 |
| `LmeSzinc/StarRailCopilot` | `module/ocr/base_ocr.py`、`module/device/env.py` 含复制来源注释 | 上游仓库为 GPLv3。处理原则同上，不能仅凭 OAS 作者团体授权覆盖该独立来源 |
| `untitaker/python-atomicwrites` | `module/config/atomicwrites.py` 顶部明确标注 copy-pasted，版本字段为 1.4.1 | 原项目为 MIT，许可证原文已归档；发行时携带该通知 |
| `pydanny/cached-property` | `deploy/utils.py`、`module/device/platform2/utils.py` 的 `cached_property` 注释 | 原项目为 BSD 3-Clause，许可证原文已归档；发行时携带该通知 |
| `bottlepy/bottle` | 上述 `cached_property` 注释同时指向 Bottle 提交 | Bottle 为 MIT，许可证原文已归档；仍需在文件级审计中确认当前表达实际来自 cached-property、Bottle 或两者 |
| `dssg/dickens` | `module/server/setting.py` 的 `cached_class_property` 注释 | 已确认来源，尚未在本地找到可靠许可证文本；发布前核实或重写该小段实现 |
| `2833844911/gurs` | `module/base/cBezier.py` 顶部明确标注 copy from | 已确认来源，许可证状态待核实；发布前取得许可记录或重写替换 |

## 运行组件与待继续核实项

以下名称或实现引用已在设备层、依赖文件或文档中出现，发行审计时需要确认是外部依赖、内置二进制、复制源码还是仅有协议兼容：

- OpenSTF / minitouch
- DroidCast
- scrcpy
- nemu IPC 相关接口或二进制
- PaddleOCR / ppocr-onnx 及模型文件
- npm、Python 和桌面打包依赖及其传递许可证
- 图片、字体、OCR 模型、ADB 工具和其他随安装包分发的资源

## 发布处理规则

1. 根项目许可证只控制本项目有权许可的内容，不覆盖独立第三方组件的原许可证。
2. MIT、BSD 等许可的代码即使允许闭源分发，通常仍需在发行物中保留版权和许可通知。
3. 对第三方 GPL 派生内容，在自有闭源发行前完成文件级边界确认、独立授权或替换；不能只通过混淆或打包规避来源义务。
4. 发布流水线最终应从锁文件和本清单生成版本化的 `THIRD-PARTY-NOTICES`，并在 CI 中阻止未知许可证组件进入正式包。
5. 新增第三方源码或二进制时，在同一提交更新本文件和 `licenses/`，不得等到发版时补记。
