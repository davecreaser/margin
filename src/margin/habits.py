"""Habits report: the constructions an author repeats, counted per chapter, with every instance
in its sentence (spec 0007). Deterministic: no model, no key, no cost.

Every instance is an exact span of a stored paragraph and is checked against its passage with
the citation verifier before it is shown (ADR 0001).
"""

import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from margin import textspans as ts
from margin import wordlists as wl
from margin.manuscript import Chapter
from margin.passages import Passage, chapter_label
from margin.verify import normalise, quote_in_normalised

log = logging.getLogger(__name__)

KINDS = [
    ("similes", "Similes"),
    ("as_if", "As if / as though"),
    ("gestures", "Stock gestures"),
    ("filter", "Filter verbs"),
    ("crutch", "Crutch words"),
    ("openers", "Sentence openers"),
    ("phrases", "Repeated phrases"),
]
OPENER_RUN = 3
OPENER_COMMA_WORDS = 15


@dataclass
class Instance:
    habit: str
    chapter: int
    paragraph: int  # 1-based
    start: int  # in the paragraph
    end: int
    sentence_start: int
    sentence_end: int
    dialogue: bool


@dataclass
class Habit:
    id: str
    kind: str
    label: str
    instances: list[Instance] = field(default_factory=list)
    variants: list[tuple[str, int]] = field(default_factory=list)
    ratio: float = 0.0


def _w(words: list[str]) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


# --- Patterns ---------------------------------------------------------------------------------

LIKE_A = re.compile(r"\blike an?\b", re.I)
AS_AS = re.compile(r"\bas ([A-Za-z]+) as\b", re.I)
AS_IF = re.compile(r"\bas (if|though)\b", re.I)
GESTURE_VERB = {
    habit: re.compile(rf"\b(?:{_w(forms)})\b", re.I) for habit, forms in wl.GESTURE_VERBS.items()
}
GESTURE_PHRASE = {habit: re.compile(p, re.I) for habit, p in wl.GESTURE_PHRASES.items()}
FILTER = {
    habit: re.compile(rf"\b(?:{_w(forms)})\b", re.I) for habit, forms in wl.FILTER_VERBS.items()
}
CRUTCH = {w: re.compile(rf"\b{w}\b", re.I) for w in wl.CRUTCH_WORDS}
BASE_FORMS = {f for forms in wl.GESTURE_VERBS.values() for f in forms[:2]}
# Filter verbs' base and -s forms are also nouns ("notice", "watch", "wonders"): they count only
# where a verb can stand.
FILTER_BASE = {
    f
    for forms in wl.FILTER_VERBS.values()
    for f in forms
    if not f.endswith(("ed", "ing", "saw", "felt", "heard", "seen"))
}


def _hyphened(text: str, m: re.Match[str]) -> bool:
    """Part of a hyphenated word: "watch-cases"."""
    return (m.start() > 0 and text[m.start() - 1] == "-") or text[m.end() : m.end() + 1] == "-"


def _verb_context(p: str) -> bool:
    return (
        p in wl.SUBJECTS
        or p in wl.AUXILIARIES
        or p in wl.VERB_LEADS
        or p.endswith(("'ll", "’ll", "'d", "’d"))
    )


def _sentence_of(sents: list[ts.Sentence], pos: int) -> ts.Sentence:
    for s in sents:
        if s.start <= pos < s.end:
            return s
    return sents[-1] if sents else ts.Sentence(0, 0)


