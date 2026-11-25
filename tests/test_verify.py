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


@pytest.mark.parametrize(
    ("quote", "passage"),
    [
        ("he was married to", "She was married to the Countess's cousin."),
        ("happy man about it", "He was an unhappy man about it."),
        ("Denry ... married ... cousin", "Denry, who never married, met a cousin."),
        ("Denry was there ... cousin", "Denry was there, and later met a cousin."),
    ],
)
def test_word_fragments_and_scattered_words_do_not_verify(quote: str, passage: str) -> None:
    assert not quote_in_passage(quote, passage)


def test_each_elided_part_of_three_words_verifies() -> None:
    assert quote_in_passage(
        "Denry was there ... met a cousin", "Denry was there, and later met a cousin."
    )
