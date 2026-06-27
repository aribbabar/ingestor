# Ingestor App Evaluation Report

**Date:** 2026-06-27
**Scope:** Bugs, UI/UX, usability, performance, and code/architecture review of the Ingestor Tauri desktop application.
**Method:** CUA Driver MCP automation, direct API inspection, backend log/SQLite probing, and source-code review.

> No code changes were made during this evaluation. Findings are documented below with recommended fixes and prioritization.

---

## 1. Bugs / Defects

| # | Issue | Evidence / Impact | Priority |
|---|-------|-------------------|----------|
| 1 | **Capture-page submit button is missing from the accessibility tree and appears visually unreachable.** On the Local docs form, the "Index selected docs" / "Starting" button is not exposed as a normal clickable element in the UIA tree, preventing reliable keyboard or assistive-technology submission. Subsequent attempts to drive the form via UIA failed, and the backend had no record of a second job. | UIA snapshot shows only a generic "Button Starting" with no usable index. Direct form submission could not be triggered through accessibility or keyboard paths. | High |
| 2 | **Source list renders placeholder metadata labels literally.** Every source row displays `EMBEDDING Unknown INDEXED Unknown DURATION Unknown STRATEGY Unknown`, which is confusing and looks broken. | Visible on Sources page for both registered and indexing sources. | High |
| 3 | **Settings Save button is not properly disabled when no changes are pending.** After changing retrieval mode and saving, the Save button remained focusable, encouraging duplicate saves. | Observed on Settings page after selecting "Full text" and clicking Save. | Medium |
| 4 | **Tauri `mainBinaryName` (`ingestor-desktop`) and expected backend binary (`ingestor-daemon.exe`) do not match built artifacts (`ingestor.exe`).** This makes the dev/packaged launch logic fragile and likely breaks the built-in daemon startup. | `tauri.conf.json` + `lib.rs` reference `ingestor-daemon`. The debug binary produced is `ingestor.exe`. | Medium |
| 5 | **Backend does not expose `GET /api/sources/jobs`.** Calling it returns `405 Method Not Allowed`. The frontend uses `/api/sources` and `/api/sources/jobs/{job_id}`, so the collection endpoint is inconsistent with REST conventions. | Direct API call returned `405 Method Not Allowed`. | Low |

---

## 2. UI / UX Improvements

| # | Issue | Recommendation |
|---|-------|----------------|
| 1 | **No visible progress bar or ETA during indexing.** The Sources page only shows "Indexing" with a document/chunk counter. | Add a linear progress bar and an estimated time remaining, or at least "X of Y files scanned." |
| 2 | **No way to cancel a running index job.** Once started, users must wait or kill the backend process. | Add a "Cancel indexing" action that sets the job status to `cancelled` and stops the worker thread safely. |
| 3 | **Search panel on Sources page is disabled with a static message.** When a source is not queryable, the panel explains why but offers no link to view its progress. | Link the disabled message to the selected source row or its progress details. |
| 4 | **Settings dropdown labels are verbose and duplicated.** Each option repeats the category name ("Hybrid Combine full text...", "Full text Use SQLite FTS5..."). | Use short labels with tooltips or secondary description text. |
| 5 | **The "Check" update button gives no feedback about network/updater configuration.** In a dev build it is unclear whether it does anything. | Disable or hide the updater section when not running an installed/updatable build. |
| 6 | **"Start with Windows" checkbox is shown in the dev build even though `startupSettings.supported` is false.** | Gate the section on `window.ingestorDesktop` and `supported`. Hide or clearly disable it when unavailable. |

---

## 3. Usability Concerns

