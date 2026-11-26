# 0008: Story notes: a better timeline, and a bible of characters and places

Status: approved

## Problem

The timeline (spec 0006) lists every action as an event, so one chapter can give twenty cards. It shows one moment told in three chapters as three unrelated cards. It numbers days from the earliest dated event, not from the start of the story, and it doesn't see that "Day 3" and "the fourth of March" are the same day. It also mixes backstory into the story's days.

Authors also keep a bible of who is who and where is where. They note a character's age, trade, family and where they live, and a place's features. They spend time keeping it in line with the text. Margin reads every chapter for the timeline already, and the same read can build the bible, with every entry quoted.

## User stories

- **US-1** As an author, I want the timeline in scenes, a handful per chapter, so I can read the shape of the story at a glance.
- **US-2** As an author, I want a moment told in several chapters to appear once, with each telling quoted, so I can see where my chapters run in parallel.
- **US-3** As an author, I want the story's days numbered from the start of the story, with the dates the text gives, and backstory kept apart.
- **US-4** As an author, I want a bible of characters and places, built from my text, with every fact quoted and the chapters each one appears in.
- **US-5** As an author, I want both built in one read of the book, only when I ask, after seeing the cost, and paying only for chapters that changed.

## Acceptance criteria

Terms are from `CONTEXT.md`.

- **AC-1 One read, on request.**
  - A regenerate makes the timeline and the bible together: one extraction call per section of each changed chapter, then one placement call and one bible call.
  - The cost is shown first, as in spec 0006. The CLI always asks unless `--yes` is given. `margin timeline --regenerate` and `margin bible --regenerate` do the same thing.
  - Per-chapter extraction is cached as in spec 0006.
- **AC-2 Scenes, not actions.**
  - Extraction lists a chapter's scenes and turning points: about one per 700 words, at least 1, at most 8 per chapter (config).
  - Each has one sentence, a verified quote and optional verified time words, as in 0006.
- **AC-3 One moment, one card.**
  - Placement may group events from different chapters that tell the same moment into one card.
  - The card shows each telling's chapter and quote ("Told in Chapter II, Chapter VI").
- **AC-4 One calendar.**
  - Day 1 is the first day of the story's main action.
  - A period's label carries the date when the text gives one ("Day 2 · the fourth of March").
  - Events dated by a date in one chapter and by a link ("the next morning") in another land in the same period when the text makes them the same day.
