/// <reference types="vite/client" />

type BackendStatus = { online: boolean }
type StartupSettings = { supported: boolean; openAtLogin: boolean }
type CliPathSettings = { supported: boolean; path: string; inPath: boolean }
type LocalPathDropEvent =
  | { type: 'enter'; paths: string[]; position: unknown }
  | { type: 'over'; position: unknown }
  | { type: 'drop'; paths: string[]; position: unknown }
  | { type: 'leave' }
type DesktopUpdateStatus =
  | { available: false }
  | { available: true; version: string; currentVersion: string; date?: string; body?: string }

interface Window {
  __TAURI_INTERNALS__?: unknown
  ingestorDesktop?: {
    backendUrl: string
    getBackendUrl: () => Promise<string>
    pickFolder: () => Promise<string | null>
    pickFiles: () => Promise<string[]>
    getStartupSettings: () => Promise<StartupSettings>
    setStartupEnabled: (enabled: boolean) => Promise<StartupSettings>
    getCliPathSettings: () => Promise<CliPathSettings>
    addCliToPath: () => Promise<CliPathSettings>
    checkForUpdate: () => Promise<DesktopUpdateStatus>
    installUpdate: () => Promise<void>
    onBackendStatus: (callback: (status: BackendStatus) => void) => () => void
    onLocalPathDrop: (callback: (event: LocalPathDropEvent) => void) => () => void
  }
}
