import type {
  FormSubmitHandler,
  IndexJob,
  LocalForm,
  Message,
  SourceMode,
  SourceRecord,
  ViewName,
  WebForm
} from "../../types";
import { ModeTabs } from "../../components/source/ModeTabs/ModeTabs";
import { Badge } from "../../components/ui/Badge/Badge";
import { MessageLine } from "../../components/ui/MessageLine/MessageLine";
import { PageHeading } from "../../components/ui/PageHeading/PageHeading";
import { SelectControl } from "../../components/ui/SelectControl/SelectControl";
import styles from "./CapturePage.module.css";

type CapturePageProps = {
  activeLogs: string;
  latestJob: IndexJob | undefined;
  selectedSource: SourceRecord | undefined;
  mode: SourceMode;
  message: Message;
  recentSources: SourceRecord[];
  localForm: LocalForm;
  webForm: WebForm;
  isPickingFiles: boolean;
  isPickingFolder: boolean;
  isSubmitting: boolean;
  onModeChange: (mode: SourceMode) => void;
  onLocalFormChange: (form: LocalForm) => void;
  onWebFormChange: (form: WebForm) => void;
  onPickFiles: () => void;
  onPickFolder: () => void;
  onRemoveLocalPath: (path: string) => void;
  onRegisterLocal: FormSubmitHandler;
  onRegisterWeb: FormSubmitHandler;
  onResetWebOptions: () => void;
  onNavigate: (view: ViewName) => void;
  onSelectSource: (sourceId: string) => void;
};

const crawlScopeOptions: {
  value: WebForm["scope"];
  label: string;
  description: string;
}[] = [
  {
    value: "hostname",
    label: "Hostname",
    description: "Stay on the same host as the starting URL."
  },
  {
    value: "subpages",
    label: "Subpages",
    description: "Only crawl URLs beneath the starting URL path."
  },
  {
    value: "domain",
    label: "Domain",
    description: "Allow the registrable domain and its subdomains."
  }
];

