# 0005: Progress tracker

Status: draft

## Problem

A novelist drafting a book keeps a running tally by hand: how many words so far, how many chapters drafted and how many still only outlined, how far from the target, how much got written this week. The tally goes stale the moment they stop updating it. Margin already reads every chapter and counts its words at each ingest, but forgets the numbers.

## User stories

- **US-1** As an author, I want to see my total words against my target, so I know how far along the draft is.
- **US-2** As an author, I want to see which chapters are drafted and which are still stubs or outlines, in reading order.
- **US-3** As an author, I want to see how my word count has grown over time and how much I've written since last time.
- **US-4** As an author, I want this kept up to date without doing anything beyond ingesting as usual, and without spending anything.

## Acceptance criteria

Terms are from `CONTEXT.md`.

- **AC-1 Snapshots.**
  - Every ingest that indexes something saves a snapshot for that manuscript: the time, and each chapter's number, title and word count.
  - An ingest that finds no changes saves nothing new.
  - Snapshots are kept in the data volume, one file per manuscript (by name), never in the repo.
  - No model calls.
- **AC-2 Target.**
  - The author sets a word target per manuscript: `margin progress --target 80000`, or from the page.
  - With no target, the page shows totals without a percentage.
- **AC-3 Stubs.**
  - A chapter under a threshold (config `stub_words`, default 200) counts as a **stub**, otherwise as **drafted**.
  - "Drafted 10 of 23" counts chapters.
- **AC-4 `margin progress`** prints:
  - total words and the percentage of the target
  - drafted and stub chapters
  - words added since the previous snapshot, and in the last 7 days
  - a per-chapter table with words and status
- **AC-5 The page.** A **Progress** view shows:
  - a bar to the target with the total
  - drafted and stub counts
  - words since last time and this week
  - a chart of total words over time, drawn as inline SVG with no chart library; each point is a snapshot, and hovering shows its date and total
  - the chapters in reading order, each with a bar for its words and a stub or drafted label
- **AC-6 History starts now.** Before the second snapshot there's no growth to show: the page says "Progress over time appears after your next ingest" instead of an empty chart.
- **AC-7 HTTP.** `GET /progress` returns the target, the latest snapshot and the history (time and total per snapshot). `POST /progress/target` sets the target.

Traceability: US-1 → AC-2, AC-4, AC-5. US-2 → AC-3, AC-5. US-3 → AC-1, AC-5, AC-6. US-4 → AC-1.

## Eval

No model step, so no eval. Tests cover:
- snapshots on changed versus unchanged ingests
- stub counting
- words since last time and in the last 7 days, with fixed timestamps
- the API

## Non-goals

- Daily goals, streaks or reminders.
- Reading targets or status out of the author's notes.
- Per-session timing or keystroke tracking.
- History from before this feature ships.

## Grounding & safety

- Word counts come from the indexed text, so they match what Ask and Check see.
- Excluded tabs (spec 0003) aren't counted.
- Snapshots hold numbers and chapter titles only, no text.

## Interface

```
$ ./margin progress
The Lantern Road: 41,250 of 80,000 words (52%)
Drafted 12 of 18 chapters · 6 stubs
+2,140 words since 24 Nov · +5,900 in the last 7 days

  1  Chapter 1 ........................  3,410  drafted
  2  Chapter 2 ........................  4,002  drafted
  …
 17  Interlude IV .....................      6  stub
```

## Open questions

1. **Stub threshold.** Recommended: 200 words, configurable. A tab holding an outline of a few hundred words would count as drafted, so it could be raised.
