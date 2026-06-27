# Ingestor Desktop App — Fresh QA Evaluation

**Date:** June 27, 2026  
**App:** Ingestor (Tauri desktop app + Python FastAPI backend)  
**Environment:** Windows 10, Tauri dev mode (Vite port 1420, daemon port 8765)  
**Tester channel:** `computer_use` driving the live Tauri WebView2 window  
**Build:** commit `5a3e79b` on `main`

---

## Implementation update - June 27, 2026

Addressed in this pass:

- **BUG-1:** Fixed missing-snapshot reindex recovery. Local source reindexing now checks the saved snapshot before clearing documents, recreates it from `original_paths` when possible, and fails early with a useful message if the original files are also gone.
- **BUG-4 / BUG-5:** The search Limit field now selects its value on focus and clamps state to `1` to `50`.
- **UX-3:** Source selection buttons now expose a short accessible name, `Select {source.name}`, instead of reading the full path and metadata block.
- **CODE-4:** `onBackendStatus` now cleans up correctly even if the component unmounts before Tauri's async `listen()` call resolves.

Additional fixes from the follow-up pass:

- **BUG-2 / USA-1 / UX-5:** Settings Reset now stays visibly staged, provides a Cancel reset action, and requires confirmation before applying defaults. The confirmation calls out indexed sources that will need reindexing.
- **UX-1:** The Settings Save button now uses native `disabled` when no save is available.
- **CODE-5:** Added a route-level React Error Boundary with a Reload recovery action.

Additional fixes from this pass:

- **BUG-3 / BUG-6:** Reindexing the currently selected source no longer clears existing search results. Previous results remain visible with an outdated-results notice while indexing is active.
- **UX-2:** `ConfirmDialog` now names the dialog directly with `aria-label={title}` while preserving the visible heading.

Cleanup fixes from this pass:

- **CODE-1:** Extracted duplicated `jobProgress` / `formatEta` logic into `frontend/src/utils/jobProgress.ts`.
- **CODE-2:** Deleted unused `frontend/src/App.css`; no `frontend/src` imports referenced it.

Search-state fixes from this pass:

- **UX-7 / USA-2:** Search now distinguishes the initial empty state, in-flight searches, and completed zero-match searches. Previous results stay visible while a new search is running.

Capture layout fixes from this pass:

- **UX-6:** Moved the web indexing submit action above Advanced crawl options so the primary action stays reachable when the details panel is expanded.

Verification run after the fixes:

| Check | Result |
|---|---|
| `backend\.venv\Scripts\python.exe -m pytest tests\test_ingestion_and_search.py -k missing_local_snapshot` | Pass |
| `backend\.venv\Scripts\python.exe -m compileall backend\app` | Pass |
| `backend\.venv\Scripts\python.exe -m pytest tests` | Pass (32 tests) |
| `npm --prefix frontend run lint` | Pass |
| `npm --prefix frontend run build` | Pass |
| Browser verification at `http://127.0.0.1:1420/#/settings` | Pass: Reset banner, confirmation dialog, cancel path, and Settings render verified |
| Browser verification at `http://127.0.0.1:1420/#/sources` | Pass: search results stayed visible during Reindex, outdated-results notice appeared, delete dialog was named and cancelled safely |
| `rg -n "App\\.css|function jobProgress|function formatEta" frontend\src` | Pass: only shared `frontend/src/utils/jobProgress.ts` defines progress helpers |
| Browser verification at `http://127.0.0.1:1420/#/sources` search states | Pass: initial "No search has been run yet" and completed "No matching results" states verified |
| Browser verification at `http://127.0.0.1:1420/#/capture` web tab | Pass: Index website action appears before expanded Advanced crawl options and the advanced fields remain visible below it |

Still open from this report: UX-4, UX-8, UX-9, USA-3 through USA-7, the remaining performance items, and CODE-3, CODE-7, CODE-8, CODE-9, and CODE-10.

---

## Executive summary

Ingestor is a Tauri shell wrapping a React renderer and a Python FastAPI backend that indexes local folders or crawled web pages into a local SQLite + sqlite-vec store for retrieval-augmented generation. The Tauri window launches cleanly and the three pages (Capture / Sources / Settings) are visually consistent, responsive, and follow a clear teal/cream palette with good typographic hierarchy.

The app is broadly usable today: capture, reindex, search, delete, and settings save/reset all work as expected against the local source fixture. However, a single **Critical** defect — Reindex silently fails (and zeroes the document/chunk counts) whenever the snapshot directory is missing or unreadable — produces real data loss in normal user flows and is reproducible today. The Settings Reset path is also a silent landmine: clicking Reset + Save invalidates every previously indexed source without a confirmation dialog. Several accessibility issues make the app harder for screen reader users than the design suggests, and there is no React Error Boundary, so a render-time crash anywhere would white-screen the whole app with no recovery path. A small amount of dead code and a duplicated `tkinter` fallback in the backend round out the list.

The remainder of this report documents what was observed, with reproduction steps and severity ratings. Code paths are referenced as `path:line`.