- **AC-5 Backstory apart.**
  - Events from before the main action (memories, histories, a character's childhood) go in a **Before the story** band, in their own order, above Day 1.
  - Events after the main action go in an **After** band.
- **AC-6 Stricter placement.**
  - A placement stands only when it rests on verified time words. Those are either the card's own events' time words, or those of an event next to one of them in the same chapter (at most two events away).
  - **Uncertain** is set only when the text allows two placements.
  - Everything else is **Not placed**.
- **AC-7 The bible.**
  - Extraction also lists the characters and places each section mentions, with facts the section states about them. Each fact is one sentence and a verified quote from the chapter. A fact whose quote fails is dropped.
  - One bible call merges names that are the same character or place ("Brother Odo", "Odo") into one entry, using only the names and their facts. Two entries are never merged on a guess: a merge needs a fact or quote that links the names, otherwise they stay apart.
  - For each entry, the chapters it appears in are counted in code: chapters whose text contains one of its names.
- **AC-8 The page.**
  - **Timeline:** scene cards, merged tellings, the Before the story and After bands, and dates in period labels.
  - **Bible:** a new view with Characters and Places tabs and a filter. Each entry has its names, its facts in reading order (each quote opens the passage panel), and the chapters it appears in.
  - Staleness ("3 chapters changed since") shows on both views.
- **AC-9 `margin bible`.** Prints characters, then places: names, facts with chapter and quote, and the chapters each appears in.
- **AC-10 Text is data** (ADR 0005), in all three prompts.
- **AC-11 HTTP.**
  - `GET /bible`.
  - `POST /timeline/regenerate` builds both; `GET /timeline` is unchanged in shape apart from the grouped cards and bands.

Traceability: US-1 → AC-2. US-2 → AC-3. US-3 → AC-4, AC-5, AC-6. US-4 → AC-7, AC-8, AC-9. US-5 → AC-1.

## Eval

`eval/timeline/` is extended, and `eval/bible/` is added. Both are run by hand.

**Cases** (invented text and the demo's eval copy only):
- **Novella 2.** About 8 invented chapters written to break the old timeline:
  - one moment told in three chapters (two scenes and a letter)
  - a backstory scene in the middle of a chapter
  - a date in one chapter linked to "the next morning" in another
  - a letter retelling the previous night
  - an undated scene
  - an injected instruction
- **Novella 1** (spec 0006), kept as a regression set.
- **Demo eval copy.** Birth year 1866. The Clutterbucks are renamed the Pembertons in that copy, so the bible must say Pemberton.
- **Bible gold.** For each novella:
  - every named character and place, with its names
  - 2–3 facts each, as a phrase that the fact's quote must contain

**Grading:**
- **Timeline:** gold events are located by chapter and paragraph range (the scene), so scene-sized events are graded fairly. Then:
  - placement, by period label key term
  - pairwise order
  - **merge:** a gold moment told in several chapters is on one card
  - **backstory:** gold backstory events are in Before the story
  - **granularity:** events per chapter within the gold range
- **Bible:**
  - character and place recall
  - **split rate:** a gold character spread over two entries
  - **false merge rate:** two gold characters in one entry
  - fact recall
  - the counterfactual name

**Bar** (3 runs):
- **Timeline:** placement ≥ 0.80, pairwise order ≥ 0.90, merge ≥ 0.70, backstory ≥ 0.80, granularity ≥ 0.80. Novella 1 no worse than its 0006 baseline. 0 failed citations shown.
- **Bible:** character recall ≥ 0.90, place recall ≥ 0.80, false merges 0, split rate ≤ 0.10, fact recall ≥ 0.70, counterfactual 100%, 0 failed citations shown.

**Cost:** a full run (3 runs, both sets, extraction on Sonnet, placement on Opus, the bible on Sonnet) should come to about $5.

## Non-goals

- Editing the bible or the timeline by hand, or exporting them.
- Comparing them with the author's own notes. That's a follow-up: it would flag drift.
- Relationship graphs, and per-character timelines beyond the filter.
- Inferring facts the text doesn't state (ages computed from dates, for example).

## Grounding & safety

- Every event, telling and fact shows a quote verified against its chapter.
- Placements rest on verified time words, under the stricter rule in AC-6.
- Merges in the bible come from the model, so they could be wrong. The page shows every name an entry merges, so a wrong merge is visible, and the eval measures false merges.
- What reaches the model:
  - Extraction sees one section.
  - Placement sees event sentences and time words.
  - The bible call sees names and fact sentences, never whole chapters.
- Spend is shown and confirmed first. Unchanged chapters are not re-read.

## Interface

```
$ ./margin bible
Characters
  Maren Venn  (Maren)                    Chapters 1, 3, 5, 6, 7
    The lighthouse keeper's daughter.     Chapter 1   "His sister Maren watched it from the lamp gallery"
    She was nine in the winter of 1871.   Chapter 3   "Maren had been nine"
  …
Places
  Carrick Island                          Chapters 1, 3, 5
    …
12 characters · 6 places · made 26 Nov · ≈ $0.31
```

## Open questions

1. **One read or two.** Recommended: one regenerate builds both, which is cheaper. The alternative is separate buttons, so an author can refresh one without paying for the other.
2. **Bible model.** Recommended: Sonnet for the bible call, checked against Opus in the eval, as with placement.

## Decisions

- 2026-11-26: Approved with both recommendations: one regenerate builds the timeline and the bible; the bible call runs on Sonnet, checked against Opus in the eval.
- 2026-11-26 (build): A chapter's scene cap is at least 2, not 1. Short chapters often hold two scenes, and a cap of 1 dropped one. The cap stays about one per 700 words, at most 8.
- 2026-11-26 (build): The bible is graded in `eval/timeline/` rather than a separate `eval/bible/`, because both come from one regenerate. Code splits any part of a model's merge the names don't support. A name joins only when its name words are all in another's ("Odo", "Brother Odo"; "Mr Lusk", "Matthew Lusk"), and never when it clashes with one: different given names ("Maren Venn", "Tomas Venn") or different titles ("Mr Venn", "Mrs Venn"). A name that could join two entries ("Mrs Garrow" beside Nell and Kit Garrow) stays on its own. Facts alone never merge names, so a false merge needs the names themselves to agree.
- 2026-11-26 (eval): The timeline meets every bar. The bible meets every bar but the split rate (0.14 on Sonnet, 0.17 on Opus, bar 0.10), measured before titles were compared only with titles; most splits were titled names ("Mr Abernathy", "J. Abernathy"), which that fix merges. The owner chose not to rerun the eval for this PR. Sonnet stays the bible model: Opus scored the same and split more.
