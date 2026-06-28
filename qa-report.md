# Ingestor Desktop App - QA Evaluation Report

**Date:** June 27, 2026  
**App:** Ingestor (Tauri desktop app + Python FastAPI backend)  
**Environment:** Windows 10, Tauri dev mode (Vite port 1420, daemon port 8765)  
**Testing channels:** `computer_use` (Tauri WebView2 AX tree) + `browser_*` (Vite dev server)  

---

## Implementation update - June 27, 2026

Addressed in this pass:

- **BUG-1:** Fixed local reindexing when the saved snapshot directory is missing. The backend now validates or recreates the local snapshot from `original_paths` before clearing indexed documents, and raises a clear pre-clear error if neither snapshot nor originals are available.
- **UX-3:** Added a concise accessible name to source selection buttons: `Select {source.name}`.
- **BUG-4 / BUG-5 from the fresh QA report:** Search limit now selects on focus and clamps entered values to the supported `1` to `50` range.
- **CODE-7:** Fixed the async `onBackendStatus` cleanup race in the Tauri desktop bridge with a cancellation guard.

Additional fixes from the follow-up pass:

- **BUG-2 / USA-1:** Settings Reset now stays visibly staged, exposes a Cancel reset action, and opens a confirmation dialog before applying defaults. The dialog calls out indexed sources that will need reindexing.
- **UX-1:** The Settings Save button now uses native `disabled` when saving is unavailable.
- **UX-7 / CODE-6:** Added a route-level React Error Boundary with a Reload recovery action.

Additional fixes from this pass:

- **BUG-3:** Reindexing the currently selected source no longer clears existing search results. The Sources page keeps the previous results visible and shows a notice that they may be outdated until indexing finishes.
- **UX-2:** `ConfirmDialog` now names the dialog directly with `aria-label={title}` while preserving the visible heading.

Cleanup fixes from this pass:

- **CODE-1:** Extracted duplicated `jobProgress` / `formatEta` logic into `frontend/src/utils/jobProgress.ts`.
- **CODE-2:** Deleted unused `frontend/src/App.css`; no `frontend/src` imports referenced it.

Search-state fixes from this pass:

- **UX-5 / USA-2:** Search now distinguishes the initial empty state, in-flight searches, and completed zero-match searches. Previous results stay visible while a new search is running.

Capture layout fixes from this pass:

- **UX-6:** Moved the web indexing submit action above Advanced crawl options so the primary action stays reachable when the details panel is expanded.

Local reindex correctness fixes from this pass:

- **CODE-8 from the fresh QA report:** Local reindex now refreshes the stored snapshot from `original_paths` when the original files are available, so changed local docs are indexed instead of reusing stale snapshot content.

Source-list polish fixes from this pass:

- **UX-8 from the fresh QA report:** Source names and paths now ellipsize within the source selector, and focused source rows show a clear accent focus ring.

Header and recent-source fixes from this pass:

- **USA-7 from the fresh QA report:** The backend status pill now renders capitalized status text, so assistive output reports `Online`, `Checking`, or `Offline` instead of lowercase raw state.
- **UX-9 from the fresh QA report:** Recent source rows now expose an explicit `Open {source.name} in Sources` action with a visible Open affordance.

Accessibility text and settings-load fixes from this pass:

- **UX-4:** Reworked the reported split-text locations with coherent strings or `aria-label`s: Capture index counts, ready-source counts, search source sizes, Settings stale/indexing/error text, Sources stale warnings, and search result labels.
- **PERF-2:** `loadSettingsBundle()` no longer waits on `/api/health`; Settings now loads from `/api/settings` directly while optional Ollama and skill checks remain separately timeout-protected.

Crawl dependency and local-hashing fixes from this pass:

- **CODE-9 from the fresh QA report:** Crawl4AI dependency import failures now surface as a clean `RuntimeError` with the missing module detail instead of leaking raw import tracebacks from crawl execution.
- **PERF-3:** Sources search now shows a local-hashing notice explaining that vector-only semantic matches are limited until Ollama embeddings are configured. Punctuation-only vector queries also skip the vector branch instead of querying with a zero vector.

Polling and Capture search-state fixes from this pass:

