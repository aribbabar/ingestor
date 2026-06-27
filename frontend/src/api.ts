import type {
  EmbeddingIndexingStrategy,
  HealthResponse,
  IndexJob,
  OllamaModelsResponse,
  SearchMode,
  SearchResponse,
  SettingsResponse,
  SkillTargetsResponse,
  SourceRecord,
} from './types'

export const API_BASE_URL =
  window.ingestorDesktop?.backendUrl ?? import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765'

type SourcesPayload = { sources: SourceRecord[]; jobs: IndexJob[] }
type JobPayload = { job: IndexJob; logs: string }
type SourcePayload = { source: SourceRecord }
type FolderPayload = { path: string | null }
type FilesPayload = { paths: string[] }

export async function loadSources() {
  return requestJson<SourcesPayload>('/api/sources')
}

export async function loadSettingsBundle() {
  const [health, settings, ollamaModels, skillTargets] = await Promise.all([
    requestJson<HealthResponse>('/api/health'),
    requestJson<SettingsResponse>('/api/settings'),
    requestJson<OllamaModelsResponse>('/api/ollama/models'),
    requestJson<SkillTargetsResponse>('/api/skills/targets'),
  ])
  return { health, settings, ollamaModels, skillTargets }
}

export async function loadJob(jobId: string) {
  return requestJson<JobPayload>(`/api/sources/jobs/${jobId}`)
}

export async function registerLocalSource(paths: string[], name: string) {
  return requestJson<SourcePayload>('/api/sources/local-folder', {
    method: 'POST',
    body: { paths, name },
  })
}

export async function registerWebSource(request: {
  url: string
  name: string
  max_depth: number
  max_pages: number
  scope: string
  include_patterns: string[]
  exclude_patterns: string[]
}) {
  return requestJson<SourcePayload>('/api/sources/web', {
    method: 'POST',
    body: request,
  })
}

export async function pickFolderFromApi() {
  return requestJson<FolderPayload>('/api/folders/pick', { method: 'POST' })
}

export async function pickFilesFromApi() {
  return requestJson<FilesPayload>('/api/folders/pick-files', { method: 'POST' })
}

export async function startIndexJob(sourceId: string) {
  return requestJson<{ job: IndexJob }>(`/api/sources/${sourceId}/index`, { method: 'POST' })
}

export async function searchSource(request: {
  source_id: string
  query: string
  limit: number
  mode: SearchMode
}) {
  return requestJson<SearchResponse>('/api/sources/search', {
    method: 'POST',
    body: request,
  })
}

export async function cancelIndexJob(jobId: string) {
  return requestJson<JobPayload>(`/api/sources/jobs/${jobId}/cancel`, { method: 'POST' })
}

export async function deleteSource(sourceId: string) {
  return requestJson(`/api/sources/${sourceId}/delete`, { method: 'POST' })
}

export async function resetSettings() {
  return requestJson<SettingsResponse>('/api/settings/reset', { method: 'POST' })
}

export async function updateEmbeddingSettings(model: string) {
  return requestJson<SettingsResponse>('/api/settings/embedding', {
    method: 'PUT',
    body: { model },
  })
}

export async function updateEmbeddingIndexingSettings(request: {
  strategy: EmbeddingIndexingStrategy
  batch_size: number
}) {
  return requestJson<SettingsResponse>('/api/settings/embedding/indexing', {
    method: 'PUT',
    body: request,
  })
}

export async function updateRetrievalSettings(mode: SearchMode) {
  return requestJson<SettingsResponse>('/api/settings/retrieval', {
    method: 'PUT',
    body: { mode },
  })
}

export async function syncSkills(targetIds?: string[]) {
  return requestJson<SkillTargetsResponse>('/api/skills/sync', {
    method: 'POST',
    body: { target_ids: targetIds ?? null },
  })
}

async function requestJson<T>(path: string, options: { method?: string; body?: unknown } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? 'GET',
    headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (!response.ok) throw new Error(await readErrorMessage(response))
  return (await response.json()) as T
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
