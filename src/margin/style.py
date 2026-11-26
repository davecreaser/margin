"""House style: the author's own rules, checked deterministically against the indexed text
(spec 0007). Stored in the data volume as style/<manuscript>.toml, never in the repo.

A mismatch states a difference from the author's rule; it never judges or suggests.
"""

import fnmatch
import hashlib
import logging
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from margin import textspans as ts
from margin import wordlists as wl
from margin.manuscript import Chapter
from margin.passages import Passage, chapter_label
from margin.verify import normalise, quote_in_normalised

log = logging.getLogger(__name__)

CHOICES: dict[str, list[str]] = {
    "spelling": ["british", "british-oxford", "american"],
    "quotes": ["double-curly", "double-straight", "single-curly", "single-straight"],
    "numbers": ["spell-under-100", "spell-under-10", "off"],
    "dash": ["closed-em", "spaced-em", "spaced-en", "double-hyphen"],
    "ellipsis": ["character", "three-dots", "spaced-dots"],
}
TEXT_RULES = ["scene_break", "chapter_heading"]
LIST_RULES = ["heading_exempt", "watch"]
RULES = ["spelling", "quotes", "scene_break", "chapter_heading", "numbers", "dash", "ellipsis"]
DEFAULT_EXEMPT = ["Prologue", "Epilogue", "Interlude *", "Part *"]
PLACEHOLDERS = {
    "{n}": r"\d+",
    "{roman}": r"[IVXLCDM]+",
    "{word}": r"[A-Z][a-z]+(?:[- ][A-Za-z]+)*",
    "{title}": r".+",
}


class StyleError(ValueError):
    pass


# --- Storage ---------------------------------------------------------------------------------


def _path(data_dir: Path, manuscript: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", manuscript.lower()).strip("-")[:40] or "manuscript"
    digest = hashlib.sha256(manuscript.encode()).hexdigest()[:8]
    return data_dir / "style" / f"{slug}-{digest}.toml"


def load(data_dir: Path, manuscript: str) -> dict[str, Any]:
    p = _path(data_dir, manuscript)
    if not p.exists():
        return {}
    return validate(tomllib.loads(p.read_text()))


def save(data_dir: Path, manuscript: str, rules: dict[str, Any]) -> dict[str, Any]:
    rules = validate(rules)
    p = _path(data_dir, manuscript)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dumps(rules))
    return rules


