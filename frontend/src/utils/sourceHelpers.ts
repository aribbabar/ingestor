import type { IndexJob, SettingsResponse, SourceRecord } from '../types'

export function isSourceQueryable(source: SourceRecord | undefined, settings: SettingsResponse | null) {
  if (!source || source.status !== 'indexed') return false
  const embedding = source.metadata.embedding
  if (!settings || !isRecord(embedding)) return false
  return embedding.provider === settings.embedding.provider && embedding.model === settings.embedding.model
}

export function sourceQueryDisabledMessage(source: SourceRecord, settings: SettingsResponse | null) {
  if (source.status !== 'indexed') {
    return `${source.name} is ${source.status}. It must finish indexing before it can be searched.`
  }

  const current = settings?.embedding.display_name ?? 'the current embedding model'
  const indexedWith = sourceEmbeddingDisplayName(source) ?? 'a different embedding model'
  if (!sourceEmbeddingDisplayName(source)) {
    return `${source.name} must be re-indexed before searching because it has no embedding model metadata.`
  }
  return `${source.name} must be re-indexed before searching. It was indexed with ${indexedWith}, but the current embedding model is ${current}.`
}

export function sourceEmbeddingDisplayName(source: SourceRecord) {
  const embedding = isRecord(source.metadata.embedding) ? source.metadata.embedding : null
  return stringValue(embedding?.display_name) ?? stringValue(embedding?.model)
}

export function isActiveJob(job: IndexJob) {
  return job.status === 'running' || job.status === 'cancelling'
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function stringValue(value: unknown) {
  return typeof value === 'string' && value ? value : undefined
}
