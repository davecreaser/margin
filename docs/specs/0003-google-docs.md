# 0003: Google Docs manuscripts

Status: approved

## Problem

Many novelists write in Google Docs, often with the whole book in one document, one tab per chapter. Today Margin reads only local `.md`, `.txt` and `.docx` files, so such an author has to export the book by hand before every ingest, and export a new chapter before every check. Re-ingesting also re-embeds the whole book even when one chapter changed.

## User stories

- **US-1** As an author whose book is in a Google Doc with tabs, I want to ingest it by its link, so that I never export files by hand.
- **US-2** As an author, I want re-ingesting after an edit to be quick, so that I can run it whenever I've written something.
- **US-3** As an author, I want to check one tab (a new or revised chapter) against the rest of the book.
- **US-4** As an author, I want Margin to have read-only access to my Google account and nothing more, and to be able to revoke it.

## Acceptance criteria

Terms are from `CONTEXT.md`.

- **AC-1 Sign in.**
  - `margin google login` prints a Google sign-in link. After the author allows access, Google redirects to the local service (`localhost:8000`), which stores the token in the service's data volume (never in the repo or the image).
  - The only scope is read-only access to Google Docs (`documents.readonly`).
  - `margin google logout` deletes the token and revokes it with Google.
  - The OAuth client ID and secret are the author's own, in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`). The README walks through creating them. A missing client gives "Google Docs isn't set up: see README, Google Docs".
- **AC-2 Ingest a Google Doc.**
  - `margin ingest <Google Doc link or id>` reads the document with all its tabs, in tab order (child tabs after their parent).
  - Each tab with text is one chapter, titled by the tab's name. A tab that itself contains several chapter headings is split by them, with the same rules as a local file.
  - `--exclude "Notes*"` (repeatable, glob on tab names, case-insensitive) leaves tabs out. Empty tabs are skipped.
  - The excluded patterns are remembered for that document, so a re-ingest without `--exclude` uses them again; `--exclude ""` clears them.
  - `POST /google/tabs` (`{"doc": "<link>"}`) lists the document's tabs (name, words, whether currently excluded), so a front end can offer them as checkboxes.
  - The document is only read, never written.
  - The output is the same as a local ingest, plus how many tabs were read, reused and excluded.
- **AC-3 Cheap re-ingest.**
  - If the document hasn't changed since the last ingest (its Docs revision ID) and the excluded tabs are the same, ingest stops after one small metadata call and says "No changes since the last ingest".
  - Otherwise the document is fetched once, and only tabs whose text changed are re-split and re-embedded. Passage vectors are cached by the passage text's hash, so an unchanged passage is never embedded twice.
  - Re-ingesting a 100,000-word book after editing one 4,000-word tab takes under 15 seconds on a laptop, embedding included.
  - Ingest makes no Claude calls; Google's API calls are free.
- **AC-4 Check a tab.**
  - `margin check --tab "Chapter 13"` checks that tab of the ingested Google Doc (fetched fresh).
  - When the tab is already indexed, `--replaces` defaults to its chapter, so it's checked against the rest of the book. The output says so.
  - An unknown tab gives "No tab called <name>", listing the tabs.
- **AC-5 Errors.**
  - Not signed in: "Sign in to Google first: ./margin google login".
  - An expired or revoked token: the same message.
  - No access to the document: "Your Google account can't open that document".
  - Not a Google Doc link: "That isn't a Google Doc link".
  - Google unreachable: "Couldn't reach Google; try again in a minute".
- **AC-6 HTTP.** `POST /ingest` accepts `{"google_doc": "<link or id>", "exclude": [...]}`. `POST /check` accepts `{"tab": "<name>"}` in place of the text. `GET /google/login`, `GET /google/callback` and `POST /google/logout` back the sign-in.
- **AC-7 Privacy.**
  - The cached document text, tab hashes, vectors and token live only in the Docker data volume.
  - Nothing from a real document appears in logs. Tests use invented document JSON, never a real document.