def _paragraph_habits(text: str, sents: list[ts.Sentence]) -> list[tuple[str, str, int, int]]:
    """(kind, habit, start, end) for every fixed-list habit in one paragraph."""
    out: list[tuple[str, str, int, int]] = []

    def prev(pos: int) -> str:
        return ts.previous_word(text, pos, _sentence_of(sents, pos).start)

    for m in LIKE_A.finditer(text):
        p = prev(m.start())
        if p not in wl.LIKE_A_NOT and not p.endswith(("'d", "’d")):
            out.append(("similes", "like a …", m.start(), m.end()))
    for m in AS_AS.finditer(text):
        if m.group(1).lower() not in wl.AS_AS_NOT:
            out.append(("similes", "as … as …", m.start(), m.end()))
    for m in AS_IF.finditer(text):
        out.append(("as_if", f"as {m.group(1).lower()}", m.start(), m.end()))
    for habit, rx in GESTURE_VERB.items():
        for m in rx.finditer(text):
            word, p = m.group(0).lower(), prev(m.start())
            if p in wl.DETERMINERS or p.endswith(("'s", "’s")) or _hyphened(text, m):
                continue
            if word in BASE_FORMS and not (p in wl.SUBJECTS or p in wl.AUXILIARIES):
                continue
            out.append(("gestures", habit, m.start(), m.end()))
    for habit, rx in GESTURE_PHRASE.items():
        for m in rx.finditer(text):
            out.append(("gestures", habit, m.start(), m.end()))
    for habit, rx in FILTER.items():
        for m in rx.finditer(text):
            p = prev(m.start())
            if p in wl.DETERMINERS or p.endswith(("'s", "’s")) or _hyphened(text, m):
                continue
            if m.group(0).lower() in FILTER_BASE and not _verb_context(p):
                continue  # "gave notice", "kept watch"
            if habit == "seemed" and not p:  # "seemed" needs a subject
                continue
            out.append(("filter", habit, m.start(), m.end()))
    for word, rx in CRUTCH.items():
        for m in rx.finditer(text):
            if prev(m.start()) in wl.CRUTCH_AS_ADJECTIVE.get(word, ()):
                continue
            out.append(("crutch", word, m.start(), m.end()))
    out += _openers(text, sents)
    return out


def _first_word(text: str, s: ts.Sentence) -> re.Match[str] | None:
    return ts.WORD.search(text, s.start, s.end)


def _openers(text: str, sents: list[ts.Sentence]) -> list[tuple[str, str, int, int]]:
    out: list[tuple[str, str, int, int]] = []
    firsts = [_first_word(text, s) for s in sents]
    i = 0
    while i < len(sents):
        f = firsts[i]
        j = i + 1
        while (
            f and j < len(sents) and (g := firsts[j]) and g.group(0).lower() == f.group(0).lower()
        ):
            j += 1
        if f and j - i >= OPENER_RUN:
            out.append(("openers", "runs of the same first word", f.start(), f.end()))
        i = j if f and j - i >= OPENER_RUN else i + 1
    for s, f in zip(sents, firsts, strict=True):
        if not f or f.start() - s.start > 2:
            continue
        w = f.group(0)
        if not (w[0].isupper() and w.lower().endswith("ing") and len(w) > 4):
            continue
        if w.lower() in wl.ING_NOT_PARTICIPLE:
            continue
        head = text[f.end() : s.end]
        if "," in " ".join(head.split()[:OPENER_COMMA_WORDS]):
            out.append(("openers", '"-ing" openers', f.start(), f.end()))
    return out


# --- Repeated phrases -------------------------------------------------------------------------


def _tokens(text: str, s: ts.Sentence) -> list[re.Match[str]]:
    return list(ts.WORD.finditer(text, s.start, s.end))


def _norm(word: str) -> str:
    return word.lower().replace("’", "'")


def _fold(word: str) -> str:
    w = _norm(word)
    return wl.PRONOUN_FOLD.get(w, w)


