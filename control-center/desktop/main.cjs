const { app, BrowserWindow, Menu, dialog } = require('electron')
const { spawn } = require('child_process')
const fs = require('fs')
const http = require('http')
const path = require('path')

const BRIDGE_PORT = Number(process.env.OAS_BRIDGE_PORT || 22367)
const CORE_URL = process.env.OAS_CORE_URL || 'http://127.0.0.1:22267'
let bridgeProcess = null
let mainWindow = null

function installChineseMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: '系统',
      submenu: [
        { label: '刷新界面', role: 'reload' },
        { type: 'separator' },
        { label: '退出', role: 'quit' },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { label: '撤销', role: 'undo' },
        { label: '重做', role: 'redo' },
        { type: 'separator' },
        { label: '剪切', role: 'cut' },
        { label: '复制', role: 'copy' },
        { label: '粘贴', role: 'paste' },
        { label: '全选', role: 'selectAll' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { label: '重新加载', role: 'reload' },
        { label: '切换开发者工具', role: 'toggleDevTools' },
      ],
    },
    {
      label: '窗口',
      submenu: [
        { label: '最小化', role: 'minimize' },
        { label: '缩放', role: 'zoom' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        { label: '关于 OAS 控制中心', click: () => dialog.showMessageBox({ type: 'info', title: '关于 OAS 控制中心', message: 'OAS 控制中心', detail: '独立前端 · 本机模式' }) },
      ],
    },
  ]))
}

function bridgeExecutable() {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'bridge', 'oas-control-bridge.exe')
    : path.join(__dirname, 'bridge-dist', 'oas-control-bridge.exe')
}

function uiIndex() {
  return path.join(app.getAppPath(), 'ui', 'index.html')
}

function dataDirectory() {
  return path.join(app.getPath('userData'), 'data')
}

function prepareDataDirectory() {
  const target = dataDirectory()
  fs.mkdirSync(target, { recursive: true })
  const seed = app.isPackaged
    ? path.join(process.resourcesPath, 'data-seed', 'control_center.db')
    : path.join(__dirname, 'data-seed', 'control_center.db')
  const database = path.join(target, 'control_center.db')
  if (!fs.existsSync(database) && fs.existsSync(seed)) fs.copyFileSync(seed, database)
  return target
}

function probeBridge(timeoutMs = 700) {
  return new Promise((resolve) => {
    const request = http.get({ host: '127.0.0.1', port: BRIDGE_PORT, path: '/api/v1/health', timeout: timeoutMs }, (response) => {
      response.resume()
      resolve(response.statusCode >= 200 && response.statusCode < 500)
    })
    request.on('error', () => resolve(false))
    request.on('timeout', () => { request.destroy(); resolve(false) })
  })
}

function startBridge(dataDir) {
  const executable = bridgeExecutable()
  if (!fs.existsSync(executable)) {
    dialog.showErrorBox('控制中心启动失败', `找不到 Bridge 程序：${executable}`)
    return false
  }
  bridgeProcess = spawn(executable, [], {
    cwd: path.dirname(executable),
    windowsHide: true,
    stdio: 'ignore',
    env: {
      ...process.env,
      OAS_CORE_URL: CORE_URL,
      OAS_BRIDGE_PORT: String(BRIDGE_PORT),
      OAS_CONTROL_CENTER_DATA_DIR: dataDir,
    },
  })
  bridgeProcess.on('error', (error) => dialog.showErrorBox('Bridge 启动失败', error.message))
  return true
}

async function waitForBridge(timeoutMs = 12000) {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    if (await probeBridge()) return true
    await new Promise((resolve) => setTimeout(resolve, 180))
  }
  return false
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1680,
    height: 980,
    minWidth: 1280,
    minHeight: 760,
    show: false,
    backgroundColor: '#edf2f7',
    webPreferences: {
      preload: path.join(app.getAppPath(), 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  await mainWindow.loadFile(uiIndex())
  mainWindow.once('ready-to-show', () => mainWindow.show())
}

app.whenReady().then(async () => {
  installChineseMenu()
  const dataDir = prepareDataDirectory()
  if (!(await probeBridge())) startBridge(dataDir)
  await waitForBridge()
  await createWindow()
})

app.on('before-quit', () => {
  if (bridgeProcess && !bridgeProcess.killed) bridgeProcess.kill()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
