"""Ingest: read a manuscript, split it into passages, embed them locally, replace the index."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from margin import manuscript as ms
from margin import passages as ps
from margin.config import Settings
from margin.embedding import Embedder
from margin.index import ElasticIndex


@dataclass
class IngestResult:
    manuscript: str
    chapters: list[dict[str, Any]]
    words: int
    passages: int
    seconds: float


def ingest(
    path: Path, *, index: ElasticIndex, embedder: Embedder, settings: Settings
) -> IngestResult:
    started = time.perf_counter()
    manuscript = ms.load(path)  # raises NoChaptersError before the index is touched
    passages = ps.split(manuscript, settings.min_passage_words, settings.max_passage_words)
    vectors = embedder.embed_passages([p.text for p in passages])
    chapters = ps.chapter_summary(manuscript.chapters)
    index.replace(manuscript.name, chapters, passages, vectors)
    return IngestResult(
        manuscript=manuscript.name,
        chapters=chapters,
        words=manuscript.words,
        passages=len(passages),
        seconds=time.perf_counter() - started,
    )
