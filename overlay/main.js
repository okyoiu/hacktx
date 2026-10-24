// Two always-on-top windows that only this screen shows:
//  - cards: full-screen, transparent and click-through; glass name cards sit beside faces
//  - dock:  small "Top picks" panel; its own window so macOS/Windows can blur what is behind it (real glass)
// `npm run mock` replays shared/mocks/overlay-demo.jsonl instead of listening to the memory service.
const { app, BrowserWindow, ipcMain, screen, systemPreferences } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const MOCK = process.argv.includes('--mock')
const MEMORY_WS = (process.env.MEMORY_URL || 'http://localhost:8000').replace(/^http/, 'ws') + '/ws'
const ENROLL_URL = process.env.ENROLL_URL || 'http://localhost:8000/enroll'
const DOCK = { width: 360, height: 400 }

function overlayWindow(opts, query) {
  const win = new BrowserWindow({
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    skipTaskbar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
    ...opts,
  })
  win.setAlwaysOnTop(true, 'screen-saver')
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  // Keeps it out of screen shares on Windows; newer macOS screen sharing can still capture it.
  win.setContentProtection(true)
  win.loadFile('index.html', { query: { ...query, ws: MEMORY_WS, enroll: ENROLL_URL, mock: MOCK ? '1' : '' } })
  return win
}

function replay(windows) {
  const file = path.join(__dirname, '..', 'shared', 'mocks', 'overlay-demo.jsonl')
  let at = 0
  for (const line of fs.readFileSync(file, 'utf8').split('\n').filter(Boolean)) {
    const { delayMs, event } = JSON.parse(line)
    at += delayMs
    setTimeout(() => windows.forEach((w) => w.webContents.send('event', event)), at)
  }
}

app.whenReady().then(() => {
  const { bounds } = screen.getPrimaryDisplay()

  const cards = overlayWindow({ ...bounds }, { view: 'cards', ox: bounds.x, oy: bounds.y })
  cards.setIgnoreMouseEvents(true, { forward: true })

  const dock = overlayWindow(
    {
      ...DOCK,
      x: bounds.x + bounds.width - DOCK.width - 24,
      y: bounds.y + 48,
      vibrancy: 'hud', // macOS blur
      visualEffectState: 'active', // keep the blur when another app has focus
      backgroundMaterial: 'acrylic', // Windows 11 blur
    },
    { view: 'dock' },
  )

  if (MOCK) cards.webContents.once('did-finish-load', () => replay([cards, dock]))
})

// A card turns clickable while the pointer is over it (e.g. its "Copy invite link" button).
ipcMain.on('click-through', (e, on) => {
  BrowserWindow.fromWebContents(e.sender)?.setIgnoreMouseEvents(on, { forward: true })
})

// The dock fades when the conversation goes quiet. CSS opacity can't reach the OS blur layer, so fade the
// whole window instead (Windows and macOS; Linux ignores window opacity).
const IDLE_OPACITY = 0.3
let fadeTimer
ipcMain.on('dock-idle', (e, idle) => {
  const win = BrowserWindow.fromWebContents(e.sender)
  if (!win) return
  const to = idle ? IDLE_OPACITY : 1
  clearInterval(fadeTimer)
  if (systemPreferences.getAnimationSettings().prefersReducedMotion) return win.setOpacity(to)
  const from = win.getOpacity()
  const ms = idle ? 800 : 200
  const start = Date.now()
  fadeTimer = setInterval(() => {
    const t = Math.min(1, (Date.now() - start) / ms)
    win.setOpacity(from + (to - from) * t)
    if (t === 1) clearInterval(fadeTimer)
  }, 16)
})

app.on('window-all-closed', () => app.quit())
