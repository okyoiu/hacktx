// Small rules shared by main.js and the renderer (loaded as a plain script), tested in logic.test.js.

// The only memory API calls the overlay makes; main refuses anything else. Action ids are short words.
const ROUTES = /^\/(listening|ask|actions\/[\w-]+|faces\/\d+\/remember|calls\/end)$/

// What each method may call. The People dashboard reads, renames and deletes people; ids are short words.
const PERSON = /^\/people\/[\w-]+$/
const CALLS = { POST: ROUTES, GET: /^\/(people(\/[\w-]+)?|health)$/, PATCH: PERSON, DELETE: PERSON }

// A name typed into "Remember them": trimmed, single-spaced, at most 80 characters like the enroll page.
function cleanName(raw) {
  return String(raw).trim().replace(/\s+/g, ' ').slice(0, 80)
}

// The "Remember them" body: `role` ("Your team lead", at most 60 characters) is sent only when typed.
const cleanRole = (raw) => String(raw).trim().replace(/\s+/g, ' ').slice(0, 60)
function rememberBody(name, role) {
  const label = cleanRole(role)
  return { name: cleanName(name), consent: true, ...(label && { role: label }) }
}

// Call time since startedAt: "mm:ss", or "h:mm:ss" past an hour; "00:00" while unknown.
function elapsed(startedAt, now) {
  const started = Date.parse(startedAt)
  const s = Number.isFinite(started) ? Math.max(0, Math.floor((now - started) / 1000)) : 0
  const two = (n) => String(n).padStart(2, '0')
  return (s >= 3600 ? Math.floor(s / 3600) + ':' : '') + two(Math.floor(s / 60) % 60) + ':' + two(s % 60)
}

// Whether a `response` event may replace what the AI response panel shows.
function takesOver(shown, event, closedId) {
  if (event.id === closedId || shown.state === 'ask') return false // closed by the user, or they're typing a question
  return event.status === 'thinking' || !shown.id || event.id === shown.id // a late answer to an older question loses
}

// In a big call (BIG_CALL or more cards) a name card hides once its person hasn't been seen arriving or heard for QUIET_MS.
const BIG_CALL = 6
const QUIET_MS = 60_000
function isQuiet(cardCount, lastActive, now) {
  return cardCount >= BIG_CALL && now - lastActive > QUIET_MS
}

// A call is a known route plus no body or a small plain object; main checks this before forwarding.
function validCall(route, body, method = 'POST') {
  if (typeof route !== 'string' || !Object.hasOwn(CALLS, method) || !CALLS[method].test(route)) return false
  if (body == null) return true
  return typeof body === 'object' && !Array.isArray(body) && JSON.stringify(body).length <= 2000
}

// Only web links open in the browser.
function webUrl(url) {
  try {
    return ['http:', 'https:'].includes(new URL(url).protocol)
  } catch {
    return false
  }
}

// ---------- what each panel shows ----------

// Control bar: offline wins, then the pause state. The timer shows the call time, "Not sent" after a failed
// pause or the toast after End call (`flash`), and "Offline" without a connection.
function barState(connected, listeningOn) {
  return !connected ? 'offline' : listeningOn ? 'live' : 'paused'
}
function timerText({ connected, flash, startedAt, now }) {
  return flash || (connected ? elapsed(startedAt, now) : 'Offline')
}

// Live insights: at most 3 points and 4 actions, whatever the service sends.
const shownPoints = (points) => points.slice(0, 3)
const shownActions = (actions) => actions.slice(0, 4)

// "Show transcript" swaps the summary for the captions, and back.
function transcriptToggle(transcriptHidden) {
  return { open: transcriptHidden, label: transcriptHidden ? 'Hide transcript' : 'Show transcript' }
}

// AI response: the paragraphs the panel draws for a state ("thinking" and "ask" draw none).
function answerLines(state, text) {
  if (state === 'done') return text.split('\n').filter((l) => l.trim())
  if (state === 'error') return ["Couldn't get an answer.", (text ? text + ' ' : '') + 'Try again in a moment.']
  return []
}

