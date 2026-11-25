# Margin

Margin reads a manuscript like an editor. It answers questions about the book with cited passages, checks new chapters for continuity, and reports the author's repeated habits. It never writes prose. Product direction is in `docs/product/brief.md`.

## Language

### The book

**Manuscript**:
The book Margin reads: its chapters in order, and optionally the author's notes. Margin only ever reads it.
_Avoid_: document, corpus (except in eval code), book file

**Chapter**:
One titled section of the manuscript, in reading order. Interludes and prologues are chapters too.
_Avoid_: section, part (a part groups chapters)

**Passage**:
The unit Margin retrieves and cites. It is a run of whole paragraphs inside one chapter, with that chapter's number and the paragraph range.
_Avoid_: chunk (fine in indexing code, never in the UI), document, node

**Notes**:
The author's own material about the book: character lists, timelines, decisions. Notes can be cited, but they are always labelled as notes, never as the text.
_Avoid_: story bible (in the UI), wiki

### Grounding

**Citation**:
A pointer from something Margin says to a passage, with an exact quote from it. The quote is checked word for word before it is shown; a quote that can't be found is a **failed citation**, never displayed.
_Avoid_: source, reference, footnote

**Grounded**:
Supported by at least one verified citation. Everything Margin states must be grounded.

**Not in the manuscript**:
Margin's answer when retrieval finds no passage that supports an answer. It is a correct result, not an error.
_Avoid_: no results, unknown, I don't know (in the UI)

### Features

**Ask**:
Asking the manuscript a question in plain words and getting a grounded **answer** or "not in the manuscript".
_Avoid_: chat, search, query (in the UI)

**Continuity check**:
Checking a new or revised chapter against the rest of the manuscript.

**Claim**:
One factual statement a checked chapter makes about the story: who, what, when, where, what something looks like, or who knows what.
_Avoid_: fact, assertion

**Finding**:
The verdict on one claim, with citations: **contradicts** (the manuscript says otherwise), **consistent** (the manuscript agrees), or **new** (the manuscript doesn't say).
_Avoid_: error, issue, flag (as a noun)

**Habit**:
A construction the author repeats across the manuscript, such as "with the X of a man who…". Each **instance** is shown in context.
_Avoid_: tic (in the UI), cliché, mistake

**Kind**:
A family of habits in the habits report: similes, "as if / as though", stock gestures, filter verbs, crutch words, sentence openers, repeated phrases.
_Avoid_: category, family (in the UI)

**Habits report**:
The habits found in the manuscript, grouped by kind and counted by chapter.

**House style**:
The rules an author keeps for the manuscript, as in a style sheet: spelling variety, quotation marks, scene-break and chapter-heading formats, numbers, dashes, ellipses, and watched words. Margin checks only the rules the author sets.
_Avoid_: style guide, lint (in the UI)

**Mismatch**:
A place where the text differs from a house-style rule, with its chapter and paragraph.
_Avoid_: violation, error, mistake

### Evaluation

**Eval**:
A fixed set of cases with known answers, run by hand against the real pipeline and graded on results. Each feature has its own.

**Golden question**:
An Ask eval case: a question, the chapters whose passages prove the answer, and the answer's key facts.

**Counterfactual edit**:
A deliberate change to the eval copy of the demo novel (a name, a number, a date) so that the right answer differs from the published book. A pipeline that answers from the model's memory instead of the manuscript fails it.

**Planted contradiction**:
A deliberate inconsistency written into a continuity-check eval chapter, with the passage it contradicts.

**Baseline**:
The committed numbers from an eval run (no text, no transcripts), which later runs are compared against.
