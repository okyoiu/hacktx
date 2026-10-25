// The consent text people actually see: the enroll page carries the security agent's exact points, and the
// Remember form reads the same points aloud, one line each (TASKS.md Round 8).
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { REMEMBER_POINTS } = require('./logic')

const page = fs.readFileSync(path.join(__dirname, '..', 'web', 'enroll.html'), 'utf8')

test('the enroll page names every use of what it keeps, in the agreed words', () => {
  for (const line of [
    'Remember each other?',
    "Hello Again runs on the host's laptop. It will remember you for one year, or until you delete it.",
    'Only the host sees this on their screen; a screen share can show it.',
    'it saves numbers made from your face so it can recognise you on calls. It does not keep your photo.',
    'and, if the host adds one, who you are to them.',
    "on a call, the audio is sent to Meta's Muse to turn it into text. This happens for everyone on the call.",
    'Meta\'s Muse reads it and writes notes, short facts (like "Loves F1"), how you met, and a summary and topic for each call. The host sees these next to your face and in their People list.',
    'you can delete all of it at any time with the link you get after you agree.',
    'I agree to all of the above.',
    "Also let the host's Muse app read my notes (the connector)",
  ]) assert.ok(page.includes(line), line)
  assert.ok(!page.includes('Nobody else in the call sees anything'), 'the old line is gone')
  assert.ok(page.includes('<input id="connector" type="checkbox">'), 'the second tick is separate and unticked')
  assert.ok(page.includes("if ($('connector').checked) body.append('connector', '1')"), 'connector=1 goes only when ticked')
})

test('the Remember form reads the same points, one short line each', () => {
  assert.equal(REMEMBER_POINTS.length, 5)
  for (const p of REMEMBER_POINTS) assert.ok(p.length <= 60 && !p.includes('\n'), p)
  const text = REMEMBER_POINTS.join(' ').toLowerCase()
  for (const word of ['face', 'photo', 'name', 'voice', 'muse', 'notes', 'facts', 'delete']) assert.ok(text.includes(word), word)
})
