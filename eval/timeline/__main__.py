"""Run the timeline eval by hand: python -m eval.timeline --help

Needs ANTHROPIC_API_KEY in .env, except for --dry-run. No Elasticsearch: chapters are read from
the files. Each run extracts events afresh; every placement model in --place-models then places
the same extracted events, so the models are compared on identical input. Full results go to
eval/runs/ (git-ignored); --save-baseline writes numbers only to
eval/timeline/baseline-<place model>.json.
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from eval.ask import corpus
from eval.timeline.graders import Gold, grade, score
from margin import timeline
from margin.config import Settings
from margin.manuscript import Chapter, Manuscript, load, load_chapter
from margin.passages import split
from margin.verify import quote_in_passage

HERE = Path(__file__).parent
RUNS = HERE.parent / "runs"
BAR = {
    "event_recall": 0.80,
    "pairwise_order": 0.90,
    "placement_accuracy": 0.80,
    "counterfactual": 1.0,
    "injection": 1.0,
}


def load_sets(only: list[str] | None) -> dict[str, tuple[list[Chapter], list[Gold]]]:
    cases = yaml.safe_load((HERE / "cases.yaml").read_text())
    sets: dict[str, tuple[list[Chapter], list[Gold]]] = {}
    if not only or "novella" in only:
        files = sorted((HERE / "novella").glob("*.md"))
        chapters = [load_chapter(f) for f in files]
        for n, c in enumerate(chapters, 1):
            c.number = n
        sets["novella"] = (chapters, [Gold.from_dict(d) for d in cases["novella"]["events"]])
    if not only or "demo" in only:
        copy = corpus.build(RUNS / "manuscript")
        sets["demo"] = (load(copy).chapters, [Gold.from_dict(d) for d in cases["demo"]["events"]])
    return sets


def displayed_failed(t: dict[str, Any], chapters: list[Chapter]) -> int:
    text = {c.number: "\n\n".join(c.paragraphs) for c in chapters}
    shown = [e for p in t["periods"] for e in p["events"]] + t["unplaced"]
    bad = sum(1 for e in shown if not quote_in_passage(e["quote"], text[e["chapter"]]))
    by_id = {e["id"]: e for e in shown}
    bad += sum(
        1
        for p in t["periods"]
        for e in p["events"]
        for b in e["basis"]
        if not quote_in_passage(b["time"], text[by_id[b["id"]]["chapter"]], timeline.TIME_MIN_WORDS)
    )
    return bad


def run_set(
    name: str, chapters: list[Chapter], golds: list[Gold], s: Settings, client: Any
) -> dict[str, Any]:
    passages = split(Manuscript(name, chapters), s.min_passage_words, s.max_passage_words)
    started = time.perf_counter()
    events = list(timeline.regenerate(name, chapters, passages, client=client, settings=s))
    t = next(d for n, d in events if n == "done")
    return {
        "set": name,
        "place_model": s.place_model,
        **grade(golds, t),
        "events": t["events"],
        "failed": t["failed"],
        "displayed_failed": displayed_failed(t, chapters),
        "words": sum(c.words for c in chapters),
        "input_tokens": t["input_tokens"],
        "output_tokens": t["output_tokens"],
        "cost": t["cost"],
        "seconds": round(time.perf_counter() - started, 1),
        "timeline": t,
    }


def report(model: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    scores = score(results)
    print(f"\nPlacement {model}:")
    for r in results:
        print(f"  run {r['run']} {r['set']:<8} found {r['found']}/{r['gold']}  "
              f"placement {r['placement_right']}/{r['placement_total']}  order {r['pairs_right']}/{r['pairs']}  "
              f"cf {r['counterfactual']}  injection {r['injection']}  "
              f"{r['placed']} placed / {r['unplaced']} not  ${r['cost']:.3f}  {r['seconds']}s")  # fmt: skip
    for metric, bar in BAR.items():
        v = scores[metric]
        ok = v is not None and v >= bar
        print(f"  {metric:<20} {'-' if v is None else f'{v:.3f}':>6}  bar >={bar}  {'meets' if ok else 'MISSES'}")  # fmt: skip
    words = sum(r["words"] for r in results)
    events = sum(r["events"] for r in results)
    failed = sum(r["failed"]["quotes"] for r in results)
    scores.update(
        {
            "events_per_1000_words": round(events / words * 1000, 2),
            "event_quote_failure_rate": round(failed / (events + failed), 3) if events else None,
            "time_words_failed": sum(r["failed"]["times"] for r in results),
            "ungrounded_placements": sum(r["failed"]["ungrounded"] for r in results),
            "displayed_failed_citations": sum(r["displayed_failed"] for r in results),
        }
    )
    for name in sorted({r["set"] for r in results}):  # a long book is where placement gives up
        rs = [r for r in results if r["set"] == name]
        events_in_set = sum(r["placed"] + r["unplaced"] for r in rs)
        scores[f"not_placed_rate_{name}"] = (
            round(sum(r["unplaced"] for r in rs) / events_in_set, 3) if events_in_set else None
        )
    for k in ("not_placed_rate", "events_per_1000_words", "event_quote_failure_rate",
              "time_words_failed", "ungrounded_placements", "displayed_failed_citations",
              "not_placed_rate_novella", "not_placed_rate_demo"):  # fmt: skip
        print(f"  {k:<28} {scores[k]}")
    return scores


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m eval.timeline", description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--runs", type=int, default=1, help="the bar uses 3")
    p.add_argument("--only", nargs="*", help="novella and/or demo")
    p.add_argument("--place-models", nargs="+", help="placement models to compare")
    p.add_argument("--budget", type=float, default=8.0)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--save-baseline", action="store_true")
    args = p.parse_args()

    load_dotenv()
    base = Settings()
    models = args.place_models or [base.place_model]
    sets = load_sets(args.only)
    worst = 0.0
    with tempfile.TemporaryDirectory() as empty:
        for chapters, _ in sets.values():
            for m in models:
                s = base.model_copy(update={"place_model": m, "data_dir": Path(empty)})
                est = timeline.estimate(chapters, Path(empty), s)
                worst += est["worst_case"] if m == models[0] else est["placement"]
    worst *= args.runs
    for name, (chapters, golds) in sets.items():
        print(f"  {name:<8} {len(chapters)} chapters, {sum(c.words for c in chapters):,} words, "
              f"{len(golds)} gold events")  # fmt: skip
    print(f"Extraction {base.events_model}; placement {', '.join(models)}; {args.runs} run(s)")
    print(f"Worst-case cost ${worst:.2f} (every chapter at the event cap, every call at "
          f"its max_tokens); budget ${args.budget:.2f}")  # fmt: skip
    if args.dry_run:
        return
    if worst > args.budget and not args.yes:
        sys.exit(f"Worst case ${worst:.2f} is above the budget: use --budget or --yes")

    from margin.llm import AnthropicClient

    client = AnthropicClient()
    results: dict[str, list[dict[str, Any]]] = {m: [] for m in models}
    for run in range(1, args.runs + 1):
        with tempfile.TemporaryDirectory() as data_dir:  # fresh extraction each run
            for name, (chapters, golds) in sets.items():
                for m in models:  # later models reuse this run's cached extraction
                    s = base.model_copy(update={"place_model": m, "data_dir": Path(data_dir)})
                    r = {"run": run, **run_set(name, chapters, golds, s, client)}
                    results[m].append(r)
                    print(f"  run {run} {name:<8} {m:<18} found {r['found']}/{r['gold']}  "
                          f"placement {r['placement_right']}/{r['placement_total']}  "
                          f"${r['cost']:.3f}  {r['seconds']}s")  # fmt: skip

    RUNS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for m in models:
        scores = report(m, results[m])
        out = RUNS / f"timeline-{stamp}-{m}.json"
        out.write_text(json.dumps({"scores": scores, "results": results[m]}, indent=2))
        print(f"  Full results: {out.relative_to(HERE.parent.parent)}")
        if args.save_baseline:
            rs = results[m]
            baseline = {
                "events_model": base.events_model,
                "place_model": m,
                "effort": {"events": base.events_effort, "place": base.place_effort},
                "sets": sorted({r["set"] for r in rs}),
                "runs": args.runs,
                "date": time.strftime("%Y-%m-%d"),
                "scores": scores,
                "input_tokens": sum(r["input_tokens"] for r in rs),
                "output_tokens": sum(r["output_tokens"] for r in rs),
                "cost_usd": round(sum(r["cost"] for r in rs), 4),
                "note": "Extraction cost is counted under the first placement model only.",
            }
            path = HERE / f"baseline-{m}.json"
            path.write_text(json.dumps(baseline, indent=2) + "\n")
            print(f"  Baseline: {path.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
