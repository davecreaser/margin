"""Run the continuity-check eval by hand: python -m eval.check --help

Needs Elasticsearch on localhost:9200 (docker compose up -d) and, except for --dry-run,
ANTHROPIC_API_KEY in .env. Full results go to eval/runs/ (git-ignored); --save-baseline
writes numbers only to eval/check/baseline-<judge model>.json.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from eval.check.graders import ChapterCase, grade, score
from margin import check
from margin.config import Settings
from margin.manuscript import load_chapter
from margin.verify import quote_in_passage

HERE = Path(__file__).parent
RUNS = HERE.parent / "runs"
BAR = {
    "contradiction_recall": (0.80, ">="),
    "contradiction_precision": (0.80, ">="),
    "clean_false_alarms_max": (1, "<="),
    "counterfactual_recall": (1.0, ">="),
    "injection_recall": (1.0, ">="),
}


def load_cases(only: list[str] | None) -> list[ChapterCase]:
    cases = [ChapterCase.from_dict(d) for d in yaml.safe_load((HERE / "cases.yaml").read_text())]
    return [c for c in cases if not only or c.id in only or c.kind in only]


def run_case(
    case: ChapterCase, run: int, index: Any, retriever: Any, client: Any, s: Settings
) -> dict[str, Any]:
    chapter = load_chapter(HERE / "chapters" / case.file)
    started = time.perf_counter()
    events = list(check.run(chapter, retriever=retriever, store=index, client=client, settings=s))
    findings = [d for n, d in events if n == "finding"]
    done = next(d for n, d in events if n == "done")
    text = "\n\n".join(chapter.paragraphs)

    def passage_text(pid: str) -> str:
        return str(index.es.get(index=index.alias, id=pid)["_source"]["text"])

    displayed_failed = sum(1 for f in findings if not quote_in_passage(f["quote"], text)) + sum(
        1
        for f in findings
        for c in f["citations"]
        if not quote_in_passage(c["quote"], passage_text(c["passage_id"]))
    )
    return {
        "id": case.id,
        "kind": case.kind,
        "run": run,
        **grade(case, findings),
        "claims": done["claims"],
        "claim_quotes_failed": done["claim_quotes_failed"],
        "quotes_total": done["quotes_total"],
        "quotes_failed": done["quotes_failed"],
        "displayed_failed": displayed_failed,
        "counts": done["counts"],
        "words": chapter.words,
        "input_tokens": done["input_tokens"],
        "output_tokens": done["output_tokens"],
        "cost": done["cost"],
        "seconds": round(time.perf_counter() - started, 1),
        "findings": findings,
    }


def report(scores: dict[str, Any], results: list[dict[str, Any]], s: Settings) -> None:
    print(f"\nContinuity-check eval · claims {s.claims_model} · judge {s.judge_model} · "
          f"{len({r['id'] for r in results})} chapters × {max(r['run'] for r in results)} run(s)")  # fmt: skip
    print("\nBy chapter:")
    for r in results:
        print(f"  {r['id']:<26} caught {len(r['caught'])}/{r['planted']}  false alarms {len(r['false_alarms'])}  "
              f"claims {r['claims']}  {r['counts']}")  # fmt: skip
        for m in r["missed"]:
            print(f"      missed: {m}")
        for fa in r["false_alarms"]:
            print(f"      false alarm: {fa['claim']}  ({fa['quote']})")
    print("\nAgainst the bar:")
    for metric, (bar, op) in BAR.items():
        v = scores[metric]
        ok = v is not None and (v >= bar if op == ">=" else v <= bar)
        shown = "  -  " if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)
        print(f"  {metric:<26} {shown:>6}  bar {op}{bar}  {'meets' if ok else 'MISSES'}")
    for metric in (
        "consistent_accuracy",
        "new_accuracy",
        "manuscript_quote_failure_rate",
        "claim_quote_failure_rate",
    ):
        v = scores[metric]
        print(f"  {metric:<26} {'-' if v is None else f'{v:.3f}':>6}")
    print(f"  {'displayed_failed_citations':<26} {scores['displayed_failed_citations']:>6}")
    words = sum(r["words"] for r in results)
    cost = sum(r["cost"] for r in results)
    print(f"\nTokens: {sum(r['input_tokens'] for r in results):,} in / {sum(r['output_tokens'] for r in results):,} out"
          f" · cost ≈ ${cost:.2f} (≈ ${cost / words * 1000:.3f} per 1,000 words)"
          f" · mean {sum(r['seconds'] for r in results) / len(results):.1f}s per chapter")  # fmt: skip


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m eval.check", description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--runs", type=int, default=1, help="runs per chapter (the bar uses 3)")
    p.add_argument("--only", nargs="*", help="chapter ids or kinds")
    p.add_argument("--claims-model")
    p.add_argument("--judge-model")
    p.add_argument("--budget", type=float, default=15.0)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--save-baseline", action="store_true")
    args = p.parse_args()

    load_dotenv()
    s = Settings()
    if args.claims_model:
        s.claims_model = args.claims_model
    if args.judge_model:
        s.judge_model = args.judge_model
    cases = load_cases(args.only)
    chapters = {c.id: load_chapter(HERE / "chapters" / c.file) for c in cases}
    worst = args.runs * sum(check.worst_case_cost(ch.words, s) for ch in chapters.values())

    if args.dry_run:
        for c in cases:
            print(f"  {c.id:<26} {c.kind:<15} {chapters[c.id].words:>5} words  "
                  f"{len(c.contradictions)} planted contradictions")  # fmt: skip
        print(
            f"\n{len(cases)} chapters, {sum(len(c.contradictions) for c in cases)} planted contradictions"
        )
        print(f"Models: claims {s.claims_model}, judge {s.judge_model}")
        print(f"Worst-case cost ${worst:.2f} (every chapter at the claim cap of {s.claim_cap}, "
              f"every call at max_tokens); budget ${args.budget:.2f}")  # fmt: skip
        return
    if worst > args.budget and not args.yes:
        sys.exit(
            f"Worst-case cost ${worst:.2f} is above the budget ${args.budget:.2f}: use --budget or --yes"
        )

    from eval.ask.__main__ import ingest_eval_copy
    from margin.llm import AnthropicClient

    index, retriever = ingest_eval_copy(s)
    client = AnthropicClient()
    results = []
    for run in range(1, args.runs + 1):
        for c in cases:
            r = run_case(c, run, index, retriever, client, s)
            results.append(r)
            print(f"  run {run} {c.id:<26} caught {len(r['caught'])}/{r['planted']}  "
                  f"false alarms {len(r['false_alarms'])}  ${r['cost']:.3f}  {r['seconds']}s")  # fmt: skip
    scores = score(results)
    report(scores, results, s)

    RUNS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = RUNS / f"check-{stamp}-{s.judge_model}.json"
    out.write_text(
        json.dumps(
            {
                "claims_model": s.claims_model,
                "judge_model": s.judge_model,
                "scores": scores,
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\nFull results: {out.relative_to(HERE.parent.parent)}")
    if args.save_baseline:
        baseline = {
            "claims_model": s.claims_model,
            "judge_model": s.judge_model,
            "effort": {"claims": s.claims_effort, "judge": s.judge_effort},
            "passages_per_claim": s.check_top_k,
            "chapters": len(cases),
            "runs": args.runs,
            "date": time.strftime("%Y-%m-%d"),
            "scores": scores,
            "input_tokens": sum(r["input_tokens"] for r in results),
            "output_tokens": sum(r["output_tokens"] for r in results),
            "cost_usd": round(sum(r["cost"] for r in results), 4),
        }
        path = HERE / f"baseline-{s.judge_model}.json"
        path.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"Baseline: {path.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
