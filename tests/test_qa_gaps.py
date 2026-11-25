"""Acceptance checks added in QA for spec 0001 (fake model client, invented text only)."""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from margin import ask
from margin import manuscript as ms
from margin.config import Settings
from margin.ingest import ingest
from margin.passages import Passage
from margin.retrieval import Retriever
from margin.steps.answer import AnswerOutput, Citation, Statement
from margin.verify import quote_in_passage
from tests.fakes import FakeClient, FixedEmbedder, InMemoryStore, reply


class RecordingIndex:
    def __init__(self) -> None:
        self.replaced: list[tuple[str, int]] = []

    def replace(
        self, manuscript: str, chapters: Any, passages: list[Passage], vectors: Any
    ) -> None:
        self.replaced.append((manuscript, len(passages)))


def _fingerprint(folder: Path) -> dict[str, tuple[str, int]]:
    return {
        str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
    }


# --- AC-3: the whole ingest only reads the source, and a failed read leaves the index alone


def test_full_ingest_never_writes_to_the_source_folder(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"{i:02d}.md").write_text(
            f"# Chapter {i}\n\nThe ferry left at {i} o'clock.\n\nThe gulls followed it out.\n"
        )
    before = _fingerprint(tmp_path)
    index = RecordingIndex()
    ingest(tmp_path, index=index, embedder=FixedEmbedder([1.0, 0.0]), settings=Settings())  # type: ignore[arg-type]
    assert index.replaced == [(tmp_path.name, 3)]
    assert _fingerprint(tmp_path) == before


def test_no_chapters_leaves_the_index_untouched(tmp_path: Path) -> None:
    f = tmp_path / "notes.txt"
    f.write_text("Plot notes with no chapter headings.\n")
    index = RecordingIndex()
    with pytest.raises(ms.NoChaptersError):
        ingest(f, index=index, embedder=FixedEmbedder([1.0, 0.0]), settings=Settings())  # type: ignore[arg-type]
    assert index.replaced == []


# --- AC-6: curly versus straight quotes, in both directions


@pytest.mark.parametrize(
    ("quote", "passage"),
    [
        ("she didn't want the herring", "And she didn’t want the herring at all."),
        ("she didn’t want the herring", "And she didn't want the herring at all."),
        ('the sign read "Closed for winter"', "Then the sign read “Closed for winter” again."),
        ("the sign read “Closed for winter”", 'Then the sign read "Closed for winter" again.'),
        ("‘Not today,’ said Osric", "'Not today,' said Osric, and shut the door."),
    ],
)
def test_curly_and_straight_quotes_match_either_way(quote: str, passage: str) -> None:
    assert quote_in_passage(quote, passage)


def test_quote_marks_never_excuse_a_changed_word() -> None:
    assert not quote_in_passage("she didn’t need the herring", "And she didn't want the herring.")


# --- Bugs found in QA, recorded as strict xfails so they flip when fixed


PASSAGE = Passage(
    1, "One", 2, 2, 'The sign over the window read "Tolliver & Daughter" in faded gilt.'
)


def _run(out: AnswerOutput) -> ask.AskResult:
    store = InMemoryStore([PASSAGE], [[1.0, 0.0]])
    retriever = Retriever(store, FixedEmbedder([1.0, 0.0]), top_k=8, candidates=8, rrf_k=60)
    return ask.run(
        "What does the sign say?",
        retriever=retriever,
        store=store,
        client=FakeClient(reply(out)),  # type: ignore[arg-type]
        settings=Settings(),
    )


def test_shown_quote_is_the_text_as_written_not_xml_escaped() -> None:
    # The prompt escapes "&" as "&amp;", and the model copies the quote from the prompt.
    # Verification unescapes, so the quote verifies, but it is then shown with "&amp;".
    out = AnswerOutput(
        kind="answer",
        statements=[
            Statement(
                text="The sign reads Tolliver & Daughter.",
                citations=[
                    Citation(passage_id="1:2-2", quote="read &quot;Tolliver &amp; Daughter")
                ],
            )
        ],
    )
    shown = [
        d["quote"]
        for n, d in ask.events(_run(out), show_passages=False, debug=False)
        if n == "citation"
    ]
    assert shown == ['read "Tolliver & Daughter']


def test_answer_is_at_most_four_statements() -> None:
    statements = [
        Statement(
            text=f"Statement {i}.",
            citations=[Citation(passage_id="1:2-2", quote="the sign over the window")],
        )
        for i in range(6)
    ]
    result = _run(AnswerOutput(kind="answer", statements=statements))
    assert 1 <= len(result.statements) <= 4


def test_book_title_heading_is_not_a_chapter(tmp_path: Path) -> None:
    f = tmp_path / "book.md"
    f.write_text(
        "# The Lantern Road\n\nA novel\n\n## Chapter 1\n\nThe lamp was lit.\n\n"
        "## Chapter 2\n\nThe ferry came in.\n"
    )
    assert [c.title for c in ms.load(f).chapters] == ["Chapter 1", "Chapter 2"]


def test_prose_line_starting_with_chapter_is_not_a_heading(tmp_path: Path) -> None:
    f = tmp_path / "book.txt"
    f.write_text(
        "Chapter 1\n\nThe clerk read it aloud.\n\nChapter 5 of the lease was torn.\n\nHe sighed.\n"
    )
    assert len(ms.load(f).chapters) == 1
