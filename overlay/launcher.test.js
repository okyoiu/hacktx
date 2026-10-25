// node --test: the launcher with a fake spawn
const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { createLauncher, trimLogs, MAX_LOG } = require('./launcher')

function setup({ running = [], dockerStartFails = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'launcher-'))
  const calls = []
  const children = []
  const spawn = (cmd, args) => {
    const child = Object.assign(new EventEmitter(), { cmd, args, killed: false, kill() { this.killed = true } })
    calls.push([cmd, ...args])
    children.push(child)
    const isDocker = cmd === 'docker'
    if (isDocker) setImmediate(() => child.emit('exit', dockerStartFails && args[0] === 'start' ? 1 : 0))
    return child
  }
  const statuses = []
  const launcher = createLauncher({
    root, spawn, isRunning: async (name) => running.includes(name), wait: async () => true,
    onStatus: (name, state) => statuses.push(`${name}:${state}`),
  })
  return { launcher, calls, children, statuses, root }
}
const uvChildren = (children) => children.filter((c) => c.cmd === 'uv')

test('starts only what is not already running', async () => {
  const { launcher, calls } = setup({ running: ['db', 'server'] })
  await launcher.start()
  assert.deepEqual(calls.map((c) => c.slice(0, 5).join(' ')), ['uv run --env-file .env python', 'uv run --env-file .env python'])
  assert.ok(calls[0].includes('capture.faces') && calls[1].includes('capture.transcribe'))
  assert.ok(!calls.some((c) => c[0] === 'docker'))
})

test('creates the database container, bound to this laptop, when there is none', async () => {
  const { launcher, calls, statuses } = setup({ dockerStartFails: true })
  await launcher.start()
  const run = calls.find((c) => c[0] === 'docker' && c[1] === 'run')
  assert.ok(run.includes('127.0.0.1:5432:5432'))
  assert.ok(statuses.includes('db:ok'))
})

test('no command line carries a key', async () => {
  process.env.MODEL_API_KEY = 'sk-test-secret'
  const { launcher, calls } = setup()
  await launcher.start()
  assert.ok(calls.length >= 4)
  assert.ok(!JSON.stringify(calls).includes('sk-test-secret'))
  assert.ok(calls.filter((c) => c[0] === 'uv').every((c) => c.join(' ').includes('--env-file .env')))
  delete process.env.MODEL_API_KEY
})

test('a process that dies is restarted once, then reported down', async () => {
  const { launcher, children, statuses } = setup({ running: ['db', 'server', 'transcribe'] })
  await launcher.start()
  uvChildren(children)[0].emit('exit', 1)
  assert.equal(uvChildren(children).length, 2, 'restarted')
  uvChildren(children)[1].emit('exit', 1)
  assert.equal(uvChildren(children).length, 2, 'not a second time')
  assert.deepEqual(statuses.filter((s) => s.startsWith('faces')), ['faces:ok', 'faces:restarting', 'faces:ok', 'faces:down'])
})

test('quitting stops what we started, not what was already running, and nothing restarts', async () => {
  const { launcher, children, calls } = setup({ running: ['server'] })
  await launcher.start()
  const started = uvChildren(children)
  launcher.stop()
  assert.ok(started.every((c) => c.killed))
  started[0].emit('exit', null)
  assert.equal(uvChildren(children).length, started.length, 'no restart while quitting')
  assert.ok(calls.some((c) => c[0] === 'docker' && c[1] === 'stop'), 'we started the db, so we stop it')
})

test('logs are private to this account, even ones an older version made', async () => {
  if (process.platform === 'win32') return
  const { launcher, root } = setup({ running: ['db'] })
  fs.mkdirSync(path.join(root, 'logs'))
  fs.writeFileSync(path.join(root, 'logs', 'server.log'), 'old', { mode: 0o644 })
  await launcher.start()
  for (const name of fs.readdirSync(path.join(root, 'logs'))) {
    assert.equal(fs.statSync(path.join(root, 'logs', name)).mode & 0o077, 0, name)
  }
})

test('a log over 1 MB keeps only its last 1 MB; small logs and other files are left alone', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'logs-'))
  fs.writeFileSync(path.join(dir, 'big.log'), 'a'.repeat(MAX_LOG) + 'END')
  fs.writeFileSync(path.join(dir, 'small.log'), 'hi')
  fs.writeFileSync(path.join(dir, 'other.txt'), 'b'.repeat(MAX_LOG * 2))
  trimLogs(dir)
  const big = fs.readFileSync(path.join(dir, 'big.log'), 'utf8')
  assert.equal(big.length, MAX_LOG)
  assert.ok(big.endsWith('END'))
  assert.equal(fs.readFileSync(path.join(dir, 'small.log'), 'utf8'), 'hi')
  assert.equal(fs.statSync(path.join(dir, 'other.txt')).size, MAX_LOG * 2)
  trimLogs(path.join(dir, 'missing')) // no logs folder yet: nothing to do
})
