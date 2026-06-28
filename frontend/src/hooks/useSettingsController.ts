import { useCallback, useState } from 'react'
import {
  API_BASE_URL,
  loadOllamaModels,
  loadSettingsBundle,
  loadSkillTargets,
  resetSettings,
  syncSkills as syncSkillsRequest,
  updateEmbeddingIndexingSettings,
  updateEmbeddingSettings,
  updateRetrievalSettings,
} from '../api'
import type { SettingsSaveRequest } from '../pages/SettingsPage/SettingsPage'
import type {
  CliPathSettings,
  DesktopUpdateStatus,
  Message,
  OllamaModelsResponse,
  SettingsResponse,
  SkillTargetsResponse,
  StartupSettings,
  ViewName,
} from '../types'

type AppMessage = Exclude<Message, null>

const OPTIONAL_SETTINGS_TIMEOUT_MS = 3500
const UPDATE_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000
const UPDATE_LAST_CHECKED_STORAGE_KEY = 'ingestor.updates.lastCheckedAt'

type UseSettingsControllerOptions = {
  showMessage: (view: ViewName, message: AppMessage) => void
}

export function useSettingsController({ showMessage }: UseSettingsControllerOptions) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [skillTargets, setSkillTargets] = useState<SkillTargetsResponse | null>(null)
  const [startupSettings, setStartupSettings] = useState<StartupSettings | null>(null)
  const [cliPathSettings, setCliPathSettings] = useState<CliPathSettings | null>(null)
  const [updateStatus, setUpdateStatus] = useState<DesktopUpdateStatus | null>(null)
  const [updateMessage, setUpdateMessage] = useState<Message>(null)
  const [ollamaModels, setOllamaModels] = useState<OllamaModelsResponse | null>(null)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [isSyncingSkills, setIsSyncingSkills] = useState(false)
  const [isSavingStartup, setIsSavingStartup] = useState(false)
  const [isAddingCliPath, setIsAddingCliPath] = useState(false)
  const [isRefreshingSettings, setIsRefreshingSettings] = useState(false)
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false)
  const [isInstallingUpdate, setIsInstallingUpdate] = useState(false)

  const refreshOllamaModels = useCallback(async () => {
    try {
      setOllamaModels(await loadOllamaModels({ timeoutMs: OPTIONAL_SETTINGS_TIMEOUT_MS }))
    } catch (error) {
      setOllamaModels({
        base_url: API_BASE_URL,
        models: [],
        selected_model: null,
        reachable: false,
        error: error instanceof Error ? error.message : 'Unable to load Ollama models.',
      })
    }
  }, [])

  const refreshSkillTargets = useCallback(async () => {
    try {
      setSkillTargets(await loadSkillTargets({ timeoutMs: OPTIONAL_SETTINGS_TIMEOUT_MS }))
    } catch {
      setSkillTargets({ source_dir: '', skills: [], targets: [] })
    }
  }, [])

  const refreshSettings = useCallback(async () => {
    const { settings: settingsPayload } = await loadSettingsBundle()
    setSettings(settingsPayload)

    void refreshOllamaModels()
    void refreshSkillTargets()
    return settingsPayload
  }, [refreshOllamaModels, refreshSkillTargets])

  const refreshStartupSettings = useCallback(async () => {
    if (!window.ingestorDesktop) {
      setStartupSettings({ supported: false, openAtLogin: false })
      return
    }
    setStartupSettings(await window.ingestorDesktop.getStartupSettings())
  }, [])

  const refreshCliPathSettings = useCallback(async () => {
    if (!window.ingestorDesktop) {
      setCliPathSettings({ supported: false, path: '', inPath: false })
      return
    }
    setCliPathSettings(await window.ingestorDesktop.getCliPathSettings())
  }, [])

  const refreshSettingsData = useCallback(async () => {
    setIsRefreshingSettings(true)
    try {
      const { settings: settingsPayload } = await loadSettingsBundle()
      setSettings(settingsPayload)
      await Promise.allSettled([
        refreshOllamaModels(),
        refreshSkillTargets(),
        refreshStartupSettings(),
        refreshCliPathSettings(),
      ])
      showMessage('settings', { text: 'Settings refreshed', tone: 'success' })
      return settingsPayload
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to refresh settings',
        tone: 'error',
      })
      return null
    } finally {
      setIsRefreshingSettings(false)
    }
  }, [refreshCliPathSettings, refreshOllamaModels, refreshSkillTargets, refreshStartupSettings, showMessage])

  const saveSettings = useCallback(async (request: SettingsSaveRequest) => {
    setIsSavingSettings(true)
    try {
      let nextSettings: SettingsResponse | null = null

      if (request.resetToDefaults) {
        nextSettings = await resetSettings()
      }

      if (request.model) {
        nextSettings = await updateEmbeddingSettings(request.model)
      }

      if (request.indexing) {
        nextSettings = await updateEmbeddingIndexingSettings({
          strategy: request.indexing.strategy,
          batch_size: request.indexing.batchSize,
        })
      }

      if (request.retrievalMode) {
        nextSettings = await updateRetrievalSettings(request.retrievalMode)
      }

      if (nextSettings) {
        setSettings(nextSettings)
      }
      showMessage('settings', { text: 'Settings saved', tone: 'success' })
      return nextSettings
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to save settings',
        tone: 'error',
      })
      return null
    } finally {
      setIsSavingSettings(false)
    }
  }, [showMessage])

  const syncSkills = useCallback(async (targetIds?: string[]) => {
    setIsSyncingSkills(true)
    try {
      setSkillTargets(await syncSkillsRequest(targetIds))
      showMessage('settings', { text: 'Agent skills updated', tone: 'success' })
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to update agent skills',
        tone: 'error',
      })
    } finally {
      setIsSyncingSkills(false)
    }
  }, [showMessage])

  const setStartupEnabled = useCallback(async (enabled: boolean) => {
    if (!window.ingestorDesktop) return
    setIsSavingStartup(true)
    try {
      setStartupSettings(await window.ingestorDesktop.setStartupEnabled(enabled))
      showMessage('settings', {
        text: enabled ? 'Ingestor will start with Windows' : 'Startup disabled',
        tone: 'success',
      })
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to update startup setting',
        tone: 'error',
      })
    } finally {
      setIsSavingStartup(false)
    }
  }, [showMessage])

  const addCliToPath = useCallback(async () => {
    if (!window.ingestorDesktop) return
    setIsAddingCliPath(true)
    try {
      const nextSettings = await window.ingestorDesktop.addCliToPath()
      setCliPathSettings(nextSettings)
      showMessage('settings', {
        text: nextSettings.inPath ? 'Ingestor CLI folder added to PATH' : 'Unable to confirm PATH update',
        tone: nextSettings.inPath ? 'success' : 'error',
      })
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to add CLI folder to PATH',
        tone: 'error',
      })
    } finally {
      setIsAddingCliPath(false)
    }
  }, [showMessage])

  const copyCliPath = useCallback(async () => {
    const path = cliPathSettings?.path
    if (!path) return

    try {
      await navigator.clipboard.writeText(path)
      showMessage('settings', { text: 'CLI folder path copied', tone: 'success' })
    } catch {
      showMessage('settings', { text: 'Select the CLI folder path and copy it manually', tone: 'error' })
    }
  }, [cliPathSettings?.path, showMessage])

  const checkForUpdates = useCallback(async (options: { silent?: boolean } = {}) => {
    if (!window.ingestorDesktop) return
    if (!options.silent) {
      setUpdateMessage(null)
      setIsCheckingUpdate(true)
    }
    try {
      const nextStatus = await window.ingestorDesktop.checkForUpdate()
      setUpdateStatus(nextStatus)
      storeLastUpdateCheckAt(Date.now())
    } catch (error) {
      if (!options.silent) {
        setUpdateMessage({
          text: error instanceof Error ? error.message : 'Unable to check for updates',
          tone: 'error',
        })
      }
    } finally {
      if (!options.silent) setIsCheckingUpdate(false)
    }
  }, [])

  const checkForUpdatesIfDue = useCallback(async () => {
    if (!window.ingestorDesktop || !isUpdateCheckDue()) return
    await checkForUpdates({ silent: true })
  }, [checkForUpdates])

  const installUpdate = useCallback(async () => {
    if (!window.ingestorDesktop || !updateStatus?.available) return
    setUpdateMessage(null)
    setIsInstallingUpdate(true)
    try {
      await window.ingestorDesktop.installUpdate()
    } catch (error) {
      setUpdateMessage({
        text: error instanceof Error ? error.message : 'Unable to install update',
        tone: 'error',
      })
      setIsInstallingUpdate(false)
    }
  }, [updateStatus?.available])

  return {
    addCliToPath,
    checkForUpdates,
    checkForUpdatesIfDue,
    cliPathSettings,
    copyCliPath,
    installUpdate,
    isAddingCliPath,
    isCheckingUpdate,
    isInstallingUpdate,
    isRefreshingSettings,
    isSavingSettings,
    isSavingStartup,
    isSyncingSkills,
    ollamaModels,
    refreshCliPathSettings,
    refreshSettings,
    refreshSettingsData,
    refreshStartupSettings,
    saveSettings,
    setStartupEnabled,
    settings,
    skillTargets,
    startupSettings,
    syncSkills,
    updateMessage,
    updateStatus,
  }
}

function isUpdateCheckDue() {
  try {
    const lastCheckedAt = Number(window.localStorage.getItem(UPDATE_LAST_CHECKED_STORAGE_KEY))
    return !Number.isFinite(lastCheckedAt) || Date.now() - lastCheckedAt >= UPDATE_CHECK_INTERVAL_MS
  } catch {
    return true
  }
}

function storeLastUpdateCheckAt(timestamp: number) {
  try {
    window.localStorage.setItem(UPDATE_LAST_CHECKED_STORAGE_KEY, String(timestamp))
  } catch {
    // Update checks should still work when localStorage is unavailable.
  }
}