- **PERF-1:** Active job polling now adapts from the fast 1.5 second cadence to a slower 4.5 second cadence after repeated unchanged job progress, and keeps refreshing briefly after a selected job finishes.
- **CODE-7 from the fresh QA report:** Capture now surfaces failed or stale sources that cannot be searched, with an Open Sources action instead of silently hiding them from the searchable list.

Log retention and API documentation fixes from this pass:

- **USA-5 from the fresh QA report:** Capture logs are now cached by job id and rehydrated from the selected source's latest job, so navigating between views or switching sources does not replace the visible log context with another job's logs.
- **CODE-4 / CODE-3 from the fresh QA report:** The duplicate delete-source surface is now documented: `DELETE /api/sources/{source_id}` is the canonical CLI/REST endpoint, while `POST /api/sources/{source_id}/delete` is marked deprecated for desktop compatibility.

Verification run after the fixes:

| Check | Result |
|---|---|
| `backend\.venv\Scripts\python.exe -m pytest tests\test_ingestion_and_search.py -k missing_local_snapshot` | Pass |
| `backend\.venv\Scripts\python.exe -m compileall backend\app` | Pass |
| `backend\.venv\Scripts\python.exe -m pytest tests\test_ingestion_and_search.py -k "missing_local_snapshot or refreshes_snapshot"` | Pass |
| `backend\.venv\Scripts\python.exe -m pytest tests\test_ingestion_and_search.py -k crawl4ai_dependency_import_errors` | Pass |
| `backend\.venv\Scripts\python.exe -m pytest tests\test_ingestion_and_search.py -k vector_search_skips_queries_without_tokens` | Pass |
| `backend\.venv\Scripts\python.exe -m pytest tests` | Pass (35 tests) |
| `npm --prefix frontend run lint` | Pass |
| `npm --prefix frontend run build` | Pass |
| Browser verification at `http://127.0.0.1:1420/#/settings` | Pass: Reset banner, confirmation dialog, cancel path, and Settings render verified |
| Browser verification at `http://127.0.0.1:1420/#/sources` | Pass: search results stayed visible during Reindex, outdated-results notice appeared, delete dialog was named and cancelled safely |
| `rg -n "App\\.css|function jobProgress|function formatEta" frontend\src` | Pass: only shared `frontend/src/utils/jobProgress.ts` defines progress helpers |
| Browser verification at `http://127.0.0.1:1420/#/sources` search states | Pass: initial "No search has been run yet" and completed "No matching results" states verified |
| Browser verification at `http://127.0.0.1:1420/#/capture` web tab | Pass: Index website action appears before expanded Advanced crawl options and the advanced fields remain visible below it |
| Browser verification at `http://127.0.0.1:1420/#/sources` at 980px viewport | Pass: source location uses hidden overflow/ellipsis/nowrap and focused source row shows an accent focus ring |
| Browser verification at `http://127.0.0.1:1420/#/capture` recent sources | Pass: header status is exposed as `Online`; Recent source action reads `Open test-docs in Sources` and navigates to the selected source on `/sources` |
| Source inspection for UX-4 reported locations | Pass: reported text fragments now use coherent strings or explicit `aria-label`s |
| `rg -n "/api/health|HealthResponse" frontend\src\api.ts` | Pass: no health dependency remains in `loadSettingsBundle()` |
| Browser verification at `http://localhost:1420/#/sources` | Pass: local-hashing search-quality notice rendered |
| Source inspection for `frontend\src\hooks\useSourcesController.ts` | Pass: active job polling backs off after unchanged progress and keeps a short post-job refresh window |
| Browser verification at `http://127.0.0.1:1420/#/capture` with a temporary failed source | Pass: Capture showed the blocked-source hint and Open Sources action; temporary QA source was removed |
| Source inspection for `frontend\src\hooks\useSourcesController.ts` job log cache | Pass: logs are keyed by job id and active logs derive from the selected source's latest job |
| Source inspection for `backend\app\api\routes.py` delete endpoints | Pass: DELETE is documented as canonical; POST compatibility route is deprecated |
| Browser verification at `http://127.0.0.1:1420/#/capture` after navigating away and back | Pass: Capture progress/log context remained rendered after returning from Sources |
| In-process FastAPI OpenAPI schema check | Pass: DELETE is documented as canonical; POST compatibility route is deprecated |

