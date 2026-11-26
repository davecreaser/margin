from pathlib import Path
from typing import Any

import yaml

from eval.timeline.graders import (
    Entity,
    Gold,
    grade,
    grade_bible,
    label_matches,
    resolve,
    score,
    score_bible,
)
from margin.manuscript import Chapter, load_chapter

HERE = Path(__file__).parent


def telling(chapter: int, paragraph: int) -> dict[str, Any]:
    return {"chapter": chapter, "paragraph": paragraph, "quote": "q"}


def card(*tellings: dict[str, Any]) -> dict[str, Any]:
    return {"tellings": list(tellings), "basis": [], "uncertain": False}


def test_labels_match_key_terms_and_ordinals_but_not_longer_numbers() -> None:
    assert label_matches("Day 3, night", "Day 3")
    assert label_matches("The third day of the gales", "Day 3")
    assert label_matches("Winter of 1871", "1871")
    assert not label_matches("Day 12", "Day 1")
    assert not label_matches("1867", "1866")


def test_grade_scenes_by_paragraph_range_with_merges_bands_and_granularity() -> None:
    golds = [
        Gold("a", "Day 1", order=2, moment="m", paras=(1, 3), chapter=1),
        Gold("b", "Day 1", order=2, moment="m", paras=(2, 2), chapter=2),
        Gold("c", "1871", band="before", order=1, paras=(4, 4), chapter=1),
        Gold("d", None, paras=(1, 1), chapter=3),
        Gold("e", "Day 2", order=3, paras=(5, 6), chapter=2),  # never extracted
    ]
    t = {
        "periods": [
            {"label": "Day 1", "band": "story", "cards": [card(telling(1, 2), telling(2, 2))]},
            {"label": "1871", "band": "story", "cards": [card(telling(1, 4))]},  # wrong band
        ],
        "unplaced": [telling(3, 1), telling(1, 9), telling(1, 10)],
    }
    g = grade(golds, t, injection="Day 1")
    assert (g["found"], g["gold"]) == (4, 5)
    assert (g["placement_right"], g["placement_total"]) == (3, 4)
    assert (g["pairs_right"], g["pairs"]) == (1, 3)  # 1871 shown after both Day 1 scenes
    assert (g["merged"], g["merge_pairs"]) == (1, 1)
    assert g["backstory"] == [False]
    assert g["granularity"] == [False, True, True]  # chapter 1 has 4 tellings for 2 scenes
    assert g["injection"] == [False]  # one of two placed cards is on Day 1
    s = score([g])
    assert s["event_recall"] == 0.8 and s["merge"] == 1.0


def test_resolve_finds_each_phrase_and_refuses_a_missing_one() -> None:
    chapters = [Chapter(1, "One", ["x"]), Chapter(2, "Two", ["y", "the ferry left"])]
    [g] = resolve([Gold("ferry left", "Day 1")], chapters)
    assert (g.chapter, g.paras) == (2, (2, 3))
    outer, inner = resolve(
        [Gold("x", "Day 1", paras=(1, 1)), Gold("x", "1871", paras=(1, 1))], chapters
    )
    assert outer.skip == inner.skip == frozenset()  # same width: neither owns the other
    wide, narrow = resolve(
        [Gold("x", "Day 1", paras=(1, 2)), Gold("x", "1871", paras=(1, 1))], chapters
    )
    assert wide.skip == frozenset({1}) and narrow.skip == frozenset()
    try:
        resolve([Gold("not there", None)], chapters)
    except ValueError:
        pass
    else:
        raise AssertionError("missing phrase accepted")


def test_bible_recall_splits_false_merges_facts_and_counterfactual() -> None:
    golds = [
        Entity("character", ["Nell Garrow", "Nell"], ["miller's widow"]),
        Entity("character", ["Kit Garrow", "Kit"], ["fourteen"]),
        Entity("character", ["Jory"], []),
        Entity("place", ["the Weir House"], []),
    ]
    fact = {"text": "Nell is the miller's widow.", "quote": "Nell Garrow, the miller's widow"}
    bible = {
        "characters": [
            {"names": ["Nell"], "facts": [fact]},
            {"names": ["Nell Garrow", "Kit"], "facts": []},  # Nell split; Nell and Kit merged
            {"names": ["Pemberton"], "facts": []},
        ],
        "places": [{"names": ["Weir House"], "facts": []}],
    }
    b = grade_bible(golds, bible, {"name": "Pemberton", "not": "Clutterbuck"})
    assert (b["characters_found"], b["characters"], b["places_found"]) == (2, 3, 1)
    assert (b["split"], b["false_merges"], b["facts"], b["counterfactual"]) == (
        1,
        1,
        [True, False],
        [True],
    )
    s = score_bible([b])
    assert s["character_recall"] == 0.667 and s["split_rate"] == 0.333


def test_cases_resolve_against_the_text_and_fact_phrases_are_in_it() -> None:
    cases = yaml.safe_load((HERE / "cases.yaml").read_text())
    for name in ("novella", "novella2"):
        chapters = [load_chapter(f) for f in sorted((HERE / cases[name]["dir"]).glob("*.md"))]
        for n, c in enumerate(chapters, 1):
            c.number = n
        golds = resolve([Gold.from_dict(d) for d in cases[name]["events"]], chapters)
        for g in golds:
            assert g.paras is not None
            chapter = chapters[g.chapter - 1]
            assert g.paras[1] <= len(chapter.paragraphs), g.phrase
            assert any(g.phrase in p for p in chapter.paragraphs[g.paras[0] - 1 : g.paras[1]])
        text = "\n".join(p for c in chapters for p in c.paragraphs)
        assert cases[name]["injection"] in text
        for kind in ("characters", "places"):
            for e in cases[name]["bible"][kind]:
                assert any(n in text for n in e["names"]), e["names"]
                for f in e["facts"]:
                    assert f in text, f