export function CapturePage({
  activeLogs,
  latestJob,
  selectedSource,
  mode,
  message,
  recentSources,
  localForm,
  webForm,
  isPickingFiles,
  isPickingFolder,
  isSubmitting,
  onModeChange,
  onLocalFormChange,
  onWebFormChange,
  onPickFiles,
  onPickFolder,
  onRemoveLocalPath,
  onRegisterLocal,
  onRegisterWeb,
  onResetWebOptions,
  onNavigate,
  onSelectSource
}: CapturePageProps) {
  const isLocal = mode === "local";
  const isPickingLocalPath = isPickingFolder || isPickingFiles;
  const lastLogLine = latestLogLine(activeLogs);
  const recentLogLines = latestLogLines(activeLogs, 4);

  function openSource(sourceId: string) {
    onSelectSource(sourceId);
    onNavigate("sources");
  }

  return (
    <main>
      <PageHeading
        title="Capture documentation"
        text="Add a local docs folder or crawl a remote docs site. Ingestor indexes it into a local SQLite store for CLI, UI, and agent retrieval."
      />

      <section className={styles.captureCard} aria-labelledby="capture-title">
        <h2 id="capture-title" className={styles.visuallyHidden}>
          Add a source
        </h2>

        <ModeTabs mode={mode} onModeChange={onModeChange} />

        {isLocal ? (
          <form onSubmit={onRegisterLocal}>
            <div className={styles.selectionBlock}>
              <div className={styles.selectionHeader}>
                <div>
                  <h3>Selected paths</h3>
                  <p>Folder and file names are shown here after selection.</p>
                </div>
                <div className={styles.pathField}>
                  <button
                    className={styles.secondaryButton}
                    disabled={isPickingLocalPath}
                    onClick={onPickFolder}
                    type="button"
                  >
                    {isPickingFolder ? "Opening" : "Add folder"}
                  </button>
                  <button
                    className={styles.secondaryButton}
                    disabled={isPickingLocalPath}
                    onClick={onPickFiles}
                    type="button"
                  >
                    {isPickingFiles ? "Opening" : "Add files"}
                  </button>
                </div>
              </div>
              {localForm.paths.filter(Boolean).length ? (
                <div className={styles.selectedPathList}>
                  {localForm.paths.filter(Boolean).map((path) => (
                    <span className={styles.selectedPath} key={path}>
                      <span title={path}>{pathLabel(path)}</span>
                      <button
                        onClick={() => onRemoveLocalPath(path)}
                        type="button"
                        aria-label={`Remove ${path}`}
                      >
                        x
                      </button>
                    </span>
                  ))}
                </div>
              ) : (
                <div className={styles.emptySelection}>
                  No folders or files selected.
                </div>
              )}
            </div>
            <div className={styles.field}>
              <label htmlFor="local-source-name">Name</label>
              <input
                id="local-source-name"
                onChange={(event) =>
                  onLocalFormChange({ ...localForm, name: event.target.value })
                }
                required
                type="text"
                value={localForm.name}
              />
            </div>
            <div className={styles.formActions}>
              <span className={styles.hint}>
                Indexes supported text, markup, JSON, YAML, TOML, and HTML
                files.
              </span>
              <button
                className={styles.primaryButton}
                disabled={isSubmitting}
                type="submit"
              >
                {isSubmitting ? "Starting" : "Index selected docs"}
              </button>
            </div>
            <MessageLine message={message} />
          </form>
        ) : (
          <form onSubmit={onRegisterWeb}>
            <div className={styles.field}>
              <label htmlFor="web-url">Docs URL</label>
              <input
                id="web-url"
                onChange={(event) =>
                  onWebFormChange({ ...webForm, url: event.target.value })
                }
                placeholder="https://react.dev/reference/react"
                required
                type="url"
                value={webForm.url}
              />
            </div>
            <div className={styles.field}>
              <label htmlFor="web-source-name">Name</label>
              <input
                id="web-source-name"
                onChange={(event) =>
                  onWebFormChange({ ...webForm, name: event.target.value })
                }
                placeholder="react"
                required
                type="text"
                value={webForm.name}
              />
            </div>
            <details className={styles.advancedOptions}>
              <summary>Advanced crawl options</summary>
              <div className={styles.advancedIntro}>
                <p>
                  Filter crawled URLs before they are indexed. Patterns are one
                  per line and support glob syntax or slash-delimited regular
                  expressions.
                </p>
                <button
                  className={styles.resetButton}
                  onClick={onResetWebOptions}
                  type="button"
                >
                  Reset defaults
                </button>
              </div>
              <div className={styles.optionGrid}>
                <div className={styles.field}>
                  <label htmlFor="web-max-pages">Max pages</label>
                  <input
                    id="web-max-pages"
                    max="1000"
                    min="1"
                    onChange={(event) =>
                      onWebFormChange({
                        ...webForm,
                        maxPages: Number(event.target.value)
                      })
                    }
                    required
                    type="number"
                    value={webForm.maxPages}
                  />
                </div>
                <div className={styles.field}>
                  <label htmlFor="web-max-depth">Max depth</label>
                  <input
                    id="web-max-depth"
                    max="10"
                    min="0"
                    onChange={(event) =>
                      onWebFormChange({
                        ...webForm,
                        maxDepth: Number(event.target.value)
                      })
                    }
                    required
                    type="number"
                    value={webForm.maxDepth}
                  />
                </div>
                <div className={styles.field}>
                  <span className={styles.fieldLabel}>Scope</span>
                  <SelectControl
                    id="web-scope"
                    value={webForm.scope}
                    options={crawlScopeOptions}
                    onChange={(scope) => onWebFormChange({ ...webForm, scope })}
                  />
                </div>
              </div>
              <div className={styles.patternGrid}>
                <div className={styles.patternField}>
                  <label htmlFor="web-include-patterns">Include patterns</label>
                  <textarea
                    id="web-include-patterns"
                    onChange={(event) =>
                      onWebFormChange({
                        ...webForm,
                        includePatterns: event.target.value
                      })
                    }
                    placeholder={`https://docs.example.com/reference/**\ndocs/reference/**`}
                    value={webForm.includePatterns}
                  />
                  <p className={styles.fieldHint}>
                    When set, only URLs matching at least one pattern are
                    indexed.
                  </p>
                </div>
                <div className={styles.patternField}>
                  <label htmlFor="web-exclude-patterns">Exclude patterns</label>
                  <textarea
                    id="web-exclude-patterns"
                    onChange={(event) =>
                      onWebFormChange({
                        ...webForm,
                        excludePatterns: event.target.value
                      })
                    }
                    value={webForm.excludePatterns}
                  />
                  <p className={styles.fieldHint}>
                    Matching URLs are skipped even when they pass the scope and
                    include filters.
                  </p>
                </div>
              </div>
            </details>
            <div className={styles.formActions}>
              <span className={styles.hint}>
                Uses Crawl4AI, then indexes cleaned markdown content directly.
              </span>
              <button
                className={styles.primaryButton}
                disabled={isSubmitting}
                type="submit"
              >
                {isSubmitting ? "Starting" : "Index website"}
              </button>
            </div>
            <MessageLine message={message} />
          </form>
        )}
      </section>

      <section
        className={styles.progressPanel}
        aria-labelledby="progress-title"
      >
        <div className={styles.sectionHeading}>
          <h2 id="progress-title">Index progress</h2>
          {selectedSource ? (
            <Badge
              value={selectedSource.status}
              variant={selectedSource.status}
            />
          ) : null}
        </div>

        {latestJob && selectedSource ? (
          <div className={styles.progressContent}>
            <div className={styles.progressSummary}>
              <div>
                <strong>
                  {latestJob.status === "running"
                    ? "Indexing"
                    : latestJob.status}
                </strong>
                <span>{selectedSource.name}</span>
              </div>
              <div className={styles.progressStats} aria-label="Index counts">
                <span>
                  <strong>{selectedSource.document_count}</strong>
                  {selectedSource.kind === "web" ? "pages" : "docs"}
                </span>
                <span>
                  <strong>{selectedSource.chunk_count}</strong>
                  chunks
                </span>
              </div>
            </div>
            <ol className={styles.stageList}>
              <li className={styles.done}>
                <span /> Registered
              </li>
              <li
                className={
                  latestJob.status === "running" ? styles.active : styles.done
                }
              >
                <span /> Ingesting
              </li>
              <li
                className={
                  latestJob.status === "succeeded"
                    ? styles.done
                    : styles.pending
                }
              >
                <span /> Searchable
              </li>
            </ol>
            <div className={styles.jobDetail}>
              <span>Job {latestJob.id.slice(0, 8)}</span>
              <span>{latestJob.message || selectedSource.location}</span>
            </div>
            {selectedSource.error || lastLogLine ? (
              <p className={styles.logLine}>
                {selectedSource.error ?? lastLogLine}
              </p>
            ) : null}
            {recentLogLines.length > 1 ? (
              <ol className={styles.logList} aria-label="Recent index activity">
                {recentLogLines.map((line, index) => (
                  <li key={`${index}-${line}`}>{line}</li>
                ))}
              </ol>
            ) : null}
          </div>
        ) : (
          <div className={styles.emptyState}>
            No indexing job has started yet.
          </div>
        )}
      </section>

      <section className={styles.recentPanel} aria-labelledby="recent-title">
        <div className={styles.sectionHeading}>
          <h2 id="recent-title">Recent sources</h2>
          <button
            className={styles.linkButton}
            onClick={() => onNavigate("sources")}
            type="button"
          >
            View all
          </button>
        </div>
        <div className={styles.sourceList}>
          {recentSources.length ? (
            recentSources.map((source) => (
              <button
                className={styles.sourceItem}
                key={source.id}
                onClick={() => openSource(source.id)}
                type="button"
              >
                <span className={styles.sourceMeta}>
                  <strong>{source.name}</strong>
                  <span>{source.location}</span>
                </span>
                <Badge value={source.kind} variant={source.kind} />
                <Badge value={source.status} variant={source.status} />
              </button>
            ))
          ) : (
            <div className={styles.emptyState}>
              No sources yet. Add a folder or URL above.
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

function latestLogLine(logs: string) {
  return latestLogLines(logs, 1).at(0);
}

function latestLogLines(logs: string, limit: number) {
  return logs
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(-limit);
}

function pathLabel(path: string) {
  const normalized = path.replace(/[/\\]+$/, "");
  return normalized.split(/[\\/]/).filter(Boolean).at(-1) || normalized;
}