// "Remember them": Enter saves once the name and the yes are in, Escape cancels.
function rememberKey(key, canSave) {
  return key === 'Escape' ? 'cancel' : key === 'Enter' && canSave ? 'save' : null
}
const canSave = (name, consent) => Boolean(cleanName(name) && consent)

// What a save's answer means for the form. `gone` is true when the face left while it was saving.
function rememberResult({ error, status }, gone) {
  if (status === 409) return { kind: 'left', text: 'They left the call before saving.' }
  if (gone) return { kind: 'left', text: error ? undefined : 'Saved. They have left the call.' }
  return error ? { kind: 'error', text: error } : { kind: 'saved' }
}

// ---------- memory pop-up ----------

// A known card opens with its bullets the first time that person shows up in the call, for POP_MS, and
// whenever the pointer is over it. `seen` is the set of person ids already popped; it empties when the call does.
const POP_MS = 10_000
const shouldPop = (seen, personId) => !seen.has(personId)
const isOpen = (popUntil, hovering, now) => hovering || now < popUntil

// Up to 5 bullets (three from memory, then "This call: …" lines the server appends while they talk), or
// (an older server) the label and the last-time line.
function bulletsOf(person) {
  const list = person.bullets?.length ? person.bullets : [person.role, person.line]
  return list.filter((b) => typeof b === 'string' && b.trim()).slice(0, 5)
}

// ---------- People dashboard ----------

// Search matches the name or the label, ignoring case; an empty search lists everyone.
function filterPeople(people, query) {
  const needle = String(query).trim().toLowerCase()
  return people.filter((p) => !needle || `${p.name} ${p.role || ''}`.toLowerCase().includes(needle))
}

// "Sep 24" from an ISO date, or "" when the server sent nothing usable.
function shortDate(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}

// People dashboard keys. `field` is the focused text field ('' for none, 'search' or 'role'), `cursor` the
// highlighted row (-1 for none) among `count` rows. Returns what to do and the new cursor.
// Arrows move the cursor, Enter opens it (the first row if none), "/" jumps to search, Esc closes; a label
// being typed keeps every key but Esc.
function peopleKey(key, { field = '', count, cursor }) {
  if (key === 'Escape') return { action: 'close', cursor }
  if (field === 'role') return { action: null, cursor }
  if (key === '/' && !field) return { action: 'search', cursor }
  if (key === 'ArrowDown' || key === 'ArrowUp') {
    const next = key === 'ArrowDown' ? cursor + 1 : cursor - 1
    return { action: count ? 'move' : null, cursor: Math.max(0, Math.min(next, count - 1)) }
  }
  if (key === 'Enter' && count) return { action: 'open', cursor: Math.max(cursor, 0) }
  return { action: null, cursor }
}

// Deleting takes two clicks: Delete, then Confirm. Cancel, Escape or opening someone else puts it back.
function deleteStep(step, event) {
  if (event === 'delete') return step === 'idle' ? 'confirm' : step
  if (event === 'confirm') return step === 'confirm' ? 'deleting' : step
  return 'idle' // cancel, escape, switch
}

// One launch: the control bar's warning names whatever the launcher couldn't keep running.
const PART_NAMES = { db: 'Database', server: 'Memory', faces: 'Face capture', transcribe: 'Transcription' }
function launchWarning(statuses) {
  return Object.entries(statuses).filter(([, state]) => state === 'down').map(([name]) => PART_NAMES[name]).filter(Boolean).join(' · ')
}

// The invite link guests open: the enroll page, with ?code= when ENROLL_CODE is set.
function inviteLink(base, code) {
  try {
    const url = new URL(base)
    if (code) url.searchParams.set('code', code)
    return url.href
  } catch {
    return base
  }
}

// GET /health: the dot is green, or amber with the reasons. The server may send {problems: [...]} or a map of
// check -> ok; a server that can't be reached, or a part the launcher lost, counts too.
// shortcut: the exact /health shape isn't in the README yet, upgrade this once it is.
function healthProblems(health, launchWarningText = '') {
  const problems = []
  if (!health || health.error) problems.push('The memory server is not answering')
  else if (Array.isArray(health.problems)) problems.push(...health.problems.filter((p) => typeof p === 'string'))
  else for (const [check, ok] of Object.entries(health.checks || health)) if (ok === false || ok === 'down' || ok === 'error') problems.push(`${check} is not working`)
  if (launchWarningText) problems.push(`${launchWarningText} stopped`)
  return problems
}