Still open from this report: the remaining lower-priority cleanup/performance items, excluding USA-5, PERF-1, PERF-2, PERF-3, CODE-3, CODE-7, and CODE-9 from the fresh report.

---

## 1. Bugs and Defects

### BUG-1: Reindex fails after settings reset because snapshot directory is lost [Critical]

**Severity:** Critical  
**Category:** Functional / Reliability  

**Reproduction:**
1. Have an indexed local source (e.g., chakra-ui with 252 docs, 2799 chunks)
2. Go to Settings > Click "Reset" > Click "Save" (resets embedding model to local-hashing)
3. Go to Sources page > The source now shows "Reindex Required" badge
4. Click "Reindex" on the source
5. **Result:** Source status changes to "Failed" with error: `Path does not exist: C:\Users\aribb\AppData\Roaming\com.arib.ingestor\data\local\ingest-20260626-224755-77d86cb8-chakra-ui\content`
6. The document and chunk counts drop to 0

**Root cause:** `index_local_source_incrementally()` in `backend/app/sources/service.py:297` reads from `local_source_paths(source)` which returns the `snapshot_paths` from `source.metadata`. These snapshot paths were created during `register_local_source()` but the snapshot directory no longer exists (it was empty/cleaned at `C:/Users/aribb/AppData/Roaming/com.arib.ingestor/data/local/`). The reindex code does not recreate the snapshot from the original paths—it blindly uses the stale metadata. There is no fallback to `original_paths` when `snapshot_paths` are missing.

**Expected:** Reindex should either (a) re-snapshot from `original_paths` if `snapshot_paths` are missing, or (b) the UI should prevent reindex when the snapshot is unavailable and show a helpful message directing the user to re-add the source.

---

### BUG-2: Settings "Reset" silently changes embedding model, making all indexed sources stale [High]

**Severity:** High  
**Category:** UX / Data Integrity  

**Reproduction:**
1. Have an indexed source using `ollama:embeddinggemma:latest`
2. Go to Settings > Click "Reset" (draft becomes pending, embedding model placeholder changes to "Built-in local hashing")
3. Click "Save"
4. "Settings saved" message appears
5. Warning appears: "1 indexed source must be re-indexed before search"
6. **Result:** All previously indexed sources are now stale and unsearchable. The user may not realize that clicking "Reset" then "Save" changes the active embedding model.

**Expected:** The Reset button's behavior is confusing—it stages a full reset as a draft rather than immediately resetting. The consequence (invalidating all existing indexes) should be more prominently communicated, ideally with a confirmation dialog before saving a reset that affects existing sources.

---

### BUG-3: Orphaned dev processes hold ports after app closure [High]

**Severity:** High  
**Category:** Reliability / Stability  

**Reproduction:**
1. Run `npm run dev` (starts Vite on 1420, daemon on 8765, and the Tauri window)
2. Close the Tauri window
3. Run `netstat -ano | grep -E '1420|8765'`
4. **Result:** Both ports still have LISTENING processes (Vite dev server and Python daemon survive the Tauri window closure)
5. Next `npm run dev` fails because ports are occupied

**Root cause:** The Tauri shell's `beforeDevCommand` starts Vite and the Python daemon as child processes, but they are not always terminated when the Tauri window closes, especially after a crash or forced quit.

**Expected:** The Tauri shell should ensure child processes are terminated when the app exits, or the app should detect port conflicts on startup and offer to kill stale processes.

---

## 2. UI/UX Improvements

### UX-1: Disabled buttons invisible to accessibility tools [High]

**Severity:** High  
**Category:** Accessibility  

**Observation:** The Save button on the Settings page uses `aria-disabled="true"` and `data-disabled` attribute with `disabled={isSavingSettings}` when no changes have been made. When the button is in this disabled-draft state (no changes), it is completely absent from the Tauri WebView2 AX tree. A screen reader user would not know the Save button exists at all until they make a change.

**Affected buttons:** Save (Settings page), Search (Sources page when no source is selected or source is not queryable)

