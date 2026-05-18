const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('auraDesktop', {
  isElectron: true,
  getRuntimeCandidates: () => ipcRenderer.invoke('aura:runtime:candidates'),
  readRuntimeToken: (tokenPath) => ipcRenderer.invoke('aura:runtime:read-token', tokenPath),
  openExternal: (url) => ipcRenderer.invoke('aura:shell:open-external', url),
})
