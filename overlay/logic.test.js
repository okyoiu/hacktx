// node --test (npm test in overlay/)
const test = require('node:test')
const assert = require('node:assert/strict')
const { ROUTES, elapsed, takesOver, cleanName, peopleKey, cardPlace, healthProblems, insightsEmptyText, inviteLink, launchWarning, cleanRole, filterPeople, shortDate, deleteStep, rememberBody, shouldPop, isOpen, bulletsOf, POP_MS, validCall, webUrl, barState, timerText, shownPoints, shownActions, transcriptToggle, answerLines, rememberKey, canSave, rememberResult, isQuiet, BIG_CALL, QUIET_MS } = require('./logic')

test('main only forwards the memory API calls the overlay makes', () => {
  for (const route of ['/listening', '/ask', '/actions/x1', '/actions/act_2-b']) assert.ok(ROUTES.test(route), route)
  for (const route of ['/people/p_1', '/enroll', '/actions/', '/actions/..', '/actions/a%2Fb', '/ask?x=1', '//evil.test/ask']) {
    assert.ok(!ROUTES.test(route), route)
  }
})

test('"Remember them" only posts for a numeric face track', () => {
  assert.ok(ROUTES.test('/faces/3/remember'))
  for (const route of ['/faces/x/remember', '/faces/NaN/remember', '/faces//remember', '/faces/3/remember/..', '/faces/3']) {
    assert.ok(!ROUTES.test(route), route)
  }
})

test('a typed name is trimmed, single-spaced and at most 80 characters, like the enroll page', () => {
  assert.equal(cleanName('  Maya   Chen \n'), 'Maya Chen')
  assert.equal(cleanName('   '), '')
  assert.equal(cleanName('x'.repeat(200)).length, 80)
})

test('the call timer counts from startedAt', () => {
  const start = '2026-10-24T21:40:00Z'
  const t = Date.parse(start)
  assert.equal(elapsed(start, t + 20_000), '00:20')
  assert.equal(elapsed(start, t + 3_725_000), '1:02:05')
  assert.equal(elapsed(start, t - 5_000), '00:00') // a clock a little behind the server's
  assert.equal(elapsed(undefined, t), '00:00')
})

test('only the current answer or a new question replaces the AI response', () => {
  const shown = { state: 'thinking', id: 'r1' }
  assert.ok(takesOver(shown, { id: 'r1', status: 'done' }))
  assert.ok(takesOver(shown, { id: 'r2', status: 'thinking' }))
  assert.ok(takesOver({ state: 'idle' }, { id: 'r3', status: 'done' }))
  assert.ok(!takesOver(shown, { id: 'r0', status: 'done' }), 'a late answer to an older question')
  assert.ok(!takesOver(shown, { id: 'r1', status: 'done' }, 'r1'), 'the user closed it')
  assert.ok(!takesOver({ state: 'ask' }, { id: 'r2', status: 'thinking' }), 'the user is typing a question')
})

test('name cards only go quiet in big calls, after a minute without activity', () => {
  assert.ok(isQuiet(BIG_CALL, 0, QUIET_MS + 1))
  assert.ok(!isQuiet(BIG_CALL, 0, QUIET_MS), 'exactly a minute is not yet quiet')
  assert.ok(!isQuiet(BIG_CALL - 1, 0, QUIET_MS * 10), 'a small call keeps every card')
})

test('main forwards only known routes with a small plain-object body', () => {
  assert.ok(validCall('/ask', { question: 'hi' }))
  assert.ok(validCall('/listening'))
  assert.ok(!validCall('/ask', 'text'))
  assert.ok(!validCall('/ask', [1]))
  assert.ok(!validCall('/ask', { question: 'x'.repeat(3000) }))
  assert.ok(!validCall({ toString: () => '/ask' }, {}), 'a route that is not a string')
  assert.ok(!validCall('/people/p_1'))
})

test('only http(s) links open in the browser', () => {
  assert.ok(webUrl('https://example.com/a'))
  assert.ok(webUrl('http://example.com'))
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'smb://host/share', 'not a url', undefined]) assert.ok(!webUrl(url), String(url))
})

