/**
 * 模拟器窗口识别（给「一键扫描绑定」用）。
 *
 * Bridge 的 /windows 会把系统里所有可见顶层窗口都列出来（含资源管理器、浏览器…），
 * 这里按进程名/标题挑出常见模拟器和游戏窗口，并把窗口映射到 OAS 的 emulatorinfo_type。
 * 纯前端启发式，识别不了就返回 null（绑定时只写窗口句柄、类型保持 auto，绝不写坏值）。
 */

// 每种模拟器：进程名正则 + 可能的 emulatorinfo_type 取值（按优先级，真正写入前会和 Core 的真实枚举比对）
export const EMULATOR_SIGNS = [
  { key: 'mumu', label: 'MuMu 模拟器', proc: /mumu|nemu/i, typeHints: ['MuMuPlayer12', 'MuMu12', 'MuMuPlayer', 'mumu', 'nemu'] },
  { key: 'ld', label: '雷电模拟器', proc: /dnplayer|ldplayer|ldvbox|dnmulti|dnconsole/i, typeHints: ['LDPlayer', 'LDPlayer9', 'ld'] },
  { key: 'nox', label: '夜神模拟器', proc: /nox|noxvmhandle/i, typeHints: ['NoxPlayer', 'Nox', 'nox'] },
  { key: 'bluestacks', label: '蓝叠模拟器', proc: /hd-player|bluestacks|bstk/i, typeHints: ['BlueStacks', 'BlueStacks5', 'bluestacks'] },
  { key: 'memu', label: '逍遥模拟器', proc: /memu/i, typeHints: ['MEmu', 'MEmuPlayer', 'memu'] },
  { key: 'mumu6', label: 'MuMu 模拟器', proc: /mumuvmm/i, typeHints: ['MuMuPlayer', 'mumu'] },
]

const EMU_TITLE = /模拟器|mumu|雷电|夜神|蓝叠|逍遥|bluestacks|nox|ldplayer|memu/i
const GAME_TITLE = /阴阳师|onmyoji/i

/** 判定一个窗口是什么：命中的模拟器签名 / 游戏窗口 / null（不是模拟器或游戏）。 */
export function classifyWindow(win) {
  const proc = String(win?.process || '')
  const title = String(win?.title || '')
  for (const sign of EMULATOR_SIGNS) {
    if (sign.proc.test(proc)) return sign
  }
  if (EMU_TITLE.test(title)) return { key: 'emu', label: '模拟器', typeHints: [] }
  if (GAME_TITLE.test(title)) return { key: 'game', label: '游戏窗口', typeHints: [] }
  return null
}

export const isEmulatorWindow = (win) => classifyWindow(win) !== null
export const emulatorLabel = (win) => classifyWindow(win)?.label || '窗口'

/**
 * 从窗口 + Core 真实枚举里挑一个合法的 emulatorinfo_type。
 * 先精确匹配（大小写不敏感），再宽松匹配（选项包含关键字）；都挑不到返回 null（保持 auto）。
 * 这样即使不同 OAS 版本的枚举写法不同，也不会写入非法值被 Core 拒绝。
 */
export function inferEmulatorType(win, options = []) {
  const sign = classifyWindow(win)
  if (!sign || !sign.typeHints || !sign.typeHints.length) return null
  const opts = (options || []).map((item) => String(item)).filter((item) => item && item !== 'auto')
  for (const hint of sign.typeHints) {
    const exact = opts.find((opt) => opt.toLowerCase() === hint.toLowerCase())
    if (exact) return exact
  }
  const loose = opts.find((opt) => opt.toLowerCase().includes(sign.key.toLowerCase()))
  return loose || null
}