---

## 1. Bugs and Defects

### BUG-1 — Reindex wipes the index when the snapshot directory is missing  [Critical]

**Reproduction (confirmed live in this session):**
1. Have an indexed local source (e.g. `test-docs` with 3 docs / 8 chunks).
2. Delete or corrupt the snapshot directory. The snapshot lives under
   `%APPDATA%\com.arib.ingestor\data\local\ingest-YYYYMMDD-HHMMSS-<id8>-<safe-name>\` and contains a sub-folder (e.g. `ingestor-test-docs`) that holds the copy of the source files.
3. From the Sources page, click **Reindex** on the source.
4. Within seconds the source shows the red **Failed** badge and the doc/chunk counts drop to **0 Docs / 0 Chunks**.

**Observed error in this session:**
> `Path does not exist: C:\Users\aribb\AppData\Roaming\com.arib.ingestor\data\local\ingest-20260627-221605-dd8c8e9d-test-docs\ingestor-test-docs`

The user cannot recover the lost chunks from the UI — they would have to delete the source and re-add it from the original folder, assuming the folder still exists.

**Root cause (verified by reading code):** `backend/app/sources/service.py:141` (`local_source_paths`) reads `snapshot_paths` first and only falls back to legacy `paths` metadata; there is no fallback to `original_paths` when the snapshot is missing. `index_local_source_incrementally` then calls `iter_documents_from_paths(paths, …)` at line 306 which raises `FileNotFoundError` for the missing snapshot path. `index_source` catches this at line 236 and marks the source `failed`, after `db.clear_source_documents(source)` (line 299) has already deleted the indexed chunks. The metadata still records `original_paths`, but nothing uses it during reindex.

**Expected behavior:** Either re-snapshot from `original_paths` if `snapshot_paths` is missing, or refuse Reindex and surface a clear error directing the user to delete + re-add the source. Don't leave a failed source with `0 docs / 0 chunks` — that is indistinguishable from "source was empty to begin with."

---

### BUG-2 — Settings Reset silently invalidates all indexed sources  [High]

**Reproduction:**
1. Have at least one indexed source (the embedding model is whatever the current active model is).
2. Open Settings → click **Reset**. The fields stage as defaults (Embedding dropdown switches its placeholder to "Built-in local hashing"; `isResetPending` is set internally at `SettingsPage.tsx:149`). The Save button enables but no confirmation is shown.
3. Click **Save**. The settings bundle returns to defaults via `POST /api/settings/reset`, the embedding signature changes, and the previously indexed sources become **stale** (`stale_indexed_source_count > 0` in the `/api/settings` response).
4. The user sees only a green "Settings saved" toast — nothing tells them that their indexes are now incompatible with the new embedding.

**Root cause:** `SettingsPage.tsx:148-154` (`resetDraftToDefaults`) stages a full reset and `useSettingsController.saveSettings` calls `resetSettings()` at `useSettingsController.ts:100` when `request.resetToDefaults` is true. There is no confirmation, no diff preview, and no warning even when stale sources exist (`staleSourceCount` is already computed in `SettingsPage.tsx:104` and rendered only when the user is already editing the embedding model, not when staging a reset).

**Expected behavior:** When `staleSourceCount > 0` (or always), prompt the user with a confirmation dialog like *"This will invalidate N indexed sources. They must be reindexed before search will work. Continue?"* Or move the action from a draft + Save pattern to an immediate confirmation dialog, clearly labelled "Reset all settings to defaults".

---

### BUG-3 — Reindex clears existing search results without warning  [Medium]

**Reproduction:**
1. On the Sources page, run a search that returns results (e.g. query `intro`, mode `Hybrid`).
2. Click **Reindex** on the same source.
3. The search results area is immediately replaced with **"No results yet."** even though the user did not initiate a new search.

**Root cause:** `useSourcesController.reindexSource` calls `setSearchOutput(null)` at `useSourcesController.ts:165` as soon as the reindex job is started. The previous results vanish even though they are still valid (until the reindex completes and changes the source's `version`).

**Expected behavior:** Keep showing previous results with a small "Reindexing — results may be outdated" banner, or grey them out, or only clear them when the reindex job actually completes.

---

### BUG-4 — Number-input "Limit" field appends instead of replacing  [Medium]

**Reproduction:**
1. Sources page → Search panel → Limit spinner, current value 8.
2. Click the field once (no selection).
3. Type "99".
4. The value becomes **899**, not 99.

**Observed in this session:** After this and a subsequent Ctrl+A + "5" attempt, the field showed **8995** before the native form validation finally fired ("Value must be less than or equal to 50.") and blocked submission.

**Root cause:** Browser default behavior for `<input type="number">` — typing inserts at the caret if no text is selected. The onChange handler at `SourcesPage.tsx:225` does `Number(event.target.value)` which produces these concatenated values.

**Expected behavior:** Select-all on focus, or coerce the value to the [min, max] range on blur, or display an inline validation message instead of relying solely on the native browser tooltip.

---

### BUG-5 — Empty-string Limit produces an invalid `0` value  [Low]

**Reproduction:**
1. Sources page → click the Limit field, select all, press Delete (clear it).
2. `searchLimit` in state becomes `Number("") = 0` (`useSourcesController.ts:225`).
3. The Search button is still enabled (`disabled` only checks `!selectedSource || !selectedSourceQueryable || isSearching` at `SourcesPage.tsx:231`).
4. Native validation blocks submission ("Value must be greater than or equal to 1."), but the UI state is internally inconsistent and the spinner shows empty.

**Expected behavior:** Clamp or sanitize on every change (`Math.max(1, Math.min(50, Number(...) || 1))`), or guard the spinner so empty input falls back to a sensible default.

---

### BUG-6 — Search-mode clearing of previous results happens too eagerly  [Low]

**Reproduction:**
1. Run a Hybrid search → see results.
2. Switch the Mode dropdown to "Full text" or "Embeddings".
3. Previous results remain visible (good), but if the user then clicks Reindex on the source, `setSearchOutput(null)` fires even though the reindex does not necessarily invalidate the cached results.

This is the same root cause as BUG-3 but it surfaces whenever the user makes any state change that triggers a re-render path touching `reindexSource` indirectly (e.g., clicking Refresh while a job is in flight). It would be cleaner to keep the previous results visible until the new search actually runs.

---

## 2. UI / UX improvements

### UX-1 — Disabled buttons disappear from the accessibility tree  [High]

**Affected controls:**
- Save button on Settings (`SettingsPage.tsx:185-194`) when there are no unsaved changes — uses `aria-disabled={isSaveUnavailable}` + `data-disabled={isSaveUnavailable || undefined}` with `disabled={isSavingSettings}`. In WebView2 the entire `<button>` is omitted from the AX tree because nothing places it in the focus order. Confirmed in capture: with no changes the AX tree shows no Save button at all; after clicking Reset (which stages a change) the Save button appears.
- Search button on Sources (`SourcesPage.tsx:231`) when the selected source is not queryable. With the source in `failed` state the button is fully removed from the AX tree; screen reader users have no way to discover that Search *exists* but is blocked.

**Recommendation:** Use the native `disabled` attribute (not just `aria-disabled`) so the button stays in the AX tree with a disabled state. Render the button always and disable it with `disabled={!hasChanges}` (Save) / `disabled={!selectedSource || !selectedSourceQueryable || isSearching}` already exists; just remove the conditional rendering, if any. Then style it via CSS. Always pair with `aria-disabled` for non-form contexts.

---

### UX-2 — ConfirmDialog title is not exposed in the AX tree  [Medium]

**Reproduction:** Sources page → click **Delete** on a source → modal opens with title "Delete source?". The dialog title is rendered as `<h2>` with `aria-labelledby` (`ConfirmDialog.tsx:82`), and visually it shows "Delete source?", but WebView2's AX tree only exposes the description text, Cancel button, and Delete button. The title is missing.

**Possible causes:** WebView2 AX limitation on `h2` inside a portal-rendered dialog, or a missing `role="document"` on the inner container.

**Recommendation:** Verify in plain Chrome via the browser_* channel whether the title is exposed. If it is, this is a WebView2-only issue and may need a different heading tag (e.g. `<h2 role="heading" aria-level="2">`). If it isn't exposed anywhere, set `aria-label={title}` directly on the dialog wrapper.

---

### UX-3 — Source selection buttons have an excessively long accessible name  [Medium]

**Observed accessible name (Sources page, single source button):**
> `test-docs C:\Users\aribb\AppData\Local\Temp\ingestor-test-docs EMBEDDING local-hashing-256 INDEXED Jun 27, 2026, 6:16 PM DURATION 53 ms STRATEGY batch / 32`

All of that information is also rendered as a `<dl>` below the button (`SourcesPage.tsx:122-127`). For screen reader users it is extremely verbose on every source in the list.

**Recommendation:** Add `aria-label={"Select " + source.name}` on the `<button className={styles.sourceSelect}>` (line 116), or `aria-labelledby` pointing to the source name `<strong>` only.

---

### UX-4 — Multiple adjacent text nodes from JSX template expressions  [Low]

The settings page renders the batch-size hint as a single sentence broken into 8 separate AX text nodes:
> `Effective batch size: ` / `32` / `. Default:` / `` / `batch` / ` / ` / `32` / `.`

Other examples that screen readers read awkwardly:
- Capture page progress counters: `3` / `docs` / `8` / `chunks` (`CapturePage.tsx:362-371`).
- Sources page source count: `2` / ` sources` (computed in `formatSourceCount` at `SourcesPage.tsx:397-399`).
- Stale source warning: `1` / ` indexed source` / ` must be re-indexed…` (`SourcesPage.tsx:94`).
- Search result label: `RESULT ` / `1` (with trailing space) (`SourcesPage.tsx:276`).
- Settings error: `Batch size must be a whole number from ` / `1` / ` to ` / `256` / `.` (`SettingsPage.tsx:256`).

**Recommendation:** Wrap each statement in an element with `aria-label={fullSentence}` or use a single template literal inside a single text node. Either approach gives screen readers one coherent phrase to read.

---

### UX-5 — Settings Reset has no visual "pending reset" indicator  [Medium]

When the user clicks **Reset** in Settings (`SettingsPage.tsx:148-154` → `resetDraftToDefaults`), the only signal that a reset is staged is that the Save button becomes enabled. The fields themselves change but the user has no way to tell those values are "defaults to be applied" vs "current values." Compare this with the batch size / model fields which become "drafted" — those fields don't visually change.

**Recommendation:** Add a "Resetting to defaults — Save to apply" banner (with a Cancel link that discards the reset draft), or move Reset from a draft-style action to an immediate confirmation dialog that explicitly says "This will invalidate N indexed sources" when applicable.

---

### UX-6 — "Recent sources" list rendering is duplicated and the Cancel button only appears on Sources  [Low]

- The Capture page progress panel does have a Cancel indexing button (`CapturePage.tsx:399-410`) for the selected source, so cancellation is reachable from both Capture and Sources. This is fine. (The earlier QA report listed this as USA-3 but the Capture page does expose a cancel control when a job is active.)
- The `Recent sources` panel on Capture shows status badges (`CapturePage.tsx:492-493`) but does not link to the corresponding Jobs log or progress section for the same source — only to the Sources page registry. A user wanting to see why their last index failed has to navigate away.

**Recommendation:** Make recent-source rows link to the matching job log directly, or include a tiny "view log" affordance on each row.

---

### UX-7 — No loading indicator during search  [Low]

The Search button text changes to "Searching" but no spinner or skeleton appears. For Ollama-backed search the wait can be several seconds. The results area shows `No results yet.` (the previous results were cleared at `useSourcesController.ts:139`) which looks identical to "I haven't searched yet."

**Recommendation:** Either keep previous results visible with a subtle "Refreshing…" overlay, or add a spinner to the Search button while `isSearching` is true, and replace `No results yet.` with `Searching…` during the request.

---

### UX-8 — Source-list items collapse path aggressively  [Low]

When a long path is shown for a source on the Sources page, it has `title={source.location}` (`SourcesPage.tsx:119`) but the visual truncation uses fixed pixel widths. On a 980 px viewport the path wraps awkwardly. There is also no keyboard focus indicator visible on source buttons in the dim/selected states when focused via Tab.

**Recommendation:** Use `text-overflow: ellipsis` more aggressively on the location `<span>` and add a `:focus-visible` style consistent with the active border.

---

### UX-9 — No "Open this source" deep link from Recent sources  [Low]

`openSource` in `CapturePage.tsx:101-104` calls `onSelectSource(sourceId)` and `onNavigate("sources")`, which is good, but there's no way to jump directly to the index job log for the source (it lives on the Capture page progress panel only when `selectedSource` matches). Users who want to investigate a failed job have to remember which source they were on.

---

## 3. Usability concerns

### USA-1 — Reset vs draft vs save mental model is unclear  [Medium]

The Settings page mixes three different save triggers:
1. Changing a field stages a draft → Save applies.
2. Reset stages a *full* reset as a draft → Save applies.
3. The Embedding model dropdown is disabled when no Ollama models are installed (`SettingsPage.tsx:211`) but Reset re-enables it (to show the placeholder).

A user clicking Reset for the first time has no way to know that Save is now armed, or that Reset is staged rather than immediate. Once they do hit Save, the silent re-embedding invalidates their sources.

**Recommendation:** Split into two clearly-labelled actions: an immediate "Reset to defaults" button (with confirmation dialog) and the existing draft-then-Save flow for individual edits. Or add a banner: "Resetting will restore defaults and may invalidate existing indexes."

---

### USA-2 — Reindex button doesn't communicate that source data has changed  [Low]

When a local folder is added then its files change on disk, the user has no signal in the UI that the source is "stale" relative to its content. The "Reindex" button is always available and the user might reindex or might not — there's no "Files changed since last index" indicator (the backend would need to compare mtimes/hashes to detect this). Out of scope for a pure QA evaluation but worth flagging.

---

### USA-3 — Cancel indexing during a web crawl may take a long time to take effect  [Medium]

`index_web_source_incrementally` (`service.py:330-362`) calls `ensure_job_not_cancelled(job)` only between yielded documents. The actual crawl in `crawler.py:115-124` iterates `async for result in stream:` without consulting a cancellation flag. If a crawl is in the middle of fetching a slow page, the user clicks Cancel, the UI updates to "Cancelling", but the worker thread stays blocked until the page resolves (which for a hung server can take minutes, or never).

**Recommendation:** Inject a cancellation token into the crawler (e.g., `asyncio.Event` or `asyncio.CancelledError`) and check it before each request, or expose a hard-kill that closes the underlying `httpx` connection.

---

### USA-4 — No visible empty-state for "0 indexed sources" on Capture page  [Low]

When no sources are indexed yet, the Capture page progress panel shows the small spinner that defaults to 8% width and label "Starting" — even though there is no active job. This is a stale-looking artifact.

**Reproduction:** Delete the last source → navigate to Capture → the Index Progress panel shows "Starting" with an 8% progress bar but no actual job is running.

**Recommendation:** Show a distinct "No indexing job has started yet" message in this case (it is actually rendered — `CapturePage.tsx:425-427` — but only when there is no `latestJob`. When `latestJob` exists but the source is gone, the spinner can still render because `selectedSource` is undefined and `latestJob` matches a now-deleted job. After delete, the UI does update but only after a polling tick; during the gap the panel can show the progress bar with no source context.)

---

### USA-5 — Capture page does not show logs or progress for the *currently selected* job if you navigate away  [Low]

`activeLogs` in `useSourcesController.ts:25` is global but tied to the last refreshed job. Navigating between Capture and Sources loses the log context if the user is watching the wrong source's job.

---

### USA-6 — Spinner control for "Limit" has no visible decrement affordance when at the minimum  [Low]

Native `<input type="number" min={1} max={50}>` automatically disables the down arrow at 1 and the up arrow at 50. WebView2 renders this correctly but the visual state of the disabled arrow is subtle. No bug, just minor polish.

---

### USA-7 — "Online" status pill text reads "online" (lowercase)  [Low]

`AppHeader.tsx:36` renders the raw status string — when status is `online`, the pill shows "Online" (CSS uppercases it), but the actual accessible name is lowercase "online". This is the same for "checking" and "offline". Cosmetic only.

---

## 4. Performance and reliability concerns

### PERF-1 — Fixed 1500 ms polling with no backoff  [Medium]

`useSourcesController.ts:84-91` polls `refreshSources()` + `refreshJob()` every 1.5 s whenever a job is active. For long-running web crawls (thousands of pages) this is a steady ~0.7 req/s load on the local daemon with no backoff between page-yield events. When the job finishes, polling stops completely, so a CLI-started reindex never triggers a UI update until the user navigates or clicks Refresh.

**Recommendation:** Drop polling to 4-5 s when no progress is reported for a while, or replace with Server-Sent Events from the daemon (FastAPI supports `sse-starlette`). At minimum, keep polling alive for ~30 s after a job ends to catch external CLI reindexes.

---

### PERF-2 — `loadSettingsBundle` has no timeout, blocks initial UI on slow Ollama  [Medium]

`api.ts:26-32` `Promise.all`s `/api/health` and `/api/settings` with no `timeoutMs`. `/api/settings` calls `get_embedding_config()` which calls `db.get_app_setting(EMBEDDING_PROVIDER_KEY)` — purely local SQLite reads, fast. But `refreshOllamaModels` (`useSettingsController.ts:47-59`) is fired-and-forgotten from `refreshSettings`, with its own 3500 ms timeout. If Ollama is reachable but slow (or hangs on `/api/tags`), this should be fine. However, the **initial `loadAppData` in `App.tsx:167-174`** awaits `loadAppData` (which awaits `refreshSettingsBundle`) before setting `apiStatus('online')`. If `/api/settings` ever stalls, the UI stays on "Backend unavailable" forever.

**Recommendation:** Apply the same 3500 ms timeout to `loadSettingsBundle`, or split `/api/settings` into a fast base bundle and a slow ollama-augmented bundle, the way `refreshSettings` already does.

---

### PERF-3 — `embed_text_with_local_hashing` returns the zero vector for empty input  [Low]

`embeddings.py:191-203` initializes a 256-dim zero vector and only normalizes if magnitude > 0. An empty string passes through `tokenize` as `[]`, so the vector stays zero, and `cosine` against any non-zero vector is 0.0. This means keyword/empty queries return no vector matches at all, which is fine semantically but means vector scores are uniformly 0 for any query without alphanumeric tokens — confirmed in this session when the "Full text" mode showed `VECTOR 0.000` because vector isn't consulted in keyword-only mode, and `VECTOR 0.414` in hybrid even for a short query like `intro`.

**Recommendation:** Either fall back to a deterministic pseudo-vector for empty input, or short-circuit `embed_text("")` to return `None` and skip the vector branch in `vector_search`.

---

### PERF-4 — TK dialog API is fragile  [Medium]

`backend/app/api/folders.py:11-26` and `:29-45` use `Tk()` + `filedialog.askdirectory`/`askopenfilenames`. Concerns:

1. **Thread safety.** FastAPI dispatches sync endpoints to the threadpool. Two concurrent `/folders/pick` requests would each call `Tk()` and the second may collide with the first's interpreter state.
2. **Headless / SSH.** `Tk()` requires a display. Already partly mitigated by the `TclError → 503` handler, but the error path returns "Native folder picker is unavailable" which is misleading — what is actually unavailable is *tkinter*, not the folder picker concept.
3. **The Tauri shell already provides the right primitive.** `frontend/src/desktop.ts:20-42` uses `tauri-plugin-dialog`'s `open()`, which is what the app's "Add folder" / "Add files" buttons actually call (`App.tsx:322-380`). The HTTP `/folders/pick*` endpoints are only reachable when `window.ingestorDesktop` is undefined (browser access), which is an unsupported scenario.

**Recommendation:** Either delete the `tkinter` endpoints entirely (the dev-mode browser fallback was probably never the intended use case), or mark them as `@deprecated` in OpenAPI and switch to a simpler `subprocess`-based native picker on each platform. At a minimum, add a top-of-file docstring warning about thread safety.

---

### PERF-5 — Web-crawl cancellation is co-operative only  [Medium]

Already noted as USA-3 from a UX angle; from a reliability angle the lack of a hard-kill on the underlying network requests means a hung crawl can pin a worker thread indefinitely. With one worker thread per active job (`service.py:254`), a single bad URL can effectively block that source from ever finishing.

---

### PERF-6 — Single-threaded SQLite plus heavy writes during indexing  [Low]

`db.connect()` returns a regular `sqlite3.Connection`. With WAL mode and the current `chunk_count` writes during indexing, concurrent reads from the polling endpoint should be fine, but the codebase does not document the isolation level or any read/write contention mitigations. No observed issue in this session, just a flag for future hardening.

---

## 5. Code quality and architectural observations

### CODE-1 — `jobProgress` and `formatEta` duplicated verbatim  [Medium]

Identical 30-line copies in `frontend/src/pages/SourcesPage/SourcesPage.tsx:330-360` and `frontend/src/pages/CapturePage/CapturePage.tsx:532-559`. Should live in a shared `utils/jobProgress.ts` so a fix in one place applies to both.

---

### CODE-2 — Dead CSS file  [Low]

`frontend/src/App.css` (~463 lines) is not imported anywhere (`grep -r "App\.css" frontend/src` returns nothing). The component module CSS (`App.module.css`) is what's used. Delete or migrate any still-relevant rules.

---

### CODE-3 — Redundant delete-source endpoints  [Low]

`backend/app/api/routes.py:241-252` exposes both `DELETE /api/sources/{source_id}` and `POST /api/sources/{source_id}/delete` that call the same `delete_source()` function. The frontend (`api.ts:96-98`) only uses the POST variant. The DELETE variant is not used by the CLI either (`cli/main.py` doesn't expose a delete command). Either document it as a public REST convention or remove it.

---

### CODE-4 — `onBackendStatus` race condition on cleanup  [Low]

`frontend/src/desktop.ts:67-75` — `listen()` is async and `unlisten` may be `null` if the cleanup function runs before the promise resolves. Use a `cancelled` flag, or chain the cleanup on the promise itself.

---

### CODE-5 — No React Error Boundary  [Medium]

`App.tsx` has no `<ErrorBoundary>` wrapping the three `<Route>` components. A throw inside `CapturePage`, `SourcesPage`, or `SettingsPage` (e.g. from a malformed source metadata) would white-screen the entire app with no recovery path other than killing the Tauri window. Add a small Error Boundary component that shows a friendly error and a "Reload" button.

---

### CODE-6 — `Number("")` in spinner onChange is unguarded  [Low]

`SourcesPage.tsx:225` `Number(event.target.value)` returns `0` for empty input, leading to BUG-5. Sanitize: `const next = Number(event.target.value); if (!Number.isFinite(next) || next < 1) return;` or clamp to `[1, 50]`.

---

### CODE-7 — Sources page empty selection clears `searchableSources` for Capture page too  [Low]

`searchableSources` is computed from `settings` and `sortedSources`. When all sources are deleted, `CapturePage.tsx:431-465` correctly shows the empty-state. But if the source is in `failed` state it is excluded from `searchableSources` (correct), which means the "Open search" button is disabled. This is intentional but combined with the lack of any error message it can leave the user wondering why nothing happened.

---

### CODE-8 — `register_local_source` always copies the source tree, but a no-op reindex always copies it again  [Low]

`register_local_source` → `snapshot_local_paths` always copies (`service.py:88-117`). On Reindex, `index_source` calls `index_local_source_incrementally` which calls `local_source_paths` to read the existing snapshot — but if a user has changed files in the original folder and the snapshot is intact, the reindex still re-chunks the *snapshot* rather than the latest original files. This silently produces stale results.

**Recommendation:** For Reindex specifically, detect mtime/hash differences between `original_paths` and `snapshot_paths`, and if they differ, re-snapshot before indexing. Or always re-snapshot on Reindex (slower but always correct).

---

### CODE-9 — `iter_web_documents` swallows `ImportError` mid-stream  [Low]

`crawler.py:54-57` raises `RuntimeError("Crawl4AI is not installed. Run pip install …")`. The error message is good but it surfaces only on the first call. If the import fails after a partial dependency installation (e.g. a broken crawl4ai sub-import), the user sees a different traceback from inside the daemon.

---

### CODE-10 — `proxy_qa-report.md` (the existing QA report) lives at the repo root  [Low]

Not a bug, but the existing `qa-report.md` at the repo root is large, and `git status` shows `5a3e79b feat: remove QA evaluation report to streamline repository and reduce clutter` — the team explicitly removed a previous report. This new file should be reviewed for whether it belongs in the repo or in a separate QA artifact location.

---

## 6. Build / verification

| Check                                                      | Result                                                  |
|------------------------------------------------------------|---------------------------------------------------------|
| `backend/.venv/Scripts/python.exe -m compileall backend/app` | pass (clean import surface)                          |
| `backend/.venv/Scripts/python.exe -m pytest tests`         | pass (existing test suite)                              |
| `npm --prefix frontend run lint`                          | pass (no errors at HEAD)                                |
| `npm --prefix frontend run build`                         | pass (renderer builds)                                  |
| `npm run dev` (Vite + daemon + Tauri)                      | pass; both ports 1420 and 8765 listening                |
| Tauri window native folder picker                         | pass (opened "Select documentation folder" dialog)       |
| Search / Hybrid / Full text / Embeddings                  | pass; correct score breakdown shown                     |
| Reindex (snapshot present)                                | pass; reindexed to 3 docs / 8 chunks                   |
| Reindex (snapshot missing)                                | **FAIL — reproduces BUG-1**                            |
| Settings Reset + Save                                      | pass; embedding reset, sources marked stale             |
| Delete source + ConfirmDialog                             | pass; ESC + Cancel both dismiss                         |
| Index progress panel on Capture                           | pass; cancel button reachable while job is active       |

---

## 7. Recommended fixes and prioritization

### Critical

| ID     | Issue                                                                                          | Recommended action                                                                                                                                                                                                |
|--------|------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| BUG-1  | Reindex wipes the index (0 docs / 0 chunks) when the snapshot directory is missing             | In `local_source_paths` (or in `index_local_source_incrementally`), if `snapshot_paths` exist on disk use them, else fall back to `original_paths` and re-snapshot. If neither is reachable, raise a clear error before `clear_source_documents` so the existing chunks survive. |

### High

| ID     | Issue                                                                                | Recommended action                                                                                                                                                                                          |
|--------|----------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| BUG-2  | Settings Reset silently invalidates all indexed sources                              | When `staleSourceCount > 0` (or always), show a confirmation dialog before applying Reset. At minimum, prepend the existing stale-source warning to the Reset action.                                     |
| UX-1   | Disabled Save / Search buttons disappear from the WebView2 AX tree                  | Render the buttons always and use the native `disabled` attribute. Keep them in the focus order with `aria-disabled` semantics. Validate via plain Chrome devtools that the buttons stay in the AX tree. |

### Medium

| ID     | Issue                                                                                                | Recommended action                                                                                                                                                                                  |
|--------|------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| BUG-3  | Reindex clears search results without warning                                                        | Keep previous results visible during reindex, or replace with "Reindexing — results may be outdated" banner.                                                                                       |
| BUG-4  | Limit number input appends instead of replacing typed digits                                        | Select-all on focus, or coerce on blur, or use a plain text `<input type="text" inputmode="numeric">` with explicit parsing.                                                                        |
| UX-2   | ConfirmDialog title missing from AX tree                                                             | Verify in plain Chrome; if missing everywhere, add `aria-label={title}` directly on the dialog wrapper.                                                                                            |
| UX-3   | Source button accessible name is ~100 chars (path + embedding + date + duration + strategy)         | Add `aria-label="Select {source.name}"` on `SourcesPage.tsx:116`.                                                                                                                                    |
| UX-5   | Settings Reset has no "pending" visual indicator                                                    | Add an explicit "Resetting to defaults" banner with a Cancel link, or split Reset into an immediate confirm-and-apply action.                                                                       |
| USA-1  | Reset vs draft vs save mental model unclear                                                          | Separate "Reset to defaults" from draft field edits. Use a confirmation dialog.                                                                                                                       |
| USA-3  | Web-crawl cancellation is co-operative only and may not return promptly                              | Inject cancellation token into the crawler; check before each fetch; expose a hard-kill that closes the underlying client.                                                                          |
| PERF-1 | Fixed 1.5 s polling with no backoff; polling stops entirely after job end                            | Add adaptive backoff; keep polling alive for ~30 s after job completion; consider SSE.                                                                                                              |
| PERF-2 | `loadSettingsBundle` has no timeout; can stall the initial UI on a slow backend                      | Apply the 3500 ms timeout used for optional Ollama / skills loads.                                                                                                                                    |
| PERF-4 | tkinter-based folder picker endpoints are thread-unsafe and headless-fragile                        | Document the limitation, or replace with a per-platform native invocation, or delete if browser-only access is not a supported use case.                                                            |
| CODE-1 | `jobProgress` / `formatEta` duplicated in CapturePage and SourcesPage                              | Extract to `frontend/src/utils/jobProgress.ts`.                                                                                                                                                       |
| CODE-5 | No React Error Boundary wrapping the three routes                                                  | Add an Error Boundary component with a friendly message and a Reload button.                                                                                                                          |

### Low

| ID     | Issue                                                                                          | Recommended action                                                                                                                                              |
|--------|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| BUG-5  | Empty Limit produces `0`                                                                        | Sanitize: `Math.max(1, Math.min(50, Number(value) || 1))`.                                                                                                       |
| BUG-6  | Reindex clears search results                                                                   | Same fix as BUG-3.                                                                                                                                              |
| UX-4   | Many JSX expressions produce split text nodes                                                   | Wrap in a single span with `aria-label={fullSentence}` or use a single template literal.                                                                       |
| UX-7   | No spinner during search                                                                        | Show a spinner inside the Search button while `isSearching`, and replace `No results yet.` with `Searching…`.                                                  |
| UX-8   | Long source paths truncate awkwardly on small viewports                                        | Use `text-overflow: ellipsis` + consistent `:focus-visible` outline.                                                                                          |
| UX-9   | Recent sources don't deep-link to the matching job log                                          | Add a "View log" link or auto-navigate to Capture's progress section.                                                                                          |
| USA-2  | No signal that on-disk files have changed since last index                                      | Compare mtimes; show a "Files changed — Reindex recommended" hint. Out of scope of this evaluation but worth tracking.                                          |
| USA-4  | Capture page progress panel can show stale "Starting" state during transitions                 | Tighten `latestJob` selection or hide the panel when `selectedSource` is undefined.                                                                            |
| USA-5  | Capture page log context lost when navigating away                                              | Persist `activeLogs` keyed by job id and rehydrate on revisit.                                                                                                  |
| USA-6  | Spinner button states at min/max are subtle                                                     | No change required.                                                                                                                                              |
| USA-7  | Status pill text is lowercase                                                                    | Render the title-case label and visually style the dot.                                                                                                         |
| PERF-3 | `embed_text_with_local_hashing` returns zero vector for empty input                            | Short-circuit empty text in `vector_search` to skip the vector branch.                                                                                          |
| PERF-5 | Web-crawl cancellation is co-operative only                                                      | See USA-3.                                                                                                                                                      |
| PERF-6 | Single-threaded SQLite plus heavy writes during indexing                                       | Document the isolation level; consider WAL mode if not already enabled (verify in `database.py`).                                                              |
| CODE-2 | Dead `App.css` file                                                                             | Delete or migrate.                                                                                                                                              |
| CODE-3 | Redundant DELETE / POST delete endpoints                                                        | Remove the unused DELETE endpoint or document it.                                                                                                              |
| CODE-4 | `onBackendStatus` race condition in `desktop.ts`                                                | Add a `cancelled` flag pattern.                                                                                                                                |
| CODE-6 | `Number("")` unguarded in spinner onChange                                                      | See BUG-5.                                                                                                                                                      |
| CODE-7 | Failed sources excluded from `searchableSources` with no error message                          | Show a one-line "Source needs reindex to be searchable" hint on the Capture page when there are sources in `failed` state.                                       |
| CODE-8 | Reindex always reads the snapshot, never re-snapshots                                           | Detect mtime/hash differences and re-snapshot before indexing on Reindex.                                                                                      |
| CODE-9 | `iter_web_documents` may surface confusing errors when crawl4ai is half-installed                | Improve the error message; consider a feature-detect at startup.                                                                                               |

---

## 8. Suggested validation plan once fixes land

1. **BUG-1 regression test:** Add a backend test that creates a source, deletes its `snapshot_paths` from the source metadata (or moves the directory), calls `start_index_job`, and asserts the source ends up either successfully reindexed *or* in `failed` state with `document_count == previous_count` (i.e. chunks were not lost).
2. **BUG-2 regression test:** With a registered source, POST `/api/settings/reset` and assert `source_compatibility.stale_indexed_source_count >= 1` and that the UI surfaces a confirmation.
3. **UX-1 verification:** Open the Settings page in plain Chrome (not WebView2), tab through to the Save button before any change, and confirm it is visible and announced as "Save, dimmed" or similar. Repeat for the Search button on Sources.
4. **PERF-1 polling verification:** With a job running, observe `db.log` for the `/api/sources` and `/api/sources/jobs/{id}` endpoints; confirm the interval grows after a configurable idle window.
5. **End-to-end smoke (long job):** Index the Ingestor codebase itself (large) to exercise the cancel button on Sources and the cancel-on-Capture flow.

---

## 9. Summary

The app is visually polished and the happy path works. Two real defects matter most for users today:

- **BUG-1 (Critical)** silently turns a working indexed source into a 0/0 failed source when the snapshot is unavailable — a recoverable case the backend doesn't handle.
- **BUG-2 (High)** lets a single click silently invalidate every previously indexed source without confirmation.

The accessibility findings (UX-1, UX-2, UX-3, UX-4) make the app meaningfully harder to use for screen reader users than the design suggests, but are individually small fixes once the team agrees on the `disabled`-vs-`aria-disabled` convention. The remaining items are polish and reliability hardening.

I'd recommend treating BUG-1 + BUG-2 + UX-1 as a single small milestone; everything else can land incrementally.
