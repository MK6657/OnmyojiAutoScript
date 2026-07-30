import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { categoryLabel, fieldDescription, fieldLabel, groupLabel, optionLabel, taskLabel } from './locale.js'

const BRIDGE_ORIGIN = import.meta.env.VITE_BRIDGE_URL || window.location.origin
const API_BASE = `${BRIDGE_ORIGIN.replace(/\/$/, '')}/api/v1`
const WS_BASE = API_BASE.replace(/^http/, 'ws')

const listPayload = (value, key) => Array.isArray(value) ? value : (Array.isArray(value?.[key]) ? value[key] : [])
const TEMPLATE_STORAGE_KEY = 'oas-control-center.templates.v1'
const TASK_ORDER_STORAGE_KEY = 'oas-control-center.task-order.v1'
const clone = (value) => JSON.parse(JSON.stringify(value))
const makeId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
const groupHints = {
  scheduler: '控制任务是否启用、运行时间和优先级',
  device: '绑定模拟器设备、游戏客户端和窗口',
  optimization: '调整截图频率、间隔和任务队列行为',
  evo_zone_config: '设置队伍身份、挑战方式、时间和次数',
  invite_config: '设置邀请人数、好友和等待方式',
  general_battle_config: '设置队伍、预设阵容和战斗行为',
}
const groupHint = (group) => groupHints[group] || '调整本任务的相关运行参数'

function readTemplates() {
  try {
    const value = JSON.parse(window.localStorage.getItem(TEMPLATE_STORAGE_KEY) || '[]')
    return Array.isArray(value) ? value : []
  } catch {
    return []
  }
}

function writeTemplates(value) {
  window.localStorage.setItem(TEMPLATE_STORAGE_KEY, JSON.stringify(value))
}

function readTaskOrders() {
  try {
    const value = JSON.parse(window.localStorage.getItem(TASK_ORDER_STORAGE_KEY) || '{}')
    return value && typeof value === 'object' ? value : {}
  } catch {
    return {}
  }
}

function writeTaskOrders(value) {
  window.localStorage.setItem(TASK_ORDER_STORAGE_KEY, JSON.stringify(value))
}

async function request(path, options = {}, attempt = 0) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (response.status >= 500 && attempt < 2) {
    await new Promise((resolve) => window.setTimeout(resolve, 180 * (attempt + 1)))
    return request(path, options, attempt + 1)
  }
  const contentType = response.headers.get('content-type') || ''
  const body = contentType.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) throw new Error(body?.detail || body?.message || `请求失败（${response.status}）`)
  return body
}

function StatusDot({ state }) {
  return <span className={`status-dot ${state || 'offline'}`} />
}

