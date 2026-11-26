"""Habits eval (spec 0007): deterministic, so it runs as pytest in CI and by hand as a table.

Gold labels are written into the texts as [[K:matched words]] (see labels.yaml). Grading is on
results, not wording: a found instance matches a gold one in the same text and paragraph when
their spans overlap, and each gold instance matches at most once.
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from margin import habits as hb
from margin import manuscript as ms
from margin import passages as ps
from margin import style as st
from margin.config import DEMO_DIR, Settings
from margin.timeline import chapters_from_passages

HERE = Path(__file__).parent
MARK = re.compile(r"\[\[([A-Z])(d?):(.+?)\]\]")
KIND = {"S": "similes", "A": "as_if", "G": "gestures", "F": "filter", "C": "crutch", "O": "openers"}
KINDS = list(KIND.values())


@dataclass
class Gold:
    kind: str
    text: str  # the file
    paragraph: int  # 1-based in its chapter
    start: int
    end: int
    dialogue: bool


@dataclass
class Book:
    """A labelled text, stripped of its labels, as indexed passages."""

    name: str
    chapters: list[ms.Chapter]
    passages: list[ps.Passage]
    gold: list[Gold] = field(default_factory=list)


def labels() -> dict[str, Any]:
    return dict(yaml.safe_load((HERE / "labels.yaml").read_text()))


def _strip(paragraph: str) -> tuple[str, list[tuple[str, bool, int, int]]]:
    out, marks, last = [], [], 0
    pos = 0
    for m in MARK.finditer(paragraph):
        out.append(paragraph[last : m.start()])
        pos += m.start() - last
        marks.append((KIND[m.group(1)], m.group(2) == "d", pos, pos + len(m.group(3))))
        out.append(m.group(3))
        pos += len(m.group(3))
        last = m.end()
    out.append(paragraph[last:])
    return "".join(out), marks


def _lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if not line.startswith("<!--")]


def book(files: list[str], s: Settings | None = None) -> Book:
    s = s or Settings()
    chapters: list[ms.Chapter] = []
    gold: list[Gold] = []
    for i, f in enumerate(files, 1):
        raw = ms.chapter_from_lines(Path(f).stem, _lines((HERE / f).read_text()))
        paragraphs = []
        for pi, para in enumerate(raw.paragraphs, 1):
            clean, marks = _strip(para)
            paragraphs.append(clean)
            gold += [Gold(k, f, pi, a, b, d) for k, d, a, b in marks]
        chapters.append(ms.Chapter(i, raw.title, paragraphs, scene_breaks=raw.scene_breaks))
    passages = ps.split(ms.Manuscript("eval", chapters), s.min_passage_words, s.max_passage_words)
    b = Book("eval", chapters_from_passages(passages), passages, gold)
    b.chapters = [
        ms.Chapter(
            c.number, c.title, c.paragraphs, scene_breaks=chapters[c.number - 1].scene_breaks
        )
        for c in b.chapters
    ]
    return b


@dataclass
class KindScore:
    gold: int = 0
    found: int = 0
    matched_gold: int = 0
    matched_found: int = 0
    misses: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.matched_gold / self.gold if self.gold else 1.0

    @property
    def precision(self) -> float:
        return self.matched_found / self.found if self.found else 1.0

    def add(self, other: "KindScore") -> None:
        self.gold += other.gold
        self.found += other.found
        self.matched_gold += other.matched_gold
        self.matched_found += other.matched_found
        self.misses += other.misses
        self.extras += other.extras


def grade_instances(b: Book, files: list[str], s: Settings | None = None) -> dict[str, Any]:
    """Recall and precision per kind, and the dialogue flag's accuracy on graded files."""
    s = s or Settings(habit_min_count=1)
    a = hb.analyse(b.name, b.chapters, b.passages, s)
    chapter_of = {f: i for i, f in enumerate(files, 1)}
    scores = {k: KindScore() for k in KINDS}
    flags = [0, 0]  # right, total
    for kind in KINDS:
        found = [i for h in a.habits if h.kind == kind for i in h.instances]
        gold = [g for g in b.gold if g.kind == kind]
        sc = scores[kind]
        sc.gold, sc.found = len(gold), len(found)
        used: set[int] = set()
        for i in found:
            hit = None
            for gi, g in enumerate(gold):
                if gi in used or chapter_of[g.text] != i.chapter or g.paragraph != i.paragraph:
                    continue
                if i.start < g.end and g.start < i.end:
                    hit = gi
                    break
            text = b.chapters[i.chapter - 1].paragraphs[i.paragraph - 1]
            where = f"{files[i.chapter - 1]} ¶{i.paragraph}: {text[max(0, i.start - 30) : i.end + 30]!r}"
            if hit is None:
                sc.extras.append(where)
                continue
            used.add(hit)
            sc.matched_found += 1
            g = gold[hit]
            if "d" in _flagged(g.text):
                flags[0] += int(i.dialogue == g.dialogue)
                flags[1] += 1
        sc.matched_gold = len(used)
        for gi, g in enumerate(gold):
            if gi not in used:
                text = b.chapters[chapter_of[g.text] - 1].paragraphs[g.paragraph - 1]
                sc.misses.append(f"{g.text} ¶{g.paragraph}: {text[g.start : g.end]!r}")
    return {"kinds": scores, "dialogue": flags, "failed": a.failed, "analysis": a}


