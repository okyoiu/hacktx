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

test('a card shows at most 5 bullets (the server appends "This call: …"), falling back to the label and last time', () => {
  assert.deepEqual(bulletsOf({ bullets: ['a', ' ', 'b', 'c', 'd', 'This call: e', 'f'] }), ['a', 'b', 'c', 'd', 'This call: e'])
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

// ---------- round 5: presets, fixed spots, Ask AI nudge, Recap, debug ----------
const { presetFor, layoutFor, askPlace, cardRect, recapFrom, debugLabel, devMode, shouldMove, BAR, PANEL, STRIP, RECAP, MATCH_MIN } = require('./logic')

const WORK = { x: 0, y: 25, width: 1440, height: 875 } // a 13" Mac under its menu bar
const inside = (r, area = WORK) => r.x >= area.x && r.y >= area.y && r.x + r.width <= area.x + area.width && r.y + (r.height || 0) <= area.y + area.height
const overlap = (a, b) => Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))

test('each call app gets a preset; browsers mean Meet; anything else is general', () => {
  assert.equal(presetFor('zoom.us'), 'zoom')
  assert.equal(presetFor('Microsoft Teams classic'), 'teams')
  assert.equal(presetFor('FaceTime'), 'facetime')
  for (const app of ['Google Chrome', 'Arc', 'Safari']) assert.equal(presetFor(app), 'meet', app)
  for (const app of ['Discord', '', null, undefined]) assert.equal(presetFor(app), 'general', String(app))
})

test('full screen: the strip sits at the top, the rail inside on the app\'s free side, the transcript above its bar', () => {
  const full = [WORK.x, WORK.y, WORK.width, WORK.height]
  const expect = {
    zoom: { side: 'right', strip: 'center', bottom: 64, top: 48 },
    teams: { side: 'left', strip: 'left', bottom: 0, top: 64 },
    facetime: { side: 'left', strip: 'center', bottom: 80, top: 40 },
    meet: { side: 'left', strip: 'center', bottom: 88, top: 0 },
    general: { side: 'right', strip: 'center', bottom: 72, top: 48 },
  }
  const apps = { zoom: 'zoom.us', teams: 'Microsoft Teams', facetime: 'FaceTime', meet: 'Google Chrome', general: 'Discord' }
  for (const [preset, want] of Object.entries(expect)) {
    const l = layoutFor(apps[preset], full, WORK)
    assert.equal(l.preset, preset)
    for (const part of ['bar', 'insights', 'ask', 'transcript', 'recap']) assert.ok(inside(l[part]), `${preset} ${part} on screen`)
    assert.equal(l.bar.y, WORK.y + 6, `${preset} strip at the top`)
    assert.equal(l.bar.x, want.strip === 'left' ? 24 : Math.round((WORK.width - BAR.width) / 2), `${preset} strip ${want.strip}`)
    assert.equal(l.insights.x, want.side === 'left' ? 24 : WORK.width - 24 - PANEL.width, `${preset} rail ${want.side}`)
    assert.ok(l.insights.y >= Math.max(WORK.y + want.top, l.bar.y + l.bar.height) + 12, `${preset} rail below the strip and the app's top band`)
    assert.equal(l.ask.x, l.insights.x)
    assert.equal(l.ask.y, l.insights.y + 220 + 12, 'Ask AI under Live insights')
    assert.equal(l.transcript.y + l.transcript.height, WORK.y + WORK.height - want.bottom - 12, `${preset} transcript above the app's bar`)
    assert.equal(l.recap.x, Math.round((WORK.width - RECAP.width) / 2), 'Recap centred')
    assert.deepEqual(l.bands.map((b) => b.height), [want.top, want.bottom].filter(Boolean), `${preset} bands`)
  }
})

test('with room beside the window, the strip goes above it, the rail beside it on the wider side, the transcript below', () => {
  const big = { x: 0, y: 25, width: 2560, height: 1415 }
  const rect = [200, 120, 1400, 900]
  for (const app of ['zoom.us', 'Microsoft Teams']) {
    const l = layoutFor(app, rect, big)
    assert.equal(l.bar.y, 120 - 12 - BAR.height, 'strip above the window')
    assert.deepEqual([l.insights.x, l.insights.y], [1600 + 12, 120], `${app}: rail on the right, outside`)
    assert.equal(l.transcript.y, 1020 + 12, 'transcript below the window')
    assert.equal(l.transcript.x + l.transcript.width / 2, 900, 'transcript centred under the window')
    assert.equal(l.recap.x + l.recap.width / 2, 900, 'Recap centred over the window')
    for (const part of ['bar', 'insights', 'ask', 'transcript', 'recap']) assert.ok(inside(l[part], big), part)
  }
  const left = layoutFor('zoom.us', [1000, 120, 1400, 900], big)
  assert.equal(left.insights.x, 1000 - 12 - PANEL.width, 'the wider free side is the left')
})

