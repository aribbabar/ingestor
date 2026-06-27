import type { FormSubmitHandler, Message, SearchMode, SearchResponse, SettingsResponse, SourceRecord } from '../../types'
import { Badge } from '../../components/ui/Badge/Badge'
import { MessageLine } from '../../components/ui/MessageLine/MessageLine'
import { PageHeading } from '../../components/ui/PageHeading/PageHeading'
import { SelectControl } from '../../components/ui/SelectControl/SelectControl'
import { classNames } from '../../utils/classNames'
import styles from './SourcesPage.module.css'

type SourcesPageProps = {
  deletingSourceId: string | null
  isSearching: boolean
  message: Message
  query: string
  searchLimit: number
  searchMode: SearchMode
  searchOutput: SearchResponse | null
  selectedSource: SourceRecord | undefined
  settings: SettingsResponse | null
  reindexingSourceId: string | null
  sources: SourceRecord[]
  totalSourceCount: number
  onRequestDeleteSource: (source: SourceRecord) => void
  onQueryChange: (query: string) => void
  onRefreshSources: () => Promise<void>
  onReindexSource: (source: SourceRecord) => Promise<void>
  onSearchDocs: FormSubmitHandler
  onSearchLimitChange: (limit: number) => void
  onSearchModeChange: (mode: SearchMode) => void
  onSelectSource: (sourceId: string) => void
}

const searchModeOptions: { value: SearchMode; label: string }[] = [
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'keyword', label: 'Full text' },
  { value: 'vector', label: 'Embeddings' },
]

