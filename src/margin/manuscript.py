"""Reading a manuscript: a folder of chapter files, or one file with chapter headings.

Margin only ever reads the source files.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt"}
SINGLE_FILE_SUFFIXES = TEXT_SUFFIXES | {".docx"}

# "# Title", "## Chapter 3", "Chapter 3", "CHAPTER III", "Chapter 12: The Card"
MARKDOWN_HEADING = re.compile(r"^#{1,3}\s+(?P<title>.+?)\s*#*\s*$")
CHAPTER_LINE = re.compile(
    r"^(?:chapter|CHAPTER|Chapter)\s+(?P<num>\d+|[IVXLCDM]+|[ivxlcdm]+)\b[\s.:\-–—]*(?P<rest>.*)$"
)
SCENE_BREAK = re.compile(r"^\s*([*#~\-–—]\s*){3,}$|^\s*#\s*$")


class NoChaptersError(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"No chapters found in {name}: use one file per chapter, or chapter headings"
        )


@dataclass
class Chapter:
    number: int
    title: str
    paragraphs: list[str] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)


@dataclass
class Manuscript:
    name: str
    chapters: list[Chapter]

    @property
    def words(self) -> int:
        return sum(c.words for c in self.chapters)


def load(path: Path) -> Manuscript:
    """Read a manuscript from a folder of chapter files or a single file."""
    if path.is_dir():
        chapters = _from_folder(path)
    elif path.is_file() and path.suffix.lower() in SINGLE_FILE_SUFFIXES:
        lines = _docx_lines(path) if path.suffix.lower() == ".docx" else _text_lines(path)
        chapters = _from_headings(lines)
    else:
        chapters = []
    chapters = [c for c in chapters if c.paragraphs]
    if not chapters:
        raise NoChaptersError(path.name)
    for number, chapter in enumerate(chapters, 1):
        chapter.number = number
    return Manuscript(name=path.name, chapters=chapters)


def _text_lines(path: Path) -> list[str]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")  # older Windows exports
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _docx_lines(path: Path) -> list[str]:
    import docx

    lines: list[str] = []
    for para in docx.Document(str(path)).paragraphs:
        style = (para.style.name if para.style is not None else "") or ""
        text = para.text.strip()
        if style.lower().startswith("heading") and text:
            lines.append(f"# {text}")
        else:
            lines.append(text)
        lines.append("")  # each docx paragraph is its own paragraph
    return lines


def _paragraphs(lines: list[str]) -> list[str]:
    """Blank-line separated paragraphs, with hard-wrapped lines joined. Scene breaks are skipped.

    Text with no blank lines between its lines (one paragraph per line, a common export)
    is read as one paragraph per line.
    """
    text_lines = [line for line in lines if line.strip()]
    first = next((i for i, line in enumerate(lines) if line.strip()), 0)
    last = max((i for i, line in enumerate(lines) if line.strip()), default=0)
    if len(text_lines) > 1 and all(line.strip() for line in lines[first : last + 1]):
        return [t.strip() for t in text_lines if not SCENE_BREAK.match(t)]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in [*lines, ""]:
        if line.strip():
            current.append(line.strip())
            continue
        if current:
            text = " ".join(current)
            if not SCENE_BREAK.match(text):
                paragraphs.append(text)
            current = []
    return paragraphs


def _heading(line: str) -> str | None:
    """The chapter title if this line is a chapter heading."""
    stripped = line.strip()
    if m := MARKDOWN_HEADING.match(stripped):
        return m.group("title").strip()
    if (m := CHAPTER_LINE.match(stripped)) and len(stripped) <= 80:
        return stripped
    return None


def _from_headings(lines: list[str]) -> list[Chapter]:
    chapters: list[Chapter] = []
    body: list[str] = []
    title: str | None = None

    def flush() -> None:
        if title is not None:
            chapters.append(Chapter(number=0, title=title, paragraphs=_paragraphs(body)))

    for line in lines:
        heading = _heading(line)
        if heading is not None:
            flush()
            title, body = heading, []
        else:
            body.append(line)  # text before the first heading (front matter) is ignored
    flush()
    return chapters


def _from_folder(folder: Path) -> list[Chapter]:
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
    chapters = []
    for path in files:
        lines = _text_lines(path)
        title = path.stem
        # A heading on the first non-blank line is the chapter's title, not a paragraph.
        for i, line in enumerate(lines):
            if line.strip():
                if (heading := _heading(line)) is not None:
                    title, lines = heading, lines[i + 1 :]
                break
        chapters.append(Chapter(number=0, title=title, paragraphs=_paragraphs(lines)))
    return chapters