def parse(text: str) -> dict[str, Any]:
    """A style file's text: rejected with its line number if it isn't valid TOML."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise StyleError(f"The style file isn't valid TOML: {e}") from e
    return validate(data)


def _toml_str(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(rules: dict[str, Any]) -> str:
    lines = []
    for k in [*CHOICES, *TEXT_RULES, *LIST_RULES]:
        if k not in rules:
            continue
        v = rules[k]
        if isinstance(v, list):
            lines.append(f"{k} = [{', '.join(_toml_str(x) for x in v)}]")
        else:
            lines.append(f"{k} = {_toml_str(v)}")
    return "\n".join(lines) + "\n"


def _or_list(values: list[str]) -> str:
    return ", ".join(values[:-1]) + " or " + values[-1] if len(values) > 1 else values[0]


def validate(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    known = [*CHOICES, *TEXT_RULES, *LIST_RULES]
    for k, v in data.items():
        if k not in known:
            raise StyleError(f'Unknown rule "{k}": use {_or_list(known)}.')
        if v is None or v == "" or v == []:
            continue
        if k in CHOICES:
            if v not in CHOICES[k]:
                raise StyleError(f'Unknown {k} style "{v}": use {_or_list(CHOICES[k])}.')
            out[k] = v
        elif k in TEXT_RULES:
            if not isinstance(v, str) or not v.strip():
                raise StyleError(f"{k} is a line of text, e.g. {_example(k)}.")
            if k == "chapter_heading" and not re.search(r"\{(n|roman|word|title)\}", v):
                raise StyleError(
                    "chapter_heading uses {n}, {roman}, {word} or {title}, e.g. "
                    '"Chapter {n}: {title}".'
                )
            out[k] = v.strip()
        else:
            if isinstance(v, str):
                v = [v]
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise StyleError(f"{k} is a list of words or phrases.")
            out[k] = list(dict.fromkeys(x.strip() for x in v if x.strip()))
    return out


def _example(k: str) -> str:
    return '"* * *"' if k == "scene_break" else '"Chapter {n}"'


def set_rule(rules: dict[str, Any], rule: str, value: str) -> dict[str, Any]:
    new = dict(rules)
    if rule in LIST_RULES:
        new[rule] = [x.strip() for x in value.split(",")]
    else:
        new[rule] = value
    return validate(new)


# --- Finding mismatches ----------------------------------------------------------------------


@dataclass
class Found:
    rule: str
    chapter: int
    paragraph: int  # 1-based; 0 is the chapter heading
    start: int
    end: int
    what: str  # the label for one mismatch: "gray", "straight quotation mark"
    after: bool = False  # a scene break, after this paragraph


US_TO_GB = {us: (gb, g) for gb, us, g in wl.SPELLING_PAIRS}
GB_TO_US = {gb: (us, g) for gb, us, g in wl.SPELLING_PAIRS}
MONTHS = set(wl.MONTHS)
# A number used as a label: "No. 5", "page 12", "Room 10", but not "examination-room 10 minutes".
NUMBER_LABEL = re.compile(
    r"(?<![\w-])(?:no|number|page|chapter|room|platform|verse|act)\.?\s+$", re.I
)
ELISIONS = re.compile(r"(?:em|tis|twas|til|till|cause|n|ere|bout|un|ow)\b|\d{2}\b", re.I)
DASHES = re.compile(r"\s*(?:—|–|--+)\s*|\s+-\s+")
ELLIPSES = re.compile(r"\.\s\.\s\.(?:\s\.)?|\.{3,}|…")
NUMERAL = re.compile(r"(?<![\w£$€¥.,:/'’-])\d+(?![\w%:/-]|[.,]\d)")


QUOTE_START = re.compile(r"(?:[\"“‘(:—–]|--)\s*$")


def _sentence_starts(text: str) -> set[int]:
    """Where sentences start, and the first word of a quotation or after a colon or dash, where
    a capital doesn't mark a name: He said, "Color is all."."""
    starts = {
        m.start()
        for m in ts.WORD.finditer(text)
        if QUOTE_START.search(text, max(0, m.start() - 4), m.start())
    }
    for s in ts.sentences(text):
        m = ts.WORD.search(text, s.start, s.end)
        if m:
            starts.add(m.start())
    return starts


def _spelling(text: str, setting: str) -> list[tuple[int, int, str]]:
    out = []
    starts = _sentence_starts(text)
    for m in ts.WORD.finditer(text):
        w = m.group(0)
        if w[0].isupper() and m.start() not in starts:
            continue  # a name: "the Mercer Center"
        lw = w.lower()
        if setting == "american":
            wrong = lw in GB_TO_US
        else:
            gb = US_TO_GB.get(lw)
            us = GB_TO_US.get(lw)
            if setting == "british":
                wrong = gb is not None
            else:  # british-oxford: -ize, otherwise British
                wrong = (gb is not None and gb[1] != "ize") or (us is not None and us[1] == "ize")
        if wrong:
            out.append((m.start(), m.end(), lw))
    return out


def _quote_marks(text: str) -> list[tuple[int, str, bool]]:
    """(position, mark, opens a quotation at the top level with a single mark) for every
    quotation mark and apostrophe."""
    out = []
    inside_double = False
    for i, c in enumerate(text):
        if c in '"“”':
            if c == "“":
                inside_double = True
            elif c == "”":
                inside_double = False
            else:
                inside_double = not inside_double
            out.append((i, c, False))
        elif c in "'‘’":
            before = text[i - 1] if i else " "
            opens = (
                not before.isalnum()
                and before not in ".,"
                and i + 1 < len(text)
                and text[i + 1].isalpha()
                and not ELISIONS.match(text, i + 1)
                and not inside_double
            )
            out.append((i, c, opens))
    return out


def _quotes(text: str, setting: str) -> list[tuple[int, int, str]]:
    curly = setting.endswith("curly")
    single = setting.startswith("single")
    out = []
    opens = [m.start() for m in SINGLE_OPEN.finditer(text)] if single else []
    closes = [m.start() for m in SINGLE_CLOSE.finditer(text)] if single else []
    for i, c, opens_single in _quote_marks(text):
        if curly and c in "\"'":
            out.append((i, i + 1, "straight quotation mark"))
        elif not curly and c in "“”‘’":
            out.append((i, i + 1, "curly quotation mark"))
        elif not single and opens_single:
            out.append((i, i + 1, "quotation opened with a single mark"))
        elif single and c in '"“' and _opens_top(text, i, opens, closes):
            out.append((i, i + 1, "quotation opened with a double mark"))
    return out


