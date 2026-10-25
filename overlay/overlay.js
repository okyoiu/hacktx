// Renders memory-service events in one overlay window, picked by ?view=: cards (name tags and cards beside
// faces), island (the pill that becomes a notice, the sheet with Live insights and Ask AI, and the Recap),
// transcript (the strip along the bottom) or people (the dashboard). view=all, a plain browser tab, draws
// everything for styling, placed with the same layout rules as the app. Event shapes: see README "Overlay events".
const q = new URLSearchParams(location.search)
const view = q.get('view') || 'all'
const ISLAND_PARTS = ['bar', 'insights', 'response', 'recap'] // all drawn by the island window
const shows = (part) => view === 'all' || view === part || (view === 'island' && ISLAND_PARTS.includes(part))
const origin = { x: +q.get('ox') || 0, y: +q.get('oy') || 0 } // the cards window's top-left in screen points
const CARD = { width: 300, gap: 12, open: 244 } // open: the name, role, the facts row and three bullets (CARD_SIZE in logic.js)
const KIND_EMOJI = { define: '📘', search: '🌐', places: '📍', events: '📅', recall: '👋', followups: '💬', helpful: '✨' }
const calm = matchMedia('(prefers-reduced-motion: reduce)')
const DEBUG = q.get('debug') === '1' // developer mode: only main.js sets this, and only when started with `npm run dev`

const $ = (id) => document.getElementById(id)
document.body.dataset.view = view
$('island').hidden = !shows('bar')
$('transcript').hidden = view !== 'transcript' // in the preview it opens with "Show transcript"
$('people').hidden = view !== 'people' // the dashboard has its own window
$('hint').hidden = !shows('cards')
setTimeout(() => ($('hint').hidden = true), 45_000) // nothing extra on screen for long
if (!/Mac/.test(navigator.platform)) for (const key of document.querySelectorAll('kbd.mod')) key.textContent = 'Ctrl'

function el(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text != null) node.textContent = text // names, captions and answers are untrusted; never innerHTML
  return node
}

// resolves to the service's answer, or to { error } with a sentence to show (see main.js)
const api = (route, body, method) => (window.overlay ? window.overlay.api(route, body, method) : Promise.resolve({ error: 'Open the overlay app to send this.' }))

function handle(e) {
  if (shows('cards')) {
    if (e.type === 'face') {
      $('hint').hidden = true // a face showed up; the hint has done its job
      faceBoxes.set(e.trackId, e.screenBox)
      placeCard(e)
    }
    if (e.type === 'face_gone') {
      faceBoxes.delete(e.trackId)
      removeCard(e.trackId)
    }
    if (e.type === 'caption') heard(e.speaker)
    if (DEBUG && e.type === 'debug') drawDebug(e)
    if (DEBUG && e.type === 'face_gone') $('dbg' + e.trackId)?.remove()
  }
  if (shows('bar')) {
    if (e.type === 'listening') {
      setListening(e)
      setInsightsEmpty(e.on)
    }
    if (e.type === 'caption') {
      energy = 1
      wakePanel()
    }
    if (e.type === 'insights') {
      actions = e.actions
      showInsights(e)
    }
    if (e.type === 'response') showResponse(e)
    if (e.type === 'recap') showRecap(e)
  }
  if (shows('transcript') && e.type === 'caption') addCaption(e)
  if (view === 'all') {
    if (e.type === 'window') previewWindow = e
    if (['window', 'face', 'face_gone'].includes(e.type)) schedulePreview()
  }
}

// ---------- name tags and cards beside faces (click-through, never show tracking data) ----------

function placeCard({ trackId, screenBox, person }) {
  const id = 't' + trackId
  let card = $(id)
  const kind = cardKind(person, DEBUG)
  if (kind === 'none') return card?.remove() // your own tile: nothing
  if (kind === 'you') {
    // developers see a dim "You" so they know the self tile was recognised; it takes no clicks and never opens
    if (!card) {
      card = el('div', 'card glass you')
      card.id = id
      card.append(el('span', 'name', 'You'))
      $('cards').append(card)
    }
    card.dataset.face = JSON.stringify(screenBox)
    return position(card)
  }
  const known = person ? [person.id, ...bulletsOf(person), person.met].join('\n') : 'unknown'
  if (!card) {
    card = el('div')
    card.id = id
    card.dataset.track = trackId
    card.addEventListener('mouseenter', () => {
      card.dataset.hover = 'true'
      syncMouse()
      syncOpen(card)
    })
    card.addEventListener('mouseleave', () => {
      delete card.dataset.hover
      syncMouse()
      syncOpen(card)
    })
    fillCard(card, person)
    $('cards').append(card)
    card.dataset.active = Date.now()
  } else if (card.dataset.person !== known) {
    const before = card.dataset.person
    morph(card, () => fillCard(card, person, new Set(before.split('\n'))))
    card.dataset.active = Date.now()
    // a new "This call: …" line while they talk: the card opens again so you see it rise in
    if (person && card.dataset.pid === person.id && !dismissed.has(person.id)) pop(card)
  }
  if (person && card.dataset.pid !== person.id) {
    card.dataset.pid = person.id
    if (shouldPop(popped, person.id)) {
      popped.add(person.id)
      pop(card)
    }
  }
  card.dataset.person = known
  syncOpen(card)
  // anchored to the face: it follows only when the face really moved, with one eased slide, never jitter
  const prev = card.dataset.face ? JSON.parse(card.dataset.face) : null
  if (shouldMove(prev, screenBox) || card.dataset.known !== String(!!person)) {
    card.dataset.face = JSON.stringify(screenBox)
    card.dataset.known = String(!!person) // a pill that became a name card is placed for its new size
    position(card)
  }
  settleOthers(card)
}