test('the bar shows offline, live or paused, and the timer follows', () => {
  assert.equal(barState(false, true), 'offline')
  assert.equal(barState(true, true), 'live')
  assert.equal(barState(true, false), 'paused')
  const start = '2026-10-24T21:40:00Z'
  const now = Date.parse(start) + 65_000
  assert.equal(timerText({ connected: true, startedAt: start, now }), '01:05')
  assert.equal(timerText({ connected: true, flash: 'Not sent', startedAt: start, now }), 'Not sent')
  assert.equal(timerText({ connected: false, startedAt: start, now }), 'Offline')
})

test('Live insights shows at most 3 points and 4 actions, and the transcript toggle flips', () => {
  assert.equal(shownPoints(['a', 'b', 'c', 'd']).length, 3)
  assert.equal(shownActions([1, 2, 3, 4, 5]).length, 4)
  assert.deepEqual(transcriptToggle(true), { open: true, label: 'Hide transcript' })
  assert.deepEqual(transcriptToggle(false), { open: false, label: 'Show transcript' })
})

test('the AI response draws paragraphs only for done and error', () => {
  assert.deepEqual(answerLines('done', 'One.\n\n  \nTwo.'), ['One.', 'Two.'])
  assert.deepEqual(answerLines('error', ''), ["Couldn't get an answer.", 'Try again in a moment.'])
  assert.deepEqual(answerLines('error', 'Timed out.'), ["Couldn't get an answer.", 'Timed out. Try again in a moment.'])
  for (const state of ['thinking', 'ask', 'idle']) assert.deepEqual(answerLines(state, 'x'), [])
})

test('Remember them: Enter saves only when ready, Escape always cancels', () => {
  assert.equal(rememberKey('Enter', true), 'save')
  assert.equal(rememberKey('Enter', false), null)
  assert.equal(rememberKey('Escape', false), 'cancel')
  assert.equal(rememberKey('a', true), null)
  assert.ok(canSave(' Maya ', true))
  assert.ok(!canSave('   ', true), 'a blank name')
  assert.ok(!canSave('Maya', false), 'no yes yet')
})

test('Remember them: a 409 says they left, a failure keeps the form, a late save is still honest', () => {
  assert.deepEqual(rememberResult({ error: 'x', status: 409 }), { kind: 'left', text: 'They left the call before saving.' })
  assert.deepEqual(rememberResult({ error: 'Try again.', status: 500 }), { kind: 'error', text: 'Try again.' })
  assert.deepEqual(rememberResult({}), { kind: 'saved' })
  assert.equal(rememberResult({}, 'true').text, 'Saved. They have left the call.')
  assert.equal(rememberResult({ error: 'x' }, 'true').text, undefined, 'unsaved and gone: the default sentence')
})

test('a known card pops open once per person, for 10 seconds, and again while hovered', () => {
  const seen = new Set()
  assert.ok(shouldPop(seen, 'p_1'))
  seen.add('p_1')
  assert.ok(!shouldPop(seen, 'p_1'))
  assert.ok(shouldPop(seen, 'p_2'))
  assert.equal(POP_MS, 10_000)
  assert.ok(isOpen(POP_MS, false, POP_MS - 1))
  assert.ok(!isOpen(POP_MS, false, POP_MS), 'shrinks at 10 seconds')
  assert.ok(isOpen(POP_MS, true, POP_MS * 5), 'hover opens it again')
})

test('a card shows at most 3 bullets, falling back to the label and last time', () => {
  assert.deepEqual(bulletsOf({ bullets: ['a', ' ', 'b', 'c', 'd'] }), ['a', 'b', 'c'])
  assert.deepEqual(bulletsOf({ role: 'Your team lead', line: 'Last time: the move' }), ['Your team lead', 'Last time: the move'])
  assert.deepEqual(bulletsOf({ bullets: [], role: '', line: '' }), [])
})

test('Remember them sends the optional role only when typed, at most 60 characters', () => {
  assert.deepEqual(rememberBody(' Maya  Chen ', ''), { name: 'Maya Chen', consent: true })
  assert.deepEqual(rememberBody('Maya', '  Your   team lead '), { name: 'Maya', consent: true, role: 'Your team lead' })
  assert.equal(rememberBody('Maya', 'x'.repeat(100)).role.length, 60)
})

