import pytest

from margin.verify import normalise, quote_in_passage

PASSAGE = (
    "He picked it up, glanced at the door and at the rows of empty desks, and wrote a neat "
    '"_2_" in front of the _7_; then he strolled innocently forth and came back late. His '
    "trick ought to have been found out--the odds were against him--but it was not found out."
)


@pytest.mark.parametrize(
    "quote",
    [
        "glanced at the door and at the rows of empty desks",
        "GLANCED  AT THE\nDOOR",
        "found out—the odds were against him—but it was not",  # em dashes for "--"
        "found out – the odds were against him",
        "wrote a neat “2” in front of the 7",  # curly quotes, no emphasis marks
        "He picked it up ... came back late",
        "…the odds were against him…",
        "His trick ought to have been found out",
    ],
)
def test_quotes_that_match(quote: str) -> None:
    assert quote_in_passage(quote, PASSAGE)


@pytest.mark.parametrize(
    "quote",
    [
        "glanced at the window and at the rows",  # a changed word
        "the odds were in his favour",
        "came back late ... He picked it up",  # parts out of order
        "found out",  # too short to prove anything
        "",
    ],
)
def test_quotes_that_fail(quote: str) -> None:
    assert not quote_in_passage(quote, PASSAGE)


def test_html_entities_in_quote_match_raw_text() -> None:
    assert quote_in_passage("Smith &amp; Sons of Hanbridge", "It was Smith & Sons of Hanbridge.")


def test_normalise() -> None:
    assert normalise("“It’s  ME”") == '"it\'s me"'
