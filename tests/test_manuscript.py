import hashlib
from pathlib import Path

import docx
import pytest

from margin import manuscript as ms
from margin.config import DEMO_DIR


def test_folder_one_chapter_per_file_in_file_name_order(tmp_path: Path) -> None:
    (tmp_path / "02-second.md").write_text("# The Second\n\nBeta para.\n\nGamma para.\n")
    (tmp_path / "01-first.txt").write_text("Alpha para one\ncontinues here.\n\nAlpha two.\n")
    (tmp_path / "notes.json").write_text("{}")
    m = ms.load(tmp_path)
    assert [(c.number, c.title) for c in m.chapters] == [(1, "01-first"), (2, "The Second")]
    assert m.chapters[0].paragraphs == ["Alpha para one continues here.", "Alpha two."]
    assert m.chapters[1].paragraphs == ["Beta para.", "Gamma para."]


def test_single_file_with_markdown_headings_skips_front_matter(tmp_path: Path) -> None:
    f = tmp_path / "book.md"
    f.write_text("Title page\n\n## One\n\nFirst.\n\n* * *\n\nSecond.\n\n## Two\n\nThird.\n")
    m = ms.load(f)
    assert [c.title for c in m.chapters] == ["One", "Two"]
    assert m.chapters[0].paragraphs == ["First.", "Second."]  # scene break skipped


@pytest.mark.parametrize("heading", ["Chapter 3", "CHAPTER III", "Chapter 12: The Card"])
def test_single_text_file_with_chapter_lines(tmp_path: Path, heading: str) -> None:
    f = tmp_path / "book.txt"
    f.write_text(f"{heading}\n\nOne paragraph.\n\nChapter 4\n\nAnother.\n")
    m = ms.load(f)
    assert [c.title for c in m.chapters] == [heading, "Chapter 4"]
    assert [c.number for c in m.chapters] == [1, 2]


def test_docx_with_heading_styles(tmp_path: Path) -> None:
    d = docx.Document()
    d.add_heading("Opening", level=1)
    d.add_paragraph("The lamp was lit.")
    d.add_paragraph("The door was shut.")
    d.add_heading("Closing", level=1)
    d.add_paragraph("The end came.")
    f = tmp_path / "book.docx"
    d.save(str(f))
    m = ms.load(f)
    assert [c.title for c in m.chapters] == ["Opening", "Closing"]
    assert m.chapters[0].paragraphs == ["The lamp was lit.", "The door was shut."]


def test_no_chapters_gives_the_spec_message(tmp_path: Path) -> None:
    f = tmp_path / "notes.txt"
    f.write_text("Just some text with no headings at all.\n")
    with pytest.raises(ms.NoChaptersError) as e:
        ms.load(f)
    assert str(e.value) == (
        "No chapters found in notes.txt: use one file per chapter, or chapter headings"
    )


def test_empty_folder_has_no_chapters(tmp_path: Path) -> None:
    with pytest.raises(ms.NoChaptersError):
        ms.load(tmp_path)


def test_demo_novel_has_twelve_chapters() -> None:
    m = ms.load(DEMO_DIR)
    assert len(m.chapters) == 12
    assert m.chapters[0].title == "The Dance"
    assert 70_000 < m.words < 80_000


def _fingerprint(folder: Path) -> dict[str, tuple[str, float]]:
    return {
        str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def test_reading_never_writes_to_the_source(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"{i:02d}.md").write_text(f"# Chapter {i}\n\nText {i}.\n")
    before = _fingerprint(tmp_path)
    ms.load(tmp_path)
    assert _fingerprint(tmp_path) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["00.md", "01.md", "02.md"]


def test_one_paragraph_per_line_without_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "book.txt"
    f.write_text("Chapter 1\nFirst paragraph.\nSecond paragraph.\nThird paragraph.\n")
    assert ms.load(f).chapters[0].paragraphs == [
        "First paragraph.",
        "Second paragraph.",
        "Third paragraph.",
    ]


def test_windows_1252_text_is_read(tmp_path: Path) -> None:
    f = tmp_path / "book.txt"
    f.write_bytes("# One\n\nShe said “hello”.\n".encode("cp1252"))
    assert ms.load(f).chapters[0].paragraphs == ["She said “hello”."]
