import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { open } from '@tauri-apps/plugin-dialog'
import { relaunch } from '@tauri-apps/plugin-process'
import { check, type Update } from '@tauri-apps/plugin-updater'
import { getCurrentWindow } from '@tauri-apps/api/window'
import type { DragDropEvent } from '@tauri-apps/api/window'

const backendUrl = 'http://127.0.0.1:8765'
let pendingUpdate: Update | null = null

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
    getCliPathSettings: () => invoke<CliPathSettings>('get_cli_path_settings'),
    addCliToPath: () => invoke<CliPathSettings>('add_cli_to_path'),
    checkForUpdate: async () => {
      pendingUpdate = await check()
      if (!pendingUpdate) {
        return { available: false }
      }
      return {
        available: true,
        version: pendingUpdate.version,
        currentVersion: pendingUpdate.currentVersion,
        date: pendingUpdate.date,
        body: pendingUpdate.body,
      }
    },
    installUpdate: async () => {
      if (!pendingUpdate) {
        throw new Error('Check for updates before installing.')
      }
      await pendingUpdate.downloadAndInstall()
      await relaunch()
    },
    onBackendStatus: (callback) => {
      let cancelled = false
      let unlisten: (() => void) | null = null
      void listen<BackendStatus>('backend-status', (event) => callback(event.payload)).then((handler) => {
        if (cancelled) {
          handler()
          return
        }
        unlisten = handler
      })
      return () => {
        cancelled = true
        unlisten?.()
      }
    },
    onLocalPathDrop: (callback) => {
      let cancelled = false
      let unlisten: (() => void) | null = null
      void getCurrentWindow().onDragDropEvent((event: { payload: DragDropEvent }) => {
        callback(event.payload)
      }).then((handler) => {
        if (cancelled) {
          handler()
          return
        }
        unlisten = handler
      })
      return () => {
        cancelled = true
        unlisten?.()
      }
    },
  }
}

installDesktopBridge()
