# 0004: Web front end

Status: draft

## Problem

Margin is used through a terminal command today. Many novelists don't use a terminal, and even for those who do, reading long cited answers and contradiction reports there is uncomfortable: quotes wrap badly, nothing links to the passage, and choosing which Google Docs tabs to leave out means typing glob patterns. Margin needs a small, pleasant page in the browser over the same local API.

## User stories

- **US-1** As an author, I want to open Margin in my browser and see what's indexed, so that I know it's ready.
- **US-2** As an author, I want to ingest my manuscript from the page: a Google Doc link, a folder under `manuscripts/`, or the demo novel.
- **US-3** As an author ingesting a Google Doc, I want to see its tabs and untick the ones that aren't the book (notes, cast lists), so that only chapters are indexed, and have that choice remembered.
- **US-4** As an author, I want to ask a question and read the answer with each quote shown under its statement, and open the full passage behind any citation.
- **US-5** As an author, I want to check a chapter (a Google Docs tab, or pasted text) and read the contradictions with both sides side by side.
- **US-6** As an author, I want to see the cost before a check runs and confirm it, as in the CLI.

## Acceptance criteria

Terms are from `CONTEXT.md`.

- **AC-1 Served by the service.** `http://localhost:8000/` serves the page from the Margin service itself: plain HTML, CSS and JavaScript, with no build step, no Node and no external requests (no CDN fonts or scripts). `docker compose up` is still the only setup. The OpenAPI docs stay at `/docs`.
- **AC-2 Status.** A header shows the indexed manuscript (name, chapters, passages), whether the Anthropic key is set, and the Google sign-in state. When nothing is indexed, the page opens on the ingest view.
- **AC-3 Ingest.**
  - **Google Doc:** paste a link and click "Show tabs". The page lists every tab (name, words) with a checkbox, ticked except those the remembered exclusions leave out. Glob patterns can also be typed (e.g. `Notes*`). Ingest sends the unticked tabs as exclusions, which are remembered.
  - **Folder or file:** a list of what's in `manuscripts/`.
  - **Demo novel:** one button.
  - Progress shows while indexing. The result shows the chapters, words, passages, tabs read and unchanged, and excluded tabs.
  - When Google isn't set up or signed in, the page says so, with a "Sign in to Google" button that opens the sign-in in a new tab.
- **AC-4 Ask.**
  - A question box. The answer streams in.
  - Each statement shows its numbered citations with chapter, paragraph and quote. Clicking a citation shows the whole passage, with the quote highlighted.
  - "Not in the manuscript" and the prose refusal show as plain answers, not errors. The cost and model show in small text.
- **AC-5 Check.**
  - Choose a tab of the ingested Google Doc (a list), or paste a chapter's text with a title.
  - The worst-case cost shows first, and the check runs only after "Check (≈ $0.62)" is clicked.
  - Contradictions appear as they are found, each as a card with the explanation and the two quotes side by side ("This chapter, ¶ 4" and "Chapter 6, ¶ 5"). Then the counts; consistent and new claims are in a collapsed section.
  - When the tab is already indexed, the page says it's checked against the rest of the book.
- **AC-6 Grounding in the page** (ADR 0001). The page shows only what the API returns. It never shows a failed citation, and never offers to rewrite, continue or improve text: no "fix" buttons, no generated suggestions.
- **AC-7 Text is text.** Manuscript and model text is inserted as text, never as HTML (`textContent`, no `innerHTML` with data), so a passage containing markup or script is shown literally.
- **AC-8 Errors.** API errors are shown in the page with the same messages as the CLI (service down, search down, no key, Google sign-in needed, empty index).
- **AC-9 Look and feel.**
  - Readable and calm: a serif reading face for manuscript text, generous line height, and quotes styled as quotes.
  - Light and dark follow the system setting. Usable from 1024px wide down to a tablet.
  - Keyboard: Enter asks, Escape closes the passage view, and every control is reachable by Tab.

Traceability: US-1 → AC-2. US-2 → AC-3. US-3 → AC-3. US-4 → AC-4, AC-6, AC-7. US-5 → AC-5, AC-6, AC-7. US-6 → AC-5. Errors → AC-8.

## Eval

This feature adds no model step and changes none, so it has no eval. It's covered by:
- API tests for the new endpoints (the manuscripts listing, the check estimate)
- a test that `/` and its static files are served with no external URLs in them
- an escaping test: a passage containing `<script>` is returned by the API unchanged, and the page code never uses `innerHTML` with data (checked by a grep test)
- a manual QA pass in a browser, with screenshots of the demo novel only

## Non-goals

- Accounts, login to Margin itself, or exposing Margin beyond `localhost`.
- Editing the manuscript in the page, or any writing aid.
- A habits report view (that feature doesn't exist yet).
- Saving question history between sessions.
- A mobile phone layout.

## Grounding & safety

- **Same API, same rules:** the page is a client of the API that already verifies every quote. It adds no model calls.
- **No HTML injection:** manuscript and model text is always inserted as text.
- **Local only:** the service listens on `127.0.0.1`, and the page makes no third-party requests.
- **Spend:** a check always shows its worst-case cost and waits for a click.

## Interface

```
┌ Margin ──────────── The Lantern Road · 22 chapters · 1,604 passages · Google: signed in ┐
│  [ Ask ]  [ Check a chapter ]  [ Manuscript ]                                            │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│  Manuscript                                                                              │
│  Google Doc  [ https://docs.google.com/document/d/…            ] [ Show tabs ]           │
│    ☐ Notes                 1,204 words                                                   │
│    ☐ Cast                    880 words                                                   │
│    ☑ Chapter 1             3,410 words                                                   │
│    ☑ Chapter 2             4,002 words   …                                               │
│    Also exclude tabs matching: [ Draft* ]                                                │
│                                                          [ Ingest 22 tabs ]              │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

New HTTP: `GET /` (the page), `GET /static/…`, `GET /manuscripts` (what's under `manuscripts/`), and `POST /check/estimate` (worst-case cost for a chapter or tab).

## Open questions

1. **Paste or upload for checks.** Recommended: a tab, or pasted text with a title (uploading `.docx` later). Alternative: also upload a file now.
2. **Passage view.** Recommended: a side panel that keeps the answer visible. Alternative: a modal.
