/// <reference types="vite/client" />

type BackendStatus = { online: boolean }
type StartupSettings = { supported: boolean; openAtLogin: boolean }

interface Window {
  __TAURI_INTERNALS__?: unknown
  ingestorDesktop?: {
    backendUrl: string
    getBackendUrl: () => Promise<string>
    pickFolder: () => Promise<string | null>
    pickFiles: () => Promise<string[]>
    getStartupSettings: () => Promise<StartupSettings>
    setStartupEnabled: (enabled: boolean) => Promise<StartupSettings>
    onBackendStatus: (callback: (status: BackendStatus) => void) => () => void
  }
}

type BackendStatus = { online: boolean }
type StartupSettings = { supported: boolean; openAtLogin: boolean }

interface Window {
  ingestorDesktop?: {
    backendUrl: string
    getBackendUrl: () => Promise<string>
    pickFolder: () => Promise<string | null>
    pickFiles: () => Promise<string[]>
    getStartupSettings: () => Promise<StartupSettings>
    setStartupEnabled: (enabled: boolean) => Promise<StartupSettings>
    onBackendStatus: (callback: (status: BackendStatus) => void) => () => void
  }
}
