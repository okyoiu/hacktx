// Always-on-top windows that only this screen shows:
//  - cards:    full-screen, transparent and click-through; glass name cards sit beside faces
//  - bar:      control bar (pause, waveform, timer, Ask AI ⌘↵, Show/Hide ⌘\)
//  - insights: Live insights panel (topic, points, transcript, actions)
//  - response: AI response panel, shown while there is a question or an answer
// Each panel is its own window so macOS/Windows can blur what is behind it (real glass).
// Main owns the event source (the memory service's WebSocket, or the demo replay with `npm run mock`) and
// forwards every event to every window; panels call the memory API through main.
const { app, BrowserWindow, clipboard, globalShortcut, ipcMain, screen, shell, systemPreferences } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { validCall, webUrl } = require('./logic')

const MOCK = process.argv.includes('--mock')
const MEMORY_URL = process.env.MEMORY_URL || 'http://localhost:8000'
const ENROLL_URL = process.env.ENROLL_URL || 'http://localhost:8000/enroll'
const PEOPLE_SIZE = { width: 760, height: 540 }
const PANEL = { width: 448, gap: 12, margin: 24 }
const BAR_HEIGHT = 56
const IDLE_OPACITY = 0.3

const windows = {}
const shownBeforeHide = new Set()
const closing = new Set() // windows fading out to hidden; idle fades and Show/Hide must not stop that
let allHidden = false
let closedResponse = null // the answer the user closed; its late events must not reopen the panel
let lastInsights = null

function overlayWindow(query, opts) {
  const win = new BrowserWindow({
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    skipTaskbar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
    },
    ...opts,
  })
  win.setAlwaysOnTop(true, 'screen-saver')
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  // Keeps it out of screen shares on Windows; newer macOS screen sharing can still capture it.
  win.setContentProtection(true)
  // Source links open in the browser; nothing navigates the overlay itself.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (webUrl(url)) shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (e) => e.preventDefault())
  win.webContents.on('will-attach-webview', (e) => e.preventDefault())
  // The overlay needs no camera, microphone or other permission of its own.
  win.webContents.session.setPermissionRequestHandler((_wc, _permission, deny) => deny(false))
  win.loadFile('index.html', { query: { ...query, mock: MOCK ? '1' : '' } })
  return win
}

function panelWindow(view, bounds) {
  return overlayWindow({ view }, {
    ...bounds,
    acceptFirstMouse: true, // the first click on an inactive panel still presses the button under it
    vibrancy: 'hud', // macOS blur
    visualEffectState: 'active', // keep the blur when the call app has focus
    backgroundMaterial: 'acrylic', // Windows 11 blur
  })
}

// ---------- showing, hiding and fading ----------

const fades = new Map()

// Fades a whole window, OS blur included; CSS opacity can't reach the blur layer. Linux ignores window opacity.
function fade(win, to, ms, done) {
  clearInterval(fades.get(win))
  if (systemPreferences.getAnimationSettings().prefersReducedMotion) ms = 0
  const from = win.getOpacity()
  const start = Date.now()
  const step = () => {
    const t = ms ? Math.min(1, (Date.now() - start) / ms) : 1
    win.setOpacity(from + (to - from) * t)
    if (t < 1) return
    clearInterval(fades.get(win))
    done?.()
  }
  fades.set(win, setInterval(step, 16))
  step()
}

function reveal(win) {
  if (allHidden) return shownBeforeHide.add(win)
  closing.delete(win)
  if (!win.isVisible()) {
    win.setOpacity(0)
    win.showInactive()
  }
  fade(win, 1, 220)
}

function conceal(win) {
  shownBeforeHide.delete(win)
  if (!win.isVisible()) return
  closing.add(win)
  fade(win, 0, 160, () => {
    closing.delete(win)
    win.hide()
  })
}

function toggleAll() {
  allHidden = !allHidden
  for (const win of Object.values(windows)) {
    if (allHidden && win.isVisible() && !closing.has(win)) {
      conceal(win)
      shownBeforeHide.add(win)
    } else if (!allHidden && shownBeforeHide.delete(win)) reveal(win)
  }
}

// The People dashboard: its own window, centred, opened by the control bar or ⌘⇧P, works without a call.
function togglePeople() {
  const win = windows.people
  if (win.isVisible() && !closing.has(win)) return conceal(win)
  if (allHidden) toggleAll()
  reveal(win)
  if (process.platform === 'darwin') app.focus({ steal: true })
  win.focus()
  win.webContents.send('people-open')
}

function openAsk() {
  if (allHidden) toggleAll()
  closedResponse = null
  reveal(windows.response)
  // typing needs keyboard focus; this is the one moment the overlay takes it from the call
  if (process.platform === 'darwin') app.focus({ steal: true })
  windows.response.focus()
  windows.response.webContents.send('ask')
}