// A known card is placed for its open size, so opening it never pushes it over the face, and clear of every
// other face and the island.
let islandRect = null // the island window, in this window's coordinates (main.js sends it)
const faceBoxes = new Map() // trackId -> screenBox of every face on screen, your own included
const localFace = ([x, y, w, h]) => [x - origin.x, y - origin.y, w, h]
function avoidFor(card) {
  const others = [...faceBoxes].filter(([id]) => 't' + id !== card?.id).map(([, box]) => localFace(box))
  // and the other cards where they are now, so two cards never stack
  for (const c of document.querySelectorAll('#cards .card[data-place]')) {
    if (c === card) continue
    const [left, top] = JSON.parse(c.dataset.place)
    const { width, height } = cardSize(c)
    others.push([left, top, width, height])
  }
  if (view === 'all') {
    const r = $('island').getBoundingClientRect()
    return [...others, [r.left, r.top, r.width, r.height]]
  }
  return islandRect ? [...others, islandRect] : others
}
function cardSize(card) {
  return card.classList.contains('known') ? { width: CARD.width, height: CARD.open } : { width: card.offsetWidth || CARD.width, height: card.offsetHeight || 40 }
}
function position(card) {
  const size = cardSize(card)
  const { left, top } = cardPlace({ face: localFace(JSON.parse(card.dataset.face)), card: size, screen: { width: innerWidth, height: innerHeight }, avoid: avoidFor(card), gap: CARD.gap })
  card.dataset.place = JSON.stringify([left, top])
  card.style.transform = `translate(${left}px, ${top}px)`
}
// A face or the island arrived under a card that was already placed: that card moves, the others stay.
function settleOthers(except) {
  for (const card of document.querySelectorAll('#cards .card[data-face]')) {
    if (card === except || !card.dataset.place) continue
    const [left, top] = JSON.parse(card.dataset.place)
    const { width, height } = cardSize(card)
    const covered = avoidFor(card).some(([x, y, w, h]) => left < x + w && left + width > x && top < y + h && top + height > y)
    if (covered) position(card)
  }
}
const repositionAll = () => document.querySelectorAll('#cards .card[data-face]').forEach(position)
window.addEventListener('resize', repositionAll)
window.overlay?.onIslandBounds((b) => {
  islandRect = [b.x - origin.x, b.y - origin.y, b.width, b.height]
  settleOthers(null)
})

function pop(card) {
  card.dataset.popUntil = Date.now() + POP_MS
  setTimeout(() => syncOpen(card), POP_MS)
}

// Speaking brings a quiet card back. Face events repeat while a face is on screen, so only arrivals and
// changes count as being seen; in a big call a face that just sits there fades out.
function heard(speaker) {
  for (const card of document.querySelectorAll('#cards .card')) {
    if (card.querySelector('.name')?.textContent === speaker) card.dataset.active = Date.now()
  }
}

setInterval(() => {
  const cards = [...document.querySelectorAll('#cards .card')]
  for (const card of cards) {
    const stays = card.matches('.thinking, .remembering, .leaving')
    card.classList.toggle('quiet', !stays && isQuiet(cards.length, +card.dataset.active, Date.now()))
  }
}, 5000)

// The memory pop-up: a known card shows its bullets while it's new, hovered or pinned open, else just the name
// tag. ✕ closes it for that person for the rest of the call; clicking the name tag opens or closes it by hand.
const popped = new Set() // person ids already popped in this call; emptied when the last card leaves
const dismissed = new Set() // person ids whose card was closed with ✕
function syncOpen(card) {
  const pid = card.dataset.pid
  const open = card.dataset.pinned === 'true' || (!dismissed.has(pid) && isOpen(+card.dataset.popUntil || 0, !!card.dataset.hover, Date.now()))
  card.classList.toggle('open', open)
}

function fillCard(card, person, oldBullets = new Set()) {
  const hadForm = card.classList.contains('remembering')
  if (!person) {
    // A face we can't name yet (still matching, or not enrolled) gets the thinking sparkle, never "unknown".
    // Its one action, shown on hover, is "Remember them".
    card.className = 'card glass thinking'
    const remember = el('button', 'remember', 'Remember them')
    remember.type = 'button'
    remember.addEventListener('click', () => morph(card, () => openRemember(card)))
    card.replaceChildren(icon('sparkle', 'mark'), verb('Recalling,Thinking,Remembering,Looking'), remember)
  } else {
    card.className = 'card glass known'
    const tag = el('button', 'tag')
    tag.type = 'button'
    tag.append(el('span', 'dot'), el('span', 'name', person.name))
    tag.addEventListener('click', () => {
      card.dataset.pinned = String(!card.classList.contains('open'))
      if (card.dataset.pinned === 'false') dismissed.add(person.id)
      syncOpen(card)
    })
    const close = el('button', 'close')
    close.type = 'button'
    close.setAttribute('aria-label', 'Close for this call')
    close.append(icon('close'))
    close.addEventListener('click', () => {
      dismissed.add(person.id)
      card.dataset.pinned = 'false'
      syncOpen(card)
    })
    const row = el('div', 'row')
    row.append(tag, close)
    // the memory jogger: name and role, the facts row, then three one-line bullets
    const facts = el('dl', 'facts')
    for (const f of cardFacts(person, Date.now())) {
      const item = el('div')
      const value = el('dd', null, f.value)
      if (f.title) value.title = f.title // "Oct 18" says "a week ago" on hover
      item.append(el('dt', null, f.label), value)
      facts.append(item)
    }
    const bullets = el('ul', 'bullets')
    bullets.append(...cardBullets(person).map((b) => fresh(el('li', null, oneLine(b, 44)), oldBullets.has(b))))
    const inner = el('div')
    inner.append(el('div', 'role', person.role || ''), facts, bullets)
    const more = el('div', 'more')
    more.append(inner)
    card.replaceChildren(row, more)
    syncOpen(card)
  }
  if (hadForm) release()
  else syncMouse() // a hovered pill that just became a name card must stop taking the mouse
}

