/** 四个主视图：概览、任务、日志、设置。 */
import { useMemo, useState } from 'react'
import { categoryLabel, groupLabel, optionLabel, taskLabel } from './locale.js'
import { FieldRow, useFieldFilter, useOpenGroups } from './fields.jsx'
import { Avatar, Banner, Empty, Search, StateDot, StatePill } from './components.jsx'

const GROUP_HINTS = {
  scheduler: '控制这个任务是否参与调度、下一次运行时间、间隔和优先级',
  device: '绑定模拟器 / 游戏窗口，这一项配错会导致所有任务失败',
  error: '出错时如何处理：是否截图、是否推送通知',
  optimization: '截图频率、任务队列为空时的行为、调度规则',
  general_battle_config: '队伍、预设阵容与战斗过程行为',
  invite_config: '邀请人数、好友来源与等待方式',
  switch_soul: '开始前是否切换御魂预设',
  costume_config: '庭院、结界与主题皮肤',
}
const groupHint = (group) => GROUP_HINTS[group] || '这一组是本任务的运行参数'

const shortTime = (value) => {
  if (!value) return ''
  const text = String(value)
  const match = text.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/)
  if (!match) return text
  const [, year, month, day, hour, minute] = match
  const now = new Date()
  const sameDay = now.getFullYear() === Number(year) && now.getMonth() + 1 === Number(month) && now.getDate() === Number(day)
  return sameDay ? `今天 ${hour}:${minute}` : `${month}-${day} ${hour}:${minute}`
}

const isPast = (value) => {
  const stamp = Date.parse(String(value || '').replace(' ', 'T'))
  return Number.isFinite(stamp) && stamp <= Date.now()
}

/* ============================================================== 概览视图 */

