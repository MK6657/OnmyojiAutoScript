# 07 Bridge 接口与数据流

## REST 接口

Bridge 默认地址：`http://127.0.0.1:22367`

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/v1/health` | 检查 Bridge 和 Core |
| GET | `/api/v1/accounts` | 获取账号及运行摘要 |
| POST | `/api/v1/accounts` | 从 Core template 创建账号 |
| PATCH | `/api/v1/accounts/{account_id}` | 更新 UI 元数据或重命名 Core 配置 |
| DELETE | `/api/v1/accounts/{account_id}` | 停止运行时并删除 Core 账号 |
| GET | `/api/v1/tasks/catalog` | 获取全部任务目录 |
| GET | `/api/v1/accounts/{account_id}/tasks` | 获取当前账号已启用任务 |
| GET | `/api/v1/accounts/{account_id}/tasks/{task_id}/config` | 获取任务配置 Schema 和当前值 |
| PATCH | `/api/v1/accounts/{account_id}/tasks/{task_id}/config` | 批量保存任务字段 |
| PUT | `/api/v1/accounts/{account_id}/tasks/{task_id}/enabled?enabled=true` | 启用或停用任务 |
| POST | `/api/v1/accounts/{account_id}/actions` | `start`、`stop`、`restart`、`refresh` |
| GET | `/api/v1/accounts/{account_id}/logs?limit=100` | 获取最近日志 |

另有 WebSocket：`ws://127.0.0.1:22367/api/v1/events`。

## Core 调用映射

`bridge/app/core_client.py` 集中封装了以下 Core 端点：

| Bridge 需要 | Core 端点 |
|---|---|
| 健康检查 | `GET /test` |
| 账号列表 | `GET /config_list` |
| 新账号名 | `GET /config_new_name` |
| 复制模板 | `POST /config_copy?file=...&template=template` |
| 删除配置 | `DELETE /config?name=...` |
| 重命名配置 | `PUT /config?old_name=...&new_name=...` |
| 任务菜单 | `GET /script_menu` |
| 任务 Schema | `GET /{config}/{task}/args` |
| 保存字段 | `PUT /{config}/{task}/{group}/{name}/value` |
| 账号运行 WS | `WS /ws/{config}` |

## 事件契约

契约文件：`control-center/contracts/event.schema.json`。

事件必备字段：`version`、`seq`、`timestamp`、`type`、`level`、`payload`。账号和任务相关事件还会带 `accountId`、`taskId`。

常见事件：

- `bridge.ready`；
- `account.connected` / `account.disconnected`；
- `task.started` / `task.stopped` / `task.state`；
- `task.commanded`；
- `schedule.updated`；
- `log.appended`；
- `task.configured`。

事件序号只保证在当前 Bridge 进程内递增。前端断线重连后必须重新走 REST，不能只依赖事件补状态。

## 错误处理

- Core 无法连接：Bridge 返回 503；
- Core 返回业务错误：Bridge 返回 502；
- 请求参数或账号不存在：返回 4xx；
- 前端对 5xx 请求最多自动重试两次。

## Bridge 数据库

开发模式数据库：`D:\OSAyys\control-center\data\control_center.db`。桌面版数据库位于 Electron 的 `app.getPath('userData')\data\control_center.db`。

当前表：`account_metadata`，字段包括 `account_id`、`name`、`avatar`、`tags`、`device_label`、`sort_order`。这里不保存 OAS 任务参数。

