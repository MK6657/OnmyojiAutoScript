# UI-claude · OAS 控制中心前端（对比版）

路径：`D:\OSAyys\control-center\desktop\release\UI-claude`

这是控制中心前端的一次重写，和 `control-center\frontend`、`UI-grok`、`UI-hermes` 平行存在，**不会改动生产前端**。
它使用同一套 Bridge 契约（`/api/v1`），可以直接连真实 Bridge，也可以连内置的 mock bridge 离线试用。

## 快速开始

```powershell
Set-Location D:\OSAyys\control-center\desktop\release\UI-claude

# 离线试用：不需要 OAS Core，不会写任何真实配置
.\start-ui-claude.ps1 -Mock

# 连真实环境：需要先启动 Core 和 Bridge
.\start-ui-claude.ps1
```

然后打开 `http://127.0.0.1:4175/`。原预览在 `4173`、UI-grok 在 `4174`，三者可以并排对比。

首次运行会优先把 `control-center\frontend\node_modules` 做成目录联接来复用依赖，没有才执行 `npm install`。

## 相对旧版改了什么

### 一、界面结构

旧版是四栏平铺（全部任务 / 当前任务 / 任务设置 / 关键日志），四块内容互相挤压，日志和配置都只能看到很小一片。
新版改成 **左侧账号栏 + 四个视图**：

| 视图 | 解决什么问题 |
|---|---|
| 概览 | 启动前检查、Core 调度快照、最近日志。回答「现在能不能启动、下一个跑什么」 |
| 任务 | 任务目录与配置表单各占一半，都能完整展开 |
| 日志 | 整屏日志，可按级别过滤、搜索、导出 |
| 设置 | 主题、密度、连接状态、模板管理、账号重命名/删除 |

### 二、明确「点名称 = 看配置，开关 = 启用」

旧版用一个 `＋` / `✓` 按钮表示启用状态，很容易被当成「添加」。
新版右侧是标准开关控件（`role="switch"`），状态一眼可见，并且在面板标题下直接写了这句话。

### 三、启动前检查

概览页会检查四件事，任何一项不通过就禁用启动按钮，并给出可直接跳转的修复入口：

- OAS Core 是否连接；
- 这个账号是否绑定了设备或窗口；
- 是否至少启用了一项任务（一项都没有时 Core 启动后会立刻报「没有可执行任务」）；
- 实时事件通道是否正常。

### 四、只保存改动过的字段

旧版点保存会把当前任务的**所有**字段回写给 Core，包括调度器自己维护的 `next_run`，等于每次保存都重置一次排期。
新版做了脏字段追踪：

- 改过的字段有黄色底色和「未保存」标记；
- 面板标题显示「N 项未保存」，`Ctrl+S` 保存；
- 保存只提交改动的字段；
- 切换任务 / 账号 / 视图、关闭页面前，有未保存内容会先确认。

### 五、时间类字段有真正的编辑器

`success_interval` 这类 `DD HH:MM:SS` 的值旧版是纯文本框，手输容易写出 Core 解析不了的格式。
新版拆成「天数 + 时分秒」两个控件，并在提交前统一规范化成 Core 要求的格式。

### 六、断线自动恢复

旧版每切换一次账号就重建一次事件 WebSocket，而且断开后不会重连，Bridge 一重启界面就静止了。
新版是全局单例 + 指数退避重连，Bridge 重启后会自动重连并重新拉一次 REST 状态。

### 七、深浅色主题与显示密度

顶部「设置」里可切换深色 / 浅色 / 跟随系统，以及舒适 / 紧凑密度，选择会记住。
所有颜色都走 CSS 变量，没有写死的色值；字号只用 12/13/14/16/20 五档，没有 8–9px 的小字。

## 目录

```text
UI-claude/
├─ src/
│  ├─ App.jsx          应用外壳与全部状态
│  ├─ api.js           Bridge 客户端（REST + 自动重连的事件流）
│  ├─ store.js         主题、密度、本地降级存储
│  ├─ views.jsx        概览 / 任务 / 日志 / 设置
│  ├─ fields.jsx       各类型配置字段的编辑器
│  ├─ components.jsx   状态点、对话框、提示条等通用件
│  ├─ locale.js        中文映射（沿用生产前端的映射表并做了上下文修正）
│  └─ styles.css       全部样式，深浅色都靠变量切换
├─ tools/
│  ├─ mock-bridge.mjs  离线 mock bridge，数据由真实 config 派生
│  └─ e2e.mjs          Playwright 端到端回归（21 个用例）
├─ start-ui-claude.ps1      启动脚本
└─ promote-to-production.ps1  确认满意后，一键替换生产前端（带备份）
```

## 端到端回归

`tools/e2e.mjs` 对着 mock bridge 跑真实交互：账号切换、任务启用/停用、
「点名称不改变启用状态」、脏字段与保存请求体、保存失败提示、日志过滤、
主题切换、账号增删、1280×760 与 1180×680 下的溢出检查等，共 21 个用例。

```powershell
# 需要 Playwright（首次）
npm install -D playwright
npx playwright install chromium

# 三个终端分别跑：mock bridge、前端、回归
node tools\mock-bridge.mjs --port 22368
.\start-ui-claude.ps1 -Mock
node tools\e2e.mjs
```

脚本里的 `BASE` 默认指向 `http://127.0.0.1:4180/`，改成你实际的前端端口即可。

## 满意之后怎么替换生产前端

```powershell
.\promote-to-production.ps1            # 先看会动哪些文件
.\promote-to-production.ps1 -Apply     # 真正替换，原文件自动备份到 frontend\_backup_<时间戳>
Set-Location D:\OSAyys\control-center\desktop
.\build.ps1 -SkipNpmInstall
```

替换只涉及 `frontend\src` 和 `frontend\index.html`，不动 `package.json`（没有引入任何新依赖），
也不动 bridge / desktop / module / tasks。

## 边界

- 只通过 Bridge 的 `/api/v1` 访问数据，不读写 `config/*.json`，不 import OAS 的 Python 包；
- 模板和任务显示顺序优先存到 Bridge 数据库，Bridge 不支持时自动退回浏览器本地存储，键名与旧版一致；
- mock bridge 只用于开发，不连接 Core、不写配置、不绑定窗口、不启动任务。
