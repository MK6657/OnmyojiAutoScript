/**
 * 配置字段编辑器。
 *
 * OAS Core 的 Schema 会随上游变化，所以这里按「类型 + 字段名」两级匹配，
 * 匹配不上时一律降级成文本框，保证新增字段永远可见、可改，不会白屏。
 *
 * 值的格式统一在这里收敛成 Core 能直接接受的形式：
 *   time        -> HH:MM:SS
 *   date_time   -> YYYY-MM-DD HH:MM:SS
 *   time_delta  -> DD HH:MM:SS
 * 不依赖 Bridge 再做一次字符串补全，避免两边规则不一致。
 */
import { useEffect, useMemo, useState } from 'react'
import { fieldDescription, fieldLabel, optionLabel } from './locale.js'

const pad2 = (value) => String(Math.max(0, Math.floor(Number(value) || 0))).padStart(2, '0')

/* ------------------------------------------------------------------ 时间值 */

export function normalizeTime(value) {
  const text = String(value ?? '').trim()
  const parts = text.split(':')
  if (parts.length < 2) return '00:00:00'
  return `${pad2(parts[0])}:${pad2(parts[1])}:${pad2(parts[2] ?? 0)}`
}

export function normalizeDateTime(value) {
  const text = String(value ?? '').trim().replace('T', ' ')
  const [date = '', time = ''] = text.split(' ')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return '2023-01-01 00:00:00'
  return `${date} ${normalizeTime(time || '00:00:00')}`
}

export function parseDelta(value) {
  const text = String(value ?? '').trim()
  const match = text.match(/^(\d+)[\s|](\d{1,2}):(\d{1,2}):(\d{1,2})$/)
  if (match) return { days: Number(match[1]), time: `${pad2(match[2])}:${pad2(match[3])}:${pad2(match[4])}` }
  if (/^\d{1,2}:\d{1,2}:\d{1,2}$/.test(text)) return { days: 0, time: normalizeTime(text) }
  return { days: 0, time: '00:00:00' }
}

export const formatDelta = ({ days, time }) => `${pad2(days)} ${normalizeTime(time)}`

/* ------------------------------------------------------------ 基础输入控件 */

function Switch({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={Boolean(checked)}
      disabled={disabled}
      className={`switch ${checked ? 'on' : ''}`}
      onClick={() => onChange(!checked)}
    >
      <span className="switch-knob" />
    </button>
  )
}

function WindowPicker({ field, value, onChange, windows, windowsLoading, onRefreshWindows }) {
  const current = String(value ?? '')
  const known = windows.some((item) => String(item.handle) === current)
  const matched = windows.find((item) => String(item.handle) === current)

  return (
    <div className="window-picker">
      <div className="window-picker-row">
        <select
          value={known ? current : ''}
          onChange={(event) => onChange(event.target.value)}
          aria-label="选择要绑定的游戏窗口"
        >
          <option value="">不绑定窗口（由设备序列号决定）</option>
          {windows.map((item) => (
            <option key={item.handle} value={String(item.handle)}>
              {item.title} · 句柄 {item.handle}{item.process ? ` · ${item.process}` : ''}
            </option>
          ))}
        </select>
        <button type="button" className="btn ghost sm" onClick={onRefreshWindows} disabled={windowsLoading}>
          {windowsLoading ? '读取中…' : '刷新窗口'}
        </button>
        {current ? (
          <button type="button" className="btn ghost sm danger" onClick={() => onChange('')}>清除</button>
        ) : null}
      </div>
      <div className="window-picker-note">
        {matched
          ? <><span className="ok-dot" />已选择「{matched.title}」，句柄 {matched.handle}</>
          : current
            ? <><span className="warn-dot" />当前句柄 {current} 不在窗口列表里，可能窗口已关闭</>
            : <>先打开模拟器，再点「刷新窗口」选择这个账号要控制的窗口</>}
      </div>
      <input
        className="window-manual"
        value={current}
        placeholder="也可以手动填写窗口句柄"
        onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ''))}
        aria-label={`${fieldLabel(field)} 手动输入`}
      />
    </div>
  )
}

