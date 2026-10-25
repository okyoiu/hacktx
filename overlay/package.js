// `npm run package`: a double-clickable app with its own icon, built from the Electron this repo already has, no
// new dependency. The bundle holds only Electron and a tiny shim that runs THIS folder's main.js by its absolute
// path, so `git pull` updates the app without a rebuild. No .env, keys, notes/, logs/ or face data go in.
//  macOS:   overlay/dist/Hello Again.app
//  Windows: overlay/dist/Hello Again/Hello Again.exe   (same shim; untested here)
const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const here = __dirname
const dist = path.join(here, 'dist')
const electron = path.join(here, 'node_modules', 'electron', 'dist')
const NAME = 'Hello Again'
const ID = 'com.helloagain.overlay'

// Runs inside the app. Finder (and a Windows shortcut) starts apps with a bare PATH, so it adds the folders where
// uv and docker usually are before the launcher looks for them. If the repo folder is gone, it says to rebuild.
const shim = `// Built by \`npm run package\` on ${new Date().toISOString().slice(0, 10)}. Runs the overlay from the repo so \`git pull\` updates the app.
const path = require('node:path')
const os = require('node:os')
const OVERLAY = ${JSON.stringify(here)}
process.env.PATH = ['/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin'), process.env.PATH || '/usr/bin:/bin'].join(path.delimiter)
try {
  require(path.join(OVERLAY, 'main.js'))
} catch (err) {
  const { app, dialog } = require('electron')
  app.whenReady().then(() => {
    dialog.showErrorBox('Hello Again', 'The code folder this app runs is missing or broken:\\n' + OVERLAY + '\\n\\nGet the repo back, then rebuild: cd overlay && npm run package\\n\\n' + err.message)
    app.quit()
  })
}
`

function writeShim(appDir) {
  fs.mkdirSync(appDir, { recursive: true })
  fs.writeFileSync(path.join(appDir, 'package.json'), JSON.stringify({ name: 'hello-again', private: true, main: 'main.js' }, null, 2) + '\n')
  fs.writeFileSync(path.join(appDir, 'main.js'), shim)
}

function mac() {
  const bundle = path.join(dist, `${NAME}.app`)
  fs.rmSync(bundle, { recursive: true, force: true })
  fs.mkdirSync(dist, { recursive: true })
  execFileSync('ditto', [path.join(electron, 'Electron.app'), bundle]) // keeps symlinks, modes and the code's structure
  const contents = path.join(bundle, 'Contents')
  const resources = path.join(contents, 'Resources')
  const plist = path.join(contents, 'Info.plist')
  fs.renameSync(path.join(contents, 'MacOS', 'Electron'), path.join(contents, 'MacOS', NAME)) // the process is "Hello Again" too
  for (const [key, value] of [['CFBundleName', NAME], ['CFBundleDisplayName', NAME], ['CFBundleExecutable', NAME], ['CFBundleIdentifier', ID], ['CFBundleIconFile', 'icon.icns']]) {
    execFileSync('plutil', ['-replace', key, '-string', value, plist])
  }
  fs.rmSync(path.join(resources, 'electron.icns'), { force: true })
  fs.rmSync(path.join(resources, 'default_app.asar'), { force: true }) // Electron's own placeholder app
  fs.copyFileSync(path.join(here, 'icon.icns'), path.join(resources, 'icon.icns'))
  writeShim(path.join(resources, 'app'))
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', bundle])
  console.log(`Built ${bundle}\nDouble-click it, or drag it to the Dock.`)
}

// shortcut: copies the whole Electron folder and renames the exe; nobody on the team has Windows to try it.
function windows() {
  const folder = path.join(dist, NAME)
  fs.rmSync(folder, { recursive: true, force: true })
  fs.cpSync(electron, folder, { recursive: true })
  fs.renameSync(path.join(folder, 'electron.exe'), path.join(folder, `${NAME}.exe`))
  fs.rmSync(path.join(folder, 'resources', 'default_app.asar'), { force: true })
  writeShim(path.join(folder, 'resources', 'app'))
  console.log(`Built ${path.join(folder, `${NAME}.exe`)}`)
}

if (process.platform === 'win32') windows()
else if (process.platform === 'darwin') mac()
else {
  console.error('npm run package builds a Mac or Windows app; on Linux run `npm start`.')
  process.exit(1)
}