def _phrases(
    chapters: list[Chapter], sents: dict[tuple[int, int], list[ts.Sentence]], s: Any
) -> list[Habit]:
    counts: Counter[tuple[str, ...]] = Counter()
    seen_in: dict[tuple[str, ...], list[int]] = {}  # [last chapter, number of chapters]
    freq: Counter[str] = Counter()
    mid_total: Counter[str] = Counter()
    mid_caps: Counter[str] = Counter()
    total = 0
    for c in chapters:
        for pi, text in enumerate(c.paragraphs):
            for sent in sents[(c.number, pi)]:
                toks = _tokens(text, sent)
                folded = [_fold(t.group(0)) for t in toks]
                for k, t in enumerate(toks):
                    freq[folded[k]] += 1
                    if k:
                        mid_total[_norm(t.group(0))] += 1
                        mid_caps[_norm(t.group(0))] += t.group(0)[0].isupper()
                total += len(toks)
                for n in range(3, 7):
                    for k in range(len(folded) - n + 1):
                        key = tuple(folded[k : k + n])
                        counts[key] += 1
                        last = seen_in.get(key)
                        if last is None:
                            seen_in[key] = [c.number, 1]
                        elif last[0] != c.number:
                            last[0] = c.number
                            last[1] += 1
    if not total:
        return []
    names = {w for w, n in mid_total.items() if n and mid_caps[w] / n >= 0.9}

    def content(key: tuple[str, ...]) -> bool:
        return any(
            not w.startswith("<") and w not in wl.FUNCTION_WORDS and w not in names and len(w) > 2
            for w in key
        )

    found: dict[tuple[str, ...], float] = {}
    for key, n in counts.items():
        if n < s.phrase_min_count or seen_in[key][1] < s.phrase_min_chapters:
            continue
        if not content(key):
            continue
        log_expected = math.log(total) + sum(math.log(freq[w] / total) for w in key)
        ratio = math.log(n) - log_expected
        if ratio >= math.log(s.phrase_min_ratio):
            found[key] = ratio
    # Where each phrase occurs, how it is written, and which of its words are capitalised
    # mid-sentence there (a name: "the Five Towns" is a place, not a habit).
    habits: dict[tuple[str, ...], Habit] = {
        key: Habit(id="phrase:" + " ".join(key), kind="phrases", label="", ratio=r)
        for key, r in found.items()
    }
    forms: dict[tuple[str, ...], Counter[str]] = {key: Counter() for key in habits}
    caps: dict[tuple[str, ...], list[list[int]]] = {k: [[0, 0] for _ in k] for k in habits}
    lengths = sorted({len(k) for k in habits}, reverse=True)
    for c in chapters:
        for pi, text in enumerate(c.paragraphs):
            for sent in sents[(c.number, pi)]:
                toks = _tokens(text, sent)
                folded = [_fold(t.group(0)) for t in toks]
                for n in lengths:
                    for k in range(len(folded) - n + 1):
                        key = tuple(folded[k : k + n])
                        if key not in habits:
                            continue
                        span = toks[k : k + n]
                        forms[key][" ".join(_norm(t.group(0)) for t in span)] += 1
                        for j, t in enumerate(span):
                            if k + j:
                                caps[key][j][0] += 1
                                caps[key][j][1] += t.group(0)[0].isupper()
                        habits[key].instances.append(
                            Instance(
                                habits[key].id, c.number, pi + 1, span[0].start(),
                                span[-1].end(), sent.start, sent.end, False,
                            )
                        )  # fmt: skip

    def common(key: tuple[str, ...], j: int) -> bool:
        w = key[j]
        if w.startswith("<") or w in wl.FUNCTION_WORDS or w in names or len(w) <= 2:
            return True
        seen, capped = caps[key][j]
        return bool(seen) and capped / seen >= 0.9

    kept = {
        k
        for k in habits
        if not all(common(k, j) for j in range(len(k))) and k[-1] not in wl.DANGLING
    }
    # Fold a phrase into a longer kept one that holds nearly all its uses.
    for key in sorted(kept, key=len, reverse=True):
        for n in range(3, len(key)):
            for k in range(len(key) - n + 1):
                sub = key[k : k + n]
                if sub in kept and counts[key] >= 0.8 * counts[sub]:
                    kept.discard(sub)
    # Then a phrase that is a kept phrase plus a function word at either end adds nothing.
    for key in list(kept):
        for core, edge in ((key[1:], key[0]), (key[:-1], key[-1])):
            if core in kept and (edge in wl.FUNCTION_WORDS or edge.startswith("<")):
                kept.discard(key)
                break
    out = []
    for key in kept:
        h = habits[key]
        ranked = forms[key].most_common()
        h.label = ranked[0][0]
        h.variants = ranked[1:]
        out.append(h)
    out.sort(key=lambda h: (-len(h.instances), -h.ratio, h.label))
    return out


