# Ingestor App Evaluation Report

**Date:** 2026-06-27
**Scope:** Bugs, UI/UX, usability, performance, and code/architecture review of the Ingestor Tauri desktop application.
**Method:** CUA Driver MCP automation, direct API inspection, backend log/SQLite probing, and source-code review.

> Initial evaluation made no code changes. This file is now being maintained as the remediation log while fixes are implemented.

## 0. Remediation Status

**Last updated:** 2026-06-27

| Status | Area | Notes |
|---|---|---|
| Fixed | Capture submit accessibility | Local and web submit buttons expose explicit accessible labels and stable sizing. Verified in the running app. |
| Fixed | Source metadata placeholders | Source rows hide missing metadata and show a pending/indexing note instead of literal `Unknown` values. Verified in the running app. |
| Fixed | Settings Save state | Save enables for draft changes and disables after a successful save. Verified in the running app. |
| Fixed | Local snapshot ignores | Snapshot and discovery skip heavy/runtime folders including `target`, `.git`, `.venv`, IDE folders, and cache folders. Covered by tests. |
| Fixed | Duplicate/running local indexing | Backend rejects duplicate running jobs for a source and rejects exact duplicate local paths before snapshotting. Covered by tests and live API probes. |
| Fixed | Dev-only desktop controls | Startup, PATH, and Updates controls are hidden outside the installed Tauri bridge. Verified in the running app. |
| Fixed | `GET /api/sources/jobs` | Collection endpoint now returns jobs instead of `405`. Verified by live API probe. |
| Not reproduced | Tauri backend binary mismatch | Current packaging builds `ingestor-daemon.exe` and `ingestor.exe`; `lib.rs` resolves `ingestor-daemon.exe` from bundled `binaries`. No code change needed unless a future installer build disproves this. |
| Fixed | Background job exception logging | Worker-thread failures now emit traceback-bearing process logs in addition to job status/log updates. Covered by tests. |
| Fixed | Cancel running jobs | Running jobs can be cancelled through the API and Sources/Capture UI. Active workers stop cooperatively; stale jobs from prior backend processes finalize as `cancelled`. Covered by tests and live API/UI checks. |
| Fixed | Progress estimates | Jobs now expose structured progress fields. Local indexing shows exact scanned file totals and ETA; web indexing shows discovered page counts. Covered by tests and live API/UI checks. |
| Fixed | CSP tightening | `tauri.conf.json` now restricts default loading, Tauri IPC, local backend access, image sources, and local styles instead of disabling CSP entirely. |
| Fixed | Backend unavailable state | When the local API cannot be reached, the frontend shows a focused offline panel with the backend URL, desktop/dev startup guidance, and a retry action. Verified in the running browser UI. |
| Fixed | Settings dropdown labels | Dropdown options now expose concise accessible names while keeping longer descriptions as secondary visible text/tooltips. Verified in the running browser UI. |
| Partially fixed | Frontend service split | Frontend API calls moved out of `App.tsx` into `frontend/src/api.ts`; `App.tsx` still owns page state and can be split further later. |
| Fixed | Local source request contract | Backend local-source registration now accepts `paths` only and rejects the legacy singular `path` field. Covered by tests. |
| Fixed | Evaluation runtime cleanup | Removed the two evaluation sources, their jobs, and their local snapshot folders from the repo-local backend data. Verified by live API and filesystem checks. |

Verification for the latest remediation pass:

- `backend\.venv\Scripts\python.exe -m pytest tests`
- `backend\.venv\Scripts\python.exe -m compileall backend\app`
- `npm --prefix frontend run lint`
- `npm --prefix frontend run build`
- `npm --prefix frontend run tauri -- info`
- JSON parse check for `frontend/src-tauri/tauri.conf.json`
- Live API check: local job cancellation moved from `cancelling` to `cancelled`; completed local job reported `progress_current=3` and `progress_total=3`.
- Live browser check: Sources page rendered row-level progress, Cancel/Cancelling states, and cleared stuck cancellation controls after finalization.
- Live browser check: backend-offline panel rendered after stopping the daemon, Retry recovered after restarting the daemon, and Settings dropdown options exposed short accessible labels.
- Live API/filesystem check: `test-src-tauri` and `eval-test-frontend-src-tauri` sources are absent, job count is `0`, and their `backend/data/local` snapshot folders no longer exist.
- Live API check: singular `path` local-source registration payload now returns `422`; `paths` is the supported request field.