def _flagged(f: str) -> str:
    return "d" if f in ("demo-excerpt.md", "adversarial.md") else ""


def grade_phrases(s: Settings | None = None) -> dict[str, Any]:
    lb = labels()
    files = [f for f in lb["files"] if f.startswith("invented/")]
    b = book(files, s)
    a = hb.analyse(b.name, b.chapters, b.passages, s or Settings())
    reported = [h for h in a.habits if h.kind == "phrases"]
    forms = [[h.label, *[f for f, _ in h.variants]] for h in reported]
    found = [p for p in lb["planted_phrases"] if any(p in f for fs in forms for f in fs)]
    leaked = [p for p in lb["must_not_report"] if any(p in f or f in p for fs in forms for f in fs)]
    return {
        "planted": lb["planted_phrases"],
        "found": found,
        "leaked": leaked,
        "reported": [h.label for h in reported],
    }


def demo_book() -> tuple[list[ms.Chapter], list[ps.Passage]]:
    s = Settings()
    m = ms.load(DEMO_DIR)
    passages = ps.split(m, s.min_passage_words, s.max_passage_words)
    return chapters_from_passages(passages), passages


def grade_demo_top(s: Settings | None = None, top: int = 20) -> dict[str, Any]:
    """Precision of the demo's top repeated phrases against phrases.yaml. An unlabelled phrase
    in the top fails the grade with "label these", so the labels can't go stale."""
    s = s or Settings()
    chapters, passages = demo_book()
    a = hb.analyse("the-card", chapters, passages, s)
    ranked = [h.label for h in a.habits if h.kind == "phrases"][:top]
    labelled = yaml.safe_load((HERE / "phrases.yaml").read_text())["labels"]
    unlabelled = [p for p in ranked if p not in labelled]
    yes = sum(1 for p in ranked if labelled.get(p) is True)
    return {
        "top": ranked,
        "unlabelled": unlabelled,
        "precision": yes / len(ranked) if ranked else 1.0,
    }


# --- House style ------------------------------------------------------------------------------


def _style_book(
    text: str,
) -> tuple[list[ms.Chapter], list[ps.Passage], dict[int, list[dict[str, Any]]]]:
    s = Settings()
    c = ms.chapter_from_lines("Chapter 1", _lines(text))
    c.number = 1
    passages = ps.split(ms.Manuscript("eval", [c]), s.min_passage_words, s.max_passage_words)
    breaks = {1: [{"after": a, "text": t} for a, t in c.scene_breaks]}
    return chapters_from_passages(passages), passages, breaks


def _mismatches(rules: dict[str, Any], text: str) -> list[tuple[str, str]]:
    chapters, passages, breaks = _style_book(text)
    ck = st.check(st.validate(rules), chapters, passages, breaks)
    out = []
    for f in ck.found:
        if f.paragraph == 0 or f.after:
            out.append((f.rule, f.what))
        else:
            out.append((f.rule, chapters[0].paragraphs[f.paragraph - 1][f.start : f.end]))
    return out


