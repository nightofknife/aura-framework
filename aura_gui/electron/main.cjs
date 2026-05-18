const { app, BrowserWindow, ipcMain, shell } = require('electron')
const fs = require('node:fs/promises')
const path = require('node:path')
const os = require('node:os')

const DEFAULT_RUNTIME_PORT = 18098
const DEFAULT_API_BASE = `http://127.0.0.1:${DEFAULT_RUNTIME_PORT}/api/v1`
const DEFAULT_WS_BASE = `ws://127.0.0.1:${DEFAULT_RUNTIME_PORT}`
const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1'])
const MAX_TOKEN_BYTES = 4096

let mainWindow = null
let tokenPathAllowlist = new Set()

function runtimeRegistryPaths() {
  const paths = []
  if (process.env.AURA_RUNTIME_REGISTRY_PATH) paths.push(process.env.AURA_RUNTIME_REGISTRY_PATH)

  const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local')
  const appData = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming')
  paths.push(path.join(localAppData, 'Aura', 'runtime-registry.json'))
  paths.push(path.join(appData, 'Aura', 'runtime-registry.json'))

  return [...new Set(paths.map((item) => path.resolve(item)))]
}

function isLoopbackHttpUrl(value) {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && LOOPBACK_HOSTS.has(url.hostname)
  } catch {
    return false
  }
}

function toWsBase(apiBase) {
  try {
    const url = new URL(apiBase)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${url.host}`
  } catch {
    return DEFAULT_WS_BASE
  }
}

function normalizeRuntimeInstance(instance, sourcePath) {
  const apiBase = instance.api_base || instance.apiBase || instance.api_url || instance.apiUrl
  if (!apiBase || !isLoopbackHttpUrl(apiBase)) return null

  const basePath = instance.base_path || instance.basePath || ''
  const tokenPath = instance.token_path || instance.tokenPath || ''
  const normalizedTokenPath = tokenPath ? path.resolve(tokenPath) : ''
  const runtimePort = Number(instance.info_port || instance.api_port || instance.port || new URL(apiBase).port || DEFAULT_RUNTIME_PORT)

  return {
    id: String(instance.id || instance.name || apiBase),
    version: instance.version || '',
    host: instance.host || new URL(apiBase).hostname || '127.0.0.1',
    port: runtimePort,
    infoPort: runtimePort,
    apiBase,
    wsBase: instance.ws_base || instance.wsBase || toWsBase(apiBase),
    basePath: basePath ? path.resolve(basePath) : '',
    tokenPath: normalizedTokenPath,
    status: instance.status || 'unknown',
    source: sourcePath,
  }
}

async function readRuntimeRegistry(registryPath) {
  try {
    const raw = await fs.readFile(registryPath, 'utf8')
    const parsed = JSON.parse(raw)
    const instances = Array.isArray(parsed.instances) ? parsed.instances : []
    return instances
      .map((instance) => normalizeRuntimeInstance(instance, registryPath))
      .filter(Boolean)
  } catch (error) {
    if (error?.code === 'ENOENT') return []
    return []
  }
}

async function probeRuntime(apiBase) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 900)
  try {
    const response = await fetch(`${apiBase.replace(/\/$/, '')}/system/health`, {
      signal: controller.signal,
    })
    return response.ok ? 'running' : `http_${response.status}`
  } catch {
    return 'unreachable'
  } finally {
    clearTimeout(timer)
  }
}

async function getRuntimeCandidates() {
  const registryCandidates = []
  for (const registryPath of runtimeRegistryPaths()) {
    registryCandidates.push(...(await readRuntimeRegistry(registryPath)))
  }

  const envApiBase = process.env.AURA_API_BASE_URL
  const candidates = [
    ...registryCandidates,
    normalizeRuntimeInstance(
      {
        id: 'default-local',
        api_base: envApiBase && isLoopbackHttpUrl(envApiBase) ? envApiBase : DEFAULT_API_BASE,
        ws_base: envApiBase ? toWsBase(envApiBase) : DEFAULT_WS_BASE,
        token_path: process.env.AURA_LOCAL_API_TOKEN_PATH || '',
        status: 'unknown',
      },
      'default'
    ),
  ].filter(Boolean)

  const deduped = []
  const seen = new Set()
  for (const candidate of candidates) {
    const key = candidate.apiBase
    if (seen.has(key)) continue
    seen.add(key)
    const health = await probeRuntime(candidate.apiBase)
    const nextCandidate = { ...candidate, health }
    deduped.push(nextCandidate)
    if (nextCandidate.tokenPath) tokenPathAllowlist.add(nextCandidate.tokenPath)
  }
  return deduped
}

async function readRuntimeToken(tokenPath) {
  const resolved = path.resolve(String(tokenPath || ''))
  if (!tokenPathAllowlist.has(resolved)) {
    throw new Error('Token path is not registered for a discovered Aura runtime.')
  }

  const stat = await fs.stat(resolved)
  if (!stat.isFile() || stat.size > MAX_TOKEN_BYTES) {
    throw new Error('Token file is not a small regular file.')
  }

  const raw = await fs.readFile(resolved, 'utf8')
  return raw.trim()
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 880,
    minWidth: 1080,
    minHeight: 720,
    title: 'Aura',
    backgroundColor: '#0b1020',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  const devServerUrl = process.env.AURA_GUI_DEV_SERVER_URL
  if (devServerUrl) {
    mainWindow.loadURL(devServerUrl)
    if (process.env.AURA_GUI_OPEN_DEVTOOLS === '1') mainWindow.webContents.openDevTools()
    return
  }

  mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
}

ipcMain.handle('aura:runtime:candidates', async () => getRuntimeCandidates())
ipcMain.handle('aura:runtime:read-token', async (_event, tokenPath) => readRuntimeToken(tokenPath))
ipcMain.handle('aura:shell:open-external', async (_event, url) => {
  const parsed = new URL(url)
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Unsupported external URL protocol.')
  return shell.openExternal(parsed.toString())
})

app.whenReady().then(() => {
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
