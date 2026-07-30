import { createHash } from 'node:crypto'
import { createServer } from 'node:http'

const portIndex = process.argv.indexOf('--port')
const port = Number(portIndex >= 0 ? process.argv[portIndex + 1] : 22368)

const catalog = [
  ['Script', 'Script', 'Script'],
  ['Restart', 'Restart', 'Script'],
  ['Orochi', 'Orochi', 'Daily Task'],
  ['WantedQuests', 'WantedQuests', 'Daily Task'],
  ['MemoryScrolls', 'MemoryScrolls', 'Activity Task'],
  ['KekkaiUtilize', 'KekkaiUtilize', 'Daily Task'],
  ['KekkaiActivation', 'KekkaiActivation', 'Daily Task'],
  ['TrueOrochi', 'TrueOrochi', 'Activity Task'],
  ['DemonEncounter', 'DemonEncounter', 'Daily Task'],
  ['TalismanPass', 'TalismanPass', 'Activity Task'],
  ['SoulsTidy', 'SoulsTidy', 'Daily Task'],
  ['Delegation', 'Delegation', 'Daily Task'],
  ['Duel', 'Duel', 'Daily Task'],
  ['GuildActivityMonitor', 'GuildActivityMonitor', 'Guild'],
  ['MysteryShop', 'MysteryShop', 'Other'],
]

const accounts = new Map([
  ['oas1', { id: 'oas1', name: 'oas1', avatar: 'blue', device_label: 'MuMu 12 / Window 01', state: 'paused', state_label: 'Paused', connected: true, selected_tasks: ['Script', 'MemoryScrolls'] }],
  ['oas2', { id: 'oas2', name: 'oas2', avatar: 'mint', device_label: 'MuMu 12 / Window 02', state: 'running', state_label: 'Running', connected: true, selected_tasks: ['DailyTrifles', 'KekkaiUtilize'] }],
  ['oas3', { id: 'oas3', name: 'oas3', avatar: 'gold', device_label: 'Waiting for device', state: 'offline', state_label: 'Waiting for device', connected: false, selected_tasks: [] }],
])

const windows = [
  { handle: 2303, title: '2303 - Game Window', pid: 2303, process: 'MuMuPlayer.exe' },
  { handle: 2304, title: 'MuMu Emulator', pid: 2304, process: 'MuMuPlayer.exe' },
  { handle: 2305, title: 'MuMuNxDevice', pid: 2305, process: 'MuMuNxDevice.exe' },
]

function log(level, message) {
  return { timestamp: new Date().toISOString(), level, message }
}

const logs = new Map([
  ['oas1', [log('info', 'Preview Bridge connected'), log('info', 'Loaded account metadata'), log('info', 'Window binding is simulated in preview mode')]],
  ['oas2', [log('info', 'Daily task schedule loaded')]],
  ['oas3', [log('warn', 'Waiting for a simulated device')]],
])
const configs = new Map()
const clients = new Set()

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function taskSummary(id, enabled = false) {
  const entry = catalog.find((item) => item[0] === id)
  return { id, title: entry?.[1] || id, category: entry?.[2] || 'Other', enabled, next_run: enabled ? '09:00' : null, available: true }
}

function accountView(account) {
  return { ...account, selected_count: account.selected_tasks.length, selected_tasks: [...account.selected_tasks] }
}

function configFor(accountId, taskId) {
  const key = `${accountId}/${taskId}`
  if (!configs.has(key)) {
    configs.set(key, {
      task_id: taskId,
      title: taskId,
      groups: {
        scheduler: [
          { name: 'enable', title: 'enable', description: 'Enable this task', default: true, value: true, type: 'boolean', options: [] },
          { name: 'next_run', title: 'next_run', description: 'Next scheduled run', default: '09:00', value: '09:00', type: 'time', options: [] },
          { name: 'priority', title: 'priority', description: 'Task priority', default: 5, value: 5, type: 'integer', options: [] },
        ],
        device: [
          { name: 'handle', title: 'handle', description: 'Select the game or emulator window', default: '2303', value: accountId === 'oas3' ? '' : '2303', type: 'string', options: [] },
          { name: 'package', title: 'package', description: 'Game client package', default: 'com.netease.onmyoji', value: 'com.netease.onmyoji', type: 'enum', options: ['com.netease.onmyoji', 'com.netease.onmyoji.bili'] },
        ],
      },
    })
  }
  return configs.get(key)
}

function appendLog(accountId, level, message) {
  const list = logs.get(accountId) || []
  list.push(log(level, message))
  logs.set(accountId, list.slice(-120))
}

function wsFrame(text) {
  const payload = Buffer.from(text)
  if (payload.length < 126) return Buffer.concat([Buffer.from([0x81, payload.length]), payload])
  const header = Buffer.alloc(4)
  header[0] = 0x81
  header[1] = 126
  header.writeUInt16BE(payload.length, 2)
  return Buffer.concat([header, payload])
}

function broadcast(event) {
  const frame = wsFrame(JSON.stringify(event))
  for (const socket of clients) if (!socket.destroyed) socket.write(frame)
}

