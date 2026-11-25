"""Splitting chapters into passages: runs of whole paragraphs inside one chapter.

The splitting rule is a pure function (`paragraph_ranges`). `ParagraphPassageParser` wraps
it as a LlamaIndex node parser, so passages are LlamaIndex `TextNode`s carrying their chapter
and paragraph range (ADR 0004).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from llama_index.core.node_parser import NodeParser
from llama_index.core.schema import BaseNode, Document, TextNode

from margin.manuscript import Chapter, Manuscript

PARAGRAPH_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class Passage:
    chapter: int
    chapter_title: str
    para_start: int  # 1-based, inclusive
    para_end: int
    text: str

    @property
    def id(self) -> str:
        return f"{self.chapter}:{self.para_start}-{self.para_end}"

    @property
    def location(self) -> str:
        paras = (
            f"¶ {self.para_start}"
            if self.para_start == self.para_end
            else f"¶ {self.para_start}–{self.para_end}"
        )
        return f"{chapter_label(self.chapter, self.chapter_title)}, {paras}"


# Titles that already say what they are: "Interlude II", "Chapter IV", "Part 2", "Prologue".
SELF_LABELLED = re.compile(
    r"^(chapter|interlude|prologue|epilogue|part|book|act|intro|introduction|outro|"
    r"afterword|foreword|preface|coda|appendix)\b",
    re.IGNORECASE,
)


def chapter_label(number: int, title: str) -> str:
    """How a chapter is named to the author: its own title when that names it ("Interlude II"),
    otherwise its place in the manuscript ("Chapter 3"). Never a position that clashes with the
    author's own numbering."""
    title = title.strip()
    return title if SELF_LABELLED.match(title) else f"Chapter {number}"


def paragraph_ranges(word_counts: Sequence[int], min_words: int, max_words: int) -> list[range]:
    """Group paragraphs into passages of about min_words..max_words, never splitting one.

    A paragraph longer than max_words is a passage of its own. A short last passage joins
    the one before it when the result stays within max_words plus min_words.
    """
    ranges: list[range] = []
    start, words = 0, 0
    for i, count in enumerate(word_counts):
        if i > start and words >= min_words and words + count > max_words:
            ranges.append(range(start, i))
            start, words = i, 0
        words += count
    if start < len(word_counts):
        tail = range(start, len(word_counts))
        if ranges and words < min_words:
            previous = ranges[-1]
            merged = sum(word_counts[j] for j in previous) + words
            if merged <= max_words + min_words:
                ranges[-1] = range(previous.start, tail.stop)
                return ranges
        ranges.append(tail)
    return ranges


def chapter_documents(manuscript: Manuscript) -> list[Document]:
    return [
        Document(
            text=PARAGRAPH_SEPARATOR.join(chapter.paragraphs),
            metadata={"chapter": chapter.number, "chapter_title": chapter.title},
        )
        for chapter in manuscript.chapters
        if chapter.paragraphs  # a chapter with no text yet has no passages
    ]


class ParagraphPassageParser(NodeParser):
    """LlamaIndex node parser: one chapter Document in, paragraph-aligned passage nodes out."""

    min_words: int = 150
    max_words: int = 400

    def _parse_nodes(
        self, nodes: Sequence[BaseNode], show_progress: bool = False, **kwargs: Any
    ) -> list[BaseNode]:
        out: list[BaseNode] = []
        for node in nodes:
            paragraphs = node.get_content().split(PARAGRAPH_SEPARATOR)
            counts = [len(p.split()) for p in paragraphs]
            for r in paragraph_ranges(counts, self.min_words, self.max_words):
                chapter = int(node.metadata["chapter"])
                out.append(
                    TextNode(
                        id_=f"{chapter}:{r.start + 1}-{r.stop}",
                        text=PARAGRAPH_SEPARATOR.join(paragraphs[r.start : r.stop]),
                        metadata={
                            "chapter": chapter,
                            "chapter_title": node.metadata["chapter_title"],
                            "para_start": r.start + 1,
                            "para_end": r.stop,
                        },
                    )
                )
        return out


def split(manuscript: Manuscript, min_words: int, max_words: int) -> list[Passage]:
    parser = ParagraphPassageParser(min_words=min_words, max_words=max_words)
    nodes = parser.get_nodes_from_documents(chapter_documents(manuscript))
    return [
        Passage(
            chapter=n.metadata["chapter"],
            chapter_title=n.metadata["chapter_title"],
            para_start=n.metadata["para_start"],
            para_end=n.metadata["para_end"],
            text=n.get_content(),
        )
        for n in nodes
    ]


def chapter_summary(chapters: Sequence[Chapter]) -> list[dict[str, Any]]:
    return [{"number": c.number, "title": c.title, "words": c.words} for c in chapters]