// ---------- events in ----------

function broadcast(event) {
  if (event.type === 'insights') lastInsights = event
  if (MOCK && event.type === 'face') demoFaces.set(event.trackId, event)
  if (MOCK && event.type === 'face_gone') demoFaces.delete(event.trackId)
  if (event.type === 'response' && event.id !== closedResponse) reveal(windows.response)
  for (const win of Object.values(windows)) win.webContents.send('event', event)
}

function status(state) {
  for (const win of Object.values(windows)) win.webContents.send('status', state)
}

function connect() {
  const ws = new WebSocket(MEMORY_URL.replace(/^http/, 'ws') + '/ws')
  ws.onopen = () => status('on')
  ws.onmessage = (m) => {
    try {
      broadcast(JSON.parse(m.data))
    } catch (err) {
      console.error('Skipped a malformed event:', err.message)
    }
  }
  ws.onclose = () => {
    status('off')
    setTimeout(connect, 2000)
  }
}

const demoStart = new Date().toISOString()

function replay() {
  const file = path.join(__dirname, '..', 'shared', 'mocks', 'overlay-demo.jsonl')
  let at = 0
  for (const line of fs.readFileSync(file, 'utf8').split('\n').filter(Boolean)) {
    const { delayMs, event } = JSON.parse(line)
    at += delayMs
    if (event.startedAt) event.startedAt = demoStart // the demo's timer starts at 00:00, not at the sample date
    setTimeout(() => broadcast(event), at)
  }
}

// The demo answers locally, so clicking around in `npm run mock` never posts to a real memory service.
let demoAnswers = 0
const demoFaces = new Map()
const demoPeople = [
  { id: 'p_jordan', name: 'Jordan Lee', role: 'Your team lead', firstMet: '2026-09-24T18:00:00Z', lastMet: '2026-10-24T18:00:00Z', lastTime: 'Talked about the move to Austin.' },
  { id: 'p_maya', name: 'Maya Chen', role: '', firstMet: '2026-10-01T18:00:00Z', lastMet: '2026-10-20T18:00:00Z', lastTime: 'Asked about climbing gyms.' },
]
function demoPeopleApi(route, body, method) {
  const id = route.split('/')[2]
  const person = demoPeople.find((p) => p.id === id)
  if (!id) return demoPeople
  if (!person) return { error: 'Nobody with that id.', status: 404 }
  if (method === 'DELETE') demoPeople.splice(demoPeople.indexOf(person), 1)
  if (method === 'PATCH') person.role = body.role ?? person.role
  if (method !== 'GET') return method === 'PATCH' ? person : { deleted: id }
  return { ...person, encounters: [{ about: 'Sample', lastTime: person.lastTime, date: person.lastMet }], notes: [{ text: 'A sample note from the demo.' }] }
}

function demoApi(route, body, method) {
  if (route.startsWith('/people')) return demoPeopleApi(route, body, method)
  const remember = route.match(/^\/faces\/(\d+)\/remember$/)
  if (remember) {
    const face = demoFaces.get(+remember[1])
    if (!face) return { error: 'That face has left the call.', status: 409 }
    broadcast({ ...face, person: { id: `p_demo${++demoAnswers}`, name: body.name, line: '', met: 'Met today' } })
    return { id: 'p_demo', deleteToken: 'demo' }
  }
  if (route === '/listening') {
    broadcast({ type: 'listening', on: body.on, startedAt: demoStart })
    return {}
  }
  const id = `demo${++demoAnswers}`
  const action = lastInsights?.actions.find((a) => route === `/actions/${encodeURIComponent(a.id)}`)
  const query = body?.question || action?.label || 'Sample question'
  broadcast({ type: 'response', id, query, status: 'thinking', text: '', sources: [] })
  const text = 'This is a sample answer from the demo replay.\nStart the memory service to get real answers.'
  setTimeout(() => broadcast({ type: 'response', id, query, status: 'done', text, sources: [] }), 1800)
  return { id }
}

// ---------- calls from the panels ----------