Traceability: US-1 → AC-1, AC-2, AC-5, AC-6. US-2 → AC-3. US-3 → AC-4. US-4 → AC-1, AC-7.

## Eval

This feature adds no model step and changes none, so it has no eval. It's covered by tests:
- tab flattening, splitting and exclusion on invented Docs API JSON
- revision-unchanged short-circuit, and only changed tabs re-embedded (a counting fake embedder)
- token handling with a stubbed Google client
- a `live` smoke test against a real document, which CI doesn't run

## Non-goals

- Writing to, commenting on or suggesting edits in the document.
- Watching the document for changes (ingest is run by hand).
- Several Google Docs as one manuscript, or Google Docs mixed with local files.
- Reading comments, suggestions or revision history.
- A shared OAuth client run by the project.

## Grounding & safety

- **Read-only scope** (`documents.readonly`), and the token can be revoked from the CLI.
- **Secrets:** the client secret is in `.env`, and the token is in the data volume. Neither is ever printed or logged.
- **No private text in the repo:** tests use invented JSON, and the cache is in the Docker volume, not the working tree.
- **Grounding** is unchanged: passages from a tab are cited like any passage, with the tab name as the chapter title.

## Interface

```
$ ./margin google login
Open this link to give Margin read-only access to your Google Docs:
https://accounts.google.com/o/oauth2/auth?...
Signed in.

$ ./margin ingest "https://docs.google.com/document/d/1AbC…/edit" --exclude "Notes*"
Reading "My Novel" from Google Docs: 24 tabs, 2 excluded.
Indexed my-novel: 22 chapters, 1,604 passages (22 tabs read, 0 reused).

$ ./margin ingest "https://docs.google.com/document/d/1AbC…/edit"
"My Novel": 1 tab changed (Chapter 13), 21 reused. Indexed: 22 chapters, 1,611 passages (6s).

$ ./margin check --tab "Chapter 13"
Checking "Chapter 13" (3,912 words) against the rest of my-novel (it replaces chapter 13).
…
```

## Open questions

1. **Tab to chapter.** Recommended: one tab is one chapter, split further only when a tab holds several chapter headings. Alternative: always split by headings, ignoring tabs.
2. **Where the cache lives.** Recommended: a named Docker volume (`margin-data`) at `/data`, which survives `docker compose down` and is removed with `down -v`.
3. **Embedding cache scope.** Recommended: a cache keyed by passage-text hash for any manuscript, local files included, so a local re-ingest also gets faster. Alternative: Google Docs only.

## Decisions

- 2026-11-25: Approved with the recommended answers: one tab is one chapter (split only when a tab holds several chapter headings); cache and token in a `margin-data` Docker volume at `/data`; the embedding cache is keyed by passage-text hash and used for every ingest, local files included.
- 2026-11-25: Excluding tabs is a first-class option: remembered per document, and listed by `GET /google/tabs` so the front end (spec 0004) can offer it at ingest.
- 2026-11-25 (build): Change detection uses the Docs API's `revisionId` (requested with a `fields` mask, so the reply is tiny) instead of Drive's version. Margin then needs only the `documents.readonly` scope, and the Drive API needn't be enabled.
- 2026-11-25 (build): OAuth is a "Web application" client with the redirect `http://localhost:8000/google/callback` and PKCE, implemented with httpx (no Google client library).
- 2026-11-25 (review): A tab is split only by "Chapter N" headings, so scene subheadings stay as text and text before the first chapter heading stays with the tab. Ingest records which chapters each tab became, and `check --tab` leaves all of them out of retrieval. The tab endpoints take POST bodies, and the service runs without an access log, so tab names and the sign-in code never reach the logs. `GET /google/tabs` became `POST /google/tabs`.
- 2026-11-25 (follow-up): Not yet tried against a real Google Doc; the `live` smoke test (`tests/test_gdocs_live.py`) is for the owner's first sign-in.
