/**
 * 本地偏好与降级存储。
 *
 * 模板和任务排序优先走 Bridge（可备份、跨浏览器一致）；
 * Bridge 不支持时回落到 localStorage，行为与旧版一致，不会丢数据。
 */
import { useCallback, useEffect, useState } from 'react'

const NS = 'oas-control-center'
export const KEYS = {
  theme: `${NS}.theme.v1`,
  density: `${NS}.density.v1`,
  view: `${NS}.view.v1`,
  sidebar: `${NS}.sidebar.v1`,
  account: `${NS}.account.v1`,
  templates: `${NS}.templates.v1`,      // 与旧版共用，升级后模板不丢
  taskOrder: `${NS}.task-order.v1`,     // 与旧版共用
  logLevels: `${NS}.log-levels.v1`,
  onboarded: `${NS}.onboarded.v1`,
}

export function readJSON(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key)
    if (raw === null) return fallback
    const value = JSON.parse(raw)
    return value === null || value === undefined ? fallback : value
  } catch {
    return fallback
  }
}

export function writeJSON(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 隐私模式下写入会失败，忽略即可，功能降级为不记忆 */
  }
}

export function usePersistentState(key, fallback) {
  const [value, setValue] = useState(() => readJSON(key, fallback))
  const update = useCallback((next) => {
    setValue((current) => {
      const resolved = typeof next === 'function' ? next(current) : next
      writeJSON(key, resolved)
      return resolved
    })
  }, [key])
  return [value, update]
}

/** 深浅色主题：默认深色，可切浅色，也可跟随系统。 */
export function useTheme() {
  const [theme, setTheme] = usePersistentState(KEYS.theme, 'dark')

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: light)')
    const apply = () => {
      const resolved = theme === 'system' ? (query?.matches ? 'light' : 'dark') : theme
      document.documentElement.dataset.theme = resolved
      document.documentElement.style.colorScheme = resolved
    }
    apply()
    if (theme !== 'system' || !query) return undefined
    query.addEventListener?.('change', apply)
    return () => query.removeEventListener?.('change', apply)
  }, [theme])

  return [theme, setTheme]
}

export function useDensity() {
  const [density, setDensity] = usePersistentState(KEYS.density, 'comfortable')
  useEffect(() => { document.documentElement.dataset.density = density }, [density])
  return [density, setDensity]
}

export const makeId = (prefix = 'id') =>
  `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`

export const clone = (value) => (value === undefined ? value : JSON.parse(JSON.stringify(value)))
