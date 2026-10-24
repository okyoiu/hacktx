const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('overlay', {
  setClickThrough: (on) => ipcRenderer.send('click-through', on),
  setDockIdle: (idle) => ipcRenderer.send('dock-idle', idle),
  onEvent: (fn) => ipcRenderer.on('event', (_e, event) => fn(event)),
})
