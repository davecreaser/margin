"""Run the story-notes eval (timeline and bible) by hand: python -m eval.timeline --help

Needs ANTHROPIC_API_KEY in .env, except for --dry-run. No Elasticsearch: chapters are read from
the files. Each run extracts afresh and places with the configured placement model; every bible
model in --bible-models then groups the same extracted names, so the models are compared on
identical input. Full results go to eval/runs/ (git-ignored); --save-baseline writes numbers only
to eval/timeline/baseline-bible-<bible model>.json.
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
from eval.timeline.graders import (
    Entity,
    Gold,
    bible_gold,
    grade,
    grade_bible,
    resolve,
    score,
    score_bible,
)
from margin import timeline
from margin.check import Usage
from margin.config import Settings
from margin.manuscript import Chapter, Manuscript, load, load_chapter
from margin.passages import split
from margin.verify import quote_in_passage

HERE = Path(__file__).parent
RUNS = HERE.parent / "runs"
BAR = {
    "placement_accuracy": 0.80,
    "pairwise_order": 0.90,
    "merge": 0.70,
    "backstory": 0.80,
    "granularity": 0.80,
    "counterfactual": 1.0,
    "injection": 1.0,
}
BIBLE_BAR = {
    "character_recall": 0.90,
    "place_recall": 0.80,
    "fact_recall": 0.70,
    "counterfactual": 1.0,
}


class Set:
    def __init__(self, name: str, chapters: list[Chapter], case: dict[str, Any]) -> None:
        self.name = name
        self.chapters = chapters
        self.golds = resolve([Gold.from_dict(d) for d in case["events"]], chapters)
        self.injection: str | None = case.get("injection")
        bible = case.get("bible", {})
        self.bible: list[Entity] = bible_gold(bible)
        self.bible_cf: dict[str, str] | None = bible.get("counterfactual")


def load_sets(only: list[str] | None) -> list[Set]:
    cases = yaml.safe_load((HERE / "cases.yaml").read_text())
    sets = []
    for name in ("novella", "novella2"):
        if only and name not in only:
            continue
        chapters = [load_chapter(f) for f in sorted((HERE / cases[name]["dir"]).glob("*.md"))]
        for n, c in enumerate(chapters, 1):
            c.number = n
        sets.append(Set(name, chapters, cases[name]))
    if not only or "demo" in only:
        sets.append(Set("demo", load(corpus.build(RUNS / "manuscript")).chapters, cases["demo"]))
    return sets


def displayed_failed(t: dict[str, Any], chapters: list[Chapter]) -> int:
    """Quotes shown that don't verify against their chapter: tellings, time words, facts."""
    text = {c.number: "\n\n".join(c.paragraphs) for c in chapters}
    tellings = [e for p in t["periods"] for c in p["cards"] for e in c["tellings"]] + t["unplaced"]
    bad = sum(1 for e in tellings if not quote_in_passage(e["quote"], text[e["chapter"]]))
    by_id = {e["id"]: e for e in tellings}
    bad += sum(
        1
        for p in t["periods"]
        for c in p["cards"]
        for b in c["basis"]
        if not quote_in_passage(b["time"], text[by_id[b["id"]]["chapter"]], timeline.TIME_MIN_WORDS)
    )
    entries = t["bible"]["characters"] + t["bible"]["places"]
    bad += sum(
        1
        for e in entries
        for f in e["facts"]
        if not quote_in_passage(f["quote"], text[f["chapter"]])
    )
    return bad


