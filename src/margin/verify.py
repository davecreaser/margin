"""Quote verification (ADR 0001): every quote is checked against its passage's stored text.

Matching ignores whitespace, curly versus straight quotes, dashes, emphasis marks and letter
case, but never the words themselves. A quote may skip text with an ellipsis; each part must
then appear in the passage, in order.
"""

import html
import re
import unicodedata

MIN_QUOTE_WORDS = 3

_TRANSLATE = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "`": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
        "―": "-", "−": "-",
        "_": None, "*": None,
    }
)  # fmt: skip
_ELLIPSIS = re.compile(r"\.\.\.+|…|\[\.\.\.\]")
_DASHES = re.compile(r"\s*-{1,}\s*")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(_TRANSLATE)
    text = _DASHES.sub(" - ", text)
    return " ".join(text.split()).lower()


def _parts(quote: str) -> list[str]:
    parts = [normalise(p) for p in _ELLIPSIS.split(quote)]
    return [p.strip(" \"'") for p in parts if p.strip(" \"'.,;:!?-")]


def quote_in_passage(quote: str, passage_text: str) -> bool:
    """True if the quote's words appear in the passage, in order, as written."""
    parts = _parts(quote)
    if sum(len(p.split()) for p in parts) < MIN_QUOTE_WORDS:
        return False
    haystack = normalise(passage_text)
    position = 0
    for part in parts:
        found = haystack.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return True
