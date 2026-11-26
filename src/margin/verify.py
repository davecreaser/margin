"""Quote verification (ADR 0001): every quote is checked against its passage's stored text.

Matching ignores whitespace, curly versus straight quotes, dashes, emphasis marks and letter
case, but never the words themselves: matches start and end on word boundaries, so "he" never
matches inside "she". A quote may skip text with an ellipsis; each part must then appear in
the passage, in order, and be at least MIN_QUOTE_WORDS words long on its own.
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


def quote_in_passage(quote: str, passage_text: str, min_words: int = MIN_QUOTE_WORDS) -> bool:
    """True if the quote's words appear in the passage, in order, as written."""
    return quote_in_normalised(quote, normalise(passage_text), min_words)


def quote_in_normalised(quote: str, haystack: str, min_words: int = MIN_QUOTE_WORDS) -> bool:
    """quote_in_passage against a passage already normalised, for checking many quotes."""
    parts = _parts(quote)
    if not parts or any(len(p.split()) < min_words for p in parts):
        return False
    position = 0
    for part in parts:
        found = re.compile(r"(?<!\w)" + re.escape(part) + r"(?!\w)").search(haystack, position)
        if found is None:
            return False
        position = found.end()
    return True
