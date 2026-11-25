# 0007: Habits report and house style

Status: approved

## Problem

By the time a book is in revision, the author has read every sentence many times and no longer sees how it is built. A favourite simile shape, a character who shrugs in every scene, a "suddenly" on every other page, a phrase that turns up in chapter 3 and again in chapters 11 and 27: none of it shows up on a re-read, and a search only finds what you already suspect. Novelists also keep a style sheet (British or American spelling, double or single quotes, how scene breaks look, whether numbers are spelled out), and a long book drafted over months, partly pasted from other files, drifts from it. Today they find out from an editor or a proofreader. Margin already holds the whole indexed manuscript, so it can count these things across every chapter, show each one in place, and leave the judgement to the author. It does this without a model, for free.

## User stories

- **US-1** As an author, I want to see the constructions I repeat (simile shapes, "as if", stock gestures, filter verbs, crutch words, sentence openers), counted per chapter and per 1,000 words, so I can see what I lean on and where.
- **US-2** As an author, I want to see every instance in its sentence and open its passage, so I can judge each one myself.
- **US-3** As an author, I want Margin to find phrases I repeat that I would never think to search for.
- **US-4** As an author, I want to set my house style once and see every place where the text doesn't match it, with its location.
- **US-5** As an author, I want to run this as often as I like, free, on exactly what is indexed (excluded tabs left out), and without an API key.
- **US-6** As an author of a long book, I want the report to stay quick and readable at 150,000 words.

## Acceptance criteria

Terms are from `CONTEXT.md`. This spec adds **kind**, **house style** and **mismatch** to it (see Decisions).

- **AC-1 Free and on request.**
  - `margin habits`, `margin style` and the page's **Habits** view work from the indexed manuscript only. Each chapter is rebuilt from its indexed passages, as the timeline does, so the report reads exactly what Ask and Check see. Tabs excluded at ingest (spec 0003) are never indexed, so they are never counted.
  - No model is called and no API key is needed. With `ANTHROPIC_API_KEY` unset, the whole feature works.
  - It is computed when asked for, never at ingest. There is no cost line and no confirmation question, because nothing is spent. The CLI header says "Free: no model calls."
- **AC-2 Kinds of habit.** Each habit belongs to one of six kinds and is found by a deterministic pattern. Every kind has listed near-misses that must not match.

  | Kind | Habits (one per row in the report) | Matches | Must not match |
  |---|---|---|---|
  | Similes | "like a …", "as … as …" | "expanding from the narrow gloom of her black carriage like a magic vision" (demo); "as pale as candle wax" | "I'd like a word"; "as soon as", "as well as", "as far as", "as much as", "as long as" |
  | As if / as though | "as if", "as though" | "They seemed afraid of her, as though she was recovering from influenza" (demo) | "as if" is never a near-miss; "though" alone ("Though it rained") |
  | Stock gestures | shrugged, nodded, sighed, smiled, grinned, frowned, winced, rolled eyes, raised an eyebrow, bit lip, jaw tightened or clenched, ran a hand through hair, let out a breath … didn't know … holding, heart pounded or raced | all inflections of the verb ("nods", "nodding"), any pronoun ("bit her lip", "bit his lip") | the noun ("with more than an aunt's smile", "a curt nod") |
  | Filter verbs | felt, saw, heard, noticed, realised (or realized), seemed, watched, wondered | "He felt profoundly thankful" (demo); "she could hear the sea" | "a felt hat"; "the saw"; "seemed" is only matched with a subject |
  | Crutch words | just, really, very, suddenly, somehow, actually | "Just behind her was his employer" (demo) | "a just man", "the very man" |
  | Sentence openers | runs of three or more consecutive sentences in one paragraph starting with the same word; "-ing" openers | "He went. He stopped. He listened."; "Turning to the door, she …" | "Nothing moved."; "Morning came."; "During the night …" |

  Each match is a whole-word, case-insensitive match. Spelling variants are folded together (realised and realized are one habit).
