# 13 UI-claude 前端与 Bridge 缺陷修复

日期：2026-07-26
范围：`control-center/desktop/release/UI-claude`（新增）、`control-center/bridge`（修改）
未改动：`module/`、`tasks/`、`script.py`、`server.py`、原 QML、`control-center/frontend`、`control-center/desktop`

---

## 一、交付了什么

1. **UI-claude**：控制中心前端的一次重写，作为与 `UI-grok` / `UI-hermes` 平行的对比版，
   放在 `control-center/desktop/release/UI-claude`，自带说明、启动脚本和端到端回归。
2. **Bridge 修复**：`control-center/bridge/app` 下五个文件的修改，均为向后兼容，
   原有接口的路径、参数和返回结构都没有变，只新增字段和新增接口。
   原文件已备份到 `control-center/bridge/app/_backup_20260726/`。
3. **Bridge 回归测试**：`control-center/bridge/tests/test_bridge.py`，16 个用例，
   不需要真实 Core 即可运行。

---

## 二、修掉的缺陷

### B1 账号列表把 Core 打爆（性能，影响最大）

**现象**：账号一多，界面每次刷新都要卡好几秒。

**原因**：`GET /api/v1/accounts` 会对**每个账号的每个任务**调用一次 Core 的 `/{config}/{task}/args`，
只为读出 `scheduler.enable` 一个布尔值。3 个账号 × 53 个任务 = 159 次请求，
而 Core 每次都要现场生成一份 pydantic JSON Schema，并且这 159 个请求是无节制并发发出去的。

**修法**：三级取数，从便宜到贵。

1. Core 的 WebSocket 本来就会推送 `schedule` 快照，`running + pending + waiting` 合起来正好是
   这个账号所有启用中的任务，还自带 `next_run`。有快照就直接用，**0 次 HTTP 请求**；
2. 没有快照时读本地缓存（`TaskStateCache`，默认 45 秒，可用 `OAS_TASK_CACHE_TTL` 调整）；
3. 两者都没有才做全量扫描，且 `OasCoreClient` 加了并发闸门（默认 8），不再一次性冲垮 Core。

任何写操作（启用/停用任务、保存 scheduler 字段、增删账号）都会立刻让对应账号的缓存失效，
所以不会出现「改了看不到」。

**效果**：首次加载仍需一次扫描，之后的刷新是 0 次 Core 请求；账号已连上 Core 时首次也是 0 次。
`tests/test_bridge.py` 里有三个用例专门盯着这个请求次数。

### B2 保存配置会把整张表单回写 Core

**现象**：改一个字段点保存，Core 侧收到几十次写入，其中包括调度器自己维护的 `next_run`，
等于每次保存都把这个任务的排期重置一次。

**修法**：前端做脏字段追踪，只提交改动过的字段；Bridge 侧配合做了两件事：

- `PATCH .../config` 里对「没带类型的字段」只读一次 schema。原实现是**每个**缺类型的字段读一次，
  保存一张大表单会把同一份几十 KB 的 schema 反复拉几十遍；
- 只有真的动了 `scheduler` 分组才让 Core 重算调度。

### B3 时间类字段格式容易写坏

**现象**：`date_time` / `time` / `time_delta` 少一位秒，Core 直接返回 400。

**修法**：值的规范化收敛到 `OasCoreClient.normalize_value` 一处，并补上了 `time_delta`
（`DD HH:MM:SS`）的处理；前端也在提交前就把值规范化好，两边规则一致。
前端还把 `time_delta` 从纯文本框换成了「天数 + 时分秒」两个控件。

### B4 CORS 白名单写死端口

**现象**：任何非 5173/4173 端口的本地前端（对比版、自定义端口）都会被浏览器拦掉。

**修法**：改为 `allow_origin_regex`，放行 `localhost` / `127.0.0.1` / `[::1]` 的任意端口。
Bridge 本来就只监听回环地址，这不扩大暴露面。

### B5 事件 WebSocket 断了不会重连

**现象**：Bridge 一重启，界面就停在旧状态，只能手动刷新页面。

**修法**：前端把事件通道改成全局单例 + 指数退避重连（最长 15 秒），
并且收到 `bridge.ready` 时会重新走一次 REST 拉状态——事件序号在 Bridge 重启后会归零，
只靠事件补状态一定会漏。旧版还有一个附带问题：每切换一次账号就重建一次连接，现在不会了。

### B6 空任务账号导致重连风暴