function DeltaEditor({ value, onChange }) {
  const parsed = parseDelta(value)
  return (
    <div className="delta-editor">
      <label className="delta-part" title="OAS Core 的接口格式为两位天数，最多 99 天（见 handoff/16 C1）">
        <input
          type="number" min="0" max="99" value={parsed.days}
          onChange={(event) => onChange(formatDelta({ ...parsed, days: Math.min(99, Math.max(0, Number(event.target.value) || 0)) }))}
        />
        <span>天</span>
      </label>
      <input
        type="time" step="1" value={parsed.time}
        onChange={(event) => onChange(formatDelta({ ...parsed, time: event.target.value || '00:00:00' }))}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ 主控件 */

function Control({ field, value, onChange, windows, windowsLoading, onRefreshWindows }) {
  const type = field.type
  const options = field.options || []

  if (field.name === 'handle') {
    return (
      <WindowPicker
        field={field} value={value} onChange={onChange}
        windows={windows} windowsLoading={windowsLoading} onRefreshWindows={onRefreshWindows}
      />
    )
  }
  if (type === 'boolean') return <Switch checked={Boolean(value)} onChange={onChange} />
  if (type === 'enum' || options.length) {
    const current = String(value ?? '')
    const list = options.map(String)
    return (
      <select value={current} onChange={(event) => onChange(event.target.value)}>
        {!list.includes(current) && current !== '' ? <option value={current}>{optionLabel(current)}（当前值）</option> : null}
        {list.map((option) => <option key={option} value={option}>{optionLabel(option)}</option>)}
      </select>
    )
  }
  if (type === 'time_delta') return <DeltaEditor value={value} onChange={onChange} />
  if (type === 'time') {
    return (
      <input type="time" step="1" value={normalizeTime(value)}
        onChange={(event) => onChange(normalizeTime(event.target.value))} />
    )
  }
  if (type === 'date_time') {
    const canonical = normalizeDateTime(value)
    return (
      <input
        type="datetime-local" step="1" value={canonical.replace(' ', 'T')}
        onChange={(event) => onChange(normalizeDateTime(event.target.value))}
      />
    )
  }
  if (type === 'integer' || type === 'number') {
    const step = type === 'number' ? '0.1' : '1'
    return (
      <input
        type="number" step={step} value={value ?? 0}
        onChange={(event) => {
          const raw = event.target.value
          if (raw === '') { onChange(type === 'integer' ? 0 : 0); return }
          onChange(type === 'integer' ? Math.trunc(Number(raw)) || 0 : Number(raw) || 0)
        }}
      />
    )
  }
  const text = String(value ?? '')
  if (text.length > 48 || text.includes('\n')) {
    return <textarea rows={Math.min(6, text.split('\n').length + 1)} value={text} onChange={(event) => onChange(event.target.value)} />
  }
  return <input type="text" value={text} onChange={(event) => onChange(event.target.value)} />
}

const sameValue = (left, right) => JSON.stringify(left ?? null) === JSON.stringify(right ?? null)

const hideLegacyPresetIndexes = (fields) => {
  const names = new Set((fields || []).map((field) => field.name))
  if (!names.has('preset_group_name') || !names.has('preset_team_name')) return fields || []
  return fields.filter((field) => field.name !== 'preset_group' && field.name !== 'preset_team')
}

export function FieldRow({ field, group, dirty, onChange, windows, windowsLoading, onRefreshWindows }) {
  const label = fieldLabel(field, group)
  const description = fieldDescription(field, group)
  const isDefault = sameValue(field.value, field.default)

  return (
    <div className={`field ${dirty ? 'dirty' : ''} ${field.type === 'boolean' ? 'inline' : ''}`}>
      <div className="field-head">
        <span className="field-label">
          {label}
          {dirty ? <em className="dirty-mark" title="已修改，尚未保存">未保存</em> : null}
        </span>
        {description ? <span className="field-desc">{description}</span> : null}
        <span className="field-meta" title="OAS Core 内部字段名，方便与源码对照">{field.name}</span>
      </div>
      <div className="field-control">
        <Control
          field={field} value={field.value} onChange={onChange}
          windows={windows} windowsLoading={windowsLoading} onRefreshWindows={onRefreshWindows}
        />
        {!isDefault ? (
          <button
            type="button" className="btn ghost xs field-reset"
            title={`恢复默认值：${String(field.default)}`}
            onClick={() => onChange(field.default)}
          >
            恢复默认
          </button>
        ) : null}
      </div>
    </div>
  )
}

/** 表单里的字段搜索，字段多的任务（比如运行设置）离不开它。 */
export function useFieldFilter(groups, keyword) {
  return useMemo(() => {
    const text = keyword.trim().toLowerCase()
    const result = {}
    for (const [group, fields] of Object.entries(groups || {})) {
      const currentFields = hideLegacyPresetIndexes(fields)
      if (!text) {
        result[group] = currentFields
        continue
      }
      const matched = currentFields.filter((field) =>
        `${fieldLabel(field, group)} ${field.name} ${field.title} ${fieldDescription(field, group)}`.toLowerCase().includes(text))
      if (matched.length) result[group] = matched
    }
    return result
  }, [groups, keyword])
}

/** 让折叠状态在切换任务时回到「全部展开」，避免用户以为字段丢了。 */
export function useOpenGroups(taskId, groups) {
  const [open, setOpen] = useState({})
  useEffect(() => { setOpen({}) }, [taskId])
  const isOpen = (group) => open[group] !== false
  const toggle = (group) => setOpen((current) => ({ ...current, [group]: current[group] === false }))
  const setAll = (value) => setOpen(Object.fromEntries(Object.keys(groups || {}).map((group) => [group, value])))
  return { isOpen, toggle, setAll }
}