# --- The report -------------------------------------------------------------------------------


@dataclass
class Analysis:
    manuscript: str
    chapters: list[Chapter]
    habits: list[Habit]
    passages: dict[tuple[int, int], Passage]
    failed: int = 0

    def habit(self, habit_id: str) -> Habit | None:
        return next((h for h in self.habits if h.id == habit_id), None)


def _passage_index(passages: list[Passage]) -> dict[tuple[int, int], Passage]:
    out = {}
    for p in passages:
        for para in range(p.para_start, p.para_end + 1):
            out[(p.chapter, para)] = p
    return out


def analyse(manuscript: str, chapters: list[Chapter], passages: list[Passage], s: Any) -> Analysis:
    pindex = _passage_index(passages)
    sents: dict[tuple[int, int], list[ts.Sentence]] = {}
    found: dict[tuple[str, str], Habit] = {}
    failed = 0
    for c in chapters:
        open_quote = False
        for pi, text in enumerate(c.paragraphs):
            ss = ts.sentences(text)
            sents[(c.number, pi)] = ss
            spans, open_quote = ts.dialogue_spans(text, open_quote)
            for kind, habit, a, b in _paragraph_habits(text, ss):
                sent = _sentence_of(ss, a)
                h = found.setdefault(
                    (kind, habit), Habit(id=f"{kind}:{habit}", kind=kind, label=habit)
                )
                h.instances.append(
                    Instance(
                        h.id, c.number, pi + 1, a, b, sent.start, sent.end, ts.inside(a, spans)
                    )
                )
    habits = list(found.values()) + _phrases(chapters, sents, s)
    # Dialogue flags for phrases, which are found sentence by sentence.
    by_para: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for c in chapters:
        open_quote = False
        for pi, text in enumerate(c.paragraphs):
            by_para[(c.number, pi + 1)], open_quote = ts.dialogue_spans(text, open_quote)
    texts = {(c.number, pi + 1): t for c in chapters for pi, t in enumerate(c.paragraphs)}
    normalised: dict[str, str] = {}

    def hay(p: Passage) -> str:
        if p.id not in normalised:
            normalised[p.id] = normalise(p.text)
        return normalised[p.id]

    for h in habits:
        if h.kind == "phrases":
            for i in h.instances:
                i.dialogue = ts.inside(i.start, by_para[(i.chapter, i.paragraph)])
        kept = []
        for i in h.instances:
            p = pindex.get((i.chapter, i.paragraph))
            span = texts[(i.chapter, i.paragraph)][i.start : i.end]
            if p is None or not quote_in_normalised(span, hay(p), 1):
                failed += 1
                continue
            kept.append(i)
        h.instances = kept
    habits = [h for h in habits if len(h.instances) >= s.habit_min_count]
    if failed:
        log.warning("habits: %d instances failed verification and are not shown", failed)
    return Analysis(manuscript, chapters, habits, pindex, failed)


def _counted(h: Habit, narration: bool) -> list[Instance]:
    return [i for i in h.instances if not (narration and i.dialogue)]