**现象**（这条是修 B1 时发现的）：如果一个账号一项任务都没启用，
Core 在 WebSocket 握手阶段调用 `config.get_next()` 会抛 `RequestHumanTakeover` 并立刻断开。
Bridge 原来的重连逻辑会以 1–5 秒的间隔无限重试，日志里刷满连接错误。

**修法**：识别「连上不到 3 秒且没收到任何消息」的秒断，连续 3 次后退避到 30 秒，
并把最后一次错误记录到 `runtime.last_error`，通过 `/schedule` 接口暴露出来。

### B7 日志全都是「信息」级

**现象**：Core 通过 WebSocket 广播的是纯文本日志行，Bridge 一律标成 `info`，
前端没法区分错误和普通输出。

**修法**：在 `runtime.py` 里解析 OAS 的日志格式（`… | ERROR | …`），
识别 TRACE/DEBUG/INFO/SUCCESS/WARNING/ERROR/CRITICAL 并映射到 info/warn/error，
同时把行首的时间戳提取出来当日志时间。前端据此做级别过滤和高亮。

顺带修了一个吞日志的问题：原来的 `_handle_message` 会先 `json.loads`，
如果某行日志恰好是合法 JSON（纯数字、被引号包住的字符串），就会被判成非 dict 然后**直接丢弃**。
现在非 dict 一律当日志处理。

### B8 重命名账号在数据库里留孤儿

**现象**：`PATCH /accounts/{id}` 改名后，Bridge 的 SQLite 里旧 `account_id` 那一行不会被删，
昵称、头像、设备显示名也不会迁移过去。

**修法**：新增 `repository.rename()`，把元数据和任务显示顺序一起迁移，并删掉旧行；
同时释放旧账号的运行时连接。

### B9 创建重名账号会静默失败

**现象**：Core 的 `config_copy` 遇到同名文件只在自己的日志里报错然后正常返回，
Bridge 因此认为创建成功，前端拿到的其实是别人的配置。

**修法**：创建前先查重返回 409，创建后再确认文件确实出现在 `config_list` 里。

### B10 启动/停止只有 WebSocket 一条路

**现象**：Core 在跑但 WebSocket 恰好断开时，点启动会直接失败。

**修法**：`send()` 先试 WebSocket，失败则退回 Core 的 REST 入口
（`GET /{config}/start`、`GET /{config}/stop`）。

### B11 任务分类没翻译全

**现象**：`Weekly Task`、`Activity Task` 直接以英文出现；
`Guild` 被翻成「公会任务」（OAS 里是「阴阳寮」），`Liver Emperor Exclusive` 被翻成「活动任务」（应为「肝帝专属」）。

**修法**：Bridge 的 `TASK_LABELS` 补齐到 53 项，`CATEGORY_LABELS` 补齐并订正。
测试里有一条用例会扫描目录，发现任何未翻译的分类或任务就失败。

### B12 同名字段被错误翻译

**现象**：OAS 里很多分组都有 `enable` 字段。前端的翻译表是按字段名全局匹配的，
于是「御魂切换 → enable」也被显示成「启用任务」，让人以为是任务总开关。

**修法**：`fieldLabel(field, group)` / `fieldDescription(field, group)` 增加分组参数，
非 `scheduler` 分组下的 `enable` 显示为「启用<分组名>」。

---

## 三、新增的 Bridge 接口

全部是新增，旧前端不受影响。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/v1/accounts/{id}/schedule` | Core 的调度快照（正在执行 / 待执行 / 等待时间到达） |
| GET/POST | `/api/v1/templates` | 配置模板列表 / 保存 |
| DELETE | `/api/v1/templates/{id}` | 删除模板 |
| GET/PUT | `/api/v1/accounts/{id}/task-order` | 任务显示顺序 |

`GET /api/v1/accounts` 的返回里多了一个 `next_run` 字段；`GET /api/v1/health` 多了 `version`。
`GET /api/v1/tasks/catalog` 和 `/accounts/{id}/tasks` 新增可选参数 `refresh=true`，用来强制跳过缓存。

模板和任务顺序原来只存在浏览器 localStorage 里（交接文档 10 里列为 P1 遗留项），
现在落到了 Bridge 的 SQLite，可以随数据库一起备份。前端在 Bridge 不支持这些接口时会自动退回
localStorage，键名与旧版一致，升级不会丢模板。

---

## 四、怎么验证

### Bridge

```powershell
Set-Location D:\OSAyys\control-center\bridge
..\..\.venv\Scripts\python.exe -m compileall -q .\app
..\..\.venv\Scripts\python.exe .\tests\test_bridge.py
```

测试用假 Core，不需要启动真实 Core，也不会碰任何配置文件。预期 16/16 通过。

### 前端

```powershell
Set-Location D:\OSAyys\control-center\desktop\release\UI-claude
.\start-ui-claude.ps1 -Mock
```

打开 `http://127.0.0.1:4175/`。mock bridge 的数据由真实 `config/oas1.json` 派生，
任务名、分组名、字段名与线上一致，但不连接 Core、不写配置、不绑定窗口、不启动任务。