// "Remember them": a name, their yes, Save. The cards window takes the keyboard while this is open.
function openRemember(card) {
  card.className = 'card glass remembering'
  const name = el('input', 'name-field')
  Object.assign(name, { type: 'text', maxLength: 80, placeholder: 'Their name', autocomplete: 'off', spellcheck: false })
  name.setAttribute('aria-label', 'Their name')
  const role = el('input', 'name-field')
  Object.assign(role, { type: 'text', maxLength: 60, placeholder: 'Who are they to you? (optional)', autocomplete: 'off', spellcheck: false })
  role.setAttribute('aria-label', 'Who are they to you?')
  const consent = el('input')
  consent.type = 'checkbox'
  const yes = el('label', 'yes')
  yes.append(consent, el('span', null, 'They said yes'))
  const save = el('button', 'save', 'Save')
  save.type = 'submit'
  save.disabled = true
  const invite = el('button', 'invite', 'Copy invite link')
  invite.type = 'button'
  const close = el('button', 'tool')
  close.type = 'button'
  close.setAttribute('aria-label', 'Close')
  close.append(icon('close'))
  const head = el('div', 'remember-head')
  head.append(icon('sparkle', 'mark'), el('span', null, 'Remember them'), close)
  const actions = el('div', 'remember-actions')
  actions.append(save, invite)
  const note = el('p', 'note')
  note.setAttribute('role', 'status')
  const form = el('form', 'remember-form')
  form.append(name, role, yes, actions, note)
  card.replaceChildren(head, form)

  const ready = () => (save.disabled = !canSave(name.value, consent.checked))
  name.addEventListener('input', ready)
  consent.addEventListener('change', ready)
  close.addEventListener('click', () => closeRemember(card))
  invite.addEventListener('click', () => {
    window.overlay?.copyInvite() // for people who'd rather enroll themselves with a selfie
    invite.textContent = 'Link copied'
  })
  form.addEventListener('submit', async (e) => {
    e.preventDefault()
    if (save.disabled) return
    for (const control of [name, role, consent, save]) control.disabled = true
    save.textContent = 'Saving…'
    note.textContent = ''
    card.dataset.saving = 'true'
    const { error, status } = await api(`/faces/${Number(card.dataset.track)}/remember`, rememberBody(name.value, role.value))
    delete card.dataset.saving
    if (!card.classList.contains('remembering')) return // already their name card
    const result = rememberResult({ error, status }, card.dataset.gone)
    if (result.kind === 'left') return leftCall(card, result.text)
    if (result.kind === 'error') {
      note.textContent = result.text
      save.textContent = 'Save'
      name.disabled = role.disabled = consent.disabled = false
      return ready()
    }
    // the server now pushes this face's updated `face` event, which morphs the form into their name card
    setTimeout(() => card.classList.contains('remembering') && closeRemember(card), 4000)
  })
  window.overlay?.focusCards(true)
  name.focus()
}

function closeRemember(card) {
  morph(card, () => fillCard(card, null))
}

// They left the call while the form was open: say so, then let the card go.
function leftCall(card, text = 'They left the call before saving.') {
  card.querySelector('.note').textContent = text
  for (const control of card.querySelectorAll('input, .save')) control.disabled = true
  setTimeout(() => {
    card.remove()
    release()
  }, 2500)
}

// The cards window takes the mouse only while the pointer is over a pill, a name card or its form.
const syncMouse = () => window.overlay?.setClickThrough(!document.querySelector('#cards :is(.thinking, .remembering, .known):hover'))

// Hands the keyboard back to the call app, and the mouse unless the pointer is still over a pill.
function release() {
  window.overlay?.focusCards(false)
  syncMouse()
}