SINGLE_OPEN = re.compile(r"(?:^|(?<=[\s(—–-]))[‘']")
SINGLE_CLOSE = re.compile(r"[’'](?=$|[\s.,;:!?)—–-])")


def _opens_top(text: str, i: int, opens: list[int], closes: list[int]) -> bool:
    """A double mark opening a quotation that isn't inside a single-quoted one. opens and
    closes are the single marks' positions, found once per paragraph (linear, not per mark)."""
    from bisect import bisect_left

    nested = bisect_left(opens, i) > bisect_left(closes, i)
    starts = i == 0 or not text[i - 1].isalnum()
    return starts and not nested and i + 1 < len(text) and not text[i + 1].isspace()


def _numbers(text: str, setting: str) -> list[tuple[int, int, str]]:
    limit = 100 if setting == "spell-under-100" else 10
    out = []
    for m in NUMERAL.finditer(text):
        n = int(m.group(0))
        if n >= limit or len(m.group(0)) > 3:
            continue
        before = ts.previous_word(text, m.start())
        after = ts.WORD.match(text, _skip(text, m.end()))
        nxt = after.group(0).lower() if after else ""
        labelled = NUMBER_LABEL.search(text, max(0, m.start() - 20), m.start())
        if before in MONTHS or nxt in MONTHS or labelled:
            continue
        if nxt in {"per", "percent", "am", "pm", "a.m", "p.m", "o'clock"}:
            continue
        if re.match(r"\s*(?:st|nd|rd|th)\b", text[m.end() :]):
            continue  # an ordinal date: "the 27th"
        if re.match(r"\s*(?:[ap]\.?m\b|[ap]\.m\.)", text[m.end() :], re.I):
            continue  # a time: "4 A.M."
        if re.match(r"\s*[ds]\.", text[m.end() :]):
            continue  # money: "5s.", "6d."
        out.append((m.start(), m.end(), m.group(0)))
    return out


def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] == " ":
        i += 1
    return i


def _dash_form(text: str, m: re.Match[str]) -> str | None:
    """closed-em, spaced-em, spaced-en, double-hyphen, closed-en, spaced-hyphen, either-em, or
    None for an en dash between numbers (a range)."""
    s = m.group(0)
    core = s.strip()
    left = s[0].isspace()
    right = s[-1].isspace()
    if core.startswith("--"):
        return "double-hyphen"
    if core == "-":
        return "spaced-hyphen"
    if core == "–":
        a, b = text[m.start() - 1 : m.start()], text[m.end() : m.end() + 1]
        if a.isdigit() and b.isdigit():
            return None
        return "spaced-en" if left and right else "closed-en"
    if left and right:
        return "spaced-em"
    if not left and not right:
        return "closed-em"
    return "either-em"  # at a quotation mark or the end of a paragraph


def _dashes(text: str, setting: str) -> list[tuple[int, int, str]]:
    out = []
    for m in DASHES.finditer(text):
        form = _dash_form(text, m)
        if form is None or form == setting:
            continue
        if form == "either-em" and setting in ("closed-em", "spaced-em"):
            continue
        at_edge = m.start() == 0 or m.end() == len(text)
        if at_edge and form in ("either-em", "closed-em", "spaced-em") and setting.endswith("em"):
            continue
        label = {
            "closed-em": "closed em dash",
            "spaced-em": "spaced em dash",
            "either-em": "em dash",
            "spaced-en": "spaced en dash",
            "closed-en": "en dash",
            "double-hyphen": "double hyphen",
            "spaced-hyphen": "spaced hyphen",
        }[form]
        a = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
        b = m.end() - (len(m.group(0)) - len(m.group(0).rstrip()))
        out.append((a, b, label))
    return out


def _ellipsis_form(s: str) -> str:
    if s == "…":
        return "character"
    return "spaced-dots" if " " in s else "three-dots"


def _ellipses(text: str, setting: str) -> list[tuple[int, int, str]]:
    labels = {
        "character": "ellipsis character",
        "three-dots": "three dots",
        "spaced-dots": "spaced dots",
    }
    return [
        (m.start(), m.end(), labels[_ellipsis_form(m.group(0))])
        for m in ELLIPSES.finditer(text)
        if _ellipsis_form(m.group(0)) != setting
    ]


