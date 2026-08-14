/**
 * 真实三层端到端回归：正式前端（浏览器）→ 真实 Bridge → mock Core。
 *
 * 与 e2e.mjs 的区别：那份对着轻量 mock bridge 验证前端契约；这一份跑的是
 * 【真正的 Bridge 进程】——缓存、调度快照、WebSocket 运行时、日志级别解析、
 * SQLite 模板、CORS（前端与 Bridge 跨端口直连）全部走真实代码路径。
 *
 * 运行前提（三个进程）：
 *   1. mock Core：  python -m uvicorn tests.mock_core:app --port 22268   （bridge 目录）
 *   2. 隔离 Bridge：OAS_CORE_URL=http://127.0.0.1:22268、OAS_INTEGRATION_TEST=1、
 *                  独立 OAS_CONTROL_CENTER_DATA_DIR，监听 22368
 *   3. 前端：       OAS_BRIDGE_URL=http://127.0.0.1:22368 让 Vite proxy 指向隔离 Bridge
 * 然后：node tools/e2e-real.mjs [--shots]
 *
 * 必填环境变量：OAS_TEST_BRIDGE_URL、OAS_TEST_MOCK_URL。
 * 可选环境变量：OAS_UI_BASE（前端地址，默认 http://127.0.0.1:4175/）。
 */
const BASE = process.env.OAS_UI_BASE || process.env.UI_CLAUDE_BASE || 'http://127.0.0.1:4175/'
const BRIDGE_ROOT = (process.env.OAS_TEST_BRIDGE_URL || '').replace(/\/$/, '')
const MOCK = (process.env.OAS_TEST_MOCK_URL || '').replace(/\/$/, '')
const BRIDGE = `${BRIDGE_ROOT}/api/v1`
const CHROME = process.env.CHROMIUM_PATH || undefined
const SHOTS = process.argv.includes('--shots')

const results = []
const consoleErrors = []
let page

const check = async (name, fn) => {
  try {
    await fn()
    results.push(['PASS', name, ''])
  } catch (error) {
    results.push(['FAIL', name, error.message])
  }
}
const expect = (condition, message) => { if (!condition) throw new Error(message) }
const text = async (selector) => (await page.locator(selector).first().innerText()).trim()
const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `shots/${name}.png` }) }
const mockFault = (on) => fetch(`${MOCK}/__mock__/fault?on=${on}`, { method: 'POST' })

const requireIsolatedEnvironment = async () => {
  if (!BRIDGE_ROOT || !MOCK) throw new Error('必须设置 OAS_TEST_BRIDGE_URL 和 OAS_TEST_MOCK_URL')
  const bridgeUrl = new URL(BRIDGE_ROOT)
  const mockUrl = new URL(MOCK)
  const loopback = new Set(['127.0.0.1', 'localhost', '[::1]'])
  if (!loopback.has(bridgeUrl.hostname) || !loopback.has(mockUrl.hostname)) {
    throw new Error('端到端测试只允许访问本机回环地址')
  }
  if (bridgeUrl.port === '22367') throw new Error('拒绝使用正式 Bridge 端口 22367')

  const [mockResponse, healthResponse] = await Promise.all([
    fetch(`${MOCK}/__mock__/stats`),
    fetch(`${BRIDGE}/health`),
  ])
  const mockStats = mockResponse.ok ? await mockResponse.json() : null
  const health = healthResponse.ok ? await healthResponse.json() : null
  if (!mockStats || typeof mockStats.args_calls !== 'number') throw new Error('指定地址不是 mock Core')
  if (!health || health.integration_test !== true) throw new Error('Bridge 未以隔离测试模式启动')
  if (health.data_isolated !== true) throw new Error('Bridge 未使用隔离数据目录')
  if (String(health.core_url || '').replace(/\/$/, '') !== MOCK) throw new Error('Bridge 未指向指定 mock Core')
  if (!health.data_dir) throw new Error('Bridge 未报告隔离数据目录')
}

try {
  await requireIsolatedEnvironment()
} catch (error) {
  console.error(`安全预检失败，未执行界面写操作：${error.message}`)
  process.exit(2)
}

let chromium
try {
  ;({ chromium } = await import('playwright'))
} catch (error) {
  console.error(`Playwright 未安装，无法运行浏览器回归：${error.message}`)
  process.exit(1)
}