// Resolves to the service's JSON, or to { error } with a sentence the panel can show as is.
ipcMain.handle('api', async (e, route, body, method = 'POST') => {
  if (!ours(e) || !validCall(route, body, method)) return { error: 'The overlay never makes that call.' }
  if (MOCK) return demoApi(route, body, method)
  try {
    const res = await fetch(MEMORY_URL + route, {
      method,
      headers: body ? { 'content-type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    })
    const data = await res.json().catch(() => ({}))
    if (res.ok) return data
    // the service explains refusals in `detail`, such as an action left over from before a restart
    return { error: typeof data.detail === 'string' ? data.detail : `Hello Again answered ${res.status}. Try again.`, status: res.status }
  } catch {
    return { error: "Couldn't reach Hello Again. Check it's running, then try again." }
  }
})

// Only our own pages (local files) may use the channels below.
const ours = (e) => e.senderFrame?.url.startsWith('file://')
const on = (channel, handler) => ipcMain.on(channel, (e, ...args) => ours(e) && handler(e, ...args))

// Panels grow and shrink with their content, so the blur never shows past the glass, and stop at the screen's edge.
on('fit', (e, height) => {
  const win = BrowserWindow.fromWebContents(e.sender)
  const bounds = win?.getBounds()
  if (!bounds || !(height > 0)) return
  const { workArea } = screen.getDisplayMatching(bounds)
  const fitted = Math.min(Math.ceil(height), workArea.y + workArea.height - bounds.y)
  if (bounds.height !== fitted) win.setBounds({ ...bounds, height: fitted })
})

on('panel-idle', (e, idle) => {
  if (typeof idle !== 'boolean') return
  const win = BrowserWindow.fromWebContents(e.sender)
  if (win?.isVisible() && !allHidden && !closing.has(win)) fade(win, idle ? IDLE_OPACITY : 1, idle ? 800 : 200)
})

on('copy', (_e, text) => typeof text === 'string' && clipboard.writeText(text.slice(0, 20000)))
// A thinking pill takes the mouse while the pointer is over it, and the keyboard while its form is open.
on('click-through', (_e, on) => windows.cards.setIgnoreMouseEvents(Boolean(on), { forward: true }))
on('cards-focus', (_e, on) => {
  if (on) {
    windows.cards.setFocusable(true)
    windows.cards.focus()
  } else {
    if (windows.cards.isFocused()) windows.cards.blur() // the keyboard goes back to the call app
    windows.cards.setFocusable(false)
  }
})
on('copy-invite', () => clipboard.writeText(ENROLL_URL))
on('ask', openAsk)
on('people-toggle', togglePeople)
on('toggle-all', toggleAll)
on('close-response', (_e, id) => {
  if (typeof id !== 'string') return
  closedResponse = id
  conceal(windows.response)
})

// ---------- start ----------

app.whenReady().then(async () => {
  const { bounds, workArea } = screen.getPrimaryDisplay()
  const right = workArea.x + workArea.width - PANEL.margin
  const top = workArea.y + PANEL.margin / 2
  const below = top + BAR_HEIGHT + PANEL.gap

  // A macOS panel takes typing for "Remember them" without activating the overlay, so the call app keeps focus.
  // It can only take the keyboard while that form is open (cards-focus); clicks still land without it.
  const panel = process.platform === 'darwin' ? { type: 'panel' } : {}
  windows.cards = overlayWindow({ view: 'cards', ox: bounds.x, oy: bounds.y }, { ...bounds, ...panel, focusable: false, acceptFirstMouse: true })
  windows.cards.setIgnoreMouseEvents(true, { forward: true }) // click-through, but hover still reaches thinking pills
  windows.bar = panelWindow('bar', { width: PANEL.width, height: BAR_HEIGHT, x: right - PANEL.width, y: top })
  windows.response = panelWindow('response', { width: PANEL.width, height: 160, x: right - PANEL.width, y: below })
  windows.insights = panelWindow('insights', {
    width: PANEL.width,
    height: 200,
    x: Math.max(workArea.x + PANEL.margin, right - 2 * PANEL.width - PANEL.gap),
    y: below,
  })

  const { workArea: area } = screen.getPrimaryDisplay()
  windows.people = panelWindow('people', {
    ...PEOPLE_SIZE,
    x: Math.round(area.x + (area.width - PEOPLE_SIZE.width) / 2),
    y: Math.round(area.y + (area.height - PEOPLE_SIZE.height) / 2),
  })

  await Promise.all(Object.values(windows).map((win) => new Promise((r) => win.webContents.once('did-finish-load', r))))
  windows.cards.showInactive()
  reveal(windows.bar)
  reveal(windows.insights)

  const shortcuts = { 'CommandOrControl+Return': openAsk, 'CommandOrControl+Shift+P': togglePeople, 'CommandOrControl+\\': toggleAll }
  for (const [keys, run] of Object.entries(shortcuts)) {
    if (!globalShortcut.register(keys, run)) console.warn(`${keys} is taken by another app; use the control bar instead`)
  }

  if (MOCK) {
    status('demo')
    replay()
  } else connect()
})

// Clicking the Dock icon brings a hidden overlay back, in case another app owns ⌘\.
app.on('activate', () => allHidden && toggleAll())
app.on('will-quit', () => globalShortcut.unregisterAll())
app.on('window-all-closed', () => app.quit())
