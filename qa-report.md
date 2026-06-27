# Ingestor Desktop App — QA Evaluation Report

**Date**: 2026-06-27
**Tester**: Hermes Agent (automated exploratory QA)
**App version**: 0.1.0 (debug build)
**Environment**: Windows 10, Tauri WebView2, backend on 127.0.0.1:8765, Ollama at 127.0.0.1:11434
**Testing methods**: Tauri desktop app via computer_use (cua-driver), Vite dev server via browser automation, backend API via curl, source code inspection

## Executive Summary

Launched the Tauri desktop application from its pre-built debug binary and also tested the Vite dev server via browser automation. Explored all three primary pages (Capture, Sources, Settings). Registered and indexed a local documentation source (tauri-docs: 277 docs, 5277 chunks, 56.9s indexing time). Tested form validation, search (keyword and hybrid modes), settings save workflow, delete confirmation dialog, custom SelectControl dropdowns, and the Agent Skills sync section. Found accessibility issues with the custom dropdown component, a disabled-button visibility issue in WebView2's accessibility tree, duplicated code across modules, and several minor UX concerns. No console errors or crashes were found on any page.

**Key correction from initial report**: The scroll issue initially reported as Critical (BUG-1) was found to be a cua-driver limitation with WebView2, NOT an app bug. Scrolling works correctly in the browser and should work for real Tauri users with mouse/keyboard.

## Fix Pass — 2026-06-27

Addressed the first batch of accessibility, freshness, and cleanup findings:

- Fixed BUG-1 by keeping the Settings Save button exposed when unavailable via `aria-disabled="true"` instead of native `disabled` for the no-changes state. Native `disabled` is still used while a save is actively running.
- Fixed BUG-2 by refreshing Sources whenever the `/sources` route is opened while the backend is online.
- Fixed BUG-3 by giving each `SelectControl` an accessible label that combines the field label and current selected value.
- Fixed USA-3 by moving focus into `ConfirmDialog`, trapping Tab/Shift+Tab within it, and restoring focus on close.
- Fixed CODE-1 by removing unread health state from `useSettingsController`.
- Fixed CODE-2 by moving shared source/job helper logic into `frontend/src/utils/sourceHelpers.ts`.
- Fixed CODE-5 by adding `aria-activedescendant` and stable option IDs to `SelectControl` while the listbox is open.
- Fixed UX-2 by formatting the Sources registry count as one string.

Verification completed:

- `npm --prefix frontend run lint` — passed.
- `npm --prefix frontend run build` — passed.
- Browser smoke checks against `http://127.0.0.1:5173/#/sources` and `#/settings` confirmed route rendering, select labels such as `Mode: Full text`, active-descendant wiring, and Save button exposure with `aria-disabled="true"`.

---

## Bugs and Defects

### BUG-1 — Disabled Save button not exposed in Tauri WebView2 accessibility tree (Medium)

**Status**: Fixed in the 2026-06-27 fix pass.

- **Where**: Settings page (`/settings`)
- **Reproduction**: Open Settings page in the Tauri desktop app with no unsaved changes. Inspect the accessibility tree via a screen reader or AX inspection tool.
- **Expected**: Both "Reset" and "Save" buttons should be present in the AX tree (Save would be disabled).
- **Actual**: Only the "Reset" button appears in the Tauri WebView2 AX tree. The "Save" button is present in the DOM (confirmed via browser testing where it shows as `[disabled]`) but is omitted from the WebView2 accessibility tree when disabled. This means screen reader users cannot perceive the Save button at all until changes make it enabled.
- **Note**: This may be a WebView2 platform behavior rather than an app bug, but it impacts accessibility. Consider adding `aria-disabled="true"` and keeping the button in the tab order, or using a different disabled pattern (e.g., `tabIndex={0}` with `aria-disabled` instead of the native `disabled` attribute).

### BUG-2 — Sources page does not auto-refresh when navigating from Capture (High)

**Status**: Fixed in the 2026-06-27 fix pass.

- **Where**: Sources page (`/sources`)
- **Reproduction**: Register a source via the API (or have another process create one after app load). Navigate to the Sources page.
- **Expected**: The Sources page should load current data on mount, showing the newly registered source.
- **Actual**: The page shows "0 sources" / "No sources yet." until the user manually clicks the "Refresh" button. The initial `loadAppData` in `App.tsx` calls `refreshSources()` on app mount, but if sources change after that initial load, navigating to Sources doesn't re-fetch. The `useSourcesController` hook only refreshes on explicit `refreshSources()` calls.
- **Note**: The polling interval (1500ms) only runs when there's an active job. Once the job completes, polling stops and the list goes stale. Sources created through the Capture page UI do call `refreshSources()` after registration, but external changes or navigation away-and-back won't trigger a refresh.