test('the dashboard may read, rename and delete people, nothing else', () => {
  assert.ok(validCall('/people', undefined, 'GET'))
  assert.ok(validCall('/people/p_1a2b', undefined, 'GET'))
  assert.ok(validCall('/people/p_1a2b', { role: 'Your team lead' }, 'PATCH'))
  assert.ok(validCall('/people/p_1a2b', undefined, 'DELETE'))
  for (const [route, method] of [['/people', 'DELETE'], ['/people', 'PATCH'], ['/people/p_1', 'POST'], ['/people/../ask', 'GET'], ['/people/a/b', 'GET'], ['/enroll', 'GET'], ['/ask', 'GET'], ['/people/p_1', 'PUT']]) {
    assert.ok(!validCall(route, undefined, method), `${method} ${route}`)
  }
  assert.ok(!validCall('/people/p_1', { role: 'x'.repeat(3000) }, 'PATCH'))
  assert.ok(!validCall('/ask', { question: 'hi' }, 'GET'), 'POST routes stay POST')
})

test('search finds people by name or label, ignoring case', () => {
  const people = [{ name: 'Jordan Lee', role: 'Your team lead' }, { name: 'Maya Chen', role: '' }, { name: 'Sam' }]
  assert.deepEqual(filterPeople(people, '  MAYA ').map((p) => p.name), ['Maya Chen'])
  assert.deepEqual(filterPeople(people, 'lead').map((p) => p.name), ['Jordan Lee'])
  assert.equal(filterPeople(people, '').length, 3)
  assert.equal(filterPeople(people, 'zzz').length, 0)
})

test('dates read as "Sep 24" and a bad date as nothing; labels are cleaned like the form', () => {
  assert.equal(shortDate('2026-09-24T18:00:00Z'), 'Sep 24')
  assert.equal(shortDate('nope'), '')
  assert.equal(shortDate(undefined), '')
  assert.equal(cleanRole('  Your   team lead '), 'Your team lead')
  assert.equal(cleanRole('x'.repeat(90)).length, 60)
})

test('deleting someone takes Delete then Confirm, and anything else backs out', () => {
  assert.equal(deleteStep('idle', 'confirm'), 'idle', 'no confirm without asking first')
  const asked = deleteStep('idle', 'delete')
  assert.equal(asked, 'confirm')
  assert.equal(deleteStep(asked, 'confirm'), 'deleting')
  for (const back of ['cancel', 'escape', 'switch']) assert.equal(deleteStep(asked, back), 'idle')
})

test('the bar warns about each part that is down, and says nothing when all is well', () => {
  assert.equal(launchWarning({ db: 'ok', server: 'ok', faces: 'restarting' }), '')
  assert.equal(launchWarning({ db: 'ok', faces: 'down', transcribe: 'down' }), 'Face capture · Transcription')
  assert.equal(launchWarning({ nonsense: 'down' }), '')
})

test('the invite link carries the code only when one is set, URL-encoded', () => {
  assert.equal(inviteLink('http://192.168.1.5:8000/enroll', ''), 'http://192.168.1.5:8000/enroll')
  assert.equal(inviteLink('http://192.168.1.5:8000/enroll', undefined), 'http://192.168.1.5:8000/enroll')
  assert.equal(inviteLink('http://192.168.1.5:8000/enroll', 'taco'), 'http://192.168.1.5:8000/enroll?code=taco')
  assert.equal(inviteLink('http://x.test/enroll', 'a b&c=d'), 'http://x.test/enroll?code=a+b%26c%3Dd')
  assert.equal(inviteLink('http://x.test/enroll?lang=en', 'taco'), 'http://x.test/enroll?lang=en&code=taco')
  assert.equal(inviteLink('not a url', 'taco'), 'not a url')
})

test('End call is a POST the overlay may make, and /health a GET', () => {
  assert.ok(validCall('/calls/end'))
  assert.ok(validCall('/health', undefined, 'GET'))
  assert.ok(!validCall('/health'), 'health is read-only')
  assert.ok(!validCall('/calls/end', undefined, 'GET'))
})