def _heading_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{(?:n|roman|word|title)\})", template)
    rx = "".join(PLACEHOLDERS.get(p, re.escape(p)) for p in parts)
    return re.compile(rf"^{rx}$")


def _paragraph_rules(text: str, rules: dict[str, Any]) -> list[tuple[str, int, int, str]]:
    out: list[tuple[str, int, int, str]] = []
    checks = {
        "spelling": _spelling,
        "quotes": _quotes,
        "numbers": _numbers,
        "dash": _dashes,
        "ellipsis": _ellipses,
    }
    for rule, fn in checks.items():
        setting = rules.get(rule)
        if not setting or setting == "off":
            continue
        out += [(rule, a, b, what) for a, b, what in fn(text, setting)]
    return out


@dataclass
class Check:
    rules: dict[str, Any]
    found: list[Found]
    chapters: list[Chapter]
    passages: dict[tuple[int, int], Passage]
    breaks_recorded: bool
    watch: dict[str, list[Found]]
    failed: int = 0


def check(
    rules: dict[str, Any],
    chapters: list[Chapter],
    passages: list[Passage],
    scene_breaks: dict[int, list[dict[str, Any]]] | None,
) -> Check:
    """Every mismatch with the rules that are set. scene_breaks is None for an index made
    before they were recorded."""
    pindex = {}
    for p in passages:
        for para in range(p.para_start, p.para_end + 1):
            pindex[(p.chapter, para)] = p
    found: list[Found] = []
    watch: dict[str, list[Found]] = {w: [] for w in rules.get("watch", [])}
    watch_rx = {
        w: re.compile(r"(?<![\w’'])" + r"\s+".join(map(re.escape, w.split())) + r"(?![\w’'])", re.I)
        for w in watch
    }
    for c in chapters:
        for pi, text in enumerate(c.paragraphs):
            for rule, a, b, what in _paragraph_rules(text, rules):
                found.append(Found(rule, c.number, pi + 1, a, b, what))
            for w, rx in watch_rx.items():
                for m in rx.finditer(text):
                    watch[w].append(Found("watch", c.number, pi + 1, m.start(), m.end(), w))
        if rules.get("chapter_heading"):
            exempt = rules.get("heading_exempt", DEFAULT_EXEMPT)
            title = c.title.strip()
            exempted = any(fnmatch.fnmatch(title, pat) for pat in exempt)
            if not exempted and not _heading_regex(rules["chapter_heading"]).match(title):
                found.append(Found("chapter_heading", c.number, 0, 0, len(title), title))
        if rules.get("scene_break") and scene_breaks is not None:
            for br in scene_breaks.get(c.number, []):
                if br["text"].strip() != rules["scene_break"]:
                    found.append(
                        Found("scene_break", c.number, br["after"], 0, 0, br["text"].strip(), True)
                    )
    texts = {(c.number, pi + 1): t for c in chapters for pi, t in enumerate(c.paragraphs)}
    kept, failed = [], 0
    for f in found:
        if f.paragraph == 0 or f.after:
            kept.append(f)
            continue
        if _verified(f, texts, pindex):
            kept.append(f)
        else:
            failed += 1
    for w in watch:
        ok = [f for f in watch[w] if _verified(f, texts, pindex)]
        failed += len(watch[w]) - len(ok)
        watch[w] = ok
    if failed:
        log.warning("style: %d mismatches failed verification and are not shown", failed)
    return Check(rules, kept, chapters, pindex, scene_breaks is not None, watch, failed)


def _context(text: str, a: int, b: int) -> str:
    """A few words around a span: what the verifier checks against the stored passage."""
    base = max(0, a - 80)
    lo = [base + m.start() for m in re.finditer(r"\S+", text[base:a])][-3:]
    if lo and base and lo[0] == base:
        lo = lo[1:]  # a word cut by the window
    hi = [m.end() for m in re.finditer(r"\S+", text[b : b + 80])][:3]
    return text[lo[0] if lo else a : b + hi[-1] if hi else b]


_normalised: dict[str, str] = {}


