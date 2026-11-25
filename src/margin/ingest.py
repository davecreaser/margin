"""Ingest: read a manuscript, split it into passages, embed them locally, replace the index.

Sources are a local folder or file, or a Google Doc (spec 0003). Sources are only read.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from margin import gdocs
from margin import manuscript as ms
from margin import passages as ps
from margin.config import Settings
from margin.embedding import Embedder


class Index(Protocol):
    def replace(
        self, manuscript: str, chapters: Any, passages: list[ps.Passage], vectors: Any
    ) -> None: ...


class StatsIndex(Index, Protocol):
    def stats(self) -> Any: ...


class Docs(Protocol):
    def revision(self, doc: str) -> tuple[str, str]: ...
    def fetch(self, doc: str) -> dict[str, Any]: ...


@dataclass
class IngestResult:
    manuscript: str
    chapters: list[dict[str, Any]]
    words: int
    passages: int
    seconds: float
    source: str = "file"
    unchanged: bool = False
    tabs_read: list[str] = field(default_factory=list)
    tabs_reused: list[str] = field(default_factory=list)
    tabs_excluded: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    passages_embedded: int | None = None


def _index(
    manuscript: ms.Manuscript, *, index: Index, embedder: Embedder, settings: Settings
) -> tuple[list[dict[str, Any]], int]:
    passages = ps.split(manuscript, settings.min_passage_words, settings.max_passage_words)
    vectors = embedder.embed_passages([p.text for p in passages])
    chapters = ps.chapter_summary(manuscript.chapters)
    index.replace(manuscript.name, chapters, passages, vectors)
    return chapters, len(passages)


def ingest(path: Path, *, index: Index, embedder: Embedder, settings: Settings) -> IngestResult:
    started = time.perf_counter()
    manuscript = ms.load(path)  # raises NoChaptersError before the index is touched
    misses = getattr(embedder, "misses", None)
    chapters, n = _index(manuscript, index=index, embedder=embedder, settings=settings)
    return IngestResult(
        manuscript=manuscript.name,
        chapters=chapters,
        words=manuscript.words,
        passages=n,
        seconds=time.perf_counter() - started,
        passages_embedded=None if misses is None else embedder.misses - misses,  # type: ignore[attr-defined]
    )


# --- Google Docs -----------------------------------------------------------------------


def _state_dir(data_dir: Path) -> Path:
    return data_dir / "google-docs"


def _load_state(data_dir: Path, doc: str) -> dict[str, Any]:
    p = _state_dir(data_dir) / f"{doc}.json"
    return dict(json.loads(p.read_text())) if p.exists() else {}


def _save_state(data_dir: Path, doc: str, state: dict[str, Any]) -> None:
    d = _state_dir(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{doc}.json").write_text(json.dumps(state))
    (d / "current.json").write_text(json.dumps({"doc": doc, "title": state["title"]}))


def current_doc(data_dir: Path) -> dict[str, str] | None:
    p = _state_dir(data_dir) / "current.json"
    return dict(json.loads(p.read_text())) if p.exists() else None


def _patterns(exclude: list[str] | None, state: dict[str, Any]) -> list[str]:
    if exclude is None:
        return list(state.get("exclude", []))
    return sorted({p.strip() for p in exclude if p.strip()})  # [""] clears them


def ingest_google(
    link: str,
    *,
    exclude: list[str] | None,
    docs: Docs,
    index: StatsIndex,
    embedder: Embedder,
    settings: Settings,
    data_dir: Path,
) -> IngestResult:
    started = time.perf_counter()
    doc = gdocs.doc_id(link)
    state = _load_state(data_dir, doc)
    patterns = _patterns(exclude, state)
    title, revision = docs.revision(doc)

    stats = index.stats()
    if (
        state.get("revision") == revision
        and state.get("exclude", []) == patterns
        and stats.manuscript == title
        and stats.passages > 0
    ):
        _save_state(data_dir, doc, state)  # it is the current document again
        return IngestResult(
            manuscript=title,
            chapters=stats.chapters,
            words=sum(c["words"] for c in stats.chapters),
            passages=stats.passages,
            seconds=time.perf_counter() - started,
            source="google",
            unchanged=True,
            tabs_reused=list(state.get("tabs", {}).values()),
            tabs_excluded=state.get("excluded", []),
            exclude=patterns,
            passages_embedded=0,
        )

    all_tabs = gdocs.tabs(docs.fetch(doc))
    left_out = [t.title for t in all_tabs if gdocs.excluded(t.title, patterns)]
    used = [t for t in all_tabs if not gdocs.excluded(t.title, patterns) and t.text.strip()]
    manuscript, by_tab = ms.from_tabs(title, [(t.id, t.title, t.lines) for t in used])
    old = state.get("hashes", {})
    reused = [t.title for t in used if old.get(t.id) == t.hash]
    read = [t.title for t in used if old.get(t.id) != t.hash]
    misses = getattr(embedder, "misses", None)
    chapters, n = _index(manuscript, index=index, embedder=embedder, settings=settings)
    _save_state(
        data_dir,
        doc,
        {
            "title": title,
            "revision": revision,
            "exclude": patterns,
            "excluded": left_out,
            "hashes": {t.id: t.hash for t in used},
            "tabs": {t.id: t.title for t in used},
            "chapters": by_tab,
        },
    )
    return IngestResult(
        manuscript=title,
        chapters=chapters,
        words=manuscript.words,
        passages=n,
        seconds=time.perf_counter() - started,
        source="google",
        tabs_read=read,
        tabs_reused=reused,
        tabs_excluded=left_out,
        exclude=patterns,
        passages_embedded=None if misses is None else embedder.misses - misses,  # type: ignore[attr-defined]
    )


def tab_list(link: str, *, docs: Docs, data_dir: Path) -> dict[str, Any]:
    """The document's tabs, for choosing which to exclude before ingesting."""
    doc = gdocs.doc_id(link)
    document = docs.fetch(doc)
    patterns = _patterns(None, _load_state(data_dir, doc))
    return {
        "doc": doc,
        "title": document.get("title", "Untitled"),
        "exclude": patterns,
        "tabs": [
            {"title": t.title, "words": t.words, "excluded": gdocs.excluded(t.title, patterns)}
            for t in gdocs.tabs(document)
        ],
    }


def load_tab(name: str, *, docs: Docs, data_dir: Path) -> tuple[ms.Chapter, str, list[int]]:
    """A tab of the ingested Google Doc, fetched fresh, as one chapter to check, with the
    indexed chapters it became at the last ingest (empty if it wasn't indexed)."""
    current = current_doc(data_dir)
    if current is None:
        raise gdocs.GoogleError("No Google Doc has been ingested: ./margin ingest <link>")
    all_tabs = gdocs.tabs(docs.fetch(current["doc"]))
    match = [t for t in all_tabs if t.title.casefold() == name.strip().casefold()]
    if not match:
        names = ", ".join(t.title for t in all_tabs)
        err = gdocs.GoogleError(f"No tab called {name}. Tabs: {names}")
        err.status = 404
        raise err
    tab = match[0]
    chapter = ms.chapter_from_lines(tab.title, tab.lines)
    chapter.title = tab.title
    indexed = _load_state(data_dir, current["doc"]).get("chapters", {}).get(tab.id, [])
    return chapter, current["title"], list(indexed)
