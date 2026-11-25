"""Continuity check: extract a chapter's claims, retrieve the passages each one touches,
judge each claim, and show only what verified (spec 0002, ADR 0001).

A claim's quote must verify against the checked chapter, or the claim is dropped. A
contradicts or consistent finding must carry a manuscript quote that verifies, or it is
shown as new.
"""

import html
import math
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from margin.ask import EmptyIndexError, snippet
from margin.config import Settings, estimate_cost
from margin.index import PassageStore
from margin.llm import ModelBusyError, ModelClient, ModelReply
from margin.manuscript import Chapter
from margin.retrieval import Retriever
from margin.steps import claims as claims_step
from margin.steps import judge as judge_step
from margin.verify import quote_in_passage

TOKENS_PER_WORD = 1.4


def sections(paragraphs: list[str], words: int) -> list[list[str]]:
    """Paragraph-aligned sections of about `words` words, so no prompt grows with the chapter."""
    out: list[list[str]] = [[]]
    count = 0
    for p in paragraphs:
        n = len(p.split())
        if out[-1] and count + n > words:
            out.append([])
            count = 0
        out[-1].append(p)
        count += n
    return [s for s in out if s]


def worst_case_cost(chapter_words: int, s: Settings) -> float:
    n_sections = max(1, math.ceil(chapter_words / s.section_words))
    extract_in = int(min(chapter_words, s.section_words) * TOKENS_PER_WORD) + 600
    extract = n_sections * (estimate_cost(s.claims_model, extract_in, s.claims_max_tokens) or 0)
    judge_in = int(s.check_top_k * 800 * TOKENS_PER_WORD) + 800  # passages at the prompt cap
    judge = s.claim_cap * (estimate_cost(s.judge_model, judge_in, s.judge_max_tokens) or 0)
    return extract + judge


def locate(quote: str, paragraphs: list[str]) -> int | None:
    """The 1-based paragraph a verified quote starts in (it may run into the next one)."""
    for i, p in enumerate(paragraphs):
        if quote_in_passage(quote, p):
            return i + 1
    for i in range(len(paragraphs) - 1):
        if quote_in_passage(quote, paragraphs[i] + "\n\n" + paragraphs[i + 1]):
            return i + 1
    return None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, reply: ModelReply[Any]) -> None:
        with self._lock:
            self.input_tokens += reply.input_tokens
            self.output_tokens += reply.output_tokens
            self.cost += estimate_cost(model, reply.input_tokens, reply.output_tokens) or 0.0
            self.calls += 1


def _call_twice(fn: Any, model: str, usage: Usage) -> ModelReply[Any]:
    """One retry for output that fails the schema; truncation and refusals aren't retried."""
    reply: ModelReply[Any] = fn()
    usage.add(model, reply)
    if reply.output is None and reply.stop_reason not in ("refusal", "max_tokens"):
        reply = fn()
        usage.add(model, reply)
    return reply


def run(
    chapter: Chapter,
    *,
    retriever: Retriever,
    store: PassageStore,
    client: ModelClient,
    settings: Settings,
    replaces: int | list[int] | None = None,
) -> Iterator[tuple[str, Any]]:
    """Events: claim_count, finding (one per claim, as judged), debug, done."""
    s = settings
    if store.stats().passages == 0:
        raise EmptyIndexError()
    usage = Usage()
    text_paragraphs = chapter.paragraphs

    # 1. Claims, section by section; each quote must verify against the chapter.
    found: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    dropped_claims: list[dict[str, str]] = []
    capped = False
    for section in sections(text_paragraphs, s.section_words):
        left = s.claim_cap - len(found)
        if left <= 0:
            capped = True
            break
        reply = _call_twice(
            lambda section=section, left=left: claims_step.extract(
                client,
                title=chapter.title,
                text="\n\n".join(section),
                cap=left,
                model=s.claims_model,
                effort=s.claims_effort,
                max_tokens=s.claims_max_tokens,
            ),
            s.claims_model,
            usage,
        )
        if reply.output is None:
            yield "debug", {"kind": "model_error", "step": "claims", "error": reply.error}
            continue
        for c in reply.output.claims[:left]:
            quote = html.unescape(c.quote)
            para = locate(quote, text_paragraphs)
            if para is None:
                dropped_claims.append({"claim": c.text, "quote": c.quote})
                continue
            if quote.lower() in seen:
                continue
            seen.add(quote.lower())
            found.append((html.unescape(c.text), quote, para))
        if len(reply.output.claims) >= left and len(found) >= s.claim_cap:
            capped = True
    for d in dropped_claims:
        yield "debug", {"kind": "failed_claim_quote", **d}
    yield "claim_count", {"claims": len(found), "capped": capped, "cap": s.claim_cap}

    # 2. Judge each claim against its retrieved passages, a few at a time.
    def check_one(n: int, text: str, quote: str, para: int) -> dict[str, Any]:
        retrieved = retriever.retrieve(
            text + " " + quote, k=s.check_top_k, exclude_chapter=replaces
        )
        passages = [r.passage for r in retrieved]
        by_id = {p.id: p for p in passages}
        finding: dict[str, Any] = {
            "n": n,
            "claim": text,
            "quote": quote,
            "paragraph": para,
            "verdict": "new",
            "explanation": "",
            "citations": [],
            "failed": [],
        }
        if not passages:
            return finding
        reply = _call_twice(
            lambda: judge_step.judge(
                client,
                claim=text,
                quote=quote,
                passages=passages,
                model=s.judge_model,
                effort=s.judge_effort,
                max_tokens=s.judge_max_tokens,
            ),
            s.judge_model,
            usage,
        )
        if reply.output is None:
            finding["verdict"] = "not_checked"
            finding["error"] = reply.error
            return finding
        out = reply.output
        if out.verdict == "new":
            return finding
        for c in out.citations:
            p = by_id.get(c.passage_id)
            if p is not None and quote_in_passage(c.quote, p.text):
                finding["citations"].append(
                    {
                        "passage_id": p.id,
                        "location": p.location,
                        "quote": html.unescape(c.quote),
                    }
                )
            else:
                finding["failed"].append({"passage_id": c.passage_id, "quote": c.quote})
        if finding["citations"]:  # grounded or silent: unverified verdicts become "new"
            finding["verdict"] = out.verdict
            finding["explanation"] = html.unescape(out.explanation)
        return finding

    counts = {"contradicts": 0, "consistent": 0, "new": 0, "not_checked": 0}
    quotes_total = quotes_failed = 0
    with ThreadPoolExecutor(max_workers=s.check_concurrency) as pool:
        futures = [pool.submit(check_one, n, *claim) for n, claim in enumerate(found, 1)]
        for future in as_completed(futures):
            try:
                finding = future.result()
            except ModelBusyError:
                for f in futures:
                    f.cancel()
                raise
            counts[finding["verdict"]] += 1
            quotes_total += len(finding["citations"]) + len(finding["failed"])
            quotes_failed += len(finding["failed"])
            yield "finding", finding

    yield (
        "done",
        {
            "counts": counts,
            "claims": len(found),
            "capped": capped,
            "models": sorted({s.claims_model, s.judge_model}),
            "calls": usage.calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost": usage.cost,
            "quotes_total": quotes_total,
            "quotes_failed": quotes_failed,
            "claim_quotes_failed": len(dropped_claims),
        },
    )


def chapter_snippet(chapter: Chapter) -> str:
    return snippet(" ".join(chapter.paragraphs), 10)
