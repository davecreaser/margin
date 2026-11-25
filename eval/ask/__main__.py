"""Run the Ask eval by hand: python -m eval.ask --help

Needs Elasticsearch on localhost:9200 (docker compose up -d) and, except for --dry-run and
--retrieval-only, ANTHROPIC_API_KEY in .env. Full results go to eval/runs/ (git-ignored);
--save-baseline writes numbers only to eval/ask/baseline-<model>.json.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from eval.ask import corpus
from eval.ask.graders import Case, answer_correct, evidence_hit, retrieval_hit, score
from margin.config import PRICES, Settings, estimate_cost
from margin.steps.answer import PASSAGE_WORD_CAP
from margin.verify import quote_in_passage

HERE = Path(__file__).parent
RUNS = HERE.parent / "runs"
EVAL_INDEX = "margin-eval-passages"
PROMPT_OVERHEAD_TOKENS = 800  # system prompt, tags and question
TOKENS_PER_WORD = 1.4

BAR = {
    "retrieval_recall": 0.90,
    "answer_accuracy": 0.80,
    "abstention_accuracy": 0.90,
    "counterfactual_accuracy": 0.90,
    "injection_and_prose": 1.0,
}


def load_cases(only: list[str] | None) -> list[Case]:
    cases = [Case.from_dict(d) for d in yaml.safe_load((HERE / "cases.yaml").read_text())]
    if only:
        cases = [c for c in cases if c.id in only or c.category in only]
    return cases


def worst_case_cost(settings: Settings, model: str, calls: int) -> float:
    """Every call at max_tokens, every passage at the prompt cap, every case retried once."""
    input_tokens = settings.top_k * PASSAGE_WORD_CAP * TOKENS_PER_WORD
    input_tokens += PROMPT_OVERHEAD_TOKENS
    per_call = estimate_cost(model, int(input_tokens), settings.answer_max_tokens) or 0.0
    return per_call * calls * 2


def ingest_eval_copy(settings: Settings) -> Any:
    from margin.embedding import FastEmbedder
    from margin.index import ElasticIndex
    from margin.ingest import ingest
    from margin.retrieval import Retriever

    index = ElasticIndex(settings.es_url, EVAL_INDEX)
    embedder = FastEmbedder(settings.embed_model, settings.embed_cache)
    copy = corpus.build(RUNS / "manuscript")
    r = ingest(copy, index=index, embedder=embedder, settings=settings)
    print(f"Indexed the eval copy: {len(r.chapters)} chapters, {r.passages} passages "
          f"({settings.embed_model}, {r.seconds:.0f}s)")  # fmt: skip
    retriever = Retriever(
        index, embedder, settings.top_k, settings.candidates_per_method, settings.rrf_k
    )
    return index, retriever


def retrieval_only(cases: list[Case], retriever: Any, modes: list[str]) -> dict[str, Any]:
    """Recall@k by gold chapter (the spec's metric) and, stricter, by key facts retrieved."""
    scored = [c for c in cases if c.gold]
    recall: dict[str, Any] = {}
    for mode in modes:
        hits, evidence = [], []
        for c in scored:
            found = retriever.retrieve(c.question, mode=mode)
            hits.append(retrieval_hit(c, [r.passage.chapter for r in found]))
            evidence.append(evidence_hit(c, [r.passage.text for r in found]))
        recall[mode] = sum(bool(h) for h in hits) / len(hits)
        recall[f"{mode}_evidence"] = sum(bool(e) for e in evidence) / len(evidence)
        missing = [c.id for c, e in zip(scored, evidence, strict=True) if not e]
        print(
            f"  {mode:<6} recall@{retriever.top_k} {recall[mode]:.3f}  "
            f"evidence {recall[f'{mode}_evidence']:.3f}  missing: {', '.join(missing) or '-'}"
        )
    return recall


def run_case(
    case: Case, run: int, index: Any, retriever: Any, client: Any, settings: Settings
) -> dict[str, Any]:
    from margin import ask

    started = time.perf_counter()
    result = ask.run(
        case.question, retriever=retriever, store=index, client=client, settings=settings
    )
    statements = [s.text for s in result.statements]
    quotes = [c.quote for c in result.citations]
    return {
        "id": case.id,
        "run": run,
        "category": case.category,
        "question": case.question,
        "outcome": result.outcome,
        "correct": answer_correct(case, result.outcome, statements, quotes),
        "retrieval_hit": retrieval_hit(case, [r.passage.chapter for r in result.retrieved]),
        "evidence_hit": evidence_hit(case, [r.passage.text for r in result.retrieved]),
        "statements": statements,
        "citations": [{"passage_id": c.passage.id, "quote": c.quote} for c in result.citations],
        "dropped": result.dropped,
        "statements_shown": len(result.statements),
        "statements_dropped": sum(1 for d in result.dropped if not d["kept"]),
        "quotes_total": result.quotes_total,
        "quotes_failed": result.quotes_failed,
        # Re-check every shown citation independently; by construction this is 0.
        "displayed_failed": sum(
            1 for c in result.citations if not quote_in_passage(c.quote, c.passage.text)
        ),
        "model_error": result.model_error,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost": result.cost,
        "retrieved": [r.passage.id for r in result.retrieved],
        "seconds": round(time.perf_counter() - started, 2),
    }


def report(scores: Any, results: list[dict[str, Any]], model: str) -> None:
    print(f"\nAsk eval · {model} · {len({r['id'] for r in results})} cases × "
          f"{max(r['run'] for r in results)} run(s)")  # fmt: skip
    print("\nBy category:")
    for cat, value in scores.by_category.items():
        n = sum(1 for r in results if r["category"] == cat)
        print(f"  {cat:<15} {value:.2f}  (n={n})")
    print("\nAgainst the bar:")
    for metric, bar in BAR.items():
        value = getattr(scores, metric)
        verdict = "n/a" if value is None else ("meets" if value >= bar else "BELOW")
        shown = "  -  " if value is None else f"{value:.3f}"
        print(f"  {metric:<24} {shown}  bar {bar:.2f}  {verdict}")
    far = scores.false_abstention_rate
    print(f"  {'false_abstention_rate':<24} {far:.3f}  bar ≤0.10  {'meets' if far <= 0.10 else 'ABOVE'}"
          if far is not None else "")  # fmt: skip
    print(f"  {'displayed_failed':<24} {scores.displayed_failed_citations}")
    if scores.failed_citation_rate is not None:
        print(f"\nGrounding: {scores.statements_verified:.3f} of statements verified; "
              f"pre-verification failed-citation rate {scores.failed_citation_rate:.3f}")  # fmt: skip
    tokens_in = sum(r["input_tokens"] for r in results)
    tokens_out = sum(r["output_tokens"] for r in results)
    cost = sum(r["cost"] or 0 for r in results)
    mean_s = sum(r["seconds"] for r in results) / len(results)
    print(f"Tokens: {tokens_in:,} in / {tokens_out:,} out · cost ≈ ${cost:.2f} · "
          f"mean {mean_s:.1f}s per question")  # fmt: skip
    failed = sorted({r["id"] for r in results if not r["correct"]})
    print(f"Failed cases: {', '.join(failed) or 'none'}")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m eval.ask", description=__doc__.split("\n")[0])
    p.add_argument(
        "--dry-run", action="store_true", help="list cases and worst-case cost; no calls"
    )
    p.add_argument("--retrieval-only", action="store_true", help="score retrieval; no model calls")
    p.add_argument("--retrieval", choices=["hybrid", "bm25", "knn", "all"], default="all")
    p.add_argument("--model", default=None, help="answer model (default: from config)")
    p.add_argument("--runs", type=int, default=1, help="runs per case (the bar uses 3)")
    p.add_argument("--only", nargs="*", help="case ids or categories")
    p.add_argument("--budget", type=float, default=15.0, help="refuse above this worst case ($)")
    p.add_argument("--yes", action="store_true", help="run even above the budget")
    p.add_argument("--save-baseline", action="store_true")
    args = p.parse_args()

    load_dotenv()  # ANTHROPIC_API_KEY for the SDK; never printed
    settings = Settings()
    if args.model:
        settings.answer_model = args.model
    model = settings.answer_model
    cases = load_cases(args.only)
    calls = len(cases) * args.runs
    worst = worst_case_cost(settings, model, calls)

    if args.dry_run:
        for c in cases:
            print(f"  {c.id:<12} {c.category:<15} {c.question}")
        counts: dict[str, int] = {}
        for c in cases:
            counts[c.category] = counts.get(c.category, 0) + 1
        print(f"\n{len(cases)} cases: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        price = PRICES.get(model)
        print(
            f"Model: {model} (${price[0]}/${price[1]} per M tokens)" if price else f"Model: {model}"
        )
        print(f"{calls} model calls; worst-case cost ${worst:.2f} "
              f"(each call at max_tokens={settings.answer_max_tokens}, retried once); budget ${args.budget:.2f}")  # fmt: skip
        return

    index, retriever = ingest_eval_copy(settings)
    modes = ["hybrid", "bm25", "knn"] if args.retrieval == "all" else [args.retrieval]
    print("Retrieval:")
    recall = retrieval_only(cases, retriever, modes)
    if args.retrieval_only:
        return

    if worst > args.budget and not args.yes:
        sys.exit(f"Worst-case cost ${worst:.2f} is above the budget ${args.budget:.2f}: "
                 "use --budget or --yes")  # fmt: skip
    from margin.llm import AnthropicClient

    client = AnthropicClient()
    results = []
    for run in range(1, args.runs + 1):
        for c in cases:
            r = run_case(c, run, index, retriever, client, settings)
            results.append(r)
            mark = "✓" if r["correct"] else "✗"
            print(
                f"  {mark} run {run} {c.id:<12} {r['outcome']:<18} {' '.join(r['statements'])[:80]}"
            )
    scores = score(results)
    report(scores, results, model)

    RUNS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = RUNS / f"ask-{stamp}-{model}.json"
    out.write_text(
        json.dumps(
            {"model": model, "recall": recall, "scores": asdict(scores), "results": results},
            indent=2,
        )
    )
    print(f"\nFull results: {out.relative_to(HERE.parent.parent)}")
    if args.save_baseline:
        baseline = {
            "model": model,
            "effort": settings.answer_effort,
            "embed_model": settings.embed_model,
            "top_k": settings.top_k,
            "cases": len(cases),
            "runs": args.runs,
            "date": time.strftime("%Y-%m-%d"),
            "retrieval_recall": recall,
            "scores": asdict(scores),
            "input_tokens": sum(r["input_tokens"] for r in results),
            "output_tokens": sum(r["output_tokens"] for r in results),
            "cost_usd": round(sum(r["cost"] or 0 for r in results), 4),
        }
        path = HERE / f"baseline-{model}.json"
        path.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"Baseline: {path.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
