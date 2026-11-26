"""Habits report (spec 0007): deterministic patterns, counts, dialogue, grounding, limits."""

import re
import time
from pathlib import Path

import pytest

from margin import habits as hb
from margin import manuscript as ms
from margin import passages as ps
from margin import textspans as ts
from margin.config import DEMO_DIR, Settings
from margin.manuscript import Chapter
from margin.timeline import chapters_from_passages
from margin.verify import quote_in_passage

# Tiny texts: a phrase's chance rate is high, so the ratio bar is set low here.
S = Settings(habit_min_count=1, phrase_min_count=3, phrase_min_chapters=2, phrase_min_ratio=2)


def analyse(*chapters: list[str], s: Settings = S) -> hb.Analysis:
    cs = [
        Chapter(number=i + 1, title=f"Chapter {i + 1}", paragraphs=p)
        for i, p in enumerate(chapters)
    ]
    m = ms.Manuscript("test", cs)
    passages = ps.split(m, s.min_passage_words, s.max_passage_words)
    return hb.analyse("test", chapters_from_passages(passages), passages, s)


def found(text: str) -> list[tuple[str, str]]:
    """(habit label, matched text) for one paragraph."""
    a = analyse([text])
    out = []
    for h in a.habits:
        if h.kind == "phrases":
            continue
        for i in h.instances:
            out.append((h.label, text[i.start : i.end]))
    return out


def labels(text: str) -> set[str]:
    return {label for label, _ in found(text)}


# --- AC-2: kinds, with their near-misses ------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The lamps came on like a slow tide over the causeway.",
        "Her face was as pale as candle wax.",
    ],
)
def test_similes_match(text: str) -> None:
    assert labels(text) & {"like a …", "as … as …"}


@pytest.mark.parametrize(
    "text",
    [
        "I'd like a word with you.",
        "Would you like a cup of tea?",
        "She left as soon as she could.",
        "He took the coat as well as the hat.",
        "They walked as far as the bridge.",
        "It rained as much as it ever had.",
        "Stay as long as you need.",
    ],
)
def test_simile_near_misses_dont_match(text: str) -> None:
    assert not labels(text) & {"like a …", "as … as …"}


def test_as_if_and_as_though_but_not_though_alone() -> None:
    assert labels("He stared as if the wall had spoken.") >= {"as if"}
    assert labels("She was calm, as though nothing had happened.") >= {"as though"}
    assert "as though" not in labels("Though it rained, they walked.")


@pytest.mark.parametrize(
    ("text", "habit"),
    [
        ("He nodded.", "nodded"),
        ("She nods at the door.", "nodded"),
        ("Nodding, he left the room.", "nodded"),
        ("She bit her lip.", "bit lip"),
        ("He bit his lip and waited.", "bit lip"),
        ("His jaw tightened.", "jaw tightened"),
        ("Her jaw clenched at the word.", "jaw tightened"),
        ("He raised an eyebrow.", "raised an eyebrow"),
        ("She rolled her eyes.", "rolled eyes"),
        ("He ran a hand through his hair.", "ran a hand through hair"),
        ("Her heart pounded in the dark.", "heart pounded"),
        ("She let out a breath she didn't know she was holding.", "breath didn't know … holding"),
        ("He shrugged and turned away.", "shrugged"),
    ],
)
def test_gestures_match_any_inflection_and_pronoun(text: str, habit: str) -> None:
    assert habit in labels(text)


@pytest.mark.parametrize(
    "text",
    [
        "She looked at him with more than an aunt's smile.",
        "He gave a curt nod to the porter.",
        "With a sigh of relief the clerk sat.",
        "Her smile was brief.",
    ],
)
def test_gesture_nouns_dont_match(text: str) -> None:
    assert not {h for h in labels(text) if h in {"smiled", "nodded", "sighed"}}


@pytest.mark.parametrize(
    ("text", "habit"),
    [
        ("He felt profoundly thankful.", "felt"),
        ("She could hear the sea.", "heard"),
        ("He realized the door was open.", "realised"),
        ("She realised the door was open.", "realised"),
        ("The house seemed empty.", "seemed"),
    ],
)
def test_filter_verbs_match(text: str, habit: str) -> None:
    assert habit in labels(text)


@pytest.mark.parametrize(
    "text", ["He wore a felt hat.", "The saw lay on the bench.", "Seemed fine."]
)
def test_filter_verb_near_misses(text: str) -> None:
    assert not labels(text) & {"felt", "saw", "seemed"}


def test_crutch_words_but_not_adjectives() -> None:
    assert "just" in labels("Just behind her was his employer.")
    assert "very" in labels("It was very late.")
    assert "just" not in labels("He was a just man.")
    assert "very" not in labels("That was the very man.")


