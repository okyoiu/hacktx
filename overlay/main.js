// Always-on-top windows that only this screen shows:
//  - cards:      full-screen, transparent and click-through; glass name cards sit beside faces (and the debug view)
//  - bar:        control strip (pause, waveform, timer, Ask AI ⌘↵, End call, People, Show/Hide ⌘\)
//  - insights:   Live insights (topic, points, actions), in the preset's rail
//  - response:   Ask AI: a thread of questions and answers, under Live insights, nudged clear of faces
//  - transcript: a slim strip of captions along the bottom, off until "Show transcript"
//  - recap:      the Recap at the end of the call, centred over the call window
//  - people:     the People dashboard
// Each panel is its own window so macOS/Windows can blur what is behind it (real glass). Where each one sits
// comes from logic.js `layoutFor` (a preset per call app) and follows the `window` event.
// Main owns the event source (the memory service's WebSocket, or the demo replay with `npm run mock`) and
// forwards every event to every window; panels call the memory API through main.
const { app, BrowserWindow, clipboard, globalShortcut, ipcMain, screen, shell, systemPreferences } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { inviteLink, validCall, webUrl, layoutFor, askPlace, recapFrom, devMode } = require('./logic')
const { createLauncher } = require('./launcher')

// The repo's .env supplies ENROLL_CODE, ENROLL_URL and MEMORY_URL; variables already set win.
try {
  process.loadEnvFile(path.join(__dirname, '..', '.env'))
} catch {}

const MOCK = process.argv.includes('--mock')
// Developer mode (`npm run dev`): the debug view exists, and the processes the launcher starts inherit HELLO_DEBUG.
const DEV = devMode(process.argv, process.env)
if (DEV) process.env.HELLO_DEBUG = '1'
const MEMORY_URL = process.env.MEMORY_URL || 'http://localhost:8000'
const ENROLL_URL = process.env.ENROLL_URL || 'http://localhost:8000/enroll'
const PEOPLE_SIZE = { width: 760, height: 540 }
const IDLE_OPACITY = 0.3
const RECAP_WAIT_MS = 15_000 // after End call, how long to wait for the server's recap before building one here
const ICON = path.join(__dirname, 'icon.png')

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
    icon: ICON,
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
  // only main can turn the debug view on, by loading the page with it; nothing over IPC or the network can
  win.loadFile(path.join(__dirname, 'index.html'), { query: { ...query, mock: MOCK ? '1' : '', debug: DEV ? '1' : '' } })
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

const showing = (win) => win.isVisible() && !closing.has(win)

function toggleAll() {
  allHidden = !allHidden
  for (const win of Object.values(windows)) {
    if (allHidden && showing(win)) {
      conceal(win)
      shownBeforeHide.add(win)
    } else if (!allHidden && shownBeforeHide.delete(win)) reveal(win)
  }
}

// The People dashboard: its own window, centred, opened by the control bar or ⌘⇧P, works without a call.
function togglePeople() {
  const win = windows.people
  if (showing(win)) return conceal(win)
  if (allHidden) toggleAll()
  reveal(win)
  if (process.platform === 'darwin') app.focus({ steal: true })
  win.focus()
  win.webContents.send('people-open')
}

// Ask AI (⌘↵ or the button): a fresh thread in the preset's spot, nudged clear of faces and controls.
function openAsk() {
  if (allHidden) toggleAll()
  closedResponse = null
  placeAsk(true)
  reveal(windows.response)
  // typing needs keyboard focus; this is the one moment the overlay takes it from the call
  if (process.platform === 'darwin') app.focus({ steal: true })
  windows.response.focus()
  windows.response.webContents.send('ask')
}

function toggleTranscript() {
  const win = windows.transcript
  if (showing(win)) conceal(win)
  else reveal(win)
  windows.insights.webContents.send('transcript-shown', !showing(win) ? false : true)
}

// ---------- where everything sits ----------

let callWindow = { app: null, rect: null } // the followed call window, from the `window` event
let layout = null
let insightsHeight = 220
let askBusy = false // the Ask AI input is focused or holds text: the panel must not move
const faces = new Map() // trackId -> the latest face event, to keep Ask AI off people

const workAreaFor = (rect) => (rect ? screen.getDisplayMatching({ x: rect[0], y: rect[1], width: rect[2], height: rect[3] }) : screen.getPrimaryDisplay()).workArea

function move(win, spot) {
  const bounds = win.getBounds()
  const next = { ...bounds, ...spot }
  if (next.x !== bounds.x || next.y !== bounds.y || next.width !== bounds.width || next.height !== bounds.height) win.setBounds(next)
}

