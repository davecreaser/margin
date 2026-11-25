from margin import manuscript as ms
from margin import passages as ps
from margin.config import DEMO_DIR


def test_ranges_cover_every_paragraph_in_order() -> None:
    counts = [50, 120, 90, 300, 40, 600, 30, 20]
    ranges = ps.paragraph_ranges(counts, 150, 400)
    flat = [i for r in ranges for i in r]
    assert flat == list(range(len(counts)))


def test_long_paragraph_is_never_split() -> None:
    assert ps.paragraph_ranges([900], 150, 400) == [range(0, 1)]


def test_short_tail_joins_previous_passage() -> None:
    assert ps.paragraph_ranges([200, 150, 20], 150, 400) == [range(0, 3)]


def test_demo_passages_are_whole_paragraphs_within_one_chapter() -> None:
    m = ms.load(DEMO_DIR)
    passages = ps.split(m, 150, 400)
    by_chapter = {c.number: c for c in m.chapters}
    for p in passages:
        chapter = by_chapter[p.chapter]
        paras = chapter.paragraphs[p.para_start - 1 : p.para_end]
        assert p.text == "\n\n".join(paras)  # exactly as written
        assert p.chapter_title == chapter.title
    words = [len(p.text.split()) for p in passages]
    in_band = sum(1 for w in words if 150 <= w <= 400) / len(words)
    assert in_band > 0.8
    assert len({p.id for p in passages}) == len(passages)
    assert passages[0].id.startswith("1:1-")


def test_location_label() -> None:
    p = ps.Passage(4, "Wrecking Of A Life", 12, 14, "text")
    assert p.location == "Chapter 4, ¶ 12–14"
    assert ps.Passage(4, "t", 3, 3, "x").location == "Chapter 4, ¶ 3"


def test_a_self_naming_title_is_the_location_and_a_descriptive_one_gets_a_number() -> None:
    from margin.passages import Passage

    assert Passage(14, "Interlude II", 3, 5, "x").location == "Interlude II, ¶ 3–5"
    assert Passage(15, "Chapter IV", 2, 2, "x").location == "Chapter IV, ¶ 2"
    assert Passage(1, "Prologue", 1, 1, "x").location == "Prologue, ¶ 1"
    assert Passage(1, "The Dance", 5, 6, "x").location == "Chapter 1, ¶ 5–6"
    assert Passage(2, "Partridge Hill", 1, 1, "x").location == "Chapter 2, ¶ 1"


def test_prompts_name_chapters_as_the_author_does() -> None:
    from margin.passages import Passage
    from margin.steps.answer import build_prompt

    prompt = build_prompt(
        "q", [Passage(14, "Interlude II", 3, 5, "x"), Passage(6, "The Dance", 1, 1, "y")]
    )
    assert 'chapter="Interlude II"' in prompt and 'chapter="6"' in prompt


def test_a_chapter_with_no_text_has_no_passages() -> None:
    from margin.manuscript import Chapter, Manuscript
    from margin.passages import split

    m = Manuscript("m", [Chapter(1, "Chapter X", []), Chapter(2, "Two", ["Some words here."])])
    assert [p.id for p in split(m, 150, 400)] == ["2:1-1"]
