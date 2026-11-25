"""Build the bundled demo manuscript from Project Gutenberg eBook #12986.

Usage: python scripts/build_demo.py <path to pg12986.txt>

Writes src/margin/demo/the-card/NN-title.md, one Markdown file per chapter:
- the Project Gutenberg header, footer and front matter are removed
- hard-wrapped lines are joined, so each paragraph is one line
- the numbered sections inside a chapter ("I", "II", ...) become scene breaks ("* * *")

The words themselves are not changed.
"""

import re
import sys
from pathlib import Path

ROMAN = re.compile(r"^[IVXLC]+$")
OUT = Path(__file__).resolve().parent.parent / "src" / "margin" / "demo" / "the-card"


def main(source: Path) -> None:
    text = source.read_text(encoding="utf-8").replace("\r\n", "\n")
    body = text.split("*** START OF THE PROJECT GUTENBERG EBOOK", 1)[1]
    body = body.split("*** END OF THE PROJECT GUTENBERG EBOOK", 1)[0]
    parts = re.split(r"\n\s*CHAPTER ([IVXLC]+)\s*\n", body)[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    for n, (_numeral, chapter) in enumerate(zip(parts[::2], parts[1::2], strict=True), 1):
        blocks = [" ".join(b.split()) for b in re.split(r"\n\s*\n", chapter.strip())]
        blocks = [b for b in blocks if b]
        title = " ".join(w.capitalize() for w in blocks[0].lower().split())
        if "* * * * *" in blocks:  # the printer's colophon after the last chapter
            blocks = blocks[: blocks.index("* * * * *")]
        paras: list[str] = []
        for block in blocks[1:]:
            if ROMAN.match(block):
                if paras:
                    paras.append("* * *")
                continue
            paras.append(block)
        slug = re.sub(r"[^a-z]+", "-", title.lower().replace("'", "")).strip("-")
        path = OUT / f"{n:02d}-{slug}.md"
        path.write_text(f"# {title}\n\n" + "\n\n".join(paras) + "\n", encoding="utf-8")
        print(f"{path.name}: {sum(len(p.split()) for p in paras)} words")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
