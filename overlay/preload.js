const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('overlay', {
  onEvent: (fn) => ipcRenderer.on('event', (_e, event) => fn(event)),
  onStatus: (fn) => ipcRenderer.on('status', (_e, state) => fn(state)),
  onAsk: (fn) => ipcRenderer.on('ask', () => fn()),
  api: (route, body) => ipcRenderer.invoke('api', route, body),
  fit: (height) => ipcRenderer.send('fit', height),
  setIdle: (idle) => ipcRenderer.send('panel-idle', idle),
  copy: (text) => ipcRenderer.send('copy', text),
  setClickThrough: (on) => ipcRenderer.send('click-through', on),
  focusCards: (on) => ipcRenderer.send('cards-focus', on),
  copyInvite: () => ipcRenderer.send('copy-invite'),
  ask: () => ipcRenderer.send('ask'),
  toggleAll: () => ipcRenderer.send('toggle-all'),
  closeResponse: (id) => ipcRenderer.send('close-response', id),
})