**Recommendation:** Use `disabled` attribute on the `<button>` element (not just `aria-disabled`) so the button remains in the accessibility tree with a disabled state, or add `aria-disabled="true"` without removing the element from the tab order. Ensure disabled buttons are still visible to assistive technology.

---

### UX-2: ConfirmDialog title not exposed in AX tree [Medium]

**Severity:** Medium  
**Category:** Accessibility  

**Observation:** When the "Delete source?" confirmation dialog opens, the dialog title (`<h2>`) is not present in the Tauri WebView2 AX tree. The dialog's `aria-labelledby` points to the title's ID, but the title text node is missing from the accessibility tree. Only the description text, Cancel, and Delete buttons appear.

**Recommendation:** Verify the dialog title is properly rendered and accessible. This may be a WebView2 AX tree omission, but the title should be verified using browser tools as well.

---

### UX-3: Source selection button has excessively long accessible name [Medium]

**Severity:** Medium  
**Category:** Accessibility  

**Observation:** On the Sources page, each source is rendered as a `<button>` whose accessible name includes the source name, full file path(s), embedding model, indexed date, duration, and strategy. Example:

> `test-docs C:\Users\aribb\AppData\Local\Temp\ingestor-test-docs EMBEDDING local-hashing-256 INDEXED Jun 27, 2026, 6:16 PM DURATION 53 ms STRATEGY batch / 32`

This is extremely verbose for screen reader users. All of this information is also available in the metadata `<dl>` below the button.

**Recommendation:** Set an `aria-label` on the source button with just the source name (e.g., `aria-label="Select test-docs"`), or use `aria-labelledby` to reference only the source name element.

---

### UX-4: Split text nodes throughout the UI [Low]

**Severity:** Low  
**Category:** Accessibility  

**Observation:** JSX expressions like `{count} source{count === 1 ? '' : 's'}` and `Effective batch size: {size}. Default: {strategy} / {batch}.` produce multiple adjacent text nodes that appear as separate AX tree elements. Screen readers may read these awkwardly (e.g., "3" pause "docs" pause "8" pause "chunks").

**Affected locations:**
- Capture page: doc/chunk counts ("3" / "docs" / "8" / "chunks")
- Settings page: "Effective batch size: 32. Default: batch / 32." (8 separate text nodes)
- Settings page: error message "Batch size must be a whole number from 1 to 256." (5 text nodes)
- Sources page: stale source warning ("1" / " indexed source" / " must be re-indexed...")
- Search results: "RESULT " / "1" (with trailing space)

**Recommendation:** Use template literals or `aria-label` on container elements to provide a single coherent text string for screen readers.

---

### UX-5: No loading/spinner indicator for search [Low]

**Severity:** Low  
**Category:** UX / Feedback  

**Observation:** When executing a search, the Search button text changes to "Searching" but there is no spinner or visual progress indicator. For local-hashing embeddings the search is near-instant, but with Ollama embeddings the search could take several seconds. During this time, the search results section shows "No results yet." (the previous results are cleared with `setSearchOutput(null)` before the request).

**Recommendation:** Show a spinner or skeleton state during search, and keep the previous results visible until new results arrive (or show a distinct "Searching..." state that replaces the empty state).

---

### UX-6: Advanced crawl options pushes submit button below fold [Medium]

**Severity:** Medium  
**Category:** Layout / UX  

**Observation:** When the "Advanced crawl options" `<details>` element is expanded on the Capture page Web docs tab, the page height increases significantly (from ~1205px to ~1655px in a 820px viewport). The submit button ("Index website documentation") is pushed below the fold and is no longer visible without scrolling.

**Recommendation:** Consider a sticky submit button bar, or move the advanced options into a modal/popover, or place the submit button above the advanced options.

---

### UX-7: No error boundary for route components [Medium]

**Severity:** Medium  
**Category:** Reliability  

**Observation:** The `App.tsx` component renders `<Routes>` with three page components (CapturePage, SourcesPage, SettingsPage) but has no React Error Boundary wrapping them. If any page component throws during render (e.g., from a type mismatch in source metadata), the entire app would crash to a white screen with no recovery path.

**Recommendation:** Add an Error Boundary component wrapping each route, showing a friendly error message with a "Reload" button.

