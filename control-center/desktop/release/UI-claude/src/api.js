/**
 * Bridge 客户端。
 *
 * 所有网络访问都集中在这里，界面层不直接 fetch。
 * 设计要点：
 * - 只依赖 Bridge 的 /api/v1 契约，不读 OAS 的 JSON，也不认识 OAS 的内部类名；
 * - 新增接口（schedule / templates / task-order）在 Bridge 缺失时自动降级，
 *   这样这套前端对旧版本 Bridge 依然可用；
 * - 事件 WebSocket 自带指数退避重连，断线不需要用户刷新页面。
 */

const DEFAULT_BRIDGE = 'http://127.0.0.1:22367'

/**
 * Bridge 地址的解析顺序：
 *   1. 构建时注入的 VITE_BRIDGE_URL；
 *   2. 当前页面 origin（Vite 开发服务器会把 /api 代理到 Bridge）；
 *   3. 默认的 127.0.0.1:22367。
 * 第三条是给 Electron 用的：桌面版从 file:// 载入页面，origin 是 "null"，
 * 只靠前两条会拼出 null/api/v1 这种打不通的地址。
 */
function resolveBridgeOrigin() {
  const injected = import.meta.env?.VITE_BRIDGE_URL
  if (injected) return String(injected)
  const origin = window.location?.origin || ''
  return /^https?:/i.test(origin) ? origin : DEFAULT_BRIDGE
}

export const BRIDGE_ORIGIN = resolveBridgeOrigin().replace(/\/+$/, '')
export const API_BASE = `${BRIDGE_ORIGIN}/api/v1`
const WS_BASE = API_BASE.replace(/^http/, 'ws')

/** 已知会被旧版 Bridge 404 的接口，记下来后不再重复请求。 */
const missingEndpoints = new Set()

export class BridgeError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.name = 'BridgeError'
    this.status = status
    this.detail = detail
  }
}

function describe(status, body) {
  const detail = body?.detail || body?.message || (typeof body === 'string' ? body.slice(0, 300) : '')
  if (status === 503) return detail || 'OAS Core 未启动，请先启动原项目服务'
  if (status === 502) return detail || 'OAS Core 返回了错误，请查看 Core 日志'
  if (status === 404) return detail || '接口或对象不存在'
  if (status === 0) return '无法连接 Bridge，请确认 Bridge 已启动'
  return detail || `请求失败（HTTP ${status}）`
}

export async function request(path, options = {}, attempt = 0) {
  // 只有幂等方法(GET/PUT/DELETE)才允许自动重试；POST 不重试：否则服务端已处理、连接却中断时
  // 会把「创建账号 / 发指令」重发一遍，导致重复创建或“账号已存在”误报（见 handoff/17 F5）。
  const method = (options.method || 'GET').toUpperCase()
  const canRetry = method === 'GET' || method === 'PUT' || method === 'DELETE'
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    })
  } catch (error) {
    if (canRetry && attempt < 2) {
      await new Promise((done) => window.setTimeout(done, 250 * (attempt + 1)))
      return request(path, options, attempt + 1)
    }
    throw new BridgeError(describe(0), 0, error.message)
  }

  // 5xx 多半是 Core 抖动，重试两次再报错（同样只对幂等方法，避免重发 POST）。
  if (canRetry && response.status >= 500 && response.status !== 502 && response.status !== 503 && attempt < 2) {
    await new Promise((done) => window.setTimeout(done, 220 * (attempt + 1)))
    return request(path, options, attempt + 1)
  }

  const contentType = response.headers.get('content-type') || ''
  const body = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '')

  if (!response.ok) throw new BridgeError(describe(response.status, body), response.status, body?.detail)
  return body
}

/** 对可选接口的调用：Bridge 没实现时返回 fallback，而不是抛错。 */
async function optional(path, options, fallback) {
  if (missingEndpoints.has(path)) return fallback
  try {
    return await request(path, options)
  } catch (error) {
    if (error.status === 404 || error.status === 405) {
      missingEndpoints.add(path)
      return fallback
    }
    throw error
  }
}

const asList = (value, key) => (Array.isArray(value) ? value : Array.isArray(value?.[key]) ? value[key] : [])
const enc = encodeURIComponent