export function OverviewView({
  account, tasks, schedule, deviceSummary, logs, coreOnline, eventStatus,
  onGoTasks, onOpenTask, onToggleTask, onAction, onScanBind, busyAction,
}) {
  if (!account) {
    return <Empty title="还没有选择账号" hint="在左侧账号列表里选择一个账号，或者新建一个账号开始配置。" />
  }

  const checks = [
    {
      key: 'core',
      ok: coreOnline,
      title: 'OAS Core 已连接',
      failed: 'OAS Core 没有连接，任务无法启动',
      hint: '先按原项目方式启动 server.py，再回到这里。',
    },
    {
      key: 'device',
      ok: deviceSummary.bound,
      title: deviceSummary.explicit
        ? `设备已绑定：${deviceSummary.label}`
        : '设备：自动检测（未手动绑定窗口，连不上就点右侧绑定）',
      failed: '还没有绑定设备或窗口',
      hint: '先打开模拟器和游戏，再点这里一键扫描并绑定窗口（也可到「运行设置 → 设备」手动填）。',
      action: onScanBind || (() => onOpenTask('Script')),
      actionText: '🔗 扫描并绑定窗口',
      showActionWhenOk: !deviceSummary.explicit,
    },
    {
      key: 'tasks',
      ok: tasks.length > 0,
      title: `已启用 ${tasks.length} 项任务`,
      failed: '这个账号还没有启用任何任务',
      hint: '至少启用一项任务，否则 Core 启动后会立即报「没有可执行任务」。',
      action: onGoTasks,
      actionText: '去启用任务',
    },
    {
      key: 'events',
      ok: eventStatus === 'online',
      title: '实时通道正常',
      failed: '实时通道未连接，状态和日志不会自动更新',
      hint: '通常是 Bridge 重启了，稍等几秒会自动重连。',
    },
  ]
  const blocking = checks.filter((item) => !item.ok)

  const running = schedule?.running?.name ? [schedule.running] : []
  const pending = schedule?.pending || []
  const waiting = schedule?.waiting || []
  const hasSchedule = Boolean(schedule) && (running.length || pending.length || waiting.length)
  const recentLogs = logs.slice(-6).reverse()

  return (
    <div className="view overview">
      <section className="card hero">
        <div className="hero-main">
          <Avatar name={account.name} tone={account.avatar} size="lg" />
          <div>
            <h2>{account.name}</h2>
            <p>
              <StatePill state={account.state} label={account.state_label} connected={account.connected} />
              <span className="sep">·</span>
              {deviceSummary.label}
              <span className="sep">·</span>
              配置文件 {account.id}.json
            </p>
          </div>
        </div>
        <div className="hero-actions">
          {account.state === 'running' ? (
            <button className="btn danger lg" disabled={busyAction} onClick={() => onAction('stop')}>
              {busyAction === 'stop' ? '停止中…' : '■ 停止'}
            </button>
          ) : (
            <button className="btn primary lg" disabled={busyAction || blocking.length > 0} onClick={() => onAction('start')}
              title={blocking.length ? '先解决下面的启动前检查项' : '启动这个账号的任务调度'}>
              {busyAction === 'start' ? '启动中…' : '▶ 启动'}
            </button>
          )}
          <button className="btn ghost lg" disabled={busyAction} onClick={() => onAction('restart')}>
            {busyAction === 'restart' ? '重启中…' : '↻ 重启'}
          </button>
        </div>
      </section>

      <div className="grid-2">
        <section className="card">
          <header className="card-head">
            <h3>启动前检查</h3>
            <span className={`counter ${blocking.length ? 'bad' : 'good'}`}>
              {blocking.length ? `${blocking.length} 项待处理` : '全部通过'}
            </span>
          </header>
          <ul className="checklist">
            {checks.map((item) => {
              const showAction = item.action && (!item.ok || item.showActionWhenOk)
              return (
                <li key={item.key} className={item.ok ? 'ok' : 'bad'}>
                  <span className="check-icon" aria-hidden="true">{item.ok ? (item.showActionWhenOk ? '·' : '✓') : '!'}</span>
                  <div>
                    <strong>{item.ok ? item.title : item.failed}</strong>
                    {(!item.ok || item.showActionWhenOk) && item.hint ? <small>{item.hint}</small> : null}
                  </div>
                  {showAction ? (
                    <button type="button" className="btn ghost sm" onClick={item.action}>{item.actionText}</button>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </section>

        <section className="card">
          <header className="card-head">
            <h3>任务调度</h3>
            <span className="counter">{tasks.length} 项已启用</span>
          </header>
          {hasSchedule ? (
            <div className="schedule">
              <ScheduleGroup title="正在执行" tone="running" items={running} />
              <ScheduleGroup title="待执行" tone="pending" items={pending} />
              <ScheduleGroup title="等待时间到达" tone="waiting" items={waiting} />
            </div>
          ) : (
            <div className="schedule-fallback">
              <p className="muted">
                Core 还没有回传调度快照。下面是这个账号已启用的任务，实际执行顺序由 Core 的调度规则决定。
              </p>
              <ul className="task-mini-list">
                {tasks.map((task) => (
                  <li key={task.id}>
                    <button type="button" className="link" onClick={() => onOpenTask(task.id)}>{taskLabel(task)}</button>
                    <span className={`stamp ${isPast(task.next_run) ? 'due' : ''}`}>
                      {task.next_run ? (isPast(task.next_run) ? '可执行' : shortTime(task.next_run)) : '等待调度'}
                    </span>
                    <button type="button" className="icon-btn sm" title="停用这个任务" onClick={() => onToggleTask(task, false)}>×</button>
                  </li>
                ))}
                {!tasks.length ? <li className="muted">还没有启用任务</li> : null}
              </ul>
            </div>
          )}
        </section>
      </div>

      <section className="card">
        <header className="card-head">
          <h3>最近日志</h3>
          <span className="counter">{logs.length ? `共 ${logs.length} 条` : '暂无'}</span>
        </header>
        {recentLogs.length ? (
          <ul className="log-preview">
            {recentLogs.map((log, index) => (
              <li key={`${log.timestamp}-${index}`} className={log.level}>
                <time>{formatClock(log.timestamp)}</time>
                <span className={`level ${log.level}`}>{levelText(log.level)}</span>
                <span className="log-text">{log.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted pad">这个账号还没有产生日志。启动后 Core 的输出会实时出现在这里。</p>
        )}
      </section>
    </div>
  )
}

function ScheduleGroup({ title, tone, items }) {
  return (
    <div className={`schedule-group ${tone}`}>
      <div className="schedule-title"><StateDot state={tone === 'running' ? 'running' : 'offline'} />{title}<em>{items.length}</em></div>
      <ul>
        {items.map((item, index) => (
          <li key={`${item.name}-${index}`}>
            <span>{taskLabel({ id: item.name })}</span>
            <time>{shortTime(item.next_run)}</time>
          </li>
        ))}
        {!items.length ? <li className="muted">无</li> : null}
      </ul>
    </div>
  )
}

/* ============================================================== 任务视图 */

export function TasksView({
  account, catalog, enabledIds, selectedTaskId, onSelectTask, onToggleTask,
  config, dirtyKeys, onFieldChange, onSave, onResetAll, saving,
  windows, windowsLoading, onRefreshWindows,
  templates, onSaveTemplate, onApplyTemplate, onDeleteTemplate,
}) {
  const [keyword, setKeyword] = useState('')
  const [onlyEnabled, setOnlyEnabled] = useState(false)
  const [fieldKeyword, setFieldKeyword] = useState('')

  const filtered = useMemo(() => {
    const text = keyword.trim().toLowerCase()
    return catalog.filter((task) => {
      if (onlyEnabled && !enabledIds.has(task.id)) return false
      if (!text) return true
      return `${taskLabel(task)} ${task.id} ${task.title} ${categoryLabel(task.category)}`.toLowerCase().includes(text)
    })
  }, [catalog, keyword, onlyEnabled, enabledIds])

  const grouped = useMemo(() => {
    const groups = new Map()
    for (const task of filtered) {
      if (!groups.has(task.category)) groups.set(task.category, [])
      groups.get(task.category).push(task)
    }
    return [...groups.entries()]
  }, [filtered])

  const visibleGroups = useFieldFilter(config?.groups, fieldKeyword)
  const { isOpen, toggle, setAll } = useOpenGroups(config?.task_id, config?.groups)
  const taskTemplates = templates.filter((item) => item.task_id === config?.task_id)
  const [templateName, setTemplateName] = useState('')
  const [pickedTemplate, setPickedTemplate] = useState('')
  const dirtyCount = dirtyKeys.size

  if (!account) return <Empty title="还没有选择账号" hint="任务和配置都是按账号独立保存的，先选一个账号。" />

  return (
    <div className="view tasks">
      <section className="panel catalog">
        <header className="panel-head">
          <div>
            <h3>任务目录</h3>
            <small>点名称看配置，右侧开关才是启用</small>
          </div>
          <span className="counter">{filtered.length}/{catalog.length}</span>
        </header>
        <div className="panel-tools">
          <Search value={keyword} onChange={setKeyword} placeholder="搜索任务（按 / 聚焦）" autoFocusKey />
          <label className="checkline">
            <input type="checkbox" checked={onlyEnabled} onChange={(event) => setOnlyEnabled(event.target.checked)} />
            只看已启用
          </label>
        </div>
        <div className="panel-scroll">
          {grouped.map(([category, tasks]) => (
            <div className="catalog-group" key={category}>
              <div className="catalog-group-title">{categoryLabel(category)}<em>{tasks.length}</em></div>
              {tasks.map((task) => {
                const enabled = enabledIds.has(task.id)
                const active = selectedTaskId === task.id
                return (
                  <div key={task.id} className={`catalog-row ${enabled ? 'enabled' : ''} ${active ? 'active' : ''}`}>
                    <button type="button" className="catalog-main" onClick={() => onSelectTask(task.id)}>
                      <span className="catalog-name">{taskLabel(task)}</span>
                      <span className="catalog-id">{task.id}</span>
                    </button>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={enabled}
                      aria-label={`${enabled ? '停用' : '启用'}${taskLabel(task)}`}
                      title={enabled ? `停用「${taskLabel(task)}」` : `为 ${account.name} 启用「${taskLabel(task)}」`}
                      className={`switch sm ${enabled ? 'on' : ''}`}
                      onClick={() => onToggleTask(task, !enabled)}
                    >
                      <span className="switch-knob" />
                    </button>
                  </div>
                )
              })}
            </div>
          ))}
          {!filtered.length ? <Empty title="没有匹配的任务" hint="换个关键词，或取消「只看已启用」。" /> : null}
        </div>
      </section>

      <section className="panel settings">
        {config ? (
          <>
            <header className="panel-head sticky">
              <div>
                <h3>
                  {taskLabel({ id: config.task_id, title: config.title })}
                  {enabledIds.has(config.task_id)
                    ? <span className="tag on">已启用</span>
                    : <span className="tag off">未启用</span>}
                </h3>
                <small>只对账号 {account.name} 生效 · 内部标识 {config.task_id}</small>
              </div>
              <div className="panel-head-actions">
                {dirtyCount ? <span className="counter warn">{dirtyCount} 项未保存</span> : <span className="counter good">已同步</span>}
                <button type="button" className="btn ghost" disabled={!dirtyCount || saving} onClick={onResetAll}>放弃改动</button>
                <button type="button" className="btn primary" disabled={!dirtyCount || saving} onClick={onSave} title="Ctrl+S">
                  {saving ? '保存中…' : `保存${dirtyCount ? ` (${dirtyCount})` : ''}`}
                </button>
              </div>
            </header>

            <div className="panel-tools">
              <Search value={fieldKeyword} onChange={setFieldKeyword} placeholder="在本任务里搜索配置项" />
              <div className="tool-buttons">
                <button type="button" className="btn ghost sm" onClick={() => setAll(true)}>全部展开</button>
                <button type="button" className="btn ghost sm" onClick={() => setAll(false)}>全部折叠</button>
              </div>
            </div>

            <details className="template-bar">
              <summary>配置模板<em>{taskTemplates.length}</em></summary>
              <div className="template-body">
                <p className="muted">
                  模板保存的是这个任务的全部参数，可以套用到别的账号的同名任务。套用后仍然要点「保存」才会写入 Core。
                </p>
                <div className="template-row">
                  <select value={pickedTemplate} onChange={(event) => setPickedTemplate(event.target.value)} aria-label="选择配置模板">
                    <option value="">选择已保存的模板</option>
                    {taskTemplates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                  <button type="button" className="btn ghost sm" disabled={!pickedTemplate} onClick={() => onApplyTemplate(pickedTemplate)}>套用</button>
                  <button type="button" className="btn ghost sm danger" disabled={!pickedTemplate}
                    onClick={() => { onDeleteTemplate(pickedTemplate); setPickedTemplate('') }}>删除</button>
                </div>
                <div className="template-row">
                  <input value={templateName} placeholder="新模板名称（留空自动命名）" onChange={(event) => setTemplateName(event.target.value)} />
                  <button type="button" className="btn ghost sm" onClick={() => { onSaveTemplate(templateName); setTemplateName('') }}>
                    存为模板
                  </button>
                </div>
              </div>
            </details>

            <div className="panel-scroll form">
              {Object.entries(visibleGroups).map(([group, fields]) => (
                <section className={`config-group ${isOpen(group) ? '' : 'collapsed'}`} key={group}>
                  <button type="button" className="config-group-head" onClick={() => toggle(group)} aria-expanded={isOpen(group)}>
                    <span className="chev" aria-hidden="true">▾</span>
                    <span className="group-copy">
                      <strong>{groupLabel(group)}</strong>
                      <small>{groupHint(group)}</small>
                    </span>
                    <em>{fields.length} 项</em>
                  </button>
                  {isOpen(group) ? (
                    <div className="config-fields">
                      {fields.map((field) => (
                        <FieldRow
                          key={`${group}.${field.name}`}
                          field={field}
                          group={group}
                          dirty={dirtyKeys.has(`${group}.${field.name}`)}
                          onChange={(value) => onFieldChange(group, field.name, value)}
                          windows={windows}
                          windowsLoading={windowsLoading}
                          onRefreshWindows={onRefreshWindows}
                        />
                      ))}
                    </div>
                  ) : null}
                </section>
              ))}
              {!Object.keys(visibleGroups).length ? (
                <Empty title="没有匹配的配置项" hint={fieldKeyword ? '换一个关键词试试。' : '这个任务没有可编辑的参数。'} />
              ) : null}
            </div>
          </>
        ) : selectedTaskId ? (
          <Empty title="正在读取配置…" hint="首次读取真实 Core 的参数表可能要等一两秒，请稍候。" />
        ) : (
          <Empty title="选择一个任务" hint="左侧点击任务名称即可查看它在当前账号下的配置，不会改变启用状态。" />
        )}
      </section>
    </div>
  )
}

/* ============================================================== 日志视图 */

const LEVELS = [
  { key: 'info', label: '信息' },
  { key: 'warn', label: '警告' },
  { key: 'error', label: '错误' },
]
export const levelText = (level) => ({ error: '错误', warn: '警告', info: '信息' }[level] || '信息')

export function formatClock(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value || '').slice(11, 19)
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

export function LogsView({ account, logs, levels, onLevels, onClear, onExport }) {
  const [keyword, setKeyword] = useState('')
  const [follow, setFollow] = useState(true)

  const visible = useMemo(() => {
    const text = keyword.trim().toLowerCase()
    return logs.filter((log) => {
      if (!levels.includes(log.level || 'info')) return false
      if (!text) return true
      return String(log.message || '').toLowerCase().includes(text)
    })
  }, [logs, levels, keyword])

  if (!account) return <Empty title="还没有选择账号" hint="日志是按账号分开的。" />

  const toggleLevel = (key) => {
    const next = levels.includes(key) ? levels.filter((item) => item !== key) : [...levels, key]
    onLevels(next.length ? next : [key])
  }

  return (
    <div className="view logs">
      <section className="panel full">
        <header className="panel-head">
          <div>
            <h3>{account.name} 的运行日志</h3>
            <small>Bridge 在内存里保留每个账号最近 300 条；完整日志在项目的 log 目录</small>
          </div>
          <div className="panel-head-actions">
            <span className="counter">{visible.length}/{logs.length}</span>
            <button type="button" className="btn ghost sm" onClick={onExport} disabled={!logs.length}>导出</button>
            <button type="button" className="btn ghost sm" onClick={onClear} disabled={!logs.length}>清空显示</button>
          </div>
        </header>
        <div className="panel-tools">
          <Search value={keyword} onChange={setKeyword} placeholder="搜索日志内容" />
          <div className="level-filter">
            {LEVELS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`chip ${item.key} ${levels.includes(item.key) ? 'on' : ''}`}
                onClick={() => toggleLevel(item.key)}
              >
                {item.label}
              </button>
            ))}
            <label className="checkline">
              <input type="checkbox" checked={follow} onChange={(event) => setFollow(event.target.checked)} />
              自动滚动
            </label>
          </div>
        </div>
        <div className="log-stream" ref={(node) => { if (node && follow) node.scrollTop = node.scrollHeight }}>
          {visible.map((log, index) => (
            <div key={`${log.timestamp}-${index}`} className={`log-line ${log.level}`}>
              <time>{formatClock(log.timestamp)}</time>
              <span className={`level ${log.level}`}>{levelText(log.level)}</span>
              <span className="log-text">{log.message}</span>
            </div>
          ))}
          {!visible.length ? (
            <Empty
              title={logs.length ? '当前过滤条件下没有日志' : '还没有日志'}
              hint={logs.length ? '试试放开级别过滤或清空搜索词。' : '启动这个账号后，Core 的输出会实时出现在这里。'}
            />
          ) : null}
        </div>
      </section>
    </div>
  )
}

/* ============================================================== 设置视图 */

export function SettingsView({
  health, bridgeOrigin, eventStatus, theme, onTheme, density, onDensity,
  templates, onDeleteTemplate, templateStorage,
  account, onRenameAccount, onDeleteAccount, onReconnect,
}) {
  return (
    <div className="view settings-view">
      <section className="card">
        <header className="card-head"><h3>外观</h3></header>
        <div className="setting-row">
          <div><strong>主题</strong><small>深色适合长时间挂机，浅色适合白天和截图</small></div>
          <div className="segmented">
            {[['dark', '深色'], ['light', '浅色'], ['system', '跟随系统']].map(([key, label]) => (
              <button key={key} type="button" className={theme === key ? 'on' : ''} onClick={() => onTheme(key)}>{label}</button>
            ))}
          </div>
        </div>
        <div className="setting-row">
          <div><strong>显示密度</strong><small>小屏幕或 1280×760 的窗口建议用紧凑</small></div>
          <div className="segmented">
            {[['comfortable', '舒适'], ['compact', '紧凑']].map(([key, label]) => (
              <button key={key} type="button" className={density === key ? 'on' : ''} onClick={() => onDensity(key)}>{label}</button>
            ))}
          </div>
        </div>
      </section>

      <section className="card">
        <header className="card-head"><h3>连接</h3></header>
        <dl className="kv">
          <dt>Bridge 地址</dt><dd><code>{bridgeOrigin}</code></dd>
          <dt>Bridge 状态</dt><dd>{health.bridge === 'ok' ? '正常' : '未连接'}</dd>
          <dt>OAS Core</dt>
          <dd>
            {health.core === 'ok' ? '在线' : '未连接'}
            {health.core_url ? <code className="ml">{health.core_url}</code> : null}
          </dd>
          <dt>实时事件通道</dt>
          <dd>
            {{ online: '已连接', connecting: '连接中', reconnecting: '重连中', offline: '已断开' }[eventStatus] || eventStatus}
            <button type="button" className="btn ghost sm ml" onClick={onReconnect}>立即重连</button>
          </dd>
        </dl>
        <Banner tone="info">
          控制中心只通过 Bridge 访问 OAS Core，不直接读写 <code>config/*.json</code>。任务参数的唯一事实来源仍然是 Core。
        </Banner>
      </section>

      <section className="card">
        <header className="card-head">
          <h3>配置模板</h3>
          <span className="counter">{templates.length}</span>
        </header>
        <p className="muted pad">
          存储位置：{templateStorage === 'bridge' ? 'Bridge 数据库（可随 Bridge 一起备份）' : '本机浏览器存储（换机器不会同步）'}
        </p>
        {templates.length ? (
          <ul className="template-list">
            {templates.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <small>{taskLabel({ id: item.task_id, title: item.task_title })} · {String(item.created_at || '').slice(0, 10)}</small>
                </div>
                <button type="button" className="btn ghost sm danger" onClick={() => onDeleteTemplate(item.id)}>删除</button>
              </li>
            ))}
          </ul>
        ) : <p className="muted pad">还没有保存模板。在「任务」页调好参数后可以存为模板。</p>}
      </section>

      <section className="card danger-zone">
        <header className="card-head"><h3>当前账号</h3></header>
        {account ? (
          <>
            <div className="setting-row">
              <div><strong>{account.name}</strong><small>配置文件 {account.id}.json</small></div>
              <button type="button" className="btn ghost" onClick={onRenameAccount}>重命名</button>
            </div>
            <div className="setting-row">
              <div><strong>删除账号</strong><small>会删除 Core 里的配置文件，且不可撤销</small></div>
              <button type="button" className="btn danger" onClick={onDeleteAccount}>删除 {account.name}</button>
            </div>
          </>
        ) : <p className="muted pad">先选择一个账号。</p>}
      </section>
    </div>
  )
}
