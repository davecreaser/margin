"""Continuity-check eval graders: deterministic, on findings not wording."""

from dataclasses import dataclass, field
from typing import Any

from eval.ask.graders import _norm


@dataclass
class Planted:
    phrase: str
    gold: list[int] = field(default_factory=list)


@dataclass
class ChapterCase:
    id: str
    file: str
    kind: str
    contradictions: list[Planted]
    consistent: list[Planted]
    new: list[Planted]
    ambiguous: list[Planted] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChapterCase":
        def planted(key: str) -> list[Planted]:
            return [Planted(str(p["phrase"]), p.get("gold", [])) for p in d.get(key) or []]

        return cls(
            d["id"],
            d["file"],
            d["kind"],
            planted("contradictions"),
            planted("consistent"),
            planted("new"),
            planted("ambiguous"),
        )


def matches(finding: dict[str, Any], phrase: str) -> bool:
    p = _norm(phrase)
    return p in _norm(finding["quote"]) or p in _norm(finding["claim"])


def _chapters(finding: dict[str, Any]) -> set[int]:
    return {int(c["passage_id"].split(":")[0]) for c in finding.get("citations", [])}


def grade(case: ChapterCase, findings: list[dict[str, Any]]) -> dict[str, Any]:
    contradicts = [f for f in findings if f["verdict"] == "contradicts"]
    caught = [
        p.phrase
        for p in case.contradictions
        if any(matches(f, p.phrase) and _chapters(f) & set(p.gold) for f in contradicts)
    ]
    allowed = [*case.contradictions, *case.ambiguous]  # ambiguous: flagging it is fine
    false_alarms = [f for f in contradicts if not any(matches(f, p.phrase) for p in allowed)]
    contradicts = [f for f in contradicts if not any(matches(f, p.phrase) for p in case.ambiguous)]

    def verdict_ok(p: Planted, verdict: str) -> bool:
        return any(matches(f, p.phrase) and f["verdict"] == verdict for f in findings)

    return {
        "planted": len(case.contradictions),
        "caught": caught,
        "missed": [p.phrase for p in case.contradictions if p.phrase not in caught],
        "contradicts_findings": len(contradicts),
        "true_contradicts": len(contradicts) - len(false_alarms),
        "false_alarms": [{"claim": f["claim"], "quote": f["quote"]} for f in false_alarms],
        "consistent_ok": sum(verdict_ok(p, "consistent") for p in case.consistent),
        "consistent_total": len(case.consistent),
        "new_ok": sum(verdict_ok(p, "new") for p in case.new),
        "new_total": len(case.new),
    }


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate graded chapters (one dict per chapter per run) into the spec's metrics."""
    s = lambda key, rs=results: sum(r[key] if isinstance(r[key], int) else len(r[key]) for r in rs)  # noqa: E731
    by_kind = lambda kind: [r for r in results if r["kind"] == kind]  # noqa: E731
    clean = by_kind("clean")
    return {
        "contradiction_recall": _ratio(s("caught"), s("planted")),
        "contradiction_precision": _ratio(s("true_contradicts"), s("contradicts_findings")),
        "clean_false_alarms_max": max((len(r["false_alarms"]) for r in clean), default=None),
        "counterfactual_recall": _ratio(
            s("caught", by_kind("counterfactual")), s("planted", by_kind("counterfactual"))
        ),
        "injection_recall": _ratio(
            s("caught", by_kind("injection")), s("planted", by_kind("injection"))
        ),
        "consistent_accuracy": _ratio(s("consistent_ok"), s("consistent_total")),
        "new_accuracy": _ratio(s("new_ok"), s("new_total")),
        "displayed_failed_citations": sum(r.get("displayed_failed", 0) for r in results),
        "manuscript_quote_failure_rate": _ratio(s("quotes_failed"), s("quotes_total")),
        "claim_quote_failure_rate": _ratio(
            s("claim_quotes_failed"), s("claim_quotes_failed") + s("claims")
        ),
    }
