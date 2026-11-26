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
_Avoid_: wiki; and **bible**, which is what Margin builds from the text

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

**Story notes**:
The timeline and the bible together. One regenerate builds both, only when the author asks, after showing the cost.

**Timeline**:
The story's scenes in story order, grouped into periods. Reading order is the order the book tells them.

**Scene**:
One stretch of story in one place and time, as one sentence with a verified quote. A chapter gives a handful.
_Avoid_: event (in the UI), action, beat

**Card**:
One moment of the story on the timeline. When several chapters tell the same moment, each is a **telling** on the same card. A card is placed only by verified time words: its own scenes', or a scene's beside them in the same chapter.

**Period**:
A group of cards that happen together ("Day 2 · the fourth of March", "1871"), in one **band**: **before the story** (backstory), the **story** itself (numbered from Day 1, the start of the main action), or **after**.

**Not placed**:
A scene the text gives no time for. It is shown apart, never guessed.
_Avoid_: unknown, undated (in the UI)

**Bible**:
Margin's index of the book's characters and places, built from the text. Each **entry** has the names the text uses for it, facts each quoted from the text, and the chapters that name it.
_Avoid_: wiki, cast list (that is the author's notes)

**Habit**:
A construction the author repeats across the manuscript, such as "with the X of a man who…". Each **instance** is shown in context.
_Avoid_: tic (in the UI), cliché, mistake

**Habits report**:
The habits found in the manuscript, grouped and counted by chapter.

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
