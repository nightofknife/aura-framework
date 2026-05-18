import { spawn } from 'node:child_process'

const viteCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const electronCommand = process.platform === 'win32' ? 'npx.cmd' : 'npx'
const devServerUrl = process.env.AURA_GUI_DEV_SERVER_URL || 'http://127.0.0.1:5173'

function run(command, args, options = {}) {
  return spawn(command, args, {
    stdio: 'inherit',
    shell: false,
    ...options,
  })
}

function waitForUrl(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const response = await fetch(url)
        if (response.ok) {
          clearInterval(timer)
          resolve()
        }
      } catch {
        // Retry until timeout.
      }
      if (Date.now() > deadline) {
        clearInterval(timer)
        reject(new Error(`Timed out waiting for ${url}`))
      }
    }, 400)
  })
}

const vite = run(viteCommand, ['run', 'dev'])

try {
  await waitForUrl(devServerUrl)
} catch (error) {
  vite.kill()
  throw error
}

const electron = run(electronCommand, ['electron', '.'], {
  env: {
    ...process.env,
    AURA_GUI_DEV_SERVER_URL: devServerUrl,
  },
})

function shutdown() {
  electron.kill()
  vite.kill()
}

electron.on('exit', (code) => {
  vite.kill()
  process.exit(code ?? 0)
})

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)
