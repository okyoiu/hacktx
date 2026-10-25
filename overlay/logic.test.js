// node --test (npm test in overlay/)
const test = require('node:test')
const assert = require('node:assert/strict')
const { ROUTES, elapsed, takesOver, cleanName } = require('./logic')

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
