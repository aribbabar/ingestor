import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router'
import { AppHeader } from './components/layout/AppHeader/AppHeader'
import { ConfirmDialog } from './components/ui/ConfirmDialog/ConfirmDialog'
import { CapturePage } from './pages/CapturePage/CapturePage'
import { SettingsPage } from './pages/SettingsPage/SettingsPage'
import { SourcesPage } from './pages/SourcesPage/SourcesPage'
import type {
  LocalForm,
  Message,
  SourceMode,
  SourceRecord,
  ViewName,
  WebForm,
} from './types'
import {
  API_BASE_URL,
  pickFilesFromApi,
  pickFolderFromApi,
  registerLocalSource as registerLocalSourceRequest,
  registerWebSource as registerWebSourceRequest,
} from './api'
import { useSettingsController } from './hooks/useSettingsController'
import { useSourcesController } from './hooks/useSourcesController'
import { DEFAULT_EXCLUDE_PATTERNS } from './constants/webDefaults'
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

  const settingsController = useSettingsController({ showMessage })
  const {
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
    refreshSettings: refreshSettingsBundle,
    refreshStartupSettings,
    saveSettings,
    setStartupEnabled,
    settings,
    skillTargets,
    startupSettings,
    syncSkills,
    updateStatus,
  } = settingsController

  const sourcesController = useSourcesController({ settings, showMessage })
  const {
    activeLogs,
    applyInitialSearchMode,
    applySavedSearchMode,
    cancelJob,
    clearSearchOutput,
    deletePendingSource,
    deletingSourceId,
    isSearching,
    jobs,
    latestJob,
    query,
    recentSources,
    refreshJob,
    refreshSources,
    reindexingSourceId,
    reindexSource,
    searchDocs,
    searchableSources,
    searchLimit,
    searchMode,
    searchOutput,
    selectCreatedSource,
    selectedSource,
    selectSource,
    setQuery,
    setSearchLimit,
    setSearchMode,
    setSourcePendingDelete,
    sortedSources,
    sourcePendingDelete,
    sources,
    startIndexJobForSource,
  } = sourcesController

  const captureMessage = message?.view === 'capture' ? message : null
  const sourcesMessage = message?.view === 'sources' ? message : null
  const settingsMessage = message?.view === 'settings' ? message : null

  const loadAppData = useCallback(async () => {
    const settingsPayload = await refreshSettingsBundle()
    applyInitialSearchMode(settingsPayload.default_search_mode)
    setApiStatus('online')
    await refreshStartupSettings()
    await refreshCliPathSettings()
    await refreshSources()
  }, [applyInitialSearchMode, refreshCliPathSettings, refreshSettingsBundle, refreshSources, refreshStartupSettings])

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
    return window.ingestorDesktop?.onBackendStatus((status) => {
      if (!status.online) setApiStatus('offline')
    })
  }, [])

  useEffect(() => {
    if (apiStatus !== 'online' || activeView !== 'sources') return
    void refreshSources()
  }, [activeView, apiStatus, refreshSources])

  async function retryApiConnection() {
    setApiStatus('checking')
    setMessage(null)
    try {
      await loadAppData()
    } catch {
      setApiStatus('offline')
    }
  }

  function searchFromCapture(sourceId?: string) {
    if (sourceId) selectSource(sourceId)
    clearSearchOutput()
    navigate('/sources')
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
      selectCreatedSource(payload.source.id)
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
    const url = webForm.url.trim()
    if (!url) {
      showMessage('capture', { text: 'Enter a documentation URL', tone: 'error' })
      return
    }
    if (!isHttpUrl(url)) {
      showMessage('capture', { text: 'Enter a valid http or https documentation URL', tone: 'error' })
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
    if (!isIntegerInRange(webForm.maxPages, 1, 1000)) {
      showMessage('capture', { text: 'Max pages must be a whole number from 1 to 1000', tone: 'error' })
      return
    }
    if (!isIntegerInRange(webForm.maxDepth, 0, 10)) {
      showMessage('capture', { text: 'Max depth must be a whole number from 0 to 10', tone: 'error' })
      return
    }

    setIsSubmitting(true)
    setMessage(null)
    try {
      const payload = await registerWebSourceRequest({
        url,
        name,
        max_depth: webForm.maxDepth,
        max_pages: webForm.maxPages,
        scope: webForm.scope,
        include_patterns: splitPatternLines(webForm.includePatterns),
        exclude_patterns: splitPatternLines(webForm.excludePatterns),
      })
      const job = await startIndexJobForSource(payload.source.id)
      setWebForm((current) => ({ ...current, url: '', name: '' }))
      selectCreatedSource(payload.source.id)
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

  async function handleSaveSettings(...args: Parameters<typeof saveSettings>) {
    const nextSettings = await saveSettings(...args)
    if (nextSettings) {
      applySavedSearchMode(nextSettings.default_search_mode)
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
                searchableSources={searchableSources}
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
                onSearchSource={searchFromCapture}
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
                onSaveSettings={handleSaveSettings}
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
          description={sourceDeleteDescription(sourcePendingDelete)}
          confirmLabel="Delete source"
          isConfirming={deletingSourceId === sourcePendingDelete.id}
          onCancel={() => setSourcePendingDelete(null)}
          onConfirm={() => void deletePendingSource()}
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

function isIntegerInRange(value: number, min: number, max: number) {
  return Number.isInteger(value) && value >= min && value <= max
}

function isHttpUrl(value: string) {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

function sourceDeleteDescription(source: SourceRecord) {
  const docs = `${source.document_count} ${source.document_count === 1 ? 'doc' : 'docs'}`
  const chunks = `${source.chunk_count} ${source.chunk_count === 1 ? 'chunk' : 'chunks'}`
  return `This will remove "${source.name}" and its indexed content from Ingestor, including ${docs} and ${chunks}.`
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

export default App
