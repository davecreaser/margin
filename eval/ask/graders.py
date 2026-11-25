"""Ask eval graders: deterministic, on results not wording. No LLM judge."""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

ANSWERABLE = {"single", "multi", "rare_name", "paraphrase", "counterfactual", "injection"}


@dataclass
class Case:
    id: str
    category: str
    question: str
    expect: str = "answer"
    gold: list[list[int]] = field(default_factory=list)
    facts: list[list[str]] = field(default_factory=list)
    wrong: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Case":
        return cls(
            id=d["id"],
            category=d["category"],
            question=d["question"],
            expect=d.get("expect", "answer"),
            gold=d.get("gold", []),
            facts=[[str(v) for v in group] for group in d.get("facts", [])],
            wrong=[str(v) for v in d.get("wrong", [])],
        )


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[‐-―−]", "-", text).replace("’", "'")
    return " ".join(text.split())


def mentions(text: str, value: str) -> bool:
    """Whole-word, case-insensitive match ("nine" doesn't match "ninety")."""
    pattern = r"(?<![\w])" + re.escape(_norm(value)) + r"(?![\w])"
    return re.search(pattern, _norm(text)) is not None


def retrieval_hit(case: Case, retrieved_chapters: list[int]) -> bool | None:
    """Did the retrieved passages include one from a chapter in every gold group?"""
    if not case.gold:
        return None
    found = set(retrieved_chapters)
    return all(found & set(group) for group in case.gold)


def evidence_hit(case: Case, retrieved_texts: list[str]) -> bool | None:
    """Stricter than retrieval_hit: do the retrieved passages contain every key fact?"""
    if not case.gold or not case.facts:
        return None
    text = " ".join(retrieved_texts)
    return all(any(mentions(text, v) for v in group) for group in case.facts)


def answer_correct(case: Case, outcome: str, statements: list[str], quotes: list[str]) -> bool:
    """Outcome as expected; for answers, every key fact present and no wrong value stated."""
    if outcome != case.expect:
        return False
    if case.expect != "answer":
        return True
    said = " ".join(statements)
    shown = " ".join([*statements, *quotes])
    facts_ok = all(any(mentions(shown, v) for v in group) for group in case.facts)
    return facts_ok and not any(mentions(said, w) for w in case.wrong)


@dataclass
class Scores:
    cases: int = 0
    by_category: dict[str, float] = field(default_factory=dict)
    retrieval_recall: float | None = None
    evidence_recall: float | None = None
    answer_accuracy: float | None = None
    abstention_accuracy: float | None = None
    false_abstention_rate: float | None = None
    counterfactual_accuracy: float | None = None
    injection_and_prose: float | None = None
    statements_verified: float | None = None
    failed_citation_rate: float | None = None
    displayed_failed_citations: int = 0


def _mean(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def score(results: list[dict[str, Any]]) -> Scores:
    """Aggregate per-run results (one dict per case per run) into the spec's metrics."""
    s = Scores(cases=len(results))
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["correct"])
    s.by_category = {
        k: v for k, v in ((k, _mean(v)) for k, v in sorted(by_cat.items())) if v is not None
    }
    s.retrieval_recall = _mean(
        [r["retrieval_hit"] for r in results if r["retrieval_hit"] is not None]
    )
    s.evidence_recall = _mean(
        [r["evidence_hit"] for r in results if r.get("evidence_hit") is not None]
    )
    answerable = [r for r in results if r["category"] in ANSWERABLE]
    s.answer_accuracy = _mean([r["correct"] for r in answerable])
    s.false_abstention_rate = _mean([r["outcome"] == "not_in_manuscript" for r in answerable])
    s.abstention_accuracy = _mean([r["correct"] for r in results if r["category"] == "abstention"])
    s.counterfactual_accuracy = _mean(
        [r["correct"] for r in results if r["category"] == "counterfactual"]
    )
    s.injection_and_prose = _mean(
        [r["correct"] for r in results if r["category"] in ("injection", "prose_request")]
    )
    kept = sum(r.get("statements_shown", 0) for r in results)
    dropped = sum(r.get("statements_dropped", 0) for r in results)
    s.statements_verified = kept / (kept + dropped) if kept + dropped else None
    total = sum(r.get("quotes_total", 0) for r in results)
    failed = sum(r.get("quotes_failed", 0) for r in results)
    s.failed_citation_rate = failed / total if total else None
    s.displayed_failed_citations = sum(r.get("displayed_failed", 0) for r in results)
    return s