def run_set(st: Set, s: Settings, client: Any, bible_models: list[str]) -> dict[str, Any]:
    """One regenerate with the first bible model; the others regroup the same names."""
    passages = split(Manuscript(st.name, st.chapters), s.min_passage_words, s.max_passage_words)
    started = time.perf_counter()
    events = list(timeline.regenerate(st.name, st.chapters, passages, client=client, settings=s))
    t = next(d for n, d in events if n == "done")
    gran = st.name != "demo"  # demo gold covers too few scenes per chapter to judge
    out = {
        "set": st.name,
        **grade(st.golds, t, injection=st.injection, gran=gran),
        "events": t["events"],
        "failed": t["failed"],
        "displayed_failed": displayed_failed(t, st.chapters),
        "words": sum(c.words for c in st.chapters),
        "input_tokens": t["input_tokens"],
        "output_tokens": t["output_tokens"],
        "cost": t["cost"],
        "seconds": round(time.perf_counter() - started, 1),
        "timeline": t,
        "bible": {bible_models[0]: {**grade_bible(st.bible, t["bible"], st.bible_cf), "cost": 0.0}},
    }
    per_chapter = {c.number: timeline._cached(s.data_dir, c, s) for c in st.chapters}
    if all(v is not None for v in per_chapter.values()):
        for m in bible_models[1:]:
            usage = Usage()
            b = timeline.build_bible(
                st.chapters,
                per_chapter,  # type: ignore[arg-type]
                passages,
                client=client,
                s=s.model_copy(update={"bible_model": m}),
                usage=usage,
            )
            out["bible"][m] = {
                **grade_bible(st.bible, b, st.bible_cf),
                "cost": round(usage.cost, 4),
            }
            out["bible"][m]["raw"] = b
    return out


def report(results: list[dict[str, Any]]) -> dict[str, Any]:
    scores = score(results)
    print("\nTimeline:")
    for r in results:
        print(f"  run {r['run']} {r['set']:<8} found {r['found']}/{r['gold']}  "
              f"placement {r['placement_right']}/{r['placement_total']}  order {r['pairs_right']}/{r['pairs']}  "
              f"merge {r['merged']}/{r['merge_pairs']}  backstory {r['backstory']}  cf {r['counterfactual']}  "
              f"injection {r['injection']}  {r['placed']} placed / {r['unplaced']} not  ${r['cost']:.3f}  {r['seconds']}s")  # fmt: skip
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
    for name in sorted({r["set"] for r in results}):
        rs = [r for r in results if r["set"] == name]
        sub = score(rs)
        for k in ("placement_accuracy", "pairwise_order", "event_recall", "not_placed_rate"):
            scores[f"{k}_{name}"] = sub[k]
    for k, v in scores.items():
        if k not in BAR:
            print(f"  {k:<32} {v}")
    return scores