// Same element, new content: tween the old size to the new one and blur the new content in.
function morph(card, change) {
  const size = () => ({ width: card.offsetWidth + 'px', height: card.offsetHeight + 'px', borderRadius: getComputedStyle(card).borderRadius })
  const from = size()
  change()
  if (calm.matches) return
  card.animate([{ ...from, overflow: 'hidden' }, { ...size(), overflow: 'hidden' }], { duration: 420, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' })
  for (const child of card.children) {
    child.animate([{ opacity: 0, filter: 'blur(4px)' }, { opacity: 1, filter: 'blur(0)' }], { duration: 320, delay: 120, easing: 'ease-out', fill: 'backwards' })
  }
}

function removeCard(trackId) {
  const card = $('t' + trackId)
  if (!card) return
  if (card.classList.contains('remembering')) {
    if (card.dataset.saving) card.dataset.gone = 'true' // the save's answer decides what to say
    else leftCall(card)
    return
  }
  card.classList.add('leaving')
  setTimeout(() => {
    card.remove()
    if (!document.querySelector('#cards .card')) {
      popped.clear() // the call is empty; the next hello pops again
      dismissed.clear()
    }
    syncMouse() // in case the pointer was over it
  }, 250)
}

if (shows('cards')) {
  document.addEventListener('keydown', (e) => {
    const open = document.querySelector('.card.remembering')
    if (!open) return
    const act = rememberKey(e.key, !open.querySelector('.save').disabled)
    if (act) e.preventDefault() // Enter must not also submit natively
    if (act === 'cancel') closeRemember(open)
    if (act === 'save') open.querySelector('form').requestSubmit()
  })
}

// an icon from the <symbol>s in index.html
function icon(id, className) {
  const ns = 'http://www.w3.org/2000/svg'
  const svg = document.createElementNS(ns, 'svg')
  if (className) svg.setAttribute('class', className)
  svg.setAttribute('aria-hidden', 'true')
  const use = document.createElementNS(ns, 'use')
  use.setAttribute('href', '#' + id)
  svg.append(use)
  return svg
}

function verb(list) {
  const verbs = list.split(',')
  const span = el('span', 'verb shimmer', verbs[verbIndex % verbs.length] + '…')
  span.dataset.verbs = list
  return span
}

// Thinking verbs take turns while we wait ("Recalling…", "Searching…").
let verbIndex = 0
setInterval(() => {
  if (calm.matches) return
  verbIndex++
  for (const node of document.querySelectorAll('.verb')) {
    const list = node.dataset.verbs.split(',')
    node.textContent = list[verbIndex % list.length] + '…'
    node.animate([{ opacity: 0, filter: 'blur(3px)' }, { opacity: 1, filter: 'blur(0)' }], { duration: 320, easing: 'ease-out' })
  }
}, 2400)

// ---------- developer debug view (only built in developer mode; the normal app has none of this) ----------

// What the computer sees, on the click-through layer: each person's box and track number, the face box, the
// match score against the cutoff and the decision, plus frames per second. Hidden until the toggle or ⌘⌥D.
function drawDebug({ trackId, personBox, faceBox, score, decision, fps }) {
  const layer = $('debug')
  if (!layer) return
  const box = (node, [x, y, w, h]) => Object.assign(node.style, { left: x - origin.x + 'px', top: y - origin.y + 'px', width: w + 'px', height: h + 'px' })
  let item = $('dbg' + trackId)
  if (!item) {
    item = el('div', 'dbg')
    item.id = 'dbg' + trackId
    item.append(el('div', 'dbg-person'), el('div', 'dbg-face'), el('span', 'dbg-label'))
    layer.append(item)
  }
  const [person, face, label] = item.children
  box(person, personBox)
  face.hidden = !faceBox
  if (faceBox) box(face, faceBox)
  label.textContent = debugLabel({ trackId, score, decision })
  label.style.left = personBox[0] - origin.x + 'px'
  label.style.top = personBox[1] + personBox[3] - origin.y + 4 + 'px'
  $('fps').textContent = typeof fps === 'number' ? fps.toFixed(1) + ' fps' : ''
}

if (DEBUG && shows('cards')) {
  const layer = el('div')
  layer.id = 'debug'
  layer.hidden = !!window.overlay // the browser preview shows it straight away
  const fps = el('span', 'dbg-fps')
  fps.id = 'fps'
  layer.append(fps)
  document.body.append(layer)
  window.overlay?.onDebugShow((on) => (layer.hidden = !on))
}

if (DEBUG && shows('bar')) {
  const toggle = el('button', 'tool debug-btn')
  toggle.type = 'button'
  toggle.title = 'Debug view ⌘⌥D: what the computer sees'
  toggle.setAttribute('aria-label', toggle.title)
  toggle.setAttribute('aria-pressed', 'false')
  toggle.append(icon('eye'))
  toggle.addEventListener('click', () => window.overlay?.toggleDebug())
  window.overlay?.onDebugShow((on) => toggle.setAttribute('aria-pressed', String(on)))
  $('hideBtn').before(toggle)
}

// ---------- the island: pill · notice · sheet · recap ----------

let open = false // the sheet is open (⌘↵, a click on the pill, an answer)
let recapOn = false // the call ended and the Recap is showing
let noticeUntil = 0 // a new insight widens the pill until then
let noticeTimer
let unseen = 0 // points that arrived while the sheet was closed, for the pill's badge

function syncStage() {
  const stage = islandStage({ recap: recapOn, open, noticeUntil, now: Date.now() })
  if ($('island').dataset.stage !== stage) {
    $('island').dataset.stage = stage
    wakePanel()
    if (stage === 'sheet' || stage === 'recap') {
      unseen = 0
      renderBadge()
    }
    if (view === 'all') schedulePreview()
  }
}

function setOpen(on) {
  open = on
  if (!on) {
    closed = turns.at(-1)?.id ?? null // an answer that lands after you closed the sheet stays quiet
    $('question').blur()
  }
  syncStage()
}

function notify() {
  noticeUntil = Date.now() + NOTICE_MS
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(syncStage, NOTICE_MS + 20)
  syncStage()
}

function renderBadge() {
  $('badge').hidden = !unseen
  $('badge').textContent = unseen
}

if (shows('bar')) {
  $('pillBtn').addEventListener('click', () => !recapOn && setOpen(!open))
  $('askBtn').addEventListener('click', () => (window.overlay ? window.overlay.ask() : startAsk()))
  $('closeRecap').addEventListener('click', () => {
    recapOn = false
    syncStage()
  })
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return
    recapOn = false
    setOpen(false)
  })
  $('island').addEventListener('mouseenter', wakePanel)
}

// ---------- the head: waveform, timer, tools ----------

let listening = { on: false, startedAt: null }
let connected = !window.overlay || !!q.get('mock') // a browser preview has no connection to lose
let energy = 0 // jumps to 1 on each caption, then settles: the waveform breathes with the conversation

