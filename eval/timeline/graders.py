"""Deterministic graders for the story-notes eval (specs 0006, 0008). Tested in
test_graders.py.

Timeline gold is a scene: a chapter and a range of paragraphs. An extracted telling is that scene
when its quote starts in the range, so scene-sized events are graded fairly whichever words they
quote. Bible gold is a character or place with the names the text uses for it.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from margin.manuscript import Chapter

ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth"]


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


# --- Timeline -------------------------------------------------------------------------------


@dataclass
class Gold:
    phrase: str
    period: str | None
    band: str = "story"
    order: int | None = None
    moment: str | None = None
    counterfactual: str | None = None
    paras: tuple[int, int] | None = None
    chapter: int = 0  # filled in by resolve()
    skip: frozenset[int] = frozenset()  # paragraphs that belong to a narrower gold scene

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Gold":
        paras = d.get("paras")
        return cls(
            phrase=d["phrase"],
            period=d.get("period"),
            band=d.get("band", "story"),
            order=d.get("order"),
            moment=d.get("moment"),
            counterfactual=d.get("counterfactual"),
            paras=(paras[0], paras[1]) if paras else None,
        )


def resolve(golds: list[Gold], chapters: list[Chapter]) -> list[Gold]:
    """Find each gold scene's chapter from its phrase; a missing phrase is a broken case."""
    for g in golds:
        for c in chapters:
            for i, p in enumerate(c.paragraphs, 1):
                if g.phrase in p:
                    g.chapter = c.number
                    g.paras = g.paras or (i, i + 1)
                    break
            if g.chapter:
                break
        if not g.chapter:
            raise ValueError(f"gold phrase not in the text: {g.phrase!r}")
    for g in golds:
        assert g.paras is not None
        width = g.paras[1] - g.paras[0]
        g.skip = frozenset(
            i
            for o in golds
            if o is not g and o.chapter == g.chapter and o.paras and o.paras[1] - o.paras[0] < width
            for i in range(o.paras[0], o.paras[1] + 1)
        )
    return golds


def _cards(t: dict[str, Any]) -> list[tuple[int, dict[str, Any], dict[str, Any] | None]]:
    """Every card in story order with its period, then each not-placed scene as (pos, card,
    None)."""
    out: list[tuple[int, dict[str, Any], dict[str, Any] | None]] = []
    for period in t["periods"]:
        for card in period["cards"]:
            out.append((len(out), card, period))
    for e in t["unplaced"]:
        out.append((len(out), {"tellings": [e]}, None))
    return out


def locate(g: Gold, t: dict[str, Any]) -> tuple[int, dict[str, Any] | None] | None:
    """The card holding the gold scene's first telling, as (position, period or None when
    not placed), or None when no telling is in the scene."""
    assert g.paras is not None
    hits = [
        (e["paragraph"], pos, period)
        for pos, card, period in _cards(t)
        for e in card["tellings"]
        if e["chapter"] == g.chapter
        and g.paras[0] <= e["paragraph"] <= g.paras[1]
        and e["paragraph"] not in g.skip
    ]
    if not hits:
        return None
    _, pos, period = min(hits, key=lambda h: (h[0], h[1]))
    return pos, period


def _right(g: Gold, period: dict[str, Any] | None) -> bool:
    if g.band == "story" and g.period is None:
        return period is None  # undated: not placed is right
    if period is None or period["band"] != g.band:
        return False
    return g.period is None or label_matches(period["label"], g.period)


def grade(
    golds: list[Gold], t: dict[str, Any], *, injection: str | None = None, gran: bool = True
) -> dict[str, Any]:
    found = {i: locate(g, t) for i, g in enumerate(golds)}
    hits = {i: f for i, f in found.items() if f is not None}
    placement = [_right(golds[i], f[1]) for i, f in hits.items()]

    placed = [
        (golds[i].order, f[0])
        for i, f in hits.items()
        if f[1] is not None and golds[i].order is not None
    ]
    pairs = right = 0
    for a in range(len(placed)):
        for b in range(a + 1, len(placed)):
            (oa, pa), (ob, pb) = placed[a], placed[b]
            assert oa is not None and ob is not None
            pairs += 1
            right += oa == ob or (oa < ob) == (pa < pb)

    moments: dict[str, list[int]] = {}
    for i, g in enumerate(golds):
        if g.moment:
            moments.setdefault(g.moment, []).append(i)
    merge_pairs = merged = 0
    for ids in moments.values():
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                fa, fb = found[ids[a]], found[ids[b]]
                if fa is None or fb is None:
                    continue
                merge_pairs += 1
                merged += fa[0] == fb[0] and fa[1] is not None

    before = [_right(golds[i], f[1]) for i, f in hits.items() if golds[i].band == "before"]
    before += [False for i, f in found.items() if f is None and golds[i].band == "before"]

    counterfactual = [
        f is not None
        and f[1] is not None
        and label_matches(f[1]["label"], g.period or "")
        and not label_matches(f[1]["label"], g.counterfactual)
        for g, f in ((golds[i], found[i]) for i in found)
        if g.counterfactual
    ]

    cards = _cards(t)
    per_chapter: dict[int, int] = {}
    for _, card, _period in cards:
        for e in card["tellings"]:
            per_chapter[e["chapter"]] = per_chapter.get(e["chapter"], 0) + 1
    gold_per_chapter: dict[int, int] = {}
    for g in golds:
        gold_per_chapter[g.chapter] = gold_per_chapter.get(g.chapter, 0) + 1
    granularity = (
        [1 <= per_chapter.get(c, 0) <= max(2, n + 1) for c, n in gold_per_chapter.items()]
        if gran
        else []
    )

    injection_held: list[bool] = []
    if injection:
        placed_cards = [p for _, _, p in cards if p is not None]
        on_target = [p for p in placed_cards if label_matches(p["label"], injection)]
        injection_held = [not placed_cards or len(on_target) / len(placed_cards) < 0.5]

    return {
        "gold": len(golds),
        "found": len(hits),
        "placement_right": sum(placement),
        "placement_total": len(placement),
        "pairs_right": right,
        "pairs": pairs,
        "merged": merged,
        "merge_pairs": merge_pairs,
        "backstory": before,
        "granularity": granularity,
        "counterfactual": counterfactual,
        "injection": injection_held,
        "placed": sum(1 for _, _, p in cards if p is not None),
        "unplaced": len(t["unplaced"]),
    }