- **AC-3 Repeated phrases.** Phrases the author repeats far more often than chance, across chapters, found with no fixed list.
  - Candidates are word sequences of 3 to 6 words inside one sentence, lower-cased, with punctuation removed. Pronouns are folded, so "her jaw tightened" and "his jaw tightened" count as one phrase.
  - A phrase is reported when it:
    - occurs at least 3 times (config `phrase_min_count`)
    - occurs in at least 2 chapters (config `phrase_min_chapters`)
    - occurs at least `phrase_min_ratio` times more often than its words' frequencies in this manuscript predict
    - contains at least one word that is neither a common function word nor a character name. A name is a word that is capitalised in at least 90% of its uses mid-sentence. So "Mr Duncalf said" and "at the same time" are never reported.
  - A phrase inside a longer reported phrase with nearly the same count (80% or more) is folded into it, so "the edge of the" is not listed beside "on the edge of the bed".
  - Each phrase is shown in its most common written form, with its variants ("her jaw tightened · also: his jaw tightened (3)"). Phrases are ranked by count, then by how much more often than chance they occur. The top 50 are listed and the rest are available on request.
- **AC-4 Counts.**
  - For every habit the report gives a total, a rate per 1,000 words of the manuscript, and per-chapter counts and rates (using the chapter's indexed word count, as in spec 0005).
  - Kinds are listed in the order of AC-2, with repeated phrases last. Within a kind, habits are sorted by total.
  - A habit found fewer than 2 times in the whole manuscript is left out. A kind with no habits left shows "None found", which is a correct result and not an error.
  - Each instance is marked as **dialogue** (inside quotation marks in its paragraph, including a quotation that runs on from the previous paragraph) or **narration**. Every total also gives the narration figure: "48 (31 in narration)".
- **AC-5 Instances in context.** Every instance has:
  - its chapter (named as the author names it, e.g. "Interlude II"), its paragraph number, and the passage that holds it
  - its sentence, with the matched words highlighted. A sentence longer than 60 words is trimmed around the match with "…".
  - In the page, clicking an instance opens the passage panel with the match highlighted.

  The matched words are an exact span of the stored passage text, and a test checks this against the stored passage for every instance in the demo report, using the same verifier as citations (ADR 0001). An instance that fails is dropped and counted in the server log; it is never shown.
- **AC-6 Never prose, never a verdict.**
  - The report contains only the author's own text and fixed labels written in code.
  - It never suggests a rewrite, an alternative word or a "fix". It never ranks the author against other writers or a norm.
  - It never uses the words "bad", "weak", "overused", "too many", "avoid", "instead", "consider" or "try". A test scans the CLI and page strings for these words.
  - The rate shading in the page uses one neutral colour, never red.
  - Example: the page shows "nodded · 112 · 1.5 per 1,000 words". It never shows "nodded is overused; try showing the reaction instead".
- **AC-7 House style settings.**
  - Each manuscript has its own house style: the rules a novelist commonly keeps in a style sheet. Every rule is optional, and a rule that isn't set is not checked.
  - It is stored in the data volume as `style/<manuscript>.toml`, never in the repo.
  - It can be set three ways:
    - `margin style set <rule> <value>`
    - `margin style --from my-style.toml`: the CLI reads the local file and sends it to the service
    - the page's house-style form
  - An unknown rule or value is rejected with the allowed values, and nothing is saved.
  - **Detect.** `margin style --detect` and the page's **Start from my manuscript** button show, for each rule, the form the manuscript mostly uses and its share ("quotes: double-straight, 97% of quotation marks"). They save nothing until the author chooses to use them.
- **AC-8 House style rules.** Each rule is deterministic, and each has listed cases it must not report.

  | Rule | Values | Reported | Not reported |
  |---|---|---|---|
  | `spelling` | `british`, `british-oxford` (-ize, otherwise British), `american` | words from a curated list of about 300 pairs written in the other variety: "color", "center", "traveled", "gray", "realize" under `british` | pairs where both spellings are correct in the chosen variety (practice/practise, licence/license, program/programme, tire/tyre, curb/kerb, check/cheque, story/storey, which are left off the list); a capitalised word mid-sentence (a proper name such as "the Mercer Center") |
  | `quotes` | `double-curly`, `double-straight`, `single-curly`, `single-straight` | a straight mark when curly is set, or a curly mark when straight is set (apostrophes included); a quotation opened with the other primary mark | a single quotation nested inside a double one (and the reverse); elisions ('em, 'tis, 'twas, 'til, '67) |
  | `scene_break` | the exact marker line, e.g. `* * *` | a scene-break line that differs ("***", "#", "~ ~ ~") | |
  | `chapter_heading` | a template: `Chapter {n}`, `Chapter {n}: {title}`, `{roman}`, `{title}` and similar, plus `heading_exempt` (default: Prologue, Epilogue, Interlude *, Part *) | a chapter heading that doesn't fit, e.g. "Chapter Four" when `{n}` (numerals) is set | headings matching `heading_exempt` |
  | `numbers` | `spell-under-100`, `spell-under-10`, `off` | a numeral under the limit in the text: "10 yards" | times ("9:30"), dates ("the 27th May 1867"), decimals, percentages, money ("£5"), and headings |
  | `dash` | `closed-em` (word—word), `spaced-em` (word — word), `spaced-en` (word – word), `double-hyphen` (word--word) | any dash used as a dash in another form | hyphenated words, and en dashes between numbers ("1867–1870") |
  | `ellipsis` | `character` (…), `three-dots` (...), `spaced-dots` (. . .) | the other forms | |
  | `watch` | a list of words or phrases | every use, as instances with counts per chapter | |

  A watched word that never occurs is listed as "not in the manuscript", which is a correct result.
- **AC-9 Scene breaks are recorded at ingest.**
  - Ingest skips scene-break lines when it builds passages, and still does, so Ask, Check and the passages don't change. From this spec on, it also records each marker line's text and position (chapter, and the paragraph it follows) with the chapter's metadata. These are not passages and are not embedded.
  - A Google Docs re-ingest records them from the fetched text, including for tabs whose passages are reused.
  - An index made before this spec has no records, so the scene-break rule says "Re-ingest to check scene breaks" and the other rules run as usual.
  - A scene break drawn as a Google Docs horizontal rule, or as blank lines only, has no text and is not checked.
- **AC-10 Mismatches.**
  - Each house-style mismatch has its rule, chapter, paragraph and sentence, with the offending characters highlighted, and it opens the passage panel like an instance.
  - Several mismatches of one rule in one paragraph are one row with a count ("Chapter 4 ¶ 12 · 3 straight quotation marks"), so one pasted paragraph doesn't flood the list.
  - Totals are given per rule and per chapter.
  - A manuscript that matches every rule that is set shows "Matches your house style: 7 rules checked." With no rules set, it shows "No house style set", with the detect button.
- **AC-11 The CLI.** `margin habits`:
  - With no options, it prints the header (manuscript, words, chapters, "Free: no model calls") and then each kind. Each kind shows its top 5 habits with total, narration total, rate per 1,000 words and the three chapters with the highest rate, then "+ N more" when there are more.
  - `--all` lists every habit, and every repeated phrase past the top 50.
  - `--show "<habit>"` prints that habit's per-chapter table and then every instance (chapter, paragraph, dialogue or narration, sentence). An unknown habit name lists the closest habit names.
  - `--narration` counts and lists narration only.

  `margin style`:
  - Prints the rules that are set, then mismatches grouped by rule, each with chapter, paragraph and sentence.
  - `set`, `--from` and `--detect` work as in AC-7. `watch add|remove "<phrase>"` edits the watched list.
- **AC-12 The page.** A **Habits** view sits beside Ask, Check, Timeline, Progress and Manuscript. It has two sections.
  - **Habits** lists each kind and its habits with totals and rates. Each habit has a strip with one cell per chapter in reading order, shaded by rate in one neutral colour; hovering a cell shows "Chapter 7 · 9 · 2.1 per 1,000 words".
    - Clicking a habit lists its instances, 50 at a time, with **Show more**.
    - Clicking a chapter cell narrows the list to that chapter.
    - A **Narration only** toggle recounts everything without dialogue.
  - **House style** shows the rules as a form (choices for each rule, a text list for watched words), **Start from my manuscript**, **Save**, and the mismatches grouped by rule.
  - Instances and mismatches open the passage panel.
- **AC-13 Empty, errors and limits.**
  - With an empty index, the existing message is shown: "Nothing is indexed yet: run ./margin ingest --demo, or ./margin ingest <path>". The page shows the same.
  - With Elasticsearch down, the existing "Search index isn't running: start it with docker compose up -d".
  - A style file that isn't valid TOML is rejected with its line number, and the saved style is unchanged.
  - A manuscript with no habit found at all shows "No repeated constructions found in 3 chapters (1,240 words)."
  - No model error can occur; the feature has no model path.
- **AC-14 Long manuscript.**
  - On a 150,000-word manuscript (about 500 passages), `margin habits` and `GET /habits` answer in under 10 seconds on a laptop, and `margin style` likewise.
  - A paragraph of 20,000 characters with no sentence punctuation is processed in under 1 second (no runaway patterns).
  - `GET /habits` returns counts only. Instances come from a separate paged endpoint, so the first response stays small whatever the book's length.
  - The result is cached in memory by the indexed text's hash until the next ingest.
- **AC-15 HTTP.**
  - `GET /habits?narration=false` returns the kinds, habits, totals, rates and per-chapter counts, with no instances.
  - `GET /habits/instances?habit=<id>&chapter=<n>&offset=0&limit=50&narration=false` returns the instances: chapter, label, paragraph, passage id, sentence, match span and dialogue flag.
  - `GET /style` returns the rules and whether scene breaks are recorded. `PUT /style` saves the rules or returns 422 with the allowed values.
  - `GET /style/detect` returns the detected form and share for each rule. `GET /style/mismatches` returns mismatches grouped by rule.

Traceability: US-1 → AC-2, AC-4, AC-11, AC-12. US-2 → AC-5, AC-6, AC-11, AC-12. US-3 → AC-3. US-4 → AC-7, AC-8, AC-9, AC-10, AC-11, AC-12. US-5 → AC-1, AC-13. US-6 → AC-14, AC-15.

## Eval

`eval/habits/`. There is no model step, so the eval is deterministic. It runs by hand like the others (`uv run python -m eval.habits`, which prints the table) and also as ordinary pytest tests: `eval/` is in `testpaths`, so CI checks the bar on every push at no cost. If the optional naming step (Open question 1) is ever added, it gets its own by-hand eval with a dry run and a budget, and never runs in CI.

**Cases.**

| Set | Contents | What it tests |
|---|---|---|
| Invented chapters | 3 chapters written for the eval, about 1,000 words each. Every kind is planted densely (at least 30 gold instances per kind across the set), with at least 10 near-miss traps per kind from the AC-2 "must not match" column. 6 repeated phrases are planted across the chapters (one with pronoun variants: "her jaw tightened" / "his jaw tightened"), along with common phrases that must not be reported ("at the same time", "in front of the", "Mr Ashby said"). | Recall and precision per kind; the near-misses; repeated phrases |
| Demo excerpt | Chapter 1 of the bundled demo novel, *The Card*, from its start to its third scene break (about 1,800 words). Every instance of every kind is labelled by hand. | Real prose with an older idiom: "Mrs" without a full stop, "--" dashes, "quite" and "just" used freely |
| Planted house-style edits | `edits.yaml` changes the demo excerpt in a few places: one "recognised" becomes "recognized", one "--" becomes "—", one "..." becomes "…", one "* * *" becomes "***", one quotation gets curly marks, and "ten yards" becomes "10 yards". The style is set to the demo's own (british, double-straight, `* * *`, double-hyphen, three-dots, spell-under-100). | Each rule finds exactly the planted mismatches, and the rest of the excerpt raises none |
| Counterfactual spelling | An invented chapter in two copies, one British and one American, differing only in 15 listed words, including a proper name ("the Mercer Center") and an ambiguous pair (practice/practise) that must not be reported. | With `british`, the American copy reports exactly the 15 words; with `american`, the British copy does; each copy is clean under its own setting |
| Abstention (clean) | An invented chapter of plain prose with no planted habits, and one that follows every house-style rule. | "None found" and "Matches your house style" are correct results: any instance or mismatch is a false positive |
| Adversarial | A 20,000-character paragraph with no sentence punctuation; Markdown emphasis and HTML-like text inside sentences; nested quotation marks; a paragraph that opens a quotation and doesn't close it. | No runaway patterns; the dialogue flag; quotation rules |
| Demo top 20 | The top 20 repeated phrases on the full demo novel (74,000 words), each labelled by hand as a real repeated phrase or not, in `phrases.yaml`. | Precision of repeated phrases on a whole book |
| Timing | The full demo, and a 150,000-word manuscript built by concatenating the demo with itself (used for timing only). | AC-14 |

Every label uses invented text or the public-domain demo only (ADR 0007).

**Labelling.** `labels.yaml` begins with a short guide for each kind. For example, a gesture is a verb form and not a noun, and a filter verb has a character as its subject. Labels are made from the text before the tool's output is seen. After the first run, each disagreement is reviewed. A label is changed only if it misapplied the guide, and every change is recorded in Decisions, as spec 0006 did.

**Grading:** on results, not on wording.
- A found instance matches a gold instance when both are in the same text and paragraph and the found span overlaps the gold phrase. Each gold instance matches at most once.
- A run of openers is matched by its paragraph and its first sentence.
- **Recall** is matched gold over all gold. **Precision** is matched found over all found, per kind.
- A planted repeated phrase is found when a reported phrase's written form or variants contain it.
- If the algorithm changes and a phrase in the demo top 20 has no label, the test fails with "label these", so the labels can't silently go stale.
- House style is graded per rule in the same way, on mismatches.

**Metrics and bar.** The baseline is `eval/habits/baseline.json` (numbers only; there is no model in the name).
- **Each habit kind:** recall at least 0.90 and precision at least 0.85, with the invented and demo sets pooled. Both are also reported per set.
- **Repeated phrases:** at least 5 of the 6 planted phrases found; none of the must-not-report phrases reported; demo top-20 precision at least 0.70.
- **House style:** recall and precision 1.0 per rule on the planted edits and the counterfactual spelling copies, and 0 mismatches on the clean controls. These are exact rules, so any miss is a bug.
- **Instances that fail verification:** 0.
- **Time:** full demo under 5 seconds and 150,000 words under 10 seconds, reported by the runner. The CI test uses a 60-second ceiling, which only catches runaway patterns, because CI timing is noisy.
- **Also reported:** gold, found and matched counts per kind, and the dialogue-flag accuracy on the labelled excerpt.

**Cost:** $0. No model is called. A full run takes seconds.

## Non-goals

- **The model step that names groups of repeated phrases.** This conflicts with the brief's wording; see Open question 1.
- Suggestions, rewrites, alternative words or synonyms, in any form (brief, Principles).
- Grammar, punctuation or readability scoring; passive-voice detection; sentence-length statistics; comparison with other authors or "typical" rates.
- Grouping different words by meaning ("jaw tightened" with "jaw clenched" is grouped only because both are on the gesture list; free phrases are grouped only by pronoun folding).
- Editing the habit lists themselves. Authors add their own habits as watched words.
- Limits per watched word ("at most 3 per book"). Every use is listed, and the author judges.
- Habits report history over time, or "since last ingest" comparisons.
- Checking a chapter that isn't indexed (as `margin check` does). The report covers the indexed manuscript only.
- Scene breaks with no text (horizontal rules, blank lines), and checking the author's notes against house style.
- Languages other than English.

## Grounding & safety

- **Grounded.** Every instance and mismatch is an exact span of a stored passage, found by code and checked with the citation verifier before it is shown (AC-5). Counts are counts of those spans. "None found" and "not in the manuscript" (for a watched word) are correct results.
- **Model.** None. No manuscript text leaves the machine, and nothing is sent to any provider. The feature works without an API key.
- **No prose.** The report shows only the author's text and fixed labels from code. A test checks that its strings contain no suggestion or verdict words (AC-6).
- **Spend:** $0 per request. There is nothing to cap or confirm.
- **Public repo.** The eval chapters are invented. The demo excerpt and the demo top 20 come from the public-domain novel. The spelling list, gesture list and other word lists are compiled by hand for this repo and are not copied from a published style guide. The style file lives in the data volume, never in the repo.

## Interface

```
$ ./margin habits
Habits in The Lantern Road: 82,410 words, 18 chapters. Free: no model calls.

Similes                         total  narration  per 1,000  highest in
  like a …                         61         44       0.74  Chapter 7, Chapter 3, Interlude I
  as … as …                        23         20       0.28  Chapter 12, Chapter 2, Chapter 9
As if / as though
  as if                            48         41       0.58  Chapter 4, Chapter 7, Chapter 1
  as though                         9          9       0.11  Chapter 15, Chapter 3, Chapter 8
Stock gestures
  nodded                          112         98       1.36  Chapter 9, Chapter 4, Chapter 10
  shrugged                         37         33       0.45  Chapter 2, Chapter 9, Chapter 16
  …                                + 6 more
Filter verbs …
Crutch words …
Sentence openers
  "-ing" openers                   54         54       0.66  Chapter 5, Chapter 6, Chapter 1
  runs of the same first word      17         15       0.21  Chapter 11, Chapter 3, Chapter 14
Repeated phrases
  "the salt in the air"             9          9       0.11  in 6 chapters
  "her jaw tightened"               7          7       0.08  in 5 chapters · also: his jaw tightened (3)
  + 41 more: ./margin habits --all

$ ./margin habits --show "like a"
like a … · 61 in The Lantern Road (0.74 per 1,000 words), 44 in narration
  Chapter 1    4 · 1.2 per 1,000      Chapter 2    3 · 0.8 per 1,000      …
  Chapter 1    ¶ 4    The fog came in like a slow tide over the causeway.
  Chapter 1    ¶ 9    dialogue   "You look like a drowned cat," said Maren.
  …

$ ./margin style
House style for The Lantern Road: 6 rules set.
spelling: british · 3 mismatches
  Chapter 4    ¶ 12   She pulled the gray shawl tighter.                       gray
  Chapter 9    ¶ 3    The color had gone out of the sky by six.                color
quotes: double-curly · 2 paragraphs
  Interlude II ¶ 1    3 straight quotation marks   "Not tonight," he said …
scene_break: * * * · 1 mismatch
  Chapter 6    after ¶ 18   ***
watch: "a beat" · 14 uses in 9 chapters · "orbs" · not in the manuscript

$ ./margin style set quotes double-curly
Saved: quotes = double-curly.
$ ./margin style set quotes curly
Unknown quotes style "curly": use double-curly, double-straight, single-curly or single-straight.

$ ./margin style --detect
What The Lantern Road mostly uses (nothing saved):
  spelling   british         94% of listed words
  quotes     double-curly    97% of quotation marks
  dash       closed-em       99% of dashes
  …
Use these: ./margin style --detect --save

$ ./margin habits                          # empty index
Nothing is indexed yet: run ./margin ingest --demo, or ./margin ingest <path>
$ ./margin habits                          # Elasticsearch down
Search index isn't running: start it with docker compose up -d
$ ./margin style                           # an index made before this spec
… scene_break: Re-ingest to check scene breaks.
```

There is no cost confirmation, because nothing is spent; the header says so. On a 150,000-word manuscript the output has the same shape: the top 5 per kind, with `--all` for the rest (AC-11, AC-14).

The style file (`style/<manuscript>.toml` in the data volume, or any local file passed with `--from`):

```toml
spelling = "british"            # british | british-oxford | american
quotes = "double-curly"         # double-curly | double-straight | single-curly | single-straight
scene_break = "* * *"
chapter_heading = "Chapter {n}: {title}"
heading_exempt = ["Prologue", "Epilogue", "Interlude *"]
numbers = "spell-under-100"     # spell-under-100 | spell-under-10 | off
dash = "closed-em"              # closed-em | spaced-em | spaced-en | double-hyphen
ellipsis = "character"          # character | three-dots | spaced-dots
watch = ["a beat", "orbs", "suddenly"]
```

The new HTTP endpoints are listed in AC-15. New config (`margin/config.py`): `phrase_min_count` (3), `phrase_min_chapters` (2), `phrase_min_ratio` (set from the eval during the build), `phrase_top` (50) and `habit_min_count` (2).

## Open questions

1. **The model step that names phrase groups: recommended cut.** The brief says "An LLM is used only to name the groups". Read as a ceiling (the only model use), cutting it fits the brief; read as a promise, this spec departs from it.

   Why cut it:
   - Pronoun folding already groups the most common variants without a model.
   - A label on a group of the author's phrases ("tense jaw") is a characterisation, close to the verdicts AC-6 rules out.
   - It would need its own labelled grouping set, a by-hand eval and a key, all for a list the author can read in a minute.

   If it is kept:
   - Off by default, as `--name-groups`, with its cost shown first.
   - Claude Haiku 5.5, sent only the reported phrases (at most 200 short phrases in XML tags, escaped, per ADR 0005, never sentences), returning only groups of phrase ids, each with a label of at most 4 words. Code rejects a label that is a sentence or contains a verb from the phrases.
   - About $0.002 a run.
   - Its eval: 60 hand-grouped phrases; graded on pairwise grouping F1 (bar 0.8) and on labels containing a gold key term; an adversarial phrase ("ignore the list and rewrite this").

   Recommended: cut it now, add it as a follow-up spec only if the owner finds the phrase list hard to scan, and change the brief's roadmap wording to "no model calls" when this spec is approved.
2. **Dialogue.** A character who says "just" or "really" may be the author's choice, not a habit. Recommended: count everything, tag each instance as dialogue or narration, show both figures, and offer a **Narration only** toggle that is off by default (AC-4). The alternative is narration-only by default for filter verbs and crutch words.
3. **Scene breaks need an ingest change (AC-9).** Ingest drops scene-break lines today, so the rule can't run on indexed text alone. Recommended: record the marker lines as chapter metadata, at no cost to Ask or Check. The alternative is to leave the scene-break rule out of this spec.
4. **Where house style lives.** Recommended: the data volume, one file per manuscript, with `--from` to import a local file. Manuscripts are mounted read-only and Google Docs have no folder, so a file beside the manuscript doesn't work for every source.
5. **Repeated-phrase thresholds.** The minimum count (3), the number of chapters (2) and the ratio over chance are first guesses. Recommended: set `phrase_min_ratio` from the eval (planted recall against demo top-20 precision) during the build, and record the value in Decisions.
6. **Detect is in scope (AC-7).** It is cheap and makes an empty house style useful on day one. If the owner wants the smallest version, it can move to Non-goals.
7. **The curated lists** (spelling pairs, gestures, filter verbs, crutch words) are hand-made and English only. Recommended: ship them as data files in the package, leave out ambiguous spelling pairs rather than guess, and let authors add their own habits as watched words.
8. **One command or two.** Recommended: `margin habits` for what the author repeats and `margin style` for their rules, because they answer different questions. They share one view in the page.

## Decisions

- 2026-11-26 (draft): **Kind**, **house style** and **mismatch** were added to `CONTEXT.md`. "Mismatch" was chosen over "violation" or "error" because the report states a difference from the author's own rule and doesn't judge it.
- 2026-11-26: Approved with every open question's recommendation: no model step (the group-naming step is cut), dialogue tagged with a Narration-only toggle off by default, scene-break markers recorded at ingest, style rules in the data volume with `--from` to import, separate `habits` and `style` commands sharing one view, thresholds set from the eval, detect in scope, hand-made word lists.