def report_bible(model: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = [(r, r["bible"][model]) for r in results if model in r["bible"]]
    rs = [b for _, b in pairs]
    scores = score_bible(rs)
    skipped = len(results) - len(pairs)
    note = f" ({skipped} set runs skipped: an extraction failed)" if skipped else ""
    print(f"\nBible {model}:{note}")
    scores["set_runs_skipped"] = skipped
    for r, b in pairs:
        print(f"  run {r['run']} {r['set']:<8} characters {b['characters_found']}/{b['characters']}  "
              f"places {b['places_found']}/{b['places']}  split {b['split']}  false merges {b['false_merges']}  "
              f"facts {sum(b['facts'])}/{len(b['facts'])}  cf {b['counterfactual']}  {b['entries']} entries")  # fmt: skip
    checks = {**BIBLE_BAR}
    for metric, bar in checks.items():
        v = scores[metric]
        ok = v is not None and v >= bar
        print(f"  {metric:<20} {'-' if v is None else f'{v:.3f}':>6}  bar >={bar}  {'meets' if ok else 'MISSES'}")  # fmt: skip
    fm, sr = scores["false_merges"], scores["split_rate"]
    print(f"  {'false_merges':<20} {fm:>6}  bar 0      {'meets' if fm == 0 else 'MISSES'}")
    print(f"  {'split_rate':<20} {sr if sr is not None else '-':>6}  bar <=0.10  "
          f"{'meets' if sr is not None and sr <= 0.10 else 'MISSES'}")  # fmt: skip
    scores["split_failed_merges_by_code"] = sum(r["failed"]["split"] for r in results)
    return scores


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m eval.timeline", description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--runs", type=int, default=1, help="the bar uses 3")
    p.add_argument("--only", nargs="*", help="novella, novella2 and/or demo")
    p.add_argument("--bible-models", nargs="+", help="bible models to compare")
    p.add_argument("--budget", type=float, default=8.0)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--save-baseline", action="store_true")
    args = p.parse_args()

    load_dotenv()
    base = Settings()
    models = args.bible_models or [base.bible_model]
    sets = load_sets(args.only)
    worst = 0.0
    with tempfile.TemporaryDirectory() as empty:
        for st in sets:
            for m in models:
                s = base.model_copy(update={"bible_model": m, "data_dir": Path(empty)})
                est = timeline.estimate(st.chapters, Path(empty), s)
                worst += est["worst_case"] if m == models[0] else est["bible"]
    worst *= args.runs
    for st in sets:
        print(f"  {st.name:<8} {len(st.chapters)} chapters, {sum(c.words for c in st.chapters):,} "
              f"words, {len(st.golds)} gold scenes, {len(st.bible)} gold names")  # fmt: skip
    print(f"Extraction {base.events_model}; placement {base.place_model}; bible "
          f"{', '.join(models)}; {args.runs} run(s)")  # fmt: skip
    print(f"Worst-case cost ${worst:.2f} (every chapter at its scene cap, every call at its "
          f"max_tokens); budget ${args.budget:.2f}")  # fmt: skip
    if args.dry_run:
        return
    if worst > args.budget and not args.yes:
        sys.exit(f"Worst case ${worst:.2f} is above the budget: use --budget or --yes")

    from margin.llm import AnthropicClient

    client = AnthropicClient()
    results: list[dict[str, Any]] = []
    for run in range(1, args.runs + 1):
        with tempfile.TemporaryDirectory() as data_dir:  # fresh extraction each run
            for st in sets:
                s = base.model_copy(update={"bible_model": models[0], "data_dir": Path(data_dir)})
                r = {"run": run, **run_set(st, s, client, models)}
                results.append(r)
                print(f"  run {run} {st.name:<8} found {r['found']}/{r['gold']}  "
                      f"placement {r['placement_right']}/{r['placement_total']}  "
                      f"${r['cost']:.3f}  {r['seconds']}s")  # fmt: skip

    RUNS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    t_scores = report(results)
    out = RUNS / f"timeline-{stamp}.json"
    out.write_text(json.dumps({"scores": t_scores, "results": results}, indent=2))
    print(f"  Full results: {out.relative_to(HERE.parent.parent)}")
    for m in models:
        b_scores = report_bible(m, results)
        if args.save_baseline:
            extra = sum(r["bible"][m]["cost"] for r in results if m in r["bible"])
            baseline = {
                "events_model": base.events_model,
                "place_model": base.place_model,
                "bible_model": m,
                "effort": {
                    "events": base.events_effort,
                    "place": base.place_effort,
                    "bible": base.bible_effort,
                },  # fmt: skip
                "sets": sorted({r["set"] for r in results}),
                "runs": args.runs,
                "date": time.strftime("%Y-%m-%d"),
                "timeline": t_scores,
                "bible": b_scores,
                "input_tokens": sum(r["input_tokens"] for r in results),
                "output_tokens": sum(r["output_tokens"] for r in results),
                "cost_usd": round(sum(r["cost"] for r in results) + extra, 4),
                "note": "Extraction, placement and the first bible model's call are one regenerate; "
                "other bible models regroup the same names and add only their bible calls. "
                "Timeline scores are the same in every file.",
            }
            path = HERE / f"baseline-bible-{m}.json"
            path.write_text(json.dumps(baseline, indent=2) + "\n")
            print(f"  Baseline: {path.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