---

## 1. Bugs / Defects

| # | Issue | Evidence / Impact | Priority |
|---|-------|-------------------|----------|
| 1 | **Fixed.** Capture-page submit button is missing from the accessibility tree and appears visually unreachable. On the Local docs form, the "Index selected docs" / "Starting" button is not exposed as a normal clickable element in the UIA tree, preventing reliable keyboard or assistive-technology submission. Subsequent attempts to drive the form via UIA failed, and the backend had no record of a second job. | UIA snapshot shows only a generic "Button Starting" with no usable index. Direct form submission could not be triggered through accessibility or keyboard paths. Follow-up browser check confirmed explicit accessible labels. | High |
| 2 | **Fixed.** Source list renders placeholder metadata labels literally. Every source row displays `EMBEDDING Unknown INDEXED Unknown DURATION Unknown STRATEGY Unknown`, which is confusing and looks broken. | Visible on Sources page for both registered and indexing sources. Follow-up browser check confirmed no literal `Unknown` placeholders. | High |
| 3 | **Fixed.** Settings Save button is not properly disabled when no changes are pending. After changing retrieval mode and saving, the Save button remained focusable, encouraging duplicate saves. | Observed on Settings page after selecting "Full text" and clicking Save. Follow-up browser check confirmed Save disables after successful save. | Medium |
| 4 | **Not reproduced with current build scripts.** Tauri `mainBinaryName` (`ingestor-desktop`) and expected backend binary (`ingestor-daemon.exe`) do not match built artifacts (`ingestor.exe`). This makes the dev/packaged launch logic fragile and likely breaks the built-in daemon startup. | Current `build-packaged-binaries.mjs` builds `ingestor-daemon` for the backend and `ingestor` for the CLI. `lib.rs` resolves `ingestor-daemon.exe` from bundled `binaries`. | Medium |
| 5 | **Fixed.** Backend does not expose `GET /api/sources/jobs`. Calling it returns `405 Method Not Allowed`. The frontend uses `/api/sources` and `/api/sources/jobs/{job_id}`, so the collection endpoint is inconsistent with REST conventions. | Direct API call returned `405 Method Not Allowed`. Follow-up live API probe returned `200`. | Low |

---

## 2. UI / UX Improvements

| # | Issue | Recommendation |
|---|-------|----------------|
| 1 | **Fixed.** No visible progress bar or ETA during indexing. The Sources page only shows "Indexing" with a document/chunk counter. | Sources and Capture now render job progress bars. Local jobs show exact scanned file totals and ETA when possible; web jobs show discovered page counts. |
| 2 | **Fixed.** No way to cancel a running index job. Once started, users must wait or kill the backend process. | Sources and Capture now expose a cancel action. Backend jobs transition through `cancelling` and finalize as `cancelled`; stale jobs from previous backend processes can also be cleared. |
| 3 | **Fixed.** Search panel on Sources page is disabled with a static message. When a source is not queryable, the panel explains why but offers no link to view its progress. | Disabled search messaging now links users back to registry progress when the selected source has an active indexing job. |
| 4 | **Fixed.** Settings dropdown labels are verbose and duplicated. Each option repeats the category name ("Hybrid Combine full text...", "Full text Use SQLite FTS5..."). | Options now keep short accessible labels (`Hybrid`, `Full text`, `Embeddings`) while preserving descriptions as secondary visible text and tooltips. |
| 5 | **Fixed.** The "Check" update button gives no feedback about network/updater configuration. In a dev build it is unclear whether it does anything. | Updater section is hidden when the Tauri desktop bridge is unavailable. |
| 6 | **Fixed.** "Start with Windows" checkbox is shown in the dev build even though `startupSettings.supported` is false. | Desktop behavior section is hidden when the Tauri desktop bridge is unavailable. |

---

## 3. Usability Concerns

- **Partially fixed.** `frontend/src/desktop.ts` and `frontend/src-tauri/src/lib.rs` default to `http://127.0.0.1:8765`. The Tauri shell already auto-starts the bundled daemon in desktop builds. Browser/dev sessions now show a clear backend-unavailable state with the backend URL, startup guidance, and Retry instead of failing silently.
- **Fixed.** Local file picker does not warn about huge artifact directories. Selecting `frontend/src-tauri` copied the entire `target/` directory (debug and release build outputs) into the local source snapshot. The resulting index grew to more than 1,500 documents and 2,000 chunks, most of which were `.json` fingerprint/build files rather than documentation.
- **Fixed.** Default exclude/ignore patterns are insufficient. The snapshot ignore list ignores `node_modules`, `dist`, and `build`, but not `target/**`, `.git/**`, `.venv/**`, or IDE metadata. This causes unnecessary disk use and long index times.
- **No search-as-you-type or search from the Capture page.** Users must switch to Sources and select a source before searching.

