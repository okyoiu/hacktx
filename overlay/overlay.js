// Renders memory-service events in one overlay window, picked by ?view=: cards (name cards beside faces),
// bar (control bar), insights (Live insights) or response (AI response). view=all, a plain browser tab,
// draws everything for styling. Event shapes: see README "Overlay events".
const q = new URLSearchParams(location.search)
const view = q.get('view') || 'all'
const shows = (part) => view === 'all' || view === part
const origin = { x: +q.get('ox') || 0, y: +q.get('oy') || 0 } // the cards window's top-left in screen points
const CARD = { width: 208, gap: 12 }
const KIND_EMOJI = { define: '📘', search: '🌐', places: '📍', events: '📅', recall: '👋', followups: '💬', helpful: '✨' }
const calm = matchMedia('(prefers-reduced-motion: reduce)')

const $ = (id) => document.getElementById(id)
document.body.dataset.view = view
$('bar').hidden = !shows('bar')
$('insights').hidden = !shows('insights')
if (!/Mac/.test(navigator.platform)) for (const key of document.querySelectorAll('kbd.mod')) key.textContent = 'Ctrl'

function el(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text != null) node.textContent = text // names, captions and answers are untrusted; never innerHTML
  return node
}

// resolves to the service's answer, or to { error } with a sentence to show (see main.js)
const api = (route, body) => (window.overlay ? window.overlay.api(route, body) : Promise.resolve({ error: 'Open the overlay app to send this.' }))

function handle(e) {
  if (shows('cards')) {
    if (e.type === 'face') placeCard(e)
    if (e.type === 'face_gone') removeCard(e.trackId)
  }
  if (shows('bar')) {
    if (e.type === 'listening') setListening(e)
    if (e.type === 'caption') energy = 1
  }
  if (shows('insights')) {
    if (e.type === 'insights') showInsights(e)
    if (e.type === 'caption') addCaption(e)
  }
  if (shows('response')) {
    if (e.type === 'insights') actions = e.actions
    if (e.type === 'response') showResponse(e)
  }
}

// ---------- name cards (click-through, never show tracking data) ----------