---

## 3. Usability Concerns

### USA-1: Settings "Reset" button behavior is ambiguous [Medium]

The "Reset" button on the Settings page stages a full settings reset as a draft—it doesn't immediately reset. The user must then click "Save" to apply. This is different from typical "Reset to defaults" patterns where the reset is immediate or clearly staged with a visual indicator. There is no visual indication that a reset is pending other than the field values changing to defaults and the Save button becoming enabled.

**Recommendation:** Add a "Reset pending" indicator or change the button to "Reset to defaults" with a confirmation dialog that clearly states what will be reset.

---

### USA-2: No feedback when search returns zero results for empty query [Low]

The search form has `required` on the query input, so submitting an empty query is blocked by native validation. However, the backend `search_chunks` returns an empty list for empty queries (line 53-54 in search.py). The UI shows "No results yet." for both "never searched" and "search returned zero results" states, which is ambiguous.

**Recommendation:** Distinguish between "No search has been performed" and "Search returned no matching results."

---

### USA-3: No way to cancel a web crawl from the Capture page [Low]

The Capture page shows indexing progress with a "Cancel indexing" button, but this is only visible when `latestJob` is active and `selectedSource` is set. For web sources, the crawl may take a long time and the user may want to cancel from the Capture page. Currently, the user must navigate to the Sources page to cancel.

---

### USA-4: No keyboard shortcut for search [Low]

The search form requires clicking the Search button. Pressing Enter in the query field does submit the form (native `<form onSubmit>` behavior), but there's no visible indication that this is possible.

---

## 4. Performance and Reliability Concerns

### PERF-1: Fixed-interval polling with no backoff [Medium]

**File:** `frontend/src/hooks/useSourcesController.ts:84-91`

```typescript
useEffect(() => {
    if (!latestJob || !isActiveJob(latestJob)) return
    const timer = window.setInterval(() => {
      void refreshSources()
      void refreshJob(latestJob.id)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [latestJob, refreshJob, refreshSources])
```

The polling interval is a fixed 1500ms with no backoff. For long-running indexing jobs (e.g., crawling a large website), this creates unnecessary load. Additionally, polling stops entirely after job completion—there's no mechanism to detect externally-triggered changes (e.g., a reindex started from the CLI).

**Recommendation:** Use exponential backoff or adaptive polling based on job status. Consider WebSocket or SSE for real-time updates instead of polling.

---

### PERF-2: `loadSettingsBundle` uses `Promise.all` that can block on slow Ollama check [Medium]

**File:** `frontend/src/api.ts:27-32`

```typescript
export async function loadSettingsBundle() {
  const [health, settings] = await Promise.all([
    requestJson<HealthResponse>('/api/health'),
    requestJson<SettingsResponse>('/api/settings'),
  ])
  return { health, settings }
}
```

The settings bundle load includes health and settings endpoints. If the health endpoint is slow (e.g., because it calls `get_embedding_config()` which may query Ollama), the entire settings load is blocked. The `refreshSettings` hook does fire `refreshOllamaModels` and `refreshSkillTargets` separately with timeouts, but the core `loadSettingsBundle` has no timeout.

**Recommendation:** Add a timeout to the `loadSettingsBundle` request, or split the health and settings requests so they don't block each other.

---

### PERF-3: Local hashing embeddings produce low-discrimination vector scores [Low]

**Observation:** Vector search with local-hashing-256 embeddings produces scores in a very narrow range (0.414-0.533 for 8 chunks). The hybrid RRF score is dominated by keyword scores. This means the "vector" search mode provides little semantic value when Ollama is not available.

This is expected behavior (local hashing is a fallback), but users may not understand why vector search results are poor without Ollama.

**Recommendation:** Show a notice in the Settings page or search results when local hashing is active, explaining that semantic search quality is limited.

---

## 5. Code Quality and Architectural Observations

### CODE-1: Duplicated `jobProgress` and `formatEta` functions [Medium]

**Files:** `CapturePage.tsx:532-560` and `SourcesPage.tsx:330-360`

Both files define identical `jobProgress()` and `formatEta()` functions. These should be extracted to a shared utility module (e.g., `utils/jobProgress.ts`).

---