function setListening({ on, startedAt }) {
  listening = { on, startedAt: startedAt || listening.startedAt }
  renderBar()
}

// The status dot: hidden while everything runs, amber with what's wrong, from GET /health every 10 s and the launcher.
let launchDown = ''
async function checkHealth() {
  const problems = healthProblems(connected ? await api('/health', undefined, 'GET') : { error: 'offline' }, launchDown)
  $('health').dataset.state = problems.length ? 'warn' : 'ok'
  $('health').title = problems.length ? problems.join('. ') + '.' : 'Everything is running'
  $('health').setAttribute('aria-label', $('health').title)
}
if (shows('bar')) {
  checkHealth()
  setInterval(checkHealth, 10_000)
}

// One launch: the launcher says which parts it couldn't keep running.
window.overlay?.onLaunch((statuses) => {
  const down = launchWarning(statuses)
  launchDown = down
  checkHealth()
  $('warn').hidden = !down
  $('warn').textContent = down && '⚠ ' + down
  $('warn').title = down && down + ' stopped. See the logs folder.'
})

function renderBar() {
  const live = connected && listening.on
  $('bar').dataset.state = barState(connected, listening.on)
  $('pause').disabled = !connected
  $('endBtn').disabled = !connected
  $('pause').setAttribute('aria-label', listening.on ? 'Pause listening' : 'Resume listening')
  tick()
  if (live && !calm.matches) requestAnimationFrame(wave)
  else drawWave(live ? 'icon' : 'flat')
}

let flash = { text: '', until: 0 } // "Not sent" or "Saved" takes the timer's place for a few seconds

function tick() {
  $('timer').textContent = timerText({ connected, flash: Date.now() < flash.until ? flash.text : '', startedAt: listening.startedAt, now: Date.now() })
}

const BARS = [...$('wave').children]
const ICON = [0.35, 0.6, 0.95, 0.55, 1, 0.7, 0.4] // the resting waveform glyph

function drawWave(shape) {
  BARS.forEach((bar, i) => (bar.style.transform = `scaleY(${shape === 'flat' ? 0.14 : ICON[i]})`))
}

let waving = false
function wave(t) {
  if (waving) return
  waving = true
  const frame = (now) => {
    if ($('bar').dataset.state !== 'live' || calm.matches) {
      waving = false
      return renderBar()
    }
    energy = Math.max(0.2, energy * 0.985)
    BARS.forEach((bar, i) => {
      const swing = Math.abs(Math.sin(now / (240 + i * 41) + i * 1.9))
      bar.style.transform = `scaleY(${0.16 + ICON[i] * (0.25 + 0.75 * energy) * swing})`
    })
    requestAnimationFrame(frame)
  }
  frame(t)
}

if (shows('bar')) {
  renderBar()
  setInterval(tick, 1000)
  calm.addEventListener('change', renderBar)
  window.overlay?.onStatus((state) => {
    connected = state !== 'off'
    renderBar()
  })
  $('pause').addEventListener('click', async () => {
    $('pause').disabled = true
    const { error } = await api('/listening', { on: !listening.on }) // the bar updates when the `listening` event comes back
    $('pause').disabled = !connected
    $('timer').title = error || ''
    if (error) flash = { text: 'Not sent', until: Date.now() + 3000 }
    tick()
  })
  $('endBtn').addEventListener('click', async () => {
    $('endBtn').disabled = true
    const { error } = await api('/calls/end') // the Recap follows, from the server or built by main.js
    $('endBtn').disabled = false
    flash = { text: error ? 'Not saved' : 'Saved', until: Date.now() + 4000 }
    $('timer').title = error || ''
    tick()
  })
  $('peopleBtn').addEventListener('click', () => window.overlay?.togglePeople())
  $('hideBtn').addEventListener('click', () => window.overlay?.toggleAll())
  $('transcriptBtn').addEventListener('click', () => {
    if (window.overlay && view !== 'all') window.overlay.toggleTranscript()
    else setTranscriptShown($('transcriptBtn').getAttribute('aria-pressed') !== 'true')
  })
  window.overlay?.onTranscriptShown(setTranscriptShown)
}

// "Show transcript" opens the strip along the bottom (its own window; the preview shows it in place).
function setTranscriptShown(shown) {
  $('transcriptBtn').setAttribute('aria-pressed', shown)
  $('transcriptBtn').setAttribute('aria-label', transcriptToggle(shown).label)
  if (view === 'all') {
    $('transcript').hidden = !shown
    $('captions').scrollTop = $('captions').scrollHeight // lines added while it was hidden couldn't scroll
  }
}

// ---------- Live insights (in the sheet; a new one shows as the notice while the pill is closed) ----------

let insights = null
let actions = [] // the latest actions, to put the right emoji on a query chip