function placeCard({ trackId, screenBox: [x, y, w], person }) {
  const id = 't' + trackId
  let card = $(id)
  const known = person ? person.id : 'unknown'
  if (!card) {
    card = el('div')
    card.id = id
    card.dataset.track = trackId
    card.addEventListener('mouseenter', syncMouse)
    card.addEventListener('mouseleave', syncMouse)
    fillCard(card, person)
    $('cards').append(card)
  } else if (card.dataset.person !== known) morph(card, () => fillCard(card, person))
  card.dataset.person = known
  // beside the face, flipping to the left side near the screen edge
  let left = x - origin.x + w + CARD.gap
  if (left + CARD.width > innerWidth) left = x - origin.x - CARD.width - CARD.gap
  card.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, y - origin.y)}px)`
}

function fillCard(card, person) {
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
    card.className = 'card glass'
    const row = el('div', 'row')
    row.append(el('span', 'dot'), el('span', 'name', person.name))
    card.replaceChildren(row)
    if (person.line) card.append(el('div', 'line', person.line))
    card.append(el('div', 'met', person.met))
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
  form.append(name, yes, actions, note)
  card.replaceChildren(head, form)

  const ready = () => (save.disabled = !(cleanName(name.value) && consent.checked))
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
    for (const control of [name, consent, save]) control.disabled = true
    save.textContent = 'Saving…'
    note.textContent = ''
    card.dataset.saving = 'true'
    const { error, status } = await api(`/faces/${Number(card.dataset.track)}/remember`, { name: cleanName(name.value), consent: true })
    delete card.dataset.saving
    if (!card.classList.contains('remembering')) return // already their name card
    if (status === 409) return leftCall(card)
    if (card.dataset.gone) return leftCall(card, error ? undefined : 'Saved. They have left the call.') // left while saving
    if (error) {
      note.textContent = error
      save.textContent = 'Save'
      name.disabled = consent.disabled = false
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

// The cards window takes the mouse only while the pointer is over a thinking pill or its form.
const syncMouse = () => window.overlay?.setClickThrough(!document.querySelector('#cards :is(.thinking, .remembering):hover'))

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
    syncMouse() // in case the pointer was over it
  }, 250)
}

if (shows('cards')) {
  document.addEventListener('keydown', (e) => {
    const open = document.querySelector('.card.remembering')
    if (e.key === 'Escape' && open) closeRemember(open)
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

// ---------- control bar ----------

let listening = { on: false, startedAt: null }
let connected = !window.overlay || !!q.get('mock') // a browser preview has no connection to lose
let energy = 0 // jumps to 1 on each caption, then settles: the waveform breathes with the conversation

function setListening({ on, startedAt }) {
  listening = { on, startedAt: startedAt || listening.startedAt }
  renderBar()
}

function renderBar() {
  const live = connected && listening.on
  $('bar').dataset.state = !connected ? 'offline' : live ? 'live' : 'paused'
  $('pause').disabled = !connected
  $('pause').setAttribute('aria-label', listening.on ? 'Pause listening' : 'Resume listening')
  tick()
  if (live && !calm.matches) requestAnimationFrame(wave)
  else drawWave(live ? 'icon' : 'flat')
}

let notSentUntil = 0 // a failed pause shows "Not sent" in the timer's place for a few seconds

function tick() {
  $('timer').textContent = Date.now() < notSentUntil ? 'Not sent' : connected ? elapsed(listening.startedAt, Date.now()) : 'Offline'
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
    if (error) notSentUntil = Date.now() + 3000
    tick()
  })
  $('askBtn').addEventListener('click', () => window.overlay?.ask())
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
  $('points').replaceChildren(...next.points.slice(0, 3).map((p) => fresh(el('li', null, p), seen.has(p))))
  const had = new Set(prev?.actions.map((a) => a.id))
  $('actionsTitle').hidden = !next.actions.length
  $('actions').replaceChildren(...next.actions.slice(0, 4).map((a) => fresh(actionRow(a), had.has(a.id))))
}

// new lines blur in; lines that were already there stay still
function fresh(node, old = false) {
  if (!old) {
    node.classList.remove('fresh')
    void node.offsetWidth // restart the animation on a reused element
    node.classList.add('fresh')
  }
  return node
}

function actionRow({ id, kind, label }) {
  const item = el('li')
  const button = el('button', 'action')
  button.type = 'button'
  button.append(el('span', 'emoji', KIND_EMOJI[kind] || '✨'), el('span', null, label))
  button.firstChild.setAttribute('aria-hidden', 'true')
  button.addEventListener('click', async () => {
    button.disabled = true
    const { error } = await api('/actions/' + encodeURIComponent(id)) // the answer arrives as `response` events
    $('actionsNote').textContent = error || ''
    button.disabled = false
  })
  item.append(button)
  return item
}

const MAX_CAPTIONS = 200

function addCaption({ speaker, text, final }) {
  wakePanel()
  const list = $('transcript')
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 24
  // a speaker's partial line keeps growing in place until its final version arrives
  const line = [...list.querySelectorAll('li.partial')].find((li) => li.dataset.speaker === speaker) || list.appendChild(el('li'))
  line.dataset.speaker = speaker
  line.className = final ? '' : 'partial'
  line.replaceChildren(el('span', 'who', speaker), el('span', 'said', text))
  while (list.children.length > MAX_CAPTIONS) list.firstElementChild.remove()
  if (atBottom) list.scrollTop = list.scrollHeight
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
    const open = $('transcript').hidden
    $('transcript').hidden = !open
    $('insightsBody').hidden = open
    $('transcriptBtn').setAttribute('aria-pressed', open)
    $('transcriptBtn').lastElementChild.textContent = open ? 'Hide transcript' : 'Show transcript'
    if (open) $('transcript').scrollTop = $('transcript').scrollHeight
  })
  $('copyInsights').addEventListener('click', (e) => {
    const lines = $('transcript').hidden
      ? insights ? [insights.topic, ...insights.points.map((p) => '- ' + p)] : []
      : [...$('transcript').children].map((li) => `${li.dataset.speaker}: ${li.lastChild.textContent}`)
    copy(e.currentTarget, lines.join('\n'))
  })
}

// ---------- AI response ----------

let response = { state: 'idle' } // idle | ask | thinking | done | error
let actions = [] // the latest actions, to put the right emoji on a query chip
let closed = null

function showResponse(e) {
  if (!takesOver(response, e, closed)) return
  wakePanel()
  response = { state: e.status, id: e.id, query: e.query, text: e.text || '', sources: e.sources || [] }
  renderResponse()
}

function renderResponse() {
  const { state, query, text, sources } = response
  const panel = $('response')
  panel.hidden = state === 'idle'
  panel.dataset.state = state
  $('responseTitle').textContent = state === 'ask' ? 'Ask AI' : 'AI response'
  $('askForm').hidden = state !== 'ask'
  $('askNote').textContent = ''
  $('chip').hidden = state === 'ask' || !query
  $('chipEmoji').textContent = KIND_EMOJI[actions.find((a) => a.label === query)?.kind] || ''
  $('chipText').textContent = query || ''
  $('chip').title = query || ''
  $('copyAnswer').hidden = state === 'ask'
  $('copyAnswer').disabled = state !== 'done'
  $('thinking').hidden = state !== 'thinking'
  const lines = state === 'done' ? text.split('\n').filter((l) => l.trim())
    : state === 'error' ? ["Couldn't get an answer.", (text ? text + ' ' : '') + 'Try again in a moment.']
    : []
  $('answer').replaceChildren(...lines.map((line, i) => {
    const p = el('p', null, line)
    p.style.animationDelay = i * 70 + 'ms'
    return p
  }))
  $('sources').replaceChildren(...(state === 'done' ? sources : []).map(sourceLink))
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

function closeResponse() {
  closed = response.id
  window.overlay?.closeResponse(response.id)
  response = { state: 'idle' }
  setTimeout(renderResponse, window.overlay ? 200 : 0) // after the window has faded out
}

function startAsk() {
  closed = null
  response = { state: 'ask' }
  renderResponse()
  $('question').value = ''
  $('question').focus()
}

if (shows('response')) {
  window.overlay?.onAsk(startAsk)
  $('closeResponse').addEventListener('click', closeResponse)
  document.addEventListener('keydown', (e) => e.key === 'Escape' && response.state !== 'idle' && closeResponse())
  $('copyAnswer').addEventListener('click', (e) => {
    copy(e.currentTarget, [response.text, ...response.sources.map((s) => `${s.title}: ${s.url}`)].join('\n'))
  })
  $('askForm').addEventListener('submit', async (e) => {
    e.preventDefault()
    const question = $('question').value.trim()
    if (!question) return
    $('question').disabled = true
    response = { state: 'sent' } // the answer's events may arrive before its id does; let them in
    const { id, error } = await api('/ask', { question })
    $('question').disabled = false
    if (error) {
      response = { state: 'ask' }
      renderResponse()
      $('askNote').textContent = error
    } else if (response.id !== id) showResponse({ id, query: question, status: 'thinking' })
  })
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
  if (!shows(part)) continue
  $(part).addEventListener('mouseenter', wakePanel)
  if (view === part && window.overlay) {
    new ResizeObserver(() => window.overlay.fit(Math.ceil($(part).getBoundingClientRect().height))).observe($(part))
  }
}

window.overlay?.onEvent(handle)
if (shows('insights')) wakePanel()