export function SourcesPage({
  deletingSourceId,
  isSearching,
  message,
  query,
  searchLimit,
  searchMode,
  searchOutput,
  selectedSource,
  settings,
  reindexingSourceId,
  sources,
  totalSourceCount,
  onRequestDeleteSource,
  onQueryChange,
  onRefreshSources,
  onReindexSource,
  onSearchDocs,
  onSearchLimitChange,
  onSearchModeChange,
  onSelectSource,
}: SourcesPageProps) {
  const staleCount = sources.filter((source) => source.status === 'indexed' && !isSourceQueryable(source, settings)).length
  const selectedSourceQueryable = isSourceQueryable(selectedSource, settings)

  return (
    <main>
      <PageHeading
        title="Sources"
        text="View documentation sources, re-index stale vectors, and search compatible indexed corpora."
      />

      <section className={styles.panel} aria-labelledby="registry-title">
        <div className={styles.panelHeader}>
          <div>
            <h2 id="registry-title">Registry</h2>
            <p>{sources.length} source{sources.length === 1 ? '' : 's'}</p>
          </div>
          <button className={styles.secondaryButton} onClick={() => void onRefreshSources()} type="button">
            Refresh
          </button>
        </div>
        <MessageLine message={message} />
        {staleCount ? (
          <div className={styles.warningState}>
            {staleCount} indexed source{staleCount === 1 ? '' : 's'} must be re-indexed before search or agent retrieval.
          </div>
        ) : null}

        {sources.length ? (
          <div className={styles.sourceList}>
            {sources.map((source) => {
              const sourceQueryable = isSourceQueryable(source, settings)
              const metadata = sourceMetadata(source)
              const metadataItems = sourceMetadataItems(metadata)
              const isReindexing = reindexingSourceId === source.id || source.status === 'indexing'
              return (
                <div
                  aria-current={selectedSource?.id === source.id ? 'true' : undefined}
                  className={classNames(
                    selectedSource?.id === source.id ? styles.selectedSource : undefined,
                    source.status === 'indexed' && !sourceQueryable ? styles.staleSource : undefined,
                  )}
                  key={source.id}
                >
                  <button className={styles.sourceSelect} onClick={() => onSelectSource(source.id)} type="button">
                    <span className={styles.sourceIdentity}>
                      <strong>{source.name}</strong>
                      <span title={source.location}>{source.location}</span>
                    </span>
                    {metadataItems.length ? (
                      <dl className={styles.sourceDetails}>
                        {metadataItems.map((item) => (
                          <Detail key={item.label} label={item.label} value={item.value} />
                        ))}
                      </dl>
                    ) : (
                      <span className={styles.sourcePendingDetail}>
                        {source.status === 'indexing' ? 'Indexing metadata will appear when the job finishes.' : 'Not indexed yet.'}
                      </span>
                    )}
                  </button>
                  <span className={styles.sourceMeta}>
                    <Badge value={source.kind} variant={source.kind} />
                    <Badge
                      value={sourceCompatibilityLabel(source, sourceQueryable)}
                      variant={sourceQueryable ? 'indexed' : source.status === 'indexed' ? 'failed' : source.status}
                    />
                    <Badge value={`${source.document_count} docs`} />
                    <Badge value={`${source.chunk_count} chunks`} />
                    <button
                      className={styles.secondaryButton}
                      disabled={isReindexing}
                      onClick={() => void onReindexSource(source)}
                      type="button"
                    >
                      {isReindexing ? 'Indexing' : 'Reindex'}
                    </button>
                    <button
                      className={styles.dangerButton}
                      disabled={deletingSourceId === source.id}
                      onClick={() => onRequestDeleteSource(source)}
                      type="button"
                    >
                      {deletingSourceId === source.id ? 'Deleting' : 'Delete'}
                    </button>
                  </span>
                </div>
              )
            })}
          </div>
        ) : (
          <div className={styles.emptyState}>
            {totalSourceCount ? 'No sources match this view.' : 'No sources yet.'}
          </div>
        )}
      </section>

      <section className={styles.panel} aria-labelledby="search-title">
        <div className={styles.panelHeader}>
          <div>
            <h2 id="search-title">Search</h2>
            <p>{selectedSource ? selectedSource.name : 'Select a source'}</p>
          </div>
        </div>
        {selectedSource && !selectedSourceQueryable ? (
          <div className={styles.warningState}>{sourceQueryDisabledMessage(selectedSource, settings)}</div>
        ) : null}
        <form className={styles.searchForm} onSubmit={onSearchDocs}>
          <div className={styles.field}>
            <label htmlFor="query">Query</label>
            <input
              id="query"
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder='useEffect cleanup'
              required
              type="text"
              value={query}
            />
          </div>
          <div className={styles.field}>
            <label htmlFor="search-mode">Mode</label>
            <SelectControl id="search-mode" value={searchMode} options={searchModeOptions} onChange={onSearchModeChange} />
          </div>
          <div className={styles.field}>
            <label htmlFor="limit">Limit</label>
            <input
              id="limit"
              max="50"
              min="1"
              onChange={(event) => onSearchLimitChange(Number(event.target.value))}
              required
              type="number"
              value={searchLimit}
            />
          </div>
          <button className={styles.primaryButton} disabled={!selectedSource || !selectedSourceQueryable || isSearching} type="submit">
            {isSearching ? 'Searching' : 'Search'}
          </button>
        </form>
        <SearchResults output={searchOutput} />
      </section>
    </main>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

function SearchResults({ output }: { output: SearchResponse | null }) {
  if (!output) return <div className={styles.emptyState}>No results yet.</div>
  if (output.stderr) return <div className={styles.errorState}>{output.stderr}</div>
  if (!output.results.length) return <div className={styles.emptyState}>No matching results.</div>

  return (
    <div className={styles.resultList}>
      {output.results.map((result, index) => (
        <article className={styles.resultCard} key={`${result.uri}-${index}`}>
          <div className={styles.resultHeader}>
            <div>
              <span className={styles.resultIndex}>Result {index + 1}</span>
              <h3>{result.title}</h3>
            </div>
            <span className={styles.score}>{result.score.toFixed(3)}</span>
          </div>
          <p className={styles.resultSource}>{result.uri}</p>
          <p className={styles.snippet}>{formatSnippet(result.summary || result.content)}</p>
          {result.code ? <pre className={styles.codeSnippet}>{result.code}</pre> : null}
          <dl className={styles.metadataList}>
            <div>
              <dt>Keyword</dt>
              <dd>{result.keyword_score.toFixed(3)}</dd>
            </div>
            <div>
              <dt>Vector</dt>
              <dd>{result.vector_score.toFixed(3)}</dd>
            </div>
          </dl>
        </article>
      ))}
    </div>
  )
}

function formatSnippet(snippet: string) {
  const normalized = snippet.replace(/\s+\n/g, '\n').trim()
  return normalized.length > 1200 ? `${normalized.slice(0, 1200).trim()}...` : normalized
}

function isSourceQueryable(source: SourceRecord | undefined, settings: SettingsResponse | null) {
  if (!source || source.status !== 'indexed') return false
  const embedding = source.metadata.embedding
  if (!settings || !isRecord(embedding)) return false
  return embedding.provider === settings.embedding.provider && embedding.model === settings.embedding.model
}

function sourceMetadata(source: SourceRecord) {
  const embedding = isRecord(source.metadata.embedding) ? source.metadata.embedding : null
  const lastIndex = isRecord(source.metadata.last_index) ? source.metadata.last_index : null
  return {
    embedding: stringValue(embedding?.display_name) ?? stringValue(embedding?.model),
    finishedAt: formatDateTime(stringValue(lastIndex?.finished_at)),
    duration: formatDuration(numberValue(lastIndex?.duration_seconds)),
    strategy: formatStrategy(lastIndex),
  }
}

function sourceMetadataItems(metadata: ReturnType<typeof sourceMetadata>) {
  return [
    { label: 'Embedding', value: metadata.embedding },
    { label: 'Indexed', value: metadata.finishedAt },
    { label: 'Duration', value: metadata.duration },
    { label: 'Strategy', value: metadata.strategy },
  ].filter((item): item is { label: string; value: string } => Boolean(item.value))
}

function sourceQueryDisabledMessage(source: SourceRecord, settings: SettingsResponse | null) {
  if (source.status !== 'indexed') {
    return `${source.name} is ${source.status}. It must finish indexing before it can be searched.`
  }
  const current = settings?.embedding.display_name ?? 'the current embedding model'
  const metadata = sourceMetadata(source)
  if (!metadata.embedding) {
    return `${source.name} must be re-indexed before searching because it has no embedding model metadata.`
  }
  return `${source.name} must be re-indexed before searching. It was indexed with ${metadata.embedding}, but the current embedding model is ${current}.`
}

function sourceCompatibilityLabel(source: SourceRecord, sourceQueryable: boolean) {
  if (sourceQueryable) return 'queryable'
  if (source.status === 'indexed') return 'reindex required'
  return source.status
}

function formatStrategy(lastIndex: Record<string, unknown> | null) {
  if (!lastIndex) return undefined
  const strategy = stringValue(lastIndex.indexing_strategy)
  if (!strategy) return undefined
  const effectiveBatchSize = numberValue(lastIndex.effective_embedding_batch_size)
  return effectiveBatchSize ? `${strategy} / ${effectiveBatchSize}` : strategy
}

function formatDateTime(value: string | undefined) {
  if (!value) return undefined
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return undefined
  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function formatDuration(value: number | undefined) {
  if (value === undefined) return undefined
  if (value < 1) return `${Math.round(value * 1000)} ms`
  if (value < 60) return `${value.toFixed(1)} s`
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return `${minutes}m ${seconds}s`
}

function stringValue(value: unknown) {
  return typeof value === 'string' && value ? value : undefined
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