def test_runs_of_openers_and_ing_openers() -> None:
    assert "runs of the same first word" in labels("He went. He stopped. He listened.")
    assert "runs of the same first word" not in labels("He went. She stopped. He listened.")
    assert '"-ing" openers' in labels("Turning to the door, she listened.")
    for text in ["Nothing moved.", "Morning came.", "During the night, it snowed."]:
        assert '"-ing" openers' not in labels(text)


def test_matches_are_whole_word_and_case_insensitive() -> None:
    assert labels("LIKE A ghost, she passed.") >= {"like a …"}
    assert "just" not in labels("Justice was slow.")


# --- AC-3: repeated phrases -------------------------------------------------------------------


def test_repeated_phrase_with_pronoun_variants_across_chapters() -> None:
    a = analyse(
        ["Her jaw tightened over the salt marsh.", "The salt marsh was grey. His jaw tightened."],
        ["Her jaw tightened again over the salt marsh at dusk."],
        ["The gulls left the salt marsh."],
    )
    phrases = {h.label: h for h in a.habits if h.kind == "phrases"}
    assert "the salt marsh" in phrases
    # pronoun-folded: one phrase with variants; "her" is the most common form
    jaw = next(h for h in phrases.values() if "jaw tightened" in h.label)
    assert jaw.label.startswith("her") and any(f.startswith("his") for f, _ in jaw.variants)


def test_phrases_in_one_chapter_or_of_function_words_or_names_arent_reported() -> None:
    a = analyse(
        ["At the same time Mr Ashby said no. At the same time Mr Ashby said yes."],
        ["At the same time Mr Ashby said maybe. In front of the house it was cold."],
        ["The green lantern swung. The green lantern swung. The green lantern swung."],
    )
    labels_ = {h.label for h in a.habits if h.kind == "phrases"}
    assert not any("same time" in x or "ashby" in x or "front of" in x for x in labels_)
    assert not any("green lantern" in x for x in labels_)  # one chapter only


def test_shorter_phrase_folds_into_longer_one() -> None:
    para = "She sat on the edge of the bed and waited."
    a = analyse([para], [para], [para])
    labels_ = [h.label for h in a.habits if h.kind == "phrases"]
    assert any("edge of the bed" in x for x in labels_)
    assert "the edge of the" not in labels_


# --- AC-4: counts and dialogue ----------------------------------------------------------------


def test_dialogue_flag_including_a_quotation_that_runs_on() -> None:
    a = analyse(
        [
            '"I just wanted to go," she said. He just went.',
            '"It was really late,',
            '"and really dark," said Ann.',
        ]
    )
    just = next(h for h in a.habits if h.label == "just")
    assert [i.dialogue for i in just.instances] == [True, False]
    really = next(h for h in a.habits if h.label == "really")
    assert all(i.dialogue for i in really.instances)


def test_report_totals_rates_and_narration_toggle() -> None:
    a = analyse(['"Just so," he said. Just then it rained.'] * 2, ["It was just fine."])
    r = hb.report(a)
    crutch = next(k for k in r["kinds"] if k["kind"] == "crutch")
    just = next(h for h in crutch["habits"] if h["label"] == "just")
    assert just["total"] == 5 and just["narration"] == 3
    assert just["chapters"] == {"1": 4, "2": 1}
    assert just["rate"] == round(5 / r["words"] * 1000, 2)
    narr = hb.report(a, narration=True)
    just_n = next(h for k in narr["kinds"] for h in k["habits"] if h["label"] == "just")
    assert just_n["total"] == 3


def test_habits_found_fewer_than_min_count_are_left_out() -> None:
    a = analyse(["He nodded. She smiled. She smiled again."], s=Settings())
    assert {h.label for h in a.habits} == {"smiled"}


def test_none_found_is_a_result() -> None:
    a = analyse(["The rain fell on the roofs of the town."], s=Settings())
    r = hb.report(a)
    assert not r["found"] and all(k["habits"] == [] for k in r["kinds"])


# --- AC-5: every instance is an exact, verified span ------------------------------------------


@pytest.fixture(scope="module")
def demo() -> tuple[hb.Analysis, list[ps.Passage]]:
    s = Settings()
    m = ms.load(DEMO_DIR)
    passages = ps.split(m, s.min_passage_words, s.max_passage_words)
    return hb.analyse(m.name, chapters_from_passages(passages), passages, s), passages


def test_every_demo_instance_is_an_exact_span_of_its_stored_passage(demo: tuple) -> None:
    a, passages = demo
    by_id = {p.id: p for p in passages}
    assert a.failed == 0
    n = 0
    for h in a.habits:
        page = hb.instances(a, h.id, limit=10_000)
        assert page is not None
        for row in page["instances"]:
            p = by_id[row["passage_id"]]
            assert row["text"] in p.text
            s, e = row["match"]
            assert row["sentence"][s:e] == row["text"]
            assert quote_in_passage(row["text"], p.text, 1)
            n += 1
    assert n > 500


