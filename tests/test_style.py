"""House style (spec 0007): settings, each rule with its must-not-report cases, the API."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from margin import api
from margin import manuscript as ms
from margin import passages as ps
from margin import style as st
from margin.config import Settings
from margin.index import IndexStats
from margin.manuscript import Chapter
from margin.timeline import chapters_from_passages


def run(rules: dict[str, Any], *chapters: list[str], titles: list[str] | None = None,
        breaks: dict[int, list[dict[str, Any]]] | None = None) -> dict[str, Any]:  # fmt: skip
    s = Settings()
    cs = [
        Chapter(
            number=i + 1, title=(titles or [])[i] if titles else f"Chapter {i + 1}", paragraphs=p
        )
        for i, p in enumerate(chapters)
    ]
    passages = ps.split(ms.Manuscript("t", cs), s.min_passage_words, s.max_passage_words)
    rebuilt = chapters_from_passages(passages)
    return st.report(
        st.check(st.validate(rules), rebuilt, passages, breaks if breaks is not None else {})
    )


def hits(rules: dict[str, Any], text: str) -> list[str]:
    r = run(rules, [text])
    return [row["text"] for rule in r["by_rule"] for row in rule["rows"] for _ in range(1)]


def rule_total(rules: dict[str, Any], text: str) -> int:
    return run(rules, [text])["mismatches"]


# --- AC-7: settings ---------------------------------------------------------------------------


def test_unknown_rule_or_value_is_rejected_with_the_allowed_values() -> None:
    with pytest.raises(
        st.StyleError, match="double-curly, double-straight, single-curly or single-straight"
    ):
        st.validate({"quotes": "curly"})
    with pytest.raises(st.StyleError, match='Unknown rule "colour"'):
        st.validate({"colour": "red"})


def test_invalid_toml_is_rejected_with_its_line(tmp_path: Path) -> None:
    with pytest.raises(st.StyleError, match="line 2"):
        st.parse('spelling = "british"\nquotes = \n')


def test_saved_in_the_data_volume_and_round_trips(tmp_path: Path) -> None:
    rules = {"spelling": "british", "scene_break": "* * *", "watch": ["a beat", 'say "hi"']}
    st.save(tmp_path, "My Book", rules)
    assert st.load(tmp_path, "My Book") == rules
    assert list((tmp_path / "style").glob("*.toml"))
    assert st.load(tmp_path, "Another") == {}


# --- AC-8: rules ------------------------------------------------------------------------------


def test_spelling_british_reports_american_but_not_names_or_ambiguous_pairs() -> None:
    text = "The color of the gray sky. She will realize it at the Mercer Center. Practice and practise."
    assert sorted(hits({"spelling": "british"}, text)) == ["color"]
    r = run({"spelling": "british"}, [text])
    assert r["by_rule"][0]["rows"][0]["what"] == "color, gray, realize"


def test_spelling_oxford_takes_ize_and_american_reports_british() -> None:
    text = "She will realize the colour. They organised it."
    r = run({"spelling": "british-oxford"}, [text])
    assert r["by_rule"][0]["rows"][0]["what"] == "organised"
    r = run({"spelling": "american"}, [text])
    assert r["by_rule"][0]["rows"][0]["what"] == "colour, organised"


def test_quotes_curly_reports_straight_marks_and_apostrophes() -> None:
    r = run({"quotes": "double-curly"}, ['"Not tonight," he said. It’s late. It\'s late.'])
    assert r["by_rule"][0]["rows"][0]["what"] == "3 straight quotation marks"
    assert r["by_rule"][0]["total"] == 3


def test_quotes_nested_singles_and_elisions_are_not_reported() -> None:
    text = "\"She said 'go' to me,\" he said. 'Tis late, and 'em boys left in '67."
    assert rule_total({"quotes": "double-straight"}, text) == 0
    assert rule_total({"quotes": "double-straight"}, "'Go home,' she said.") == 1


def test_scene_break_rule_and_old_index() -> None:
    breaks = {1: [{"after": 1, "text": "* * *"}, {"after": 2, "text": "***"}]}
    r = run({"scene_break": "* * *"}, ["One.", "Two.", "Three."], breaks=breaks)
    rows = r["by_rule"][0]["rows"]
    assert [(x["paragraph"], x["text"], x["after"]) for x in rows] == [(2, "***", True)]
    old = st.report(st.check({"scene_break": "* * *"}, [], [], None))
    assert old["by_rule"][0]["unchecked"] == "Re-ingest to check scene breaks."


def test_chapter_heading_template_and_exemptions() -> None:
    titles = ["Chapter 1: Arrival", "Chapter Four", "Prologue", "Interlude II"]
    r = run(
        {"chapter_heading": "Chapter {n}: {title}"}, ["A."], ["B."], ["C."], ["D."], titles=titles
    )
    assert [x["text"] for x in r["by_rule"][0]["rows"]] == ["Chapter Four"]


def test_numbers_reports_numerals_but_not_times_dates_money_or_decimals() -> None:
    text = (
        "He walked 10 yards. At 9:30 on the 27th May 1867 it cost £5 and 2.5 per cent, "
        "or 40%, at 4 A.M. in 1867–1870."
    )
    assert hits({"numbers": "spell-under-100"}, text) == ["10"]
    assert hits({"numbers": "spell-under-10"}, text) == []
    assert rule_total({"numbers": "off"}, text) == 0


@pytest.mark.parametrize(
    ("setting", "text", "n"),
    [
        ("closed-em", "He went—slowly—home. A well-known man, 1867–1870.", 0),
        ("closed-em", "He went -- slowly -- home.", 2),
        ("double-hyphen", "He went--slowly--home.", 0),
        ("double-hyphen", "He went—slowly—home.", 2),
        ("spaced-en", "He went – slowly – home.", 0),
        ("spaced-em", "He went — slowly — home.", 0),
        ("spaced-em", "He went – slowly – home.", 2),
    ],
)
def test_dashes(setting: str, text: str, n: int) -> None:
    assert rule_total({"dash": setting}, text) == n


def test_ellipsis_forms() -> None:
    text = "Wait... Then… And . . . so."
    r = run({"ellipsis": "three-dots"}, [text])
    assert r["by_rule"][0]["total"] == 2


def test_watch_lists_every_use_and_not_in_the_manuscript() -> None:
    r = run({"watch": ["a beat", "orbs"]}, ["He waited a beat. Then A beat more."], ["A beat."])
    beat, orbs = r["watch"]
    assert beat["total"] == 3 and beat["chapters"] == {"1": 2, "2": 1}
    assert orbs["total"] == 0


def test_one_paragraph_with_several_mismatches_is_one_row() -> None:
    r = run({"quotes": "double-curly"}, ['"A," "b," "c."'])
    assert len(r["by_rule"][0]["rows"]) == 1 and r["by_rule"][0]["rows"][0]["count"] == 6


def test_clean_text_matches_the_house_style() -> None:
    rules = {"spelling": "british", "quotes": "double-straight", "dash": "closed-em",
             "ellipsis": "character", "numbers": "spell-under-100"}  # fmt: skip
    r = run(rules, ['"The colour was grey," she said—and waited…'])
    assert r["mismatches"] == 0 and r["checked"] == 5


def test_detect_finds_the_dominant_forms() -> None:
    cs = [
        Chapter(
            1, "Chapter 1", ['"The colour," she said--slowly... "Grey."', "The colour was grey."]
        )
    ]
    d = st.detect(cs, {1: [{"after": 1, "text": "* * *"}]})
    assert d["spelling"]["value"] == "british"
    assert d["quotes"]["value"] == "double-straight"
    assert d["dash"]["value"] == "double-hyphen"
    assert d["ellipsis"]["value"] == "three-dots"
    assert d["scene_break"]["value"] == "* * *"
    assert "scene_break" not in st.detect(cs, None)


def test_a_long_paragraph_is_fast() -> None:
    import time

    para = ("the colour -- of 5 things... 'and' \"the\" gray " * 600)[:20_000]
    rules = {"spelling": "british", "quotes": "double-curly", "dash": "closed-em",
             "ellipsis": "character", "numbers": "spell-under-100", "watch": ["the"]}  # fmt: skip
    started = time.perf_counter()
    run(rules, [para])
    assert time.perf_counter() - started < 1.0


# --- AC-15: the API ---------------------------------------------------------------------------


class MemoryIndex:
    def __init__(self, passages: list[ps.Passage], chapters: list[dict[str, Any]]) -> None:
        self.passages = passages
        self.chapters = chapters

    def stats(self) -> IndexStats:
        return IndexStats(
            "test", "the-book" if self.passages else None, self.chapters, len(self.passages)
        )

    def all_passages(self) -> list[ps.Passage]:
        return self.passages


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    s = Settings(data_dir=tmp_path)
    chapters = [
        Chapter(1, "Chapter 1", ['"Just so," he said. He nodded. He nodded again.', "The color was gray."],
                scene_breaks=[(1, "***")]),
        Chapter(2, "Chapter 2", ["She just nodded like a ghost and smiled. She smiled like a cat."]),
    ]  # fmt: skip
    passages = ps.split(
        ms.Manuscript("the-book", chapters), s.min_passage_words, s.max_passage_words
    )
    meta = ps.chapter_summary(chapters)
    monkeypatch.setattr(api, "index", lambda: MemoryIndex(passages, meta))
    monkeypatch.setattr(api, "settings", lambda: s)
    return TestClient(api.app)


def test_habits_endpoint_returns_counts_only_without_a_key(client: TestClient) -> None:
    r = client.get("/habits").json()
    nodded = next(h for k in r["kinds"] for h in k["habits"] if h["label"] == "nodded")
    assert nodded["total"] == 3 and nodded["chapters"] == {"1": 2, "2": 1}
    assert "instances" not in str(r)
    narr = client.get("/habits?narration=true").json()
    just = [h for k in narr["kinds"] for h in k["habits"] if h["label"] == "just"]
    # The minimum of 2 is on the whole manuscript; narration only then shows its 1.
    assert [h["total"] for h in just] == [1]


def test_instances_endpoint_pages_and_filters(client: TestClient) -> None:
    r = client.get("/habits/instances", params={"habit": "gestures:nodded", "limit": 2}).json()
    assert r["total"] == 3 and len(r["instances"]) == 2
    i = r["instances"][0]
    assert set(i) >= {
        "chapter",
        "label",
        "paragraph",
        "passage_id",
        "sentence",
        "match",
        "dialogue",
    }
    r2 = client.get("/habits/instances", params={"habit": "nodded", "chapter": 2}).json()
    assert r2["total"] == 1 and r2["instances"][0]["chapter"] == 2
    missing = client.get("/habits/instances", params={"habit": "nodd"})
    assert missing.status_code == 404 and "nodded" in missing.json()["error"]


def test_style_endpoints(client: TestClient) -> None:
    assert client.get("/style").json()["rules"] == {}
    bad = client.put("/style", json={"rules": {"quotes": "curly"}})
    assert bad.status_code == 422 and "double-curly" in bad.json()["error"]
    toml = client.put("/style", json={"toml": "spelling = \n"})
    assert toml.status_code == 422 and "line 1" in toml.json()["error"]
    ok = client.put("/style", json={"rules": {"spelling": "british", "scene_break": "* * *"}})
    assert ok.status_code == 200
    assert client.get("/style").json()["breaks_recorded"] is True
    m = client.get("/style/mismatches").json()
    by = {r["rule"]: r for r in m["by_rule"]}
    assert by["spelling"]["total"] == 2 and by["scene_break"]["rows"][0]["text"] == "***"
    d = client.get("/style/detect").json()["detected"]
    assert d["spelling"]["value"] == "american"


def test_empty_index_gives_the_existing_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "index", lambda: MemoryIndex([], []))
    c = TestClient(api.app)
    for path in ["/habits", "/style", "/style/mismatches"]:
        r = c.get(path)
        assert r.status_code == 409 and "Nothing is indexed yet" in r.json()["error"]


# --- Review fixes -----------------------------------------------------------------------------


def test_the_first_word_of_a_quotation_is_checked_for_spelling() -> None:
    assert hits({"spelling": "british"}, 'He said, "Color is all."') == ["Color"]


def test_detect_single_curly_quotes() -> None:
    cs = [Chapter(1, "Chapter 1", ["‘I don’t know,’ she said. ‘Nor I.’"])]
    assert st.detect(cs, None)["quotes"] == {
        "value": "single-curly",
        "share": 100,
        "of": "quotation marks",
    }


def test_an_elided_year_is_not_a_number_mismatch() -> None:
    assert rule_total({"numbers": "spell-under-100"}, "It was the summer of '67.") == 0


def test_nested_quote_check_is_linear() -> None:
    import time

    para = ('"a" ' * 4000)[:20_000]
    started = time.perf_counter()
    run({"quotes": "single-straight"}, [para])
    assert time.perf_counter() - started < 1.0


def test_unchecked_scene_breaks_arent_counted_as_checked() -> None:
    r = st.report(st.check({"scene_break": "* * *", "spelling": "british"}, [], [], None))
    assert r["checked"] == 1