### BUG-3 — SelectControl button accessible name shows field label instead of selected value (High)

**Status**: Fixed in the 2026-06-27 fix pass.

- **Where**: All pages using `SelectControl` (Capture page Scope dropdown, Sources page Mode dropdown, Settings page Embedding model/Indexing strategy/Retrieval dropdowns)
- **Reproduction**: Open any page with a SelectControl. Inspect the button's accessible name in the AX tree.
- **Expected**: The button should announce the currently selected value (e.g., "Hybrid", "Hostname", "batch") as its accessible name or value.
- **Actual**: The `<label htmlFor="embedding-model">` associates with the SelectControl's `<button id="embedding-model">`, making the label text ("Embedding model", "Mode", "Retrieval") the button's accessible name. The actual selected value is inside a `<span>` but is not announced as the button's value. A screen reader user would hear "Embedding model" but not know which model is currently selected without interacting with the dropdown.
- **Confirmed in browser**: The browser accessibility tree shows `button "Mode" [expanded=false]` with child `StaticText "Full text"` — the value is rendered but not part of the accessible name.
- **Recommendation**: Add `aria-label` combining the field label and current value (e.g., `aria-label="Mode: Full text"`), or use `aria-labelledby` to associate the label while keeping the button text as the accessible name.

---

## UI/UX Improvements

### UX-1 — Native required validation fires before custom validation messages (Low)

- **Where**: Capture page, local form
- **Issue**: When submitting the local form with an empty name field, the browser's native `required` validation fires (blocking submission) before the custom JavaScript validation can show the "Enter a unique source name" message. When the name is filled but no paths are selected, the custom "Select at least one local folder or file" message appears correctly. The two validation layers work but the native validation provides a less polished experience (browser-default tooltip vs. the app's inline message).

### UX-2 — Source count label splits across multiple AX text nodes (Low)

**Status**: Fixed in the 2026-06-27 fix pass.

- **Where**: Sources page, registry header
- **Issue**: The text "1 source(s)" is rendered as three separate AX text nodes: "1", " source", "s". This is because the JSX uses `{sources.length} source{sources.length === 1 ? '' : 's'}` which creates separate text runs. Screen readers may read this awkwardly.

### UX-3 — Search results have no scroll container or sticky header (Low)

- **Where**: Sources page, search results
- **Issue**: When search returns 8 results, the results list grows long and pushes the search form above the fold. There's no sticky positioning on the search form or a scroll container for results, so the user has to scroll back up to refine their query. In the Tauri desktop app (820px viewport), only 1 of 8 results is visible without scrolling.

### UX-4 — Delete confirmation dialog lacks source impact details (Low)

- **Where**: Sources page, delete dialog
- **Issue**: The `ConfirmDialog` says `This will remove "tauri-docs" and its indexed chunks from Ingestor.` — this is clear, but doesn't mention the document/chunk counts (277 docs, 5277 chunks) that would be lost, which could help users understand the impact.

---

## Usability Concerns

### USA-1 — No keyboard shortcut or menu to navigate between pages (Low)

Navigation between Capture, Sources, and Settings is only via the header links. There are no keyboard shortcuts (e.g., Alt+1/2/3) for power users.

### USA-2 — No global error boundary or persistent error log (Medium)

If the backend goes offline mid-session, the `onBackendStatus` listener sets `apiStatus` to `'offline'` and shows the offline state. However, if individual API calls fail (e.g., search fails, settings save fails), errors are shown as transient messages that auto-dismiss after 5-8 seconds. There's no persistent error log or way to review past errors.

### USA-3 — No focus trap in ConfirmDialog (Low)

**Status**: Fixed in the 2026-06-27 fix pass.

- **Where**: `ConfirmDialog.tsx`
- **Issue**: The dialog uses `aria-modal="true"` and `role="dialog"` which is correct, but there's no focus trap implementation. When the dialog opens, focus is not moved to the dialog, and Tab can still reach elements behind the dialog. The Escape key handler and backdrop click dismissal work correctly, but keyboard users can tab out of the dialog.

---

## Performance or Reliability Concerns

### PERF-1 — Backend folder/file picker uses tkinter (Medium)

- **Where**: `backend/app/api/folders.py`
- **Issue**: The fallback folder/file picker (used when not in Tauri desktop mode) creates a hidden `Tk()` root window and uses `filedialog`. This is fragile — it can fail in headless environments, service contexts, or when tkinter isn't available. The error is caught and returns a 503, but this is a heavyweight dependency for a simple file picker. In the Tauri desktop context, the native dialog plugin is used instead, so this is only a concern for the browser-only development flow.

### PERF-2 — Polling interval for job status is fixed at 1500ms (Low)

