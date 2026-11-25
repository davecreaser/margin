# Margin: product brief

Status: approved by the owner, 2026-11-25. Every spec should fit this brief. If one doesn't, change the brief on purpose or change the spec.

## In one sentence

Margin is an open-source AI assistant for novelists that reads your manuscript the way a good editor does. It answers questions about your book with the passage that proves the answer. It checks a new chapter against what you've already established. It shows you the habits in your prose that you've stopped noticing. It never writes a word of your book.

## Ambition

A self-hosted tool that the owner uses on their own manuscripts, and an open-source repo worth reading. It runs on your own computer with `docker compose up`. There is no hosted service, no accounts and no users to support.

Success looks like this:
- the owner uses it while revising a real novel
- a stranger can clone it and have it answering questions about the bundled demo novel in a few minutes
- every AI feature has eval numbers behind it

## Who it's for

**Novelists in revision**, especially on long books with many characters, a timeline, and notes kept separately from the text. They lose track of what they've established:
- the colour of a character's eyes
- which day a scene falls on
- what a character already knows
- what an object looks like when it's described again ten chapters later

They also lose track of their own tics: a favourite simile shape or stock gesture that turns up a dozen times across a book without them noticing.

## What we want people to say

1. **"It found the contradiction before my editor did."** The continuity check flags a new chapter's claims that contradict the manuscript, quoting both sides.
2. **"I could ask my own book a question."** Ask gives an answer with the passage that proves it. When the book doesn't say, Margin says "not in the manuscript".
3. **"I didn't know I did that."** The habits report groups the author's repeated constructions and shows each instance in place.

## Principles (non-negotiable)

- **The author writes the book.** Margin never generates, rewrites or "improves" prose. It finds, quotes, compares and counts. A suggestion is a pointer to a passage, not replacement text.
- **Grounded or silent.** Every claim Margin makes cites a passage. Every quote is checked word for word against the manuscript before it is shown. If it can't ground an answer, it says so. Wrong and confident is the worst outcome; "not in the manuscript" is fine (ADR 0001).
- **Measured, not hoped for.** No AI feature ships without its eval:
  - a fixed set of cases with known answers
  - graders that check results, not wording
  - a committed baseline

  Model choices and prompt changes are decided by the numbers.
- **Your manuscript stays yours.**
  - Margin runs on your machine.
  - The index and embeddings stay local.
  - Only the passages a request needs are sent to the model provider, with your own API key.
  - Manuscript text is data, never instructions (ADR 0005).
  - The repo and its evals use only a public-domain novel and invented text (ADR 0007).
- **Easy to run, cheap to use.** One command to start. Deterministic code does what it can (the habits report is mostly not an LLM). The larger model is used only where the eval shows it's needed. Every command shows what it will cost before calling a model when the cost could be noticeable.

## Not doing

- Writing, rewriting, continuing or summarising prose for the author.
- A hosted service, accounts, teams or sharing.
- A full web app. The interface is a CLI, a local HTTP API and a small local web page over that API (spec 0004).
- Formats beyond plain text, Markdown and .docx (others later, if ever).
- Fine-tuning. Retrieval, prompting and model selection come first; fine-tuning is considered only if the eval shows a ceiling they can't pass.

## Roadmap

Each step is a spec in `docs/specs/` and ships with its eval.

1. **Ask** (spec 0001, done): `docker compose up` brings up Elasticsearch and the service. `margin ingest` indexes a manuscript, either the bundled demo novel or your own. `margin ask "…"` returns an answer with verified citations, or "not in the manuscript". This is the walking skeleton: every layer, thin. Eval: golden questions, abstention cases, counterfactual questions and an injection passage.
2. **Continuity check** (spec 0002, done): `margin check chapter.md` extracts the chapter's factual claims, retrieves the passages they touch, and sorts each claim into contradicts, consistent, or new. Eval: chapters with planted contradictions, measuring how many it catches and how many false alarms it raises.
3. **Google Docs and a living manuscript** (spec 0003, done): ingest a Google Doc, one chapter per tab; re-ingesting embeds only what changed.
4. **Web page** (spec 0004, done): Ask, Check and Manuscript in the browser at `localhost:8000`.
5. **Progress tracker** (spec 0005, done): word counts per chapter at every ingest, against the author's target, over time. No model calls.
6. **Timeline** (spec 0006, done): the story's events in story order, each with its quote, generated only when the author asks, with the cost shown first.
7. **Habits report** (spec 0007): `margin habits` finds repeated constructions across the manuscript (simile shapes, "as if/as though", stock gestures) with deterministic patterns, groups and counts them by chapter, and shows each instance in context. No model calls: it's free to run. It also checks the author's own house style, with deterministic rules the author sets: spelling variety (British or American), scene-break and heading formats, and similar. Eval: hand-labelled instances, measuring how many it finds and how many are real.

## How it compares

| Alternative | What it does well | Where Margin differs |
| --- | --- | --- |
| General chatbots with a pasted manuscript | Flexible | Long books don't fit, answers aren't cited, and nothing is measured; they confidently mix up details |
| Generation-first AI writing assistants | Drafting and rewriting | Margin refuses to write prose; it checks, it doesn't co-write |
| Series bibles and wikis by hand | Exact, under the author's control | Margin builds the evidence from the text itself and checks new chapters against it |
| Grammar and style checkers | Sentence-level fixes | Margin's habits are book-level patterns, counted across chapters |
