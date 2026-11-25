"""Test doubles: a fake model client, an in-memory passage store and a toy embedder."""

import math
import random
import re
from collections import Counter
from typing import Any

from pydantic import BaseModel

from margin.index import IndexStats
from margin.llm import ModelReply
from margin.passages import Passage


class FakeClient:
    """Returns canned replies in order and records every call."""

    def __init__(self, *replies: ModelReply[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def structured[T: BaseModel](
        self, *, model: str, system: str, user: str, schema: type[T], effort: str, max_tokens: int
    ) -> ModelReply[T]:
        self.calls.append({"model": model, "system": system, "user": user, "effort": effort})
        return self.replies.pop(0)


def reply(output: BaseModel | None, stop_reason: str = "end_turn") -> ModelReply[Any]:
    return ModelReply(output=output, input_tokens=4000, output_tokens=300, stop_reason=stop_reason)


def _excluded(chapter: int | list[int] | None) -> list[int]:
    return [] if chapter is None else chapter if isinstance(chapter, list) else [chapter]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


class InMemoryStore:
    """Toy BM25-ish keyword search plus cosine kNN over given vectors."""

    def __init__(self, passages: list[Passage], vectors: list[list[float]]) -> None:
        self.passages = passages
        self.vectors = vectors

    def bm25(
        self, question: str, k: int, exclude_chapter: int | list[int] | None = None
    ) -> list[tuple[Passage, float]]:
        q = set(_tokens(question))
        df = Counter(t for p in self.passages for t in set(_tokens(p.text)))
        n = len(self.passages)
        scored = []
        for p in self.passages:
            if p.chapter in _excluded(exclude_chapter):
                continue
            tf = Counter(_tokens(p.text))
            s = sum(tf[t] * math.log(1 + n / df[t]) for t in q if tf[t])
            if s > 0:
                scored.append((p, s))
        return sorted(scored, key=lambda x: -x[1])[:k]

    def knn(
        self, vector: list[float], k: int, exclude_chapter: int | list[int] | None = None
    ) -> list[tuple[Passage, float]]:
        def cos(a: list[float], b: list[float]) -> float:
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(x * x for x in b)) or 1.0
            return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)

        scored = [
            (p, cos(vector, v))
            for p, v in zip(self.passages, self.vectors, strict=True)
            if p.chapter not in _excluded(exclude_chapter)
        ]
        return sorted(scored, key=lambda x: -x[1])[:k]

    def stats(self) -> IndexStats:
        chapters = sorted({p.chapter for p in self.passages})
        return IndexStats("test", "test", [{"number": c} for c in chapters], len(self.passages))


class FixedEmbedder:
    """Returns a fixed query vector, so tests control the kNN ranking exactly."""

    def __init__(self, query_vector: list[float]) -> None:
        self.query_vector = query_vector

    @property
    def dimensions(self) -> int:
        return len(self.query_vector)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t) % 7), 1.0] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.query_vector


WORDS = [
    "the",
    "a",
    "of",
    "and",
    "to",
    "in",
    "was",
    "he",
    "she",
    "it",
    "that",
    "with",
    "as",
    "had",
    "his",
    "her",
    "for",
    "on",
    "at",
    "by",
    "but",
    "not",
    "from",
    "they",
    "said",
    "one",
    "all",
    "were",
    "when",
    "there",
    "would",
    "been",
    "their",
    "out",
    "up",
    "into",
    "so",
    "what",
    "could",
    "time",
    "door",
    "window",
    "street",
    "lamp",
    "kettle",
    "road",
    "morning",
    "evening",
    "letter",
    "coat",
    "chair",
    "town",
    "river",
    "walked",
    "looked",
    "turned",
    "waited",
    "answered",
    "smiled",
    "carried",
    "opened",
    "closed",
    "remembered",
]


def invented_text(words: int, seed: int = 7) -> list[str]:
    """Invented paragraphs (never real prose) totalling about `words` words."""
    rng = random.Random(seed)
    paragraphs: list[str] = []
    total = 0
    while total < words:
        sentences = []
        for _ in range(rng.randint(2, 7)):
            n = rng.randint(6, 20)
            sentences.append(" ".join(rng.choice(WORDS) for _ in range(n)).capitalize() + ".")
        paragraph = " ".join(sentences)
        paragraphs.append(paragraph)
        total += len(paragraph.split())
    return paragraphs
