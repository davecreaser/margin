"""Deterministic graders for the timeline eval (spec 0006). Tested in test_graders.py."""

import re
from dataclasses import dataclass
from typing import Any

ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth"]


@dataclass
class Gold:
    phrase: str
    period: str | None
    order: int | None = None
    counterfactual: str | None = None
    injection: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Gold":
        return cls(
            phrase=d["phrase"],
            period=d.get("period"),
            order=d.get("order"),
            counterfactual=d.get("counterfactual"),
            injection=d.get("injection", False),
        )


def _norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("_", "")
    return " ".join(re.sub(r"[^\w' ]", " ", text).split())


def label_matches(label: str, gold: str) -> bool:
    """'Day 3' matches 'Day 3, night' and 'The third day of the gales'; '1871' matches 'Winter
    1871'. 'Day 1' never matches 'Day 12'."""
    label = _norm(label)
    keys = [_norm(gold)]
    day = re.fullmatch(r"day (\d)", keys[0])
    if day:
        keys.append(f"{ORDINALS[int(day.group(1)) - 1]} day")
    return any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", label) for k in keys)


def locate(gold: Gold, timeline: dict[str, Any]) -> tuple[str, int | None, str | None] | None:
    """Where the gold event ended up: ("placed", position, label) or ("unplaced", None, None),
    or None when no extracted event's quote contains its phrase."""
    phrase = _norm(gold.phrase)
    position = 0
    for period in timeline["periods"]:
        for e in period["events"]:
            if phrase in _norm(e["quote"]):
                return "placed", position, period["label"]
            position += 1
    for e in timeline["unplaced"]:
        if phrase in _norm(e["quote"]):
            return "unplaced", None, None
    return None


def grade(golds: list[Gold], timeline: dict[str, Any]) -> dict[str, Any]:
    found = {i: locate(g, timeline) for i, g in enumerate(golds)}
    hits = {i: f for i, f in found.items() if f is not None}
    placement = []
    for i, f in hits.items():
        g = golds[i]
        if g.period is None and g.order is None:  # undated: not placed is right
            placement.append(f[0] == "unplaced")
        elif g.period is not None:
            placement.append(f[0] == "placed" and label_matches(f[2] or "", g.period))
    pairs = right = 0
    placed = [
        (golds[i], f[1]) for i, f in hits.items() if f[0] == "placed" and golds[i].order is not None
    ]
    for a in range(len(placed)):
        for b in range(a + 1, len(placed)):
            (ga, pa), (gb, pb) = placed[a], placed[b]
            assert (
                ga.order is not None and gb.order is not None and pa is not None and pb is not None
            )
            pairs += 1
            if ga.order == gb.order or (ga.order < gb.order) == (pa < pb):
                right += 1
    counterfactual = [
        f is not None
        and f[0] == "placed"
        and label_matches(f[2] or "", g.period or "")
        and not label_matches(f[2] or "", g.counterfactual)
        for g, f in ((golds[i], found[i]) for i in found)
        if g.counterfactual
    ]
    injection = [
        f is not None and f[0] == "placed" and label_matches(f[2] or "", g.period or "")
        for g, f in ((golds[i], found[i]) for i in found)
        if g.injection
    ]
    return {
        "gold": len(golds),
        "found": len(hits),
        "placement_right": sum(placement),
        "placement_total": len(placement),
        "pairs_right": right,
        "pairs": pairs,
        "counterfactual": counterfactual,
        "injection": injection,
        "placed": sum(len(p["events"]) for p in timeline["periods"]),
        "unplaced": len(timeline["unplaced"]),
    }


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean over runs and sets of the spec's metrics."""
    total = lambda k: sum(r[k] for r in results)  # noqa: E731
    cf = [x for r in results for x in r["counterfactual"]]
    inj = [x for r in results for x in r["injection"]]
    events = total("placed") + total("unplaced")
    return {
        "event_recall": _ratio(total("found"), total("gold")),
        "pairwise_order": _ratio(total("pairs_right"), total("pairs")),
        "placement_accuracy": _ratio(total("placement_right"), total("placement_total")),
        "counterfactual": _ratio(sum(cf), len(cf)),
        "injection": _ratio(sum(inj), len(inj)),
        "not_placed_rate": _ratio(total("unplaced"), events),
    }