test('no call window: the general layout over the whole work area, and a taller Live insights pushes Ask AI down', () => {
  assert.deepEqual(layoutFor(null, null, WORK), layoutFor('Discord', [WORK.x, WORK.y, WORK.width, WORK.height], WORK))
  assert.equal(layoutFor(null, null, WORK, 300).ask.y, layoutFor(null, null, WORK).insights.y + 300 + 12)
  assert.ok(inside(layoutFor('zoom.us', [-50, -50, 3000, 3000], WORK).insights), 'a window larger than the screen is clipped to it')
})

test('Ask AI stays in its spot when it covers nothing, else moves to a free area away from faces and controls', () => {
  const panel = { width: PANEL.width, height: 300 }
  const spot = { x: 968, y: 100 }
  const strip = { x: 360, y: 31, width: BAR.width, height: BAR.height }
  const bands = [{ x: 0, y: 836, width: 1440, height: 64 }]
  assert.deepEqual(askPlace({ work: WORK, spot, faces: [], blocks: [strip, ...bands], panel }), spot)
  const face = { x: 1000, y: 150, width: 200, height: 250 }
  const moved = askPlace({ work: WORK, spot, faces: [face], blocks: [strip, ...bands], panel })
  const placed = { ...moved, ...panel }
  assert.ok(inside(placed))
  for (const o of [face, strip, ...bands]) assert.equal(overlap(placed, o), 0, 'covers nothing')
  const under = askPlace({ work: WORK, spot: { x: 400, y: 40 }, faces: [], blocks: [strip], panel })
  assert.equal(overlap({ ...under, ...panel }, strip), 0, 'never under the control strip')
  const card = cardRect([800, 150, 200, 250], { x: 0, y: 0, width: 1440, height: 900 })
  assert.deepEqual(card, { x: 1012, y: 150, width: 300, height: 170 }, 'the card sits to the right of its face')
  const offCard = askPlace({ work: WORK, spot: { x: 968, y: 100 }, faces: [], blocks: [], cards: [card], panel })
  assert.equal(overlap({ ...offCard, ...panel }, card), 0, 'name cards are kept clear too')
})

test('Live insights keeps its rail and only slides along it to get off a face', () => {
  const panel = { width: PANEL.width, height: 380 }
  const spot = { x: 24, y: 114 }
  const face = { x: 180, y: 260, width: 200, height: 260 }
  const slid = askPlace({ work: WORK, spot, faces: [face], blocks: [], panel, fixedX: true })
  assert.equal(slid.x, 24, 'same side')
  assert.ok(slid.y !== spot.y && overlap({ ...slid, ...panel }, face) < 200 * 40, 'slid down past the face as far as the screen allows')
  assert.deepEqual(askPlace({ work: WORK, spot, faces: [], blocks: [], panel, fixedX: true }), spot)
  assert.deepEqual(cardRect([1000, 150, 200, 250], { x: 0, y: 0, width: 1440, height: 900 }, false), { x: 1212, y: 150, width: 132, height: 36 }, 'a pill is small')
})

test('when nothing is free, Ask AI covers a control before a card and a card before a face', () => {
  const panel = { width: PANEL.width, height: 300 }
  const work = { x: 0, y: 0, width: 500, height: 700 } // too narrow to dodge anything sideways
  const face = { x: 0, y: 0, width: 500, height: 320 }
  const control = { x: 0, y: 320, width: 500, height: 380 }
  const low = askPlace({ work, spot: { x: 24, y: 6 }, faces: [face], blocks: [control], panel })
  assert.ok(low.y >= 320 - 50, 'moved off the face onto the control')
  const card = { x: 0, y: 320, width: 500, height: 380 }
  const onCard = askPlace({ work, spot: { x: 24, y: 6 }, faces: [face], blocks: [], cards: [card], panel })
  assert.ok(onCard.y >= 320 - 50, 'and onto a card rather than a face')
})

test('Ask AI in a full-screen grid of faces with no window rect: on screen, covering as little as possible', () => {
  const panel = { width: PANEL.width, height: 300 }
  const faces = []
  for (const col of [140, 620, 1100]) for (const row of [125, 575]) faces.push({ x: col, y: row, width: 200, height: 200 })
  const spot = { x: 968, y: 100 }
  const at = askPlace({ work: WORK, spot, faces, blocks: [], panel })
  const placed = { ...at, ...panel }
  assert.ok(inside(placed))
  const covered = (r) => faces.reduce((sum, f) => sum + overlap(r, f), 0)
  assert.ok(covered(placed) < covered({ ...spot, ...panel }), 'better than the spot')
  assert.ok(covered(placed) <= 200 * 70, 'at most a sliver of one face (the grid leaves no gap wide enough)')
  assert.deepEqual(askPlace({ work: WORK, spot, faces, blocks: [], panel }), at, 'stable: the same answer every time')
})

