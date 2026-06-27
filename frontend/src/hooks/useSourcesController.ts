import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  cancelIndexJob,
  deleteSource as deleteSourceRequest,
  loadJob,
  loadSources,
  searchSource,
  startIndexJob,
} from '../api'
import type { IndexJob, Message, SearchMode, SearchResponse, SettingsResponse, SourceRecord, ViewName } from '../types'
import { isActiveJob, isSourceQueryable, sourceQueryDisabledMessage } from '../utils/sourceHelpers'

type AppMessage = Exclude<Message, null>

type UseSourcesControllerOptions = {
  settings: SettingsResponse | null
  showMessage: (view: ViewName, message: AppMessage) => void
}

export function useSourcesController({ settings, showMessage }: UseSourcesControllerOptions) {
  const [sources, setSources] = useState<SourceRecord[]>([])
  const [jobs, setJobs] = useState<IndexJob[]>([])
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [activeLogs, setActiveLogs] = useState('')
  const [query, setQuery] = useState('')
  const [searchLimit, setSearchLimit] = useState(8)
  const [searchMode, setSearchMode] = useState<SearchMode>('hybrid')
  const [searchOutput, setSearchOutput] = useState<SearchResponse | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [deletingSourceId, setDeletingSourceId] = useState<string | null>(null)
  const [sourcePendingDelete, setSourcePendingDelete] = useState<SourceRecord | null>(null)
  const [reindexingSourceId, setReindexingSourceId] = useState<string | null>(null)
  const hasAppliedDefaultSearchMode = useRef(false)

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
  const searchableSources = useMemo(
    () => sortedSources.filter((source) => isSourceQueryable(source, settings)),
    [settings, sortedSources],
  )

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

  const refreshJob = useCallback(async (jobId: string) => {
    try {
      const payload = await loadJob(jobId)
      setJobs((current) => [payload.job, ...current.filter((job) => job.id !== payload.job.id)])
      setActiveLogs(payload.logs)
    } catch {
      return
    }
  }, [])

  useEffect(() => {
    if (!latestJob || !isActiveJob(latestJob)) return
    const timer = window.setInterval(() => {
      void refreshSources()
      void refreshJob(latestJob.id)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [latestJob, refreshJob, refreshSources])

  const applyInitialSearchMode = useCallback((mode: SearchMode) => {
    if (hasAppliedDefaultSearchMode.current) return
    setSearchMode(mode)
    hasAppliedDefaultSearchMode.current = true
  }, [])

  const applySavedSearchMode = useCallback((mode: SearchMode) => {
    setSearchMode(mode)
    hasAppliedDefaultSearchMode.current = true
  }, [])

  const selectSource = useCallback((sourceId: string) => {
    setSelectedSourceId(sourceId)
    const job = jobs.find((currentJob) => currentJob.source_id === sourceId)
    if (job) {
      void refreshJob(job.id)
    } else {
      setActiveLogs('')
    }
  }, [jobs, refreshJob])

  const selectCreatedSource = useCallback((sourceId: string) => {
    setSelectedSourceId(sourceId)
    setActiveLogs('')
  }, [])

  const startIndexJobForSource = useCallback(async (sourceId: string) => {
    const payload = await startIndexJob(sourceId)
    setJobs((current) => [payload.job, ...current.filter((job) => job.id !== payload.job.id)])
    return payload.job
  }, [])

  const searchDocs = useCallback(async (event: FormEvent<HTMLFormElement>) => {
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
  }, [query, searchLimit, searchMode, selectedSource, settings])

  const reindexSource = useCallback(async (source: SourceRecord) => {
    setReindexingSourceId(source.id)
    try {
      const job = await startIndexJobForSource(source.id)
      setSelectedSourceId(source.id)
      if (selectedSource?.id !== source.id) {
        setSearchOutput(null)
      }
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
  }, [refreshJob, refreshSources, selectedSource?.id, showMessage, startIndexJobForSource])

  const cancelJob = useCallback(async (job: IndexJob, view: ViewName = 'sources') => {
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
  }, [refreshSources, showMessage])

  const deletePendingSource = useCallback(async () => {
    if (!sourcePendingDelete) return

    const sourceId = sourcePendingDelete.id
    setDeletingSourceId(sourceId)
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
  }, [refreshSources, showMessage, sourcePendingDelete])

  return {
    activeLogs,
    applyInitialSearchMode,
    applySavedSearchMode,
    cancelJob,
    clearSearchOutput: () => setSearchOutput(null),
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
  }
}
