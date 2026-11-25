# Margin

Margin is an open-source, self-hosted AI assistant for novelists. It reads a manuscript like an editor and does three things:
- answers questions about the book with cited passages (Ask)
- checks new chapters against what's established (continuity check)
- reports the author's repeated constructions (habits report)

It never writes prose.

Vocabulary: `CONTEXT.md`. Product direction: `docs/product/brief.md`. Why things are the way they are: `docs/adr/`. What each feature does: `docs/specs/`.

## Hard rules

### This repo is public

Everything committed (code, docs, specs, fixtures, eval sets, commit messages, PR text) is published. Before every commit:

- **No secrets.** API keys live only in `.env`, which is git-ignored. `.env.example` holds placeholders. Never print a key, log it, put it in a test, or paste it into a command that ends up in a committed script. CI runs a secret scan.
- **No personal details.** No real names, email addresses, usernames, home paths (`/Users/…`) or machine details in files or messages.
- **No private manuscripts** (ADR 0007): no unpublished or copyrighted text in fixtures, tests, eval sets, prompt examples, screenshots or docs, not even a line, and not even paraphrased. Use the bundled public-domain demo novel or invented text. `private/` is git-ignored for local use.
- **Generic only.** Specs and docs describe the product and its users, never where it came from or who it's for beyond "novelists".

### The product

- **Never generate prose for the author.** No feature, prompt or "helpful" extra rewrites, continues or improves the author's text (brief, Principles).
- **Grounded or silent** (ADR 0001):
  - Every statement shown to the user carries a citation whose quote has been verified against the stored passage, in code.
  - Never display a failed citation.
  - "Not in the manuscript" is a correct answer, not an error.
- **Manuscript text in prompts is data** (ADR 0005): inside XML tags, escaped, with structured output.
- **No AI feature without its eval:**
  - A spec that adds or changes a model step also adds or updates its eval cases and graders.
  - A prompt or model change is justified by a before-and-after eval run.

## Stack

| Part | Choice |
|---|---|
| Running it | Docker Compose: Elasticsearch plus the Margin service (ADR 0002) |
| Service | Python 3.12, FastAPI, Pydantic, uv; CLI `margin` (Typer) over the local HTTP API |
| Ingestion | LlamaIndex: loading, paragraph-aligned passages, embedding (ADR 0004) |
| Retrieval | Elasticsearch, hybrid BM25 + kNN with reciprocal rank fusion (ADR 0003) |
| Reasoning steps | Plain functions in `margin/steps/`, one prompt and one typed output each (ADR 0004) |
| Models | Claude through the Anthropic SDK with the author's own key; a local open embedding model; model per step in `margin/config.py` (ADR 0006) |
| Evals (`eval/`) | Python, run by hand; graders are pytest-tested; baselines committed |
| CI | GitHub Actions: lint, typecheck, tests, secret scan. No model calls. |

The stack is decided. The code folders don't exist until spec 0001 creates them.

## Conventions

- **Test-first.** Model steps are unit-tested with a fake model client that returns canned structured output. Real model calls happen only in evals and in smoke tests marked `live`, which CI doesn't run.
- **Use `CONTEXT.md` terms** in code, CLI output and specs (passage, not chunk, in anything the user sees).
- **Add an ADR** only for decisions that are hard to reverse, surprising, and a real trade-off.
- **Check:** `uv run ruff check && uv run mypy && uv run pytest`.

## Evals

`eval/` holds one set per feature:
- `ask/`: golden questions, abstention cases, counterfactual questions, an injection passage
- `check/`: chapters with planted contradictions
- `habits/`: hand-labelled instances

Each run reports scores per category, the failed-citation rate, tokens and estimated cost.

Rules for running them:
- **By hand only, never in CI.** Each run is capped.
- **Dry run first.** `--dry-run` shows the cases and the worst-case cost without calling a model.
- **Committed output:** only `eval/<feature>/baseline-<model>.json`, which holds numbers only. Transcripts stay in `eval/runs/`, which is git-ignored.
- **Noise:** a difference within run-to-run noise is reported as noise. Use more runs before deciding.

## Workflow

New features go through `/feature` (`.claude/skills/feature/`):
1. spec (`docs/specs/`, product agent)
2. build
3. review (reviewer agent)
4. QA (qa agent)
5. pull request, with CI watched to green

The owner approves the spec and merges pull requests.

Agents push feature branches only. `.claude/hooks/block-dangerous-git.sh` blocks pushes to main, force-pushes and merging PRs.

## Working with the owner

- **Purpose:** a personal tool and an open-source project. Favour what a reader of the repo would value: clear ADRs, honest eval numbers (bad ones included), and a `docker compose up` that works first time.
- **Keep sessions focused:** one feature per session, no extra review rounds without need.