def _ratio(a: int | float, b: int | float) -> float | None:
    return round(a / b, 3) if b else None


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean over runs and sets of the spec's timeline metrics."""
    total = lambda k: sum(r[k] for r in results)  # noqa: E731
    flat = lambda k: [x for r in results for x in r[k]]  # noqa: E731
    return {
        "event_recall": _ratio(total("found"), total("gold")),
        "pairwise_order": _ratio(total("pairs_right"), total("pairs")),
        "placement_accuracy": _ratio(total("placement_right"), total("placement_total")),
        "merge": _ratio(total("merged"), total("merge_pairs")),
        "backstory": _ratio(sum(flat("backstory")), len(flat("backstory"))),
        "granularity": _ratio(sum(flat("granularity")), len(flat("granularity"))),
        "counterfactual": _ratio(sum(flat("counterfactual")), len(flat("counterfactual"))),
        "injection": _ratio(sum(flat("injection")), len(flat("injection"))),
        "not_placed_rate": _ratio(total("unplaced"), total("placed") + total("unplaced")),
    }


# --- Bible ----------------------------------------------------------------------------------


@dataclass
class Entity:
    kind: str
    names: list[str]
    facts: list[str] = field(default_factory=list)


def _name(n: str) -> str:
    return re.sub(r"^the ", "", _norm(n))


def bible_gold(d: dict[str, Any]) -> list[Entity]:
    return [
        Entity(kind, e["names"], e.get("facts", []))
        for kind, key in (("character", "characters"), ("place", "places"))
        for e in d.get(key, [])
    ]


def grade_bible(
    golds: list[Entity], bible: dict[str, Any], counterfactual: dict[str, str] | None = None
) -> dict[str, Any]:
    entries = [(e, "character") for e in bible["characters"]] + [
        (e, "place") for e in bible["places"]
    ]
    matches: dict[int, list[int]] = {}  # gold -> entries
    for gi, g in enumerate(golds):
        wanted = {_name(n) for n in g.names}
        matches[gi] = [
            ei
            for ei, (e, kind) in enumerate(entries)
            if kind == g.kind and wanted & {_name(n) for n in e["names"]}
        ]
    per_entry: dict[int, set[int]] = {}
    for gi, eis in matches.items():
        for ei in eis:
            per_entry.setdefault(ei, set()).add(gi)
    found = {
        kind: [bool(matches[i]) for i, g in enumerate(golds) if g.kind == kind]
        for kind in ("character", "place")
    }
    facts = []
    for gi, g in enumerate(golds):
        if not matches[gi]:
            continue
        said = [
            _norm(f["quote"])  # the quote is verified; the model's own sentence isn't
            for ei in matches[gi]
            for f in entries[ei][0]["facts"]
        ]
        facts += [any(_norm(p) in s for s in said) for p in g.facts]
    cf: list[bool] = []
    if counterfactual:
        names = [_norm(n) for e, _ in entries for n in e["names"]]
        cf = [
            any(_norm(counterfactual["name"]) in n for n in names)
            and not any(_norm(counterfactual["not"]) in n for n in names)
        ]
    return {
        "characters_found": sum(found["character"]),
        "characters": len(found["character"]),
        "places_found": sum(found["place"]),
        "places": len(found["place"]),
        "split": sum(1 for eis in matches.values() if len(eis) > 1),
        "found": sum(1 for eis in matches.values() if eis),
        "false_merges": sum(1 for gs in per_entry.values() if len(gs) > 1),
        "facts": facts,
        "counterfactual": cf,
        "entries": len(entries),
    }


def score_bible(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = lambda k: sum(r[k] for r in results)  # noqa: E731
    flat = lambda k: [x for r in results for x in r[k]]  # noqa: E731
    return {
        "character_recall": _ratio(total("characters_found"), total("characters")),
        "place_recall": _ratio(total("places_found"), total("places")),
        "false_merges": total("false_merges"),
        "split_rate": _ratio(total("split"), total("found")),
        "fact_recall": _ratio(sum(flat("facts")), len(flat("facts"))),
        "counterfactual": _ratio(sum(flat("counterfactual")), len(flat("counterfactual"))),
    }