---

## 4. Performance / Reliability Concerns

- **Fixed for same source.** Concurrent reindexing of the same folder is allowed. Starting a second index on `eval-test-frontend-src-tauri` while `test-src-tauri` was already running caused both jobs to run simultaneously. For large folders this can exhaust CPU/disk and create SQLite write contention.
- **Fixed for exact local path duplicates.** No deduplication of identical snapshots. Two sources pointing to the same physical folder (`frontend/src-tauri`) create two independent snapshots and two independent indexes, doubling storage.
- **Fixed.** Indexing jobs are cancellable through cooperative checks between local files and crawled pages. `_run_job` also logs traceback-bearing failures to the process logger.
- **Backend SQLite writes happen per-document.** For a 1,500-file local snapshot this is acceptable on SSD, but for larger docs folders or web crawls it could become a bottleneck.

---

## 5. Code / Architecture Observations

- **Partially fixed.** Frontend state management is concentrated in `App.tsx`. API wrappers now live in `frontend/src/api.ts`, but `App.tsx` still mixes routing, view state, and orchestration. A future pass can extract hooks by feature area.
- **Partially fixed.** TypeScript `API_BASE_URL` fallback chain is correct (`window.ingestorDesktop?.backendUrl ?? import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765'`). The hard-coded local default remains intentional, but unreachable backend states are now surfaced explicitly in the UI.
- **Fixed.** CSP is set to `null` in `tauri.conf.json`. This disables Content-Security Policy in the built app. It should be tightened before shipping, at minimum to `default-src 'self'; connect-src 'self' http://127.0.0.1:8765`.
- **Fixed.** Backend `LocalSourceRequest` supports both `paths` and a legacy `path` field. The model now accepts `paths` only and forbids extra fields, so singular `path` submissions fail validation instead of being treated as a compatibility path.
- **Fixed.** `index_source` failures caught by `_run_job` are now emitted through the process logger with a traceback, while the existing job log/status path remains intact.

---

## 6. Recommended Fixes by Priority

### High
1. ~~Make the Local docs form submit button visible and accessible (fix CSS/layout and ensure it is in the tab order and UIA tree).~~ Fixed.
2. ~~Populate real metadata in the Sources list or remove the placeholder labels.~~ Fixed.
3. ~~Harden the default ignore/exclude patterns to skip `target/**`, `.git/**`, `.venv/**`, IDE dirs, and lockfiles.~~ Fixed.
4. ~~Add a cancel action for running index jobs. Starting a new job on the same source is now blocked.~~ Fixed.

### Medium
5. ~~Have the Tauri shell auto-start the daemon or show a clear "daemon not running" state with a start button.~~ Partially fixed: desktop builds already auto-start the daemon; browser/dev mode now shows a backend-unavailable state with Retry and startup guidance.
6. ~~Align binary names (`mainBinaryName`, `ingestor.exe`, `ingestor-daemon.exe`) and document the packaged layout.~~ Current build scripts already produce the expected backend and CLI binaries; no mismatch reproduced.
7. ~~Hide/disable Desktop-only sections (startup, PATH, updates) when `window.ingestorDesktop` is unavailable.~~ Fixed.
8. ~~Add a duplicate-source warning when the user selects a path that is already indexed.~~ Fixed for exact local path duplicates in the UI and backend.

### Low
9. ~~Add `GET /api/sources/jobs` for consistency or remove references to it.~~ Fixed.
10. ~~Tighten the Tauri CSP before release.~~ Fixed.
11. Partially fixed: API calls moved from `App.tsx` into `frontend/src/api.ts`. Remaining hook/page-state extraction can be handled in a later pass.
12. Consider deduplicating local snapshots across sources.

---

## Note on Runtime State

Fixed. The evaluation sources (`test-src-tauri` and `eval-test-frontend-src-tauri`), their jobs, and their local snapshot folders under `backend/data/local/` have been removed from the repo-local backend data.
