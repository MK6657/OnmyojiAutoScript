/**
 * UI-claude 端到端回归。
 * 对着 mock bridge 跑真实交互，失败即退出非零。
 */
import { chromium } from 'playwright'

const BASE = process.env.UI_CLAUDE_BASE || "http://127.0.0.1:4175/"
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
const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `shots/${name}.png`, fullPage: false }) }

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })
page = await context.newPage()
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`))

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('.app', { timeout: 8000 })

await check('账号列表加载出 3 个账号', async () => {
  const count = await page.locator('.account').count()
  expect(count === 3, `期望 3 个账号，实际 ${count}`)
})

await check('概览显示启动前检查并识别未绑定设备', async () => {
  await page.waitForSelector('.checklist li', { timeout: 5000 })
  const body = await text('.overview')
  expect(body.includes('启动前检查'), '没有渲染启动前检查')
  expect(body.includes('任务调度'), '没有渲染任务调度')
})
await shot('01-overview-dark')

await check('切到任务页并加载 53 项任务目录', async () => {
  await page.getByRole('tab', { name: '任务' }).click()
  await page.waitForSelector('.catalog-row', { timeout: 5000 })
  const count = await page.locator('.catalog-row').count()
  expect(count === 53, `期望 53 项任务，实际 ${count}`)
})

await check('点击任务名只查看配置，不改变启用状态', async () => {
  const row = page.locator('.catalog-row', { hasText: '六道之门' }).first()
  const before = await row.locator('.switch').getAttribute('aria-checked')
  await row.locator('.catalog-main').click()
  await page.waitForSelector('.config-group', { timeout: 5000 })
  const after = await row.locator('.switch').getAttribute('aria-checked')
  expect(before === after, `点击名称后启用状态从 ${before} 变成了 ${after}`)
  expect((await text('.panel.settings .panel-head')).includes('六道之门'), '配置面板没有切到六道之门')
})
await shot('02-tasks-config')

await check('开关可以启用任务并同步到已启用计数', async () => {
  const row = page.locator('.catalog-row', { hasText: '六道之门' }).first()
  await row.locator('.switch').click()
  await page.waitForFunction(() => document.querySelector('.topbar-account p')?.textContent?.includes('5 项任务'), null, { timeout: 6000 })
  expect((await row.locator('.switch').getAttribute('aria-checked')) === 'true', '开关没有变成启用')
})

await check('再次点击开关可以停用', async () => {
  const row = page.locator('.catalog-row', { hasText: '六道之门' }).first()
  await row.locator('.switch').click()
  await page.waitForFunction(() => document.querySelector('.topbar-account p')?.textContent?.includes('4 项任务'), null, { timeout: 6000 })
})

await check('修改字段出现未保存标记，且只提交改动字段', async () => {
  await page.locator('.catalog-row', { hasText: '运行设置' }).first().locator('.catalog-main').click()
  await page.waitForSelector('.config-group', { timeout: 5000 })
  const field = page.locator('.field', { hasText: '截图间隔' }).first()
  const input = (await field.count()) ? field.locator('input[type=number]').first() : page.locator('.field input[type=number]').first()
  const current = await input.inputValue()
  await input.fill(current === '0.55' ? '0.45' : '0.55')
  await input.blur()
  await page.waitForSelector('.field.dirty', { timeout: 4000 })
  const badge = await text('.panel-head-actions .counter')
  expect(badge.includes('1 项未保存'), `未保存计数不对：${badge}`)

  const requests = []
  page.on('request', (request) => {
    if (request.method() === 'PATCH' && request.url().includes('/config')) requests.push(JSON.parse(request.postData() || '{}'))
  })
  await page.getByRole('button', { name: /^保存/ }).click()
  await page.waitForSelector('.toast', { timeout: 5000 })
  await page.waitForTimeout(300)
  expect(requests.length === 1, `期望 1 次保存请求，实际 ${requests.length}`)
  expect(requests[0].fields.length === 1, `期望只提交 1 个字段，实际 ${requests[0].fields.length}`)
})

await check('保存后未保存计数归零', async () => {
  await page.waitForFunction(() => document.querySelector('.panel-head-actions .counter')?.textContent?.includes('已同步'), null, { timeout: 5000 })
})

await check('切换任务时未保存改动会弹确认框', async () => {
  const input = page.locator('.field input[type=number]').first()
  const before = await input.inputValue()
  await input.fill(before === '0.77' ? '0.66' : '0.77')
  await input.blur()
  await page.waitForSelector('.field.dirty', { timeout: 4000 })
  await page.locator('.catalog-row', { hasText: '御魂整理' }).first().locator('.catalog-main').click()
  await page.waitForSelector('.dialog', { timeout: 4000 })
  expect((await text('.dialog h3')).includes('未保存'), '确认框标题不对')
  await page.getByRole('button', { name: '取消' }).click()
  await page.waitForTimeout(200)
  expect(await page.locator('.field.dirty').count() > 0, '取消后改动应当还在')
  await page.getByRole('button', { name: '放弃改动' }).click()
  await page.waitForFunction(() => !document.querySelector('.field.dirty'), null, { timeout: 4000 })
})

await check('保存失败时给出可读的错误提示', async () => {
  await page.locator('.catalog-row', { hasText: '运行设置' }).first().locator('.catalog-main').click()
  await page.waitForSelector('.config-group', { timeout: 5000 })
  const manual = page.locator('.window-manual').first()
  await manual.fill('999')
  await manual.blur()
  await page.waitForSelector('.field.dirty', { timeout: 4000 })
  await page.getByRole('button', { name: /^保存/ }).click()
  await page.waitForSelector('.toast.error', { timeout: 5000 })
  const message = await text('.toast.error')
  expect(message.includes('保存失败'), `错误提示不对：${message}`)
  await page.getByRole('button', { name: '放弃改动' }).click()
})

await check('窗口选择器能列出模拟器窗口', async () => {
  const options = await page.locator('.window-picker select option').allInnerTexts()
  expect(options.some((item) => item.includes('MuMu')), `窗口列表里没有 MuMu：${options.join(' | ')}`)
})

await check('日志页可以按级别过滤', async () => {
  await page.getByRole('tab', { name: '日志' }).click()
  await page.waitForSelector('.log-line', { timeout: 5000 })
  const total = await page.locator('.log-line').count()
  await page.locator('.chip.info').click()
  await page.waitForTimeout(250)
  const filtered = await page.locator('.log-line').count()
  expect(filtered < total, `过滤后条数应减少，${total} -> ${filtered}`)
  await page.locator('.chip.info').click()
})
await shot('03-logs')

await check('切换到浅色主题并保持可读', async () => {
  await page.getByRole('tab', { name: '设置' }).click()
  await page.waitForSelector('.segmented', { timeout: 5000 })
  await page.getByRole('button', { name: '浅色' }).click()
  await page.waitForTimeout(250)
  const theme = await page.evaluate(() => document.documentElement.dataset.theme)
  expect(theme === 'light', `主题没切换：${theme}`)
})
await shot('04-settings-light')

await check('浅色主题下概览可读', async () => {
  await page.getByRole('tab', { name: '概览' }).click()
  await page.waitForSelector('.hero', { timeout: 5000 })
})
await shot('05-overview-light')

await check('切换账号后任务与日志跟随账号', async () => {
  await page.getByRole('button', { name: '深色' }).count()
  await page.locator('.account', { hasText: 'oas2' }).click()
  await page.waitForFunction(() => document.querySelector('.topbar-account h1')?.textContent === 'oas2', null, { timeout: 5000 })
  await page.waitForFunction(() => document.querySelector('.topbar-account p')?.textContent?.includes('6 项任务'), null, { timeout: 6000 })
})

await check('运行中的账号显示停止按钮', async () => {
  const label = await text('.topbar-actions .btn')
  expect(label.includes('停止'), `oas2 是运行中，按钮应为停止，实际 ${label}`)
})

await check('新建账号对话框可以创建账号', async () => {
  await page.getByRole('button', { name: /新建账号/ }).click()
  await page.waitForSelector('.dialog input', { timeout: 4000 })
  await page.locator('.dialog input').fill('oas-test')
  await page.getByRole('button', { name: '创建' }).click()
  await page.waitForFunction(() => document.querySelector('.topbar-account h1')?.textContent === 'oas-test', null, { timeout: 6000 })
  expect(await page.locator('.account').count() === 4, '账号数量没有增加')
})

await check('删除账号需要二次确认', async () => {
  await page.getByRole('tab', { name: '设置' }).click()
  await page.waitForSelector('.danger-zone', { timeout: 4000 })
  await page.getByRole('button', { name: /删除 oas-test/ }).click()
  await page.waitForSelector('.dialog', { timeout: 4000 })
  await page.getByRole('button', { name: '确认删除' }).click()
  await page.waitForFunction(() => document.querySelectorAll('.account').length === 3, null, { timeout: 6000 })
})

await check('1280×760 小窗口下没有横向溢出', async () => {
  await page.setViewportSize({ width: 1280, height: 760 })
  await page.getByRole('tab', { name: '任务' }).click()
  await page.waitForSelector('.catalog-row', { timeout: 5000 })
  await page.waitForTimeout(300)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow <= 1, `横向溢出 ${overflow}px`)
  const vertical = await page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight)
  expect(vertical <= 1, `页面整体出现纵向滚动 ${vertical}px（应由各面板自己滚动）`)
})
await shot('06-compact-1280')

await check('紧凑密度在 1180×680 也放得下', async () => {
  await page.setViewportSize({ width: 1180, height: 680 })
  await page.getByRole('tab', { name: '设置' }).click()
  await page.waitForSelector('.segmented', { timeout: 4000 })
  await page.getByRole('button', { name: '紧凑' }).click()
  await page.getByRole('tab', { name: '任务' }).click()
  await page.waitForTimeout(350)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow <= 1, `紧凑模式仍横向溢出 ${overflow}px`)
})
await shot('07-compact-1180')

await check('页面没有 JS 报错', async () => {
  const real = consoleErrors.filter((item) => !item.includes('favicon') && !item.includes('Failed to load resource'))
  expect(real.length === 0, `控制台错误：\n${real.join('\n')}`)
})

await browser.close()

const failed = results.filter(([status]) => status === 'FAIL')
for (const [status, name, message] of results) {
  console.log(`${status === 'PASS' ? '  ✓' : '  ✗'} ${name}${message ? `\n      ${message}` : ''}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
process.exit(failed.length ? 1 : 0)
