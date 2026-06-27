import { useCallback, useState } from 'react'
import {
  loadSettingsBundle,
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

type UseSettingsControllerOptions = {
  showMessage: (view: ViewName, message: AppMessage) => void
}

export function useSettingsController({ showMessage }: UseSettingsControllerOptions) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [skillTargets, setSkillTargets] = useState<SkillTargetsResponse | null>(null)
  const [startupSettings, setStartupSettings] = useState<StartupSettings | null>(null)
  const [cliPathSettings, setCliPathSettings] = useState<CliPathSettings | null>(null)
  const [updateStatus, setUpdateStatus] = useState<DesktopUpdateStatus | null>(null)
  const [ollamaModels, setOllamaModels] = useState<OllamaModelsResponse | null>(null)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [isSyncingSkills, setIsSyncingSkills] = useState(false)
  const [isSavingStartup, setIsSavingStartup] = useState(false)
  const [isAddingCliPath, setIsAddingCliPath] = useState(false)
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false)
  const [isInstallingUpdate, setIsInstallingUpdate] = useState(false)

  const refreshSettings = useCallback(async () => {
    const { settings: settingsPayload, ollamaModels: modelsPayload, skillTargets: skillsPayload } =
      await loadSettingsBundle()
    setSettings(settingsPayload)
    setOllamaModels(modelsPayload)
    setSkillTargets(skillsPayload)
    return settingsPayload
  }, [])

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

  const checkForUpdates = useCallback(async () => {
    if (!window.ingestorDesktop) return
    setIsCheckingUpdate(true)
    try {
      const nextStatus = await window.ingestorDesktop.checkForUpdate()
      setUpdateStatus(nextStatus)
      showMessage('settings', {
        text: nextStatus.available ? `Ingestor ${nextStatus.version} is available` : 'Ingestor is up to date',
        tone: 'success',
      })
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to check for updates',
        tone: 'error',
      })
    } finally {
      setIsCheckingUpdate(false)
    }
  }, [showMessage])

  const installUpdate = useCallback(async () => {
    if (!window.ingestorDesktop || !updateStatus?.available) return
    setIsInstallingUpdate(true)
    try {
      await window.ingestorDesktop.installUpdate()
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to install update',
        tone: 'error',
      })
      setIsInstallingUpdate(false)
    }
  }, [showMessage, updateStatus?.available])

  return {
    addCliToPath,
    checkForUpdates,
    cliPathSettings,
    copyCliPath,
    installUpdate,
    isAddingCliPath,
    isCheckingUpdate,
    isInstallingUpdate,
    isSavingSettings,
    isSavingStartup,
    isSyncingSkills,
    ollamaModels,
    refreshCliPathSettings,
    refreshSettings,
    refreshStartupSettings,
    saveSettings,
    setStartupEnabled,
    settings,
    skillTargets,
    startupSettings,
    syncSkills,
    updateStatus,
  }
}
