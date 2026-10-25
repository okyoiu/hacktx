// Renders memory-service events in one overlay window, picked by ?view=: cards (name cards beside faces),
// bar (control strip), insights (Live insights), response (Ask AI), transcript (the strip along the bottom),
// recap (the Recap) or people (the dashboard). view=all, a plain browser tab, draws everything for styling,
// placed with the same layout rules as the app. Event shapes: see README "Overlay events".
const q = new URLSearchParams(location.search)
const view = q.get('view') || 'all'
const shows = (part) => view === 'all' || view === part
const origin = { x: +q.get('ox') || 0, y: +q.get('oy') || 0 } // the cards window's top-left in screen points
const CARD = { width: 208, gap: 12, open: 210 } // open: room for a name and five bullets
const KIND_EMOJI = { define: '📘', search: '🌐', places: '📍', events: '📅', recall: '👋', followups: '💬', helpful: '✨' }
const calm = matchMedia('(prefers-reduced-motion: reduce)')
const DEBUG = q.get('debug') === '1' // developer mode: only main.js sets this, and only when started with `npm run dev`

const $ = (id) => document.getElementById(id)
document.body.dataset.view = view
$('bar').hidden = !shows('bar')
$('insights').hidden = !shows('insights')
$('transcript').hidden = view !== 'transcript' // in the preview it opens with "Show transcript"
$('response').hidden = view !== 'response' // in the preview it opens with a question or an answer
$('recap').hidden = view !== 'recap' // in the preview it opens with the recap event
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
      placeCard(e)
    }
    if (e.type === 'face_gone') removeCard(e.trackId)
    if (e.type === 'caption') heard(e.speaker)
    if (DEBUG && e.type === 'debug') drawDebug(e)
    if (DEBUG && e.type === 'face_gone') $('dbg' + e.trackId)?.remove()
  }
  if (shows('bar')) {
    if (e.type === 'listening') setListening(e)
    if (e.type === 'caption') energy = 1
  }
  if (shows('insights')) {
    if (e.type === 'listening') setInsightsEmpty(e.on)
    if (e.type === 'insights') showInsights(e)
  }
  if (shows('transcript') && e.type === 'caption') addCaption(e)
  if (shows('response')) {
    if (e.type === 'insights') actions = e.actions
    if (e.type === 'response') showResponse(e)
    if (e.type === 'recap') endThread() // the thread ends with the call
  }
  if (shows('recap') && e.type === 'recap') showRecap(e)
  if (view === 'all') {
    if (e.type === 'window') previewWindow = e
    if (e.type === 'recap') $('insights').hidden = true // the Recap takes over, like main.js
    if (e.type === 'insights') $('insights').hidden = false
    if (['window', 'face', 'face_gone', 'insights', 'response'].includes(e.type)) schedulePreview()
  }
}

// ---------- name cards (click-through, never show tracking data) ----------

function placeCard({ trackId, screenBox, person }) {
  const id = 't' + trackId
  let card = $(id)
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
}

// A known card is placed for its open size, so opening it never pushes it over the face.
function position(card) {
  const [x, y, w, h] = JSON.parse(card.dataset.face)
  const known = card.classList.contains('known')
  const size = known ? { width: CARD.width, height: CARD.open } : { width: card.offsetWidth || CARD.width, height: card.offsetHeight || 40 }
  const { left, top } = cardPlace({ face: [x - origin.x, y - origin.y, w, h], card: size, screen: { width: innerWidth, height: innerHeight }, gap: CARD.gap })
  card.style.transform = `translate(${left}px, ${top}px)`
}
window.addEventListener('resize', () => document.querySelectorAll('#cards .card[data-face]').forEach(position))

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
    const bullets = el('ul', 'bullets')
    bullets.append(...bulletsOf(person).map((b) => fresh(el('li', null, b), oldBullets.has(b))))
    const inner = el('div')
    inner.append(bullets, el('div', 'met', person.met))
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
  const close = el('button', 'icon-btn')
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
  const toggle = el('button', 'icon-btn debug-btn')
  toggle.type = 'button'
  toggle.title = 'Debug view ⌘⌥D: what the computer sees'
  toggle.setAttribute('aria-label', toggle.title)
  toggle.setAttribute('aria-pressed', 'false')
  toggle.append(icon('eye'))
  toggle.addEventListener('click', () => window.overlay?.toggleDebug())
  window.overlay?.onDebugShow((on) => toggle.setAttribute('aria-pressed', String(on)))
  $('peopleBtn').after(toggle)
}

