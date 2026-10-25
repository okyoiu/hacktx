// node --test (npm test in overlay/)
const test = require('node:test')
const assert = require('node:assert/strict')
const { ROUTES, elapsed, takesOver, cleanName, shouldPop, isOpen, bulletsOf, POP_MS, validCall, webUrl, barState, timerText, shownPoints, shownActions, transcriptToggle, answerLines, rememberKey, canSave, rememberResult, isQuiet, BIG_CALL, QUIET_MS } = require('./logic')

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
  assert.equal(timerText({ connected: true, notSent: true, startedAt: start, now }), 'Not sent')
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