- **Hard-coded backend URL.** `frontend/src/desktop.ts` and `frontend/src-tauri/src/lib.rs` default to `http://127.0.0.1:8765`. `npm run dev` fails to connect if the daemon is not already running, requiring manual backend startup before the UI works. The Tauri shell should either auto-start the daemon or surface a "start daemon" prompt.
- **Local file picker does not warn about huge artifact directories.** Selecting `frontend/src-tauri` copied the entire `target/` directory (debug and release build outputs) into the local source snapshot. The resulting index grew to more than 1,500 documents and 2,000 chunks, most of which were `.json` fingerprint/build files rather than documentation.
- **Default exclude/ignore patterns are insufficient.** The snapshot ignore list ignores `node_modules`, `dist`, and `build`, but not `target/**`, `.git/**`, `.venv/**`, or IDE metadata. This causes unnecessary disk use and long index times.
- **No search-as-you-type or search from the Capture page.** Users must switch to Sources and select a source before searching.

---

## 4. Performance / Reliability Concerns

- **Concurrent reindexing of the same folder is allowed.** Starting a second index on `eval-test-frontend-src-tauri` while `test-src-tauri` was already running caused both jobs to run simultaneously. For large folders this can exhaust CPU/disk and create SQLite write contention.
- **No deduplication of identical snapshots.** Two sources pointing to the same physical folder (`frontend/src-tauri`) create two independent snapshots and two independent indexes, doubling storage.
- **Indexing thread is unbounded and not cancellable.** `_run_job` swallows all exceptions silently (`except Exception: return`), so failures are only visible in the job log/status field.
- **Backend SQLite writes happen per-document.** For a 1,500-file local snapshot this is acceptable on SSD, but for larger docs folders or web crawls it could become a bottleneck.

---

## 5. Code / Architecture Observations

- **Frontend state management is concentrated in `App.tsx` (987 lines).** It mixes API calls, business logic, and UI state. Consider moving API wrappers (`refreshSources`, `saveSettings`, etc.) into a small service layer and keeping `App.tsx` as wiring only.
- **TypeScript `API_BASE_URL` fallback chain is correct** (`window.ingestorDesktop?.backendUrl ?? import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765'`), but the hard-coded default masks environment-specific setups.
- **CSP is set to `null` in `tauri.conf.json`.** This disables Content-Security Policy in the built app. It should be tightened before shipping, at minimum to `default-src 'self'; connect-src 'self' http://127.0.0.1:8765`.
- **Backend `LocalSourceRequest` supports both `paths` and a legacy `path` field.** The API accepts `paths` while the model also exposes `path`. This should be deprecated or documented.
- **`index_source` swallows exceptions in `_run_job`.** Errors should be propagated to the job log and optionally to Sentry or stderr for easier debugging.

---

## 6. Recommended Fixes by Priority

### High
1. Make the Local docs form submit button visible and accessible (fix CSS/layout and ensure it is in the tab order and UIA tree).
2. Populate real metadata in the Sources list or remove the placeholder labels.
3. Harden the default ignore/exclude patterns to skip `target/**`, `.git/**`, `.venv/**`, IDE dirs, and lockfiles.
4. Add a cancel action for running index jobs and prevent starting a new job on a source that is already indexing.

### Medium
5. Have the Tauri shell auto-start the daemon or show a clear "daemon not running" state with a start button.
6. Align binary names (`mainBinaryName`, `ingestor.exe`, `ingestor-daemon.exe`) and document the packaged layout.
7. Hide/disable Desktop-only sections (startup, PATH, updates) when `window.ingestorDesktop` is unavailable.
8. Add a duplicate-source warning when the user selects a path that is already indexed.

### Low
9. Add `GET /api/sources/jobs` for consistency or remove references to it.
10. Tighten the Tauri CSP before release.
11. Refactor `App.tsx` into smaller service/hook modules.
12. Consider deduplicating local snapshots across sources.

---

## Note on Runtime State

The evaluation left two local sources registered (`test-src-tauri` and `eval-test-frontend-src-tauri`) and a long-running index job in the backend SQLite under `backend/data/`. Both index snapshots include the full `frontend/src-tauri/target` tree, so they consume noticeable disk space. Clean up these test sources if they are no longer needed.