function showInsights(next) {
  wakePanel()
  const prev = insights
  insights = next
  $('insightsEmpty').hidden = true
  $('topic').hidden = false
  if (next.topic !== prev?.topic) fresh($('topic'))
  $('topic').textContent = next.topic
  const seen = new Set(prev?.points)
  const points = shownPoints(next.points)
  $('points').replaceChildren(...points.map((p) => fresh(el('li', null, p), seen.has(p))))
  const had = new Set(prev?.actions.map((a) => a.id))
  $('actions').replaceChildren(...shownActions(next.actions).map((a) => fresh(actionRow(a, $('actionsNote')), had.has(a.id))))
  if (open || recapOn) return
  // closed: the pill widens for a moment with the newest point and the first action, and counts the rest
  const fresh_ = points.filter((p) => !seen.has(p))
  unseen += fresh_.length
  renderBadge()
  $('noticeTopic').textContent = next.topic
  $('noticePoint').textContent = fresh_[fresh_.length - 1] || points[points.length - 1] || ''
  $('noticeMeta').textContent = `${points.length} ${points.length === 1 ? 'note' : 'notes'} · ${next.actions.length} ${next.actions.length === 1 ? 'action' : 'actions'} · ⌘↵ to open`
  const first = next.actions[0]
  $('noticeAction').hidden = !first
  if (first) {
    $('noticeAction').firstElementChild.textContent = KIND_EMOJI[first.kind] || '✨'
    $('noticeAction').lastElementChild.textContent = first.label
    $('noticeAction').onclick = () => runAction(first.id, $('actionsNote'))
  }
  notify()
}

function setInsightsEmpty(on) {
  $('insightsEmpty').textContent = insightsEmptyText(on)
}
setInsightsEmpty()

// new lines blur in; lines that were already there stay still
function fresh(node, old = false) {
  if (!old) {
    node.classList.remove('fresh')
    void node.offsetWidth // restart the animation on a reused element
    node.classList.add('fresh')
  }
  return node
}

// One action chip; its answer arrives as `response` events in the thread, an error goes in `note`.
function actionRow({ id, kind, label }, note) {
  const item = el('li')
  const button = el('button', 'action')
  button.type = 'button'
  button.append(el('span', 'emoji', KIND_EMOJI[kind] || '✨'), el('span', 'label', label))
  button.firstChild.setAttribute('aria-hidden', 'true')
  button.addEventListener('click', async () => {
    button.disabled = true
    await runAction(id, note)
    button.disabled = false
  })
  item.append(button)
  return item
}

async function runAction(id, note) {
  const { error } = await api('/actions/' + encodeURIComponent(id))
  note.textContent = error || ''
}

// ---------- transcript strip ----------

const MAX_CAPTIONS = 200

function addCaption({ speaker, text, final }) {
  const list = $('captions')
  // a speaker's partial line keeps growing in place until its final version arrives
  const line = [...list.querySelectorAll('li.partial')].find((li) => li.dataset.speaker === speaker) || list.appendChild(el('li'))
  line.dataset.speaker = speaker
  line.className = final ? '' : 'partial'
  line.replaceChildren(el('span', 'who', speaker), el('span', 'said', text))
  while (list.children.length > MAX_CAPTIONS) list.firstElementChild.remove()
  list.scrollTop = list.scrollHeight // the newest line sits at the bottom edge
}

// ---------- Ask AI: a thread of questions and answers, in the sheet ----------

let turns = [] // [{ id, query, status, text, sources }], oldest first
let startNew = false // the next question starts a fresh thread (⌘↵ or the sparkle)
let closed = null // the turn open when the sheet was closed; its late events must not reopen it

function showResponse(e) {
  if (recapOn) return
  wakePanel()
  let turn = turns.find((t) => t.id === e.id)
  if (!turn) {
    turn = { id: e.id }
    turns.push(turn)
  }
  Object.assign(turn, { query: e.query, status: e.status, text: e.text || '', sources: e.sources || [] })
  renderThread(turn)
  if (e.id !== closed) setOpen(true)
}

function renderThread(changed) {
  $('thread').replaceChildren(...turns.map((t) => turnNode(t, t === changed)))
  $('question').placeholder = turns.length ? 'Ask a follow-up…' : 'Ask about this call…'
  $('thread').scrollTop = $('thread').scrollHeight
}

function turnNode({ query, status, text, sources }, animate) {
  const item = el('li', 'turn')
  item.dataset.state = status
  const chip = el('span', 'chip')
  chip.title = query || ''
  chip.append(el('span', 'emoji', KIND_EMOJI[actions.find((a) => a.label === query)?.kind] || ''), el('span', 'q', query || ''))
  item.append(chip)
  if (status === 'thinking') {
    const row = el('div', 'thinking')
    row.append(icon('sparkle', 'mark'), verb('Thinking,Searching,Reading,Writing'))
    item.append(row)
  }
  const answer = el('div', 'answer')
  answer.append(...answerLines(status, text).map((line, i) => {
    const p = el('p', null, line)
    if (animate) p.style.animationDelay = i * 70 + 'ms'
    else p.style.animation = 'none'
    return p
  }))
  item.append(answer)
  const list = el('ul', 'sources')
  list.setAttribute('aria-label', 'Sources')
  list.append(...(status === 'done' ? sources : []).map(sourceLink))
  item.append(list)
  return item
}

function sourceLink({ title, url }) {
  const item = el('li')
  const safe = /^https?:\/\//.test(url || '') // links come from search results; only open web pages
  const link = el(safe ? 'a' : 'span', 'source', title || url)
  if (safe) {
    link.href = url
    link.target = '_blank'
    link.rel = 'noreferrer'
    link.title = url
    link.append(icon('external'))
  }
  item.append(link)
  return item
}

// A fresh thread: the sheet opens, the thread clears and the next question is sent with new: true.
function startAsk() {
  closed = null
  turns = []
  startNew = true
  recapOn = false
  renderThread()
  $('askNote').textContent = ''
  $('question').value = ''
  setOpen(true)
  $('question').focus()
}

