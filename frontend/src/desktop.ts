import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { open } from '@tauri-apps/plugin-dialog'

const backendUrl = 'http://127.0.0.1:8765'

function isTauriRuntime() {
  return Boolean(window.__TAURI_INTERNALS__)
}

function installDesktopBridge() {
  if (!isTauriRuntime()) return

  window.ingestorDesktop = {
    backendUrl,
    getBackendUrl: () => invoke<string>('get_backend_url'),
    pickFolder: async () => {
      const selected = await open({
        directory: true,
        multiple: false,
        title: 'Select documentation folder',
      })
      return typeof selected === 'string' ? selected : null
    },
    pickFiles: async () => {
      const selected = await open({
        multiple: true,
        title: 'Select documentation files',
        filters: [
          {
            name: 'Documentation',
            extensions: ['md', 'mdx', 'txt', 'rst', 'html', 'htm', 'json', 'yaml', 'yml', 'toml'],
          },
          { name: 'All Files', extensions: ['*'] },
        ],
      })
      if (!selected) return []
      return Array.isArray(selected) ? selected : [selected]
    },
    getStartupSettings: () => invoke<StartupSettings>('get_startup_settings'),
    setStartupEnabled: (enabled) => invoke<StartupSettings>('set_startup_enabled', { enabled }),
    onBackendStatus: (callback) => {
      let unlisten: (() => void) | null = null
      void listen<BackendStatus>('backend-status', (event) => callback(event.payload)).then((handler) => {
        unlisten = handler
      })
      return () => {
        unlisten?.()
      }
    },
  }
}

installDesktopBridge()
