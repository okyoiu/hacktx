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

// Up to 3 bullets: the server's, or (an older server) the label and the last-time line.
function bulletsOf(person) {
  const list = person.bullets?.length ? person.bullets : [person.role, person.line]
  return list.filter((b) => typeof b === 'string' && b.trim()).slice(0, 3)
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

if (typeof module !== 'undefined') module.exports = { ROUTES, elapsed, takesOver, cleanName, healthProblems, insightsEmptyText, inviteLink, launchWarning, cleanRole, filterPeople, shortDate, deleteStep, rememberBody, shouldPop, isOpen, bulletsOf, POP_MS, validCall, webUrl, barState, timerText, shownPoints, shownActions, transcriptToggle, answerLines, rememberKey, canSave, rememberResult, isQuiet, BIG_CALL, QUIET_MS }