test('the status dot names what is wrong', () => {
  assert.deepEqual(healthProblems({ problems: [] }), [])
  assert.deepEqual(healthProblems({ ok: true, checks: { database: true, muse: true } }), [])
  assert.deepEqual(healthProblems({ database: true, muse: false, serpapi: 'down' }), ['muse is not working', 'serpapi is not working'])
  assert.deepEqual(healthProblems({ problems: ['No Muse key', 7] }), ['No Muse key'])
  assert.deepEqual(healthProblems({ error: 'x' }), ['The memory server is not answering'])
  assert.deepEqual(healthProblems({ problems: [] }, 'Face capture'), ['Face capture stopped'])
})

test('Live insights says Listening… until the first insight, and Paused when paused', () => {
  assert.equal(insightsEmptyText(undefined), 'Listening…')
  assert.equal(insightsEmptyText(true), 'Listening…')
  assert.match(insightsEmptyText(false), /^Paused/)
})

test('a card sits beside its face, flips to the other side, then below or above, and never covers the face', () => {
  const card = { width: 200, height: 150 }
  const screen = { width: 1000, height: 800 }
  const at = (face) => cardPlace({ face, card, screen })
  assert.deepEqual(at([100, 100, 200, 200]), { left: 312, top: 100 }, 'right of the face')
  assert.deepEqual(at([700, 100, 200, 200]), { left: 488, top: 100 }, 'no room on the right: left')
  assert.deepEqual(at([100, 700, 200, 90]), { left: 312, top: 642 }, 'a side card slides up to stay on screen')
  const wide = at([20, 20, 960, 300]) // a face as wide as the screen: below
  assert.deepEqual(wide, { left: 20, top: 332 })
  assert.deepEqual(at([20, 300, 960, 480]), { left: 20, top: 138 }, 'no room below: above')
  for (const face of [[100, 100, 200, 200], [700, 100, 200, 200], [20, 20, 960, 300], [20, 300, 960, 480]]) {
    const { left, top } = at(face)
    const [x, y, w, h] = face
    const apart = left + card.width <= x || left >= x + w || top + card.height <= y || top >= y + h
    assert.ok(apart, `covers ${face}`)
  }
})

test('dashboard keys: arrows move, Enter opens, / searches, Esc closes, a label being typed is left alone', () => {
  const list = { count: 3, cursor: -1 }
  assert.deepEqual(peopleKey('ArrowDown', list), { action: 'move', cursor: 0 })
  assert.deepEqual(peopleKey('ArrowDown', { count: 3, cursor: 2 }), { action: 'move', cursor: 2 }, 'stops at the end')
  assert.deepEqual(peopleKey('ArrowUp', { count: 3, cursor: 0 }), { action: 'move', cursor: 0 }, 'stops at the top')
  assert.deepEqual(peopleKey('Enter', { count: 3, cursor: 1 }), { action: 'open', cursor: 1 })
  assert.deepEqual(peopleKey('Enter', { ...list, field: 'search' }), { action: 'open', cursor: 0 }, 'the first match')
  assert.equal(peopleKey('Enter', { count: 0, cursor: -1 }).action, null, 'nobody to open')
  assert.equal(peopleKey('ArrowDown', { count: 0, cursor: -1 }).action, null)
  assert.equal(peopleKey('/', list).action, 'search')
  assert.equal(peopleKey('/', { ...list, field: 'search' }).action, null, 'a slash typed into search stays a slash')
  assert.equal(peopleKey('Escape', list).action, 'close')
  assert.equal(peopleKey('Escape', { ...list, field: 'role' }).action, 'close')
  for (const key of ['Enter', 'ArrowDown', '/']) assert.equal(peopleKey(key, { ...list, field: 'role' }).action, null, key)
})

test('dashboard search also finds the "who they are to you" label', () => {
  const people = [{ name: 'Jordan Lee', role: 'Recruiter at Meta' }, { name: 'Maya Chen', role: 'Your team lead' }]
  assert.deepEqual(filterPeople(people, 'recruiter').map((p) => p.name), ['Jordan Lee'])
  assert.deepEqual(filterPeople(people, 'TEAM LEAD').map((p) => p.name), ['Maya Chen'])
})
