"""Run the habits eval by hand: python -m eval.habits [--save-baseline] [--show-errors]

No model is called, so there is no dry run, budget or key: the run costs nothing and takes
seconds. The same bars are checked as pytest tests in CI (eval/habits/test_graders.py).
--save-baseline writes numbers only to eval/habits/baseline.json.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from eval.habits import graders as g

BASELINE = Path(__file__).parent / "baseline.json"


def numbers(r: dict[str, Any], t: dict[str, float]) -> dict[str, Any]:
    def kinds(scores: dict[str, g.KindScore]) -> dict[str, Any]:
        return {
            k: {
                "gold": s.gold,
                "found": s.found,
                "matched": s.matched_gold,
                "recall": round(s.recall, 3),
                "precision": round(s.precision, 3),
            }
            for k, s in scores.items()
        }

    style = r["style"]
    return {
        "kinds_pooled": kinds(r["pooled"]),
        "kinds_by_set": {name: kinds(sc) for name, sc in r["per_set"].items()},
        "dialogue_flag": {"right": r["dialogue"][0], "total": r["dialogue"][1]},
        "failed_verification": r["failed"],
        "phrases_planted_found": len(r["phrases"]["found"]),
        "phrases_planted": len(r["phrases"]["planted"]),
        "phrases_must_not_reported": len(r["phrases"]["leaked"]),
        "demo_top20_precision": round(r["demo_top"]["precision"], 3),
        "style_rules": style["rules"],
        "style_clean_mismatches": {k: len(v) for k, v in style["clean"].items()},
        "clean_habits_found": len(r["clean_habits"]),
        "seconds": {
            "demo_74k_words": round(t["demo_seconds"], 2),
            "long_150k_words": round(t["long_seconds"], 2),
            "paragraph_20k_chars": round(r["long_paragraph_seconds"], 3),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--save-baseline", action="store_true", help="Write baseline.json (numbers only)"
    )
    ap.add_argument("--show-errors", action="store_true", help="List every miss and extra")
    args = ap.parse_args()
    r = g.run_all()
    t = g.timing()
    n = numbers(r, t)
    print("Habits eval: no model calls, $0.\n")
    print(
        f"{'kind':<10} {'gold':>5} {'found':>6} {'recall':>7} {'precision':>10}   invented / demo recall, precision"
    )
    for k, s in n["kinds_pooled"].items():
        inv, demo = n["kinds_by_set"]["invented"][k], n["kinds_by_set"]["demo"][k]
        print(
            f"{k:<10} {s['gold']:>5} {s['found']:>6} {s['recall']:>7.2f} {s['precision']:>10.2f}"
            f"   {inv['recall']:.2f}, {inv['precision']:.2f} / {demo['recall']:.2f}, {demo['precision']:.2f}"
        )
    d = n["dialogue_flag"]
    print(
        f"\nDialogue flag: {d['right']} of {d['total']} right. Failed verification: {n['failed_verification']}."
    )
    print(
        f"Repeated phrases: {n['phrases_planted_found']} of {n['phrases_planted']} planted found; "
        f"{n['phrases_must_not_reported']} must-not reported; demo top-20 precision "
        f"{n['demo_top20_precision']:.2f}."
    )
    print("\nHouse style (expected / found / matched):")
    for rule, v in sorted(n["style_rules"].items()):
        print(f"  {rule:<12} {v['expected']:>3} {v['found']:>3} {v['matched']:>3}")
    print(
        "Clean controls (mismatches):",
        n["style_clean_mismatches"],
        "· clean habits found:",
        n["clean_habits_found"],
    )
    sec = n["seconds"]
    print(
        f"\nTime: demo (74,000 words) {sec['demo_74k_words']}s · {t['long_words']:,} words "
        f"{sec['long_150k_words']}s · 20,000-character paragraph {sec['paragraph_20k_chars']}s"
    )
    if args.show_errors:
        for k, s in r["pooled"].items():
            for m in s.misses:
                print(f"MISS  {k}: {m}")
            for e in s.extras:
                print(f"EXTRA {k}: {e}")
        for name, v in r["style"]["clean"].items():
            for x in v:
                print(f"CLEAN {name}: {x}")
        print("Top 20:", r["demo_top"]["top"])
    if args.save_baseline:
        BASELINE.write_text(json.dumps(n, indent=2) + "\n")
        print(f"\nSaved {BASELINE.name}")


if __name__ == "__main__":
    main()