function App() {
  const [accounts, setAccounts] = useState([])
  const [catalog, setCatalog] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [selectedTasks, setSelectedTasks] = useState([])
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [taskConfig, setTaskConfig] = useState(null)
  const [logs, setLogs] = useState([])
  const [accountFilter, setAccountFilter] = useState('')
  const [taskFilter, setTaskFilter] = useState('')
  const [health, setHealth] = useState({ bridge: 'connecting', core: 'connecting' })
  const [busy, setBusy] = useState(false)
  const [busyAction, setBusyAction] = useState('')
  const [toast, setToast] = useState('')
  const [windows, setWindows] = useState([])
  const [windowsLoading, setWindowsLoading] = useState(false)
  const [templates, setTemplates] = useState(readTemplates)
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [templateNameDraft, setTemplateNameDraft] = useState('')
  const [taskOrders, setTaskOrders] = useState(readTaskOrders)
  const socketRef = useRef(null)
  const selectedRequestRef = useRef(0)
  const configRequestRef = useRef(0)

  const currentAccount = accounts.find((item) => item.id === selectedId) || null
  const filteredAccounts = accounts.filter((item) => `${item.name} ${item.id} ${item.device_label}`.toLowerCase().includes(accountFilter.toLowerCase()))
  const filteredCatalog = useMemo(() => {
    const filter = taskFilter.toLowerCase()
    return catalog.filter((task) => `${taskLabel(task)} ${task.title} ${task.id} ${categoryLabel(task.category)}`.toLowerCase().includes(filter))
  }, [catalog, taskFilter])
  const catalogGroups = useMemo(() => filteredCatalog.reduce((groups, task) => {
    groups[task.category] ||= []
    groups[task.category].push(task)
    return groups
  }, {}), [filteredCatalog])
  const currentTaskTemplates = useMemo(
    () => templates.filter((template) => template.task_id === taskConfig?.task_id),
    [templates, taskConfig?.task_id],
  )
  const activeTemplateId = currentTaskTemplates.some((template) => template.id === selectedTemplateId) ? selectedTemplateId : ''
  const orderedSelectedTasks = useMemo(() => {
    const savedOrder = taskOrders[selectedId] || []
    const ranks = new Map(savedOrder.map((taskId, index) => [taskId, index]))
    return [...selectedTasks].sort((left, right) => {
      const leftRank = ranks.has(left.id) ? ranks.get(left.id) : selectedTasks.length + selectedTasks.indexOf(left)
      const rightRank = ranks.has(right.id) ? ranks.get(right.id) : selectedTasks.length + selectedTasks.indexOf(right)
      return leftRank - rightRank
    })
  }, [selectedId, selectedTasks, taskOrders])

  const showToast = useCallback((message) => {
    setToast(message)
    window.setTimeout(() => setToast(''), 2600)
  }, [])

  const refreshWindows = useCallback(async () => {
    setWindowsLoading(true)
    try {
      const data = listPayload(await request('/windows'), 'windows')
      setWindows(data)
      return data
    } finally {
      setWindowsLoading(false)
    }
  }, [])

  const refreshAccounts = useCallback(async (preserveSelection = true) => {
    const data = listPayload(await request('/accounts'), 'accounts')
    setAccounts(data)
    if (!preserveSelection || !data.some((item) => item.id === selectedId)) setSelectedId(data[0]?.id || '')
  }, [selectedId])

  const loadSelected = useCallback(async (accountId) => {
    if (!accountId) return
    const requestId = ++selectedRequestRef.current
    const [tasksBody, logsBody] = await Promise.all([
      request(`/accounts/${encodeURIComponent(accountId)}/tasks`),
      request(`/accounts/${encodeURIComponent(accountId)}/logs?limit=120`),
    ])
    if (requestId !== selectedRequestRef.current) return
    const tasks = listPayload(tasksBody, 'tasks')
    const accountLogs = listPayload(logsBody, 'logs')
    setSelectedTasks(tasks)
    setLogs(accountLogs)
    setSelectedTaskId((current) => tasks.some((task) => task.id === current) ? current : (tasks[0]?.id || ''))
    return tasks
  }, [])

  const loadConfig = useCallback(async (accountId, taskId) => {
    const requestId = ++configRequestRef.current
    if (!accountId || !taskId) { setTaskConfig(null); return }
    const config = await request(`/accounts/${encodeURIComponent(accountId)}/tasks/${encodeURIComponent(taskId)}/config`)
    if (requestId === configRequestRef.current) setTaskConfig(config)
  }, [])

  useEffect(() => {
    let cancelled = false
    Promise.all([request('/health'), request('/accounts'), request('/tasks/catalog')])
      .then(([status, accountData, catalogData]) => {
        if (cancelled) return
        setHealth(status)
        const normalizedAccounts = listPayload(accountData, 'accounts')
        const normalizedCatalog = listPayload(catalogData, 'tasks')
        setAccounts(normalizedAccounts)
        setCatalog(normalizedCatalog)
        setSelectedId((current) => current && normalizedAccounts.some((item) => item.id === current) ? current : (normalizedAccounts[0]?.id || ''))
      })
      .catch((error) => showToast(error.message))
    return () => { cancelled = true }
  }, [showToast])

  useEffect(() => {
    if (selectedId) loadSelected(selectedId).catch((error) => showToast(error.message))
  }, [selectedId, loadSelected, showToast])

  useEffect(() => {
    loadConfig(selectedId, selectedTaskId).catch((error) => showToast(error.message))
  }, [selectedId, selectedTaskId, loadConfig, showToast])

  useEffect(() => {
    if (taskConfig?.task_id !== 'Script') return
    refreshWindows().catch((error) => showToast(`读取窗口失败：${error.message}`))
  }, [taskConfig?.task_id, refreshWindows, showToast])

  useEffect(() => {
    const socket = new WebSocket(`${WS_BASE}/events`)
    socketRef.current = socket
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data)
        if (event.type === 'log.appended' && event.accountId === selectedId && event.payload?.log) {
          setLogs((current) => [...current, event.payload.log].slice(-120))
        }
        if (event.accountId) {
          setAccounts((current) => current.map((account) => account.id !== event.accountId ? account : {
            ...account,
            ...(event.type === 'task.started' ? { state: 'running', state_label: '运行中' } : {}),
            ...(event.type === 'task.stopped' ? { state: 'offline', state_label: '已停止' } : {}),
            ...(event.type === 'account.connected' ? { connected: true } : {}),
            ...(event.type === 'account.disconnected' ? { connected: false } : {}),
          }))
        }
      } catch { /* Ignore a malformed event; REST refresh remains available. */ }
    }
    socket.onerror = () => setHealth((current) => ({ ...current, bridge: 'offline' }))
    return () => socket.close()
  }, [selectedId])

  const runAction = async (action) => {
    if (!selectedId) return
    setBusy(true)
    setBusyAction(action)
    try {
      await request(`/accounts/${encodeURIComponent(selectedId)}/actions`, { method: 'POST', body: JSON.stringify({ action }) })
      showToast(action === 'start' ? '已发送启动命令' : action === 'stop' ? '已发送停止命令' : action === 'restart' ? '已发送重启命令' : '状态刷新中')
      window.setTimeout(() => refreshAccounts().catch(() => {}), 500)
    } catch (error) { showToast(`操作失败：${error.message}`) } finally { setBusy(false); setBusyAction('') }
  }

  const toggleTask = async (task, enabled) => {
    if (!selectedId || !task) return
    try {
      await request(`/accounts/${encodeURIComponent(selectedId)}/tasks/${encodeURIComponent(task.id)}/enabled?enabled=${enabled}`, { method: 'PUT' })
      const [nextTasks] = await Promise.all([loadSelected(selectedId), refreshAccounts()])
      setSelectedTaskId((current) => enabled ? task.id : current === task.id ? (nextTasks?.[0]?.id || '') : current)
      showToast(enabled ? `已为 ${currentAccount?.name || selectedId} 启用${taskLabel(task)}` : `已停用${taskLabel(task)}`)
    } catch (error) { showToast(error.message) }
  }

  const moveTask = (taskId, direction) => {
    const ids = orderedSelectedTasks.map((task) => task.id)
    const index = ids.indexOf(taskId)
    const target = index + direction
    if (index < 0 || target < 0 || target >= ids.length) return
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    const nextOrders = { ...taskOrders, [selectedId]: ids }
    setTaskOrders(nextOrders)
    writeTaskOrders(nextOrders)
  }

  const updateField = (group, name, value) => {
    setTaskConfig((current) => current && ({
      ...current,
      groups: {
        ...current.groups,
        [group]: current.groups[group].map((field) => field.name === name ? { ...field, value } : field),
      },
    }))
  }

  const saveConfig = async () => {
    if (!selectedId || !taskConfig) return
    const fields = Object.entries(taskConfig.groups).flatMap(([group, items]) => items.map((field) => ({ group, name: field.name, value: field.value, type: field.type })))
    try {
      await request(`/accounts/${encodeURIComponent(selectedId)}/tasks/${encodeURIComponent(taskConfig.task_id)}/config`, { method: 'PATCH', body: JSON.stringify({ fields }) })
      showToast('任务配置已保存')
    } catch (error) { showToast(error.message) }
  }

  const saveTemplate = () => {
    if (!taskConfig) return
    const defaultName = `${taskLabel({ id: taskConfig.task_id, title: taskConfig.title })}模板 ${currentTaskTemplates.length + 1}`
    const name = templateNameDraft.trim() || defaultName
    const template = {
      id: makeId(),
      name: name.trim(),
      task_id: taskConfig.task_id,
      task_title: taskLabel({ id: taskConfig.task_id, title: taskConfig.title }),
      created_at: new Date().toISOString(),
      groups: Object.fromEntries(Object.entries(taskConfig.groups).map(([group, fields]) => [
        group,
        Object.fromEntries(fields.map((field) => [field.name, { value: clone(field.value), type: field.type }])),
      ])),
    }
    const next = [template, ...templates]
    setTemplates(next)
    setSelectedTemplateId(template.id)
    setTemplateNameDraft('')
    writeTemplates(next)
    showToast(`已保存模板「${template.name}」`)
  }

  const applyTemplate = (templateId) => {
    const template = currentTaskTemplates.find((item) => item.id === templateId)
    if (!template || !taskConfig) return
    setTaskConfig((current) => ({
      ...current,
      groups: Object.fromEntries(Object.entries(current.groups).map(([group, fields]) => [
        group,
        fields.map((field) => template.groups[group]?.[field.name]
          ? { ...field, value: clone(template.groups[group][field.name].value) }
          : field),
      ])),
    }))
    showToast(`已应用模板「${template.name}」，确认无误后点击保存`)
  }

  const deleteTemplate = (templateId) => {
    const target = currentTaskTemplates.find((item) => item.id === templateId)
    if (!target) return
    const next = templates.filter((item) => item.id !== templateId)
    setTemplates(next)
    setSelectedTemplateId('')
    writeTemplates(next)
    showToast('模板已删除')
  }

  const addAccount = async () => {
    const name = window.prompt('新账号配置名（留空则自动生成）', '')
    if (name === null) return
    try {
      const account = await request('/accounts', { method: 'POST', body: JSON.stringify({ name: name.trim() || null }) })
      await refreshAccounts(false)
      setSelectedId(account.id)
      showToast(`已创建账号 ${account.id}`)
    } catch (error) { showToast(error.message) }
  }

  const clearLogs = () => setLogs([])

  return <div className="app-shell">
    <section className="accounts-panel">
      <div className="workspace-brand"><div className="brand-mark">O</div><div className="brand-copy"><strong>OAS 控制中心</strong><span>独立前端 · 本机模式</span></div><div className="workspace-health"><StatusDot state={health.core === 'ok' ? 'running' : 'offline'} /><span>{health.core === 'ok' ? 'Core 在线' : 'Core 未连接'}</span></div></div>
      <div className="panel-heading"><div><span className="eyebrow">账号工作区</span><h1>账号</h1></div><button className="square-button" onClick={addAccount} title="添加账号">＋</button></div>
      <label className="search-box"><span>⌕</span><input value={accountFilter} onChange={(event) => setAccountFilter(event.target.value)} placeholder="搜索账号" /></label>
      <div className="account-list">
        {filteredAccounts.map((account) => <button className={`account-card ${account.id === selectedId ? 'selected' : ''}`} key={account.id} onClick={() => setSelectedId(account.id)}>
          <span className={`avatar ${account.avatar || 'blue'}`}>{(account.name || account.id).slice(0, 1).toUpperCase()}</span>
          <span className="account-card-copy"><strong>{account.name}</strong><small>{account.device_label || account.id}</small><span className={`account-state ${account.state}`}><StatusDot state={account.state} />{account.state_label} · {account.selected_count} 项任务</span></span>
        </button>)}
        {!filteredAccounts.length && <div className="empty-state">没有匹配账号</div>}
      </div>
      <div className="account-extension-space"><strong>扩展位</strong><span>后续可放置插件或全局设置</span></div>
      <button className="add-account" onClick={addAccount}>＋ 添加账号 / 窗口</button>
    </section>

    <main className="main-panel">
      <header className="main-header">
        <div className="header-account"><span className={`avatar large ${currentAccount?.avatar || 'blue'}`}>{(currentAccount?.name || '—').slice(0, 1).toUpperCase()}</span><div><div className="title-line"><h2>{currentAccount?.name || '请选择账号'}</h2><span className="thread-badge"><i /> 独立线程</span></div><p>{currentAccount ? `${currentAccount.id} · ${currentAccount.device_label || '未配置设备'}` : 'Bridge 会把每个 OAS 配置隔离运行'}</p></div></div>
        <div className="header-actions"><button className="button primary" disabled={!currentAccount || busy} onClick={() => runAction('start')}>{busyAction === 'start' ? '启动中...' : '▶ 启动'}</button><button className="button" disabled={!currentAccount || busy} onClick={() => runAction('stop')}>{busyAction === 'stop' ? '停止中...' : '■ 停止'}</button><button className="button" disabled={!currentAccount || busy} onClick={() => runAction('restart')}>{busyAction === 'restart' ? '重启中...' : '↻ 重启'}</button><button className="icon-button" disabled={!currentAccount || busy} onClick={() => runAction('refresh')} title="刷新状态">⟳</button></div>
      </header>

      <div className="workspace-grid">
        <section className="task-catalog panel-card">
          <div className="section-heading"><div><span className="eyebrow">任务目录</span><h3>全部任务</h3></div><span className="counter">{filteredCatalog.length}</span></div>
          <label className="search-box compact"><span>⌕</span><input value={taskFilter} onChange={(event) => setTaskFilter(event.target.value)} placeholder="搜索任务" /></label>
          <div className="catalog-list">{Object.entries(catalogGroups).map(([category, tasks]) => <div className="catalog-group" key={category}><div className="group-title">{categoryLabel(category)}<span>{tasks.length}</span></div>{tasks.map((task) => { const enabled = selectedTasks.some((item) => item.id === task.id); const selected = selectedTaskId === task.id; return <div className={`catalog-row ${enabled ? 'enabled' : ''} ${selected ? 'selected' : ''}`} key={task.id} onClick={() => setSelectedTaskId(task.id)} title={`点击查看${taskLabel(task)}设置`}><span><strong>{taskLabel(task)}</strong><small className="internal-id">内部标识 · {task.id}</small></span><button className={`task-toggle ${enabled ? 'on' : ''}`} onClick={(event) => { event.stopPropagation(); toggleTask(task, !enabled) }} title={enabled ? '停用任务' : '启用任务'}>{enabled ? '✓' : '＋'}</button></div> })}</div>)}</div>
        </section>

        <section className="selected-tasks panel-card">
          <div className="section-heading"><div><span className="eyebrow">当前账号</span><h3>当前账号任务</h3></div><span className="counter green">{selectedTasks.length}</span></div>
          <div className="selected-list">{orderedSelectedTasks.map((task, index) => <div className={`selected-task ${task.id === selectedTaskId ? 'active' : ''}`} key={task.id}><button className="selected-task-main" onClick={() => setSelectedTaskId(task.id)}><span className="task-icon">✓</span><span className="selected-task-copy"><strong>{taskLabel(task)}</strong><small>{task.next_run ? `下次运行 ${task.next_run}` : '等待调度'}</small></span><span className="chevron">›</span></button><div className="task-actions"><button className="task-action" disabled={index === 0} onClick={() => moveTask(task.id, -1)} title="上移任务" aria-label={`上移${taskLabel(task)}`}>↑</button><button className="task-action" disabled={index === orderedSelectedTasks.length - 1} onClick={() => moveTask(task.id, 1)} title="下移任务" aria-label={`下移${taskLabel(task)}`}>↓</button><button className="task-action danger" onClick={() => toggleTask(task, false)} title="停用任务" aria-label={`停用${taskLabel(task)}`}>×</button></div></div>)}{!orderedSelectedTasks.length && <div className="empty-state inset">在左侧任务目录点击 ＋，为当前账号单独启用任务。</div>}</div>
        </section>

        <section className="settings panel-card">
          <div className="section-heading"><div><span className="eyebrow">配置表单</span><h3>任务设置</h3></div><button className="button save" disabled={!taskConfig} onClick={saveConfig}>保存</button></div>
          {taskConfig ? <div className="settings-content"><div className="settings-title"><div><strong>{taskLabel({ id: taskConfig.task_id, title: taskConfig.title })}</strong><span>仅对 {currentAccount?.name || selectedId} 生效</span></div><code title="用于与 OAS Core 对照的内部任务标识">内部标识 · {taskConfig.task_id}</code></div><div className="template-toolbar"><div className="template-copy"><strong>配置模板</strong><small>可在其他账号的同一任务中复用</small></div><select value={activeTemplateId} onChange={(event) => setSelectedTemplateId(event.target.value)} aria-label="选择配置模板"><option value="">选择模板</option>{currentTaskTemplates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</select><button className="button" disabled={!activeTemplateId} onClick={() => applyTemplate(activeTemplateId)}>应用</button><input className="template-name" value={templateNameDraft} onChange={(event) => setTemplateNameDraft(event.target.value)} placeholder="新模板名称（可选）" aria-label="新模板名称" /><button className="button" onClick={saveTemplate}>保存模板</button><button className="text-button danger" disabled={!activeTemplateId} onClick={() => deleteTemplate(activeTemplateId)}>删除</button></div>{Object.entries(taskConfig.groups).map(([group, fields]) => <details className="config-group" key={group} open><summary><span className="group-summary-copy"><strong>{groupLabel(group)}</strong><small>{groupHint(group)}</small></span><span className="group-count">{fields.length} 项设置</span></summary><div className="config-fields">{fields.map((field) => <FieldEditor key={`${group}.${field.name}`} field={field} onChange={(value) => updateField(group, field.name, value)} windows={windows} windowsLoading={windowsLoading} onRefreshWindows={refreshWindows} onNotify={showToast} />)}</div></details>)}</div> : <div className="empty-state inset">选择当前账号中的任务后，这里会显示它的独立配置。</div>}
        </section>

        <section className="logs panel-card">
          <div className="section-heading"><div><span className="eyebrow">实时输出</span><h3>关键日志</h3></div><button className="text-button" onClick={clearLogs}>清空</button></div>
          <div className="log-list">{logs.length ? logs.map((log, index) => <div className={`log-row ${log.level}`} key={`${log.timestamp}-${index}`}><time>{new Date(log.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time><span className="log-level">{log.level === 'error' ? '错' : log.level === 'warn' ? '警' : '讯'}</span><span>{log.message}</span></div>) : <div className="empty-state">启动账号后显示关键日志</div>}</div>
          <div className="log-foot"><span><StatusDot state={currentAccount?.state} />{currentAccount?.state_label || '未选择账号'}</span><span>{health.bridge === 'ok' || health.core === 'ok' ? '实时连接' : '等待 Bridge'}</span></div>
        </section>
      </div>
    </main>
    {toast && <div className="toast">{toast}</div>}
  </div>
}

function WindowField({ field, label, windows, windowsLoading, onRefreshWindows, onNotify, onChange }) {
  const currentValue = String(field.value ?? '')
  const [candidate, setCandidate] = useState(currentValue)

  useEffect(() => setCandidate(currentValue), [currentValue])

  const selectedWindow = windows.find((item) => String(item.handle) === candidate)
  const bindWindow = () => {
    onChange(candidate)
    onNotify(selectedWindow ? `已选择窗口「${selectedWindow.title}」，点击保存后生效` : `已设置窗口句柄 ${candidate}，点击保存后生效`)
  }
  const refreshWindowList = () => {
    onRefreshWindows().catch((error) => onNotify(`读取窗口失败：${error.message}`))
  }
  const clearWindow = () => {
    setCandidate('')
    onChange('')
    onNotify('已清除窗口绑定，点击保存后生效')
  }

  return <div className="field-row window-field"><span className="field-copy">{label}</span><div className="window-field-control"><select value={candidate} onChange={(event) => setCandidate(event.target.value)} aria-label="选择要绑定的窗口"><option value="">不绑定窗口</option>{candidate && !windows.some((item) => String(item.handle) === candidate) && <option value={candidate}>当前值 · {candidate}</option>}{windows.map((item) => <option key={item.handle} value={String(item.handle)}>{item.title} · HWND {item.handle}{item.process ? ` · ${item.process}` : ''}</option>)}</select><div className="window-actions"><button type="button" className="field-action" onClick={refreshWindowList} disabled={windowsLoading}>{windowsLoading ? '读取中...' : '刷新窗口'}</button><button type="button" className="field-action primary" onClick={bindWindow} disabled={!candidate || candidate === currentValue}>绑定</button><button type="button" className="field-action danger" onClick={clearWindow} disabled={!currentValue && !candidate}>清除</button></div><small className="window-status">{selectedWindow ? `当前选择：${selectedWindow.title} · HWND ${selectedWindow.handle}` : currentValue ? `当前值：${currentValue}` : '请先刷新并选择游戏或模拟器窗口'}</small></div></div>
}

function FieldEditor({ field, onChange, windows, windowsLoading, onRefreshWindows, onNotify }) {
  const type = field.type
  const value = field.value ?? ''
  const description = fieldDescription(field)
  const label = <span className="field-copy"><strong>{fieldLabel(field)}</strong>{description && <small>{description}</small>}</span>
  if (field.name === 'handle') return <WindowField field={field} label={label} windows={windows} windowsLoading={windowsLoading} onRefreshWindows={onRefreshWindows} onNotify={onNotify} onChange={onChange} />
  if (type === 'boolean') return <label className="field-row boolean-field">{label}<input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} /><i /></label>
  if (type === 'enum' || field.options?.length) return <label className="field-row">{label}<select value={String(value)} onChange={(event) => onChange(event.target.value)}>{field.options.map((option) => <option key={String(option)} value={String(option)}>{optionLabel(option)}</option>)}</select></label>
  if (type === 'date_time') return <label className="field-row">{label}<input type="datetime-local" value={String(value).replace(' ', 'T').slice(0, 16)} onChange={(event) => onChange(event.target.value)} /></label>
  return <label className="field-row">{label}<input type={type === 'integer' || type === 'number' ? 'number' : type === 'time' ? 'time' : 'text'} step={type === 'number' ? '0.1' : '1'} value={String(value)} onChange={(event) => onChange(type === 'integer' ? Number.parseInt(event.target.value || '0', 10) : type === 'number' ? Number.parseFloat(event.target.value || '0') : event.target.value)} /></label>
}

export default App