端到端回归见 `UI-claude/README.md`。

### 接手者仍需在真实设备上验收

以下事项本次同样没有做，需要用测试账号和测试设备完成：

- 用真实模拟器跑一次完整的启动 / 停止 / 重启；
- 两个账号绑定两个不同窗口时的并行运行；
- 长时间运行下日志级别解析在真实日志格式上的表现。

---

## 五、回退方式

- **前端**：UI-claude 是独立目录，删掉即可，生产前端从未被改动。
  如果已经执行过 `promote-to-production.ps1 -Apply`，把
  `control-center/frontend/_backup_<时间戳>/` 里的文件拷回去。
- **Bridge**：把 `control-center/bridge/app/_backup_20260726/` 下的五个文件拷回
  `control-center/bridge/app/` 覆盖即可。回退后前端会自动降级：
  新增接口返回 404 时，模板和任务顺序退回 localStorage，调度卡片退回显示已启用任务列表。

---

## 六、整合状态（哪一层接上了，哪一层没有）

| 链路 | 状态 | 验证情况 |
|---|---|---|
| UI-claude → Bridge（开发模式） | 已接通 | 只对着 mock bridge 验证过，没连过真实 Bridge |
| UI-claude → Bridge（桌面模式） | 已接通 | 同上；Electron 用 `file://` 加载，页面 origin 是 `null`，前端会回落到 `http://127.0.0.1:22367` 直连，Bridge 的 CORS 白名单保留了 `null` |
| Bridge → OAS Core | 代码已改 | 用假 Core 跑了 16 个用例，没连过真实 Core |
| Electron 打包 → UI-claude | **本次补上** | `build.ps1` 增加了 `-Ui` 参数 |

### 开发模式怎么接的

`start-ui-claude.ps1` 设置 `OAS_BRIDGE_URL=http://127.0.0.1:22367`，
Vite 把 `/api` 和 WebSocket 一起代理到 Bridge（`vite.config.js` 里 `ws: true`）。
前端用页面自身的 origin 拼接请求，所以不需要额外配置跨域。

### 桌面模式怎么接的

Electron 从 `file://` 载入页面，`window.location.origin` 是 `"null"`，
直接用 origin 拼 URL 会得到 `null/api/v1` 这种打不通的地址。
`src/api.js` 的 `resolveBridgeOrigin()` 对此做了兜底：origin 不是 http(s) 时回落到
`http://127.0.0.1:22367`。Bridge 侧 `allow_origins=["null"]` 放行了这种请求。

### 桌面打包现在可以选前端

`build.ps1` 原本第 18 行写死构建 `control-center\frontend`，
也就是说不替换生产源码就打不出用 UI-claude 的桌面包。现在：

```powershell
Set-Location D:\OSAyys\control-center\desktop
.\build.ps1 -SkipNpmInstall                    # 默认，和以前完全一样，打生产前端
.\build.ps1 -SkipNpmInstall -Ui UI-claude      # 打一个用 UI-claude 的试用包
```

不带 `-Ui` 时的行为与改动前逐字一致（构建、拷贝、PyInstaller、electron-builder 四个关键步骤都没动）。
原 `build.ps1` 备份在 `control-center/bridge/app/_backup_20260726/build.ps1.orig`。

注意两种包会覆盖同一个 `desktop\ui\` 目录和同一个 portable 文件名，
想同时保留两个包，打完第一个先把 `release\OAS-Control-Center-0.1.0-portable.exe` 改名。

## 七、连通性自检

`control-center/check-wiring.ps1` 会按 Core → Bridge → 前端接口的顺序逐层探测，
全程只读，不启动任务、不改配置、不绑定窗口：

```powershell
Set-Location D:\OSAyys
.\control-center\check-wiring.ps1
```

它会检查：Core 的 `/test`、`/config_list`、`/script_menu`；Bridge 的 `/health`
（包括 Bridge 自己认为的 Core 地址与状态）、账号列表两次请求的耗时对比（用来确认缓存生效）、
任务目录的中文化；再以第一个账号为例走一遍前端真正会用到的只读接口；
最后握手一次事件 WebSocket，确认能收到 `bridge.ready`。

哪一层先失败，就先修哪一层。
