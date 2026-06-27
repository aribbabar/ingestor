import type { FormEvent } from 'react'

export type SourceKind = 'local' | 'web'
export type SourceStatus = 'registered' | 'indexing' | 'indexed' | 'failed'
export type JobStatus = 'running' | 'succeeded' | 'failed'
export type SourceMode = 'local' | 'web'
export type CrawlScope = 'subpages' | 'hostname' | 'domain'
export type ViewName = 'capture' | 'sources' | 'settings'
export type SearchMode = 'hybrid' | 'keyword' | 'vector'
export type EmbeddingProvider = 'local-hashing' | 'ollama'
export type EmbeddingIndexingStrategy = 'batch' | 'single'
export type Message = { text: string; tone?: 'success' | 'error' } | null
export type FormSubmitHandler = (event: FormEvent<HTMLFormElement>) => void

export type SourceRecord = {
  id: string
  kind: SourceKind
  name: string
  version: string
  location: string
  status: SourceStatus
  document_count: number
  chunk_count: number
  metadata: Record<string, unknown>
  error: string | null
  created_at: string
  updated_at: string
}

export type IndexJob = {
  id: string
  source_id: string
  status: JobStatus
  message: string
  created_at: string
  updated_at: string
}

export type SearchResult = {
  source_id: string
  source_name: string
  title: string
  uri: string
  content: string
  summary: string
  code: string | null
  section_path: string[]
  score: number
  keyword_score: number
  vector_score: number
}

export type SearchResponse = {
  command: string[]
  stdout: string
  stderr: string
  results: SearchResult[]
}

export type HealthResponse = {
  ok: boolean
  database: string
  embedding: string
}

export type SettingsResponse = {
  data_dir: string
  database: string
  local_source_dir: string
  default_search_mode: SearchMode
  embedding: {
    provider: EmbeddingProvider
    model: string
    display_name: string
    ollama_base_url: string
    indexing: {
      strategy: EmbeddingIndexingStrategy
      batch_size: number
      effective_batch_size: number
      default_strategy: EmbeddingIndexingStrategy
      default_batch_size: number
    }
  }
  retrieval: Record<string, string>
  source_compatibility: {
    current_embedding: string
    stale_indexed_source_count: number
  }
}

export type OllamaModelsResponse = {
  base_url: string
  models: string[]
  selected_model: string | null
  reachable: boolean
  error: string | null
}

export type SkillInstallStatus = {
  name: string
  installed: boolean
  current: boolean
  path: string
}

export type SkillTarget = {
  id: string
  label: string
  path: string
  exists: boolean
  current: boolean
  skills: SkillInstallStatus[]
}

export type SkillTargetsResponse = {
  source_dir: string
  skills: { name: string; path: string; hash: string }[]
  targets: SkillTarget[]
}

export type StartupSettings = {
  supported: boolean
  openAtLogin: boolean
}

export type CliPathSettings = {
  supported: boolean
  path: string
  inPath: boolean
}

export type DesktopUpdateStatus =
  | { available: false }
  | { available: true; version: string; currentVersion: string; date?: string; body?: string }

export type LocalForm = {
  paths: string[]
  name: string
}

export type WebForm = {
  url: string
  name: string
  maxDepth: number
  maxPages: number
  scope: CrawlScope
  includePatterns: string
  excludePatterns: string
}