// Puts the strip, Live insights, the transcript and the Recap in the preset's spots, then nudges Ask AI.
function place() {
  layout = layoutFor(callWindow.app, callWindow.rect, workAreaFor(callWindow.rect), insightsHeight)
  move(windows.bar, layout.bar)
  move(windows.insights, layout.insights)
  move(windows.transcript, layout.transcript)
  move(windows.recap, { x: layout.recap.x, y: layout.recap.y, width: layout.recap.width })
  placeAsk()
}

// Ask AI goes to its spot unless that covers a face or a control, then to the nearest free area. `opening`
// forces the move; otherwise it only moves when free and a face has pushed it more than a nudge away.
function placeAsk(opening = false) {
  if (!layout || (askBusy && !opening)) return
  const panel = windows.response.getBounds()
  const blocks = [windows.bar.getBounds(), ...layout.bands]
  if (showing(windows.insights)) blocks.push(windows.insights.getBounds())
  const boxes = [...faces.values()].map(({ screenBox: [x, y, width, height] }) => ({ x, y, width, height }))
  const spot = askPlace({ work: workAreaFor(callWindow.rect), spot: layout.ask, faces: boxes, blocks, panel })
  if (opening || !showing(windows.response) || Math.abs(spot.x - panel.x) > 32 || Math.abs(spot.y - panel.y) > 32) move(windows.response, spot)
}

// ---------- events in ----------

const insightsAll = [] // this call's insights, for a Recap built here
const peopleSeen = new Map() // person id -> person, for the same
let recapTimer

function broadcast(event) {
  if (event.type === 'debug' && !DEV) return // the normal app never sees what the computer sees
  if (event.type === 'insights') {
    lastInsights = event
    insightsAll.push(event)
  }
  if (event.type === 'face') {
    faces.set(event.trackId, event)
    if (event.person) peopleSeen.set(event.person.id, event.person)
    if (showing(windows.response)) placeAsk()
  }
  if (event.type === 'face_gone') faces.delete(event.trackId)
  if (event.type === 'window') {
    callWindow = { app: event.app, rect: Array.isArray(event.rect) && event.rect.length === 4 ? event.rect : null }
    place()
  }
  if (event.type === 'response' && event.id !== closedResponse) {
    if (!showing(windows.response)) placeAsk(true)
    reveal(windows.response)
  }
  if (event.type === 'recap') showRecap()
  for (const win of Object.values(windows)) win.webContents.send('event', event)
}

function showRecap() {
  clearTimeout(recapTimer)
  insightsAll.length = 0
  peopleSeen.clear()
  if (allHidden) toggleAll()
  reveal(windows.recap)
}

// End call: the server's recap should follow; if it doesn't in time, build one from what this call showed.
function expectRecap() {
  clearTimeout(recapTimer)
  recapTimer = setTimeout(() => broadcast(recapFrom(insightsAll, [...peopleSeen.values()])), RECAP_WAIT_MS)
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
const demoApp = process.argv[process.argv.indexOf('--app') + 1] // `npm run mock -- --app "Microsoft Teams"` tries another preset
let demoRecap = null

function replay() {
  const file = path.join(__dirname, '..', 'shared', 'mocks', 'overlay-demo.jsonl')
  let at = 0
  for (const line of fs.readFileSync(file, 'utf8').split('\n').filter(Boolean)) {
    const { delayMs, event } = JSON.parse(line)
    at += delayMs
    if (event.startedAt) event.startedAt = demoStart // the demo's timer starts at 00:00, not at the sample date
    if (event.type === 'window' && event.app && process.argv.includes('--app')) event.app = demoApp
    if (event.type === 'recap') demoRecap = event
    setTimeout(() => broadcast(event), at)
  }
}

// The demo answers locally, so clicking around in `npm run mock` never posts to a real memory service.
let demoAnswers = 0
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
  if (route === '/calls/end') {
    if (demoRecap) setTimeout(() => broadcast(demoRecap), 1500)
    return { note: 'demo' }
  }
  if (route === '/health') return { problems: [] }
  if (route.startsWith('/people')) return demoPeopleApi(route, body, method)
  const remember = route.match(/^\/faces\/(\d+)\/remember$/)
  if (remember) {
    const face = faces.get(+remember[1])
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
  const text = (body?.new === false ? 'Following up: ' : '') + 'This is a sample answer from the demo replay.\nStart the memory service to get real answers.'
  setTimeout(() => broadcast({ type: 'response', id, query, status: 'done', text, sources: [] }), 1800)
  return { id }
}

// ---------- calls from the panels ----------

// Resolves to the service's JSON, or to { error } with a sentence the panel can show as is.
ipcMain.handle('api', async (e, route, body, method = 'POST') => {
  if (!ours(e) || !validCall(route, body, method)) return { error: 'The overlay never makes that call.' }
  const data = MOCK ? demoApi(route, body, method) : await callMemory(route, body, method)
  if (route === '/calls/end' && !data.error) expectRecap()
  return data
})

async function callMemory(route, body, method) {
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
}

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
  if (win === windows.insights && insightsHeight !== fitted) {
    insightsHeight = fitted
    placeAsk() // Ask AI sits under Live insights
  }
})