def report(
    a: Analysis, *, narration: bool = False, all_phrases: bool = False, phrase_top: int = 50
) -> dict[str, Any]:
    """Counts only: kinds, habits, totals, rates and per-chapter counts (AC-4, AC-15)."""
    words = sum(c.words for c in a.chapters)
    chapters = [
        {"number": c.number, "label": chapter_label(c.number, c.title), "words": c.words}
        for c in a.chapters
    ]
    kinds = []
    for kind, label in KINDS:
        rows: list[dict[str, Any]] = []
        for h in a.habits:
            if h.kind != kind:
                continue
            counted = _counted(h, narration)
            if not counted:
                continue
            per = Counter(i.chapter for i in counted)
            rows.append(
                {
                    "id": h.id,
                    "label": h.label,
                    "total": len(counted),
                    "narration": sum(1 for i in h.instances if not i.dialogue),
                    "rate": round(len(counted) / words * 1000, 2) if words else 0,
                    "chapters": {str(n): k for n, k in sorted(per.items())},
                    "in_chapters": len(per),
                    "variants": [{"form": f, "count": n} for f, n in h.variants],
                }
            )
        if kind != "phrases":
            rows.sort(key=lambda r: (-r["total"], r["label"]))
        more = 0
        if kind == "phrases" and not all_phrases and len(rows) > phrase_top:
            more, rows = len(rows) - phrase_top, rows[:phrase_top]
        kinds.append({"kind": kind, "label": label, "habits": rows, "more": more})
    return {
        "manuscript": a.manuscript,
        "words": words,
        "chapters": chapters,
        "narration": narration,
        "kinds": kinds,
        "found": any(k["habits"] for k in kinds),
    }


def instance_rows(
    a: Analysis, items: list[Instance], texts: dict[tuple[int, int], str]
) -> list[dict[str, Any]]:
    rows = []
    labels = {c.number: chapter_label(c.number, c.title) for c in a.chapters}
    for i in items:
        text = texts[(i.chapter, i.paragraph)]
        sentence = text[i.sentence_start : i.sentence_end]
        shown, s, e = ts.trimmed(sentence, i.start - i.sentence_start, i.end - i.sentence_start)
        p = a.passages.get((i.chapter, i.paragraph))
        rows.append(
            {
                "chapter": i.chapter,
                "label": labels.get(i.chapter, f"Chapter {i.chapter}"),
                "paragraph": i.paragraph,
                "passage_id": p.id if p else None,
                "sentence": shown,
                "match": [s, e],
                "text": text[i.start : i.end],
                "dialogue": i.dialogue,
            }
        )
    return rows


def instances(
    a: Analysis,
    habit_id: str,
    *,
    chapter: int | None = None,
    narration: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any] | None:
    h = a.habit(habit_id)
    if h is None:
        return None
    items = [i for i in _counted(h, narration) if chapter is None or i.chapter == chapter]
    texts = {(c.number, pi + 1): t for c in a.chapters for pi, t in enumerate(c.paragraphs)}
    return {
        "habit": h.id,
        "label": h.label,
        "total": len(items),
        "offset": offset,
        "instances": instance_rows(a, items[offset : offset + limit], texts),
    }


def closest(a: Analysis, name: str, n: int = 5) -> list[str]:
    import difflib

    labels = [h.label for h in a.habits]
    return difflib.get_close_matches(name, labels, n=n, cutoff=0.3)


def find_habit(a: Analysis, name: str) -> Habit | None:
    """A habit by id or by its label ("nodded", "like a", "like a …")."""
    for h in a.habits:
        if h.id == name:
            return h
    want = name.strip().strip('"“”').lower().rstrip(" …").strip()
    for h in a.habits:
        if h.id.lower() == want or h.label.lower().rstrip(" …").strip() == want:
            return h
    return None


# --- Cache ------------------------------------------------------------------------------------

_cache: dict[str, Analysis] = {}


def cache_key(passages: list[Passage], s: Any) -> str:
    h = hashlib.sha256()
    for p in passages:
        h.update(f"{p.chapter}\0{p.chapter_title}\0{p.para_start}\0{p.text}\0".encode())
    for k in ("phrase_min_count", "phrase_min_chapters", "phrase_min_ratio", "habit_min_count"):
        h.update(f"{k}={getattr(s, k)}\0".encode())
    return h.hexdigest()


def cached(manuscript: str, chapters: list[Chapter], passages: list[Passage], s: Any) -> Analysis:
    key = cache_key(passages, s)
    if key not in _cache:
        _cache.clear()  # one manuscript at a time: the cache holds the latest ingest only
        _cache[key] = analyse(manuscript, chapters, passages, s)
    return _cache[key]