test('without a recap from the server, one is built from the call\'s insights and the people seen', () => {
  const a = { type: 'insights', topic: 'Weekend plans', points: ['p1', 'p2'], actions: [{ id: 'x1', kind: 'events', label: 'e' }] }
  const b = { type: 'insights', topic: "Jordan's move", points: ['p3', 'p1'], actions: [{ id: 'x2', kind: 'places', label: 'g' }] }
  const people = [
    { id: 'p_j', name: 'Jordan Lee', role: 'Friend', line: 'Last time: the move' },
    { id: 'p_j', name: 'Jordan Lee', role: 'Friend', line: 'Last time: the move' },
    { id: 'p_m', name: 'Maya Chen', role: '', line: '' },
  ]
  assert.deepEqual(recapFrom([a, b], people), {
    type: 'recap',
    topic: "Jordan's move",
    points: ['p3', 'p1', 'p2'],
    actions: b.actions,
    people: [{ id: 'p_j', name: 'Jordan Lee', role: 'Friend', lastTime: 'Last time: the move' }, { id: 'p_m', name: 'Maya Chen', role: '', lastTime: '' }],
  })
  assert.equal(recapFrom([], []).topic, 'This call')
  assert.equal(recapFrom([{ points: Array.from({ length: 9 }, (_, i) => 'q' + i), actions: [] }], []).points.length, 5)
})

test('developer mode comes only from `npm run dev` (--dev) or HELLO_DEBUG=1 in the environment', () => {
  assert.ok(devMode(['electron', '.', '--dev'], {}))
  assert.ok(devMode([], { HELLO_DEBUG: '1' }))
  assert.ok(!devMode(['electron', '.', '--mock'], {}))
  assert.ok(!devMode([], { HELLO_DEBUG: 'yes' }))
  assert.ok(!devMode(['--debug'], {}), 'no other flag turns it on')
})

test('the debug label says the track, the score against the cutoff and the decision', () => {
  assert.equal(MATCH_MIN, 0.45)
  assert.equal(debugLabel({ trackId: 3, score: 0.62, decision: 'Jordan Lee' }), '#3 · 0.62 ≥ 0.45 · Jordan Lee')
  assert.equal(debugLabel({ trackId: 4, score: 0.31, decision: 'below 0.45' }), '#4 · 0.31 < 0.45 · below 0.45')
  assert.equal(debugLabel({ trackId: 5, score: null, decision: 'no face yet' }), '#5 · no score · no face yet')
})

test('a card follows its face only when the face really moved, never tracker jitter', () => {
  const face = [180, 260, 200, 260]
  assert.ok(shouldMove(null, face), 'a new card is placed')
  assert.ok(!shouldMove(face, [184, 262, 200, 260]), 'a few pixels is jitter')
  assert.ok(!shouldMove(face, [160, 240, 240, 300]), 'the box grew but its centre stayed')
  assert.ok(shouldMove(face, [220, 260, 200, 260]), 'moved 40 px across')
  assert.ok(shouldMove(face, [180, 300, 200, 260]), 'moved 40 px down')
  assert.ok(!shouldMove(face, [204, 284, 200, 260]), 'exactly the threshold stays')
})

// ---------- round 6: the island ----------
const { islandStage, islandBounds, ISLAND, NOTICE_MS } = require('./logic')

test('the island is a pill, widens to a notice for a moment, opens as a sheet, and is the Recap at the end', () => {
  const now = 10_000
  assert.equal(islandStage({ recap: false, open: false, noticeUntil: 0, now }), 'pill')
  assert.equal(islandStage({ recap: false, open: false, noticeUntil: now + NOTICE_MS, now }), 'notice')
  assert.equal(islandStage({ recap: false, open: false, noticeUntil: now, now }), 'pill', 'the notice is over')
  assert.equal(islandStage({ recap: false, open: true, noticeUntil: now + 100, now }), 'sheet', 'open beats the notice')
  assert.equal(islandStage({ recap: true, open: true, noticeUntil: now + 100, now }), 'recap', 'the Recap beats everything')
})

test('the island keeps its centre as it grows (Teams: its left edge) and stays on screen', () => {
  const spot = { x: 440, y: 31, width: BAR.width, height: BAR.height, anchor: 'center' }
  assert.deepEqual(islandBounds(spot, { width: ISLAND.pill, height: 44 }, WORK), { x: 440 + (BAR.width - ISLAND.pill) / 2, y: 31, width: ISLAND.pill, height: 44 })
  assert.deepEqual(islandBounds(spot, { width: BAR.width, height: 420 }, WORK), { x: 440, y: 31, width: BAR.width, height: 420 })
  const left = islandBounds({ ...spot, x: 24, anchor: 'left' }, { width: ISLAND.pill, height: 44 }, WORK)
  assert.equal(left.x, 24, 'Teams: grows to the right from the same left edge')
  const tall = islandBounds(spot, { width: BAR.width, height: 2000 }, WORK)
  assert.equal(tall.y + tall.height, WORK.y + WORK.height - 12, 'clipped to the work area')
  assert.equal(layoutFor('zoom.us', null, WORK).bar.anchor, 'center')
  assert.equal(layoutFor('Microsoft Teams', null, WORK).bar.anchor, 'left')
})

test('the transcript strip and Recap have fixed sizes the layout can count on', () => {
  assert.ok(STRIP.height > 0 && RECAP.width > PANEL.width)
})
