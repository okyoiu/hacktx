// Small rules shared by main.js and the renderer (loaded as a plain script), tested in logic.test.js.

// The only memory API calls the overlay makes; main refuses anything else. Action ids are short words.
const ROUTES = /^\/(listening|ask|actions\/[\w-]+|faces\/\d+\/remember)$/

// A name typed into "Remember them": trimmed, single-spaced, at most 80 characters like the enroll page.
function cleanName(raw) {
  return String(raw).trim().replace(/\s+/g, ' ').slice(0, 80)
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
function validCall(route, body) {
  if (typeof route !== 'string' || !ROUTES.test(route)) return false
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

if (typeof module !== 'undefined') module.exports = { ROUTES, elapsed, takesOver, cleanName, validCall, webUrl, isQuiet, BIG_CALL, QUIET_MS }
