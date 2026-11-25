from pathlib import Path

import yaml

from eval.check.graders import ChapterCase, grade, matches, score

CASE = ChapterCase.from_dict(
    {
        "id": "t",
        "file": "x.md",
        "kind": "ordinary",
        "contradictions": [{"phrase": "aged twelve", "gold": [6]}],
        "consistent": [{"phrase": "wash flannel", "gold": [1]}],
        "new": [{"phrase": "Gaffer"}],
    }
)


def f(verdict: str, quote: str, claim: str = "", chapter: int = 6) -> dict:
    cites = [{"passage_id": f"{chapter}:1-2"}] if verdict != "new" else []
    return {"verdict": verdict, "quote": quote, "claim": claim, "citations": cites}


def test_matches_quote_or_claim_case_insensitively() -> None:
    assert matches(f("new", "The mule, Aged Twelve and wise"), "aged twelve")
    assert matches(f("new", "x", claim="The mule was aged twelve."), "aged twelve")
    assert not matches(f("new", "aged nine"), "aged twelve")


def test_caught_needs_the_gold_chapter_and_extra_contradictions_are_false_alarms() -> None:
    g = grade(
        CASE,
        [
            f("contradicts", "The mule, aged twelve and wise", chapter=6),
            f("contradicts", "the town hall was red", chapter=2),
            f("consistent", "could wash flannel with less shrinking", chapter=1),
            f("new", "named the mule Gaffer"),
        ],
    )
    assert g["caught"] == ["aged twelve"] and g["missed"] == []
    assert len(g["false_alarms"]) == 1
    assert (g["consistent_ok"], g["new_ok"]) == (1, 1)
    wrong_chapter = grade(CASE, [f("contradicts", "aged twelve", chapter=3)])
    assert wrong_chapter["caught"] == []


def test_score() -> None:
    g = grade(CASE, [f("contradicts", "aged twelve"), f("contradicts", "red hall", chapter=2)])
    r = {
        **g,
        "kind": "ordinary",
        "quotes_total": 2,
        "quotes_failed": 0,
        "claims": 4,
        "claim_quotes_failed": 1,
    }
    s = score([r])
    assert s["contradiction_recall"] == 1.0 and s["contradiction_precision"] == 0.5
    assert s["claim_quote_failure_rate"] == 0.2


def test_case_file_phrases_appear_in_their_chapters() -> None:
    here = Path(__file__).parent
    cases = [ChapterCase.from_dict(d) for d in yaml.safe_load((here / "cases.yaml").read_text())]
    assert len(cases) == 8 and sum(len(c.contradictions) for c in cases) == 21
    for c in cases:
        text = (here / "chapters" / c.file).read_text().lower()
        for p in [*c.contradictions, *c.consistent, *c.new, *c.ambiguous]:
            assert p.phrase.lower() in text, (c.id, p.phrase)


def test_ambiguous_claims_are_neither_required_nor_false_alarms() -> None:
    case = ChapterCase.from_dict(
        {"id": "a", "file": "x.md", "kind": "ordinary", "ambiguous": [{"phrase": "twenty words"}]}
    )
    assert [p.phrase for p in case.ambiguous] == ["twenty words"]
    g = grade(case, [f("contradicts", "at a hundred and twenty words a minute", chapter=1)])
    assert g["false_alarms"] == [] and g["contradicts_findings"] == 0