def _verified(
    f: Found, texts: dict[tuple[int, int], str], pindex: dict[tuple[int, int], Passage]
) -> bool:
    p = pindex.get((f.chapter, f.paragraph))
    text = texts.get((f.chapter, f.paragraph))
    if p is None or text is None or text[f.start : f.end] == "":
        return False
    if len(_normalised) > 5000:
        _normalised.clear()
    key = f"{p.id}\0{p.text}"
    if key not in _normalised:
        _normalised[key] = normalise(p.text)
    return quote_in_normalised(_context(text, f.start, f.end), _normalised[key], 1)


# --- Report ----------------------------------------------------------------------------------


def _plural(n: int, what: str) -> str:
    if n == 1:
        return f"1 {what}"
    if what.endswith(("ch", "sh", "s")):
        return f"{n} {what}es"
    if what.endswith(" dots"):
        return f"{n} × {what}"
    return f"{n} {what}s"


def _row(
    ck: Check, items: list[Found], texts: dict[tuple[int, int], str], labels: dict[int, str]
) -> dict[str, Any]:
    f = items[0]
    p = ck.passages.get((f.chapter, max(f.paragraph, 1)))
    row: dict[str, Any] = {
        "rule": f.rule,
        "chapter": f.chapter,
        "label": labels.get(f.chapter, f"Chapter {f.chapter}"),
        "paragraph": f.paragraph,
        "after": f.after,
        "passage_id": p.id if p else None,
        "count": len(items),
    }
    if f.paragraph == 0 or f.after:
        row.update(sentence=f.what, match=[0, len(f.what)], text=f.what, what=f.what)
        return row
    text = texts[(f.chapter, f.paragraph)]
    sents = ts.sentences(text)
    sent = next((s for s in sents if s.start <= f.start < s.end), ts.Sentence(0, len(text)))
    shown, a, b = ts.trimmed(text[sent.start : sent.end], f.start - sent.start, f.end - sent.start)
    whats = Counter(i.what for i in items)
    if f.rule == "spelling" or f.rule == "numbers":
        what = ", ".join(w for w in whats)
    else:
        what = ", ".join(_plural(n, w) for w, n in whats.items())
    row.update(
        sentence=shown,
        match=[a, b],
        text=text[f.start : f.end],
        what=what,
        spans=[[i.start, i.end] for i in items],
    )
    return row


def report(ck: Check) -> dict[str, Any]:
    texts = {(c.number, pi + 1): t for c in ck.chapters for pi, t in enumerate(c.paragraphs)}
    return _report(ck, texts)


def _report(ck: Check, texts: dict[tuple[int, int], str]) -> dict[str, Any]:
    labels = {c.number: chapter_label(c.number, c.title) for c in ck.chapters}
    rules_out = []
    set_rules = [r for r in RULES if ck.rules.get(r) and ck.rules.get(r) != "off"]
    for rule in set_rules:
        items = [f for f in ck.found if f.rule == rule]
        groups: dict[tuple[int, int, bool], list[Found]] = {}
        for f in items:
            groups.setdefault((f.chapter, f.paragraph, f.after), []).append(f)
        rows = [_row(ck, g, texts, labels) for g in groups.values()]
        per = Counter(str(f.chapter) for f in items)
        entry: dict[str, Any] = {
            "rule": rule,
            "value": ck.rules[rule],
            "total": len(items),
            "chapters": dict(per),
            "rows": rows,
        }
        if rule == "scene_break" and not ck.breaks_recorded:
            entry["unchecked"] = "Re-ingest to check scene breaks."
        rules_out.append(entry)
    watch = []
    for w, items in ck.watch.items():
        groups2: dict[tuple[int, int], list[Found]] = {}
        for f in items:
            groups2.setdefault((f.chapter, f.paragraph), []).append(f)
        watch.append(
            {
                "word": w,
                "total": len(items),
                "chapters": dict(Counter(str(f.chapter) for f in items)),
                "rows": [_row(ck, g, texts, labels) for g in groups2.values()],
            }
        )
    unchecked = 1 if "scene_break" in set_rules and not ck.breaks_recorded else 0
    checked = len(set_rules) - unchecked + (1 if ck.watch else 0)
    return {
        "rules": ck.rules,
        "breaks_recorded": ck.breaks_recorded,
        "checked": checked,
        "mismatches": sum(r["total"] for r in rules_out),
        "by_rule": rules_out,
        "watch": watch,
    }


# --- Detect ----------------------------------------------------------------------------------


