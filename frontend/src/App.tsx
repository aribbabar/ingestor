import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'
import { AppHeader } from './components/layout/AppHeader/AppHeader'
import { ConfirmDialog } from './components/ui/ConfirmDialog/ConfirmDialog'
import { CapturePage } from './pages/CapturePage/CapturePage'
import { SettingsPage } from './pages/SettingsPage/SettingsPage'
import type { SettingsSaveRequest } from './pages/SettingsPage/SettingsPage'
import { SourcesPage } from './pages/SourcesPage/SourcesPage'
import type {
  CliPathSettings,
  HealthResponse,
  IndexJob,
  LocalForm,
  Message,
  OllamaModelsResponse,
  DesktopUpdateStatus,
  SearchMode,
  SearchResponse,
  SettingsResponse,
  SkillTargetsResponse,
  SourceMode,
  SourceRecord,
  StartupSettings,
  ViewName,
  WebForm,
} from './types'
import {
  API_BASE_URL,
  cancelIndexJob,
  deleteSource as deleteSourceRequest,
  loadJob,
  loadSettingsBundle,
  loadSources,
  pickFilesFromApi,
  pickFolderFromApi,
  registerLocalSource as registerLocalSourceRequest,
  registerWebSource as registerWebSourceRequest,
  resetSettings,
  searchSource,
  startIndexJob,
  syncSkills as syncSkillsRequest,
  updateEmbeddingIndexingSettings,
  updateEmbeddingSettings,
  updateRetrievalSettings,
} from './api'
import styles from './App.module.css'

type AppMessage = Exclude<Message, null> & { view: ViewName }

const PAGE_TITLES: Record<ViewName, string> = {
  capture: 'Capture | Ingestor',
  sources: 'Sources | Ingestor',
  settings: 'Settings | Ingestor',
}

const initialLocalForm: LocalForm = {
  paths: [],
  name: '',
}

const DEFAULT_EXCLUDE_PATTERNS = `**/CHANGELOG.md
**/changelog.md
**/CHANGELOG.mdx
**/changelog.mdx
**/LICENSE
**/LICENSE.md
**/license.md
**/CODE_OF_CONDUCT.md
**/code_of_conduct.md
**/*.test.*
**/*.spec.*
**/*_test.py
**/*_test.go
**/*.lock
**/package-lock.json
**/yarn.lock
**/pnpm-lock.yaml
**/go.sum
**/*.min.js
**/*.min.css
**/*.map
**/*.d.ts
**/.DS_Store
**/Thumbs.db
**/*.swp
**/*.swo
/.*\\.(ini|cfg|conf|log|pid)$/
**/archive/**
**/archived/**
**/deprecated/**
**/legacy/**
**/old/**
**/outdated/**
**/previous/**
**/superseded/**
docs/old/**
**/test/**
**/tests/**
**/__tests__/**
**/spec/**
**/dist/**
**/build/**
**/out/**
**/target/**
**/.next/**
**/.nuxt/**
**/.vscode/**
**/.idea/**
**/i18n/ar*/**
**/i18n/de*/**
**/i18n/es*/**
**/i18n/fr*/**
**/i18n/hi*/**
**/i18n/it*/**
**/i18n/ja*/**
**/i18n/ko*/**
**/i18n/nl*/**
**/i18n/pl*/**
**/i18n/pt*/**
**/i18n/ru*/**
**/i18n/sv*/**
**/i18n/th*/**
**/i18n/tr*/**
**/i18n/vi*/**
**/i18n/zh*/**
**/zh-cn/**
**/zh-hk/**
**/zh-mo/**
**/zh-sg/**
**/zh-tw/**`

const defaultWebOptions: Pick<WebForm, 'maxDepth' | 'maxPages' | 'scope' | 'includePatterns' | 'excludePatterns'> = {
  maxDepth: 3,
  maxPages: 1000,
  scope: 'hostname',
  includePatterns: '/docs/',
  excludePatterns: DEFAULT_EXCLUDE_PATTERNS,
}

const initialWebForm: WebForm = {
  url: '',
  name: '',
  ...defaultWebOptions,
}