// What Live insights says before its first insight.
const insightsEmptyText = (listeningOn) => (listeningOn === false ? 'Paused. Resume to keep listening.' : 'Listening…')

// Where a card goes, in window coordinates: beside the face (right, else left), else below it, else above,
// so it never covers the face. A side card slides up or down to stay on screen. With no room anywhere it
// goes beside the face anyway, clamped (shortcut: one card can't avoid a face that fills the screen).
function cardPlace({ face: [x, y, w, h], card, screen, gap = 12, margin = 8 }) {
  const clamp = (v, size, max) => Math.max(margin, Math.min(v, max - size - margin))
  const side = (left) => ({ left, top: clamp(y, card.height, screen.height) })
  if (x + w + gap + card.width <= screen.width - margin) return side(x + w + gap)
  if (x - gap - card.width >= margin) return side(x - gap - card.width)
  const across = clamp(x, card.width, screen.width)
  if (y + h + gap + card.height <= screen.height - margin) return { left: across, top: y + h + gap }
  if (y - gap - card.height >= margin) return { left: across, top: y - gap - card.height }
  return side(clamp(x + w + gap, card.width, screen.width))
}

// A card moves with its face only when the face's centre has moved more than JITTER points; the tracker's
// small wobble never moves it. (A card that would leave the screen is re-placed by the renderer on resize.)
const JITTER = 24
function shouldMove(prev, next) {
  if (!prev) return true
  const centre = ([x, y, w, h]) => [x + w / 2, y + h / 2]
  const [ax, ay] = centre(prev)
  const [bx, by] = centre(next)
  return Math.abs(bx - ax) > JITTER || Math.abs(by - ay) > JITTER
}

// ---------- fixed spots per call app ----------

// Window sizes the layout counts on, in screen points. Panels grow downwards from their spot (main.js `fit`).
// The strip's spot is the island at its widest (the sheet); as a pill it sits centred in that spot.
const BAR = { width: 560, height: 44 }
const ISLAND = { pill: 236, sheet: 560 }
const PANEL = { width: 448, gap: 12, margin: 24 }
const STRIP = { width: 720, height: 64 } // the transcript strip along the bottom
const RECAP = { width: 560, height: 440 } // height: a guess for centring; the window fits its content
const INSIGHTS_GUESS = 220

// Where each app keeps its own controls: a band at the top and one at the bottom of its window (points), which
// side its chat/people panels and self tile use (the rail takes the other), and where the strip sits.
const PRESETS = {
  zoom: { side: 'right', strip: 'center', top: 48, bottom: 64 },
  teams: { side: 'left', strip: 'left', top: 64, bottom: 0 }, // Teams' controls are top right
  facetime: { side: 'left', strip: 'center', top: 40, bottom: 80 },
  meet: { side: 'left', strip: 'center', top: 0, bottom: 88 },
  general: { side: 'right', strip: 'center', top: 48, bottom: 72 },
}

// The preset for the app name capture/window.py reports; Meet (and any web call) lives in a browser.
function presetFor(app) {
  const name = String(app || '')
  if (/zoom/i.test(name)) return 'zoom'
  if (/teams/i.test(name)) return 'teams'
  if (/facetime/i.test(name)) return 'facetime'
  if (/chrome|arc|safari|firefox|edge/i.test(name)) return 'meet'
  return 'general'
}

const clampTo = (v, size, lo, hi) => Math.round(Math.max(lo, Math.min(v, hi - size)))

