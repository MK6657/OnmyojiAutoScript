/**
 * OAS 控制中心 · 应用外壳
 *
 * 状态集中在这里，视图组件只负责渲染和回调，方便后续拆分或替换。
 *
 * 三个和旧版不同的关键点：
 * 1. 只提交被改过的字段（脏字段追踪），不再把整张表单回写给 Core；
 * 2. 事件 WebSocket 全局单例 + 自动重连，切换账号不重建连接；
 * 3. 有未保存改动时，切换任务 / 账号 / 视图会先提示，避免静默丢失。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, BRIDGE_ORIGIN, createEventStream } from './api.js'
import { KEYS, clone, makeId, readJSON, useDensity, usePersistentState, useTheme, writeJSON } from './store.js'
import { taskLabel } from './locale.js'
import { Avatar, Banner, Confirm, Empty, Prompt, Search, StateDot, StatePill, Toasts, WindowBindDialog } from './components.jsx'
import { inferEmulatorType } from './emulator.js'
import { LogsView, OverviewView, SettingsView, TasksView } from './views.jsx'

const VIEWS = [
  { key: 'overview', label: '概览' },
  { key: 'tasks', label: '任务' },
  { key: 'logs', label: '日志' },
  { key: 'settings', label: '设置' },
]
const LOG_LIMIT = 400
const fieldKey = (group, name) => `${group}.${name}`
const same = (left, right) => JSON.stringify(left ?? null) === JSON.stringify(right ?? null)

function AccountMenu({ account, onRename, onDelete }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])
  const pick = (fn) => (e) => { e.stopPropagation(); setOpen(false); fn() }
  return (
    <div className="account-menu" ref={ref}>
      <button type="button" className="account-menu-trigger" title="账号操作"
        aria-label={`${account.name} 的操作菜单`}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v) }}>⋯</button>
      {open ? (
        <div className="account-menu-pop" role="menu">
          <button type="button" role="menuitem" onClick={pick(onRename)}>重命名</button>
          <button type="button" role="menuitem" className="danger" onClick={pick(onDelete)}>删除账号</button>
        </div>
      ) : null}
    </div>
  )
}

export default function App() {
  /* ------------------------------------------------------------- 全局状态 */
  const [health, setHealth] = useState({ bridge: 'connecting', core: 'connecting' })
  const [eventStatus, setEventStatus] = useState('connecting')
  const [accounts, setAccounts] = useState([])
  const [catalog, setCatalog] = useState([])
  const [bootError, setBootError] = useState('')
  const [booted, setBooted] = useState(false)

  const [selectedId, setSelectedId] = usePersistentState(KEYS.account, '')
  const [view, setView] = usePersistentState(KEYS.view, 'overview')
  const [collapsed, setCollapsed] = usePersistentState(KEYS.sidebar, false)
  const [logLevels, setLogLevels] = usePersistentState(KEYS.logLevels, ['info', 'warn', 'error'])
  const [onboarded, setOnboarded] = usePersistentState(KEYS.onboarded, false)
  const [theme, setTheme] = useTheme()
  const [density, setDensity] = useDensity()

  const [accountFilter, setAccountFilter] = useState('')
  const [enabledTasks, setEnabledTasks] = useState([])
  const [schedule, setSchedule] = useState(null)
  const [deviceConfig, setDeviceConfig] = useState(null)
  const [logsByAccount, setLogsByAccount] = useState({})
  const [windows, setWindows] = useState([])
  const [windowsLoading, setWindowsLoading] = useState(false)
  const [binding, setBinding] = useState(false)   // 「扫描并绑定窗口」弹窗开关

  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [config, setConfig] = useState(null)      // 当前草稿
  const [baseline, setBaseline] = useState(null)  // 上一次与 Core 同步的值
  const [saving, setSaving] = useState(false)
  const [busyAction, setBusyAction] = useState('')

  const [templates, setTemplates] = useState([])
  const [templateStorage, setTemplateStorage] = useState('local')

  const [toasts, setToasts] = useState([])
  const [confirmRequest, setConfirmRequest] = useState(null)
  const [promptRequest, setPromptRequest] = useState(null)
  const confirmResolve = useRef(null)
  const promptResolve = useRef(null)
  const streamRef = useRef(null)
  const selectedIdRef = useRef(selectedId)
  const loadTicket = useRef(0)
  const configTicket = useRef(0)

  useEffect(() => { selectedIdRef.current = selectedId }, [selectedId])

  /* ---------------------------------------------------------------- 提示 */
  const notify = useCallback((message, tone = 'info') => {
    const id = makeId('toast')
    setToasts((current) => [...current.slice(-3), { id, message, tone }])
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), tone === 'error' ? 6000 : 3200)
  }, [])
  const dismissToast = useCallback((id) => setToasts((current) => current.filter((item) => item.id !== id)), [])

  const ask = useCallback((request) => new Promise((resolve) => {
    confirmResolve.current = resolve
    setConfirmRequest(request)
  }), [])
  const resolveConfirm = useCallback((value) => {
    setConfirmRequest(null)
    confirmResolve.current?.(value)
    confirmResolve.current = null
  }, [])
  const askText = useCallback((request) => new Promise((resolve) => {
    promptResolve.current = resolve
    setPromptRequest(request)
  }), [])
  const resolvePrompt = useCallback((value) => {
    setPromptRequest(null)
    promptResolve.current?.(value)
    promptResolve.current = null
  }, [])

  /* ------------------------------------------------------------ 派生数据 */
  const account = useMemo(() => accounts.find((item) => item.id === selectedId) || null, [accounts, selectedId])
  const enabledIds = useMemo(() => new Set(enabledTasks.map((task) => task.id)), [enabledTasks])
  const logs = logsByAccount[selectedId] || []

  const dirtyKeys = useMemo(() => {
    const keys = new Set()
    if (!config || !baseline) return keys
    for (const [group, fields] of Object.entries(config.groups || {})) {
      const reference = baseline.groups?.[group] || []
      for (const field of fields) {
        const original = reference.find((item) => item.name === field.name)
        if (!original || !same(original.value, field.value)) keys.add(fieldKey(group, field.name))
      }
    }
    return keys
  }, [config, baseline])

  const deviceSummary = useMemo(() => {
    const groups = deviceConfig?.groups?.device || []
    const find = (name) => groups.find((field) => field.name === name)?.value
    const handle = String(find('handle') ?? '').trim()
    const serial = String(find('serial') ?? '').trim()
    const emulator = String(find('emulatorinfo_name') ?? '').trim()
    if (handle) {
      const matched = windows.find((item) => String(item.handle) === handle)
      return { bound: true, explicit: true, label: matched ? `窗口「${matched.title}」` : `窗口句柄 ${handle}` }
    }
    if (serial && serial !== 'auto') return { bound: true, explicit: true, label: `设备 ${serial}` }
    if (emulator) return { bound: true, explicit: true, label: `模拟器 ${emulator}` }
    // serial=auto 只是“让 Core 自己找”，不算真正绑定某个窗口——常见连不上就卡在这（正是用户的原始问题）。
    if (serial === 'auto') return { bound: true, explicit: false, label: '设备：自动检测' }
    if (!deviceConfig) return { bound: false, explicit: false, label: '设备信息读取中' }
    return { bound: false, explicit: false, label: '未绑定设备' }
  }, [deviceConfig, windows])

  /* ------------------------------------------------------------ 数据加载 */
  const appendLogs = useCallback((accountId, items) => {
    if (!items?.length) return
    setLogsByAccount((current) => ({ ...current, [accountId]: [...(current[accountId] || []), ...items].slice(-LOG_LIMIT) }))
  }, [])

  const refreshAccounts = useCallback(async () => {
    const list = await api.accounts()
    setAccounts(list)
    return list
  }, [])

  // silent=true 用于启动时的静默预取：模拟器还没开时不该弹警告打扰用户，
  // 只有用户主动点「刷新窗口」才提示结果。
  const refreshWindows = useCallback(async (silent = false) => {
    setWindowsLoading(true)
    try {
      const list = await api.windows()
      setWindows(list)
      if (!list.length && !silent) notify('没有读到窗口。请先打开模拟器/游戏窗口，再点刷新。', 'warn')
      return list
    } catch (error) {
      if (!silent) notify(`读取窗口失败：${error.message}`, 'error')
      return []
    } finally {
      setWindowsLoading(false)
    }
  }, [notify])

  // 「一键扫描绑定」：打开弹窗并立刻静默扫描一次。
  const openWindowBind = useCallback(() => {
    setBinding(true)
    refreshWindows(true).catch(() => {})
  }, [refreshWindows])

  // 选中窗口 → 写 device.handle（+ 尽力识别 emulatorinfo_type，只写 Core 真实枚举里的合法值）→ 保存 → 刷新设备摘要。
  // 纯前端 + 现有 /windows 与配置保存接口，不改上游 Core（handoff/18）。
  const bindWindow = useCallback(async (win) => {
    if (!selectedId || !win) return
    const accountId = selectedId
    setBinding(false)
    try {
      const cfg = await api.taskConfig(accountId, 'Script')
      const device = cfg?.groups?.device || []
      const handleField = device.find((f) => f.name === 'handle')
      const typeField = device.find((f) => f.name === 'emulatorinfo_type')
      const fields = [{ group: 'device', name: 'handle', value: String(win.handle), type: handleField?.type || 'string' }]
      const inferred = typeField ? inferEmulatorType(win, typeField.options || []) : null
      if (inferred && String(typeField.value) !== inferred) {
        fields.push({ group: 'device', name: 'emulatorinfo_type', value: inferred, type: typeField.type || 'enum' })
      }
      await api.saveTaskConfig(accountId, 'Script', fields)
      if (selectedIdRef.current === accountId) {
        const fresh = await api.taskConfig(accountId, 'Script').catch(() => null)
        if (fresh) setDeviceConfig(fresh)
      }
      notify(`已绑定「${win.title || win.handle}」（句柄 ${win.handle}${inferred ? ` · ${inferred}` : ''}），已保存到 ${accountId}`, 'success')
    } catch (error) {
      notify(`绑定失败：${error.message}`, 'error')
    }
  }, [selectedId, notify])

  const loadAccountData = useCallback(async (accountId) => {
    if (!accountId) return
    const ticket = ++loadTicket.current
    try {
      const [tasks, recent, sched, script] = await Promise.all([
        api.accountTasks(accountId),
        api.logs(accountId, 200),
        api.schedule(accountId).catch(() => null),
        api.taskConfig(accountId, 'Script').catch(() => null),
      ])
      if (ticket !== loadTicket.current) return
      setEnabledTasks(tasks)
      setSchedule(sched)
      setDeviceConfig(script)
      setLogsByAccount((current) => ({ ...current, [accountId]: recent.slice(-LOG_LIMIT) }))
    } catch (error) {
      if (ticket === loadTicket.current) notify(error.message, 'error')
    }
  }, [notify])

  const loadConfig = useCallback(async (accountId, taskId) => {
    const ticket = ++configTicket.current
    if (!accountId || !taskId) { setConfig(null); setBaseline(null); return }
    try {
      const data = await api.taskConfig(accountId, taskId)
      if (ticket !== configTicket.current) return
      setConfig(data)
      setBaseline(clone(data))
    } catch (error) {
      if (ticket !== configTicket.current) return
      setConfig(null)
      setBaseline(null)
      notify(`读取「${taskLabel({ id: taskId })}」配置失败：${error.message}`, 'error')
    }
  }, [notify])

  const loadTemplates = useCallback(async () => {
    // api.templates() 约定：Bridge 有该接口 → 返回数组（哪怕空）；没有 → 返回 null 哨兵；网络异常 → 抛错。
    // 用 null 而非空数组来区分「接口缺失」与「接口存在但为空」，否则会把 templateStorage 误判为 bridge，
    // 导致本地模板不落盘、刷新即丢（见 handoff/17 F3 及 api.js 的 templates()）。
    const remote = await api.templates().catch(() => null)
    if (remote !== null) {
      setTemplates(remote)
      setTemplateStorage('bridge')   // Bridge 支持模板：以它为准，即使为空
      return
    }
    // Bridge 没有 /templates（或彻底连不上）：退回本地存储，键名与旧版一致，模板不会丢。
    const local = readJSON(KEYS.templates, [])
    setTemplates(Array.isArray(local) ? local : [])
    setTemplateStorage('local')
  }, [])

  /* --------------------------------------------------------------- 启动 */
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [status, list, menu] = await Promise.all([api.health(), api.accounts(), api.catalog()])
        if (cancelled) return
        setHealth(status)
        setAccounts(list)
        setCatalog(menu)
        setSelectedId((current) => (current && list.some((item) => item.id === current) ? current : list[0]?.id || ''))
        setBootError('')
      } catch (error) {
        if (!cancelled) setBootError(error.message)
      } finally {
        if (!cancelled) setBooted(true)
      }
    })()
    loadTemplates()
    refreshWindows(true).catch(() => {})
    return () => { cancelled = true }
  }, [loadTemplates, refreshWindows, setSelectedId])

  useEffect(() => {
    if (!selectedId) return
    loadAccountData(selectedId)
  }, [selectedId, loadAccountData])

  useEffect(() => {
    if (!selectedId || !selectedTaskId) { setConfig(null); setBaseline(null); return }
    loadConfig(selectedId, selectedTaskId)
  }, [selectedId, selectedTaskId, loadConfig])

  // 健康状态轮询：Core 掉线时要能立刻在界面上看到。
  // 另外承担“先开界面、后开 Core”的自愈：启动时那次 accounts/catalog 拉取会失败并留下错误横幅，
  // 这里在 Bridge+Core 恢复且当时启动出过错（或目录为空）时补拉一次并清横幅，
  // 避免一直卡在空界面必须手动刷新（handoff/17 F1）。
  useEffect(() => {
    const timer = window.setInterval(() => {
      api.health()
        .then((status) => {
          setHealth(status)
          if (status.bridge === 'ok' && status.core === 'ok' && (bootError || !catalog.length)) {
            Promise.all([api.accounts(), api.catalog()]).then(([list, menu]) => {
              setAccounts(list)
              setCatalog(menu)
              setBootError('')
              setSelectedId((current) => (current && list.some((item) => item.id === current) ? current : list[0]?.id || ''))
            }).catch(() => {})
          }
        })
        // Bridge 进程死了时 Core 状态也无从得知，别再显示“Core 在线”（handoff/17 F6）。
        .catch(() => setHealth((current) => ({ ...current, bridge: 'offline', core: 'offline' })))
    }, 15000)
    return () => window.clearInterval(timer)
  }, [bootError, catalog.length, setSelectedId])

  /* -------------------------------------------------------- 事件 WebSocket */
  useEffect(() => {
    const stream = createEventStream({
      onStatus: setEventStatus,
      onEvent: (event) => {
        const target = event.accountId
        if (event.type === 'log.appended' && target && event.payload?.log) {
          appendLogs(target, [event.payload.log])
        }
        if (event.type === 'schedule.updated' && target === selectedIdRef.current) {
          setSchedule(event.payload?.schedule || null)
        }
        if (target && ['task.started', 'task.stopped', 'task.state', 'account.connected', 'account.disconnected'].includes(event.type)) {
          setAccounts((current) => current.map((item) => {
            if (item.id !== target) return item
            const patch = {}
            if (event.payload?.state) { patch.state = event.payload.state; patch.state_label = event.payload.stateLabel || item.state_label }
            if (event.type === 'task.started') { patch.state = patch.state || 'running'; patch.state_label = patch.state_label || '运行中' }
            if (event.type === 'task.stopped') { patch.state = patch.state || 'offline'; patch.state_label = patch.state_label || '已停止' }
            if (event.type === 'account.connected') patch.connected = true
            if (event.type === 'account.disconnected') patch.connected = false
            return { ...item, ...patch }
          }))
        }
        if (event.type === 'account.created' || event.type === 'account.deleted') refreshAccounts().catch(() => {})
        if (event.type === 'bridge.ready') {
          // Bridge 重启后事件序号会归零，必须重新走一次 REST 而不是只靠事件补状态。
          setHealth((current) => ({ ...current, bridge: 'ok' }))
          refreshAccounts().catch(() => {})
          // 目录也要补：Bridge 曾在 Core 未就绪时启动过，catalog 可能还是空的（handoff/17 F1）。
          api.catalog().then((menu) => { if (menu?.length) { setCatalog(menu); setBootError('') } }).catch(() => {})
          if (selectedIdRef.current) loadAccountData(selectedIdRef.current)
        }
      },
    })
    streamRef.current = stream
    return () => stream.close()
  }, [appendLogs, refreshAccounts, loadAccountData])

  /* ------------------------------------------------------ 未保存改动守卫 */
  const guard = useCallback(async (what) => {
    if (!dirtyKeys.size) return true
    const ok = await ask({
      title: '还有未保存的改动',
      body: <p>「{taskLabel({ id: config?.task_id, title: config?.title })}」有 {dirtyKeys.size} 项改动没有保存。{what}后这些改动会丢失。</p>,
      confirmText: '丢弃改动并继续',
      tone: 'danger',
    })
    return ok
  }, [ask, dirtyKeys.size, config])

  useEffect(() => {
    const handler = (event) => {
      if (!dirtyKeys.size) return undefined
      event.preventDefault()
      event.returnValue = ''
      return ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirtyKeys.size])

  /* ------------------------------------------------------------ 交互动作 */
  const selectAccount = useCallback(async (id) => {
    if (id === selectedId) return
    if (!(await guard('切换账号'))) return
    setSelectedId(id)
    setSchedule(null)
    setDeviceConfig(null)
    setEnabledTasks([])
    setConfig(null)
    setBaseline(null)
  }, [guard, selectedId, setSelectedId])

  const selectTask = useCallback(async (taskId) => {
    if (taskId === selectedTaskId) return
    if (!(await guard('切换任务'))) return
    setSelectedTaskId(taskId)
  }, [guard, selectedTaskId])

  const changeView = useCallback(async (next) => {
    if (next === view) return
    if (view === 'tasks' && !(await guard('离开任务页'))) return
    setView(next)
  }, [guard, view, setView])

  const openTask = useCallback(async (taskId) => {
    if (view !== 'tasks' && !(await guard('离开当前页'))) return
    setSelectedTaskId(taskId)
    setView('tasks')
  }, [guard, view, setView])

  const runAction = useCallback(async (action) => {
    if (!selectedId) return
    if (action === 'stop' && account?.state === 'running') {
      const ok = await ask({
        title: `停止 ${account.name}？`,
        body: <p>会向 Core 发送停止命令，当前正在执行的任务会被中断。其他账号不受影响。</p>,
        confirmText: '停止',
        tone: 'danger',
      })
      if (!ok) return
    }
    setBusyAction(action)
    try {
      await api.action(selectedId, action)
      notify({ start: '已发送启动命令', stop: '已发送停止命令', restart: '已发送重启命令', refresh: '已请求刷新状态' }[action] || '命令已发送')
      const accountId = selectedId
      window.setTimeout(() => {
        refreshAccounts().catch(() => {})
        // 600ms 后用户可能已切换账号：带 accountId + selectedIdRef 守卫，别把别的账号的调度写进来（handoff/17 F2）。
        api.schedule(accountId).then((s) => { if (s && selectedIdRef.current === accountId) setSchedule(s) }).catch(() => {})
      }, 600)
    } catch (error) {
      notify(`操作失败：${error.message}`, 'error')
    } finally {
      setBusyAction('')
    }
  }, [account, ask, notify, refreshAccounts, selectedId])

  const toggleTask = useCallback(async (task, enabled) => {
    if (!selectedId || !task) return
    const accountId = selectedId
    // 乐观更新：开关立刻翻转、计数立刻变，不等真实 Core 的往返（OCR/ADB 一个来回可能 1~3 秒，
    // 等它会显得“发木/没反应”）。写失败再回滚到服务器真实状态（handoff/18）。
    setEnabledTasks((cur) => {
      const others = cur.filter((t) => t.id !== task.id)
      return enabled
        ? [...others, { id: task.id, title: task.title || taskLabel(task), category: task.category, enabled: true, next_run: null, available: true }]
        : others
    })
    try {
      await api.setTaskEnabled(accountId, task.id, enabled)
    } catch (error) {
      notify(`操作失败：${error.message}`, 'error')
      api.accountTasks(accountId).then((t) => { if (selectedIdRef.current === accountId) setEnabledTasks(t) }).catch(() => {})
      return
    }
    notify(enabled
      ? `已为 ${account?.name || accountId} 启用「${taskLabel(task)}」`
      : `已停用「${taskLabel(task)}」`)
    // 后台对账：用服务器真实数据覆盖乐观值（next_run 等）；跨账号守卫（handoff/17 F2）。
    api.accountTasks(accountId).then((t) => { if (selectedIdRef.current === accountId) setEnabledTasks(t) }).catch(() => {})
    refreshAccounts().catch(() => {})
    if (config?.task_id === task.id && !dirtyKeys.size) loadConfig(accountId, task.id)
    api.schedule(accountId).then((s) => { if (s && selectedIdRef.current === accountId) setSchedule(s) }).catch(() => {})
  }, [account, config, dirtyKeys.size, loadConfig, notify, refreshAccounts, selectedId])

  const changeField = useCallback((group, name, value) => {
    setConfig((current) => {
      if (!current) return current
      return {
        ...current,
        groups: {
          ...current.groups,
          [group]: current.groups[group].map((field) => (field.name === name ? { ...field, value } : field)),
        },
      }
    })
  }, [])

  const saveConfig = useCallback(async () => {
    if (!config || !selectedId || !dirtyKeys.size) return
    const fields = []
    for (const [group, items] of Object.entries(config.groups || {})) {
      for (const field of items) {
        if (dirtyKeys.has(fieldKey(group, field.name))) {
          fields.push({ group, name: field.name, value: field.value, type: field.type })
        }
      }
    }
    setSaving(true)
    try {
      await api.saveTaskConfig(selectedId, config.task_id, fields)
      setBaseline(clone(config))
      notify(`已保存 ${fields.length} 项改动`, 'success')
      if (config.task_id === 'Script') setDeviceConfig(clone(config))
      if (fields.some((field) => field.group === 'scheduler')) {
        const accountId = selectedId
        api.accountTasks(accountId).then((t) => { if (selectedIdRef.current === accountId) setEnabledTasks(t) }).catch(() => {})
        api.schedule(accountId).then((s) => { if (s && selectedIdRef.current === accountId) setSchedule(s) }).catch(() => {})
      }
    } catch (error) {
      notify(`保存失败：${error.message}`, 'error')
    } finally {
      setSaving(false)
    }
  }, [config, dirtyKeys, notify, selectedId])

  const resetConfig = useCallback(() => {
    if (baseline) setConfig(clone(baseline))
  }, [baseline])

  useEffect(() => {
    const handler = (event) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
      event.preventDefault()
      saveConfig()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [saveConfig])

  /* ------------------------------------------------------------ 账号管理 */
  const addAccount = useCallback(async () => {
    const name = await askText({
      title: '新建账号 / 窗口',
      body: '每个账号对应 OAS 的一个配置文件，任务、参数和日志都相互独立。留空则由 Core 自动命名。',
      placeholder: '例如 oas2',
      confirmText: '创建',
    })
    if (name === null) return
    try {
      const created = await api.createAccount({ name: name.trim() || null })
      await refreshAccounts()
      setSelectedId(created.id)
      notify(`已创建账号 ${created.id}，记得先绑定设备`, 'success')
      setView('overview')
    } catch (error) {
      notify(`创建失败：${error.message}`, 'error')
    }
  }, [askText, notify, refreshAccounts, setSelectedId, setView])

  const renameAccount = useCallback(async (target = account) => {
    if (!target) return
    const name = await askText({
      title: `重命名 ${target.name}`,
      body: '这会重命名 Core 里的配置文件。运行中的任务会先被停止。',
      initial: target.name,
      placeholder: '新的配置名',
      confirmText: '重命名',
    })
    if (!name || name.trim() === target.id) return
    try {
      const updated = await api.patchAccount(target.id, { name: name.trim() })
      await refreshAccounts()
      setSelectedId(updated.id || name.trim())
      notify('账号已重命名', 'success')
    } catch (error) {
      notify(`重命名失败：${error.message}`, 'error')
    }
  }, [account, askText, notify, refreshAccounts, setSelectedId])

  const deleteAccount = useCallback(async (target = account) => {
    if (!target) return
    const ok = await ask({
      title: `删除账号 ${target.name}？`,
      body: <p>会删除 Core 中的 <code>{target.id}.json</code> 配置文件，这一步<strong>不可撤销</strong>。删除前请确认已经备份。</p>,
      confirmText: '确认删除',
      tone: 'danger',
    })
    if (!ok) return
    try {
      await api.deleteAccount(target.id)
      const list = await refreshAccounts()
      setSelectedId(list[0]?.id || '')
      notify(`已删除账号 ${target.id}`, 'success')
      setView('overview')
    } catch (error) {
      notify(`删除失败：${error.message}`, 'error')
    }
  }, [account, ask, notify, refreshAccounts, setSelectedId, setView])

  /* -------------------------------------------------------------- 模板 */
  const persistTemplates = useCallback(async (next, changed, removedId) => {
    setTemplates(next)
    if (templateStorage === 'bridge') {
      try {
        if (removedId) await api.deleteTemplate(removedId)
        else if (changed) await api.saveTemplate(changed)
        return
      } catch {
        setTemplateStorage('local')
      }
    }
    writeJSON(KEYS.templates, next)
  }, [templateStorage])

  const saveTemplate = useCallback((name) => {
    if (!config) return
    const label = taskLabel({ id: config.task_id, title: config.title })
    const template = {
      id: makeId('tpl'),
      name: (name || '').trim() || `${label} 模板 ${templates.filter((item) => item.task_id === config.task_id).length + 1}`,
      task_id: config.task_id,
      task_title: label,
      created_at: new Date().toISOString(),
      groups: Object.fromEntries(Object.entries(config.groups).map(([group, fields]) => [
        group,
        Object.fromEntries(fields.map((field) => [field.name, { value: clone(field.value), type: field.type }])),
      ])),
    }
    persistTemplates([template, ...templates], template)
    notify(`已保存模板「${template.name}」`, 'success')
  }, [config, notify, persistTemplates, templates])

  const applyTemplate = useCallback((templateId) => {
    const template = templates.find((item) => item.id === templateId)
    if (!template || !config) return
    let applied = 0
    setConfig((current) => ({
      ...current,
      groups: Object.fromEntries(Object.entries(current.groups).map(([group, fields]) => [
        group,
        fields.map((field) => {
          const saved = template.groups?.[group]?.[field.name]
          if (!saved) return field
          // 调度时间不套用：套过来的 next_run 会打乱目标账号的排期。
          if (group === 'scheduler' && field.name === 'next_run') return field
          applied += 1
          return { ...field, value: clone(saved.value) }
        }),
      ])),
    }))
    notify(`已套用模板「${template.name}」的 ${applied} 项参数，确认后点保存才会写入 Core`, 'success')
  }, [config, notify, templates])

  const deleteTemplate = useCallback((templateId) => {
    persistTemplates(templates.filter((item) => item.id !== templateId), null, templateId)
    notify('模板已删除')
  }, [notify, persistTemplates, templates])

  /* --------------------------------------------------------------- 日志 */
  const clearLogs = useCallback(() => {
    setLogsByAccount((current) => ({ ...current, [selectedId]: [] }))
  }, [selectedId])

  const exportLogs = useCallback(() => {
    const text = logs.map((log) => `${log.timestamp}\t${log.level}\t${log.message}`).join('\n')
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selectedId || 'oas'}-logs.txt`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }, [logs, selectedId])

  /* -------------------------------------------------------------- 渲染 */
  const filteredAccounts = accounts.filter((item) =>
    `${item.name} ${item.id} ${item.device_label || ''}`.toLowerCase().includes(accountFilter.trim().toLowerCase()))
  const coreOnline = health.core === 'ok'
  // 演示/试用栈（mock bridge）会把 /health 标 mock:true 或用 mock:// 的 core_url；识别后弹醒目横幅，
  // 免得用户把模拟的“Core 在线”当成真后端而误点启动。
  const simulated = health.mock === true || /^mock:/i.test(String(health.core_url || ''))

  if (!booted) {
    return <div className="boot"><div className="boot-mark">OAS</div><p>正在连接控制中心…</p></div>
  }

  return (
    <div className={`app ${collapsed ? 'rail' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">OAS</div>
          {!collapsed ? (
            <div className="brand-text">
              <strong>控制中心</strong>
              <span className={coreOnline ? 'ok' : 'bad'}>
                <StateDot state={coreOnline ? 'running' : 'warning'} />
                {coreOnline ? 'Core 在线' : 'Core 未连接'}
              </span>
            </div>
          ) : null}
          <button
            type="button" className="icon-btn collapse"
            title={collapsed ? '展开账号栏' : '收起账号栏'}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? '»' : '«'}
          </button>
        </div>

        {!collapsed ? (
          <div className="sidebar-tools">
            <Search value={accountFilter} onChange={setAccountFilter} placeholder="搜索账号" />
          </div>
        ) : null}

        <div className="account-list">
          {filteredAccounts.map((item) => (
            <div
              key={item.id}
              role="button"
              tabIndex={0}
              className={`account ${item.id === selectedId ? 'active' : ''}`}
              onClick={() => selectAccount(item.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectAccount(item.id) } }}
              title={`${item.name} · ${item.device_label || '未配置设备'}`}
            >
              <Avatar name={item.name} tone={item.avatar} />
              {!collapsed ? (
                <>
                  <span className="account-text">
                    <strong>{item.name}</strong>
                    <small>{item.device_label || '未配置设备'}</small>
                    <span className="account-state">
                      <StateDot state={item.state} connected={item.connected} />
                      {item.state_label || '已停止'} · {item.selected_count ?? 0} 项任务
                    </span>
                  </span>
                  <AccountMenu account={item} onRename={() => renameAccount(item)} onDelete={() => deleteAccount(item)} />
                </>
              ) : <StateDot state={item.state} connected={item.connected} />}
            </div>
          ))}
          {!filteredAccounts.length ? (
            <div className="sidebar-empty">{accounts.length ? '没有匹配的账号' : '还没有账号'}</div>
          ) : null}
        </div>

        <button type="button" className="btn ghost add-account" onClick={addAccount} title="新建账号 / 窗口">
          {collapsed ? '＋' : '＋ 新建账号 / 窗口'}
        </button>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-account">
            {account ? (
              <>
                <Avatar name={account.name} tone={account.avatar} />
                <div>
                  <h1>{account.name}</h1>
                  <p>
                    <StatePill state={account.state} label={account.state_label} connected={account.connected} />
                    <span className="sep">·</span>
                    {enabledTasks.length} 项任务
                    <span className="sep">·</span>
                    {deviceSummary.label}
                    {!deviceSummary.explicit ? (
                      <button type="button" className="btn ghost xs bind-inline" onClick={openWindowBind} title="扫描并绑定模拟器窗口">绑定窗口</button>
                    ) : null}
                  </p>
                </div>
              </>
            ) : <h1>OAS 控制中心</h1>}
          </div>

          <nav className="tabs" role="tablist">
            {VIEWS.map((item) => (
              <button
                key={item.key}
                role="tab"
                aria-selected={view === item.key}
                className={view === item.key ? 'on' : ''}
                onClick={() => changeView(item.key)}
              >
                {item.label}
                {item.key === 'tasks' && dirtyKeys.size ? <em className="tab-badge">{dirtyKeys.size}</em> : null}
                {item.key === 'logs' && logs.length ? <em className="tab-count">{logs.length}</em> : null}
              </button>
            ))}
          </nav>

          <div className="topbar-actions">
            {account?.state === 'running' ? (
              <button className="btn danger" disabled={!!busyAction} onClick={() => runAction('stop')}>
                {busyAction === 'stop' ? '停止中…' : '■ 停止'}
              </button>
            ) : (
              <button className="btn primary" disabled={!account || !!busyAction} onClick={() => runAction('start')}>
                {busyAction === 'start' ? '启动中…' : '▶ 启动'}
              </button>
            )}
            <button className="icon-btn" title="刷新状态" disabled={!account || !!busyAction} onClick={() => runAction('refresh')}>⟳</button>
          </div>
        </header>

        {bootError ? (
          <Banner tone="bad" action={<button type="button" className="btn ghost sm" onClick={() => window.location.reload()}>重试</button>}>
            无法连接 Bridge（{BRIDGE_ORIGIN}）：{bootError}
          </Banner>
        ) : null}
        {!bootError && !coreOnline ? (
          <Banner tone="warn">
            OAS Core 未连接，任务无法启动。请先按原项目方式启动 <code>server.py</code>，Bridge 会自动恢复。
          </Banner>
        ) : null}
        {!onboarded && coreOnline ? (
          <Banner
            tone="info"
            action={<button type="button" className="btn ghost sm" onClick={() => setOnboarded(true)}>知道了</button>}
          >
            用法：左边选账号 → 「任务」页点任务名看配置、用右边开关启用 → 回「概览」通过启动前检查 → 点启动。
          </Banner>
        ) : null}
        {simulated ? (
          <Banner tone="warn">
            演示模式：当前连的是模拟数据（mock bridge），「Core 在线」是模拟的，不会控制任何设备、也不会读写真实配置。
          </Banner>
        ) : null}

        <div className="content">
          {view === 'overview' ? (
            <OverviewView
              account={account}
              tasks={enabledTasks}
              schedule={schedule}
              deviceSummary={deviceSummary}
              logs={logs}
              coreOnline={coreOnline}
              eventStatus={eventStatus}
              busyAction={busyAction}
              onGoTasks={() => changeView('tasks')}
              onOpenTask={openTask}
              onToggleTask={toggleTask}
              onAction={runAction}
              onScanBind={openWindowBind}
            />
          ) : null}

          {view === 'tasks' ? (
            <TasksView
              account={account}
              catalog={catalog}
              enabledIds={enabledIds}
              selectedTaskId={selectedTaskId}
              onSelectTask={selectTask}
              onToggleTask={toggleTask}
              config={config}
              dirtyKeys={dirtyKeys}
              onFieldChange={changeField}
              onSave={saveConfig}
              onResetAll={resetConfig}
              saving={saving}
              windows={windows}
              windowsLoading={windowsLoading}
              onRefreshWindows={refreshWindows}
              templates={templates}
              onSaveTemplate={saveTemplate}
              onApplyTemplate={applyTemplate}
              onDeleteTemplate={deleteTemplate}
            />
          ) : null}

          {view === 'logs' ? (
            <LogsView
              account={account}
              logs={logs}
              levels={logLevels}
              onLevels={setLogLevels}
              onClear={clearLogs}
              onExport={exportLogs}
            />
          ) : null}

          {view === 'settings' ? (
            <SettingsView
              health={health}
              bridgeOrigin={BRIDGE_ORIGIN}
              eventStatus={eventStatus}
              theme={theme}
              onTheme={setTheme}
              density={density}
              onDensity={setDensity}
              templates={templates}
              templateStorage={templateStorage}
              onDeleteTemplate={deleteTemplate}
              account={account}
              onRenameAccount={() => renameAccount(account)}
              onDeleteAccount={() => deleteAccount(account)}
              onReconnect={() => streamRef.current?.reconnectNow()}
            />
          ) : null}
        </div>

        <footer className="statusbar">
          <span><StateDot state={coreOnline ? 'running' : 'warning'} />Core {coreOnline ? '在线' : '未连接'}</span>
          <span>
            <StateDot state={eventStatus === 'online' ? 'running' : eventStatus === 'offline' ? 'warning' : 'updating'} />
            实时通道 {{ online: '已连接', connecting: '连接中', reconnecting: '重连中', offline: '已断开' }[eventStatus]}
          </span>
          <span className="spacer" />
          {dirtyKeys.size ? <span className="warn-text">{dirtyKeys.size} 项配置未保存（Ctrl+S 保存）</span> : null}
          <span className="muted">{BRIDGE_ORIGIN}</span>
        </footer>
      </main>

      <Toasts items={toasts} onDismiss={dismissToast} />
      <Confirm request={confirmRequest} onResolve={resolveConfirm} />
      <Prompt request={promptRequest} onResolve={resolvePrompt} />
      <WindowBindDialog
        open={binding}
        windows={windows}
        loading={windowsLoading}
        onRefresh={() => refreshWindows()}
        onPick={bindWindow}
        onClose={() => setBinding(false)}
      />
    </div>
  )
}
