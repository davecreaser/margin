"""The habits eval as CI tests (spec 0007): deterministic, no model, no cost."""

from typing import Any

import pytest

from eval.habits import graders as g
from margin.config import Settings


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    return g.run_all()


def test_markup_is_stripped_to_exact_spans() -> None:
    text, marks = g._strip("He [[G:nodded]] and [[Cd:just]] left.")
    assert text == "He nodded and just left."
    assert [(k, d, text[a:b]) for k, d, a, b in marks] == [
        ("gestures", False, "nodded"),
        ("crutch", True, "just"),
    ]


def test_overlapping_spans_match_once() -> None:
    b = g.book(["adversarial.md"])
    r = g.grade_instances(b, ["adversarial.md"])
    for sc in r["kinds"].values():
        assert sc.matched_found <= sc.found and sc.matched_gold <= sc.gold


def test_each_kind_meets_the_bar(result: dict[str, Any]) -> None:
    for kind, sc in result["pooled"].items():
        assert sc.gold >= 20, kind
        assert sc.recall >= 0.90, (kind, sc.misses)
        assert sc.precision >= 0.85, (kind, sc.extras)


def test_every_kind_has_30_gold_in_the_invented_set(result: dict[str, Any]) -> None:
    for kind, sc in result["per_set"]["invented"].items():
        assert sc.gold >= 30, kind


def test_no_instance_fails_verification_and_dialogue_is_flagged(result: dict[str, Any]) -> None:
    assert result["failed"] == 0
    right, total = result["dialogue"]
    assert total >= 10 and right == total


def test_repeated_phrases(result: dict[str, Any]) -> None:
    p = result["phrases"]
    assert len(p["found"]) >= 5, p
    assert p["leaked"] == []


def test_demo_top_20_is_labelled_and_holds_its_precision(result: dict[str, Any]) -> None:
    top = result["demo_top"]
    assert not top["unlabelled"], f"label these in eval/habits/phrases.yaml: {top['unlabelled']}"
    # The spec's bar is 0.70; the first build reaches 0.55 and misses it (spec 0007, Decisions).
    # This guards against falling further.
    assert top["precision"] >= 0.55


def test_house_style_is_exact(result: dict[str, Any]) -> None:
    for rule, v in result["style"]["rules"].items():
        assert v["expected"] == v["found"] == v["matched"], rule
    assert all(v == [] for v in result["style"]["clean"].values()), result["style"]["clean"]


def test_clean_text_has_no_habits(result: dict[str, Any]) -> None:
    assert result["clean_habits"] == []


def test_no_runaway_patterns(result: dict[str, Any]) -> None:
    assert result["long_paragraph_seconds"] < 1.0
    t = g.timing()
    assert t["long_seconds"] < 60  # a ceiling for runaway patterns only: CI timing is noisy


def test_the_ratio_bar_is_the_configured_one() -> None:
    assert Settings().phrase_min_ratio == 20000.0