// The spot of every piece for a call window ([x, y, w, h] in screen points, or null) on a screen's work area:
// the control strip, Live insights and Ask AI (one rail), the transcript strip and the Recap. Beside the window
// when there is room (the strip above it, the rail on the wider free side, the transcript below), inside it
// otherwise, clear of the app's own control bands. `bands` are those bands, for the Ask AI nudge.
function layoutFor(app, rect, work, insightsHeight = INSIGHTS_GUESS) {
  const preset = presetFor(app)
  const p = PRESETS[preset]
  const { gap, margin } = PANEL
  const right = work.x + work.width
  const bottom = work.y + work.height
  // the window, clipped to the screen; the whole work area when there is none
  const win = rect ? { x: Math.max(rect[0], work.x), y: Math.max(rect[1], work.y) } : { x: work.x, y: work.y }
  win.width = rect ? Math.min(rect[0] + rect[2], right) - win.x : work.width
  win.height = rect ? Math.min(rect[1] + rect[3], bottom) - win.y : work.height
  const winRight = win.x + win.width
  const winBottom = win.y + win.height

  const barAbove = win.y - work.y >= BAR.height + gap
  const bar = {
    ...BAR,
    x: clampTo(p.strip === 'left' ? win.x + margin : win.x + (win.width - BAR.width) / 2, BAR.width, work.x + margin, right - margin),
    y: barAbove ? win.y - gap - BAR.height : win.y + gap / 2,
    anchor: p.strip === 'left' ? 'left' : 'center', // what stays put as the island grows
  }

  const roomRight = right - winRight
  const roomLeft = win.x - work.x
  const outside = Math.max(roomRight, roomLeft) >= PANEL.width + gap + margin
  const side = outside ? (roomRight >= roomLeft ? 'right' : 'left') : p.side
  const railX = outside
    ? side === 'right' ? winRight + gap : win.x - gap - PANEL.width
    : side === 'right' ? winRight - margin - PANEL.width : win.x + margin
  const railY = outside ? Math.max(win.y, work.y + margin / 2) : Math.max(win.y + p.top, bar.y + bar.height) + gap
  const insights = { x: Math.round(railX), y: Math.round(railY), width: PANEL.width }
  const ask = { ...insights, y: insights.y + insightsHeight + gap }

  const transcriptBelow = bottom - winBottom >= STRIP.height + gap
  const transcript = {
    width: Math.min(STRIP.width, win.width - 2 * margin),
    height: STRIP.height,
    y: transcriptBelow ? winBottom + gap : winBottom - p.bottom - gap - STRIP.height,
  }
  transcript.x = Math.round(win.x + (win.width - transcript.width) / 2)

  const recap = {
    ...RECAP,
    x: clampTo(win.x + (win.width - RECAP.width) / 2, RECAP.width, work.x + margin, right - margin),
    y: clampTo(win.y + (win.height - RECAP.height) / 2, RECAP.height, bar.y + bar.height + gap, bottom - margin),
  }

  const bands = [
    p.top && { x: win.x, y: win.y, width: win.width, height: p.top },
    p.bottom && { x: win.x, y: winBottom - p.bottom, width: win.width, height: p.bottom },
  ].filter(Boolean)
  return { preset, bar, insights, ask, transcript, recap, bands }
}

const area = (a, b) => Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))

// The open name card beside a face, in screen points, for keeping panels off it (the renderer places the
// real card the same way, so this is where it is).
const CARD_SIZE = { width: 300, height: 170 } // an open card: name, the facts row, three bullets
const PILL_SIZE = { width: 132, height: 36 } // a "Recalling…" pill
function cardRect([x, y, w, h], screen, known = true) {
  const size = known ? CARD_SIZE : PILL_SIZE
  const { left, top } = cardPlace({ face: [x - screen.x, y - screen.y, w, h], card: size, screen })
  return { x: left + screen.x, y: top + screen.y, ...size }
}

