import type { FormSubmitHandler, IndexJob, Message, SearchMode, SearchResponse, SettingsResponse, SourceRecord } from '../../types'
import { Badge } from '../../components/ui/Badge/Badge'
import { MessageLine } from '../../components/ui/MessageLine/MessageLine'
import { PageHeading } from '../../components/ui/PageHeading/PageHeading'
import { SelectControl } from '../../components/ui/SelectControl/SelectControl'
import { classNames } from '../../utils/classNames'
import { jobProgress } from '../../utils/jobProgress'
import {
  isActiveJob,
  isRecord,
  isSourceQueryable,
  sourceEmbeddingDisplayName,
  sourceQueryDisabledMessage,
} from '../../utils/sourceHelpers'
import styles from './SourcesPage.module.css'

type SourcesPageProps = {
  deletingSourceId: string | null
  hasSearched: boolean
  isSearching: boolean
  message: Message
  query: string
  searchLimit: number
  searchMode: SearchMode
  searchOutput: SearchResponse | null
  selectedSource: SourceRecord | undefined
  settings: SettingsResponse | null
  reindexingSourceId: string | null
  jobs: IndexJob[]
  sources: SourceRecord[]
  totalSourceCount: number
  onCancelJob: (job: IndexJob) => Promise<void>
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
  hasSearched,
  isSearching,
  message,
  query,
  searchLimit,
  searchMode,
  searchOutput,
  selectedSource,
  settings,
  reindexingSourceId,
  jobs,
  sources,
  totalSourceCount,
  onCancelJob,
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
  const staleWarningText = `${formatIndexedSourceCount(staleCount)} must be re-indexed before search or agent retrieval.`
  const selectedSourceQueryable = isSourceQueryable(selectedSource, settings)
  const selectedSourceJob = selectedSource ? jobs.find((job) => job.source_id === selectedSource.id) : undefined
  const isSelectedSourceReindexing = Boolean(
    selectedSource &&
      (reindexingSourceId === selectedSource.id ||
        selectedSource.status === 'indexing' ||
        (selectedSourceJob && isActiveJob(selectedSourceJob))),
  )

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
            <p>{formatSourceCount(sources.length)}</p>
          </div>
          <button className={styles.secondaryButton} onClick={() => void onRefreshSources()} type="button">
            Refresh
          </button>
        </div>
        <MessageLine message={message} />
        {staleCount ? (
          <div className={styles.warningState}>
            {staleWarningText}
          </div>
        ) : null}

        {sources.length ? (
          <div className={styles.sourceList}>
            {sources.map((source) => {
              const sourceJob = jobs.find((job) => job.source_id === source.id)
              const sourceQueryable = isSourceQueryable(source, settings)
              const metadata = sourceMetadata(source)
              const metadataItems = sourceMetadataItems(metadata)
              const isActiveIndex = Boolean(sourceJob && isActiveJob(sourceJob))
              const isReindexing = reindexingSourceId === source.id || isActiveIndex || source.status === 'indexing'
              return (
                <div
                  aria-current={selectedSource?.id === source.id ? 'true' : undefined}
                  className={classNames(
                    selectedSource?.id === source.id ? styles.selectedSource : undefined,
                    source.status === 'indexed' && !sourceQueryable ? styles.staleSource : undefined,
                  )}
                  key={source.id}
                >
                  <button
                    aria-label={`Select ${source.name}`}
                    className={styles.sourceSelect}
                    onClick={() => onSelectSource(source.id)}
                    type="button"
                  >
                    <span className={styles.sourceIdentity}>
                      <strong>{source.name}</strong>
                      <span className={styles.sourceLocation} title={source.location}>
                        {source.location}
                      </span>
                    </span>
                    {sourceJob && isActiveJob(sourceJob) ? <JobProgress job={sourceJob} source={source} /> : null}
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
                    {sourceJob && isActiveJob(sourceJob) ? (
                      <button
                        className={styles.dangerButton}
                        disabled={sourceJob.status === 'cancelling'}
                        onClick={() => void onCancelJob(sourceJob)}
                        type="button"
                      >
                        {sourceJob.status === 'cancelling' ? 'Cancelling' : 'Cancel'}
                      </button>
                    ) : null}
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
          <div className={styles.warningState}>
            {sourceQueryDisabledMessage(selectedSource, settings)}
            {jobs.some((job) => job.source_id === selectedSource.id && isActiveJob(job)) ? (
              <button className={styles.inlineLinkButton} onClick={() => onSelectSource(selectedSource.id)} type="button">
                View indexing progress in the registry.
              </button>
            ) : null}
          </div>
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
            <SelectControl
              id="search-mode"
              accessibleLabel="Mode"
              value={searchMode}
              options={searchModeOptions}
              onChange={onSearchModeChange}
            />
          </div>
          <div className={styles.field}>
            <label htmlFor="limit">Limit</label>
            <input
              id="limit"
              max="50"
              min="1"
              onChange={(event) => onSearchLimitChange(clampSearchLimit(Number(event.target.value)))}
              onFocus={(event) => event.currentTarget.select()}
              required
              type="number"
              value={searchLimit}
            />
          </div>
          <button className={styles.primaryButton} disabled={!selectedSource || !selectedSourceQueryable || isSearching} type="submit">
            {isSearching ? 'Searching' : 'Search'}
          </button>
        </form>
        {searchOutput && isSelectedSourceReindexing ? (
          <div className={styles.searchNotice}>
            Reindexing is running. Existing results remain visible and may be outdated until indexing finishes.
          </div>
        ) : null}
        {isSearching && searchOutput ? (
          <div className={styles.searchNotice}>
            Searching. Existing results remain visible until the new search finishes.
          </div>
        ) : null}
        <SearchResults hasSearched={hasSearched} isSearching={isSearching} output={searchOutput} />
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

function JobProgress({ job, source }: { job: IndexJob; source: SourceRecord }) {
  const progress = jobProgress(job)
  return (
    <div className={styles.jobProgress} aria-label={`${source.name} indexing progress`}>
      <div className={styles.progressTrack} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent}>
        <span style={{ width: `${progress.percent}%` }} />
      </div>
      <span>
        {progress.label}
        {progress.eta ? ` - ${progress.eta}` : ''}
      </span>
    </div>
  )
}

function SearchResults({
  hasSearched,
  isSearching,
  output,
}: {
  hasSearched: boolean
  isSearching: boolean
  output: SearchResponse | null
}) {
  if (!output) {
    if (isSearching) return <div className={styles.emptyState}>Searching...</div>
    return <div className={styles.emptyState}>{hasSearched ? 'No results yet.' : 'No search has been run yet.'}</div>
  }
  if (output.stderr) return <div className={styles.errorState}>{output.stderr}</div>
  if (!output.results.length) return <div className={styles.emptyState}>No matching results.</div>

  return (
    <div className={styles.resultList}>
      {output.results.map((result, index) => {
        const resultIndexLabel = `Result ${index + 1}`
        return (
          <article className={styles.resultCard} key={`${result.uri}-${index}`}>
            <div className={styles.resultHeader}>
              <div>
                <span className={styles.resultIndex}>{resultIndexLabel}</span>
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
        )
      })}
    </div>
  )
}

function formatSnippet(snippet: string) {
  const normalized = snippet.replace(/\s+\n/g, '\n').trim()
  return normalized.length > 1200 ? `${normalized.slice(0, 1200).trim()}...` : normalized
}

function sourceMetadata(source: SourceRecord) {
  const lastIndex = isRecord(source.metadata.last_index) ? source.metadata.last_index : null
  return {
    embedding: sourceEmbeddingDisplayName(source),
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

function formatSourceCount(count: number) {
  return `${count} ${count === 1 ? 'source' : 'sources'}`
}

function formatIndexedSourceCount(count: number) {
  return `${count} indexed ${count === 1 ? 'source' : 'sources'}`
}

function clampSearchLimit(value: number) {
  if (!Number.isFinite(value)) return 8
  return Math.min(50, Math.max(1, Math.trunc(value)))
}
