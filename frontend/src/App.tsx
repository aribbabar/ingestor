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
  HealthResponse,
  IndexJob,
  LocalForm,
  Message,
  OllamaModelsResponse,
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
import styles from './App.module.css'

const API_BASE_URL = window.ingestorDesktop?.backendUrl ?? import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765'
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
    const response = await fetch(`${API_BASE_URL}/api/sources`)
    if (!response.ok) throw new Error('Unable to load sources')
    const payload = (await response.json()) as { sources: SourceRecord[]; jobs: IndexJob[] }
    setSources(payload.sources)
    setJobs(payload.jobs)
    setSelectedSourceId((current) =>
      current && payload.sources.some((source) => source.id === current)
        ? current
        : payload.sources[0]?.id || '',
    )
  }, [])

  const refreshSettings = useCallback(async () => {
    const [healthResponse, settingsResponse, ollamaModelsResponse, skillsResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/health`),
      fetch(`${API_BASE_URL}/api/settings`),
      fetch(`${API_BASE_URL}/api/ollama/models`),
      fetch(`${API_BASE_URL}/api/skills/targets`),
    ])
    if (!healthResponse.ok || !settingsResponse.ok || !ollamaModelsResponse.ok || !skillsResponse.ok) {
      throw new Error('API unavailable')
    }
    setHealth((await healthResponse.json()) as HealthResponse)
    const settingsPayload = (await settingsResponse.json()) as SettingsResponse
    setSettings(settingsPayload)
    if (!hasAppliedDefaultSearchMode.current) {
      setSearchMode(settingsPayload.default_search_mode)
      hasAppliedDefaultSearchMode.current = true
    }
    setOllamaModels((await ollamaModelsResponse.json()) as OllamaModelsResponse)
    setSkillTargets((await skillsResponse.json()) as SkillTargetsResponse)
    setApiStatus('online')
  }, [])

  const refreshStartupSettings = useCallback(async () => {
    if (!window.ingestorDesktop) {
      setStartupSettings({ supported: false, openAtLogin: false })
      return
    }
    setStartupSettings(await window.ingestorDesktop.getStartupSettings())
  }, [])

  const refreshJob = useCallback(async (jobId: string) => {
    const response = await fetch(`${API_BASE_URL}/api/sources/jobs/${jobId}`)
    if (!response.ok) return
    const payload = (await response.json()) as { job: IndexJob; logs: string }
    setJobs((current) => [payload.job, ...current.filter((job) => job.id !== payload.job.id)])
    setActiveLogs(payload.logs)
  }, [])

  useEffect(() => {
    let isActive = true

    async function load() {
      try {
        await refreshSettings()
        await refreshStartupSettings()
        await refreshSources()
      } catch {
        if (isActive) setApiStatus('offline')
      }
    }

    void load()
    return () => {
      isActive = false
    }
  }, [refreshSettings, refreshSources, refreshStartupSettings])

  useEffect(() => {
    if (!latestJob || latestJob.status !== 'running') return
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

    setIsSubmitting(true)
    setMessage(null)
    try {
      const response = await fetch(`${API_BASE_URL}/api/sources/local-folder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paths,
          name,
        }),
      })
      if (!response.ok) throw new Error(await readErrorMessage(response))
      const payload = (await response.json()) as { source: SourceRecord }
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
      const response = await fetch(`${API_BASE_URL}/api/sources/web`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: webForm.url,
          name,
          max_depth: webForm.maxDepth,
          max_pages: webForm.maxPages,
          scope: webForm.scope,
          include_patterns: splitPatternLines(webForm.includePatterns),
          exclude_patterns: splitPatternLines(webForm.excludePatterns),
        }),
      })
      if (!response.ok) throw new Error(await readErrorMessage(response))
      const payload = (await response.json()) as { source: SourceRecord }
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

      const response = await fetch(`${API_BASE_URL}/api/folders/pick`, { method: 'POST' })
      if (!response.ok) throw new Error(await readErrorMessage(response))
      const payload = (await response.json()) as { path: string | null }
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

      const response = await fetch(`${API_BASE_URL}/api/folders/pick-files`, { method: 'POST' })
      if (!response.ok) throw new Error(await readErrorMessage(response))
      const payload = (await response.json()) as { paths: string[] }
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
    const response = await fetch(`${API_BASE_URL}/api/sources/${sourceId}/index`, {
      method: 'POST',
    })
    if (!response.ok) throw new Error(await readErrorMessage(response))
    const payload = (await response.json()) as { job: IndexJob }
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
      const response = await fetch(`${API_BASE_URL}/api/sources/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_id: source.id,
          query,
          limit: searchLimit,
          mode: searchMode,
        }),
      })
      if (!response.ok) throw new Error(await readErrorMessage(response))
      setSearchOutput((await response.json()) as SearchResponse)
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

  async function deleteSource() {
    if (!sourcePendingDelete) return

    const sourceId = sourcePendingDelete.id
    setDeletingSourceId(sourceId)
    setMessage(null)
    try {
      const response = await fetch(`${API_BASE_URL}/api/sources/${sourceId}/delete`, {
        method: 'POST',
      })
      if (!response.ok) throw new Error(await readErrorMessage(response))
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
        const response = await fetch(`${API_BASE_URL}/api/settings/reset`, {
          method: 'POST',
        })
        if (!response.ok) throw new Error(await readErrorMessage(response))
        nextSettings = (await response.json()) as SettingsResponse
      }

      if (request.model) {
        const response = await fetch(`${API_BASE_URL}/api/settings/embedding`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: request.model }),
        })
        if (!response.ok) throw new Error(await readErrorMessage(response))
        nextSettings = (await response.json()) as SettingsResponse
      }

      if (request.indexing) {
        const response = await fetch(`${API_BASE_URL}/api/settings/embedding/indexing`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            strategy: request.indexing.strategy,
            batch_size: request.indexing.batchSize,
          }),
        })
        if (!response.ok) throw new Error(await readErrorMessage(response))
        nextSettings = (await response.json()) as SettingsResponse
      }

      if (request.retrievalMode) {
        const response = await fetch(`${API_BASE_URL}/api/settings/retrieval`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: request.retrievalMode }),
        })
        if (!response.ok) throw new Error(await readErrorMessage(response))
        nextSettings = (await response.json()) as SettingsResponse
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
      const response = await fetch(`${API_BASE_URL}/api/skills/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_ids: targetIds ?? null }),
      })
      if (!response.ok) throw new Error(await readErrorMessage(response))
      setSkillTargets((await response.json()) as SkillTargetsResponse)
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

  return (
    <div className={styles.appShell}>
      <AppHeader activeView={activeView} apiStatus={apiStatus} />

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
              sources={sortedSources}
              totalSourceCount={sources.length}
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
              message={settingsMessage}
              ollamaModels={ollamaModels}
              isSavingSettings={isSavingSettings}
              isSyncingSkills={isSyncingSkills}
              isSavingStartup={isSavingStartup}
              onSaveSettings={saveSettings}
              onSyncSkills={syncSkills}
              onSetStartupEnabled={setStartupEnabled}
            />
          }
        />
        <Route path="*" element={<Navigate replace to="/capture" />} />
      </Routes>

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

async function readErrorMessage(response: Response) {
  const text = await response.text()
  if (!text) return 'Request failed'

  try {
    const payload = JSON.parse(text) as { detail?: unknown }
    if (typeof payload.detail === 'string') return payload.detail
  } catch {
    return text
  }

  return text
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