const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {})
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
page = await context.newPage()
page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()) })
page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`))

const healthResponsePromise = page.waitForResponse((response) => response.url().includes('/api/v1/health'), { timeout: 10000 })
await page.goto(BASE, { waitUntil: 'networkidle' })
const healthResponse = await healthResponsePromise
const observedBridge = healthResponse.url().replace(/\/api\/v1\/health(?:\?.*)?$/, '')
const uiOrigin = new URL(BASE).origin
const observedHealth = await healthResponse.json().catch(() => null)
const routeIsExpected = observedBridge === BRIDGE_ROOT || observedBridge === uiOrigin
const responseIsIsolated = observedHealth?.integration_test === true
  && observedHealth?.data_isolated === true
  && String(observedHealth?.core_url || '').replace(/\/$/, '') === MOCK
if (!routeIsExpected || !responseIsIsolated) {
  await browser.close()
  console.error(`安全预检失败：前端请求路径 ${observedBridge} 未确认连接隔离 Bridge ${BRIDGE_ROOT}`)
  process.exit(2)
}
await page.waitForSelector('.app', { timeout: 10000 })

/* ------------------------------------------------------------ 基础链路 */

await check('三层在线：Core 在线徽标 + 实时通道已连接', async () => {
  await page.waitForFunction(() => document.querySelector('.brand-text span')?.textContent?.includes('Core 在线'), null, { timeout: 8000 })
  await page.waitForFunction(() => document.querySelector('.statusbar')?.textContent?.includes('实时通道 已连接'), null, { timeout: 8000 })
})

await check('账号列表来自真实 Bridge（3 个账号）', async () => {
  await page.waitForFunction(() => document.querySelectorAll('.account').length === 3, null, { timeout: 8000 })
})

await check('选中 oas1：3 项已启用任务 + 调度快照渲染', async () => {
  await page.locator('.account', { hasText: 'oas1' }).click()
  await page.waitForFunction(() => document.querySelector('.topbar-account p')?.textContent?.includes('3 项任务'), null, { timeout: 8000 })
  await page.waitForFunction(() => {
    const body = document.querySelector('.overview')?.textContent || ''
    return body.includes('待执行') && body.includes('等待时间到达')
  }, null, { timeout: 8000 })
})
await shot('r1-overview')

/* ------------------------------------------------------------ 任务与配置 */

await check('任务目录 53 项（经 Bridge 缓存的 Core 菜单）', async () => {
  await page.getByRole('tab', { name: '任务' }).click()
  await page.waitForSelector('.catalog-row', { timeout: 8000 })
  const count = await page.locator('.catalog-row').count()
  expect(count === 53, `期望 53，实际 ${count}`)
})

await check('点击任务名只查看配置，不改变启用状态', async () => {
  const row = page.locator('.catalog-row', { hasText: '六道之门' }).first()
  const before = await row.locator('.switch').getAttribute('aria-checked')
  await row.locator('.catalog-main').click()
  await page.waitForSelector('.config-group', { timeout: 8000 })
  expect(before === await row.locator('.switch').getAttribute('aria-checked'), '启用状态被点击改变了')
})

await check('启用/停用任务经真实 Bridge 写入 Core 并同步计数', async () => {
  const row = page.locator('.catalog-row', { hasText: '六道之门' }).first()
  await row.locator('.switch').click()
  await page.waitForFunction(() => document.querySelector('.topbar-account p')?.textContent?.includes('4 项任务'), null, { timeout: 8000 })
  await row.locator('.switch').click()
  await page.waitForFunction(() => document.querySelector('.topbar-account p')?.textContent?.includes('3 项任务'), null, { timeout: 8000 })
})

await check('脏字段追踪：只提交改动字段，保存后 Core 中的值确实变了', async () => {
  await page.locator('.catalog-row', { hasText: '运行设置' }).first().locator('.catalog-main').click()
  await page.waitForSelector('.config-group', { timeout: 8000 })
  const field = page.locator('.field', { hasText: '截图间隔' }).first()
  const input = field.locator('input[type=number]').first()
  const current = await input.inputValue()
  const next = current === '0.55' ? '0.45' : '0.55'
  await input.fill(next)
  await input.blur()
  await page.waitForSelector('.field.dirty', { timeout: 5000 })

  const bodies = []
  const listener = (request) => {
    if (request.method() === 'PATCH' && request.url().includes('/config')) bodies.push(JSON.parse(request.postData() || '{}'))
  }
  page.on('request', listener)
  await page.getByRole('button', { name: /^保存/ }).click()
  await page.waitForFunction(() => document.querySelector('.panel-head-actions .counter')?.textContent?.includes('已同步'), null, { timeout: 8000 })
  page.off('request', listener)
  expect(bodies.length === 1 && bodies[0].fields.length === 1, `提交内容异常：${JSON.stringify(bodies)}`)

  // 穿透验证：直接问 Bridge（也就是问 Core 的存储）
  const config = await (await fetch(`${BRIDGE}/accounts/oas1/tasks/Script/config`)).json()
  const stored = config.groups.optimization.find((field) => field.name === 'screenshot_interval')?.value
  expect(String(stored) === next, `Core 里的值是 ${stored}，期望 ${next}`)
})

await check('Core 故障时保存给出可读错误，恢复后可重试成功', async () => {
  const field = page.locator('.field', { hasText: '截图间隔' }).first()
  const input = field.locator('input[type=number]').first()
  const current = await input.inputValue()
  await input.fill(current === '0.5' ? '0.6' : '0.5')
  await input.blur()
  await page.waitForSelector('.field.dirty', { timeout: 5000 })
  await mockFault(true)
  try {
    await page.getByRole('button', { name: /^保存/ }).click()
    await page.waitForSelector('.toast.error', { timeout: 8000 })
    expect((await text('.toast.error')).includes('保存失败'), '没有出现保存失败提示')
  } finally {
    await mockFault(false)
  }
  await page.getByRole('button', { name: /^保存/ }).click()
  await page.waitForFunction(() => document.querySelector('.panel-head-actions .counter')?.textContent?.includes('已同步'), null, { timeout: 8000 })
})

await check('配置模板经 Bridge SQLite 持久化并在设置页可见', async () => {
  await page.locator('.template-bar summary').click()
  await page.locator('.template-body input').fill('联调模板A')
  await page.getByRole('button', { name: '存为模板' }).click()
  await page.waitForSelector('.toast', { timeout: 5000 })
  await page.getByRole('tab', { name: '设置' }).click()
  await page.waitForFunction(() => {
    const body = document.querySelector('.settings-view')?.textContent || ''
    return body.includes('联调模板A') && body.includes('Bridge 数据库')
  }, null, { timeout: 8000 })
  await page.locator('.template-list li', { hasText: '联调模板A' }).getByRole('button', { name: '删除' }).click()
  await page.waitForFunction(() => !(document.querySelector('.settings-view')?.textContent || '').includes('联调模板A'), null, { timeout: 5000 })
})

/* ------------------------------------------------------------ 启动与日志 */

await check('启动：状态经 事件WS 变为运行中，日志实时回流', async () => {
  await page.getByRole('tab', { name: '概览' }).click()
  await page.getByRole('button', { name: /▶ 启动/ }).first().click()
  await page.waitForFunction(() => document.querySelector('.topbar-account')?.textContent?.includes('运行中'), null, { timeout: 10000 })
  await page.getByRole('tab', { name: '日志' }).click()
  await page.waitForFunction(() => document.querySelectorAll('.log-line').length >= 3, null, { timeout: 12000 })
})
await shot('r2-running-logs')

await check('日志级别来自 Bridge 解析（能过滤出警告/错误）', async () => {
  await page.waitForFunction(() => document.querySelectorAll('.log-line.warn, .log-line.error').length >= 1, null, { timeout: 12000 })
  const total = await page.locator('.log-line').count()
  await page.locator('.chip.info').click()
  await page.waitForTimeout(300)
  const filtered = await page.locator('.log-line').count()
  expect(filtered < total && filtered >= 1, `过滤异常 ${total} -> ${filtered}`)
  await page.locator('.chip.info').click()
})

await check('停止：确认框 → 状态回到已停止', async () => {
  await page.getByRole('button', { name: /■ 停止/ }).first().click()
  await page.waitForSelector('.dialog', { timeout: 5000 })
  await page.getByRole('button', { name: '停止', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.topbar-account')?.textContent?.includes('已停止'), null, { timeout: 10000 })
})

/* ------------------------------------------------------------ 多账号与生命周期 */

await check('空任务账号 oas3：可选中、不崩溃、计数为 0', async () => {
  await page.locator('.account', { hasText: 'oas3' }).click()
  await page.waitForFunction(() => document.querySelector('.topbar-account h1')?.textContent === 'oas3', null, { timeout: 8000 })
  await page.waitForFunction(() => document.querySelector('.topbar-account p')?.textContent?.includes('0 项任务'), null, { timeout: 8000 })
})

await check('新建账号 → 真实写入 Core → 删除同步移除', async () => {
  await page.getByRole('button', { name: /新建账号/ }).click()
  await page.waitForSelector('.dialog input', { timeout: 5000 })
  await page.locator('.dialog input').fill('oas-e2e')
  await page.getByRole('button', { name: '创建' }).click()
  await page.waitForFunction(() => document.querySelector('.topbar-account h1')?.textContent === 'oas-e2e', null, { timeout: 8000 })
  const coreList = await (await fetch(`${MOCK}/config_list`)).json()
  expect(coreList.includes('oas-e2e'), `Core 配置列表没有新账号：${coreList}`)

  await page.getByRole('tab', { name: '设置' }).click()
  await page.getByRole('button', { name: /删除 oas-e2e/ }).click()
  await page.waitForSelector('.dialog', { timeout: 5000 })
  await page.getByRole('button', { name: '确认删除' }).click()
  await page.waitForFunction(() => document.querySelectorAll('.account').length === 3, null, { timeout: 8000 })
  const afterList = await (await fetch(`${MOCK}/config_list`)).json()
  expect(!afterList.includes('oas-e2e'), `Core 里没删掉：${afterList}`)
})

await check('页面没有 JS 报错', async () => {
  const real = consoleErrors.filter((item) => !item.includes('favicon') && !item.includes('Failed to load resource'))
  expect(real.length === 0, `控制台错误：\n${real.join('\n')}`)
})

await browser.close()

for (const [status, name, message] of results) {
  console.log(`${status === 'PASS' ? '  ✓' : '  ✗'} ${name}${message ? `\n      ${message}` : ''}`)
}
const failed = results.filter(([status]) => status === 'FAIL')
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
process.exit(failed.length ? 1 : 0)