// Where a panel goes: its spot when that covers no face, no name card and no control (ours or the app's),
// else the nearest placement that covers nothing, else the one that covers least, where a face counts most
// and a card least. Candidates are the work area's corners and each obstacle's edges, so the answer is the
// same for the same inputs. Ask AI may go anywhere; Live insights keeps its rail (`fixedX`) and only slides.
function askPlace({ work, spot, faces, blocks, cards = [], panel, fixedX = false }) {
  const { gap, margin } = PANEL
  const obstacles = [...faces, ...blocks, ...cards]
  const weight = (o) => (faces.includes(o) ? 4 : blocks.includes(o) ? 2 : 1)
  const covered = (x, y) => obstacles.reduce((sum, o) => sum + weight(o) * area({ x, y, ...panel }, o), 0)
  const clampX = (x) => clampTo(x, panel.width, work.x + margin, work.x + work.width - margin)
  const clampY = (y) => clampTo(y, panel.height, work.y + margin / 2, work.y + work.height - margin / 2)
  const home = { x: clampX(spot.x), y: clampY(spot.y) }
  if (!covered(home.x, home.y)) return home
  const xs = new Set(fixedX ? [home.x] : [home.x, clampX(work.x), clampX(work.x + work.width)])
  const ys = new Set([home.y, clampY(work.y), clampY(work.y + work.height)])
  for (const o of obstacles) {
    if (!fixedX) xs.add(clampX(o.x + o.width + gap)).add(clampX(o.x - gap - panel.width))
    ys.add(clampY(o.y + o.height + gap)).add(clampY(o.y - gap - panel.height))
  }
  let best = null
  for (const x of xs) {
    for (const y of ys) {
      const score = [covered(x, y), Math.hypot(x - home.x, y - home.y)]
      if (!best || score[0] < best.score[0] || (score[0] === best.score[0] && score[1] < best.score[1])) best = { x, y, score }
    }
  }
  return { x: best.x, y: best.y }
}

// ---------- the island ----------

// One glass object at the top of the call: a pill while you talk, a one-line notice for NOTICE_MS when a new
// insight arrives, a sheet when opened (⌘↵, a click, an answer), and the Recap when the call ends.
const NOTICE_MS = 6000
function islandStage({ recap, open, noticeUntil, now }) {
  return recap ? 'recap' : open ? 'sheet' : now < noticeUntil ? 'notice' : 'pill'
}

// The island window for a content size: it grows around its anchor (the spot's centre, or its left edge for
// apps whose own controls sit top right) and never leaves the work area.
function islandBounds(spot, size, work) {
  const x = spot.anchor === 'left' ? spot.x : spot.x + (spot.width - size.width) / 2
  const bottom = work.y + work.height - PANEL.gap
  return {
    x: clampTo(x, size.width, work.x + PANEL.gap, work.x + work.width - PANEL.gap),
    y: spot.y,
    width: size.width,
    height: Math.min(Math.ceil(size.height), bottom - spot.y),
  }
}

// ---------- Recap ----------

// A Recap built on this laptop when the server sends none within a few seconds of End call: the last topic,
// the newest points first (at most 5), the last actions, and each person seen with their "last time" line.
function recapFrom(insightsList, people) {
  const last = insightsList[insightsList.length - 1]
  const points = [...new Set([...insightsList].reverse().flatMap((i) => i.points))].slice(0, 5)
  const seen = new Map(people.map((p) => [p.id, { id: p.id, name: p.name, role: p.role || '', lastTime: p.line || '' }]))
  return { type: 'recap', topic: last?.topic || 'This call', points, actions: last?.actions || [], people: [...seen.values()] }
}

// ---------- developer debug view ----------

// Developer mode exists only when the app was started that way; nothing over IPC or the network can turn it on.
const devMode = (argv, env) => argv.includes('--dev') || env.HELLO_DEBUG === '1'

const MATCH_MIN = 0.45 // memory/store.py's cutoff; shown so a developer sees why a face stayed "Recalling…"
function debugLabel({ trackId, score, decision }) {
  const scored = typeof score === 'number' ? `${score.toFixed(2)} ${score >= MATCH_MIN ? '≥' : '<'} ${MATCH_MIN}` : 'no score'
  return `#${trackId} · ${scored} · ${decision}`
}

if (typeof module !== 'undefined') module.exports = { presetFor, layoutFor, askPlace, cardRect, recapFrom, debugLabel, devMode, shouldMove, islandStage, islandBounds, ISLAND, NOTICE_MS, BAR, PANEL, STRIP, RECAP, MATCH_MIN, ROUTES, elapsed, takesOver, cleanName, peopleKey, cardPlace, healthProblems, insightsEmptyText, inviteLink, launchWarning, cleanRole, filterPeople, shortDate, deleteStep, rememberBody, shouldPop, isOpen, bulletsOf, POP_MS, validCall, webUrl, barState, timerText, shownPoints, shownActions, transcriptToggle, answerLines, rememberKey, canSave, rememberResult, isQuiet, BIG_CALL, QUIET_MS }
