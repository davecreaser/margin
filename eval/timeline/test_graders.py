from pathlib import Path

import yaml

from eval.timeline.graders import Gold, grade, label_matches, score

HERE = Path(__file__).parent


def card(quote: str) -> dict[str, str]:
    return {"quote": quote}


def test_labels_match_key_terms_and_ordinals_but_not_longer_numbers() -> None:
    assert label_matches("Day 3, night", "Day 3")
    assert label_matches("The third day of the gales", "Day 3")
    assert label_matches("Winter of 1871", "1871")
    assert not label_matches("Day 12", "Day 1")
    assert not label_matches("1867", "1866")


def test_grade_counts_recall_placement_order_and_the_undated() -> None:
    golds = [
        Gold("the ferry left", "Day 1", 1),
        Gold("the brig struck", "Day 2", 2),
        Gold("the nets were mended", None),
        Gold("never extracted", "Day 3", 3),
        Gold("born in the year", "1866", 0, counterfactual="1867"),
    ]
    timeline = {
        "periods": [
            {"label": "1867", "events": [card("She was born in the year of the comet")]},
            {"label": "Day 2", "events": [card("and the brig struck the rock")]},
            {"label": "Day 1", "events": [card("At nine the ferry left")]},
        ],
        "unplaced": [card("the nets were mended at last")],
    }
    g = grade(golds, timeline)
    assert (g["found"], g["gold"]) == (4, 5)
    assert (g["placement_right"], g["placement_total"]) == (3, 4)  # all but the birth year
    assert (g["pairs_right"], g["pairs"]) == (2, 3)  # Day 1 shown after Day 2
    assert g["counterfactual"] == [False]
    s = score([g])
    assert s["event_recall"] == 0.8 and s["not_placed_rate"] == 0.25


def test_cases_phrases_are_in_the_novella() -> None:
    cases = yaml.safe_load((HERE / "cases.yaml").read_text())
    text = " ".join(p.read_text() for p in (HERE / "novella").glob("*.md"))
    for e in cases["novella"]["events"]:
        assert e["phrase"] in text, e["phrase"]
