"""Sentences, words and dialogue in a paragraph, as character spans (spec 0007).

Every pattern here is linear: no nested quantifiers, so a 20,000-character paragraph with no
punctuation is read in milliseconds.
"""

import re
from dataclasses import dataclass

WORD = re.compile(r"[^\W_]+(?:['’][^\W\d_]+)*")
SENTENCE_END = re.compile(r"[.!?…]+[\"”’')\]]*")
# "’em", "’tis", "’90s": an apostrophe, not an opening quotation mark.
ELISION = re.compile(r"(?:em|tis|twas|til|till|cause|n|ere|bout|un|ow)\b|\d{2}s?\b", re.I)
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "mt", "no", "jr", "sr", "prof", "rev", "capt"}


@dataclass
class Sentence:
    start: int
    end: int


def sentences(text: str) -> list[Sentence]:
    """Sentence spans: a sentence ends at . ! ? or … (with closing quotes) followed by a space
    and a capital, a quote or a digit, or at the end of the paragraph. "Mr." doesn't end one."""
    out: list[Sentence] = []
    start = 0
    for m in SENTENCE_END.finditer(text):
        end = m.end()
        rest = text[end:]
        stripped = rest.lstrip()
        if stripped and (len(stripped) == len(rest) or not _starts_sentence(stripped)):
            continue
        before = WORD.findall(text[start : m.start()])
        if text[m.start()] == "." and before and before[-1].lower() in ABBREVIATIONS:
            continue
        if text[start:end].strip():
            out.append(Sentence(_skip_space(text, start), end))
        start = end
    if text[start:].strip():
        out.append(Sentence(_skip_space(text, start), len(text.rstrip())))
    return out


def _starts_sentence(s: str) -> bool:
    c = s[0]
    return c.isupper() or c.isdigit() or c in "\"“‘'(—–-_*"


def _skip_space(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def dialogue_spans(text: str, open_at_start: bool) -> tuple[list[tuple[int, int]], bool]:
    """Spans inside double quotation marks, or curly single ones used as quotation marks, and
    whether a quotation is still open at the end (it runs on into the next paragraph).

    A quotation open at the end of the last paragraph carries on into this one when this one
    re-opens it with a quotation mark, the usual convention. A paragraph that doesn't is
    narration, so a stray unclosed mark never turns the rest of the chapter into dialogue."""
    spans: list[tuple[int, int]] = []
    inside_d = inside_s = False
    begin = 0
    for i, c in enumerate(text):
        if c == "“" or (c == '"' and not inside_d):
            if not inside_d and not inside_s:
                begin = i
            inside_d = True
        elif c == "”" or (c == '"' and inside_d):
            if inside_d and not inside_s:
                spans.append((begin, i + 1))
            inside_d = False
        elif c == "‘" and (i == 0 or not text[i - 1].isalnum()) and not ELISION.match(text, i + 1):
            if not inside_d and not inside_s:
                begin = i
            inside_s = True
        elif c == "’" and inside_s and (i + 1 == len(text) or not text[i + 1].isalpha()):
            if not inside_d:
                spans.append((begin, i + 1))
            inside_s = False
    still_open = inside_d or inside_s
    if still_open:
        spans.append((begin, len(text)))
    return spans, still_open


def inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def previous_word(text: str, pos: int, floor: int = 0) -> str:
    """The word just before pos, lower-cased, within the same sentence (from floor)."""
    words = WORD.findall(text[max(floor, pos - 60) : pos])
    return words[-1].lower().replace("’", "'") if words else ""


def trimmed(sentence: str, start: int, end: int, limit: int = 60) -> tuple[str, int, int]:
    """The sentence, cut to about `limit` words around the match with "…", and the match's
    position in what is returned."""
    words = list(re.finditer(r"\S+", sentence))
    if len(words) <= limit:
        return sentence, start, end
    at = next((i for i, w in enumerate(words) if w.end() > start), 0)
    lo = max(0, at - limit // 2)
    hi = min(len(words), lo + limit)
    lo = max(0, hi - limit)
    a, b = words[lo].start(), words[hi - 1].end()
    prefix = "… " if lo > 0 else ""
    suffix = " …" if hi < len(words) else ""
    s = max(start, a)
    e = min(end, b)
    return prefix + sentence[a:b] + suffix, s - a + len(prefix), e - a + len(prefix)
