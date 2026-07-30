#!/usr/bin/env node
/**
 * OAS 控制中心 · 离线 Mock Bridge
 *
 * 用途：在没有 OAS Core / 没有真实设备的情况下开发和回归前端。
 * 它实现 Bridge 的 /api/v1 契约（含本版本新增的 schedule / templates / task-order 接口），
 * 数据从真实的 config/oas1.json 派生，因此任务名、分组名、字段名与线上一致。
 *
 * 用法：
 *   node tools/mock-bridge.mjs --port 22368 --config ../../../config/oas1.json
 *
 * 它不会连接 OAS Core，不会写任何生产配置，不会绑定真实窗口，也不会启动任务。
 */
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const argv = process.argv.slice(2)
const argOf = (flag, fallback) => {
  const index = argv.indexOf(flag)
  return index >= 0 && argv[index + 1] ? argv[index + 1] : fallback
}
const PORT = Number(argOf('--port', 22368))

// 逐级向上找 OAS 项目根的 config 目录，这样 UI-claude 被挪到别的层级也能跑起来。
function discoverConfig() {
  const explicit = argOf('--config', '')
  if (explicit && existsSync(explicit)) return explicit
  const local = resolve(HERE, 'fixtures/oas1.json')
  if (existsSync(local)) return local
  let dir = HERE
  for (let depth = 0; depth < 8; depth += 1) {
    for (const name of ['oas1.json', 'template.json']) {
      const candidate = resolve(dir, 'config', name)
      if (existsSync(candidate)) return candidate
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return ''
}
const CONFIG_PATH = discoverConfig()
if (!CONFIG_PATH) {
  console.error('[mock] 找不到可用的 oas 配置样本，请用 --config 指定一个 config/*.json')
  process.exit(1)
}
const RAW = JSON.parse(readFileSync(CONFIG_PATH, 'utf-8'))

/* ------------------------------------------------------------------ 任务目录 */

const MENU = {
  Script: ['Script', 'Restart', 'GlobalGame'],
  'Soul Zones': ['Orochi', 'Sougenbi', 'FallenSun', 'EternitySea', 'SixRealms'],
  'Daily Task': ['DailyTrifles', 'AreaBoss', 'GoldYoukai', 'ExperienceYoukai', 'Nian', 'TalismanPass',
    'DemonEncounter', 'Pets', 'SoulsTidy', 'Delegation', 'WantedQuests', 'Tako', 'AutoCheckinBigGod'],
  'Liver Emperor Exclusive': ['BondlingFairyland', 'EvoZone', 'GoryouRealm', 'Exploration', 'Hyakkiyakou',
    'HeroTest', 'FindJade', 'MemoryScrolls'],
  Guild: ['KekkaiUtilize', 'KekkaiActivation', 'RealmRaid', 'RyouToppa', 'Dokan', 'CollectiveMissions',
    'Hunt', 'AbyssShadows', 'GuildBanquet', 'DemonRetreat', 'GuildActivityMonitor'],
  'Weekly Task': ['TrueOrochi', 'RichMan', 'Secret', 'WeeklyTrifles', 'MysteryShop', 'Duel'],
  'Activity Task': ['ActivityShikigami', 'MetaDemon', 'FrogBoss', 'FloatParade', 'Quiz', 'KittyShop', 'DyeTrials'],
}
const CATEGORY_LABELS = {
  Script: '运行与设备',
  'Soul Zones': '御魂副本',
  'Daily Task': '日常任务',
  'Liver Emperor Exclusive': '肝帝专属',
  Guild: '阴阳寮',
  'Weekly Task': '每周任务',
  'Activity Task': '限时活动',
}
const TASK_LABELS = {
  Script: '运行设置', Restart: '自动重启', GlobalGame: '全局游戏设置',
  Orochi: '御魂', Sougenbi: '业原火', FallenSun: '日轮之城', EternitySea: '永生之海', SixRealms: '六道之门',
  DailyTrifles: '每日琐事', AreaBoss: '地狱鬼王', GoldYoukai: '金币妖怪', ExperienceYoukai: '经验妖怪',
  Nian: '年兽', TalismanPass: '花合战', DemonEncounter: '封魔之时', Pets: '小猫咪', SoulsTidy: '御魂整理',
  Delegation: '式神委派', WantedQuests: '悬赏封印', Tako: '石距', AutoCheckinBigGod: '大神签到',
  BondlingFairyland: '契灵之境', EvoZone: '觉醒副本', GoryouRealm: '御灵之境', Exploration: '探索',
  Hyakkiyakou: '百鬼夜行', HeroTest: '英雄试炼', FindJade: '寻找勾玉', MemoryScrolls: '绫卷',
  KekkaiUtilize: '结界蹭卡', KekkaiActivation: '结界挂卡', RealmRaid: '个人突破', RyouToppa: '寮突破',
  Dokan: '道馆', CollectiveMissions: '集体任务', Hunt: '狩猎战', AbyssShadows: '暗影迷宫',
  GuildBanquet: '寮宴会', DemonRetreat: '退治恶鬼', GuildActivityMonitor: '寮活动监控',
  TrueOrochi: '真·八岐大蛇', RichMan: '大富翁', Secret: '秘闻之境', WeeklyTrifles: '每周琐事',
  MysteryShop: '神秘商店', Duel: '自动斗技', ActivityShikigami: '当期式神爬塔', MetaDemon: '超鬼王',
  FrogBoss: '青蛙瓷器', FloatParade: '花车巡游', Quiz: '智力问答', KittyShop: '小猫の店', DyeTrials: '染色试炼',
}

const toSnake = (value) => value.replace(/([a-z0-9])([A-Z])/g, '$1_$2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2').toLowerCase()
const titleCase = (value) => String(value).split('_').filter(Boolean).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')

/* ------------------------------------------------------- 字段类型 / 枚举推断 */

const ENUMS = {
  serial: ['auto', '127.0.0.1:16384', '127.0.0.1:7555', 'emulator-5554'],
  package_name: ['auto', 'com.netease.onmyoji', 'com.netease.onmyoji.bili', 'com.netease.onmyoji.huawei', 'com.netease.onmyoji.mi'],
  screenshot_method: ['auto', 'ADB', 'ADB_nc', 'DroidCast', 'DroidCast_raw', 'scrcpy', 'nemu_ipc', 'ldopengl'],
  control_method: ['minitouch', 'maatouch', 'MaaTouch', 'ADB', 'Hermit', 'nemu_ipc'],
  emulatorinfo_type: ['auto', 'MuMuPlayer12', 'NoxPlayer', 'LDPlayer', 'BlueStacks'],
  when_task_queue_empty: ['goto_main', 'stay_there', 'close_game', 'close_game_emulator', 'shutdown'],
  schedule_rule: ['Filter', 'Fifo', 'Priority'],
  notify_config: ['provider: null'],
  utilize_rule: ['default', 'ap_first', 'exp_first'],
  select_friend_list: ['same_server', 'cross_server', 'recent_friend'],
  shikigami_class: ['N', 'R', 'SR', 'SSR', 'SP'],
  green_mark: ['greenmain', 'greenleft1', 'greenleft2', 'greenleft3', 'greenleft4', 'greenleft5'],
  group_class: ['leader', 'member', 'alone'],
  invite_class: ['autofind', 'recent_friend', 'wild'],
  invite_number: ['one', 'two'],
  handle_error: ['accept', 'reject', 'ignore'],
  restart_type: ['restart', 'ignore', 'wait_10s'],
  layer: ['one', 'two', 'three'],
  soul_apply_rule: ['default', 'costume_main', 'costume_realm_default'],
}

function inferType(value, key) {
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number'
  if (typeof value === 'string') {
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) return 'date_time'
    if (/^\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) return 'time_delta'
    if (/^\d{2}:\d{2}:\d{2}$/.test(value)) return 'time'
    if (ENUMS[key]) return 'enum'
    return 'string'
  }
  return 'string'
}

function buildField(key, value) {
  const type = inferType(value, key)
  const options = type === 'enum' ? ENUMS[key] : (ENUMS[key] || [])
  const field = {
    name: key,
    title: titleCase(key),
    description: `${titleCase(key)} help`,
    default: value,
    value,
    type,
    options: options && options.length ? [...new Set([...options, ...(typeof value === 'string' && value ? [value] : [])])] : [],
  }
  if (field.options.length && field.type === 'string') field.type = 'enum'
  return field
}

const CONFIG_STORE = new Map() // `${accountId}/${taskId}` -> groups

function baseGroupsFor(taskId) {
  const snake = toSnake(taskId)
  const raw = RAW[snake]
  if (!raw || typeof raw !== 'object') {
    return {
      scheduler: [
        buildField('enable', false),
        buildField('next_run', '2023-01-01 00:00:00'),
        buildField('priority', 5),
        buildField('success_interval', '00 06:00:00'),
        buildField('failure_interval', '00 06:00:00'),
        buildField('server_update', '09:00:00'),
      ],
    }
  }
  const groups = {}
  for (const [groupName, groupValue] of Object.entries(raw)) {
    if (groupValue === null || typeof groupValue !== 'object' || Array.isArray(groupValue)) continue
    const fields = Object.entries(groupValue)
      .filter(([, v]) => v === null || typeof v !== 'object' || !Array.isArray(v))
      .map(([k, v]) => buildField(k, v === null ? '' : v))
      .filter((field) => typeof field.value !== 'object')
    if (fields.length) groups[groupName] = fields
  }
  return Object.keys(groups).length ? groups : { scheduler: [buildField('enable', false)] }
}

function configFor(accountId, taskId) {
  const key = `${accountId}/${taskId}`
  if (!CONFIG_STORE.has(key)) CONFIG_STORE.set(key, JSON.parse(JSON.stringify(baseGroupsFor(taskId))))
  return CONFIG_STORE.get(key)
}

/* ---------------------------------------------------------------- 账号状态 */

const ALL_TASKS = Object.entries(MENU).flatMap(([category, ids]) => ids.map((id) => ({ id, category })))
const categoryOf = (id) => ALL_TASKS.find((item) => item.id === id)?.category || 'Other'

const accounts = new Map()
function makeAccount(id, extra = {}) {
  return {
    id, name: id, avatar: 'blue', tags: [], device_label: '未配置设备', sort_order: accounts.size,
    state: 'offline', state_label: '已停止', connected: true, ...extra,
  }
}
accounts.set('oas1', makeAccount('oas1', { device_label: 'MuMu 12 · 窗口 1', avatar: 'blue' }))
accounts.set('oas2', makeAccount('oas2', { device_label: 'MuMu 12 · 窗口 2', avatar: 'mint', state: 'running', state_label: '运行中' }))
accounts.set('oas3', makeAccount('oas3', { device_label: '等待设备', avatar: 'gold', connected: false }))

const enabledOf = new Map([
  ['oas1', new Set(['Script', 'KekkaiUtilize', 'WantedQuests', 'Orochi'])],
  ['oas2', new Set(['Script', 'Restart', 'DailyTrifles', 'Pets', 'SoulsTidy', 'Delegation'])],
  ['oas3', new Set()],
])
for (const [accountId, ids] of enabledOf) {
  for (const id of ids) {
    const scheduler = configFor(accountId, id).scheduler
    const enable = scheduler?.find((field) => field.name === 'enable')
    if (enable) enable.value = true
  }
}

const pad = (n) => String(n).padStart(2, '0')
function futureStamp(minutes) {
  const date = new Date(Date.now() + minutes * 60_000)
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function enabledTasks(accountId) {
  const ids = [...(enabledOf.get(accountId) || [])]
  return ids.map((id, index) => ({
    id, title: TASK_LABELS[id] || id, category: CATEGORY_LABELS[categoryOf(id)] || '其他',
    enabled: true, next_run: futureStamp(index * 37 - 10), available: true,
  }))
}

function scheduleFor(accountId) {
  const tasks = enabledTasks(accountId)
  const account = accounts.get(accountId)
  const running = account?.state === 'running' && tasks.length
    ? { name: tasks[0].id, next_run: tasks[0].next_run } : {}
  const rest = tasks.slice(running.name ? 1 : 0)
  return {
    running,
    pending: rest.slice(0, 2).map((task) => ({ name: task.id, next_run: task.next_run })),
    waiting: rest.slice(2).map((task) => ({ name: task.id, next_run: task.next_run })),
  }
}

const clients = new Set()
let seq = 0
const logs = new Map()
const LEVELS = ['info', 'info', 'info', 'warn', 'error']
function appendLog(accountId, level, message) {
  const list = logs.get(accountId) || []
  list.push({ timestamp: new Date().toISOString(), level, message })
  logs.set(accountId, list.slice(-300))
  broadcast({ type: 'log.appended', accountId, level, payload: { log: list[list.length - 1] } })
}
appendLog('oas1', 'info', 'Mock Bridge 已连接，数据来自 config 样本')
appendLog('oas1', 'info', '任务调度器已加载 4 项任务')
appendLog('oas2', 'info', '[Orochi] 开始执行御魂副本')
appendLog('oas2', 'warn', '[Device] 截图耗时 0.82s，高于预期')
appendLog('oas3', 'error', '[Device] 未找到可用设备，请先配置窗口句柄')

const windows = [
  { handle: 4786794, title: '2301', pid: 21452, process: 'MuMuNxDevice.exe' },
  { handle: 132456, title: '阴阳师', pid: 5120, process: 'MuMuNxDevice.exe' },
  { handle: 998112, title: 'MuMu模拟器12', pid: 4400, process: 'MuMuPlayer.exe' },
  { handle: 552210, title: '雷电模拟器', pid: 6600, process: 'dnplayer.exe' },
  { handle: 700100, title: '此电脑', pid: 900, process: 'explorer.exe' },
  { handle: 700200, title: 'OAS 控制中心 · dev - Google Chrome', pid: 901, process: 'chrome.exe' },
]

/* --------------------------------------------------------- UI 元数据存储 */

let templates = [
  { id: 'tpl-demo-1', name: '结界蹭卡 · 标准', task_id: 'KekkaiUtilize', task_title: '结界蹭卡', created_at: new Date().toISOString(), groups: {} },
]
const taskOrder = new Map()

/* -------------------------------------------------------------- WebSocket */

function wsFrame(text) {
  const payload = Buffer.from(text)
  if (payload.length < 126) return Buffer.concat([Buffer.from([0x81, payload.length]), payload])
  if (payload.length < 65536) {
    const header = Buffer.alloc(4)
    header[0] = 0x81; header[1] = 126; header.writeUInt16BE(payload.length, 2)
    return Buffer.concat([header, payload])
  }
  const header = Buffer.alloc(10)
  header[0] = 0x81; header[1] = 127; header.writeBigUInt64BE(BigInt(payload.length), 2)
  return Buffer.concat([header, payload])
}
function broadcast(event) {
  const full = { version: 1, seq: ++seq, timestamp: new Date().toISOString(), level: 'info', ...event }
  const frame = wsFrame(JSON.stringify(full))
  for (const socket of clients) if (!socket.destroyed) socket.write(frame)
}

/* -------------------------------------------------------------- HTTP 接口 */

const json = (res, status, body) => {
  const payload = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': '*',
    'Access-Control-Allow-Methods': '*',
  })
  res.end(payload)
}
const readBody = (req) => new Promise((done, fail) => {
  let raw = ''
  req.setEncoding('utf8')
  req.on('data', (chunk) => { raw += chunk })
  req.on('end', () => { try { done(raw ? JSON.parse(raw) : {}) } catch (error) { fail(error) } })
  req.on('error', fail)
})