if (shows('response')) {
  window.overlay?.onAsk(startAsk)
  $('question').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !(e.metaKey || e.ctrlKey)) return
    e.preventDefault() // ⌘↵ starts a fresh thread (main's shortcut in the app; here in the preview)
    if (!window.overlay) startAsk()
  })
  $('askForm').addEventListener('submit', async (e) => {
    e.preventDefault()
    const question = $('question').value.trim()
    if (!question) return
    $('question').disabled = true
    $('askNote').textContent = ''
    const { id, error } = await api('/ask', startNew ? { question, new: true } : { question })
    $('question').disabled = false
    if (error) {
      $('askNote').textContent = error
      return $('question').focus()
    }
    startNew = false
    $('question').value = ''
    if (!turns.find((t) => t.id === id)) showResponse({ id, query: question, status: 'thinking' }) // unless its events came first
    $('question').focus()
  })
}

// ---------- Recap: the sheet one last time ----------

function showRecap(r) {
  recapOn = true
  open = false
  turns = [] // the thread ends with the call
  renderThread()
  const minutes = listening.startedAt ? Math.max(1, Math.round((Date.now() - Date.parse(listening.startedAt)) / 60000)) : 0
  $('ended').textContent = minutes ? `Call ended · ${minutes} min` : 'Call ended'
  $('recapTopic').textContent = r.topic || 'This call'
  $('recapPoints').replaceChildren(...(r.points || []).slice(0, 5).map((p) => fresh(el('li', null, p))))
  $('recapActions').replaceChildren(...shownActions(r.actions || []).map((a) => fresh(actionRow(a, $('recapNote')))))
  $('recapNote').textContent = ''
  $('recapPeopleTitle').hidden = !r.people?.length
  $('recapPeople').replaceChildren(...(r.people || []).map(recapPerson))
  syncStage()
}

function recapPerson({ name, role, lastTime }) {
  const item = el('li')
  const head = el('div', 'who-row')
  head.append(el('span', 'who', name), el('span', 'sub', role || ''))
  item.append(head)
  if (lastTime) item.append(el('p', 'last', lastTime))
  return item
}

// ---------- the island fits its window and fades when the call goes quiet ----------

const IDLE_MS = 20000
let idleTimer

function setIdle(idle) {
  document.body.classList.toggle('idle', idle)
  window.overlay?.setIdle(idle) // the window fades itself, OS blur included
}

function wakePanel() {
  if (document.body.classList.contains('idle')) setIdle(false)
  clearTimeout(idleTimer)
  idleTimer = setTimeout(() => {
    // quiet for a while: an open sheet folds back into the pill, unless a question is being typed
    if (open && !recapOn && document.activeElement !== $('question') && !$('question').value) setOpen(false)
    setIdle(true)
  }, IDLE_MS)
}

if (view === 'island' && window.overlay) {
  new ResizeObserver(() => {
    const { width, height } = $('island').getBoundingClientRect()
    window.overlay.fit({ width: Math.ceil(width), height: Math.ceil(height) })
  }).observe($('island'))
  wakePanel()
}

// The browser preview places the pieces the way the app does, from the same layout rules.
let previewWindow = { app: null, rect: null }
let previewPending = false
function schedulePreview() {
  if (previewPending) return
  previewPending = true
  requestAnimationFrame(() => {
    previewPending = false
    previewLayout()
  })
}
function previewLayout() {
  const work = { x: 0, y: 0, width: innerWidth, height: innerHeight }
  const l = layoutFor(previewWindow.app, previewWindow.rect, work)
  const put = (node, { x, y, width }) => Object.assign(node.style, { left: x + 'px', top: y + 'px', width: width + 'px' })
  const b = islandBounds(l.bar, { width: $('island').offsetWidth, height: $('island').offsetHeight }, work)
  Object.assign($('island').style, { left: b.x + 'px', top: b.y + 'px' }) // its width comes from the stage
  put($('transcript'), l.transcript)
  settleOthers(null) // cards keep clear of the island as it grows (main.js tells the real cards window)
}
if (view === 'all') {
  previewLayout()
  new ResizeObserver(schedulePreview).observe($('island'))
  window.addEventListener('resize', schedulePreview)
}

window.overlay?.onEvent(handle)

// ---------- People dashboard ----------

let everyone = []
let current = null // the person on the right: { id, step }

function personRow(p) {
  const item = el('li')
  const button = el('button', 'person-row')
  button.type = 'button'
  button.setAttribute('aria-current', String(current?.id === p.id))
  const sub = [p.role, shortDate(p.lastMet) && 'Met ' + shortDate(p.lastMet)].filter(Boolean).join(' · ')
  button.append(el('span', 'who', p.name), el('span', 'sub', sub))
  button.addEventListener('click', () => openPerson(p.id))
  item.append(button)
  return item
}

let shown = [] // the rows on screen, after search
let cursor = -1 // the keyboard-highlighted row

function renderPeople() {
  shown = filterPeople(everyone, $('peopleSearch').value)
  cursor = Math.min(cursor, shown.length - 1)
  $('peopleList').replaceChildren(...shown.map(personRow))
  markCursor()
  $('peopleEmpty').textContent = shown.length ? '' : everyone.length ? 'Nobody matches that.' : 'No one yet. Remember someone from a call.'
}

function markCursor() {
  const rows = $('peopleList').querySelectorAll('.person-row')
  rows.forEach((row, i) => row.classList.toggle('cursor', i === cursor))
  rows[cursor]?.scrollIntoView({ block: 'nearest' })
}

async function loadPeople() {
  const got = await api('/people', undefined, 'GET')
  if (got.error) $('peopleEmpty').textContent = got.error
  else {
    everyone = got
    renderPeople()
  }
  if (current) openPerson(current.id)
  renderStale(await api('/people/stale?days=30', undefined, 'GET'))
}