on('panel-idle', (e, idle) => {
  if (typeof idle !== 'boolean') return
  const win = BrowserWindow.fromWebContents(e.sender)
  if (showing(win) && !allHidden) fade(win, idle ? IDLE_OPACITY : 1, idle ? 800 : 200)
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
on('copy-invite', () => clipboard.writeText(inviteLink(ENROLL_URL, process.env.ENROLL_CODE)))
on('ask', openAsk)
on('ask-busy', (_e, busy) => (askBusy = Boolean(busy)))
on('people-toggle', togglePeople)
on('transcript-toggle', toggleTranscript)
on('toggle-all', toggleAll)
on('close-response', (_e, id) => {
  if (typeof id !== 'string') return
  closedResponse = id
  conceal(windows.response)
})
on('close-recap', () => conceal(windows.recap))

// Developer mode only: the toggle, the shortcut and the handler don't exist in the normal app.
let debugOn = false
function toggleDebug() {
  debugOn = !debugOn
  for (const win of [windows.cards, windows.bar]) win.webContents.send('debug-show', debugOn)
}
if (DEV) on('debug-toggle', toggleDebug)

// ---------- start ----------

app.whenReady().then(async () => {
  const { bounds, workArea } = screen.getPrimaryDisplay()
  const first = layoutFor(null, null, workArea)

  // A macOS panel takes typing for "Remember them" without activating the overlay, so the call app keeps focus.
  // It can only take the keyboard while that form is open (cards-focus); clicks still land without it.
  const panel = process.platform === 'darwin' ? { type: 'panel' } : {}
  windows.cards = overlayWindow({ view: 'cards', ox: bounds.x, oy: bounds.y }, { ...bounds, ...panel, focusable: false, acceptFirstMouse: true })
  windows.cards.setIgnoreMouseEvents(true, { forward: true }) // click-through, but hover still reaches thinking pills
  windows.bar = panelWindow('bar', first.bar)
  windows.insights = panelWindow('insights', { ...first.insights, height: 200 })
  windows.response = panelWindow('response', { ...first.ask, height: 160 })
  windows.transcript = panelWindow('transcript', first.transcript)
  windows.recap = panelWindow('recap', { ...first.recap, height: 300 })
  windows.people = panelWindow('people', {
    ...PEOPLE_SIZE,
    x: Math.round(workArea.x + (workArea.width - PEOPLE_SIZE.width) / 2),
    y: Math.round(workArea.y + (workArea.height - PEOPLE_SIZE.height) / 2),
  })

  await Promise.all(Object.values(windows).map((win) => new Promise((r) => win.webContents.once('did-finish-load', r))))
  place()
  windows.cards.showInactive()
  reveal(windows.bar)
  reveal(windows.insights)

  const shortcuts = { 'CommandOrControl+Return': openAsk, 'CommandOrControl+Shift+P': togglePeople, 'CommandOrControl+\\': toggleAll }
  if (DEV) shortcuts['CommandOrControl+Alt+D'] = toggleDebug
  for (const [keys, run] of Object.entries(shortcuts)) {
    if (!globalShortcut.register(keys, run)) console.warn(`${keys} is taken by another app; use the control bar instead`)
  }
  screen.on('display-metrics-changed', place)

  if (MOCK) {
    status('demo')
    replay()
  } else {
    connect()
    startEverything()
  }
})

// One launch: start what isn't running (database, memory server, capture), stop what we started on quit.
let launcher
const launched = {}
function startEverything() {
  launcher = createLauncher({
    root: path.join(__dirname, '..'),
    onStatus: (name, state) => {
      launched[name] = state
      for (const win of Object.values(windows)) win.webContents.send('launch', { ...launched })
    },
  })
  launcher.start().catch((err) => console.error('Launch failed:', err.message))
}

// Clicking the Dock icon brings a hidden overlay back, in case another app owns ⌘\.
app.on('activate', () => allHidden && toggleAll())
app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  launcher?.stop()
})
app.on('window-all-closed', () => app.quit())