function accountView(account) {
  const tasks = enabledTasks(account.id)
  return { ...account, selected_count: tasks.length, selected_tasks: tasks.map((task) => task.id), next_run: tasks[0]?.next_run || null }
}

async function handle(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`)
  const path = url.pathname
  const parts = path.split('/').filter(Boolean)
  const method = req.method

  if (method === 'OPTIONS') { json(res, 204, {}); return }

  if (method === 'GET' && path === '/api/v1/health') {
    // mock:true 让前端识别这是演示数据并弹出醒目横幅；core_url 的 mock:// 前缀是双保险。
    return json(res, 200, { status: 'ok', bridge: 'ok', core: 'ok', core_url: 'mock://preview', mock: true, version: '1.1.0-mock', accounts: accounts.size })
  }
  if (method === 'GET' && path === '/api/v1/windows') return json(res, 200, windows)
  if (method === 'GET' && path === '/api/v1/tasks/catalog') {
    return json(res, 200, ALL_TASKS.map(({ id, category }) => ({
      id, title: TASK_LABELS[id] || id, category: CATEGORY_LABELS[category] || category, enabled: false, next_run: null, available: true,
    })))
  }
  if (method === 'GET' && path === '/api/v1/accounts') return json(res, 200, [...accounts.values()].map(accountView))
  if (method === 'POST' && path === '/api/v1/accounts') {
    const body = await readBody(req)
    const id = (body.name || '').trim() || `oas${accounts.size + 1}`
    if (accounts.has(id)) return json(res, 400, { detail: `账号 ${id} 已存在` })
    const account = makeAccount(id, { device_label: body.device_label || '未配置设备', avatar: body.avatar || 'blue' })
    accounts.set(id, account)
    enabledOf.set(id, new Set())
    logs.set(id, [])
    appendLog(id, 'info', `已从模板创建账号 ${id}`)
    return json(res, 200, accountView(account))
  }

  // UI 元数据：模板
  if (path === '/api/v1/templates') {
    if (method === 'GET') return json(res, 200, templates)
    if (method === 'POST') {
      const body = await readBody(req)
      const item = { ...body, id: body.id || `tpl-${Date.now()}`, created_at: new Date().toISOString() }
      templates = [item, ...templates.filter((entry) => entry.id !== item.id)]
      return json(res, 200, item)
    }
  }
  if (method === 'DELETE' && parts[2] === 'templates' && parts[3]) {
    templates = templates.filter((item) => item.id !== decodeURIComponent(parts[3]))
    return json(res, 200, { deleted: true })
  }

  if (parts[0] !== 'api' || parts[1] !== 'v1' || parts[2] !== 'accounts') return json(res, 404, { detail: '未找到接口' })
  const accountId = decodeURIComponent(parts[3] || '')
  const account = accounts.get(accountId)
  if (!account) return json(res, 404, { detail: `账号不存在：${accountId}` })

  if (method === 'PATCH' && parts.length === 4) {
    const body = await readBody(req)
    Object.assign(account, Object.fromEntries(Object.entries(body).filter(([, value]) => value !== null && value !== undefined)))
    return json(res, 200, accountView(account))
  }
  if (method === 'DELETE' && parts.length === 4) {
    accounts.delete(accountId); enabledOf.delete(accountId); logs.delete(accountId)
    broadcast({ type: 'account.deleted', accountId })
    return json(res, 200, { deleted: true })
  }
  if (method === 'GET' && parts[4] === 'schedule') return json(res, 200, { account_id: accountId, ...scheduleFor(accountId), state: account.state, state_label: account.state_label })
  if (method === 'GET' && parts[4] === 'tasks' && parts.length === 5) return json(res, 200, enabledTasks(accountId))
  if (method === 'GET' && parts[4] === 'logs') {
    const limit = Number(url.searchParams.get('limit') || 120)
    return json(res, 200, (logs.get(accountId) || []).slice(-limit))
  }
  if (method === 'GET' && parts[4] === 'task-order') return json(res, 200, taskOrder.get(accountId) || [])
  if (method === 'PUT' && parts[4] === 'task-order') {
    const body = await readBody(req)
    taskOrder.set(accountId, Array.isArray(body.order) ? body.order : [])
    return json(res, 200, { saved: true })
  }
  if (method === 'POST' && parts[4] === 'actions') {
    const body = await readBody(req)
    const action = body.action
    if (action === 'start' || action === 'restart') {
      account.state = 'running'; account.state_label = '运行中'
      appendLog(accountId, 'info', `[Mock] 已接受 ${action} 命令，开始调度任务`)
      broadcast({ type: 'task.started', accountId, payload: { state: 'running', stateLabel: '运行中' } })
    } else if (action === 'stop') {
      account.state = 'offline'; account.state_label = '已停止'
      appendLog(accountId, 'info', '[Mock] 已接受 stop 命令')
      broadcast({ type: 'task.stopped', accountId, payload: { state: 'offline', stateLabel: '已停止' } })
    } else {
      broadcast({ type: 'schedule.updated', accountId, payload: { schedule: scheduleFor(accountId) } })
    }
    return json(res, 200, { accepted: true, account_id: accountId, action, state: { state: account.state, state_label: account.state_label, connected: account.connected, schedule: scheduleFor(accountId) } })
  }
  if (parts[4] !== 'tasks') return json(res, 404, { detail: '未找到接口' })

  const taskId = decodeURIComponent(parts[5] || '')
  if (method === 'GET' && parts[6] === 'config') {
    return json(res, 200, { task_id: taskId, title: TASK_LABELS[taskId] || taskId, category: CATEGORY_LABELS[categoryOf(taskId)] || '其他', groups: JSON.parse(JSON.stringify(configFor(accountId, taskId))) })
  }
  if (method === 'PUT' && parts[6] === 'enabled') {
    const enabled = url.searchParams.get('enabled') === 'true'
    const set = enabledOf.get(accountId) || new Set()
    if (enabled) set.add(taskId); else set.delete(taskId)
    enabledOf.set(accountId, set)
    const scheduler = configFor(accountId, taskId).scheduler
    const enable = scheduler?.find((field) => field.name === 'enable')
    if (enable) enable.value = enabled
    appendLog(accountId, 'info', `${enabled ? '已启用' : '已停用'} ${TASK_LABELS[taskId] || taskId}`)
    broadcast({ type: 'task.state', accountId, taskId, payload: { enabled } })
    return json(res, 200, { id: taskId, title: TASK_LABELS[taskId] || taskId, category: CATEGORY_LABELS[categoryOf(taskId)] || '其他', enabled, next_run: enabled ? futureStamp(5) : null, available: true })
  }
  if (method === 'PATCH' && parts[6] === 'config') {
    const body = await readBody(req)
    const groups = configFor(accountId, taskId)
    let updated = 0
    for (const field of body.fields || []) {
      const target = groups[field.group]?.find((item) => item.name === field.name)
      if (!target) continue
      if (field.name === 'handle' && String(field.value) === '999') return json(res, 502, { detail: 'OAS Core 返回 400: 窗口句柄无效（Mock 故意制造的错误，用来验证前端错误提示）' })
      target.value = field.value
      updated += 1
    }
    appendLog(accountId, 'info', `已保存 ${TASK_LABELS[taskId] || taskId} 的 ${updated} 项改动`)
    broadcast({ type: 'task.configured', accountId, taskId, payload: { fields: updated } })
    return json(res, 200, { saved: true, updated })
  }
  return json(res, 404, { detail: '未找到接口' })
}

const server = createServer((req, res) => {
  handle(req, res).catch((error) => json(res, 500, { detail: error.message }))
})

server.on('upgrade', (req, socket) => {
  const url = new URL(req.url, `http://${req.headers.host}`)
  if (url.pathname !== '/api/v1/events') return socket.destroy()
  const accept = createHash('sha1').update(`${req.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest('base64')
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`)
  clients.add(socket)
  socket.write(wsFrame(JSON.stringify({ version: 1, seq: ++seq, timestamp: new Date().toISOString(), type: 'bridge.ready', level: 'info', payload: { mock: true } })))
  socket.on('close', () => clients.delete(socket))
  socket.on('error', () => clients.delete(socket))
})

// 运行中的账号定期产生日志，用来验证日志面板的实时表现
const SAMPLE = [
  '[Orochi] 队伍已就绪，开始挑战',
  '[Orochi] 战斗胜利，结算中',
  '[Device] 截图 0.31s',
  '[Scheduler] 下一个任务：结界蹭卡',
  '[KekkaiUtilize] 已收取寮资金',
  '[Restart] 检测到游戏未响应，准备重启',
]
setInterval(() => {
  for (const account of accounts.values()) {
    if (account.state !== 'running') continue
    const level = LEVELS[Math.floor(Math.random() * LEVELS.length)]
    appendLog(account.id, level, SAMPLE[Math.floor(Math.random() * SAMPLE.length)])
  }
}, 3200)

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[mock] Bridge 样本数据来自 ${CONFIG_PATH}`)
  console.log(`[mock] 监听 http://127.0.0.1:${PORT}  (${ALL_TASKS.length} 项任务 / ${accounts.size} 个账号)`)
})