// "Haven't talked in a while": the people you last met 30 days ago or more, at the top; hidden when empty.
function renderStale(stale) {
  const rows = Array.isArray(stale) ? stale : []
  $('stale').hidden = !rows.length
  $('staleList').replaceChildren(...rows.map((p) => {
    const item = el('li')
    const button = el('button', 'person-row')
    button.type = 'button'
    button.append(el('span', 'who', p.name), el('span', 'sub', [p.role, staleLine(p)].filter(Boolean).join(' · ')))
    button.addEventListener('click', () => openPerson(p.id))
    item.append(button)
    return item
  }))
}

function showPersonNote(text) {
  const note = $('person').querySelector('.note')
  if (note) note.textContent = text
}

async function openPerson(id) {
  if (current?.id !== id) current = { id, step: 'idle' }
  const p = await api('/people/' + encodeURIComponent(id), undefined, 'GET')
  if (current?.id !== id) return // they picked someone else while this loaded
  if (p.error) {
    $('person').replaceChildren(el('p', 'note', p.error))
    return
  }
  renderPerson(p)
  renderPeople()
}

function renderPerson(p) {
  const role = el('input', 'role-field')
  Object.assign(role, { type: 'text', maxLength: 60, value: p.role || '', placeholder: 'Who are they to you?', autocomplete: 'off', spellcheck: false })
  role.setAttribute('aria-label', 'Who are they to you?')
  const saveRole = el('button', 'pill-btn', 'Save')
  saveRole.type = 'button'
  const note = el('p', 'note')
  note.setAttribute('role', 'status')
  const doSave = async () => {
    const { error } = await api('/people/' + encodeURIComponent(p.id), { role: cleanRole(role.value) }, 'PATCH')
    note.textContent = error || 'Saved.'
    if (!error) loadPeople()
  }
  saveRole.addEventListener('click', doSave)
  role.addEventListener('keydown', (e) => e.key === 'Enter' && doSave())
  const roleRow = el('div', 'role-row')
  roleRow.append(role, saveRole)

  // the same memory jogger as the card: the label row, then Muse's facts and how you met
  const facts = el('dl', 'facts')
  for (const f of cardFacts(p, Date.now())) {
    const item = el('div')
    const value = el('dd', null, f.value)
    if (f.title) value.title = f.title
    item.append(el('dt', null, f.label), value)
    facts.append(item)
  }
  const jogger = el('ul', 'bullets')
  jogger.append(...[...(p.facts || []).map((f) => f.text), p.howMet && 'Met ' + p.howMet].filter(Boolean).map((b) => el('li', null, oneLine(b, 80))))
  const talks = (p.encounters || []).map((e) => {
    const item = el('li', null, e.lastTime || '')
    const when = [shortDate(e.metAt || e.date), e.about].filter(Boolean).join(' · ')
    if (when) item.append(el('span', 'about', when))
    return item
  })
  const notes = (p.notes || []).map((n) => el('li', null, n.text))
  const sections = [el('h2', null, p.name), el('div', 'met', shortDate(p.firstMet) && 'First met ' + shortDate(p.firstMet)), roleRow, note, facts]
  if (jogger.children.length) sections.push(jogger)
  if (talks.length) sections.push(el('h3', null, 'Every conversation'), listOf(talks))
  if (notes.length) sections.push(el('h3', null, 'Notes'), listOf(notes))
  sections.push(deleteRow(p))
  $('person').replaceChildren(...sections)
}

function listOf(items) {
  const ul = el('ul')
  ul.append(...items)
  return ul
}

// Delete, then a confirm step inside this window; Cancel or Escape backs out.
function deleteRow(p) {
  const row = el('div', 'delete-row')
  const button = (text, className, event) => {
    const b = el('button', 'pill-btn ' + className, text)
    b.type = 'button'
    b.addEventListener('click', () => stepDelete(p, event))
    return b
  }
  if (current.step === 'idle') row.append(button('Delete…', '', 'delete'))
  else row.append(el('span', null, `Forget ${p.name}? This can't be undone.`), button('Delete', 'danger', 'confirm'), button('Cancel', '', 'cancel'))
  return row
}

async function stepDelete(p, event) {
  current.step = deleteStep(current.step, event)
  if (current.step !== 'deleting') return renderPerson(p)
  const { error } = await api('/people/' + encodeURIComponent(p.id), undefined, 'DELETE')
  if (error) {
    current.step = deleteStep('deleting', 'cancel')
    renderPerson(p)
    return showPersonNote(error)
  }
  current = null
  $('person').replaceChildren(el('p', 'empty', `${p.name} is forgotten.`))
  loadPeople()
}

if (view === 'people') {
  $('peopleSearch').addEventListener('input', renderPeople)
  $('closePeople').addEventListener('click', () => window.overlay?.togglePeople())
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.matches('button')) return // a focused button keeps its own Enter
    const field = e.target === $('peopleSearch') ? 'search' : e.target.matches('.role-field') ? 'role' : ''
    const { action, cursor: next } = peopleKey(e.key, { field, count: shown.length, cursor })
    if (!action) return
    e.preventDefault()
    cursor = next
    if (action === 'move') markCursor()
    if (action === 'open') openPerson(shown[cursor].id)
    if (action === 'search') $('peopleSearch').focus()
    if (action === 'close' && current?.step === 'confirm') {
      current.step = deleteStep('confirm', 'escape')
      openPerson(current.id)
    } else if (action === 'close') window.overlay?.togglePeople()
  })
  window.overlay?.onPeople(loadPeople)
  loadPeople()
}
