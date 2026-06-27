import { useMemo, useState } from 'react'
import type {
  CliPathSettings,
  EmbeddingIndexingStrategy,
  DesktopUpdateStatus,
  Message,
  OllamaModelsResponse,
  SearchMode,
  SettingsResponse,
  SkillTargetsResponse,
  StartupSettings,
} from '../../types'
import { MessageLine } from '../../components/ui/MessageLine/MessageLine'
import { PageHeading } from '../../components/ui/PageHeading/PageHeading'
import { SelectControl } from '../../components/ui/SelectControl/SelectControl'
import styles from './SettingsPage.module.css'

type SettingsPageProps = {
  settings: SettingsResponse | null
  skillTargets: SkillTargetsResponse | null
  startupSettings: StartupSettings | null
  cliPathSettings: CliPathSettings | null
  updateStatus: DesktopUpdateStatus | null
  message: Message
  ollamaModels: OllamaModelsResponse | null
  isDesktopAvailable: boolean
  isSavingSettings: boolean
  isSyncingSkills: boolean
  isSavingStartup: boolean
  isAddingCliPath: boolean
  isCheckingUpdate: boolean
  isInstallingUpdate: boolean
  onSaveSettings: (request: SettingsSaveRequest) => Promise<void>
  onSyncSkills: (targetIds?: string[]) => Promise<void>
  onSetStartupEnabled: (enabled: boolean) => Promise<void>
  onAddCliToPath: () => Promise<void>
  onCopyCliPath: () => Promise<void>
  onCheckForUpdates: () => Promise<void>
  onInstallUpdate: () => Promise<void>
}

export type SettingsSaveRequest = {
  resetToDefaults: boolean
  model: string | null
  indexing: { strategy: EmbeddingIndexingStrategy; batchSize: number } | null
  retrievalMode: SearchMode | null
}

const retrievalModeOptions: { value: SearchMode; label: string; description: string }[] = [
  { value: 'hybrid', label: 'Hybrid', description: 'Combine full text and embedding similarity.' },
  { value: 'keyword', label: 'Full text', description: 'Use SQLite FTS5 keyword ranking only.' },
  { value: 'vector', label: 'Embeddings', description: 'Use local embedding similarity only.' },
]

const indexingStrategyOptions: { value: EmbeddingIndexingStrategy; label: string; description: string }[] = [
  { value: 'batch', label: 'Batch', description: 'Send multiple chunks to Ollama per request.' },
  { value: 'single', label: 'Single', description: 'Send one chunk to Ollama per request.' },
]

const MIN_BATCH_SIZE = 1
const MAX_BATCH_SIZE = 256
const DEFAULT_INDEXING_STRATEGY: EmbeddingIndexingStrategy = 'batch'
const DEFAULT_BATCH_SIZE = 32
const DEFAULT_RETRIEVAL_MODE: SearchMode = 'hybrid'