- **Where**: `useSourcesController.ts`, `useEffect` with `setInterval`
- **Issue**: The job status polling runs every 1500ms when a job is active. This is reasonable for short jobs but for long web crawls (which could take minutes), this generates significant API traffic. No exponential backoff or adaptive interval is used. The polling also stops entirely once the job completes, meaning the UI won't detect if a new job is started externally.

### PERF-3 — Settings bundle loads 4 API calls in parallel on every app mount (Low)

- **Where**: `api.ts`, `loadSettingsBundle()` fetches `/api/health`, `/api/settings`, `/api/ollama/models`, `/api/skills/targets` in parallel via `Promise.all`. This is efficient, but the Ollama models endpoint may be slow if Ollama is unreachable (connection timeout), blocking the entire settings load. If any one of these fails, the entire `Promise.all` rejects, potentially showing the offline state even if only one endpoint is down.

---

## Code Quality or Architectural Observations

### CODE-1 — Dead state in useSettingsController (Low)

**Status**: Fixed in the 2026-06-27 fix pass.

`useSettingsController.ts:30` — `const [, setHealth] = useState<HealthResponse | null>(null)` stores health but never reads it. The `setHealth` is called in `refreshSettings` but the value is never consumed. This is dead state that should be removed or used.

### CODE-2 — Duplicated utility functions across files (Medium)

**Status**: Fixed in the 2026-06-27 fix pass.

`isSourceQueryable()`, `sourceQueryDisabledMessage()`, `isActiveJob()`, and `isRecord()` are duplicated between `SourcesPage.tsx` and `useSourcesController.ts`. These should be extracted to a shared module (e.g., `utils/sourceHelpers.ts`) to prevent drift.

### CODE-3 — Massive hardcoded DEFAULT_EXCLUDE_PATTERNS string in App.tsx (Low)

`App.tsx:41-110` — A 70-line string constant with exclude patterns is embedded directly in the root component. This should be extracted to a constants file or configuration module.

### CODE-4 — Redundant delete endpoints in API (Low)

`backend/app/api/routes.py` has both `DELETE /api/sources/{source_id}` and `POST /api/sources/{source_id}/delete` — the latter just calls the former. The frontend uses the POST variant. Having both is fine for compatibility but should be documented.

### CODE-5 — SelectControl lacks aria-activedescendant for keyboard navigation (Low)

**Status**: Fixed in the 2026-06-27 fix pass.

The `SelectControl` component correctly uses `role="listbox"` and `role="option"` with `aria-selected`, and implements ArrowUp/ArrowDown keyboard navigation. However, there's no `aria-activedescendant` tracking, which means screen readers won't announce which option is currently focused during keyboard navigation. The listbox items also appear as `ListItem` in the WebView2 AX tree rather than `option`, which may be a WebView2 mapping quirk.

### CODE-6 — ETA calculation uses Date.now() without re-render trigger (Low)

`SourcesPage.tsx:formatEta()` uses `Date.now()` to calculate elapsed time, but this is only re-evaluated when the component re-renders (which happens via the 1500ms polling). The ETA will jump in 1.5s increments rather than smoothly updating. This is acceptable but could be smoother.

### CODE-7 — Web form options persisted to localStorage with versioned keys and legacy migration (Positive)

`App.tsx:126-127` — The web form options use `ingestor.capture.webOptions.v2` with a legacy `v1` key migration path. This is a good practice for schema evolution. The `loadStoredWebOptionsFromKey` function sanitizes numbers with min/max bounds and validates the crawl scope enum.

### CODE-8 — ConfirmDialog uses createPortal correctly (Positive)

`ConfirmDialog.tsx` — The dialog renders via `createPortal` to `document.body`, uses `aria-modal="true"`, `role="dialog"`, `aria-labelledby`, and `aria-describedby`. Escape key and backdrop click dismissal are properly implemented. The only missing piece is focus trapping (see USA-3).

### CODE-9 — Search mode from Settings not reflected in Sources Mode dropdown on initial load (Low)

The `useSourcesController` hook applies the default search mode from settings via `applyInitialSearchMode` on app load. However, the Sources page Mode dropdown button shows "Mode" as its accessible name (not the selected mode value), making it hard to verify which mode is active. The actual mode is correct internally but not perceptible in the AX tree.

---

## Recommended Fixes and Prioritization

### High

1. **Done** — Fix Sources page auto-refresh on navigation (BUG-2).
2. **Done** — Fix SelectControl accessible names (BUG-3).

### Medium

3. **Done** — Fix disabled Save button visibility in WebView2 AX tree (BUG-1).
4. **Done** — Extract duplicated utility functions (CODE-2).
5. **Settings bundle error handling** (PERF-3) — Consider making the Ollama models and skill targets calls non-blocking so a slow Ollama response doesn't prevent the app from loading.
6. **Done** — Add focus trap to ConfirmDialog (USA-3).

### Low