export const api = {
  health: () => request('/health'),

  accounts: async () => asList(await request('/accounts'), 'accounts'),
  createAccount: (payload) => request('/accounts', { method: 'POST', body: JSON.stringify(payload) }),
  patchAccount: (id, payload) => request(`/accounts/${enc(id)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteAccount: (id) => request(`/accounts/${enc(id)}`, { method: 'DELETE' }),

  catalog: async () => asList(await request('/tasks/catalog'), 'tasks'),
  accountTasks: async (id) => asList(await request(`/accounts/${enc(id)}/tasks`), 'tasks'),
  taskConfig: (id, taskId) => request(`/accounts/${enc(id)}/tasks/${enc(taskId)}/config`),
  setTaskEnabled: (id, taskId, enabled) =>
    request(`/accounts/${enc(id)}/tasks/${enc(taskId)}/enabled?enabled=${enabled}`, { method: 'PUT' }),
  saveTaskConfig: (id, taskId, fields) =>
    request(`/accounts/${enc(id)}/tasks/${enc(taskId)}/config`, { method: 'PATCH', body: JSON.stringify({ fields }) }),

  action: (id, action) => request(`/accounts/${enc(id)}/actions`, { method: 'POST', body: JSON.stringify({ action }) }),
  logs: async (id, limit = 200) => asList(await request(`/accounts/${enc(id)}/logs?limit=${limit}`), 'logs'),
  windows: async () => asList(await optional('/windows', undefined, []), 'windows'),

  // 以下三组是本版本新增的接口，旧 Bridge 会静默降级到本地存储。
  schedule: (id) => optional(`/accounts/${enc(id)}/schedule`, undefined, null),
  templates: async () => {
    // 保留 null 哨兵：Bridge 没有 /templates 时 optional 返回 null（前端据此退回本地存储）。
    // 若这里直接 asList(null) 会塌成 []，前端就分不清「接口缺失」和「接口存在但为空」，
    // 结果把 templateStorage 误判为 'bridge'，本地模板不落盘、刷新即丢。只有真拿到响应才归一化。
    const data = await optional('/templates', undefined, null)
    return data === null ? null : asList(data, 'templates')
  },
  saveTemplate: (template) => optional('/templates', { method: 'POST', body: JSON.stringify(template) }, null),
  deleteTemplate: (templateId) => optional(`/templates/${enc(templateId)}`, { method: 'DELETE' }, null),
  taskOrder: (id) => optional(`/accounts/${enc(id)}/task-order`, undefined, null),
  saveTaskOrder: (id, order) =>
    optional(`/accounts/${enc(id)}/task-order`, { method: 'PUT', body: JSON.stringify({ order }) }, null),
}

/**
 * 事件通道。
 *
 * 旧版前端每次切换账号都会重建 WebSocket，并且断线后再也不会恢复。
 * 这里改成全局单例 + 指数退避重连，账号切换只换过滤条件。
 */
export function createEventStream({ onEvent, onStatus }) {
  let socket = null
  let closed = false
  let retry = 0
  let timer = 0

  const setStatus = (status) => { try { onStatus?.(status) } catch { /* 状态回调不应打断重连 */ } }

  function open() {
    if (closed) return
    setStatus(retry ? 'reconnecting' : 'connecting')
    try {
      socket = new WebSocket(`${WS_BASE}/events`)
    } catch {
      schedule()
      return
    }
    socket.onopen = () => { retry = 0; setStatus('online') }
    socket.onmessage = (message) => {
      try { onEvent?.(JSON.parse(message.data)) } catch { /* 单条坏事件不影响通道 */ }
    }
    socket.onerror = () => { /* onclose 会紧随其后，统一在那里处理 */ }
    socket.onclose = () => {
      if (closed) return
      setStatus('offline')
      schedule()
    }
  }

  function schedule() {
    if (closed) return
    retry = Math.min(retry + 1, 6)
    const wait = Math.min(1000 * 2 ** (retry - 1), 15000)
    window.clearTimeout(timer)
    timer = window.setTimeout(open, wait)
  }

  open()
  return {
    close() {
      closed = true
      window.clearTimeout(timer)
      try { socket?.close() } catch { /* 已经断开 */ }
    },
    reconnectNow() {
      retry = 0
      window.clearTimeout(timer)
      try { socket?.close() } catch { /* 忽略 */ }
      open()
    },
  }
}
