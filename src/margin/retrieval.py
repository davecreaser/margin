"""Hybrid retrieval: BM25 and kNN, merged with reciprocal rank fusion (ADR 0003)."""

from dataclasses import dataclass
from typing import Literal

from margin.embedding import Embedder
from margin.index import PassageStore
from margin.passages import Passage

Mode = Literal["hybrid", "bm25", "knn"]


@dataclass
class Retrieved:
    passage: Passage
    score: float  # the fused score (or the single method's score)
    bm25_rank: int | None = None
    bm25_score: float | None = None
    knn_rank: int | None = None
    knn_score: float | None = None


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Fuse ranked lists of ids: each id scores the sum of 1 / (k + rank) over the lists."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


class Retriever:
    def __init__(
        self, store: PassageStore, embedder: Embedder, top_k: int, candidates: int, rrf_k: int
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.top_k = top_k
        self.candidates = max(candidates, top_k)
        self.rrf_k = rrf_k

    def retrieve(
        self,
        question: str,
        mode: Mode = "hybrid",
        k: int | None = None,
        exclude_chapter: int | None = None,
    ) -> list[Retrieved]:
        k = k or self.top_k
        bm25 = self.store.bm25(question, self.candidates, exclude_chapter) if mode != "knn" else []
        knn = (
            self.store.knn(self.embedder.embed_query(question), self.candidates, exclude_chapter)
            if mode != "bm25"
            else []
        )
        found: dict[str, Retrieved] = {}
        for rank, (p, s) in enumerate(bm25, 1):
            found.setdefault(p.id, Retrieved(p, 0.0))
            found[p.id].bm25_rank, found[p.id].bm25_score = rank, s
        for rank, (p, s) in enumerate(knn, 1):
            found.setdefault(p.id, Retrieved(p, 0.0))
            found[p.id].knn_rank, found[p.id].knn_score = rank, s
        if mode == "hybrid":
            fused = reciprocal_rank_fusion(
                [[p.id for p, _ in bm25], [p.id for p, _ in knn]], self.rrf_k
            )
        else:
            fused = [(p.id, s) for p, s in (bm25 or knn)]
        results = []
        for pid, score in fused[:k]:
            found[pid].score = score
            results.append(found[pid])
        return results