7. **Done** — Remove dead health state (CODE-1).
8. **Extract DEFAULT_EXCLUDE_PATTERNS** (CODE-3) — Move to a constants file.
9. **Done** — Add `aria-activedescendant` to SelectControl (CODE-5).
10. **Unify form validation** (UX-1) — Consider removing native `required` attributes and handling all validation in JavaScript for consistent messaging.
11. **Add keyboard navigation shortcuts** (USA-1) — Support Alt+1/2/3 for page switching.
12. **Add source impact details to delete dialog** (UX-4) — Include document and chunk counts in the confirmation message.
13. **Add sticky search form or results scroll container** (UX-3) — Keep the search form accessible when viewing long result lists.

---

## Features Tested Successfully

- **Capture page local form validation**: "Select at least one local folder or file" message appears correctly when submitting with a name but no paths.
- **Capture page ModeTabs**: Switching between "Local docs" and "Web docs" tabs works correctly.
- **Capture page web form**: Advanced crawl options expand/collapse works, showing Max pages, Max depth, Scope dropdown, Include/Exclude pattern textareas.
- **Source registration and indexing**: Registered tauri-docs via API, indexed 277 docs / 5277 chunks in 56.9s. Progress bar showed real-time updates during indexing.
- **Sources page registry**: Source card displays name, location, metadata (embedding, indexed date, duration, strategy), badges (Local, Queryable, doc/chunk counts), Reindex and Delete buttons.
- **Sources page search (keyword mode)**: Returned 8 results for "window configuration" with correct FTS5 keyword scores (0.499 to 0.452), all vector scores 0.000 as expected for keyword-only mode.
- **Sources page search (hybrid mode)**: Returned 8 results with both keyword and vector scores (e.g., keyword=0.475, vector=0.521). Combined scores differ from keyword-only mode, with different ranking.
- **Sources page search mode switching**: Successfully switched between Hybrid, Full text, and Embeddings modes via the custom SelectControl dropdown.
- **Delete confirmation dialog**: Dialog appears with correct title ("Delete source?"), description, Cancel and Delete source buttons. Modal behavior, Escape key, and backdrop click dismissal all work. Cancel returns to Sources page without deleting.
- **Settings save workflow**: Changed batch size from 32 to 64, Save button enabled on change, saved successfully via API (confirmed batch_size=64 in API response).
- **Settings embedding model dropdown**: Opened to show 5 Ollama models (embeddinggemma:latest, nomic-embed-text:latest, gemma4:12b, gemma4:31b-cloud, qwen3-vl:4b).
- **Agent Skills section**: Displays three skill targets (Agents, Codex, Claude) with individual Update buttons and an "Update all" button.
- **No console errors**: No JavaScript errors or warnings on any page (Capture, Sources, Settings) in the browser console.
- **Backend API health**: All endpoints (health, settings, sources, ollama/models, skills/targets, search) responded correctly.

---

## Testing Notes

### What was tested
- Capture page: Local docs form validation (empty name, empty paths), Web docs form with advanced options expansion, ModeTabs switching, search source quick-access buttons, recent sources list
- Sources page: Source list display, indexing progress bar with real-time updates, status badges (Local, Queryable, doc/chunk counts), metadata display (embedding, indexed date, duration, strategy), Refresh button, search form with query input, mode dropdown (Hybrid/Full text/Embeddings), limit spinner, search execution (keyword and hybrid modes), 8 result cards with scores/snippets/paths, delete confirmation dialog (open, cancel)
- Settings page: Embedding model dropdown (opened, saw Ollama models), indexing strategy controls, batch size input, retrieval mode dropdown, settings save workflow (changed batch size, saved, verified via API), Reset button, Agent Skills section with three targets
- Backend API: Source registration, index job start, job status polling, settings retrieval, settings save (batch size), Ollama models listing, search (keyword and hybrid modes)
- Code inspection: App.tsx, all page components (CapturePage, SourcesPage, SettingsPage), hooks (useSourcesController, useSettingsController), API module, desktop bridge, backend routes, CSS modules, SelectControl component, ConfirmDialog component, AppHeader

### What was NOT tested (due to limitations)
- Native file/folder picker dialogs (Tauri dialog plugin) — cannot be driven by computer_use or browser automation
- Web source crawling (requires network access and Crawl4AI)
- CLI path management and app update checking (only visible in Tauri desktop context, below fold in cua-driver)
- Agent skill sync execution (Update button clicked but not fully verified)
- Offline backend state and retry flow
- Responsive layout behavior at different window sizes
- Drag-and-drop file upload
- Actual source deletion (dialog was opened and cancelled; deletion not executed to preserve test data)
- Reindex workflow (button visible but not clicked to preserve indexed state)
- Settings Reset workflow
- Embedding model change workflow (Ollama model selection)
