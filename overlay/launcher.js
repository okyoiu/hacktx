// One launch: start whatever isn't already running, stop what we started, restart a dead one once.
// Commands name the .env file but never carry a key; logs go to logs/<name>.log (git-ignored).
const net = require('node:net')
const { execFile, spawn: realSpawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const DB = 'hello-again-db'
const DB_RUN = ['run', '-d', '--name', DB, '-p', '127.0.0.1:5432:5432', '-e', 'POSTGRES_PASSWORD=postgres', 'pgvector/pgvector:pg17']
const uv = (...args) => ({ cmd: 'uv', args: ['run', '--env-file', '.env', ...args] })

// Each runs from the repo root, in this order; the capture parts need the server.
const PROCESSES = [
  { name: 'server', ...uv('uvicorn', 'memory.app:app', '--host', '127.0.0.1', '--port', '8000') },
  { name: 'faces', ...uv('python', '-u', '-m', 'capture.faces') }, // -u: lines reach the log as they happen
  { name: 'transcribe', ...uv('python', '-u', '-m', 'capture.transcribe') },
]

// shortcut: pgrep and docker are looked up on PATH and pgrep is Unix-only, upgrade if Windows ever matters.
const out = (cmd, args) => new Promise((resolve) => execFile(cmd, args, (err, stdout) => resolve(err ? '' : stdout.trim())))
const portOpen = (port) =>
  new Promise((resolve) => {
    const s = net.connect(port, '127.0.0.1')
    s.once('connect', () => (s.destroy(), resolve(true)))
    s.once('error', () => resolve(false))
  })
async function waitForPort(port, ms = 60_000) {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 500))) if (await portOpen(port)) return true
  return false
}
const systemIsRunning = async (name) =>
  name === 'db' ? !!(await out('docker', ['ps', '-q', '--filter', `name=^${DB}$`]))
  : name === 'server' ? portOpen(8000)
  : !!(await out('pgrep', ['-f', `capture.${name}`]))

// Keeps each log's last MAX_LOG bytes, so logs/ can't grow without bound.
const MAX_LOG = 1024 * 1024
function trimLogs(dir) {
  for (const name of fs.existsSync(dir) ? fs.readdirSync(dir) : []) {
    const file = path.join(dir, name)
    const { size } = fs.statSync(file)
    if (!name.endsWith('.log') || size <= MAX_LOG) continue
    const fd = fs.openSync(file, 'r')
    const tail = Buffer.alloc(MAX_LOG)
    fs.readSync(fd, tail, 0, MAX_LOG, size - MAX_LOG)
    fs.closeSync(fd)
    fs.writeFileSync(file, tail, { mode: 0o600 })
  }
}

// Everything is injectable so the tests can fake it.
function createLauncher({ root, spawn = realSpawn, isRunning = systemIsRunning, wait = waitForPort, onStatus = () => {} }) {
  const mine = new Map() // name -> child we started
  const restarted = new Set()
  let stopping = false

  const logFile = (name) => {
    const file = path.join(root, 'logs', name + '.log')
    fs.mkdirSync(path.dirname(file), { recursive: true })
    const fd = fs.openSync(file, 'a', 0o600)
    fs.fchmodSync(fd, 0o600) // a log from an older version may have been created with looser rights
    return fd
  }
  const run = (cmd, args, log) => spawn(cmd, args, { cwd: root, stdio: ['ignore', log, log] })
  const exitCode = (child) => new Promise((resolve) => (child.once('exit', resolve), child.once('error', () => resolve(1))))

  function launch(p) {
    const child = run(p.cmd, p.args, logFile(p.name))
    mine.set(p.name, child)
    onStatus(p.name, 'ok')
    let gone = false
    const died = () => {
      if (gone || stopping) return
      gone = true
      mine.delete(p.name)
      if (restarted.has(p.name)) return onStatus(p.name, 'down')
      restarted.add(p.name)
      onStatus(p.name, 'restarting')
      launch(p)
    }
    child.once('exit', died)
    child.once('error', died)
  }

  async function startDb() {
    if (await isRunning('db')) return onStatus('db', 'ok')
    const log = logFile('db')
    let code = await exitCode(run('docker', ['start', DB], log))
    if (code) code = await exitCode(run('docker', DB_RUN, log)) // no such container yet
    if (code) return onStatus('db', 'down')
    mine.set('db', null)
    onStatus('db', 'ok')
    await wait(5432, 30_000)
  }

  return {
    async start() {
      trimLogs(path.join(root, 'logs'))
      await startDb()
      for (const p of PROCESSES) {
        if (await isRunning(p.name)) onStatus(p.name, 'ok')
        else launch(p)
        if (p.name === 'server') await wait(8000)
      }
    },
    stop() {
      stopping = true
      for (const [name, child] of mine) {
        if (name === 'db') run('docker', ['stop', DB], 'ignore')
        else child.kill()
      }
      mine.clear()
    },
  }
}

module.exports = { createLauncher, trimLogs, MAX_LOG, PROCESSES }