function send(res, status, body) {
  const payload = JSON.stringify(body)
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(payload) })
  res.end(payload)
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = ''
    req.setEncoding('utf8')
    req.on('data', (chunk) => { body += chunk })
    req.on('end', () => {
      try { resolve(body ? JSON.parse(body) : {}) } catch (error) { reject(error) }
    })
    req.on('error', reject)
  })
}

function findAccount(id, res) {
  const account = accounts.get(id)
  if (!account) send(res, 404, { detail: `Unknown preview account: ${id}` })
  return account
}

async function handle(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`)
  const parts = url.pathname.split('/').filter(Boolean)
  if (req.method === 'GET' && url.pathname === '/api/v1/health') return send(res, 200, { status: 'ok', bridge: 'ok', core: 'ok', core_url: 'preview' })
  if (req.method === 'GET' && url.pathname === '/api/v1/windows') return send(res, 200, windows)
  if (req.method === 'GET' && url.pathname === '/api/v1/accounts') return send(res, 200, [...accounts.values()].map(accountView))
  if (req.method === 'POST' && url.pathname === '/api/v1/accounts') {
    const body = await readBody(req)
    const id = body.name?.trim() || `preview-${accounts.size + 1}`
    const account = { id, name: id, avatar: body.avatar || 'blue', device_label: body.device_label || 'Preview device', state: 'offline', state_label: 'Waiting for device', connected: false, selected_tasks: [] }
    accounts.set(id, account)
    logs.set(id, [log('info', 'Preview account created')])
    return send(res, 201, accountView(account))
  }
  if (req.method === 'GET' && url.pathname === '/api/v1/tasks/catalog') return send(res, 200, catalog.map(([id]) => taskSummary(id, false)))
  if (parts[0] !== 'api' || parts[1] !== 'v1' || parts[2] !== 'accounts') return send(res, 404, { detail: 'Not found' })

  const accountId = decodeURIComponent(parts[3] || '')
  const account = findAccount(accountId, res)
  if (!account) return
  if (req.method === 'POST' && parts.length === 5 && parts[4] === 'actions') {
    const body = await readBody(req)
    const action = body.action
    if (action === 'start' || action === 'restart') { account.state = 'running'; account.state_label = 'Running' }
    if (action === 'stop') { account.state = 'offline'; account.state_label = 'Stopped' }
    appendLog(accountId, 'info', `${action} accepted by preview Bridge`)
    broadcast({ version: 1, seq: Date.now(), timestamp: new Date().toISOString(), type: action === 'stop' ? 'task.stopped' : 'task.started', accountId, level: 'info', payload: { preview: true } })
    return send(res, 200, { accepted: true, account_id: accountId, action, state: account.state })
  }
  if (req.method === 'GET' && parts.length === 5 && parts[4] === 'tasks') return send(res, 200, account.selected_tasks.map((id) => taskSummary(id, true)))
  if (req.method === 'GET' && parts.length === 5 && parts[4] === 'logs') return send(res, 200, (logs.get(accountId) || []).slice(-Number(url.searchParams.get('limit') || 120)))
  if (parts[4] !== 'tasks') return send(res, 404, { detail: 'Not found' })
  const taskId = decodeURIComponent(parts[5] || '')
  if (req.method === 'GET' && parts.length === 7 && parts[6] === 'config') return send(res, 200, clone(configFor(accountId, taskId)))
  if (req.method === 'PUT' && parts.length === 7 && parts[6] === 'enabled') {
    const enabled = url.searchParams.get('enabled') === 'true'
    account.selected_tasks = enabled ? [...new Set([...account.selected_tasks, taskId])] : account.selected_tasks.filter((id) => id !== taskId)
    configFor(accountId, taskId).groups.scheduler[0].value = enabled
    appendLog(accountId, 'info', `${enabled ? 'Enabled' : 'Disabled'} ${taskId} in preview`)
    return send(res, 200, taskSummary(taskId, enabled))
  }
  if (req.method === 'PATCH' && parts.length === 7 && parts[6] === 'config') {
    const body = await readBody(req)
    const config = configFor(accountId, taskId)
    for (const field of body.fields || []) {
      const target = config.groups[field.group]?.find((item) => item.name === field.name)
      if (target) target.value = field.value
    }
    appendLog(accountId, 'info', `Saved ${taskId} configuration in preview`)
    broadcast({ version: 1, seq: Date.now(), timestamp: new Date().toISOString(), type: 'task.configured', accountId, taskId, level: 'info', payload: { preview: true } })
    return send(res, 200, { saved: true, updated: (body.fields || []).length })
  }
  return send(res, 404, { detail: 'Not found' })
}

const server = createServer((req, res) => {
  handle(req, res).catch((error) => send(res, 500, { detail: error.message }))
})

server.on('upgrade', (req, socket) => {
  const url = new URL(req.url, `http://${req.headers.host}`)
  if (url.pathname !== '/api/v1/events') return socket.destroy()
  const accept = createHash('sha1').update(`${req.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest('base64')
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`)
  clients.add(socket)
  socket.write(wsFrame(JSON.stringify({ version: 1, seq: 0, timestamp: new Date().toISOString(), type: 'bridge.ready', level: 'info', payload: { preview: true } })))
  socket.on('close', () => clients.delete(socket))
  socket.on('error', () => clients.delete(socket))
})

server.listen(port, '127.0.0.1', () => console.log(`Preview Bridge listening on http://127.0.0.1:${port}`))