def detect(
    chapters: list[Chapter], scene_breaks: dict[int, list[dict[str, Any]]] | None
) -> dict[str, Any]:
    """For each rule, the form the manuscript mostly uses and its share. Saves nothing."""
    tallies: dict[str, Counter[str]] = {
        r: Counter() for r in ["spelling", "quotes", "dash", "ellipsis", "numbers", "scene_break"]
    }
    for c in chapters:
        for text in c.paragraphs:
            starts = _sentence_starts(text)
            for m in ts.WORD.finditer(text):
                w = m.group(0)
                if w[0].isupper() and m.start() not in starts:
                    continue
                lw = w.lower()
                if lw in GB_TO_US:
                    tallies["spelling"][
                        "ize-british" if GB_TO_US[lw][1] == "ize" else "british"
                    ] += 1
                elif lw in US_TO_GB:
                    tallies["spelling"][
                        "ize-american" if US_TO_GB[lw][1] == "ize" else "american"
                    ] += 1
            curly = sum(text.count(ch) for ch in "“”")
            straight = text.count('"')
            marks = _quote_marks(text)
            tallies["quotes"]["curly"] += curly
            tallies["quotes"]["straight"] += straight
            tallies["quotes"]["single-open"] += sum(1 for _, _, o in marks if o)
            tallies["quotes"]["single-curly"] += sum(1 for _, c, _ in marks if c in "‘’")
            tallies["quotes"]["single-straight"] += sum(1 for _, c, _ in marks if c == "'")
            tallies["quotes"]["double-open"] += (curly + straight) // 2
            for m in DASHES.finditer(text):
                form = _dash_form(text, m)
                if form and form not in ("spaced-hyphen", "closed-en", "either-em"):
                    tallies["dash"][form] += 1
            for m in ELLIPSES.finditer(text):
                tallies["ellipsis"][_ellipsis_form(m.group(0))] += 1
            for m in NUMERAL.finditer(text):
                if int(m.group(0)) < 100 and len(m.group(0)) <= 2:
                    tallies["numbers"]["numerals"] += 1
            tallies["numbers"]["words"] += len(re.findall(
                r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|"
                r"forty|fifty|sixty|seventy|eighty|ninety)\b", text, re.I))  # fmt: skip
        for br in (scene_breaks or {}).get(c.number, []):
            tallies["scene_break"][br["text"].strip()] += 1
    out: dict[str, Any] = {}

    def share(n: int, total: int) -> int:
        return round(100 * n / total) if total else 0

    sp = tallies["spelling"]
    gb, us = sp["british"], sp["american"]
    ize_gb, ize_us = sp["ize-british"], sp["ize-american"]
    if gb + us + ize_gb + ize_us:
        if gb >= us:
            value = "british-oxford" if ize_us > ize_gb else "british"
            n = gb + (ize_us if value == "british-oxford" else ize_gb)
        else:
            value, n = "american", us + ize_us
        out["spelling"] = {
            "value": value,
            "share": share(n, gb + us + ize_gb + ize_us),
            "of": "listed words",
        }
    q = tallies["quotes"]
    if q["curly"] + q["straight"] + q["single-open"]:
        kind = "single" if q["single-open"] > q["double-open"] else "double"
        n_curly, n_straight = (
            (q["curly"], q["straight"])
            if kind == "double"
            else (q["single-curly"], q["single-straight"])
        )
        form = "curly" if n_curly > n_straight else "straight"
        out["quotes"] = {
            "value": f"{kind}-{form}",
            "share": share(max(n_curly, n_straight), n_curly + n_straight),
            "of": "quotation marks",
        }
    for rule, of in (("dash", "dashes"), ("ellipsis", "ellipses"), ("scene_break", "scene breaks")):
        t = tallies[rule]
        if t:
            value, n = t.most_common(1)[0]
            out[rule] = {"value": value, "share": share(n, sum(t.values())), "of": of}
    nums = tallies["numbers"]
    if nums["words"] + nums["numerals"]:
        if nums["words"] >= nums["numerals"]:
            out["numbers"] = {
                "value": "spell-under-100",
                "share": share(nums["words"], nums["words"] + nums["numerals"]),
                "of": "numbers under 100",
            }
        else:
            out["numbers"] = {
                "value": "off",
                "share": share(nums["numerals"], nums["words"] + nums["numerals"]),
                "of": "numbers under 100",
            }
    if scene_breaks is None:
        out.pop("scene_break", None)
    return out
