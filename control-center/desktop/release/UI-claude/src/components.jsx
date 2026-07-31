/** 通用小组件：状态点、徽章、搜索框、空状态、确认框、提示条、窗口绑定弹窗。 */
import { useEffect, useRef, useState } from 'react'
import { classifyWindow, isEmulatorWindow } from './emulator.js'

export const STATE_TEXT = {
  running: '运行中',
  offline: '已停止',
  warning: '异常',
  updating: '更新中',
}

export function StateDot({ state, connected = true }) {
  const resolved = state || 'offline'
  return <span className={`dot ${resolved} ${connected ? '' : 'disconnected'}`} />
}

export function StatePill({ state, label, connected = true }) {
  const resolved = state || 'offline'
  return (
    <span className={`pill ${resolved}`}>
      <StateDot state={resolved} connected={connected} />
      {label || STATE_TEXT[resolved] || '未知'}
    </span>
  )
}

export function Avatar({ name, tone = 'blue', size = 'md' }) {
  const initial = String(name || '?').trim().slice(0, 1).toUpperCase()
  return <span className={`avatar ${tone} ${size}`} aria-hidden="true">{initial}</span>
}

export function Search({ value, onChange, placeholder, autoFocusKey }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!autoFocusKey) return undefined
    const handler = (event) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey) return
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      event.preventDefault()
      ref.current?.focus()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [autoFocusKey])

  return (
    <div className="search">
      <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.6" /><path d="M10.4 10.4 14 14" /></svg>
      <input
        ref={ref}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Escape') onChange('') }}
      />
      {value ? <button type="button" className="search-clear" onClick={() => onChange('')} title="清空搜索" aria-label="清空搜索">×</button> : null}
    </div>
  )
}

export function Empty({ title, hint, action }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {hint ? <p>{hint}</p> : null}
      {action}
    </div>
  )
}

export function Toasts({ items, onDismiss }) {
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((toast) => (
        <div key={toast.id} className={`toast ${toast.tone}`}>
          <span>{toast.message}</span>
          <button type="button" onClick={() => onDismiss(toast.id)} aria-label="关闭提示">×</button>
        </div>
      ))}
    </div>
  )
}

export function Confirm({ request, onResolve }) {
  const ref = useRef(null)
  useEffect(() => { if (request) ref.current?.focus() }, [request])
  if (!request) return null
  const { title, body, confirmText = '确定', tone = 'default' } = request
  return (
    <div className="overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onResolve(false) }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        <div className="dialog-body">{body}</div>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={() => onResolve(false)}>取消</button>
          <button ref={ref} type="button" className={`btn ${tone === 'danger' ? 'danger' : 'primary'}`} onClick={() => onResolve(true)}>
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}

export function Prompt({ request, onResolve }) {
  const [value, setValue] = useState('')
  const ref = useRef(null)
  useEffect(() => { setValue(request?.initial || ''); if (request) window.setTimeout(() => ref.current?.focus(), 20) }, [request])
  if (!request) return null

  const submit = (event) => { event.preventDefault(); onResolve(value) }
  return (
    <div className="overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onResolve(null) }}>
      <form className="dialog" onSubmit={submit} role="dialog" aria-modal="true" aria-label={request.title}>
        <h3>{request.title}</h3>
        <div className="dialog-body">
          {request.body ? <p>{request.body}</p> : null}
          <input ref={ref} value={value} placeholder={request.placeholder} onChange={(event) => setValue(event.target.value)} />
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={() => onResolve(null)}>取消</button>
          <button type="submit" className="btn primary">{request.confirmText || '确定'}</button>
        </div>
      </form>
    </div>
  )
}

/** 单行提示条，用于「Core 掉线」这类需要一直可见的状态。 */
export function Banner({ tone = 'warn', children, action }) {
  return (
    <div className={`banner ${tone}`}>
      <span>{children}</span>
      {action}
    </div>
  )
}

/**
 * 一键扫描并绑定模拟器/游戏窗口（对标闭源助手的「绑定窗口」）。
 * 只列出识别到的模拟器窗口，选中即自动写入窗口句柄并保存，不用手填端口。
 */
export function WindowBindDialog({ open, windows, loading, onRefresh, onPick, onClose }) {
  if (!open) return null
  const emulators = (windows || []).filter(isEmulatorWindow)
  const list = emulators.length ? emulators : (windows || [])
  return (
    <div className="overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div className="dialog window-bind" role="dialog" aria-modal="true" aria-label="扫描并绑定模拟器窗口">
        <h3>扫描并绑定模拟器窗口</h3>
        <div className="dialog-body">
          <p className="muted">
            先打开模拟器和游戏，再选中下面对应的窗口即可。会自动填好窗口句柄和模拟器类型并保存，不用手动填端口。
          </p>
          <div className="wb-toolbar">
            <span className="wb-count">
              {loading
                ? '正在扫描窗口…'
                : `识别到 ${emulators.length} 个模拟器窗口${emulators.length !== (windows || []).length ? `（共扫描到 ${(windows || []).length} 个窗口）` : ''}`}
            </span>
            <button type="button" className="btn ghost sm" onClick={onRefresh} disabled={loading}>
              {loading ? '扫描中…' : '重新扫描'}
            </button>
          </div>
          <ul className="wb-list">
            {list.map((win) => {
              const sign = classifyWindow(win)
              return (
                <li key={win.handle}>
                  <button type="button" className="wb-item" onClick={() => onPick(win)}>
                    <span className="wb-title">{win.title || '(无标题窗口)'}</span>
                    <span className="wb-meta">
                      {sign ? <em className="wb-tag">{sign.label}</em> : null}
                      <span>{win.process || '未知进程'} · 句柄 {win.handle}{win.serial ? ` · ${win.serial}` : ' · ADB 未确认'}</span>
                    </span>
                  </button>
                </li>
              )
            })}
            {!list.length ? (
              <li className="wb-empty">{loading ? '正在扫描…' : '没扫描到窗口。请先打开模拟器和游戏，再点「重新扫描」。'}</li>
            ) : null}
          </ul>
          {!emulators.length && (windows || []).length ? (
            <p className="muted sm">没识别到常见模拟器进程，已列出全部窗口；你也可以直接选游戏窗口本身。</p>
          ) : null}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