// ---------- control bar ----------

let listening = { on: false, startedAt: null }
let connected = !window.overlay || !!q.get('mock') // a browser preview has no connection to lose
let energy = 0 // jumps to 1 on each caption, then settles: the waveform breathes with the conversation

function setListening({ on, startedAt }) {
  listening = { on, startedAt: startedAt || listening.startedAt }
  renderBar()
}

// The status dot: green, or amber with what's wrong, from GET /health every 10 s and from the launcher.
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

let flash = { text: '', until: 0 } // "Not sent" or "Saved what you talked about" takes the timer's place for a few seconds

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
    flash = { text: error ? 'Not saved' : 'Saved what you talked about', until: Date.now() + 4000 }
    $('timer').title = error || ''
    tick()
  })
  $('askBtn').addEventListener('click', () => (window.overlay ? window.overlay.ask() : startAsk()))
  $('peopleBtn').addEventListener('click', () => window.overlay?.togglePeople())
  $('hideBtn').addEventListener('click', () => window.overlay?.toggleAll())
}

// ---------- Live insights ----------

let insights = null

function showInsights(next) {
  wakePanel()
  const prev = insights
  insights = next
  $('insightsEmpty').hidden = true
  $('topic').hidden = false
  if (next.topic !== prev?.topic) fresh($('topic'))
  $('topic').textContent = next.topic
  const seen = new Set(prev?.points)
  $('points').replaceChildren(...shownPoints(next.points).map((p) => fresh(el('li', null, p), seen.has(p))))
  const had = new Set(prev?.actions.map((a) => a.id))
  $('actionsTitle').hidden = !next.actions.length
  $('actions').replaceChildren(...shownActions(next.actions).map((a) => fresh(actionRow(a, $('actionsNote')), had.has(a.id))))
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

// One action row; its answer arrives as `response` events in the Ask AI panel, an error goes in `note`.
function actionRow({ id, kind, label }, note) {
  const item = el('li')
  const button = el('button', 'action')
  button.type = 'button'
  button.append(el('span', 'emoji', KIND_EMOJI[kind] || '✨'), el('span', null, label))
  button.firstChild.setAttribute('aria-hidden', 'true')
  button.addEventListener('click', async () => {
    button.disabled = true
    const { error } = await api('/actions/' + encodeURIComponent(id))
    note.textContent = error || ''
    button.disabled = false
  })
  item.append(button)
  return item
}

// "Show transcript" opens the strip along the bottom (its own window; the preview shows it in place).
function setTranscriptShown(shown) {
  $('transcriptBtn').setAttribute('aria-pressed', shown)
  $('transcriptBtn').lastElementChild.textContent = transcriptToggle(shown).label
  if (view === 'all') {
    $('transcript').hidden = !shown
    $('captions').scrollTop = $('captions').scrollHeight // lines added while it was hidden couldn't scroll
    schedulePreview()
  }
}

function copy(button, text) {
  if (window.overlay) window.overlay.copy(text)
  else navigator.clipboard?.writeText(text).catch(() => {})
  button.classList.add('done')
  button.setAttribute('aria-label', 'Copied')
  setTimeout(() => {
    button.classList.remove('done')
    button.setAttribute('aria-label', button.dataset.label)
  }, 1400)
}
for (const button of document.querySelectorAll('.copy-btn')) button.dataset.label = button.getAttribute('aria-label')

if (shows('insights')) {
  $('transcriptBtn').addEventListener('click', () => {
    if (window.overlay && view !== 'all') window.overlay.toggleTranscript()
    else setTranscriptShown($('transcriptBtn').getAttribute('aria-pressed') !== 'true')
  })
  window.overlay?.onTranscriptShown(setTranscriptShown)
  $('copyInsights').addEventListener('click', (e) => {
    copy(e.currentTarget, insights ? [insights.topic, ...insights.points.map((p) => '- ' + p)].join('\n') : '')
  })
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

// ---------- Ask AI: a thread of questions and answers ----------

let turns = [] // [{ id, query, status, text, sources }], oldest first
let actions = [] // the latest actions, to put the right emoji on a query chip
let startNew = false // the next question starts a fresh thread (⌘↵ or the Ask AI button)
let closed = null // the turn the user closed; its late events must not reopen the panel

function showResponse(e) {
  if (e.id === closed) return
  wakePanel()
  let turn = turns.find((t) => t.id === e.id)
  if (!turn) {
    turn = { id: e.id }
    turns.push(turn)
  }
  Object.assign(turn, { query: e.query, status: e.status, text: e.text || '', sources: e.sources || [] })
  renderThread(turn)
}

function renderThread(changed) {
  $('response').hidden = view === 'all' && !turns.length && !asking
  $('thread').replaceChildren(...turns.map((t) => turnNode(t, t === changed)))
  $('copyAnswer').disabled = !turns.some((t) => t.status === 'done')
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

let asking = false // the preview keeps the panel open while a question is being typed
function closeResponse() {
  closed = turns.at(-1)?.id ?? null
  asking = false
  window.overlay?.closeResponse(closed ?? '')
  setTimeout(() => renderThread(), window.overlay ? 200 : 0) // after the window has faded out
}

// A fresh thread: the panel clears and the next question is sent with new: true.
function startAsk() {
  closed = null
  turns = []
  startNew = true
  asking = true
  renderThread()
  $('askNote').textContent = ''
  $('question').value = ''
  if (view === 'all') previewLayout() // the app's main.js places the panel before it takes focus; so does the preview
  $('question').focus()
  busy()
}

// The thread ends with the call.
function endThread() {
  turns = []
  startNew = true
  renderThread()
}

// Main must not move the panel while the question field is focused or holds text.
const busy = () => window.overlay?.setAskBusy(document.activeElement === $('question') || !!$('question').value)

if (shows('response')) {
  window.overlay?.onAsk(startAsk)
  $('closeResponse').addEventListener('click', closeResponse)
  document.addEventListener('keydown', (e) => e.key === 'Escape' && !$('response').hidden && closeResponse())
  $('copyAnswer').addEventListener('click', (e) => {
    const lines = turns.filter((t) => t.status === 'done').flatMap((t) => [t.query, t.text, ...t.sources.map((s) => `${s.title}: ${s.url}`), ''])
    copy(e.currentTarget, lines.join('\n'))
  })
  for (const type of ['focus', 'blur', 'input']) $('question').addEventListener(type, busy)
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
    busy()
    if (!turns.find((t) => t.id === id)) showResponse({ id, query: question, status: 'thinking' }) // unless its events came first
    $('question').focus()
  })
}

// ---------- Recap ----------

function showRecap(r) {
  $('recap').hidden = false
  $('recapTopic').textContent = r.topic || 'This call'
  $('recapPoints').replaceChildren(...(r.points || []).slice(0, 5).map((p) => fresh(el('li', null, p))))
  $('recapActionsTitle').hidden = !r.actions?.length
  $('recapActions').replaceChildren(...shownActions(r.actions || []).map((a) => fresh(actionRow(a, $('recapNote')))))
  $('recapNote').textContent = ''
  $('recapPeopleTitle').hidden = !r.people?.length
  $('recapPeople').replaceChildren(...(r.people || []).map(recapPerson))
  $('recap').dataset.copy = [r.topic, ...(r.points || []).map((p) => '- ' + p), ...(r.people || []).map((p) => `${p.name}: ${p.lastTime || ''}`)].join('\n')
}

function recapPerson({ name, role, lastTime }) {
  const item = el('li')
  const head = el('div', 'who-row')
  head.append(el('span', 'who', name), el('span', 'sub', role || ''))
  item.append(head)
  if (lastTime) item.append(el('p', 'last', lastTime))
  return item
}

function closeRecap() {
  if (window.overlay && view === 'recap') window.overlay.closeRecap()
  else $('recap').hidden = true
}

if (shows('recap')) {
  $('closeRecap').addEventListener('click', closeRecap)
  if (view === 'recap') document.addEventListener('keydown', (e) => e.key === 'Escape' && closeRecap())
  $('copyRecap').addEventListener('click', (e) => copy(e.currentTarget, $('recap').dataset.copy || ''))
}

// ---------- panels fit their windows and fade when the call goes quiet ----------

const IDLE_MS = 20000
let idleTimer

function setIdle(idle) {
  document.body.classList.toggle('idle', idle)
  window.overlay?.setIdle(idle) // the panel window fades itself, OS blur included
}

function wakePanel() {
  if (document.body.classList.contains('idle')) setIdle(false)
  clearTimeout(idleTimer)
  idleTimer = setTimeout(() => setIdle(true), IDLE_MS)
}

for (const part of ['insights', 'response']) {
  if (shows(part)) $(part).addEventListener('mouseenter', wakePanel)
}
for (const part of ['insights', 'response', 'recap']) {
  if (view === part && window.overlay) {
    new ResizeObserver(() => window.overlay.fit(Math.ceil($(part).getBoundingClientRect().height))).observe($(part))
  }
}

// The browser preview places the pieces the way the app does, from the same layout rules: the spots follow the
// call window, and Ask AI is nudged clear of faces (unless a question is being typed), like main.js.
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
  const l = layoutFor(previewWindow.app, previewWindow.rect, work, $('insights').offsetHeight || 220)
  const put = (node, { x, y, width }) => Object.assign(node.style, { left: x + 'px', top: y + 'px', width: width + 'px' })
  put($('bar'), l.bar)
  put($('transcript'), l.transcript)
  put($('recap'), l.recap)
  const cardNodes = [...document.querySelectorAll('#cards .card[data-face]')]
  const boxes = cardNodes.map((c) => JSON.parse(c.dataset.face))
  const faces = boxes.map(([x, y, width, height]) => ({ x, y, width, height }))
  const cards = boxes.map((box, i) => cardRect(box, work, cardNodes[i].classList.contains('known')))
  const blocks = [l.bar, ...l.bands]
  const insights = { ...askPlace({ work, spot: l.insights, faces, blocks, cards, panel: { width: l.insights.width, height: $('insights').offsetHeight || 220 }, fixedX: true }), width: l.insights.width, height: $('insights').offsetHeight }
  put($('insights'), insights)
  if (document.activeElement === $('question') || $('question').value) return
  blocks.push(insights)
  if (!$('transcript').hidden) blocks.push(l.transcript)
  const spot = { x: insights.x, y: insights.y + insights.height + 12 }
  put($('response'), { ...askPlace({ work, spot, faces, blocks, cards, panel: { width: l.ask.width, height: $('response').offsetHeight || 160 } }), width: l.ask.width })
}
if (view === 'all') {
  previewLayout()
  new ResizeObserver(schedulePreview).observe($('insights'))
  window.addEventListener('resize', schedulePreview)
}

window.overlay?.onEvent(handle)
if (shows('insights')) wakePanel()

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

  const last = p.encounters?.[0]?.lastTime
  const talks = (p.encounters || []).map((e) => {
    const item = el('li', null, e.lastTime || '')
    const when = [shortDate(e.date), e.about].filter(Boolean).join(' · ')
    if (when) item.append(el('span', 'about', when))
    return item
  })
  const notes = (p.notes || []).map((n) => el('li', null, n.text))
  const sections = [el('h2', null, p.name), el('div', 'met', shortDate(p.firstMet) && 'First met ' + shortDate(p.firstMet)), roleRow, note]
  if (last) sections.push(el('h3', null, 'Last time'), el('p', null, last))
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
