const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('overlay', {
  onEvent: (fn) => ipcRenderer.on('event', (_e, event) => fn(event)),
  onStatus: (fn) => ipcRenderer.on('status', (_e, state) => fn(state)),
  onPeople: (fn) => ipcRenderer.on('people-open', () => fn()),
  onLaunch: (fn) => ipcRenderer.on('launch', (_e, statuses) => fn(statuses)),
  onAsk: (fn) => ipcRenderer.on('ask', () => fn()),
  onMute: (fn) => ipcRenderer.on('mute', () => fn()), // ⌘M
  onTranscriptShown: (fn) => ipcRenderer.on('transcript-shown', (_e, shown) => fn(shown)),
  onDebugShow: (fn) => ipcRenderer.on('debug-show', (_e, on) => fn(on)), // main only sends this in developer mode
  onIslandBounds: (fn) => ipcRenderer.on('island-bounds', (_e, bounds) => fn(bounds)),
  islandHover: (on) => ipcRenderer.send('island-hover', on), // the pointer came onto the island: main watches it
  onIslandHover: (fn) => ipcRenderer.on('island-hover', (_e, on) => fn(on)), // main: it has really left
  api: (route, body, method) => ipcRenderer.invoke('api', route, body, method),
  fit: (size) => ipcRenderer.send('fit', size), // a height, or { width, height } for the island
  setIdle: (idle) => ipcRenderer.send('panel-idle', idle),
  copy: (text) => ipcRenderer.send('copy', text),
  setClickThrough: (on) => ipcRenderer.send('click-through', on),
  focusCards: (on) => ipcRenderer.send('cards-focus', on),
  copyInvite: () => ipcRenderer.send('copy-invite'),
  togglePeople: () => ipcRenderer.send('people-toggle'),
  toggleTranscript: () => ipcRenderer.send('transcript-toggle'),
  toggleDebug: () => ipcRenderer.send('debug-toggle'), // nobody listens in the normal app
  ask: () => ipcRenderer.send('ask'),
  toggleAll: () => ipcRenderer.send('toggle-all'),
  menu: () => ipcRenderer.send('menu'), // the ⋯ menu / right-click: People, transcript, Debug (dev), Quit
  quit: () => ipcRenderer.send('quit'),
})
