const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('overlay', {
  onEvent: (fn) => ipcRenderer.on('event', (_e, event) => fn(event)),
  onStatus: (fn) => ipcRenderer.on('status', (_e, state) => fn(state)),
  onPeople: (fn) => ipcRenderer.on('people-open', () => fn()),
  onAsk: (fn) => ipcRenderer.on('ask', () => fn()),
  api: (route, body, method) => ipcRenderer.invoke('api', route, body, method),
  fit: (height) => ipcRenderer.send('fit', height),
  setIdle: (idle) => ipcRenderer.send('panel-idle', idle),
  copy: (text) => ipcRenderer.send('copy', text),
  setClickThrough: (on) => ipcRenderer.send('click-through', on),
  focusCards: (on) => ipcRenderer.send('cards-focus', on),
  copyInvite: () => ipcRenderer.send('copy-invite'),
  togglePeople: () => ipcRenderer.send('people-toggle'),
  ask: () => ipcRenderer.send('ask'),
  toggleAll: () => ipcRenderer.send('toggle-all'),
  closeResponse: (id) => ipcRenderer.send('close-response', id),
})