def test_long_sentences_are_trimmed_around_the_match() -> None:
    words = " ".join(f"w{i}" for i in range(100))
    a = analyse([f"{words} as if {words}."])
    page = hb.instances(a, "as_if:as if")
    assert page is not None
    row = page["instances"][0]
    assert row["sentence"].startswith("… ") and row["sentence"].endswith(" …")
    s, e = row["match"]
    assert row["sentence"][s:e] == "as if"
    assert len(row["sentence"].split()) <= 64


# --- AC-6: never prose, never a verdict ------------------------------------------------------

VERDICT = re.compile(r"\b(bad|weak|overused|too many|avoid|instead|consider|try)\b", re.I)


def _strings(path: Path) -> list[str]:
    text = path.read_text()
    return re.findall(r'"([^"\n]*)"|`([^`\n]*)`|\'([^\'\n]*)\'', text)


@pytest.mark.parametrize(
    "path",
    ["src/margin/habits.py", "src/margin/style.py", "src/margin/cli.py"],
)
def test_report_strings_have_no_verdict_words(path: str) -> None:
    root = Path(__file__).parent.parent
    for groups in _strings(root / path):
        for s in groups:
            assert not VERDICT.search(s), s


def test_page_habits_strings_have_no_verdict_words() -> None:
    root = Path(__file__).parent.parent / "src/margin/web"
    js = (root / "app.js").read_text()
    section = js[js.index("// --- Habits and house style") : js.index("// --- Wiring")]
    html = (root / "index.html").read_text()
    view = html[html.index('id="view-habits"') : html.index("<!-- Progress -->")]
    texts = re.findall(r'"([^"\n]*)"|`([^`\n]*)`', section) + re.findall(r">([^<>]+)<", view)
    for t in texts:
        for x in t if isinstance(t, tuple) else (t,):
            assert not VERDICT.search(x), x


def test_rate_shading_is_neutral_not_red() -> None:
    css = (Path(__file__).parent.parent / "src/margin/web/app.css").read_text()
    rule = css[css.index(".strip button {") :].split("}")[0]
    assert "--ink" in rule and "--accent" not in rule


# --- AC-14: limits ----------------------------------------------------------------------------


def test_a_long_paragraph_with_no_punctuation_is_fast() -> None:
    para = ("the lamp and the road like a river as if the night " * 1700)[:20_000]
    started = time.perf_counter()
    analyse([para], [para[:5000]])
    assert time.perf_counter() - started < 1.0


def test_sentences_handle_abbreviations_and_quotes() -> None:
    text = 'Mr. Ashby left. "Wait!" she said. It rained.'
    got = [text[s.start : s.end] for s in ts.sentences(text)]
    assert got == ["Mr. Ashby left.", '"Wait!" she said.', "It rained."]


def test_cache_returns_the_same_analysis_until_the_text_changes(demo: tuple) -> None:
    _, passages = demo
    s = Settings()
    chapters = chapters_from_passages(passages)
    first = hb.cached("the-card", chapters, passages, s)
    assert hb.cached("the-card", chapters, passages, s) is first
    changed = [*passages[:-1], ps.Passage(**{**passages[-1].__dict__, "text": "Changed."})]
    assert hb.cached("the-card", chapters_from_passages(changed), changed, s) is not first


# --- Review fixes -----------------------------------------------------------------------------


def test_an_elision_or_stray_quote_doesnt_make_narration_dialogue() -> None:
    a = analyse(["She told ‘em to leave and he nodded.", "He nodded at the door."])
    nodded = next(h for h in a.habits if h.label == "nodded")
    assert [i.dialogue for i in nodded.instances] == [False, False]
    a = analyse(['"It was late, he said and nodded.', "He nodded at the door."])
    nodded = next(h for h in a.habits if h.label == "nodded")
    assert nodded.instances[1].dialogue is False


@pytest.mark.parametrize(
    "text",
    [
        "He gave notice on Friday.",
        "They kept watch all night.",
        "Pens and watch-cases lay on the counter.",
        "It was a thing of wonder to them.",
    ],
)
def test_filter_verb_nouns_dont_match(text: str) -> None:
    assert not labels(text) & {"noticed", "watched", "wondered"}


@pytest.mark.parametrize(
    "text",
    ["They'll see us.", "Let them see us.", "You can't hear a thing.", "I never notice it."],
)
def test_filter_verb_base_forms_match_as_verbs(text: str) -> None:
    assert labels(text) & {"saw", "heard", "noticed"}


@pytest.mark.parametrize(
    "text", ["Something that just happened.", "What just happened?", "That just isn't true."]
)
def test_just_after_that_or_what_is_the_adverb(text: str) -> None:
    assert "just" in labels(text)