export function SettingsPage({
  settings,
  skillTargets,
  startupSettings,
  cliPathSettings,
  updateStatus,
  message,
  ollamaModels,
  isDesktopAvailable,
  isSavingSettings,
  isSyncingSkills,
  isSavingStartup,
  isAddingCliPath,
  isCheckingUpdate,
  isInstallingUpdate,
  onSaveSettings,
  onSyncSkills,
  onSetStartupEnabled,
  onAddCliToPath,
  onCopyCliPath,
  onCheckForUpdates,
  onInstallUpdate,
}: SettingsPageProps) {
  const [draftModel, setDraftModel] = useState<string | null>(null)
  const [draftIndexingStrategy, setDraftIndexingStrategy] = useState<EmbeddingIndexingStrategy | null>(null)
  const [draftBatchSize, setDraftBatchSize] = useState<string | null>(null)
  const [draftRetrievalMode, setDraftRetrievalMode] = useState<SearchMode | null>(null)
  const [isResetPending, setIsResetPending] = useState(false)
  const isOllamaChecking = !ollamaModels
  const isOllamaReachable = Boolean(ollamaModels?.reachable)
  const ollamaModelNames = useMemo(() => ollamaModels?.models ?? [], [ollamaModels?.models])
  const hasOllamaModels = isOllamaReachable && ollamaModelNames.length > 0
  const ollamaModelOptions = useMemo(
    () => ollamaModelNames.map((model) => ({ value: model, label: model })),
    [ollamaModelNames],
  )
  const savedModel = settings?.embedding.provider === 'ollama' ? settings.embedding.model : ''
  const selectedModel = draftModel ?? (isResetPending ? '' : savedModel)
  const staleSourceCount = settings?.source_compatibility.stale_indexed_source_count ?? 0
  const defaultIndexingStrategy = settings?.embedding.indexing.default_strategy ?? DEFAULT_INDEXING_STRATEGY
  const defaultBatchSize = settings?.embedding.indexing.default_batch_size ?? DEFAULT_BATCH_SIZE
  const savedIndexingStrategy = settings?.embedding.indexing.strategy ?? defaultIndexingStrategy
  const selectedIndexingStrategy = draftIndexingStrategy ?? (isResetPending ? defaultIndexingStrategy : savedIndexingStrategy)
  const savedBatchSize = settings?.embedding.indexing.batch_size ?? defaultBatchSize
  const selectedBatchSize = draftBatchSize !== null ? Number(draftBatchSize) : isResetPending ? defaultBatchSize : savedBatchSize
  const isBatchSizeValid =
    Number.isInteger(selectedBatchSize) &&
    selectedBatchSize >= MIN_BATCH_SIZE &&
    selectedBatchSize <= MAX_BATCH_SIZE
  const effectiveBatchSizeLabel = isBatchSizeValid
    ? selectedIndexingStrategy === 'single'
      ? '1'
      : String(selectedBatchSize)
    : '-'
  const savedRetrievalMode = settings?.default_search_mode ?? DEFAULT_RETRIEVAL_MODE
  const selectedRetrievalMode = draftRetrievalMode ?? (isResetPending ? DEFAULT_RETRIEVAL_MODE : savedRetrievalMode)

  const modelChanged = Boolean(selectedModel && (isResetPending || selectedModel !== savedModel))
  const indexingChanged = isResetPending
    ? selectedIndexingStrategy !== defaultIndexingStrategy || selectedBatchSize !== defaultBatchSize
    : selectedIndexingStrategy !== savedIndexingStrategy || selectedBatchSize !== savedBatchSize
  const retrievalChanged = isResetPending
    ? selectedRetrievalMode !== DEFAULT_RETRIEVAL_MODE
    : selectedRetrievalMode !== savedRetrievalMode
  const hasChanges = isResetPending || modelChanged || indexingChanged || retrievalChanged
  const canSaveSettings = Boolean(settings) && hasChanges && isBatchSizeValid && !isSavingSettings
  const modelPlaceholder = isResetPending
    ? 'Built-in local hashing'
    : hasOllamaModels
      ? 'Select a local embedding model'
      : isOllamaChecking
        ? 'Checking Ollama'
        : 'Built-in local hashing'
  const ollamaStatusText = isOllamaChecking
    ? 'Checking whether Ollama is available on this machine...'
    : !isOllamaReachable
      ? `${ollamaModels?.error ?? 'Ollama is not available.'} No action is required unless you want optional stronger semantic embeddings.`
      : !hasOllamaModels
        ? `Ollama is running at ${ollamaModels?.base_url}, but no models are installed. Pull an embedding model such as nomic-embed-text to enable Ollama-backed search.`
        : `Ollama is available at ${ollamaModels?.base_url}. Select one of the installed models only if you want new indexes to use Ollama embeddings.`

  function resetDraftToDefaults() {
    setIsResetPending(true)
    setDraftModel(null)
    setDraftIndexingStrategy(defaultIndexingStrategy)
    setDraftBatchSize(String(defaultBatchSize))
    setDraftRetrievalMode(DEFAULT_RETRIEVAL_MODE)
  }

  async function saveSettings() {
    if (!canSaveSettings) return
    await onSaveSettings({
      resetToDefaults: isResetPending,
      model: modelChanged ? selectedModel : null,
      indexing: indexingChanged ? { strategy: selectedIndexingStrategy, batchSize: selectedBatchSize } : null,
      retrievalMode: retrievalChanged ? selectedRetrievalMode : null,
    })
    setIsResetPending(false)
    setDraftModel(null)
    setDraftIndexingStrategy(null)
    setDraftBatchSize(null)
    setDraftRetrievalMode(null)
  }

  return (
    <main>
      <PageHeading title="Settings" text="Configure the defaults used for new indexes and search." />

      <section className={styles.settingsPanel} aria-label="Settings defaults">
        <div className={styles.panelHeader}>
          <button
            className={styles.secondaryButton}
            disabled={!settings || isSavingSettings}
            type="button"
            onClick={resetDraftToDefaults}
          >
            Reset
          </button>
          <button
            className={styles.saveButton}
            disabled={!canSaveSettings}
            type="button"
            onClick={() => void saveSettings()}
          >
            {isSavingSettings ? 'Saving...' : 'Save'}
          </button>
        </div>

        <div className={styles.settingsRows}>
          <div className={styles.settingRow}>
            <div className={styles.rowCopy}>
              <label htmlFor="embedding-model">Embedding model</label>
              <p>
                Built-in local hashing works without Ollama. Choose an Ollama model only for stronger semantic search on
                machines that can run a local embedding model.
              </p>
            </div>
            <div className={styles.rowControls}>
              <SelectControl
                id="embedding-model"
                value={selectedModel}
                disabled={isSavingSettings || !hasOllamaModels}
                options={ollamaModelOptions}
                placeholder={modelPlaceholder}
                onChange={setDraftModel}
              />
            </div>
            <p className={isOllamaReachable && hasOllamaModels ? styles.rowNote : styles.ollamaNotice}>{ollamaStatusText}</p>
            {staleSourceCount ? (
              <p className={styles.warningText}>
                {staleSourceCount} indexed source{staleSourceCount === 1 ? '' : 's'} must be re-indexed before search.
              </p>
            ) : null}
          </div>

          <div className={styles.settingRow}>
            <div className={styles.rowCopy}>
              <label htmlFor="indexing-strategy">Embedding indexing</label>
              <p>Tune how new indexes send chunks to the embedding provider.</p>
              <span>
                Effective batch size: {effectiveBatchSizeLabel}. Default:{' '}
                {defaultIndexingStrategy} / {defaultBatchSize}.
              </span>
            </div>
            <div className={styles.indexingControls}>
              <SelectControl
                id="indexing-strategy"
                value={selectedIndexingStrategy}
                disabled={isSavingSettings}
                options={indexingStrategyOptions}
                onChange={(value) => setDraftIndexingStrategy(value)}
              />
              <input
                id="batch-size"
                aria-label="Batch size"
                max={MAX_BATCH_SIZE}
                min={MIN_BATCH_SIZE}
                step={1}
                type="number"
                value={draftBatchSize ?? String(isResetPending ? defaultBatchSize : savedBatchSize)}
                disabled={isSavingSettings}
                onChange={(event) => setDraftBatchSize(event.target.value)}
              />
            </div>
            {!isBatchSizeValid ? (
              <p className={styles.errorText}>Batch size must be a whole number from {MIN_BATCH_SIZE} to {MAX_BATCH_SIZE}.</p>
            ) : null}
          </div>

          <div className={styles.settingRow}>
            <div className={styles.rowCopy}>
              <label htmlFor="retrieval-mode">Retrieval</label>
              <p>Default search mode when no mode is specified.</p>
            </div>
            <div className={styles.rowControls}>
              <SelectControl
                id="retrieval-mode"
                value={selectedRetrievalMode}
                disabled={isSavingSettings}
                options={retrievalModeOptions}
                onChange={(value) => setDraftRetrievalMode(value)}
              />
            </div>
          </div>
        </div>

        <MessageLine message={message} />
      </section>

      {isDesktopAvailable ? (
        <>
          <section className={styles.settingsPanel} aria-label="Desktop behavior">
            <div className={styles.panelHeader}>
              <div className={styles.panelTitle}>
                <h2>Desktop</h2>
                <p>Keep the local API available for agents after sign-in.</p>
              </div>
            </div>

            <div className={styles.desktopRows}>
              <label className={styles.toggleRow}>
                <input
                  checked={Boolean(startupSettings?.openAtLogin)}
                  disabled={!startupSettings?.supported || isSavingStartup}
                  type="checkbox"
                  onChange={(event) => void onSetStartupEnabled(event.target.checked)}
                />
                <span>Start with Windows</span>
              </label>
              {!startupSettings?.supported ? (
                <p className={styles.rowNote}>Startup control is available in the installed Windows app.</p>
              ) : null}

              <div className={styles.cliPathBlock}>
                <div className={styles.cliPathHeader}>
                  <div>
                    <h3>Command line access</h3>
                    <p>
                      {cliPathSettings?.inPath
                        ? 'The Ingestor CLI folder is already on your user PATH.'
                        : 'Add the Ingestor CLI folder to your user PATH or copy the folder path for manual setup.'}
                    </p>
                  </div>
                  <button
                    className={styles.saveButton}
                    disabled={!cliPathSettings?.supported || cliPathSettings.inPath || isAddingCliPath}
                    type="button"
                    onClick={() => void onAddCliToPath()}
                  >
                    {isAddingCliPath ? 'Adding...' : cliPathSettings?.inPath ? 'Added' : 'Add to PATH'}
                  </button>
                </div>

                <div className={styles.cliPathControls}>
                  <input
                    aria-label="Ingestor CLI folder"
                    readOnly
                    value={cliPathSettings?.path || ''}
                    placeholder="CLI folder is available in the installed Windows app"
                    onFocus={(event) => event.currentTarget.select()}
                  />
                  <button
                    className={styles.secondaryButton}
                    disabled={!cliPathSettings?.path}
                    type="button"
                    onClick={() => void onCopyCliPath()}
                  >
                    Copy
                  </button>
                </div>

                {!cliPathSettings?.supported ? (
                  <p className={styles.rowNote}>CLI PATH management is available in the installed Windows app.</p>
                ) : null}
              </div>
            </div>
          </section>

          <section className={styles.settingsPanel} aria-label="App updates">
            <div className={styles.panelHeader}>
              <div className={styles.panelTitle}>
                <h2>Updates</h2>
                <p>Check for signed Ingestor releases.</p>
              </div>
              <button
                className={styles.secondaryButton}
                disabled={isCheckingUpdate || isInstallingUpdate}
                type="button"
                onClick={() => void onCheckForUpdates()}
              >
                {isCheckingUpdate ? 'Checking...' : 'Check'}
              </button>
            </div>

            <div className={styles.updateRows}>
              {updateStatus?.available ? (
                <div className={styles.updateAvailable}>
                  <div>
                    <strong>Version {updateStatus.version} is available</strong>
                    <p>
                      Current version: {updateStatus.currentVersion}
                      {updateStatus.date ? ` - Published ${updateStatus.date}` : ''}
                    </p>
                    {updateStatus.body ? <p>{updateStatus.body}</p> : null}
                  </div>
                  <button
                    className={styles.saveButton}
                    disabled={isInstallingUpdate}
                    type="button"
                    onClick={() => void onInstallUpdate()}
                  >
                    {isInstallingUpdate ? 'Installing...' : 'Install update'}
                  </button>
                </div>
              ) : updateStatus ? (
                <p className={styles.rowNote}>Ingestor is up to date.</p>
              ) : (
                <p className={styles.rowNote}>No update check has run in this session.</p>
              )}
            </div>
          </section>
        </>
      ) : null}

      <section className={styles.settingsPanel} aria-label="Agent skill sync">
        <div className={styles.panelHeader}>
          <div className={styles.panelTitle}>
            <h2>Agent Skills</h2>
            <p>Install or refresh Ingestor skills in the supported agent folders.</p>
          </div>
          <button
            className={styles.saveButton}
            disabled={!skillTargets?.targets.length || isSyncingSkills}
            type="button"
            onClick={() => void onSyncSkills()}
          >
            {isSyncingSkills ? 'Updating...' : 'Update all'}
          </button>
        </div>

        <div className={styles.skillTargets}>
          {skillTargets?.targets.map((target) => (
            <div className={styles.skillTarget} key={target.id}>
              <div className={styles.skillTargetHeader}>
                <div>
                  <h3>{target.label}</h3>
                  <p>{target.path}</p>
                </div>
                <button
                  className={styles.secondaryButton}
                  disabled={isSyncingSkills}
                  type="button"
                  onClick={() => void onSyncSkills([target.id])}
                >
                  Update
                </button>
              </div>
              <div className={styles.skillRows}>
                {target.skills.map((skill) => (
                  <div className={styles.skillRow} key={skill.name}>
                    <span>{skill.name}</span>
                    <strong data-state={skill.current ? 'current' : 'stale'}>
                      {skill.current ? 'Current' : skill.installed ? 'Update available' : 'Not installed'}
                    </strong>
                  </div>
                ))}
              </div>
            </div>
          )) ?? (
            <p className={styles.rowNote}>Checking skill folders...</p>
          )}
        </div>
      </section>
    </main>
  )
}