def grade_style() -> dict[str, Any]:
    """Per rule: planted edits found exactly; counterfactual spelling exact; clean controls."""
    plain = MARK.sub(lambda m: m.group(3), (HERE / "demo-excerpt.md").read_text())
    spec = yaml.safe_load((HERE / "edits.yaml").read_text())
    rules = spec["style"]
    edited = plain
    expected: list[tuple[str, str]] = []
    for e in spec["edits"]:
        assert edited.count(e["from"]) == 1, e["from"]
        edited = edited.replace(e["from"], e["to"])
        if e["rule"] == "quotes":
            expected += [("quotes", ch) for ch in e["mismatch"]]
        else:
            expected.append((e["rule"], e["mismatch"]))
    per_rule: dict[str, dict[str, int]] = {}

    def score(name: str, want: list[tuple[str, str]], got: list[tuple[str, str]]) -> None:
        for rule in {r for r, _ in want} | {r for r, _ in got}:
            w = sorted(x for r, x in want if r == rule)
            g = sorted(x for r, x in got if r == rule)
            matched = 0
            rest = list(g)
            for x in w:
                if x in rest:
                    rest.remove(x)
                    matched += 1
            d = per_rule.setdefault(rule, {"expected": 0, "found": 0, "matched": 0})
            d["expected"] += len(w)
            d["found"] += len(g)
            d["matched"] += matched

    score("edits", expected, _mismatches(rules, edited))
    clean_excerpt = _mismatches(rules, plain)
    template = (HERE / "spelling.md").read_text()
    pair = re.compile(r"\{([^|}]+)\|([^}]+)\}")
    gb = pair.sub(lambda m: m.group(1), template)
    us = pair.sub(lambda m: m.group(2), template)
    ambiguous = set(labels()["spelling_ambiguous"])
    want_us = [
        ("spelling", m.group(2)) for m in pair.finditer(template) if m.group(2) not in ambiguous
    ]
    want_gb = [
        ("spelling", m.group(1)) for m in pair.finditer(template) if m.group(1) not in ambiguous
    ]
    score("american copy, british", want_us, _mismatches({"spelling": "british"}, us))
    score("british copy, american", want_gb, _mismatches({"spelling": "american"}, gb))
    clean = {
        "excerpt as written": clean_excerpt,
        "british copy, british": _mismatches({"spelling": "british"}, gb),
        "american copy, american": _mismatches({"spelling": "american"}, us),
        "clean-style.md": _mismatches(rules, (HERE / "clean-style.md").read_text()),
    }
    return {"rules": per_rule, "clean": clean}


def grade_clean_habits() -> list[str]:
    b = book(["clean-habits.md"])
    a = hb.analyse(b.name, b.chapters, b.passages, Settings(habit_min_count=1))
    return [f"{h.kind}: {h.label}" for h in a.habits]


def timing() -> dict[str, float]:
    chapters, passages = demo_book()
    s = Settings()
    t = time.perf_counter()
    hb.analyse("the-card", chapters, passages, s)
    st.check({"spelling": "british", "quotes": "double-straight", "dash": "double-hyphen",
              "ellipsis": "three-dots", "numbers": "spell-under-100"}, chapters, passages, {})  # fmt: skip
    demo = time.perf_counter() - t
    # 150,000 words: the demo twice over, renumbered (timing only).
    n = len(chapters)
    doubled = chapters + [ms.Chapter(c.number + n, c.title, c.paragraphs) for c in chapters]
    m = ms.Manuscript("double", doubled)
    p2 = ps.split(m, s.min_passage_words, s.max_passage_words)
    t = time.perf_counter()
    c2 = chapters_from_passages(p2)
    hb.analyse("double", c2, p2, s)
    st.check({"spelling": "british", "quotes": "double-straight"}, c2, p2, {})
    long = time.perf_counter() - t
    return {"demo_seconds": demo, "long_seconds": long, "long_words": sum(c.words for c in c2)}


def run_all() -> dict[str, Any]:
    lb = labels()
    files = lb["files"]
    pooled = {k: KindScore() for k in KINDS}
    per_set: dict[str, dict[str, KindScore]] = {}
    dialogue = [0, 0]
    failed = 0
    for name, group in (
        ("invented", [f for f in files if f.startswith("invented/")]),
        ("demo", ["demo-excerpt.md"]),
        ("adversarial", ["adversarial.md"]),
    ):
        b = book(group)
        g = grade_instances(b, group)
        per_set[name] = g["kinds"]
        failed += g["failed"]
        dialogue[0] += g["dialogue"][0]
        dialogue[1] += g["dialogue"][1]
        if name != "adversarial":
            for k in KINDS:
                pooled[k].add(g["kinds"][k])
    # A 20,000-character paragraph with no sentence punctuation.
    t = time.perf_counter()
    para = ("the road ran like a river as if the night would never end and he just walked " * 300)[
        :20_000
    ]
    long_book = Book(
        "eval", [ms.Chapter(1, "Chapter 1", [para])], [ps.Passage(1, "Chapter 1", 1, 1, para)]
    )
    hb.analyse("eval", long_book.chapters, long_book.passages, Settings())
    long_paragraph = time.perf_counter() - t
    return {
        "pooled": pooled,
        "per_set": per_set,
        "dialogue": dialogue,
        "failed": failed,
        "phrases": grade_phrases(),
        "demo_top": grade_demo_top(),
        "style": grade_style(),
        "clean_habits": grade_clean_habits(),
        "long_paragraph_seconds": long_paragraph,
    }