const WEB_OPTIONS_STORAGE_KEY = 'ingestor.capture.webOptions.v2'
const LEGACY_WEB_OPTIONS_STORAGE_KEYS = ['ingestor.capture.webOptions.v1']

function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [apiStatus, setApiStatus] = useState<'checking' | 'online' | 'offline'>('checking')
  const [, setHealth] = useState<HealthResponse | null>(null)
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [skillTargets, setSkillTargets] = useState<SkillTargetsResponse | null>(null)
  const [startupSettings, setStartupSettings] = useState<StartupSettings | null>(null)
  const [cliPathSettings, setCliPathSettings] = useState<CliPathSettings | null>(null)
  const [updateStatus, setUpdateStatus] = useState<DesktopUpdateStatus | null>(null)
  const [ollamaModels, setOllamaModels] = useState<OllamaModelsResponse | null>(null)
  const [sources, setSources] = useState<SourceRecord[]>([])
  const [jobs, setJobs] = useState<IndexJob[]>([])
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [activeLogs, setActiveLogs] = useState('')
  const [mode, setMode] = useState<SourceMode>('local')
  const [localForm, setLocalForm] = useState<LocalForm>(initialLocalForm)
  const [webForm, setWebForm] = useState<WebForm>(() => ({
    ...initialWebForm,
    ...loadStoredWebOptions(),
  }))
  const [isPickingFolder, setIsPickingFolder] = useState(false)
  const [isPickingFiles, setIsPickingFiles] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [message, setMessage] = useState<AppMessage | null>(null)
  const [query, setQuery] = useState('')
  const [searchLimit, setSearchLimit] = useState(8)
  const [searchMode, setSearchMode] = useState<SearchMode>('hybrid')
  const [searchOutput, setSearchOutput] = useState<SearchResponse | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [deletingSourceId, setDeletingSourceId] = useState<string | null>(null)
  const [sourcePendingDelete, setSourcePendingDelete] = useState<SourceRecord | null>(null)
  const [reindexingSourceId, setReindexingSourceId] = useState<string | null>(null)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [isSyncingSkills, setIsSyncingSkills] = useState(false)
  const [isSavingStartup, setIsSavingStartup] = useState(false)
  const [isAddingCliPath, setIsAddingCliPath] = useState(false)
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false)
  const [isInstallingUpdate, setIsInstallingUpdate] = useState(false)
  const hasAppliedDefaultSearchMode = useRef(false)

  const activeView = useMemo((): ViewName => {
    if (location.pathname.startsWith('/sources')) return 'sources'
    if (location.pathname.startsWith('/settings')) return 'settings'
    return 'capture'
  }, [location.pathname])

  useEffect(() => {
    document.title = PAGE_TITLES[activeView]
  }, [activeView])

  useEffect(() => {
    if (!message) return
    const timeout = message.tone === 'error' ? 8000 : 5000
    const timer = window.setTimeout(() => {
      setMessage((current) => (current === message ? null : current))
    }, timeout)
    return () => window.clearTimeout(timer)
  }, [message])

  useEffect(() => {
    storeWebOptions(webForm)
  }, [webForm])

  const showMessage = useCallback((view: ViewName, nextMessage: Exclude<Message, null>) => {
    setMessage({ ...nextMessage, view })
  }, [])

  const captureMessage = message?.view === 'capture' ? message : null
  const sourcesMessage = message?.view === 'sources' ? message : null
  const settingsMessage = message?.view === 'settings' ? message : null

  const sortedSources = useMemo(
    () =>
      [...sources].sort(
        (left, right) =>
          new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
      ),
    [sources],
  )

  const selectedSource = useMemo(
    () =>
      sources.find((source) => source.id === selectedSourceId) ??
      sortedSources[0],
    [selectedSourceId, sortedSources, sources],
  )

  const latestJob = useMemo(() => {
    if (!selectedSource) return undefined
    return jobs.find((job) => job.source_id === selectedSource.id)
  }, [jobs, selectedSource])

  const recentSources = sortedSources.slice(0, 5)

  const refreshSources = useCallback(async () => {
    const payload = await loadSources()
    setSources(payload.sources)
    setJobs(payload.jobs)
    setSelectedSourceId((current) =>
      current && payload.sources.some((source) => source.id === current)
        ? current
        : payload.sources[0]?.id || '',
    )
  }, [])

  const refreshSettings = useCallback(async () => {
    const { health: healthPayload, settings: settingsPayload, ollamaModels: modelsPayload, skillTargets: skillsPayload } =
      await loadSettingsBundle()
    setHealth(healthPayload)
    setSettings(settingsPayload)
    if (!hasAppliedDefaultSearchMode.current) {
      setSearchMode(settingsPayload.default_search_mode)
      hasAppliedDefaultSearchMode.current = true
    }
    setOllamaModels(modelsPayload)
    setSkillTargets(skillsPayload)
    setApiStatus('online')
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

  const refreshJob = useCallback(async (jobId: string) => {
    try {
      const payload = await loadJob(jobId)
      setJobs((current) => [payload.job, ...current.filter((job) => job.id !== payload.job.id)])
      setActiveLogs(payload.logs)
    } catch {
      return
    }
  }, [])

  const loadAppData = useCallback(async () => {
    await refreshSettings()
    await refreshStartupSettings()
    await refreshCliPathSettings()
    await refreshSources()
  }, [refreshCliPathSettings, refreshSettings, refreshSources, refreshStartupSettings])

  useEffect(() => {
    let isActive = true

    async function load() {
      try {
        await loadAppData()
      } catch {
        if (isActive) setApiStatus('offline')
      }
    }

    void load()
    return () => {
      isActive = false
    }
  }, [loadAppData])

  useEffect(() => {
    if (!latestJob || !isActiveJob(latestJob)) return
    const timer = window.setInterval(() => {
      void refreshSources()
      void refreshJob(latestJob.id)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [latestJob, refreshJob, refreshSources])

  useEffect(() => {
    return window.ingestorDesktop?.onBackendStatus((status) => {
      if (!status.online) setApiStatus('offline')
    })
  }, [])

  async function retryApiConnection() {
    setApiStatus('checking')
    setMessage(null)
    try {
      await loadAppData()
    } catch {
      setApiStatus('offline')
    }
  }

  function selectSource(sourceId: string) {
    setSelectedSourceId(sourceId)
    const job = jobs.find((currentJob) => currentJob.source_id === sourceId)
    if (job) {
      void refreshJob(job.id)
    } else {
      setActiveLogs('')
    }
  }

  async function registerLocalSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const paths = normalizePathList(localForm.paths)
    const name = localForm.name.trim()
    if (!paths.length) {
      showMessage('capture', { text: 'Select at least one local folder or file', tone: 'error' })
      return
    }
    if (!name) {
      showMessage('capture', { text: 'Enter a unique source name', tone: 'error' })
      return
    }
    if (isSourceNameTaken(sources, name)) {
      showMessage('capture', { text: `A source named "${name}" already exists`, tone: 'error' })
      return
    }
    const duplicate = findDuplicateLocalPath(sources, paths)
    if (duplicate) {
      showMessage('capture', {
        text: `${duplicate.path} is already registered as "${duplicate.source.name}". Reindex or delete that source instead.`,
        tone: 'error',
      })
      return
    }

    setIsSubmitting(true)
    setMessage(null)
    try {
      const payload = await registerLocalSourceRequest(paths, name)
      const job = await startIndexJobForSource(payload.source.id)
      setLocalForm(initialLocalForm)
      setSelectedSourceId(payload.source.id)
      setActiveLogs('')
      showMessage('capture', { text: `${payload.source.name} is indexing`, tone: 'success' })
      await refreshSources()
      await refreshJob(job.id)
    } catch (error) {
      showMessage('capture', {
        text: error instanceof Error ? error.message : 'Local source registration failed',
        tone: 'error',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  async function registerWebSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = webForm.name.trim()
    if (!name) {
      showMessage('capture', { text: 'Enter a unique source name', tone: 'error' })
      return
    }
    if (isSourceNameTaken(sources, name)) {
      showMessage('capture', { text: `A source named "${name}" already exists`, tone: 'error' })
      return
    }

    setIsSubmitting(true)
    setMessage(null)
    try {
      const payload = await registerWebSourceRequest({
        url: webForm.url,
        name,
        max_depth: webForm.maxDepth,
        max_pages: webForm.maxPages,
        scope: webForm.scope,
        include_patterns: splitPatternLines(webForm.includePatterns),
        exclude_patterns: splitPatternLines(webForm.excludePatterns),
      })
      const job = await startIndexJobForSource(payload.source.id)
      setWebForm((current) => ({ ...current, url: '', name: '' }))
      setSelectedSourceId(payload.source.id)
      setActiveLogs('')
      showMessage('capture', { text: `${payload.source.name} is indexing`, tone: 'success' })
      await refreshSources()
      await refreshJob(job.id)
    } catch (error) {
      showMessage('capture', {
        text: error instanceof Error ? error.message : 'Web source registration failed',
        tone: 'error',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  async function pickFolder() {
    setIsPickingFolder(true)
    setMessage(null)
    try {
      if (window.ingestorDesktop) {
        const path = await window.ingestorDesktop.pickFolder()
        if (path) {
          setLocalForm((current) => ({
            ...current,
            paths: normalizePathList([...current.paths, path]),
          }))
        }
        return
      }

      const payload = await pickFolderFromApi()
      if (payload.path) {
        setLocalForm((current) => ({
          ...current,
          paths: normalizePathList([...current.paths, payload.path as string]),
        }))
      }
    } catch (error) {
      showMessage('capture', {
        text: error instanceof Error ? error.message : 'Could not open native folder picker',
        tone: 'error',
      })
    } finally {
      setIsPickingFolder(false)
    }
  }

  async function pickFiles() {
    setIsPickingFiles(true)
    setMessage(null)
    try {
      if (window.ingestorDesktop) {
        const paths = await window.ingestorDesktop.pickFiles()
        setLocalForm((current) => ({
          ...current,
          paths: normalizePathList([...current.paths, ...paths]),
        }))
        return
      }

      const payload = await pickFilesFromApi()
      setLocalForm((current) => ({
        ...current,
        paths: normalizePathList([...current.paths, ...payload.paths]),
      }))
    } catch (error) {
      showMessage('capture', {
        text: error instanceof Error ? error.message : 'Could not open native file picker',
        tone: 'error',
      })
    } finally {
      setIsPickingFiles(false)
    }
  }

  function removeLocalPath(path: string) {
    setLocalForm((current) => ({
      ...current,
      paths: current.paths.filter((currentPath) => currentPath !== path),
    }))
  }

  function resetWebOptions() {
    setWebForm((current) => ({
      ...current,
      ...defaultWebOptions,
    }))
  }

  async function startIndexJobForSource(sourceId: string) {
    const payload = await startIndexJob(sourceId)
    setJobs((current) => [payload.job, ...current.filter((job) => job.id !== payload.job.id)])
    return payload.job
  }

  async function searchDocs(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const source = selectedSource
    if (!source) return
    if (!isSourceQueryable(source, settings)) {
      setSearchOutput({
        command: [],
        stdout: '',
        stderr: sourceQueryDisabledMessage(source, settings),
        results: [],
      })
      return
    }
    setIsSearching(true)
    setSearchOutput(null)

    try {
      setSearchOutput(await searchSource({
        source_id: source.id,
        query,
        limit: searchLimit,
        mode: searchMode,
      }))
    } catch (error) {
      setSearchOutput({
        command: [],
        stdout: '',
        stderr: error instanceof Error ? error.message : 'Search failed',
        results: [],
      })
    } finally {
      setIsSearching(false)
    }
  }

  async function reindexSource(source: SourceRecord) {
    setReindexingSourceId(source.id)
    setMessage(null)
    try {
      const job = await startIndexJobForSource(source.id)
      setSelectedSourceId(source.id)
      setSearchOutput(null)
      setActiveLogs('')
      showMessage('sources', { text: `${source.name} is re-indexing`, tone: 'success' })
      await refreshSources()
      await refreshJob(job.id)
    } catch (error) {
      showMessage('sources', {
        text: error instanceof Error ? error.message : 'Unable to start re-index',
        tone: 'error',
      })
    } finally {
      setReindexingSourceId(null)
    }
  }

  async function cancelJob(job: IndexJob, view: ViewName = 'sources') {
    setMessage(null)
    try {
      const payload = await cancelIndexJob(job.id)
      setJobs((current) => [payload.job, ...current.filter((currentJob) => currentJob.id !== payload.job.id)])
      setActiveLogs(payload.logs)
      await refreshSources()
      showMessage(view, { text: 'Index cancellation requested', tone: 'success' })
    } catch (error) {
      showMessage(view, {
        text: error instanceof Error ? error.message : 'Unable to cancel indexing',
        tone: 'error',
      })
    }
  }

  async function deleteSource() {
    if (!sourcePendingDelete) return

    const sourceId = sourcePendingDelete.id
    setDeletingSourceId(sourceId)
    setMessage(null)
    try {
      await deleteSourceRequest(sourceId)
      setSearchOutput(null)
      setActiveLogs('')
      await refreshSources()
      setSourcePendingDelete(null)
      showMessage('sources', { text: 'Source deleted', tone: 'success' })
    } catch (error) {
      showMessage('sources', {
        text: error instanceof Error ? error.message : 'Unable to delete source',
        tone: 'error',
      })
    } finally {
      setDeletingSourceId(null)
    }
  }

  async function saveSettings(request: SettingsSaveRequest) {
    setIsSavingSettings(true)
    setMessage(null)
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
        setSearchMode(nextSettings.default_search_mode)
      }
      hasAppliedDefaultSearchMode.current = true
      showMessage('settings', { text: 'Settings saved', tone: 'success' })
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to save settings',
        tone: 'error',
      })
    } finally {
      setIsSavingSettings(false)
    }
  }

  async function syncSkills(targetIds?: string[]) {
    setIsSyncingSkills(true)
    setMessage(null)
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
  }

  async function setStartupEnabled(enabled: boolean) {
    if (!window.ingestorDesktop) return
    setIsSavingStartup(true)
    setMessage(null)
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
  }

  async function addCliToPath() {
    if (!window.ingestorDesktop) return
    setIsAddingCliPath(true)
    setMessage(null)
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
  }

  async function copyCliPath() {
    const path = cliPathSettings?.path
    if (!path) return

    try {
      await navigator.clipboard.writeText(path)
      showMessage('settings', { text: 'CLI folder path copied', tone: 'success' })
    } catch {
      showMessage('settings', { text: 'Select the CLI folder path and copy it manually', tone: 'error' })
    }
  }

  async function checkForUpdates() {
    if (!window.ingestorDesktop) return
    setIsCheckingUpdate(true)
    setMessage(null)
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
  }

  async function installUpdate() {
    if (!window.ingestorDesktop || !updateStatus?.available) return
    setIsInstallingUpdate(true)
    setMessage(null)
    try {
      await window.ingestorDesktop.installUpdate()
    } catch (error) {
      showMessage('settings', {
        text: error instanceof Error ? error.message : 'Unable to install update',
        tone: 'error',
      })
      setIsInstallingUpdate(false)
    }
  }

  return (
    <div className={styles.appShell}>
      <AppHeader activeView={activeView} apiStatus={apiStatus} />

      {apiStatus === 'offline' ? (
        <OfflineBackendState isDesktopAvailable={Boolean(window.ingestorDesktop)} onRetry={retryApiConnection} />
      ) : (
        <Routes>
          <Route index element={<Navigate replace to="/capture" />} />
          <Route
            path="/capture"
            element={
              <CapturePage
                activeLogs={activeLogs}
                latestJob={latestJob}
                selectedSource={selectedSource}
                mode={mode}
                message={captureMessage}
                recentSources={recentSources}
                localForm={localForm}
                webForm={webForm}
                isPickingFiles={isPickingFiles}
                isPickingFolder={isPickingFolder}
                isSubmitting={isSubmitting}
                onModeChange={setMode}
                onLocalFormChange={setLocalForm}
                onWebFormChange={setWebForm}
                onPickFiles={pickFiles}
                onPickFolder={pickFolder}
                onRemoveLocalPath={removeLocalPath}
                onRegisterLocal={registerLocalSource}
                onRegisterWeb={registerWebSource}
                onResetWebOptions={resetWebOptions}
                onNavigate={(view) => navigate(`/${view}`)}
                onSelectSource={selectSource}
                onCancelJob={(job) => cancelJob(job, 'capture')}
              />
            }
          />
          <Route
            path="/sources"
            element={
              <SourcesPage
                deletingSourceId={deletingSourceId}
                isSearching={isSearching}
                message={sourcesMessage}
                query={query}
                searchLimit={searchLimit}
                searchMode={searchMode}
                searchOutput={searchOutput}
                selectedSource={selectedSource}
                settings={settings}
                reindexingSourceId={reindexingSourceId}
                jobs={jobs}
                sources={sortedSources}
                totalSourceCount={sources.length}
                onCancelJob={(job) => cancelJob(job, 'sources')}
                onQueryChange={setQuery}
                onRefreshSources={refreshSources}
                onReindexSource={reindexSource}
                onRequestDeleteSource={setSourcePendingDelete}
                onSearchDocs={searchDocs}
                onSearchLimitChange={setSearchLimit}
                onSearchModeChange={setSearchMode}
                onSelectSource={selectSource}
              />
            }
          />
          <Route
            path="/settings"
            element={
              <SettingsPage
                settings={settings}
                skillTargets={skillTargets}
                startupSettings={startupSettings}
                cliPathSettings={cliPathSettings}
                updateStatus={updateStatus}
                message={settingsMessage}
                ollamaModels={ollamaModels}
                isDesktopAvailable={Boolean(window.ingestorDesktop)}
                isSavingSettings={isSavingSettings}
                isSyncingSkills={isSyncingSkills}
                isSavingStartup={isSavingStartup}
                isAddingCliPath={isAddingCliPath}
                isCheckingUpdate={isCheckingUpdate}
                isInstallingUpdate={isInstallingUpdate}
                onSaveSettings={saveSettings}
                onSyncSkills={syncSkills}
                onSetStartupEnabled={setStartupEnabled}
                onAddCliToPath={addCliToPath}
                onCopyCliPath={copyCliPath}
                onCheckForUpdates={checkForUpdates}
                onInstallUpdate={installUpdate}
              />
            }
          />
          <Route path="*" element={<Navigate replace to="/capture" />} />
        </Routes>
      )}

      {sourcePendingDelete ? (
        <ConfirmDialog
          title="Delete source?"
          description={`This will remove "${sourcePendingDelete.name}" and its indexed chunks from Ingestor.`}
          confirmLabel="Delete source"
          isConfirming={deletingSourceId === sourcePendingDelete.id}
          onCancel={() => setSourcePendingDelete(null)}
          onConfirm={() => void deleteSource()}
        />
      ) : null}
    </div>
  )
}

function normalizePathList(paths: string[]) {
  return Array.from(new Set(paths.map((path) => path.trim()).filter(Boolean)))
}

function splitPatternLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
}

function isSourceNameTaken(sources: SourceRecord[], name: string) {
  const normalizedName = name.trim().toLocaleLowerCase()
  return sources.some((source) => source.name.trim().toLocaleLowerCase() === normalizedName)
}

function findDuplicateLocalPath(sources: SourceRecord[], paths: string[]) {
  const selectedPathKeys = new Set(paths.map(pathKey))
  for (const source of sources) {
    if (source.kind !== 'local') continue
    for (const sourcePath of sourceOriginalPaths(source)) {
      if (selectedPathKeys.has(pathKey(sourcePath))) {
        return { source, path: sourcePath }
      }
    }
  }
  return null
}

function sourceOriginalPaths(source: SourceRecord) {
  const metadataPaths = source.metadata.original_paths
  if (Array.isArray(metadataPaths)) {
    return metadataPaths.map(String).filter(Boolean)
  }
  return source.location.split(';').map((path) => path.trim()).filter(Boolean)
}

function pathKey(path: string) {
  return path.trim().replace(/[/\\]+$/, '').replaceAll('\\', '/').toLocaleLowerCase()
}

function loadStoredWebOptions(): Partial<WebForm> {
  const storedOptions = loadStoredWebOptionsFromKey(WEB_OPTIONS_STORAGE_KEY, false)
  if (storedOptions) return storedOptions

  for (const key of LEGACY_WEB_OPTIONS_STORAGE_KEYS) {
    const legacyOptions = loadStoredWebOptionsFromKey(key, true)
    if (legacyOptions) return legacyOptions
  }

  return {}
}

function loadStoredWebOptionsFromKey(key: string, isLegacy: boolean): Partial<WebForm> | null {
  try {
    const stored = window.localStorage.getItem(key)
    if (!stored) return null
    const parsed = JSON.parse(stored) as Partial<WebForm>
    const includePatterns = typeof parsed.includePatterns === 'string' ? parsed.includePatterns : defaultWebOptions.includePatterns
    return {
      maxDepth: sanitizeNumber(parsed.maxDepth, defaultWebOptions.maxDepth, 0, 10),
      maxPages: sanitizeNumber(parsed.maxPages, defaultWebOptions.maxPages, 1, 1000),
      scope: isCrawlScope(parsed.scope) ? parsed.scope : defaultWebOptions.scope,
      includePatterns: isLegacy && !includePatterns.trim() ? defaultWebOptions.includePatterns : includePatterns,
      excludePatterns: typeof parsed.excludePatterns === 'string' ? parsed.excludePatterns : defaultWebOptions.excludePatterns,
    }
  } catch {
    return null
  }
}

function storeWebOptions(form: WebForm) {
  try {
    window.localStorage.setItem(
      WEB_OPTIONS_STORAGE_KEY,
      JSON.stringify({
        maxDepth: form.maxDepth,
        maxPages: form.maxPages,
        scope: form.scope,
        includePatterns: form.includePatterns,
        excludePatterns: form.excludePatterns,
      }),
    )
  } catch {
    return
  }
}

function sanitizeNumber(value: unknown, fallback: number, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback
}

function isCrawlScope(value: unknown): value is WebForm['scope'] {
  return value === 'hostname' || value === 'subpages' || value === 'domain'
}

function isSourceQueryable(source: SourceRecord | undefined, settings: SettingsResponse | null) {
  if (!source || source.status !== 'indexed') return false
  const embedding = source.metadata.embedding
  if (!settings || !isRecord(embedding)) return false
  return embedding.provider === settings.embedding.provider && embedding.model === settings.embedding.model
}

function isActiveJob(job: IndexJob) {
  return job.status === 'running' || job.status === 'cancelling'
}

function OfflineBackendState({
  isDesktopAvailable,
  onRetry,
}: {
  isDesktopAvailable: boolean
  onRetry: () => void
}) {
  return (
    <main className={styles.offlinePanel} aria-labelledby="offline-title">
      <div>
        <h1 id="offline-title">Backend unavailable</h1>
        <p>
          Ingestor could not reach the local API at <code>{API_BASE_URL}</code>.
        </p>
      </div>
      <p>
        {isDesktopAvailable
          ? 'The desktop shell normally starts the local backend automatically. Retry the connection; if it stays offline, restart Ingestor.'
          : 'Start the backend with npm run backend:serve, or run npm run dev from the repository root for the full desktop development flow.'}
      </p>
      <button className={styles.retryButton} type="button" onClick={() => void onRetry()}>
        Retry connection
      </button>
    </main>
  )
}

function sourceQueryDisabledMessage(source: SourceRecord, settings: SettingsResponse | null) {
  const current = settings?.embedding.display_name ?? 'the current embedding model'
  const embedding = source.metadata.embedding
  if (!isRecord(embedding)) {
    return `${source.name} must be re-indexed before searching because it has no embedding model metadata.`
  }
  const indexedWith = typeof embedding.display_name === 'string' ? embedding.display_name : 'a different embedding model'
  return `${source.name} must be re-indexed before searching. It was indexed with ${indexedWith}, but the current embedding model is ${current}.`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export default App
