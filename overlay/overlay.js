// Renders memory-service events. view=cards draws name cards beside faces; view=dock draws the Top picks
// fed by Muse transcripts; view=both (a plain browser tab) draws everything, for styling.
// Event shapes: see README "Overlay events".
const q = new URLSearchParams(location.search)
const view = q.get('view') || 'both'
const origin = { x: +q.get('ox') || 0, y: +q.get('oy') || 0 } // this window's top-left in screen points
const KIND_LABEL = { fact: 'Note', common: 'In common', place: 'Place', event: 'Event' }
const MAX_PICKS = 3
const CARD = { width: 208, gap: 12 }

const $ = (id) => document.getElementById(id)
document.body.dataset.view = view
$('dock').hidden = view === 'cards'

function el(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text != null) node.textContent = text // names and quotes are untrusted; never innerHTML
  return node
}

function handle(e) {
  if (view !== 'dock') {
    if (e.type === 'face') return placeCard(e)
    if (e.type === 'face_gone') return removeCard(e.trackId)
  }
  if (view !== 'cards') {
    if (e.type === 'caption') return showCaption(e)
    if (e.type === 'pick') return addPick(e)
  }
}

// ---------- name cards ----------

function placeCard({ trackId, screenBox: [x, y, w], person }) {
  const id = 't' + trackId
  let card = $(id)
  const known = person ? person.id : 'unknown'
  if (!card) {
    card = el('div')
    card.id = id
    // the cards window ignores the mouse except while the pointer is over a card with an action
    card.addEventListener('mouseenter', () => card.classList.contains('actionable') && window.overlay?.setClickThrough(false))
    card.addEventListener('mouseleave', () => window.overlay?.setClickThrough(true))
    fillCard(card, person)
    $('cards').append(card)
  } else if (card.dataset.person !== known) morphCard(card, person)
  card.dataset.person = known
  // beside the face, flipping to the left side near the screen edge
  let left = x - origin.x + w + CARD.gap
  if (left + CARD.width > innerWidth) left = x - origin.x - CARD.width - CARD.gap
  card.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, y - origin.y)}px)`
}

function fillCard(card, person) {
  if (!person) return fillThinking(card)
  // Known faces are read-only: no hover state, clicks pass straight through to the call.
  card.className = 'card glass'
  const row = el('div', 'row')
  row.append(el('span', 'dot'), el('span', 'name', person.name))
  card.replaceChildren(row)
  if (person.line) card.append(el('div', 'line', person.line))
  card.append(el('div', 'met', person.met))
}

// Same element, new content: tween the old size to the new one and blur the new content in.
function morphCard(card, person) {
  const from = { width: card.offsetWidth + 'px', height: card.offsetHeight + 'px', borderRadius: getComputedStyle(card).borderRadius }
  fillCard(card, person)
  window.overlay?.setClickThrough(true) // the pointer may have been over the old card's action
  if (calm.matches) return
  const to = { width: card.offsetWidth + 'px', height: card.offsetHeight + 'px', borderRadius: getComputedStyle(card).borderRadius }
  card.animate([{ ...from, overflow: 'hidden' }, { ...to, overflow: 'hidden' }], { duration: 420, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' })
  for (const child of card.children) {
    child.animate([{ opacity: 0, filter: 'blur(4px)' }, { opacity: 1, filter: 'blur(0)' }], { duration: 320, delay: 120, easing: 'ease-out', fill: 'backwards' })
  }
}

// A face we can't name yet (still matching, or not enrolled) keeps a small glass card with a thinking
// sparkle instead of an "unknown" label. Its one action, the invite link, only appears on hover.
const VERBS = ['Recalling', 'Thinking', 'Remembering', 'Looking']
let verbIndex = 0

function fillThinking(card) {
  card.className = 'card glass thinking actionable'
  card.replaceChildren(sparkle(), el('span', 'verb', VERBS[verbIndex] + '…'))
  const invite = el('button', 'invite', 'Copy invite link')
  invite.type = 'button'
  invite.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(q.get('enroll') || '')
      invite.textContent = 'Copied · paste in the chat'
    } catch {
      invite.textContent = q.get('enroll') || 'No invite link set'
    }
  })
  card.append(invite)
}

function sparkle() {
  const ns = 'http://www.w3.org/2000/svg'
  const svg = document.createElementNS(ns, 'svg')
  svg.setAttribute('viewBox', '-12 -12 24 24')
  svg.setAttribute('class', 'sparkle')
  svg.setAttribute('aria-hidden', 'true')
  for (const angle of [0, 45, 90, 135]) {
    const ray = document.createElementNS(ns, 'line')
    ray.setAttribute('y1', '-9')
    ray.setAttribute('y2', '9')
    ray.setAttribute('transform', `rotate(${angle})`)
    svg.append(ray)
  }
  return svg
}

const calm = matchMedia('(prefers-reduced-motion: reduce)')
setInterval(() => {
  if (calm.matches) return
  verbIndex = (verbIndex + 1) % VERBS.length
  for (const verb of document.querySelectorAll('.thinking .verb')) {
    verb.textContent = VERBS[verbIndex] + '…'
    verb.animate([{ opacity: 0, filter: 'blur(3px)' }, { opacity: 1, filter: 'blur(0)' }], { duration: 320, easing: 'ease-out' })
  }
}, 2400)

function removeCard(trackId) {
  const card = $('t' + trackId)
  if (!card) return
  card.classList.add('leaving')
  window.overlay?.setClickThrough(true) // in case the pointer was over it
  setTimeout(() => card.remove(), 250)
}

// ---------- Top picks ----------

function showCaption({ speaker, text, final }) {
  $('caption').hidden = false
  $('caption').classList.toggle('partial', !final)
  $('captionWho').textContent = speaker
  $('captionText').textContent = text
}

function addPick({ kind, title, detail, quote, speaker }) {
  const list = $('picks')
  list.querySelector('.empty')?.remove()
  const item = el('li', 'pick')
  item.dataset.kind = kind
  item.append(el('span', 'kind', KIND_LABEL[kind] || 'Note'), el('strong', 'title', title))
  if (detail) item.append(el('span', 'detail', detail))
  if (quote) item.append(el('span', 'from', `${speaker}: "${quote}"`))
  list.prepend(item)
  while (list.children.length > MAX_PICKS) list.lastElementChild.remove()
}

// ---------- event source ----------

function setStatus(state, text) {
  $('status').dataset.state = state
  $('status').textContent = text
}

function connect() {
  const ws = new WebSocket(q.get('ws') || 'ws://localhost:8000/ws')
  ws.onopen = () => setStatus('on', 'Listening')
  ws.onmessage = (m) => handle(JSON.parse(m.data))
  ws.onclose = () => {
    setStatus('off', 'Reconnecting')
    setTimeout(connect, 2000)
  }
}

window.overlay?.onEvent(handle)
if (q.get('mock')) setStatus('demo', 'Demo replay')
else connect()
