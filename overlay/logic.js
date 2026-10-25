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

if (typeof module !== 'undefined') module.exports = { ROUTES, elapsed, takesOver, cleanName, isQuiet, BIG_CALL, QUIET_MS }
