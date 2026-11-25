"""Ask: retrieve passages, run the answer step, verify every citation, show only what verified.

Grounded or silent (ADR 0001): a statement whose citations all fail is dropped, a failed
citation is never shown, and if nothing survives the answer is "Not in the manuscript."
"""

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from margin.config import Settings, estimate_cost
from margin.index import PassageStore
from margin.llm import ModelClient, ModelReply
from margin.passages import Passage
from margin.retrieval import Mode, Retrieved, Retriever
from margin.steps import answer as answer_step
from margin.verify import quote_in_passage

Outcome = Literal["answer", "not_in_manuscript", "prose_request"]


class EmptyIndexError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Nothing is indexed yet: run ./margin ingest --demo, or ./margin ingest <path>"
        )


@dataclass
class ShownCitation:
    n: int
    passage: Passage
    quote: str


@dataclass
class ShownStatement:
    text: str
    citations: list[int]


@dataclass
class AskResult:
    question: str
    outcome: Outcome
    statements: list[ShownStatement] = field(default_factory=list)
    citations: list[ShownCitation] = field(default_factory=list)
    retrieved: list[Retrieved] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    quotes_total: int = 0
    quotes_failed: int = 0
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model_error: str | None = None
    retrieval_ms: int = 0
    model_ms: int = 0

    @property
    def cost(self) -> float | None:
        return estimate_cost(self.model, self.input_tokens, self.output_tokens)


def run(
    question: str,
    *,
    retriever: Retriever,
    store: PassageStore,
    client: ModelClient,
    settings: Settings,
    mode: Mode = "hybrid",
) -> AskResult:
    result = AskResult(question=question, outcome="not_in_manuscript", model=settings.answer_model)
    started = time.perf_counter()
    result.retrieved = retriever.retrieve(question, mode=mode)
    result.retrieval_ms = int((time.perf_counter() - started) * 1000)
    if not result.retrieved:
        if store.stats().passages == 0:
            raise EmptyIndexError()
        return result

    passages = [r.passage for r in result.retrieved]
    by_id = {p.id: p for p in passages}
    started = time.perf_counter()
    reply: ModelReply[answer_step.AnswerOutput] | None = None
    for _attempt in range(2):  # one retry for output that fails the schema
        reply = answer_step.answer(
            client,
            question=question,
            passages=passages,
            model=settings.answer_model,
            effort=settings.answer_effort,
            max_tokens=settings.answer_max_tokens,
        )
        result.input_tokens += reply.input_tokens
        result.output_tokens += reply.output_tokens
        if reply.output is not None or reply.stop_reason in ("refusal", "max_tokens"):
            break  # only output that fails the schema is retried
    result.model_ms = int((time.perf_counter() - started) * 1000)
    assert reply is not None
    if reply.output is None:
        result.model_error = reply.error
        return result

    output = reply.output
    if output.kind == "prose_request":
        result.outcome = "prose_request"
        return result
    if output.kind == "not_in_manuscript":
        return result

    seen: dict[tuple[str, str], int] = {}
    for statement in output.statements:
        verified: list[int] = []
        failed: list[dict[str, str]] = []
        for c in statement.citations:
            result.quotes_total += 1
            passage = by_id.get(c.passage_id)
            if passage is None or not quote_in_passage(c.quote, passage.text):
                result.quotes_failed += 1
                failed.append({"passage_id": c.passage_id, "quote": c.quote})
                continue
            key = (passage.id, c.quote)
            if key not in seen:
                seen[key] = len(result.citations) + 1
                result.citations.append(ShownCitation(seen[key], passage, c.quote))
            if seen[key] not in verified:
                verified.append(seen[key])
        if verified:
            result.statements.append(ShownStatement(statement.text, verified))
            if failed:
                result.dropped.append({"statement": statement.text, "failed": failed, "kept": True})
        else:
            result.dropped.append({"statement": statement.text, "failed": failed, "kept": False})
    if result.statements:
        result.outcome = "answer"
    return result


def snippet(text: str, words: int = 14) -> str:
    parts = text.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _retrieved_json(r: Retrieved) -> dict[str, Any]:
    return {
        "passage_id": r.passage.id,
        "location": r.passage.location,
        "chapter_title": r.passage.chapter_title,
        "score": r.score,
        "bm25_rank": r.bm25_rank,
        "bm25_score": r.bm25_score,
        "knn_rank": r.knn_rank,
        "knn_score": r.knn_score,
        "snippet": snippet(r.passage.text),
    }


def events(result: AskResult, *, show_passages: bool, debug: bool) -> Iterator[tuple[str, Any]]:
    """The result as the event stream the API sends: answer_delta, citation, done (plus extras)."""
    if show_passages:
        yield "passages", [_retrieved_json(r) for r in result.retrieved]
    if result.outcome == "answer":
        for s in result.statements:
            yield "answer_delta", {"text": s.text, "citations": s.citations}
        for c in result.citations:
            yield (
                "citation",
                {
                    "n": c.n,
                    "passage_id": c.passage.id,
                    "location": c.passage.location,
                    "quote": c.quote,
                },
            )
    else:
        text = (
            answer_step.PROSE_REFUSAL
            if result.outcome == "prose_request"
            else answer_step.NOT_IN_MANUSCRIPT
        )
        yield "answer_delta", {"text": text, "citations": []}
    if debug:
        for d in result.dropped:
            yield "debug", {"kind": "failed_citation", **d}
        if result.model_error:
            yield "debug", {"kind": "model_error", "error": result.model_error}
    yield (
        "done",
        {
            "outcome": result.outcome,
            "closest": [_retrieved_json(r) for r in result.retrieved[:3]]
            if result.outcome == "not_in_manuscript"
            else [],
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost": result.cost,
            "retrieval_ms": result.retrieval_ms,
            "model_ms": result.model_ms,
        },
    )
