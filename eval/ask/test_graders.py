from pathlib import Path

import yaml

from eval.ask.graders import Case, answer_correct, evidence_hit, mentions, retrieval_hit, score

CASE = Case(
    id="t",
    category="counterfactual",
    question="How old was the mule?",
    gold=[[6]],
    facts=[["nine", "9"]],
    wrong=["seven"],
)


def test_mentions_is_whole_word_and_case_insensitive() -> None:
    assert mentions("It was aged Nine.", "nine")
    assert not mentions("ninety mules", "nine")
    assert mentions("about £15 a week", "£15")
    assert mentions("a dress‑suit", "dress-suit")


def test_answer_needs_every_fact_and_no_wrong_value() -> None:
    assert answer_correct(CASE, "answer", ["The mule was nine."], [])
    assert answer_correct(CASE, "answer", ["It was quite old."], ["It was aged nine"])
    assert not answer_correct(CASE, "answer", ["It was seven, or nine."], [])
    assert not answer_correct(CASE, "answer", ["It was old."], [])
    assert not answer_correct(CASE, "not_in_manuscript", [], [])


def test_abstention_and_prose_are_exact_outcomes() -> None:
    abstain = Case(id="a", category="abstention", question="?", expect="not_in_manuscript")
    assert answer_correct(abstain, "not_in_manuscript", [], [])
    assert not answer_correct(abstain, "answer", ["Blue."], [])
    prose = Case(id="p", category="prose_request", question="?", expect="prose_request")
    assert answer_correct(prose, "prose_request", [], [])


def test_retrieval_needs_every_gold_group() -> None:
    multi = Case(id="m", category="multi", question="?", gold=[[1, 2], [8]])
    assert retrieval_hit(multi, [2, 8, 8])
    assert not retrieval_hit(multi, [1, 2])
    assert retrieval_hit(Case(id="x", category="abstention", question="?"), [1]) is None


def test_score_aggregates_the_spec_metrics() -> None:
    results = [
        {"category": "single", "correct": True, "outcome": "answer", "retrieval_hit": True,
         "statements_shown": 2, "statements_dropped": 0, "quotes_total": 2, "quotes_failed": 0},
        {"category": "single", "correct": False, "outcome": "not_in_manuscript",
         "retrieval_hit": False, "statements_shown": 0, "statements_dropped": 1,
         "quotes_total": 2, "quotes_failed": 2},
        {"category": "abstention", "correct": True, "outcome": "not_in_manuscript",
         "retrieval_hit": None},
    ]  # fmt: skip
    s = score(results)
    assert s.answer_accuracy == 0.5
    assert s.false_abstention_rate == 0.5
    assert s.abstention_accuracy == 1.0
    assert s.retrieval_recall == 0.5
    assert s.failed_citation_rate == 0.5
    assert s.statements_verified == 2 / 3


def test_case_file_is_well_formed() -> None:
    raw = yaml.safe_load((Path(__file__).parent / "cases.yaml").read_text())
    cases = [Case.from_dict(d) for d in raw]
    assert len(cases) == 60 and len({c.id for c in cases}) == 60
    for c in cases:
        if c.expect == "answer":
            assert c.gold and c.facts, c.id


def test_evidence_needs_the_fact_in_the_retrieved_text() -> None:
    assert evidence_hit(CASE, ["The mule. It was aged nine, and cost ten pounds."])
    assert not evidence_hit(CASE, ["The mule was a part of his splendour."])