### CODE-2: Dead CSS file `App.css` [Low]

**File:** `frontend/src/App.css` (463 lines)

This file is not imported anywhere in the codebase. It contains classes like `.workspace`, `.capture-panel`, `.context-panel`, `.segmented`, `.searchbar`, `.result-item` that don't correspond to any current components. It appears to be a legacy stylesheet from an earlier layout.

**Recommendation:** Delete `App.css` or migrate any still-relevant styles to the appropriate CSS modules.

---

### CODE-3: tkinter dependency in backend file picker [Medium]

**File:** `backend/app/api/folders.py`

The file/folder picker endpoints use `tkinter` (`Tk()`, `filedialog`) to show native dialogs. This is fragile in service contexts:
- tkinter requires a display server (won't work in headless/SSH sessions)
- Creating a `Tk()` instance in a FastAPI request handler is not thread-safe
- The `Tk()` instance is created and destroyed per request, which is slow

The Tauri desktop bridge (`desktop.ts`) already provides `pickFolder()` and `pickFiles()` via Tauri's native dialog plugin, which is the preferred path. The tkinter endpoints are a fallback for non-desktop (browser) access.

**Recommendation:** Document the tkinter endpoints as browser-only fallbacks. Consider using a more robust dialog library or removing the endpoints if browser access is not a supported use case.

---

### CODE-4: Redundant delete source endpoints [Low]

**File:** `backend/app/api/routes.py:241-252`

Both `DELETE /api/sources/{source_id}` and `POST /api/sources/{source_id}/delete` exist and call the same `delete_source()` function. The frontend uses the POST variant, while the CLI uses the DELETE variant.

**Recommendation:** Addressed by documenting DELETE as the canonical CLI/REST endpoint and marking the POST compatibility endpoint as deprecated.

---

### CODE-5: `sourcePendingDelete` state in `useSourcesController` is not cleared on error [Low]

**File:** `frontend/src/hooks/useSourcesController.ts:195-215`

In `deletePendingSource()`, if `deleteSourceRequest()` throws, `setSourcePendingDelete(null)` is only called in the success path (line 205). On error, the dialog stays open but the `isConfirming` state is reset in the `finally` block. This means the dialog stays open with the error message, which may be intentional (allowing retry) but could also be confusing.

---

### CODE-6: No React Error Boundary [Medium]

**File:** `frontend/src/App.tsx`

The app has no `<ErrorBoundary>` component wrapping the route components. An unhandled exception in any page component would crash the entire app to a white screen.

---

### CODE-7: `onBackendStatus` listener may not clean up properly [Low]

**File:** `frontend/src/desktop.ts:67-76`

```typescript
onBackendStatus: (callback) => {
  let unlisten: (() => void) | null = null
  void listen<BackendStatus>('backend-status', (event) => callback(event.payload)).then((handler) => {
    unlisten = handler
  })
  return () => {
    unlisten?.()
  }
},
```

The `listen()` call is async and `unlisten` may still be `null` when the cleanup function is called (if the component unmounts before the listen promise resolves). In that case, the event listener is never cleaned up.

**Recommendation:** Use a `cancelled` flag:
```typescript
let cancelled = false
let unlisten: (() => void) | null = null
void listen<BackendStatus>(...).then((handler) => {
  if (cancelled) handler()
  else unlisten = handler
})
return () => { cancelled = true; unlisten?.() }
```

---

## 6. Testing Limitations

- **Native file/folder pickers** could not be tested via `computer_use` as they are OS-level dialogs. The backend tkinter-based pickers were not exercised. Test data was seeded via the backend API.
- **Scrolling in WebView2** did not work via `computer_use(action="scroll")`. The Vite dev server + `browser_*` tools were used as a complementary testing channel to verify below-fold content. Real users with a mouse can scroll normally.
- **Ollama-backed search** was not tested because the settings reset changed the embedding model to local-hashing. The Ollama embedding workflow was verified via the Settings page UI (model selection dropdown, Ollama status messages).
- **Web source crawling** was not tested end-to-end as it requires Crawl4AI and a live URL, which would take significant time. The form validation was tested.
- **Tauri desktop bridge features** (startup settings, CLI path management, update checks) were visible in the Settings page but not fully exercised, as they require the installed app (not dev mode).

---

## 7. Recommended Fixes and Prioritization

### Critical

| ID | Issue | Action |
|---|---|---|
| BUG-1 | Reindex fails when snapshot directory is lost | Re-snapshot from `original_paths` when `snapshot_paths` are missing, or prevent reindex and show a helpful error |

### High

| ID | Issue | Action |
|---|---|---|
| BUG-2 | Settings reset silently invalidates all indexes | Add confirmation dialog before saving a reset that affects existing sources |
| BUG-3 | Orphaned processes hold ports | Ensure child processes are terminated on app exit; detect port conflicts on startup |
| UX-1 | Disabled buttons invisible to accessibility | Use native `disabled` attribute; keep buttons in AX tree |
| CODE-6 | No React Error Boundary | Add Error Boundary wrapping route components |

### Medium

| ID | Issue | Action |
|---|---|---|
| UX-2 | ConfirmDialog title missing from AX tree | Verify dialog title rendering; may be WebView2 AX omission |
| UX-3 | Source button has excessively long accessible name | Set `aria-label` with just the source name |
| UX-6 | Advanced options push submit button below fold | Sticky submit bar or restructure layout |
| USA-1 | Ambiguous "Reset" button behavior | Add "Reset pending" indicator or confirmation dialog |
| PERF-1 | Fixed-interval polling with no backoff | Addressed: adaptive polling backs off after unchanged progress and keeps a short post-job refresh window |
| PERF-2 | `loadSettingsBundle` blocks on slow endpoints | Add timeout or split requests |
| CODE-1 | Duplicated `jobProgress`/`formatEta` functions | Extract to shared utility module |
| CODE-3 | tkinter dependency in file picker | Document as browser-only fallback; consider alternatives |
| CODE-7 | `onBackendStatus` cleanup race condition | Addressed: cancellation guard added |

### Low

| ID | Issue | Action |
|---|---|---|
| UX-4 | Split text nodes throughout UI | Use template literals or `aria-label` on containers |
| UX-5 | No spinner during search | Add loading state for search results |
| USA-2 | Ambiguous "No results yet" state | Distinguish "never searched" from "zero results" |
| USA-3 | No cancel from Capture page for web crawls | Add cancel button in Capture progress section |
| USA-4 | No keyboard shortcut indication for search | Add hint text or Enter key affordance |
| PERF-3 | Low vector score discrimination with local hashing | Addressed: notice added when local hashing is active |
| CODE-2 | Dead CSS file `App.css` | Delete or migrate relevant styles |
| CODE-4 | Redundant delete source endpoints | Addressed: DELETE is documented as canonical for CLI/REST; POST compatibility endpoint is deprecated |
| CODE-5 | `sourcePendingDelete` not cleared on error | Review dialog lifecycle on error |

---

## 8. Build and Test Verification

| Check | Result |
|---|---|
| `npm --prefix frontend run build` | Pass (295.78 kB JS, 35.29 kB CSS) |
| `npm --prefix frontend run lint` | Pass (no errors) |
| `backend/.venv/Scripts/python.exe -m pytest tests` | Pass (31 tests, 2.86s) |
| Backend health endpoint | Pass (`{"ok":true,...}`) |
| Frontend dev server | Pass (port 1420) |
| Tauri window | Pass (ingestor.exe running) |

---

## 9. Summary

Ingestor is a well-structured Tauri desktop app with a clean React frontend and a Python FastAPI backend. The codebase is generally well-organized with CSS modules, typed components, and clear separation of concerns. The build, lint, and tests all pass.

The most critical issue is **BUG-1** (reindex fails when the snapshot directory is lost), which is a data-loss scenario that can occur during normal use when settings are changed. The **accessibility issues** around disabled buttons being invisible to screen readers (UX-1) and the excessively long source button accessible name (UX-3) are the most impactful UX issues. The **orphaned process** port conflict (BUG-3) affects developer experience but not end users of the installed app.

The codebase has some technical debt: duplicated utility functions (CODE-1), a dead CSS file (CODE-2), and a fragile tkinter dependency (CODE-3). These are not blocking but should be addressed in future iterations.
