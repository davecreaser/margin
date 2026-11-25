# Margin

An open-source, self-hosted AI assistant that reads your manuscript the way a good editor does. It never writes a word of your book.

- **Ask:** ask your book a question and get an answer with the passage that proves it, or "not in the manuscript".
- **Continuity check:** check a new or revised chapter against everything you've already established, with both sides of every contradiction quoted.
- **Habits report** (later): see the constructions you repeat across the book, counted chapter by chapter.

Every quote Margin shows is checked word for word against your text, in code, before it is shown. Everything runs on your own computer: your manuscript and its index stay local, and only the passages a question needs are sent to the model, with your own API key.

## Quick start

You need Docker (with about 3 GB of memory free) and an Anthropic API key.

```sh
git clone <this repo> margin && cd margin
cp .env.example .env            # then put your ANTHROPIC_API_KEY in .env
docker compose up -d            # Elasticsearch + the Margin service
./margin ingest --demo          # index the bundled demo novel
./margin ask "What did Denry pay for the Widow Hullins's cottage?"
```

```
Denry bought the Widow Hullins's cottage for forty-five pounds. [1]
He paid thirty pounds in cash, with the remaining balance deducted gradually from his weekly commission. [2]

[1] Chapter 2, ¶ 95–96
    "he actually did buy the Widow Hullins's half-a-crown-a-week cottage for forty-five pounds"
[2] Chapter 2, ¶ 95–96
    "of which he paid thirty pounds in cash and arranged that the balance should be deducted gradually from his weekly commission"

claude-opus-5-5 · 7,334 in / 292 out · ≈ $0.035
```

And when the book doesn't say:

```
$ ./margin ask "What colour were Denry's eyes?"
Not in the manuscript.

Closest passages:
  Chapter 11, ¶ 115–129 "Our two stars simultaneously eclipsed!" said Denry, as the Clutterbucks…
  …
```

The demo novel is *The Card* by Arnold Bennett (1911), in the public domain (`src/margin/demo/SOURCE.md`).

### Checking a chapter

```
$ ./margin check manuscripts/market-day.md
Checking "Market Day" (175 words) against the-card: 12 chapters, 212 passages.
Worst case: claims + up to 40 judging calls with claude-sonnet-5-5 ≈ $1.26.
Found 12 claims.

CONTRADICTS
2. The mule's age: twelve in the claim, but seven in an earlier chapter.
   This chapter, ¶ 1      "The mule, aged twelve and as wise as any alderman"
   Chapter 6, ¶ 1–2       "It was aged seven, and it had cost Denry ten pounds."
…
4 contradictions · 1 consistent · 7 new  (--all to list them)
```

Each claim's quote is verified against your chapter and each manuscript quote against the passage, as with Ask; a contradiction the manuscript can't be shown to make is reported as new. Margin never suggests how to fix anything.

### Your own manuscript

Put it in `manuscripts/` (git-ignored, mounted read-only into the service), either as a folder with one `.md` or `.txt` file per chapter, or as one `.md`, `.txt` or `.docx` file with chapter headings (Markdown headings, or lines like `Chapter 3` or `CHAPTER III`):

```sh
./margin ingest manuscripts/my-novel
./margin ask "What colour is the door of the inn?"
```

Ingesting again replaces the index completely. Margin never writes to your files.

### Commands

| Command | What it does |
|---|---|
| `./margin status` | Whether Margin is ready, what is indexed, and what is sent to the model |
| `./margin ingest <path>` / `--demo` | Index a manuscript |
| `./margin ask "<question>"` | Answer with verified citations, or "Not in the manuscript." |
| `./margin ask … --show-passages` | Also print the retrieved passages, with BM25, kNN and fused scores |
| `./margin ask … --debug` | Also print statements dropped because their quotes didn't verify |
| `./margin check <chapter>` | Check a new chapter against the manuscript: contradictions in full, consistent and new as counts |
| `./margin check … --replaces 6` | Check a revised chapter 6 against the rest of the book, not its old version |
| `./margin check … --all` / `--yes` | List consistent and new claims too / don't ask before spending |

The same is available over HTTP at `http://localhost:8000` (`GET /status`, `POST /ingest`, `POST /ask` as server-sent events), with OpenAPI docs at `/docs`.

## How it works

1. **Ingest.** The manuscript is split into chapters, and each chapter into passages of whole paragraphs (about 150–400 words) by a LlamaIndex node parser. Passages are embedded locally (`BAAI/bge-small-en-v1.5`, ONNX on CPU) and stored in Elasticsearch.
2. **Retrieve.** A question runs as BM25 keyword search and kNN vector search; the two rankings are merged with reciprocal rank fusion. Names are BM25's strength, paraphrase is kNN's.
3. **Answer.** Claude gets the question and the top 8 passages, inside XML tags and escaped, as data. It returns structured output: short statements, each with a passage id and an exact quote.
4. **Verify.** Every quote is matched against the stored passage (ignoring whitespace, quote marks, dashes and case, never words). A statement with no verified quote is dropped. If nothing survives, the answer is "Not in the manuscript."

Design decisions are in `docs/adr/`, the feature spec in `docs/specs/0001-ask.md`, and the vocabulary in `CONTEXT.md`.

## Evals

Every AI feature ships with an eval (`eval/`). The continuity-check eval (`python -m eval.check`) checks eight invented chapters with 21 planted contradictions, including a clean chapter, one written with the published book's values for facts the eval copy changes, and one containing injected instructions. The Ask eval has 60 hand-written cases on a copy of the demo novel with ten facts deliberately changed, so a model answering from memory of the published book gets them wrong. It covers single and multi-passage facts, rare names, paraphrase, questions the book doesn't answer, an injected-instructions passage, and requests to write prose.

```sh
uv sync
uv run python -m eval.ask --dry-run          # cases and worst-case cost, no calls
uv run python -m eval.ask --retrieval-only   # BM25 vs kNN vs hybrid, no model calls
uv run python -m eval.ask                    # the full eval (needs ANTHROPIC_API_KEY)
```

Results are in `eval/ask/baseline-<model>.json`; see `docs/specs/0001-ask.md` for the bar.

## Development

```sh
uv sync
uv run ruff check && uv run mypy && uv run pytest
```

Tests use a fake model client; nothing in CI calls a model.

MIT licensed.
